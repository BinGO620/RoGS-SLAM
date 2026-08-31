#!/usr/bin/env python3
"""Q2 discriminating probe: is "integer cross-KF contradiction counting" (item-5,
"swap-the-gate") genuinely distinct from the free-space eviction that stage0
vac_excess already killed? ZERO-GPU, reads already-saved artifacts.

WHY THIS EXISTS (pivotal direction decision, consult_prompt_v2_direction.md Q2).
The stage0 probe killed *per-pixel single-frame free-space-violation* eviction:
vac_excess = P(violation|vacated) - P(violation|never-dynamic control) ≈ 0 on all 4
seqs, so the violation signal is global pose/opacity bias, not swept-ghost-specific.
The reopened item-5 proposes instead: accumulate *integer cross-keyframe*
contradictions per Gaussian (the alpha_lifecycle.py:224 select_carve_mask gate,
`obs_count >= min_obs_count`), then evict Gaussians whose contradictions persist.

Hermes's critique (adopted): the online contradiction counter in deferred_commit.py
runs ONLY on `pending` candidates — Gaussians that survived warm-up. Map Gaussians
that were never candidates have no counter at all. That is a selection effect: it
prescreens to non-ghosts, so "contradiction counting works" may be vacuous. To test
WHETHER the *signal itself* (persistent front-of-observation contradictions on all
map Gaussians) clusters in vacated regions, we must count on EVERY map Gaussian.

This probe therefore computes, on every saved final_after_opt Gaussian, over the
SAMPLED keyframes:
  C_i = number of keyframes where Gaussian i's center projects and is in front of
        the observed surface by > band (same center-projection as
        stage0._candidate_gaussians, same band convention as stage0 so the comparison
        to the killed pixel probe is apples-to-apples), AND is NOT under the current
        dynamic mask, AND is flow-consensus-valid (or --no-flow-gate).
Then:
  E_k = P(C_i >= k | Gaussian center in vacated region)
      - P(C_i >= k | Gaussian center in never-dynamic eroded control)
for k in {1,2,3,4}. This is the Gaussian-level vac_excess analogue: if the persistent
contradiction signal is real, contradicted Gaussians cluster in vacated regions
(E_k > 0). If it is the same global-bias signal stage0 killed, E_k ≈ 0.

Also reports opacity of the contradicted set (Hermes's pass criterion: op_p50 >= 0.5
means the persistent contradicted Gaussians are OPAQUE solids worth evicting; the
stage0 finding was that single-frame candidates are mostly semi-transparent floaters).

Reference gates (two conventions, both reported):
  - band = band_abs + band_rel * observed_depth   (per-PIXEL, stage0 convention)
  - band = band_abs + band_rel * projected_z        (per-GAUSSIAN, deferred_commit:490)
The proposed carve gate / deferred engine use the per-Gaussian one; stage0 used the
per-pixel one. Reporting both isolates which convention matters.

READ-ONLY. Writes <run>/q2_contradiction/gate_C_readout.csv + gate_E_summary.json.
Never touches live code or the map.

Usage:
  python scripts/q2_contradiction_probe.py RUN [RUN ...] [--interval 5]
      [--band-abs 0.05 --band-rel 0.02] [--min-render-op 0.5] [--max-k 4]
      [--no-flow-gate]
"""
import argparse
import csv
import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _resolve_run_dir(run_dir):
    rd = os.path.normpath(run_dir)
    if os.path.isfile(os.path.join(rd, "config.yml")):
        return rd
    configs = sorted(glob.glob(os.path.join(rd, "**", "config.yml"), recursive=True))
    for c in configs:
        base = os.path.dirname(c)
        if os.path.isfile(os.path.join(base, "point_cloud", "final_after_opt", "point_cloud.ply")):
            return base
    return os.path.dirname(configs[-1]) if configs else rd


def _load_mask(path):
    from utils.gtmc_mask import load_frozen_mask
    return np.asarray(load_frozen_mask(path), dtype=bool)


def _load_vacated_union(mask_by_stem, depth_stem_by_idx, cur_fid):
    """Union of ALL past masks up to (not incl) cur_fid, drawn at current frame
    camera space — identical to stage0_eviction_probe._load_vacated_union.
    """
    vac = None
    for j in range(cur_fid):  # strictly BEFORE current frame
        s = depth_stem_by_idx[j]
        pp = mask_by_stem.get(s)
        if pp is None:
            continue
        v = _load_mask(pp)
        vac = v if vac is None else (vac | v)
    return vac


