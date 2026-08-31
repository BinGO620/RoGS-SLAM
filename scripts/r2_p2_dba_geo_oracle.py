#!/usr/bin/env python3
"""P2-DBAphoto step2 — reliability-weighted GEOMETRIC oracle (the real gate).

WHY. Codex review 019fc47b established that the DBA geometric edge (_edge_two_sided,
dba_lite.py:179) has ONLY residual-MAD robust weight, NEVER the online reliability
weight -> the genuinely-missing, NON-redundant term is reliability-weighted GEOMETRY
(photo-BA + reliability is redundant: online static_conf=(1-w) already weights
l1_rgb+l1_depth, slam_utils.py:447/471/475). This script answers the gate question:

  As KF poses interpolate online(t=0) -> GT(t=1) along the SE(3) geodesic, does the
  reliability-weighted masked point-to-plane geometric residual DECREASE (esp. near
  t=0)?  Yes + initial direction descends -> weighted-geo objective prefers GT -> build
  the joint solver (v0).  Still rises -> close the door (third mechanism finding:
  geometric AND weighted-geometric both prefer online on these short no-loop masked
  seqs), tracking stays at P2-T.

POST-HOC: consumes the exact-online w_map snapshots from step1 (r2_p2_dba_stash.py) +
dataset depth/mask + per-frame GT poses. Does NOT re-run slam.py, does NOT need the PLY.

codex 019fc6be (second adversarial review) — 8 issues, ALL adopted:
  FATAL-1 gauge: raw TUM GT is not in the online KF0 frame. Independently interpolating
    every absolute pose (incl KF0) introduces a gauge-dependent artificial path. FIX:
    rigidly align GT to online at KF0 (Tgt'_k = Tgt_k @ inv(Tgt_0) @ Ton_0, W2C), keep
    KF0 fixed for all t.
  FATAL-2 changing correspondences/support across t makes costs non-comparable; a "GO"
    can result from rejecting hard pixels, not reducing residuals. FIX: PRIMARY metric
    = fixed-support sweep (t=0 inlier set + edge set + denominator FROZEN across t);
    report the dynamic-support solver cost separately, require both to agree.
  FATAL-3 the proposed S=(C(.05)-C(0))/C(0) is NOT the GN initial-direction test (GN at
    t=0 holds correspondence + MAD weight + reliability weight fixed while forming its
    local quadratic). FIX: primary initial-direction = fixed-support fixed-weight
    directional derivative g0^T d_GT (frozen-weight GN objective along the GT twist).
  IMP-4 frozen w_map image field is correct (no GT leakage), but w_j=grid_sample(wgrid_j,
    u(T),v(T)) is pose-dependent; GT may look better because projections move into
    lower-weight pixels. FIX: primary sweep freezes target w on the t=0 correspondences;
    pose-dependent w is a sensitivity diagnostic.
  IMP-5 run_dba_v0 acceptance cost includes an online-centered pose prior (dba_lite.py:702)
    that necessarily favors t=0; a geometric GO != the configured solver prefers GT. FIX:
    pre-declare the future solver as lm_prior=0 (geometry-only); primary sweep excludes
    the prior. A second sweep with the configured prior is a diagnostic.
  IMP-6 verdict logic must require BOTH increments (0->.02 and .02->.05) to descend for
    GO, and non-descent for KILL, else INCONCLUSIVE.
  IMP-7 KF-block bootstrap is conditional, not a 4-run generalization CI (adjacent blocks
    share target KFs, temporally correlated). FIX: contiguous KF blocks (len > max
    edge offset), report PER-RUN CIs, treat 3/4 same-direction as the cross-run gate.
  NIT-8 KF0 w=1 is not clearly no-harm; KF0 is only the source of (0,1),(0,2),(0,5).
    FIX: primary verdict EXCLUDES KF0 edges; KF0-edge w=1 is a sensitivity result.

Phases
------
  python scripts/r2_p2_dba_geo_oracle.py --phase dry       # print the plan, no GPU
  python scripts/r2_p2_dba_geo_oracle.py --phase run       # 4 runs, ~10-15min GPU
  python scripts/r2_p2_dba_geo_oracle.py --phase report    # no GPU — bootstrap + verdict
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config
from utils.coarse_pose import _se3_exp
from utils.dba_lite import (
    _attach_weight_to_geom,
    _build_edges,
    _cam_center,
    _edge_dynamic_cost,
    _edge_two_sided,
    _edge_weighted_resid_at_t,
    _edge_weighted_resid_fixed,
    _precompute_kf_geom,
    _project_source,
    _se3_log,
)
from utils.logging_utils import Log
from utils.semantic_mask import compute_semantic_dynamic_mask, semantic_mask_enabled

PY = "/data/conda_envs/monogs-ours/bin/python"
STASH_ROOT = "results/runs/P2/P2-DBA-STASH"
RESULTS_JSONL = "p2dba_geo_oracle_results.jsonl"
REPORT_JSON = "p2dba_geo_oracle_report.json"
T_GRID = [0.0, 0.02, 0.05, 0.1, 0.2, 0.5, 0.75, 1.0]
PRACTICAL_MARGIN = 0.02  # <2% drop OR CI crossing 0 = INCONCLUSIVE (codex hard req #4)
BOOTSTRAP_B = 2000
KF_BLOCK_LEN = 6  # > max edge offset (5), codex IMP-7

# 4 runs (codex: >=2 seq x 2 seed). tags match r2_p2_dba_stash.py.
RUNS = [
    {"tag": "balloon_prune_dbastash_seed0", "seq": "balloon", "seed": 0,
     "cfg_subdir": "p2s_combined_prune_dba_stash_balloon"},
    {"tag": "balloon_prune_dbastash_seed1", "seq": "balloon", "seed": 1,
     "cfg_subdir": "p2s_combined_prune_dba_stash_balloon"},
    {"tag": "mv_no_box_prune_dbastash_seed0", "seq": "mv_no_box", "seed": 0,
     "cfg_subdir": "p2s_combined_prune_dba_stash_mv_no_box"},
    {"tag": "mv_no_box_prune_dbastash_seed1", "seq": "mv_no_box", "seed": 1,
     "cfg_subdir": "p2s_combined_prune_dba_stash_mv_no_box"},
]


def _find_run_dir(tag):
    """Find the dated run dir under STASH_ROOT/<tag>/datasets_bonn/<cfg>/seed_<s>/<date>/."""
    base = os.path.join(STASH_ROOT, tag, "datasets_bonn")
    # cfg_subdir known; seed dir; date dir
    for run in RUNS:
        if run["tag"] == tag:
            cfg_sub = run["cfg_subdir"]
            for seed_dir in sorted(glob.glob(os.path.join(base, cfg_sub, "seed_*"))):
                for date_dir in sorted(glob.glob(os.path.join(seed_dir, "20*"))):
                    if os.path.isdir(date_dir):
                        return date_dir
            return None
    return None


def _load_run_meta(run):
    run_dir = _find_run_dir(run["tag"])
    if run_dir is None:
        return None
    trj_path = os.path.join(run_dir, "plot", "trj_final.json")
    cfg_path = os.path.join(run_dir, "config.yml")
    snap_dir = os.path.join(run_dir, "dba_weight_snapshots")
    if not (os.path.isfile(trj_path) and os.path.isfile(cfg_path) and os.path.isdir(snap_dir)):
        return None
    return {"run_dir": run_dir, "trj_path": trj_path, "cfg_path": cfg_path,
            "snap_dir": snap_dir}


def _mask_cache_path(snap_dir, stem):
    """Person-mask cache (pose-independent, deterministic; reuse across seeds)."""
    return os.path.join(snap_dir, "..", "mask_cache", f"{stem}_mask.pt")


def _load_person_mask(config, snap_dir, stem, rgb, device):
    """Mask R-CNN person mask, cached per (seq, dataset idx) — pose-independent so seeds
    share it (codex: deterministic; avoids 2x Mask R-CNN cost). Returns (H,W) bool or None."""
    cache = _mask_cache_path(snap_dir, stem)
    if os.path.isfile(cache):
        try:
            m = torch.load(cache, map_location=device)
            return m.to(device).bool()
        except Exception:
            pass
    if not semantic_mask_enabled(config):
        return None
    m = compute_semantic_dynamic_mask(config, rgb)  # (1,H,W) bool or None
    if m is not None:
        m = m.squeeze(0)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        try:
            torch.save(m.cpu(), cache)
        except Exception:
            pass
    return m


def _build_geom_for_kf(kf_idx, dataset, config, snap_dir, cfg_dba, device, w_cache):
    """Load depth+RGB+mask for a KF dataset index, precompute geom, attach stashed w.

    Returns (geom, w_full) or (None, None) if the KF has no usable geometry.
    KF0 (idx 0) has no snapshot -> w_full=None -> _attach_weight_to_geom uses ones (only
    used in the KF0-edge sensitivity sweep; primary verdict excludes KF0 edges)."""
    try:
        gt_color, gt_depth, _ = dataset[kf_idx]
    except Exception:
        return None, None
    if gt_depth is None:
        return None, None
    depth = torch.as_tensor(gt_depth).to(device).float()
    if depth.dim() == 3:
        depth = depth.squeeze(0)
    stem = os.path.splitext(os.path.basename(dataset.depth_paths[kf_idx]))[0]
    mask = _load_person_mask(config, snap_dir, stem, gt_color, device)
    geom = _precompute_kf_geom(
        depth, mask, float(dataset.fx), float(dataset.fy),
        float(dataset.cx), float(dataset.cy), cfg_dba, device,
    )
    # stashed w
    w_full = None
    if kf_idx in w_cache:
        w_full = w_cache[kf_idx]
    else:
        wpath = os.path.join(snap_dir, f"{stem}_w.npy")
        if os.path.isfile(wpath):
            w_full = torch.as_tensor(np.load(wpath)).to(device).float()
            w_cache[kf_idx] = w_full
    _attach_weight_to_geom(geom, w_full, cfg_dba)
    return geom, w_full


def _gauge_align_gt(T_on, T_gt_raw, kfs):
    """codex FATAL-1: align GT to online at KF0 in W2C.
    Tgt'_k = Tgt_k @ inv(Tgt_0) @ Ton_0 ; KF0 fixed = Ton_0 for all t."""
    k0 = kfs[0]
    Tgt0_inv = torch.linalg.inv(T_gt_raw[k0])
    Ton0 = T_on[k0]
    T_gt = {}
    for k in kfs:
        T_gt[k] = T_gt_raw[k] @ Tgt0_inv @ Ton0
    T_gt[k0] = Ton0.clone()  # KF0 gauge-fixed
    return T_gt


