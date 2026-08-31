#!/usr/bin/env python3
"""Stage 0 zero-GPU probe for observation-contradicted eviction.

WHY THIS EXISTS. Before proposing to EVICT live Gaussians that obstruct observed
free space in an anti-dynamic static-3DGS RGB-D SLAM, we must show the phenomenon
exists at all. The claim under test (CONTEXT.md 2026-08-05): an all-opaque map of
a swept dynamic region leaves baked-in Gaussians that block rays to the revealed
background, and these are the natural eviction targets. The earlier admission
arms (prune / deferred) could not see this because admission control is the wrong
tool once pollution is already in the map (background_reveal : foreground_conflict
= 1.7-3.8x).

This probe measures four things per frame, re-rendering the SAVED final map
(final_after_opt PLY + trj_full_final est poses) — the exact path r2_p2_t_offline_
render.py already uses. ZERO live-code changes, ZERO GPU training:

  1. free-space violation pixel ratio V   (render depth < observed - band, band =
     max(0.05, 0.02*z); render opacity >= 0.5; observed valid; NOT semantic-masked)
  2. geometry of the violation region      (contiguous blocks vs thin fringes:
     connected-component stats of V)
  3. candidate Gaussian opacity histogram  (opacity of Gaussians whose projected
     center sits at a violation pixel with center-depth also in front)
  4. spatial overlap vs frozen GTMC masks  (precision/recall vs the CURRENT dynamic
     mask AND vs the VACATED union = (union of past masks) \\ current mask — the
     real eviction target per the codex adversarial review, because swept ghosts
     live in vacated region, NOT current mask)

READOUT / DEATH RULES (pre-registered, CONTEXT.md):
  * mean v_ratio over sampled frames < 0.01  => no free-space violation => path dead.
  * candidate opacity p90 < 0.5               => selectable Gaussians are low-opacity
    floaters, carving them won't change the render => path dead.
  * overlap concentrated in VACATED region    => eviction is "erase swept ghosts" —
    proceed to Stage 1 online read-only probe.
  * many candidates but NOT in vacated region => generic map redundancy => pivot
    narrative to map compression.

WHY VACATED-UNION IS THE OVERLAP TARGET (codex round F3). The mechanism evicts
Gaussians blocking rays to REVEALED background — i.e. where a mover WAS but is not
NOW. That region is by construction the complement of the CURRENT dynamic mask, so
scoring overlap against the current mask systematically under-counts the target.
We report BOTH (current-mask overlap as a diagnostic for still-visible movers;
vacated-union overlap as the real kill-support readout).

Evidence sampling gate (per the proposal): a violation pixel is a valid evidence
pixel only when reliability flow-consensus says the pixel is trustworthy (flow_valid
with sufficient K-frame coverage) AND the pixel is not under the frozen dynamic
mask. flow_valid is NOT persisted per frame (only fv_map on the viewpoint at
tracking time), so we RECOMPUTE the flow-consensus map from the frozen per-depth
RAFT flow (flow_raft/*.npy, one per frame) using the SAME kframe_consensus() used
online. This keeps the gate faithful to the online signal without re-running SLAM.

OUTPUTS per run dir (default: <run>/stage0_eviction/):
  stage0_eviction_readout.csv    one row per sampled frame (see cols below)
  summary.json                   aggregate verdict fields (means over frames)
  never touches the run's files.

Usage:
  python scripts/stage0_eviction_probe.py RUN_DIR [RUN_DIR ...] [--interval 5]
      [--band-abs 0.05 --band-rel 0.02] [--min-render-op 0.5]
      [--sample-mode {kf,full}] [--flow-kframes 5]
"""
import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# small bbox/geometry helpers (pure numpy, no torch dependency for stats)
# ---------------------------------------------------------------------------