def probe_run(run_dir, cfg, interval, band_abs, band_rel, max_k, no_flow_gate):
    from utils.dataset import load_dataset
    from gaussian_splatting.scene.gaussian_model import GaussianModel
    from munch import munchify

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
    xyz = gaussians.get_xyz.detach().cpu().numpy()  # (N,3)
    op_all = gaussians.get_opacity.detach().cpu().numpy().reshape(-1)  # raw sigmoid input
    op_raw = 1.0 / (1.0 + np.exp(-op_all))

    with open(trj_path, "r", encoding="utf-8") as f:
        trj = json.load(f)
    pose_by_id = {int(fid): np.asarray(c2w, dtype=np.float64)
                  for fid, c2w in zip(trj["trj_id"], trj["trj_est"])}
    frame_ids = sorted(pose_by_id.keys())

    # frozen GTMC masks keyed by depth stem
    subdir = cfg["Results"].get("static_bg_mask_subdir")
    mask_dir = os.path.join(cfg["Dataset"]["dataset_path"], subdir) if subdir else ""
    mask_by_stem = {}
    if mask_dir and os.path.isdir(mask_dir):
        from utils.gtmc_mask import frozen_mask_index
        idx = frozen_mask_index(mask_dir)
        mask_by_stem = {s: os.path.abspath(p) for s, p in idx.items()}
    depth_stem_by_idx = [os.path.splitext(os.path.basename(dp))[0] for dp in dataset.depth_paths]

    # frozen RAFT flow keyed by dataset frame index
    flow_dir = os.path.join(cfg["Dataset"]["dataset_path"],
                            cfg.get("ReliabilitySignal", {}).get("flow_subdir", "flow_raft"))
    flow_by_stem = {}
    if os.path.isdir(flow_dir):
        for fn in sorted(os.listdir(flow_dir)):
            if fn.endswith(".npy"):
                flow_by_stem[os.path.splitext(fn)[0]] = os.path.join(flow_dir, fn)
    flow_by_idx = {i: flow_by_stem[s] for i, s in enumerate(depth_stem_by_idx) if s in flow_by_stem}

    from scripts.stage0_eviction_probe import _undistort_depth_like as _undistort
    H, W = dataset.height, dataset.width
    fx, fy, cx, cy = dataset.fx, dataset.fy, dataset.cx, dataset.cy

    # arrays: per-Gaussian contradiction C for each convention; per-Gaussian region tag
    C_pix = np.zeros(N, dtype=np.int16)
    C_gauss = np.zeros(N, dtype=np.int16)
    seen = np.zeros(N, dtype=np.int16)
    in_vac = np.zeros(N, dtype=bool)
    never_dyn = np.zeros(N, dtype=bool)

    sampled = [i for i in frame_ids if i % interval == 0 and i < len(depth_stem_by_idx)
               and depth_stem_by_idx[i] in mask_by_stem]
    frame_meta = []

    for kidx, fid in enumerate(sampled):
        if fid >= len(dataset.depth_paths):
            continue
        stem = depth_stem_by_idx[fid]
        c2w = pose_by_id[fid]
        inv = np.linalg.inv(c2w)
        R, t = inv[:3, :3], inv[:3, 3]

        gt_image, gt_depth_raw, _ = dataset[fid]
        gt_depth = _undistort(dataset, gt_depth_raw)  # (H,W) np float
        cam = xyz @ R.T + t
        z = cam[:, 2]
        front = z > 0.01
        u = fx * cam[:, 0] / np.maximum(z, 1e-6) + cx
        v = fy * cam[:, 1] / np.maximum(z, 1e-6) + cy
        inside = front & (u >= 0) & (u < W) & (v >= 0) & (v < H)
        ui = np.clip(u[inside].astype(np.int64), 0, W - 1)
        vi = np.clip(v[inside].astype(np.int64), 0, H - 1)

        dyn = _load_mask(mask_by_stem[stem])
        valid_obs = np.isfinite(gt_depth) & (gt_depth > 0.01)
        od = gt_depth[vi, ui]

        # flow consensus validity at mapped pixels (gate mirror), if available
        fv = None
        if (not no_flow_gate) and fid in flow_by_idx:
            from scripts.stage0_eviction_probe import _flow_anomaly_map
            e, fv, _cov = _flow_anomaly_map(np.load(flow_by_idx[fid]), flow_by_idx, None, fid)
            fv = fv[vi, ui]

        # per-pixel band (stage0 convention)
        band_pix = np.clip(band_abs + band_rel * od, 1e-6, None)
        # per-Gaussian band (deferred_commit convention)
        band_gauss = np.clip(band_abs + band_rel * z[inside], 1e-6, None)

        ovalid = np.isfinite(od)
        notdyn = ~dyn[vi, ui]
        elig = inside.copy()
        elig[inside] = ovalid & notdyn
        if fv is not None:
            elig[inside] = elig[inside] & fv

        gsel = elig[inside]
        inside_idx = np.flatnonzero(inside)
        gids = inside_idx[gsel] if gsel.any() else np.array([], dtype=np.int64)
        # local index among inside+Gaussian for the per-pixel arrays (od, band_pix, band_gauss)
        # which are indexed by the same (vi, ui) projection sequence
        # The od/band arrays are (n_inside,) — one per projected Gaussian. gsel selects from those.
        # So local_idx = which indices among the inside-projected Gaussians are eligible.
        local_idx = np.flatnonzero(gsel) if gsel.any() else np.array([], dtype=np.int64)
        if not gids.size:
            continue
        zi = z[gids]
        z_obs = od[local_idx]
        gband_pix = band_pix[local_idx]
        gband_gauss = band_gauss[local_idx]
        contra_pix = zi < (z_obs - gband_pix)
        contra_gauss = zi < (z_obs - gband_gauss)
        C_pix[gids[contra_pix]] += 1
        C_gauss[gids[contra_gauss]] += 1
        seen[gids] += 1

        # local pixel indices for the eligible Gaussians (among the projected set)
        vi_local = vi[local_idx] if local_idx.size else np.array([], dtype=np.int64)
        ui_local = ui[local_idx] if local_idx.size else np.array([], dtype=np.int64)

        # region tags (use as many keyframes BEFORE current as available)
        vacated = _load_vacated_union(mask_by_stem, depth_stem_by_idx, fid)
        if vacated is not None and gids.size:
            in_vac[gids] |= vacated[vi_local, ui_local]
        # never-dynamic control: pixel never under any mask through CURRENT frame
        if mask_by_stem:
            mask_union = np.zeros((H, W), dtype=bool)
            for j in range(min(fid + 1, len(depth_stem_by_idx))):
                s = depth_stem_by_idx[j]
                pp = mask_by_stem.get(s)
                if pp is not None:
                    mask_union |= _load_mask(pp)
            from scipy import ndimage
            never_dyn[gids] |= ~mask_union[vi_local, ui_local]

        frame_meta.append({"frame": fid, "n_gauss_elig": int(gids.size),
                           "n_contra_pix": int(contra_pix.sum()),
                           "n_contra_gauss": int(contra_gauss.sum())})
        if fid % 100 == 0 or kidx % 20 == 0:
            print(f"  [q2 {os.path.basename(run_dir)}] frame {fid} elig={gids.size} "
                  f"contra_pix={contra_pix.sum()} contra_gauss={contra_gauss.sum()}", flush=True)

    del gaussians, dataset
    return _finalize(run_dir, np.arange(N), C_pix, C_gauss, op_raw, seen,
                     in_vac, never_dyn, cfg, frame_meta, max_k)