def _pose_at(t, kfs, T_on, xi):
    return {k: _se3_exp(t * xi[k]) @ T_on[k] for k in kfs}


def _agg_fixed_cost(t, kfs, T_on, xi, edges, geom_states, geom, cfg_dba, device,
                    include_kf0=False):
    """Aggregate FIXED-support reliability-weighted cost at interpolation t.

    geom_states[(i,j)] = (state, N_fixed) from the t=0 call. Re-evaluates r(t) on the
    frozen m0 set with frozen w_total0; cost = sum_edges sum_m0(w_total0 * r(t)^2)/N_fixed.
    Returns (cost, n_edges, per_edge_costs) where n_edges is the FIXED edge count (constant
    across t by construction -- codex 019fc738 FATAL-1/FATAL-2 fix). per_edge_costs is a list
    ALIGNED with `edges` (same order; edges not in geom_states get a 0.0 placeholder) so that
    t=0 and t=1 lists are pairable by EDGE IDENTITY, not list position."""
    Tt = _pose_at(t, kfs, T_on, xi)
    total = 0.0
    per_edge = []
    n_active = 0
    for (i, j) in edges:
        if not include_kf0 and (i == kfs[0]):
            per_edge.append(0.0)
            continue
        key = (i, j)
        if key not in geom_states:
            per_edge.append(0.0)
            continue
        state, N_fixed = geom_states[key]
        rt = _edge_weighted_resid_at_t(state, geom[i], geom[j], Tt[i], Tt[j], cfg_dba, device)
        if rt is None:
            per_edge.append(0.0)
            continue
        r_t, _, _, w_total0, _ = rt
        we = w_total0 / max(N_fixed, 1)
        c = float((we * r_t * r_t).sum())
        total += c
        per_edge.append(c)
        n_active += 1
    return total, n_active, per_edge