def _bwlabel_ratio(mask, min_area=3):
    """Largest-connected-component coverage of a bool image.

    Returns (n_components, n_large, n_large_px, largest_frac_of_mask). Thin
    fringes -> many singleton labels, small largest_frac; contiguous blocks ->
    one big label.
    """
    from scipy import ndimage

    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return 0, 0, 0, 0.0
    lab, n = ndimage.label(m)
    if n == 0:
        return 0, 0, 0, 0.0
    counts = np.bincount(lab.ravel(), minlength=n + 1)
    counts[0] = 0
    sizes = np.sort(counts[1 : n + 1])[::-1]
    n_large = int((sizes >= min_area).sum())
    n_large_px = int(sizes[sizes >= min_area].sum())
    n_px = int(m.sum())
    return int(n), n_large, n_large_px, float(n_large_px / max(n_px, 1))


# ---------------------------------------------------------------------------
# flow_valid recomputation (gate mirror of utils/reliability_signal.py)
# ---------------------------------------------------------------------------


def _flow_anomaly_map(flow_t, flow_paths_t, cam, frame_idx):
    """Per-pixel flow-anomaly + flow_valid for the CURRENT frame, recomputed from
    frozen RAFT flow using the same K-frame consensus as the online signal.

    Returns (anomaly (H,W) float32, flow_valid (H,W) bool, coverage (H,W)).
    ``frame_idx`` is the dataset index; ``flow_paths_t`` maps dataset index ->
    flow npy path. Pixels with an invalid current-frame flow are invalid.
    """
    import cv2
    import torch
    from utils.reliability_signal import kframe_consensus

    H, W = flow_t.shape[:2]
    us = torch.from_numpy(np.meshgrid(np.arange(W, dtype=np.float32),
                                      np.arange(H, dtype=np.float32))[0])
    vs = torch.from_numpy(np.meshgrid(np.arange(W, dtype=np.float32),
                                      np.arange(H, dtype=np.float32))[1])
    cur_flow = torch.from_numpy(flow_t).float().unsqueeze(0)  # (1,H,W,2)
    cur_flow_finite = torch.isfinite(cur_flow).all(dim=-1)
    stack = []
    for off in (-2, -1, 1, 2):
        j = frame_idx + off
        p = flow_paths_t.get(j)
        if p is None:
            continue
        fj = torch.from_numpy(np.load(p)).float()  # (H,W,2)
        fj_finite = torch.isfinite(fj).all(dim=-1)
        # backward warp of fj to current frame centre (non-valid -> NaN)
        u = us + cur_flow[0, :, :, 0]
        v = vs + cur_flow[0, :, :, 1]
        mapx = u.numpy().astype(np.float32)
        mapy = v.numpy().astype(np.float32)
        warped = cv2.remap(fj.numpy(), mapx, mapy, cv2.INTER_LINEAR, borderValue=np.nan)
        warped = torch.from_numpy(warped)  # (H,W,2)
        ok = cur_flow_finite[0].to("cpu") & fj_finite & torch.isfinite(warped).all(dim=-1)
        wf = torch.where(ok[..., None], warped, torch.full_like(warped, float("nan")))
        stack.append(wf)
    if not stack:
        return np.zeros((H, W), np.float32), np.zeros((H, W), bool), np.zeros((H, W), np.float32)
    st = torch.stack(stack, dim=0)  # (K,H,W,2)
    delta = ((st - cur_flow) ** 2).sum(dim=-1).clamp_min(0.0).sqrt()
    valid = torch.isfinite(delta)
    e_flow, fv = kframe_consensus(delta, valid)  # (H,W) anomaly, flow_valid
    fv = fv.numpy()
    e = np.nan_to_num(e_flow.numpy(), nan=0.0)
    cov = valid.sum(dim=0).numpy().astype(np.float32)
    return e.astype(np.float32), fv.astype(bool), cov


# ---------------------------------------------------------------------------
# main per-run probe
# ---------------------------------------------------------------------------