def _finalize(run_dir, idx, C_pix, C_gauss, op_raw, seen, in_vac, never_dyn,
              cfg, frame_meta, max_k, out_name="q2_contradiction"):
    out = os.path.join(run_dir, out_name)
    os.makedirs(out, exist_ok=True)

    # ---- per-Gaussian region labels: vacated OR never-dynamic control ----
    # A Gaussian may be tagged BOTH (vacated somewhere, never-dynamic elsewhere).
    # For the E_k denominator we need disjoint support. Resolve: tag a Gaussian as
    # vacated-preferential if in_vac saw it in a vacated region, else never-dyn.
    # Exclude Gaussians never seen at all (no evidence).
    seen_mask = seen > 0
    # candidate population = seen and tagged
    vac_tag = in_vac & seen_mask
    ctrl_tag = never_dyn & (~in_vac) & seen_mask

    # exclude frames/labels that never registered — handle region support
    results = {}
    for conv, C, name in (("pixel", C_pix, "pix"), ("gauss", C_gauss, "gauss")):
        for k in range(1, max_k + 1):
            sel = C >= k
            # denominator: fraction of each region that reaches the threshold
            pv = sel[vac_tag].mean() if vac_tag.any() else float("nan")
            pc = sel[ctrl_tag].mean() if ctrl_tag.any() else float("nan")
            E = float(pv - pc) if not (pv != pv or pc != pc) else float("nan")
            n_sel = int(sel.sum())
            # opacity of the selected set
            o = op_raw[sel] if n_sel else np.array([])
            results[f"E{k}_{name}"] = E
            results[f"pv{k}_{name}"] = pv
            results[f"pc{k}_{name}"] = pc
            results[f"n_sel{k}_{name}"] = n_sel
            results[f"n_sel_fract{k}_{name}"] = float(n_sel / max(int(seen_mask.sum()), 1))
            results[f"sel_op_p50{k}_{name}"] = float(np.median(o)) if o.size else float("nan")
            results[f"sel_op_p90{k}_{name}"] = float(np.percentile(o, 90)) if o.size else float("nan")
            results[f"sel_op_ge09_frac{k}_{name}"] = float((o >= 0.9).mean()) if o.size else float("nan")
        results[f"support_vac_{name}"] = int(vac_tag.sum())
        results[f"support_ctrl_{name}"] = int(ctrl_tag.sum())
        results[f"n_seen_{name}"] = int(seen_mask.sum())

    summary = {
        "run_dir": run_dir,
        "seq": cfg["Dataset"].get("sequence", ""),
        "n_gaussians": int(len(idx)),
        "n_frames_sampled": int(len(frame_meta)),
        "n_eligible_gauss_seen": int(seen_mask.sum()),
        "interval": int(5),
        "band_abs": float(0.05), "band_rel": float(0.02),
        "results": results,
    }

    with open(os.path.join(out, "gate_E_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, default=str)
    with open(os.path.join(out, "gate_C_readout.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "n_gauss_elig", "n_contra_pix", "n_contra_gauss"])
        for r in frame_meta:
            w.writerow([r["frame"], r["n_gauss_elig"], r["n_contra_pix"], r["n_contra_gauss"]])
    print("Q2 " + json.dumps({"seq": cfg["Dataset"].get("sequence", ""), **{
        f"E{k}_{conv}": results.get(f"E{k}_{conv}") for conv in ("pix", "gauss")
        for k in range(1, max_k + 1)}, "support_vac": results.get("support_vac_pix"),
        "support_ctrl": results.get("support_ctrl_pix"), "n_seen": results.get("n_seen_pix"),
        "sel_op_p50": results.get("sel_op_p50_pix"), "run": run_dir}, default=str), flush=True)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--band-abs", type=float, default=0.05)
    ap.add_argument("--band-rel", type=float, default=0.02)
    ap.add_argument("--max-k", type=int, default=4)
    ap.add_argument("--no-flow-gate", action="store_true")
    args = ap.parse_args()
    import yaml
    os.chdir(ROOT)
    for rd_arg in args.run_dirs:
        rd = _resolve_run_dir(rd_arg)
        cfg_path = os.path.join(rd, "config.yml")
        if not os.path.isfile(cfg_path):
            print(f"Q2-FAIL {rd_arg}: no config", flush=True)
            continue
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        dp = cfg["Dataset"].get("dataset_path", "")
        if dp and not os.path.isdir(dp) and os.path.isdir(os.path.join(ROOT, dp)):
            cfg["Dataset"]["dataset_path"] = os.path.join(ROOT, dp)
        try:
            probe_run(rd, cfg, args.interval, args.band_abs, args.band_rel,
                      args.max_k, args.no_flow_gate)
        except Exception:
            import traceback
            print(f"Q2-FAIL {rd}: ", flush=True)
            traceback.print_exc()