def _dir_deriv(kfs, T_on, xi, edges, geom_states, geom, cfg_dba, device):
    """codex FATAL-3: fixed-support fixed-weight directional derivative g0^T d_GT.

    At t=0 (frozen correspondence + frozen w_total0), the GN gradient is g0 = J^T (w r);
    the GT twist is d_GT = sum_k xi[k] over free KFs. dir_deriv = g0 . d_GT.
    <0 = the frozen-weight GN linearization descends toward GT. Aggregated over edges
    (free KF blocks of J contribute; KF0 is gauge-fixed -> its block is zero)."""
    free = [k for k in kfs if k != kfs[0]]
    # free KF index in the stacked 6-vector
    col = {k: i for i, k in enumerate(free)}
    g = torch.zeros(6 * len(free), dtype=torch.float32, device=device)
    Tt = _pose_at(0.0, kfs, T_on, xi)
    for (i, j) in edges:
        if i == kfs[0] and j == kfs[0]:
            continue
        key = (i, j)
        if key not in geom_states:
            continue
        state, N_fixed = geom_states[key]
        # at t=0: r0, J_i, J_j, w_total0 (frozen)
        res0 = state.get("res0")
        if res0 is None:
            continue
        r0, J_i, J_j, w_total0 = res0
        we = w_total0 / max(N_fixed, 1)
        wr = we * r0
        if i in col:
            bi = col[i]
            g[6 * bi:6 * bi + 6] += J_i.T @ wr
        if j in col:
            bj = col[j]
            g[6 * bj:6 * bj + 6] += J_j.T @ wr
    d_gt = torch.zeros(6 * len(free), dtype=torch.float32, device=device)
    for k in free:
        bi = col[k]
        d_gt[6 * bi:6 * bi + 6] = xi[k]
    return float((g * d_gt).sum().item())


def _agg_dynamic_cost(t, kfs, T_on, xi, edges, geom, cfg_dba, device, include_kf0=False):
    """Diagnostic: the REAL solver opt_cost (dynamic support, reweighted) at t.
    codex FATAL-2: must AGREE in direction with the fixed-support metric for a GO.
    per_edge_costs is ALIGNED with `edges` (same order; None/0.0 placeholder) so t=0/t=1
    are pairable by edge identity (codex 019fc738 FATAL-2 fix)."""
    Tt = _pose_at(t, kfs, T_on, xi)
    total = 0.0
    per_edge = []
    n_active = 0
    for (i, j) in edges:
        if not include_kf0 and (i == kfs[0]):
            per_edge.append(0.0)
            continue
        out = _edge_dynamic_cost(geom[i], geom[j], Tt[i], Tt[j], cfg_dba, device)
        if out is None:
            per_edge.append(0.0)
            continue
        c, n, _ = out
        total += c
        per_edge.append(c)
        n_active += 1
    return total, n_active, per_edge


def _ate_proxy(Tt, T_gt, kfs):
    """Camera-center RMSE vs GT (cm), gauge-shared at KF0 (codex FATAL-1: KF0 fixed)."""
    d = [float(torch.norm(_cam_center(Tt[k]) - _cam_center(T_gt[k]))) for k in kfs]
    return (sum(x * x for x in d) / len(d)) ** 0.5 * 100.0