def probe_run(run_dir, cfg, interval, band_abs, band_rel, min_render_op, sample_mode,
              flow_kframes, out_name="stage0_eviction", no_flow_gate=False):
    import cv2
    import torch
    from munch import munchify

    from gaussian_splatting.gaussian_renderer import render
    from gaussian_splatting.scene.gaussian_model import GaussianModel
    from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
    from utils.camera_utils import Camera
    from utils.dataset import load_dataset

    model_params = munchify(cfg["model_params"])
    model_params.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    dataset = load_dataset(model_params, model_params.source_path, config=cfg)

    ply = os.path.join(run_dir, "point_cloud", "final_after_opt", "point_cloud.ply")
    trj_path = os.path.join(run_dir, "plot", "trj_full_final.json")
    for p, nm in ((ply, "PLY"), (trj_path, "trj_full_final.json")):
        if not os.path.isfile(p):
            raise FileNotFoundError(f"missing {nm}: {p}")

    gaussians = GaussianModel(model_params.sh_degree, config=cfg)
    gaussians.load_ply(ply)
    N = int(gaussians.get_xyz.shape[0])

    with open(trj_path, "r", encoding="utf-8") as f:
        trj = json.load(f)
    pose_by_id = {
        int(fid): np.asarray(c2w, dtype=np.float64)
        for fid, c2w in zip(trj["trj_id"], trj["trj_est"])
    }
    frame_ids = sorted(pose_by_id.keys())

    projection_matrix = (
        getProjectionMatrix2(
            znear=0.01, zfar=100.0,
            fx=dataset.fx, fy=dataset.fy, cx=dataset.cx, cy=dataset.cy,
            W=dataset.width, H=dataset.height,
        )
        .transpose(0, 1)
        .to(device=dataset.device)
    )
    background = torch.tensor([0, 0, 0], dtype=torch.float32, device="cuda")

    # frozen GTMC masks keyed by depth stem
    subdir = cfg["Results"].get("static_bg_mask_subdir")
    mask_dir = os.path.join(cfg["Dataset"]["dataset_path"], subdir) if subdir else ""
    mask_by_stem = {}
    if mask_dir and os.path.isdir(mask_dir):
        from utils.gtmc_mask import frozen_mask_index, load_frozen_mask
        idx = frozen_mask_index(mask_dir)
        mask_by_stem = {s: os.path.abspath(p) for s, p in idx.items()}
    depth_stem_by_idx = [
        os.path.splitext(os.path.basename(dp))[0] for dp in dataset.depth_paths
    ]

    # frozen RAFT flow keyed by dataset frame index (depth pair index)
    flow_dir = os.path.join(cfg["Dataset"]["dataset_path"],
                            cfg.get("ReliabilitySignal", {}).get("flow_subdir", "flow_raft"))
    flow_by_stem = {}
    if os.path.isdir(flow_dir):
        for fn in sorted(os.listdir(flow_dir)):
            if fn.endswith(".npy"):
                flow_by_stem[os.path.splitext(fn)[0]] = os.path.join(flow_dir, fn)
    flow_by_idx = {
        i: flow_by_stem[s] for i, s in enumerate(depth_stem_by_idx) if s in flow_by_stem
    }

    sampled = [i for i in frame_ids if i % interval == 0 and i < len(depth_stem_by_idx)
               and depth_stem_by_idx[i] in mask_by_stem]

    rows = []
    for k, fid in enumerate(sampled):
        if fid >= len(dataset.depth_paths):
            continue
        stem = depth_stem_by_idx[fid]
        if stem not in mask_by_stem:
            continue
        c2w = pose_by_id[fid]
        rot = np.linalg.inv(c2w)[:3, :3]
        t = np.linalg.inv(c2w)[:3, 3]
        cam = Camera(
            int(fid), None, None, torch.eye(4, device=dataset.device),
            projection_matrix, dataset.fx, dataset.fy, dataset.cx, dataset.cy,
            dataset.fovx, dataset.fovy, dataset.height, dataset.width,
            device=dataset.device,
        )
        cam.update_RT(
            torch.from_numpy(np.ascontiguousarray(rot)).float(),
            torch.from_numpy(np.ascontiguousarray(t)).float(),
        )
        cam.cam_rot_delta = None
        cam.cam_trans_delta = None
        cam.exposure_a = None
        cam.exposure_b = None

        gt_image, gt_depth_raw, _ = dataset[fid]
        gt_depth = _undistort_depth_like(dataset, gt_depth_raw)  # (H,W) m, torch->np
        render_pkg = render(cam, gaussians, munchify(cfg["pipeline_params"]), background)
        r_depth_raw = render_pkg["depth"].detach().cpu().numpy().squeeze()
        r_op = render_pkg["opacity"].detach().cpu().numpy().squeeze()  # = 1 - T (accumulated)
        del cam

        # ---- NORMALIZED depth (rasterizer FIX) ----
        # forward.cu:367 accumulates D += depth[j]*alpha*T WITHOUT dividing by the
        # accumulated opacity (1-T). So on any semi-transparent pixel the raw render
        # depth is artificially SHALLOW (weighted sum of surface depths × partial
        # opacity). A free-space-violation detector fed the raw depth reads pervasive
        # fake violations wherever opacity < ~1 — which is most of the map (map median
        # sigmoid opacity ~0.52, not the ~0.99 CONTEXT quoted for the opaque tail).
        # Normalize: depth_norm = D / (1-T) = alpha-weighted mean of contributing depths.
        # This is the codex-specified disambiguation: only a real opaque surface in
        # front of observed GT depth produces a violation; semi-transparency no longer
        # fakes one. Where accumulated opacity is ~0 the division is meaningless and we
        # gate those pixels out via r_op >= min_render_op below.
        r_op_safe = np.maximum(r_op, 1e-6)
        r_depth = r_depth_raw / r_op_safe  # (H,W) alpha-normalized mean surface depth

        dyn = _load_mask(mask_by_stem[stem])
        valid_obs = np.isfinite(gt_depth) & (gt_depth > 0.01) & (gt_depth <= 15.0)
        valid_render = np.isfinite(r_depth) & np.isfinite(r_op)
        valid_obs_r = valid_obs & valid_render

        band = np.clip(band_abs + band_rel * gt_depth, 1e-6, None)
        violation = valid_obs_r & (r_depth < (gt_depth - band)) & (r_op >= min_render_op)
        violation = violation & (~dyn)  # semantic/frozen-dynamic mask exclusion

        # vacated union up to this frame (past masks minus current) as np bool
        vacated = _load_vacated_union(mask_by_stem, depth_stem_by_idx, fid)

        # flow anomaly + flow_valid (gate mirror). --no-flow-gate skips entirely.
        had_flow = (not no_flow_gate) and (fid in flow_by_idx)
        fv = None
        if had_flow:
            ft = np.load(flow_by_idx[fid])
            e, fv, cov = _flow_anomaly_map(ft, flow_by_idx, cam=None, frame_idx=fid)

        # violation pixels that pass the flow_valid gate (default: no gate if no flow)
        gated = violation if fv is None else (violation & fv)

        # ---- columns ----
        n_obs = int(valid_obs_r.sum())
        v_all = int(violation.sum())
        v_gated = int(gated.sum())

        # connected-component geometry of the ENTIRE violation (ungated) — blocks vs fringes
        n_cc, n_cc_large, n_cc_large_px, largest_frac = _bwlabel_ratio(violation)

        # vacated-region share of violation (the real eviction target)
        v_vacated = int((violation & vacated).sum()) if vacated is not None else 0

        # ---- vac_excess (codex disambiguation (a)) ----
        # Base-rate control: violence rate inside the vacuumed (swept) region VS the
        # never-dynamic static control (pixels never under any mask, boundary-eroded to
        # drop the mover silhouette fringe). The CONTROL is the same valid/pixel-space
        # set, so a positive excess = swept ghosts really are the violation source,
        # whereas a ~0 excess means the detector is reading global pose/opacity bias.
        if vacated is not None:
            from scipy import ndimage
            never_dyn = np.zeros_like(dyn)
            for j in range(min(fid + 1, len(depth_stem_by_idx))):
                s = depth_stem_by_idx[j]
                pp = mask_by_stem.get(s)
                if pp is None:
                    continue
                never_dyn |= _load_mask(pp)
            never_dyn = (~never_dyn) & (~ndimage.binary_dilation(never_dyn, iterations=4))
            # control = never-dynamic ∧ valid ∧ render-valid (already in valid_obs_r ∧ ~dyn)
            control = never_dyn & valid_obs_r & (~dyn)
            p_v_vac = (v_vacated / max(int((vacated & valid_obs_r & (~dyn)).sum()), 1)) if v_vacated else 0.0
            p_v_ctrl = (int((violation & control).sum()) / max(int(control.sum()), 1)) if int(control.sum()) else 0.0
            vac_excess = float(p_v_vac - p_v_ctrl)
        else:
            vac_excess = float("nan")

        # candidate Gaussians: center projects to a violation pixel AND center depth in front
        cand = _candidate_gaussians(gaussians, cam_pose=c2w, fx=dataset.fx, fy=dataset.fy,
                                    cx=dataset.cx, cy=dataset.cy, W=dataset.width,
                                    H=dataset.height, violation=gated,
                                    obs_depth=gt_depth, band_abs=band_abs, band_rel=band_rel,
                                    N=N, device=dataset.device)
        n_cand = int(cand["count"])
        if n_cand:
            op = cand["opacity"]
            pcts = np.percentile(op, [25, 50, 90])
        else:
            pcts = (float("nan"),) * 3
        # overlap of candidate centers with masks
        cand_in_cur = int(np.logical_and(cand["pixel_mask"], dyn).sum()) if n_cand else 0
        cand_in_vac = (
            int(np.logical_and(cand["pixel_mask"], vacated).sum())
            if (n_cand and vacated is not None) else 0
        )

        rows.append({
            "frame": fid,
            "n_obs_px": n_obs,
            "v_px": v_all,
            "v_ratio": float(v_all / n_obs) if n_obs else float("nan"),
            "v_gated_px": v_gated,
            "v_cc": n_cc,
            "v_cc_large": n_cc_large,
            "v_cc_large_px": n_cc_large_px,
            "v_large_frac": largest_frac,
            "v_vacated_px": v_vacated,
            "vac_excess": vac_excess,
            "n_cand": n_cand,
            "cand_op_p25": pcts[0],
            "cand_op_p50": pcts[1],
            "cand_op_p90": pcts[2],
            "cand_in_current_dyn": cand_in_cur,
            "cand_in_vacated": cand_in_vac,
            "cand_prec_vac": float(cand_in_vac / n_cand) if n_cand else float("nan"),
            "cand_prec_cur": float(cand_in_cur / n_cand) if n_cand else float("nan"),
            "had_flow": had_flow,
            "flow_valid_frac": (
                float(fv.mean()) if (had_flow and fv is not None) else float("nan")
            ),
        })

        if k % 20 == 0:
            print(f"  [{os.path.basename(run_dir)}] probe frame {fid} v={v_all}/{n_obs} "
                  f"cand={n_cand} p90={pcts[2] if n_cand else 'na':>6}", flush=True)

    del gaussians, dataset
    torch.cuda.empty_cache()
    return _finalize(run_dir, rows, out_name, cfg, N)


