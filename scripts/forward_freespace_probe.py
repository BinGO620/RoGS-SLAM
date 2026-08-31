#!/usr/bin/env python3
"""Forward free-space constraint | probe (Stage-0 analog for the FORWARD lever).

WHY THIS EXISTS. The reverse-direction carve (Stage 0 eviction) died empirically:
free-space violations are global pose/rendering bias, not swept-ghost-specific, so
post-hoc deleting violating Gaussians has no dynamic target. But the LITERATURE
gap is on the FORWARD side: NeRF SLAM (Co-SLAM, NICE-SLAM, ESLAM, Point-SLAM)
regularizes a free-space loss L_fs on sampled ray points, whereas MonoGS's rasterizer
imposes NO constraint along the viewing ray (MonoGS CVPR 2024 §3.3.3: "Rasterisation
of 3DGS imposes no constraint on the Gaussians along the viewing ray direction, even
with a depth observation"), and they substitute an isotropic-shape regularizer that
does not reach the ray-forward direction. No 3DGS SLAM adds free-space supervision to
the mapping loss. This probe measures what such a term WOULD do: the magnitude and
composition of the forward free-space gradient signal on a final map, re-rendered at
the SAVED est poses (same zero-GPU offline path as r2_p2_t_offline_render.py).

WHAT IT COMPUTES (per sampled frame):
  1. forward free-space penalty value, if we added
       L_fs = mean over valid pixels of max(0, band - (gt_depth - render_depth))^2
       applied ONLY where render_depth < gt_depth - band  (geometry in front of obs)
       AND observed valid AND render opacity >= 0.5 (a real occluder exists)
       AND NOT frozen-dynamic-mask (we don't want to penalize where the mover is).
     This is exactly the term a forward constraint would add to get_loss_mapping_rgbd.
  2. The gradient-bearing support: what fraction of VALID static pixels currently
     carry an opaque (opacity>=0.5) forward violation. If this is near 0 in the
     REGION WE CARE ABOUT (vacated), the forward term is inert there.
  3. Vac-excess analogue: forward-support rate in vacated region vs never-dynamic
     control — same base-rate guard the reverse probe used, so a positive value means
     the forward term would preferentially clean swept ghosts (desirable), a ~0 or
     negative means it would mostly push global pose/rendering bias (undesirable).

This is a READ-ONLY offline probe identical in spirit to Stage 0: it re-renders saved
artifacts, writes to <run>/forward_freespace/, never touches live code or the map.

Usage:
  python scripts/forward_freespace_probe.py RUN_DIR [RUN_DIR ...] [--interval 5]
      [--band-abs 0.05 --band-rel 0.02] [--min-render-op 0.5] [--exp 2]
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


def probe_run(run_dir, cfg, interval, band_abs, band_rel, min_render_op, exp,
              out_name="forward_freespace"):
    import torch
    from munch import munchify

    from gaussian_splatting.gaussian_renderer import render
    from gaussian_splatting.scene.gaussian_model import GaussianModel
    from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
    from utils.camera_utils import Camera
    from utils.dataset import load_dataset
    from utils.gtmc_mask import frozen_mask_index

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
    pose_by_id = {int(fid): np.asarray(c2w, dtype=np.float64)
                  for fid, c2w in zip(trj["trj_id"], trj["trj_est"])}
    frame_ids = sorted(pose_by_id.keys())

    projection_matrix = (
        getProjectionMatrix2(znear=0.01, zfar=100.0, fx=dataset.fx, fy=dataset.fy,
                             cx=dataset.cx, cy=dataset.cy, W=dataset.width, H=dataset.height)
        .transpose(0, 1).to(device=dataset.device)
    )
    background = torch.tensor([0, 0, 0], dtype=torch.float32, device="cuda")

    # frozen GTMC masks keyed by depth stem
    subdir = cfg["Results"].get("static_bg_mask_subdir")
    mask_dir = os.path.join(cfg["Dataset"]["dataset_path"], subdir) if subdir else ""
    mask_by_stem = {}
    if mask_dir and os.path.isdir(mask_dir):
        idx = frozen_mask_index(mask_dir)
        mask_by_stem = {s: os.path.abspath(p) for s, p in idx.items()}
    depth_stem_by_idx = [os.path.splitext(os.path.basename(dp))[0] for dp in dataset.depth_paths]

    sampled = [i for i in frame_ids if i % interval == 0 and i < len(depth_stem_by_idx)
               and depth_stem_by_idx[i] in mask_by_stem]

    rows = []
    for k, fid in enumerate(sampled):
        stem = depth_stem_by_idx[fid]
        c2w = pose_by_id[fid]
        rot = np.linalg.inv(c2w)[:3, :3]
        t = np.linalg.inv(c2w)[:3, 3]
        cam = Camera(int(fid), None, None, torch.eye(4, device=dataset.device),
                     projection_matrix, dataset.fx, dataset.fy, dataset.cx, dataset.cy,
                     dataset.fovx, dataset.fovy, dataset.height, dataset.width,
                     device=dataset.device)
        cam.update_RT(torch.from_numpy(np.ascontiguousarray(rot)).float(),
                      torch.from_numpy(np.ascontiguousarray(t)).float())
        cam.cam_rot_delta = None
        cam.cam_trans_delta = None
        cam.exposure_a = None
        cam.exposure_b = None

        _, gt_depth_raw, _ = dataset[fid]
        gt_depth = _undistort_depth_like(dataset, gt_depth_raw)
        pkg = render(cam, gaussians, munchify(cfg["pipeline_params"]), background)
        r_depth_raw = pkg["depth"].detach().cpu().numpy().squeeze()
        r_op = pkg["opacity"].detach().cpu().numpy().squeeze()
        del cam

        # normalized depth (same as Stage 0): D/(1-T) removes semi-transparency shallowing
        r_depth = r_depth_raw / np.maximum(r_op, 1e-6)

        dyn = _load_mask(mask_by_stem[stem])
        valid_obs = np.isfinite(gt_depth) & (gt_depth > 0.01) & (gt_depth <= 15.0)
        valid_render = np.isfinite(r_depth) & np.isfinite(r_op)
        valid = valid_obs & valid_render & (~dyn)

        # forward violation: rendered depth is shallower than observed by > band,
        # at an opaque (>=0.5) location, in a valid static pixel.
        band = np.clip(band_abs + band_rel * gt_depth, 1e-6, None)
        fwd_viol = valid & (r_depth < (gt_depth - band)) & (r_op >= min_render_op)

        # the forward free-space L2 penalty a term would apply at each violating pixel
        excess = np.clip((gt_depth - r_depth).astype(np.float64), 0.0, None)
        # only where it's actually a violation (beyond band)
        excess[~fwd_viol] = 0.0
        pen = (np.clip((excess - band), 0.0, None) ** exp)

        # support rates
        support_all = int(fwd_viol.sum())
        support_frac = support_all / max(int(valid.sum()), 1)
        # vacated region (union past minus current)
        from utils.gtmc_mask import load_frozen_mask
        vacated = None
        union = None
        for j in range(min(fid, len(depth_stem_by_idx))):
            pp = mask_by_stem.get(depth_stem_by_idx[j])
            if pp is None:
                continue
            m = _load_mask(pp)
            union = m if union is None else (union | m)
        cur = _load_mask(mask_by_stem[stem])
        if union is not None:
            vacated = (union & ~cur)
        # never-dynamic control (pixel never under any mask, eroded boundary)
        from scipy import ndimage
        never = np.zeros_like(dyn)
        for j in range(min(fid + 1, len(depth_stem_by_idx))):
            pp = mask_by_stem.get(depth_stem_by_idx[j])
            if pp is None:
                continue
            never |= _load_mask(pp)
        never = (~never) & (~ndimage.binary_dilation(never, iterations=4))
        control = valid & never

        vac_viol = int((fwd_viol & vacated).sum()) if vacated is not None else 0
        vac_support = int((vacated & valid).sum()) if vacated is not None else 0
        ctrl_viol = int((fwd_viol & control).sum()) if (control is not None and int(control.sum())) else 0
        ctrl_support = int(control.sum())
        vac_rate = vac_viol / max(vac_support, 1) if vac_support else float("nan")
        ctrl_rate = ctrl_viol / max(ctrl_support, 1) if ctrl_support else float("nan")
        vac_excess = float(vac_rate - ctrl_rate) if (vac_support and ctrl_support) else float("nan")

        # mean penalty (as if L_fs = mean over all valid static pixels of pen)
        mean_pen_all = float(pen[valid].mean()) if int(valid.sum()) else float("nan")
        # mean penalty over vacated and control separately
        mean_pen_vac = float(pen[vacated & valid].mean()) if vacated is not None and int((vacated & valid).sum()) else float("nan")
        mean_pen_ctrl = float(pen[control & valid].mean()) if int((control & valid).sum()) else float("nan")

        rows.append({
            "frame": fid,
            "n_valid_px": int(valid.sum()),
            "fwd_viol_px": support_all,
            "fwd_viol_frac": support_frac,
            "vac_viol_px": vac_viol,
            "vac_support_px": vac_support,
            "ctrl_viol_px": ctrl_viol,
            "ctrl_support_px": ctrl_support,
            "vac_forward_rate": vac_rate,
            "ctrl_forward_rate": ctrl_rate,
            "vac_excess": vac_excess,
            "mean_pen_all": mean_pen_all,
            "mean_pen_vac": mean_pen_vac,
            "mean_pen_ctrl": mean_pen_ctrl,
        })
        if k % 15 == 0:
            print(f"  [{os.path.basename(run_dir)}] fwd f={fid} viol={support_all}/{int(valid.sum())} "
                  f"({support_frac:.3f}) vac_exc={vac_excess:.3f}", flush=True)

    del gaussians, dataset
    torch.cuda.empty_cache()

    # aggregate
    out = os.path.join(run_dir, out_name)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "forward_freespace_readout.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def _m(name):
        vals = [r[name] for r in rows if np.isfinite(r[name])]
        return float(np.mean(vals)) if vals else None

    summary = {
        "run_dir": run_dir,
        "seq": cfg["Dataset"].get("sequence", ""),
        "n_frames_sampled": len(rows),
        "n_gaussians": N,
        "fwd_viol": {"frac_mean": _m("fwd_viol_frac")},
        "vac_excess": {"mean": _m("vac_excess")},
        "vac_forward_rate": {"mean": _m("vac_forward_rate")},
        "ctrl_forward_rate": {"mean": _m("ctrl_forward_rate")},
        "penalty": {
            "all_mean": _m("mean_pen_all"),
            "vac_mean": _m("mean_pen_vac"),
            "ctrl_mean": _m("mean_pen_ctrl"),
        },
    }
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--band-abs", type=float, default=0.05)
    ap.add_argument("--band-rel", type=float, default=0.02)
    ap.add_argument("--min-render-op", type=float, default=0.5)
    ap.add_argument("--exp", type=float, default=2.0)
    args = ap.parse_args()

    import yaml

    os.chdir(ROOT)
    for rd0 in args.run_dirs:
        rd = _resolve_run_dir(rd0)
        with open(os.path.join(rd, "config.yml"), "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        dp = cfg["Dataset"].get("dataset_path", "")
        if dp and not os.path.isdir(dp) and os.path.isdir(os.path.join(ROOT, dp)):
            cfg["Dataset"]["dataset_path"] = os.path.join(ROOT, dp)
        try:
            s = probe_run(rd, cfg, args.interval, args.band_abs, args.band_rel,
                          args.min_render_op, args.exp)
            print("FWD-FS " + json.dumps({"seq": cfg["Dataset"].get("sequence", ""),
                                          "viol_frac": s["fwd_viol"],
                                          "vac_excess": s["vac_excess"],
                                          "penalty": s["penalty"],
                                          "run": rd}, default=str), flush=True)
        except Exception as exc:
            import traceback
            print(f"FWD-FS-FAIL {rd}: {exc}", flush=True)
            traceback.print_exc()


if __name__ == "__main__":
    main()