def _gn_test_phase(run, meta, config, cfg_dba, dataset, kf_ids, est, gt, device, max_iters=5):
    """Minimal reliability-weighted GN/LM test (codex 019fc738 next-step).

    Run a few accepted Gauss-Newton steps on the reliability-weighted geometric objective
    (lm_prior=0, geometry-only), starting from the ONLINE poses. Each step:
      * build the stacked Hessian H (6*n_free) and gradient g from ALL edges (KF0 gauge-fixed),
        with the reliability-weighted two-sided residual + Jacobian (dynamic IRLS: inlier set
        + MAD weight + reliability weight recomputed at the current pose each step -- this is
        what the real solver does, the dynamic-support objective).
      * solve dx = -(H + lam*I)^-1 g, step, accept only if the dynamic cost drops.
    Log per-iter: dynamic acceptance cost + GT-only ATE (camera-center RMSE vs GT, gauge-
    shared at KF0). The verdict:
      * consistent ATE decrease across runs -> GO to a solver spike.
      * cost drops but ATE flat/worse, or improvement stalls after a negligible step -> KILL.
      * instability / seed split -> INCONCLUSIVE.
    """
    # W2C poses + gauge align GT
    T_on = {kf_ids[k]: torch.linalg.inv(torch.tensor(est[k], dtype=torch.float32, device=device))
            for k in range(len(kf_ids))}
    T_gt_raw = {kf_ids[k]: torch.linalg.inv(torch.tensor(gt[k], dtype=torch.float32, device=device))
                 for k in range(len(kf_ids))}
    T_gt = _gauge_align_gt(T_on, T_gt_raw, kf_ids)

    geom = {}
    w_cache = {}
    for k in kf_ids:
        g, _ = _build_geom_for_kf(k, dataset, config, meta["snap_dir"], cfg_dba, device, w_cache)
        if g is not None and g["Ps"].shape[0] >= int(cfg_dba.get("min_points", 500)):
            geom[k] = g
    kfs = [k for k in kf_ids if k in geom]
    if len(kfs) < 3:
        return {"tag": run["tag"], "status": "no_geom"}
    fixed = kfs[0]
    free = [k for k in kfs if k != fixed]
    col = {k: i for i, k in enumerate(free)}
    n_free = len(free)
    offsets = [int(o) for o in cfg_dba.get("opt_offsets", [1, 2, 5])]
    edges = _build_edges(kfs, offsets)
    eye = torch.eye(6 * n_free, dtype=torch.float32, device=device)

    T = {k: T_on[k].clone() for k in kfs}

    def dynamic_cost_and_grad(Tcur):
        c = 0.0
        H = torch.zeros(6 * n_free, 6 * n_free, dtype=torch.float32, device=device)
        g = torch.zeros(6 * n_free, dtype=torch.float32, device=device)
        for (i, j) in edges:
            res = _edge_two_sided(geom[i], geom[j], Tcur[i], Tcur[j], cfg_dba, device)
            if res is None:
                continue
            r, J_i, J_j, w_robust = res
            # dynamic reliability weight (re-sample w_j at the dynamic inlier locations)
            proj = _project_source(geom[i], geom[j], Tcur[i], Tcur[j], cfg_dba, device)
            if proj is None:
                continue
            m = proj["m"]
            w_src = geom[i].get("w_src")
            if w_src is not None and w_src.shape[0] == proj["Pi"].shape[0]:
                w_i_m = w_src[m]
            else:
                w_i_m = torch.ones_like(r)
            w_j = F.grid_sample(geom[j]["wgrid"], proj["grid"], align_corners=True,
                                padding_mode="zeros")[0, 0, 0]
            n = min(w_i_m.shape[0], w_j.shape[0], r.shape[0])
            w_i_m = w_i_m[:n]; w_j_m = w_j[m][:n]; r_ = r[:n]
            J_i = J_i[:n]; J_j = J_j[:n]; w_robust = w_robust[:n]
            w_rel = torch.sqrt(w_i_m.clamp(min=1e-6) * w_j_m.clamp(min=1e-6))
            w_total = (w_robust * w_rel)
            we = w_total / max(n, 1)
            c += float((we * r_ * r_).sum())
            wr = we * r_
            blocks = []
            if i != fixed:
                blocks.append((col[i], J_i))
            if j != fixed:
                blocks.append((col[j], J_j))
            for bi, Jb in blocks:
                g[6 * bi:6 * bi + 6] += Jb.T @ wr
                Jbw = Jb * we[:, None]
                for bj, Jc in blocks:
                    H[6 * bi:6 * bi + 6, 6 * bj:6 * bj + 6] += Jbw.T @ Jc
        return c, H, g

    def gt_ate(Tcur):
        d = [float(torch.norm(_cam_center(Tcur[k]) - _cam_center(T_gt[k]))) for k in kfs]
        return (sum(x * x for x in d) / len(d)) ** 0.5 * 100.0

    def snap_c2w(Tcur):
        """Per-iter KF poses as C2W (same convention as trj_final.json ``trj_est``),
        so the offline Umeyama readout can feed them to the headline ATE protocol
        (codex 019fc7e1 next-step: the 85-98cm KF0-gauge number is not comparable
        to the 2.6-3.0cm headline ATE)."""
        return [torch.linalg.inv(Tcur[k]).detach().cpu().numpy().tolist() for k in kfs]

    rows = []
    pose_snaps = []
    c0, H0, g0 = dynamic_cost_and_grad(T)
    ate0 = gt_ate(T)
    rows.append({"iter": 0, "cost": c0, "ate_gt_cm": ate0,
                 "accepted": True, "grad_norm": float(torch.norm(g0).item())})
    pose_snaps.append({"iter": 0, "poses_c2w": snap_c2w(T)})
    lam = 1e-3
    for it in range(1, max_iters + 1):
        c_cur = rows[-1]["cost"]
        H = rows[-1] if False else None
        c_cur, H, g = dynamic_cost_and_grad(T)
        try:
            dx = -torch.linalg.solve(H + lam * eye, g)
        except Exception:
            lam = min(lam * 4, 1e3)
            rows.append({"iter": it, "cost": c_cur, "ate_gt_cm": gt_ate(T),
                         "accepted": False, "grad_norm": float(torch.norm(g).item()),
                         "note": "solve_fail"})
            pose_snaps.append({"iter": it, "poses_c2w": snap_c2w(T)})
            continue
        dstep = float(dx.norm())
        Tn = dict(T)
        for k in free:
            Tn[k] = _se3_exp(dx[6 * col[k]:6 * col[k] + 6]) @ T[k]
        c_new, _, _ = dynamic_cost_and_grad(Tn)
        if c_new < c_cur:
            T = Tn
            lam = max(lam * 0.5, 1e-6)
            rows.append({"iter": it, "cost": c_new, "ate_gt_cm": gt_ate(T),
                         "accepted": True, "step_norm": dstep,
                         "grad_norm": float(torch.norm(g).item())})
        else:
            lam = min(lam * 4, 1e3)
            rows.append({"iter": it, "cost": c_cur, "ate_gt_cm": gt_ate(T),
                         "accepted": False, "step_norm": dstep,
                         "grad_norm": float(torch.norm(g).item()),
                         "note": "rejected_cost_rose"})
        pose_snaps.append({"iter": it, "poses_c2w": snap_c2w(T)})
    # ate deltas
    ate_first = rows[0]["ate_gt_cm"]
    ate_last = rows[-1]["ate_gt_cm"]
    cost_first = rows[0]["cost"]
    cost_last = rows[-1]["cost"]
    return {"tag": run["tag"], "seq": run["seq"], "seed": run["seed"],
            "n_kfs": len(kfs), "n_edges": len(edges), "rows": rows,
            "kfs": [int(k) for k in kfs], "pose_snaps": pose_snaps,
            "ate_gt_t0_cm": ate_first, "ate_gt_tlast_cm": ate_last,
            "cost_t0": cost_first, "cost_tlast": cost_last,
            "ate_delta_cm": ate_last - ate_first,
            "cost_ratio": cost_last / max(cost_first, 1e-12),
            "n_accepted": sum(1 for r in rows if r["accepted"]) - 1,  # exclude iter0
            "ate_online_cm": None}  # filled by caller