def _finalize(run_dir, rows, out_name, cfg, N):
    import csv
    out = os.path.join(run_dir, out_name)
    os.makedirs(out, exist_ok=True)
    cols = list(rows[0].keys())
    with open(os.path.join(out, "stage0_eviction_readout.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    import numpy as np
    vg = np.array([r["v_ratio"] for r in rows if np.isfinite(r["v_ratio"])])
    vpx = np.array([r["v_gated_px"] for r in rows])
    nc = np.array([r["n_cand"] for r in rows])
    op90 = np.array([r["cand_op_p90"] for r in rows if np.isfinite(r["cand_op_p90"])])
    op50 = np.array([r["cand_op_p50"] for r in rows if np.isfinite(r["cand_op_p50"])])
    pp = np.array([r["cand_prec_vac"] for r in rows if np.isfinite(r["cand_prec_vac"])])
    pc = np.array([r["cand_prec_cur"] for r in rows if np.isfinite(r["cand_prec_cur"])])
    vvac = np.array([r["v_vacated_px"] for r in rows])

    sumd = {
        "run_dir": run_dir,
        "seq": cfg["Dataset"].get("sequence", ""),
        "n_frames_sampled": len(rows),
        "n_gaussians": N,
        "v_ratio": {
            "mean": float(vg.mean()) if vg.size else None,
            "median": float(np.median(vg)) if vg.size else None,
            "max": float(vg.max()) if vg.size else None,
        },
        "v_gated_px_mean": float(vpx.mean()) if vpx.size else None,
        "v_vacated_frac_mean": float((vvac / np.maximum(vpx, 1)).mean()) if vvac.size else None,
        "vac_excess_mean": (
            float(np.nanmean(np.array([r["vac_excess"] for r in rows if np.isfinite(r["vac_excess"])])))
            if any(np.isfinite(r["vac_excess"]) for r in rows) else None
        ),
        "n_cand_mean": float(nc.mean()) if nc.size else None,
        "n_cand_total": int(nc.sum()) if nc.size else 0,
        "n_cand": {"mean": float(nc.mean()) if nc.size else None,
                   "total": int(nc.sum()) if nc.size else 0},
        "cand_opacity": {
            "p50_mean": float(op50.mean()) if op50.size else None,
            "p90_mean": float(op90.mean()) if op90.size else None,
        },
        "overlap_vacated": {
            "prec_mean": float(pp.mean()) if pp.size else None,
            "prec_p25": float(np.percentile(pp, 25)) if pp.size else None,
        },
        "overlap_current_mask": {
            "prec_mean": float(pc.mean()) if pc.size else None,
        },
    }
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump(sumd, f, indent=2)
    return sumd


def _undistort_depth_like(dataset, depth):
    import cv2
    if depth is None:
        return None
    d = depth.detach().cpu().numpy() if hasattr(depth, "detach") else depth
    map1x = getattr(dataset, "map1x", None)
    map1y = getattr(dataset, "map1y", None)
    if getattr(dataset, "disorted", False) and map1x is not None and map1y is not None:
        return cv2.remap(np.asarray(d, np.float32), map1x, map1y, cv2.INTER_NEAREST)
    return np.asarray(d, np.float32)


def _load_mask(path):
    from utils.gtmc_mask import load_frozen_mask
    return np.asarray(load_frozen_mask(path), dtype=bool)


def _load_vacated_union(mask_by_stem, depth_stem_by_idx, cur_fid):
    """Union of frozen dynamic masks for all frames < cur_fid, minus current mask."""
    from utils.gtmc_mask import load_frozen_mask
    union = None
    for i in range(min(cur_fid, len(depth_stem_by_idx))):
        s = depth_stem_by_idx[i]
        p = mask_by_stem.get(s)
        if p is None:
            continue
        m = np.asarray(load_frozen_mask(p), dtype=bool)
        union = m if union is None else (union | m)
    cur = mask_by_stem.get(depth_stem_by_idx[cur_fid])
    if cur is not None:
        m = np.asarray(load_frozen_mask(cur), dtype=bool)
        union = union if union is not None else np.zeros_like(m)
        union = union & (~m)
    return union if union is not None else None


def _candidate_gaussians(gaussians, cam_pose, fx, fy, cx, cy, W, H, violation,
                         obs_depth, band_abs, band_rel, N, device):
    """Gaussians whose projected center lands on a violation pixel AND whose
    center depth is in front of the observed surface (by > band).

    The two-sided rule: a single violating Gaussian's center must be verifiable
    as out-in-front. Per codex F4, with center-depth compositing this is
    conservative but complete (a composite-front violation with all contributing
    centers behind cannot happen in a properly normalized rasterizer).
    """
    import torch
    xyz = gaussians.get_xyz.detach().cpu().numpy()  # (N,3)
    inv = np.linalg.inv(cam_pose)
    R, t = inv[:3, :3], inv[:3, 3]
    cam = xyz @ R.T + t  # (N,3)
    z = cam[:, 2]
    front = z > 0.01
    u = fx * cam[:, 0] / np.maximum(z, 1e-6) + cx
    v = fy * cam[:, 1] / np.maximum(z, 1e-6) + cy
    inside = front & (u >= 0) & (u < W) & (v >= 0) & (v < H)
    ui = np.clip(u[inside].astype(np.int64), 0, W - 1)
    vi = np.clip(v[inside].astype(np.int64), 0, H - 1)
    # pixel violation value at each in-view Gaussian
    pix = violation[vi, ui]
    # observed depth band at those pixel centres
    od = obs_depth[vi, ui]
    ovalid = np.isfinite(od)
    bandpix = np.clip(band_abs + band_rel * od, 1e-6, None)
    # center-in-front: z < od - band (occludes the observed surface by > band)
    zfront = z[inside] < (od - bandpix)
    sel = inside.copy()
    sel[inside] = pix & ovalid & zfront

    cand_idx = np.nonzero(sel)[0]
    count = int(cand_idx.shape[0])
    opacity = gaussians.get_opacity.detach().cpu().numpy().reshape(-1)[cand_idx] if count else None
    pixel_mask = np.zeros((H, W), dtype=bool)
    if count:
        pixmask_idx = np.nonzero(sel[inside])[0]
        pixel_mask[vi[pixmask_idx], ui[pixmask_idx]] = True
    return {"count": count, "opacity": opacity, "pixel_mask": pixel_mask,
            "idx": cand_idx}


def _resolve_run_dir(run_dir):
    """Map a top-level table run dir to the actual SLAM output dir containing
    config.yml + point_cloud/final_after_opt/point_cloud.ply + plot/trj_full_final.json.

    The P2-T batch layout nests these under a timestamp:
      <run_dir>/datasets_bonn/<method>_<seq>/seed_<N>/<timestamp>/
    """
    rd = os.path.normpath(run_dir)
    cand = os.path.join(rd, "config.yml")
    if os.path.isfile(cand):
        return rd
    import glob as _g
    # find the deepest config.yml in the run dir
    configs = sorted(_g.glob(os.path.join(rd, "**", "config.yml"), recursive=True))
    if not configs:
        return rd
    # prefer the one whose parent dir also has point_cloud/final_after_opt/point_cloud.ply
    for c in configs:
        base = os.path.dirname(c)
        if os.path.isdir(os.path.join(base, "point_cloud", "final_after_opt")):
            if os.path.isfile(os.path.join(base, "point_cloud", "final_after_opt", "point_cloud.ply")):
                return base
    # fallback: the deepest config (most-nested, by path length)
    return os.path.dirname(configs[-1])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dirs", nargs="+", help="finished mono/run dirs (contain config + final_after_opt PLY)")
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--band-abs", type=float, default=0.05)
    ap.add_argument("--band-rel", type=float, default=0.02)
    ap.add_argument("--no-flow-gate", action="store_true",
                    help="skip the recomputed flow_valid gate (violation not ANDed with fv)")
    args = ap.parse_args()

    import yaml

    os.chdir(ROOT)
    for rd_arg in args.run_dirs:
        rd = _resolve_run_dir(rd_arg)
        cfg_path = os.path.join(rd, "config.yml")
        if not os.path.isfile(cfg_path):
            print(f"STAGE0-FAIL {rd_arg}: no config.yml under {rd_arg}", flush=True)
            continue
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        # dataset path in the resolved config is relative to ROOT (the cwd); the
        # original run may store an absolute path — normalise to ROOT-relative.
        dp = cfg["Dataset"].get("dataset_path", "")
        if dp and not os.path.isdir(dp) and os.path.isdir(os.path.join(ROOT, dp)):
            cfg["Dataset"]["dataset_path"] = os.path.join(ROOT, dp)
        try:
            s = probe_run(rd, cfg, args.interval, args.band_abs, args.band_rel, 0.5,
                          "kf", 5, "stage0_eviction", args.no_flow_gate)
            print("STAGE0 " + json.dumps({"seq": cfg["Dataset"].get("sequence", ""),
                                          "v_ratio": s["v_ratio"],
                                          "vac_excess_mean": s["vac_excess_mean"],
                                          "n_cand": s["n_cand"], "cand_op": s["cand_opacity"],
                                          "overlap_vac": s["overlap_vacated"],
                                          "run": rd}, default=str), flush=True)
        except Exception as exc:
            import traceback
            print(f"STAGE0-FAIL {rd}: {exc}", flush=True)
            traceback.print_exc()


if __name__ == "__main__":
    main()