def run_one(run, dry=False):
    meta = _load_run_meta(run)
    if meta is None:
        print(f"  [{run['tag']}] SKIP — no stash/trj/config found")
        return {"tag": run["tag"], "status": "missing_data"}
    if dry:
        trj = json.load(open(meta["trj_path"]))
        n_kf = len(trj["trj_id"])
        n_snaps = len([f for f in os.listdir(meta["snap_dir"]) if f.endswith("_w.npy")])
        print(f"  [{run['tag']}] KFs={n_kf} snaps={n_snaps} cfg={os.path.basename(meta['cfg_path'])}")
        return {"tag": run["tag"], "n_kf": n_kf, "n_snaps": n_snaps, "status": "dry"}

    device = "cuda"
    config = load_config(meta["cfg_path"])
    cfg_dba = config.get("DBALite", {})
    # minimal dataset for depth+RGB by index
    from utils.dataset import load_dataset
    dataset = load_dataset(None, None, config)

    trj = json.load(open(meta["trj_path"]))
    kf_ids = [int(k) for k in trj["trj_id"]]
    est = np.array(trj["trj_est"])  # c2w
    gt = np.array(trj["trj_gt"])

    # W2C poses
    T_on = {kf_ids[k]: torch.linalg.inv(torch.tensor(est[k], dtype=torch.float32, device=device))
            for k in range(len(kf_ids))}
    T_gt_raw = {kf_ids[k]: torch.linalg.inv(torch.tensor(gt[k], dtype=torch.float32, device=device))
                 for k in range(len(kf_ids))}
    T_gt = _gauge_align_gt(T_on, T_gt_raw, kf_ids)
    xi = {k: _se3_log(T_gt[k] @ torch.linalg.inv(T_on[k])) for k in kf_ids}

    # build geom for every KF (KF0 w=None)
    geom = {}
    w_cache = {}
    for k in kf_ids:
        g, _ = _build_geom_for_kf(k, dataset, config, meta["snap_dir"], cfg_dba, device, w_cache)
        if g is not None and g["Ps"].shape[0] >= int(cfg_dba.get("min_points", 500)):
            geom[k] = g
    kfs = [k for k in kf_ids if k in geom]
    if len(kfs) < 3:
        print(f"  [{run['tag']}] SKIP — <3 KFs with usable geometry")
        return {"tag": run["tag"], "status": "no_geom"}

    # edges: offsets [1,2,5] (DBALite.opt_offsets); primary verdict EXCLUDES KF0-src edges.
    # EDGE LIST IS FROZEN across the t-sweep (codex 019fc738 FATAL-2): per_edge arrays are
    # aligned to this list by position, so t=0/t=1 pair by edge identity, NOT by survival.
    offsets = [int(o) for o in cfg_dba.get("opt_offsets", [1, 2, 5])]
    edges_all = []
    for a in range(len(kfs)):
        for off in offsets:
            b = a + off
            if b < len(kfs):
                edges_all.append((kfs[a], kfs[b]))
    edges = [e for e in edges_all if e[0] != kfs[0]]  # primary: exclude KF0-src (NIT-8)

    # t=0 frozen-support states (FATAL-2/FATAL-3). Record which edges HAD valid t=0 geometry
    # so gt_better / bootstrap only consider edges present at both t=0 and t=1.
    Tt0 = _pose_at(0.0, kfs, T_on, xi)
    geom_states = {}
    valid_edges = []
    for (i, j) in edges:
        res = _edge_weighted_resid_fixed(geom[i], geom[j], Tt0[i], Tt0[j], cfg_dba, device)
        if res is None:
            continue
        (r0, J_i, J_j, w_total0, m0, N_fixed), state = res
        state["res0"] = (r0, J_i, J_j, w_total0)  # for directional derivative
        geom_states[(i, j)] = (state, N_fixed)
        valid_edges.append((i, j))

    # sweep t over the FIXED edge list `edges` (codex 019fc738 FATAL-2). per_edge arrays
    # are aligned to `edges` by position; 0.0 placeholders for edges with no t=0 geometry.
    rows_fixed = []
    rows_dyn = []
    for t in T_GRID:
        cf, na_f, pe_f = _agg_fixed_cost(t, kfs, T_on, xi, edges, geom_states, geom,
                                         cfg_dba, device, include_kf0=False)
        cd, na_d, pe_d = _agg_dynamic_cost(t, kfs, T_on, xi, edges, geom,
                                           cfg_dba, device, include_kf0=False)
        Tt = _pose_at(t, kfs, T_on, xi)
        ate = _ate_proxy(Tt, T_gt, kfs)
        rows_fixed.append({"t": t, "cost": cf, "n_edges": na_f, "ate_proxy_cm": ate,
                           "per_edge": pe_f})
        rows_dyn.append({"t": t, "cost": cd, "n_edges": na_d, "per_edge": pe_d})
    # pair by edge identity: only edges valid at BOTH t=0 and t=1
    pe0 = rows_fixed[0]["per_edge"]
    pe1 = rows_fixed[-1]["per_edge"]
    valid_mask = [e in geom_states for e in edges]
    per_edge_t0 = [pe0[idx] for idx in range(len(edges)) if valid_mask[idx]]
    per_edge_t1 = [pe1[idx] for idx in range(len(edges)) if valid_mask[idx]]

    # directional derivative (FATAL-3)
    dd = _dir_deriv(kfs, T_on, xi, edges, geom_states, geom, cfg_dba, device)

    # KF0-edge sensitivity (NIT-8): same sweep including KF0-src edges
    edges_kf0 = [e for e in edges_all if e[0] == kfs[0]]
    rows_kf0 = []
    if edges_kf0:
        gs_kf0 = {}
        for (i, j) in edges_kf0:
            res = _edge_weighted_resid_fixed(geom[i], geom[j], Tt0[i], Tt0[j], cfg_dba, device)
            if res is None:
                continue
            (r0, J_i, J_j, w_total0, m0, N_fixed), state = res
            state["res0"] = (r0, J_i, J_j, w_total0)
            gs_kf0[(i, j)] = (state, N_fixed)
        for t in T_GRID:
            cf, na, _ = _agg_fixed_cost(t, kfs, T_on, xi, edges_kf0, gs_kf0, geom,
                                        cfg_dba, device, include_kf0=True)
            rows_kf0.append({"t": t, "cost": cf, "n_edges": na})

    # per-edge GT-better (t=1 < t=0)
    gt_better = on_better = 0
    for k in range(min(len(per_edge_t0), len(per_edge_t1))):
        if per_edge_t1[k] < per_edge_t0[k]:
            gt_better += 1
        else:
            on_better += 1

    # online ATE
    ate_online = None
    try:
        trj_csv = os.path.join(meta["run_dir"], "tracking_raw.csv")
        if os.path.isfile(trj_csv):
            with open(trj_csv) as f:
                r = list(csv.DictReader(f))
            if r:
                ate_online = float(r[0].get("ate_rmse_cm"))
    except Exception:
        pass

    result = {
        "tag": run["tag"], "seq": run["seq"], "seed": run["seed"],
        "run_dir": meta["run_dir"], "n_kfs": len(kfs), "n_edges": len(edges),
        "n_edges_valid_t0": len(valid_edges),
        "n_edges_active_t0": rows_fixed[0]["n_edges"],
        "valid_edge_mask": [e in geom_states for e in edges],
        "t_grid": T_GRID,
        "rows_fixed": rows_fixed,
        "rows_dynamic": rows_dyn,
        "rows_kf0_sensitivity": rows_kf0,
        "dir_deriv": dd,
        "gt_better": gt_better, "on_better": on_better,
        "ate_online_cm": ate_online,
        "ate_proxy_t0_cm": rows_fixed[0]["ate_proxy_cm"],
        "ate_proxy_t1_cm": rows_fixed[-1]["ate_proxy_cm"],
        "R_fixed": rows_fixed[-1]["cost"] / max(rows_fixed[0]["cost"], 1e-12),
        "R_dynamic": rows_dyn[-1]["cost"] / max(rows_dyn[0]["cost"], 1e-12),
        "delta1_fixed": rows_fixed[1]["cost"] - rows_fixed[0]["cost"],  # C(.02)-C(0)
        "delta2_fixed": rows_fixed[2]["cost"] - rows_fixed[1]["cost"],  # C(.05)-C(.02)
    }
    out_path = os.path.join(meta["run_dir"], "dba_geo_oracle_result.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    with open(os.path.join(STASH_ROOT, RESULTS_JSONL), "a") as f:
        f.write(json.dumps(result) + "\n")
    print(f"  [{run['tag']}] R_fixed={result['R_fixed']:.4f} R_dyn={result['R_dynamic']:.4f} "
          f"dir_deriv={dd:.4g} gt_better={gt_better}/{gt_better+on_better} "
          f"ate_online={ate_online}", flush=True)
    return result


def _bootstrap_ci(per_edge_t0, per_edge_t1, B=BOOTSTRAP_B):
    """Nonparametric bootstrap on R = sum(t1)/sum(t0) over EDGES (pairable, both t present).

    codex 019fc738 FATAL-2 fix: the two lists are ALIGNED by edge identity (same order,
    equal length — only edges valid at BOTH t=0 and t=1 are passed in). The prior code
    chunked sequential edge-list positions and called it "KF-block" but edges are NOT
    grouped by KF in the list, so that was not a KF block. A plain per-edge bootstrap
    (resample edges with replacement) is the honest conditional CI here; we report it as
    conditional (per-run), not a 4-run generalization CI (codex IMP-7: only 4 runs,
    edges temporally correlated -> no population-level inference)."""
    n = len(per_edge_t0)
    if n < 6 or len(per_edge_t1) != n:
        return (float("nan"), float("nan"))
    rng = np.random.RandomState(0)
    s0 = float(sum(per_edge_t0))
    if s0 <= 0:
        return (float("nan"), float("nan"))
    rs = []
    for _ in range(B):
        idx = rng.randint(0, n, size=n)
        num = sum(per_edge_t1[k] for k in idx)
        den = sum(per_edge_t0[k] for k in idx)
        if den > 0:
            rs.append(num / den)
    if not rs:
        return (float("nan"), float("nan"))
    lo, hi = np.percentile(rs, [2.5, 97.5])
    return (float(lo), float(hi))


def _gn_report(path):
    """Verdict for the minimal weighted-GN step test (codex 019fc738 next-step).

    Per-run: did the reliability-weighted GN (lm_prior=0, dynamic IRLS) lower the GT-ATE?
      * consistent ATE decrease -> GO to a solver spike.
      * cost drops but ATE flat/worse, or stalls after a negligible step -> KILL.
      * instability / seed split -> INCONCLUSIVE.
    """
    if not os.path.isfile(path):
        print("no gn runs yet")
        return 1
    with open(path) as f:
        records = [json.loads(line) for line in f if line.strip()]
    records = [r for r in records if "rows" in r]
    if not records:
        print("no completed gn runs")
        return 1
    print("\n=== DBAphoto step2: minimal reliability-weighted GN step test ===\n")
    print(f"  lm_prior=0, 5 LM iters, dynamic IRLS (inlier+MAD+w_rel recomputed each step)")
    print(f"  metric: does GN from the ONLINE pose lower GT-ATE (camera-center RMSE vs GT)?\n")
    print(f"{'run':<32} {'cost_r':>7} {'ate_t0':>7} {'ate_t5':>7} {'Δate':>8} {'accept':>7}")
    print("-" * 78)
    go = kill = incl = 0
    for r in records:
        # ATE decrease (better) = negative delta; < -0.1cm and cost_ratio<1 = useful
        ate_drop = -r["ate_delta_cm"]  # positive = ATE improved
        cost_drop = 1.0 - r["cost_ratio"]  # positive = cost improved
        cond_go = ate_drop > 0.1 and cost_drop > 0.0 and r["n_accepted"] >= 1
        cond_kill = (cost_drop <= 0.0 and r["n_accepted"] == 0) or (
            ate_drop <= 0.0 and r["n_accepted"] <= 1)
        if cond_go:
            go += 1
        elif cond_kill:
            kill += 1
        else:
            incl += 1
        print(f"{r['tag']:<32} {r['cost_ratio']:>7.4f} {r['ate_gt_t0_cm']:>7.2f} "
              f"{r['ate_gt_tlast_cm']:>7.2f} {r['ate_delta_cm']:>+8.3f} "
              f"{r['n_accepted']}/5")
    print("\nper-iter trace (balloon s0):")
    r0 = records[0]
    for row in r0["rows"]:
        acc = "accept" if row.get("accepted") else "reject"
        print(f"  iter {row['iter']}: cost={row['cost']:.4f} ate_gt={row['ate_gt_cm']:.3f}cm "
              f"grad={row.get('grad_norm', 0):.4g} {acc} {row.get('note', '')}")
    n = len(records)
    thresh = max(2, (3 * n + 3) // 4)
    if go >= thresh:
        verdict = "GO"; reason = f"{go}/{n} runs: GN lowers GT-ATE >0.1cm with cost drop -> solver spike"
    elif kill >= thresh:
        verdict = "KILL"; reason = (f"{kill}/{n} runs: cost does not drop / no accepted step / "
                                     f"ATE does not improve -> close the door; tracking stays P2-T")
    else:
        verdict = "INCONCLUSIVE"; reason = (f"go={go}/{n} kill={kill}/{n} incl={incl}/{n} -> "
                                             f"mixed: cost may drop but ATE flat/worse, or stalls")
    print(f"\nVERDICT: {verdict}\n  {reason}")
    rep = {"verdict": verdict, "reason": reason, "n_runs": n,
           "go": go, "kill": kill, "incl": incl,
           "per_run": [{"tag": r["tag"], "cost_ratio": r["cost_ratio"],
                        "ate_gt_t0_cm": r["ate_gt_t0_cm"],
                        "ate_gt_tlast_cm": r["ate_gt_tlast_cm"],
                        "ate_delta_cm": r["ate_delta_cm"],
                        "n_accepted": r["n_accepted"],
                        "ate_online_cm": r.get("ate_online_cm")}
                       for r in records]}
    with open(os.path.join(STASH_ROOT, "p2dba_geo_gn_report.json"), "w") as f:
        json.dump(rep, f, indent=2)
    print(f"\nreport -> {os.path.join(STASH_ROOT, 'p2dba_geo_gn_report.json')}")
    return 0


def report():
    path = os.path.join(STASH_ROOT, RESULTS_JSONL)
    if not os.path.isfile(path):
        print("no runs yet")
        return 1
    with open(path) as f:
        records = [json.loads(line) for line in f if line.strip()]
    records = [r for r in records if "R_fixed" in r]
    if not records:
        print("no completed runs")
        return 1

    print("\n=== DBAphoto step2: reliability-weighted GEOMETRIC oracle ===\n")
    print(f"metric: fixed-support sum(w_robust0*w_rel0*r(t)^2)/N_fixed  (codex 019fc6be FATAL-2/3)")
    print(f"t-grid: {T_GRID}   margin: {PRACTICAL_MARGIN}   bootstrap B={BOOTSTRAP_B} (per-run CI)\n")
    print(f"{'run':<32} {'R_fix':>7} {'R_dyn':>7} {'d1':>8} {'d2':>8} {'dd':>9} {'gt+':>5} {'ate':>6}")
    print("-" * 105)
    per_run_ci = []
    for r in records:
        # pair by edge identity: only edges valid at BOTH t=0 and t=1
        pe0_all = r["rows_fixed"][0]["per_edge"]
        pe1_all = r["rows_fixed"][-1]["per_edge"]
        valid = r.get("valid_edge_mask", [True] * min(len(pe0_all), len(pe1_all)))
        pe0 = [pe0_all[idx] for idx in range(len(valid)) if valid[idx] and idx < len(pe0_all)]
        pe1 = [pe1_all[idx] for idx in range(len(valid)) if valid[idx] and idx < len(pe1_all)]
        ci = _bootstrap_ci(pe0, pe1)
        per_run_ci.append(ci)
        print(f"{r['tag']:<32} {r['R_fixed']:>7.4f} {r['R_dynamic']:>7.4f} "
              f"{r['delta1_fixed']:>8.2g} {r['delta2_fixed']:>8.2g} "
              f"{r['dir_deriv']:>9.3g} "
              f"{r['gt_better']:>3}/{r['gt_better']+r['on_better']:<3} "
              f"{str(r.get('ate_online_cm')):>6}")
    print("\nper-run 95% CI on R_fixed (per-edge bootstrap, conditional):")
    for r, (lo, hi) in zip(records, per_run_ci):
        print(f"  {r['tag']:<32} R=[{lo:.4f}, {hi:.4f}]")

    # verdict (codex 019fc738 FATAL-3 fix: KILL must ALSO respect the dynamic + dir_deriv
    # evidence; a negative GN directional derivative precludes a clean "no local descent" KILL)
    go_runs = 0
    kill_runs = 0
    incl_runs = 0
    for r, (lo, hi) in zip(records, per_run_ci):
        # GO: fixed-support drops >2% with BOTH increments descending, CI<1, dir_deriv<0,
        # AND the dynamic solver objective ALSO drops (FATAL-2 selection-bias guard)
        cond_go = (r["R_fixed"] < 1 - PRACTICAL_MARGIN
                   and r["delta1_fixed"] < 0 and r["delta2_fixed"] < 0
                   and r["dir_deriv"] < 0 and hi < 1.0
                   and r["R_dynamic"] < 1.0)
        # KILL: fixed-support non-descending (both increments >=0) with CI>=1, AND the
        # dynamic objective does NOT drop near t=0 (R_dynamic>=1), AND dir_deriv>=0
        # (no local descent). If dir_deriv<0 (local descent exists) or dynamic drops, it
        # is NOT a clean KILL -> INCONCLUSIVE (shallow-basin).
        cond_kill = (r["delta1_fixed"] >= 0 and r["delta2_fixed"] >= 0
                     and lo >= 1.0 - 1e-9
                     and r["R_dynamic"] >= 1.0 and r["dir_deriv"] >= 0)
        if cond_go:
            go_runs += 1
        elif cond_kill:
            kill_runs += 1
        else:
            incl_runs += 1
    n = len(records)
    thresh = max(2, (3 * n + 3) // 4)  # >=3/4
    if go_runs >= thresh:
        verdict = "GO"
        reason = (f"{go_runs}/{n} runs: fixed R<0.98, both increments descend, dir_deriv<0, "
                  f"CI<1, AND dynamic objective drops -> build the joint solver (v0)")
    elif kill_runs >= thresh:
        verdict = "KILL"
        reason = (f"{kill_runs}/{n} runs: fixed non-descending, CI>=1, dynamic>=1, "
                  f"dir_deriv>=0 -> close the door; tracking stays at P2-T")
    else:
        verdict = "INCONCLUSIVE"
        reason = (f"go={go_runs}/{n} kill={kill_runs}/{n} incl={incl_runs}/{n} -> "
                  f"fixed vs dynamic/dir_deriv disagree (shallow-basin signal): "
                  f"GT locally but not globally preferred; the weighted-geo objective "
                  f"cannot carry optimization from 3cm to 1.5cm -> NOT a clean build, "
                  f"NOT a clean close; recommend a minimal weighted-GN step test next")

    print(f"\nVERDICT: {verdict}\n  {reason}")

    rep = {"verdict": verdict, "reason": reason, "n_runs": n,
           "go_runs": go_runs, "kill_runs": kill_runs,
           "margin": PRACTICAL_MARGIN, "t_grid": T_GRID,
           "per_run": [{"tag": r["tag"], "R_fixed": r["R_fixed"],
                         "R_dynamic": r["R_dynamic"], "dir_deriv": r["dir_deriv"],
                         "delta1": r["delta1_fixed"], "delta2": r["delta2_fixed"],
                         "ci_R": per_run_ci[i],
                         "gt_better": r["gt_better"],
                         "ate_online_cm": r.get("ate_online_cm")}
                        for i, r in enumerate(records)]}
    with open(os.path.join(STASH_ROOT, REPORT_JSON), "w") as f:
        json.dump(rep, f, indent=2)
    print(f"\nreport -> {os.path.join(STASH_ROOT, REPORT_JSON)}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--phase", choices=["dry", "run", "gn", "report"], default="dry")
    args = parser.parse_args()
    if args.phase == "dry":
        print("=== DBAphoto step2 plan: reliability-weighted geometric oracle ===")
        print(f"  {len(RUNS)} runs, t-grid={T_GRID}, margin={PRACTICAL_MARGIN}, B={BOOTSTRAP_B}")
        for run in RUNS:
            run_one(run, dry=True)
        print("\n  primary metric: fixed-support squared-robust-weighted geometry (codex 019fc6be)")
        print("  directional derivative g0.d_GT for the GN initial-direction test (FATAL-3)")
        return 0
    if args.phase == "run":
        os.makedirs(STASH_ROOT, exist_ok=True)
        started = time.time()
        for run in RUNS:
            run_one(run, dry=False)
        print(f"\nrun phase: {(time.time()-started)/60:.1f}min")
        return report()
    if args.phase == "gn":
        # Minimal reliability-weighted GN step test (codex 019fc738 next-step).
        os.makedirs(STASH_ROOT, exist_ok=True)
        gn_results = os.path.join(STASH_ROOT, "p2dba_geo_gn_results.jsonl")
        if os.path.isfile(gn_results):
            os.remove(gn_results)
        started = time.time()
        for run in RUNS:
            meta = _load_run_meta(run)
            if meta is None:
                print(f"  [{run['tag']}] SKIP — no stash/trj/config")
                continue
            config = load_config(meta["cfg_path"])
            cfg_dba = config.get("DBALite", {})
            from utils.dataset import load_dataset
            dataset = load_dataset(None, None, config)
            trj = json.load(open(meta["trj_path"]))
            kf_ids = [int(k) for k in trj["trj_id"]]
            est = np.array(trj["trj_est"])
            gt = np.array(trj["trj_gt"])
            res = _gn_test_phase(run, meta, config, cfg_dba, dataset, kf_ids, est, gt,
                                 device="cuda", max_iters=5)
            # fill online ATE
            try:
                trj_csv = os.path.join(meta["run_dir"], "tracking_raw.csv")
                if os.path.isfile(trj_csv):
                    with open(trj_csv) as f:
                        rr = list(csv.DictReader(f))
                    if rr:
                        res["ate_online_cm"] = float(rr[0].get("ate_rmse_cm"))
            except Exception:
                pass
            # Per-iter KF poses go to their own file (keeps the jsonl readable); the
            # offline Umeyama readout (scripts/r2_p2_dba_gn_umeyama.py) consumes them.
            snaps = res.pop("pose_snaps", None)
            kfs_out = res.pop("kfs", None)
            if snaps is not None:
                pose_path = os.path.join(STASH_ROOT, f"gn_poses_{run['tag']}.json")
                with open(pose_path, "w") as f:
                    json.dump({"tag": run["tag"], "seq": run["seq"], "seed": run["seed"],
                               "kfs": kfs_out, "run_dir": meta["run_dir"],
                               "iters": snaps}, f)
                res["pose_file"] = pose_path
            with open(gn_results, "a") as f:
                f.write(json.dumps(res) + "\n")
            print(f"  [{run['tag']}] cost_ratio={res['cost_ratio']:.4f} "
                  f"ate_gt {res['ate_gt_t0_cm']:.2f}->{res['ate_gt_tlast_cm']:.2f}cm "
                  f"(Δ={res['ate_delta_cm']:+.3f}) accepted={res['n_accepted']}/5", flush=True)
        print(f"\ngn phase: {(time.time()-started)/60:.1f}min")
        return _gn_report(gn_results)
    if args.phase == "report":
        return report()


if __name__ == "__main__":
    sys.exit(main())
