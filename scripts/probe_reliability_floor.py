#!/usr/bin/env python3
"""Offline GT-pose reliability FLOW-FLOOR probe (doc-10 #7, method-independent).

Calibrates ``ReliabilitySignal.flow_scale_floor`` -- the noise-floor SCALE prior that
keeps a near-static frame's MAD collapse from saturating ``e_flow`` on RAFT-glitch /
occlusion-edge pixels (``utils/reliability_signal.py::flow_anomaly``). The USER-LOCKED
floor-selection rule (direction memo doc-10 #7): pick the SMALLEST floor that pushes the
STATIC no-harm worst case (f2_xyz: long-static, camera moving, weakly constrained) below
the no-harm budget -- ``e_flow > e_thresh`` pixel-fraction small -- WHILE a real mover
(obox) stays flagged. Method-independent: GT-pose ``rigid_flow`` for the ego ``f_static``,
frozen offline RAFT ``f_obs`` -- NO SLAM estimate, NO render, NO learned mask.

Faithful to the ONLINE tracking path (``slam_frontend`` R2 feed) so the calibrated floor
transfers 1:1: RAW loader depth for ``f_static`` (``viewpoint.depth`` is undistorted-RGB
but raw-depth), undistorted-RGB frozen ``f_obs``, config intrinsics K, backward transform
``T_{t-1<-t}`` -- the ONLY substitution is GT pose for the online pose (that is the point:
the eval oracle must not depend on the estimate it is judging). K=1 consensus == shipped.

This is per-frame flow math (one flow map at a time) -- it does NOT build a dense-KF map,
so it does NOT OOM on long sequences (that is a SLAM-map problem, not a per-frame-flow one):
f2_xyz's length is a runtime cost, not a memory wall.

Usage (build f_obs first with scripts/build_flow_raft.py --config <same cfg>):
  python scripts/probe_reliability_floor.py \
      --sequence-dir /data/Datasets/TUM/rgbd_dataset_freiburg2_xyz \
      --config configs/rgbd/tum/f2_xyz.yaml --label f2_xyz_static --max-frames 500
  python scripts/probe_reliability_floor.py \
      --sequence-dir /data/Datasets/Bonn/rgbd_bonn_moving_obstructing_box \
      --label obox_mover            # Bonn: CALIB_BONN default, no --config needed
"""

import argparse
import csv
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config_utils import load_config  # noqa: E402
from utils.flow_raft import frozen_flow_index, load_frozen_flow  # noqa: E402
from utils.geometry_metrics import load_tum_associations  # noqa: E402
from utils.gtmc_mask import CALIB_BONN  # noqa: E402
from utils.reliability_signal import (  # noqa: E402
    assemble_flow_consensus,
    relative_pose_target_from_source,
    rigid_flow,
)

DEFAULT_FLOORS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]


def flagged_fraction(e_flow, flow_valid, thresh):
    """Fraction of VALID-flow pixels whose ``e_flow`` exceeds ``thresh`` (the mover
    call). Denominator is valid-flow pixels only (missing-cue pixels are out of the
    decision), so a floor cannot flatter itself by shrinking ``flow_valid``. Returns
    ``(fraction, n_flagged)``; ``fraction`` is nan when no pixel has valid flow."""
    fv = flow_valid.bool()
    denom = int(fv.sum().item())
    if denom == 0:
        return float("nan"), 0
    flagged = int(((e_flow > thresh) & fv).sum().item())
    return flagged / denom, flagged


def largest_component_fraction(flagged_np):
    """Spatial concentration of the flagged set: fraction of flagged pixels in their
    largest 4-connected component. ~1 => a coherent blob (object-like, pose-informative);
    ~0 => scattered speckle (RAFT/edge noise -- the FP a floor should suppress). 0 when
    nothing is flagged."""
    total = int(flagged_np.sum())
    if total == 0:
        return 0.0
    labels, k = ndimage.label(flagged_np)
    if k == 0:
        return 0.0
    sizes = np.bincount(labels.ravel())[1:]  # drop background label 0
    return float(sizes.max()) / total


def _percentiles(values, qs=(50, 90, 99)):
    if len(values) == 0:
        return {f"p{q}": float("nan") for q in qs}
    arr = np.asarray(values, dtype=np.float64)
    return {f"p{q}": float(np.percentile(arr, q)) for q in qs}


def frame_static_flow(obs_depth, f_obs, c2w_t, c2w_prev, fx, fy, cx, cy, device):
    """Ego ``f_static`` + valid mask + raw residual ``||f_obs - f_static||`` (px) for one
    frame, from GT poses. ``obs_depth`` raw metres (H,W); ``f_obs`` (H,W,2) frozen backward
    flow f_{t->t-1}; ``c2w_t``/``c2w_prev`` the GT camera-to-world of frame t and t-1.
    Returns ``(f_static, valid, residual_px)`` all torch on ``device``."""
    import torch

    obs = torch.as_tensor(np.asarray(obs_depth, dtype=np.float32), device=device)
    fo = torch.as_tensor(np.asarray(f_obs, dtype=np.float32), device=device)
    w2c_t = torch.as_tensor(np.linalg.inv(c2w_t), dtype=torch.float32, device=device)
    w2c_prev = torch.as_tensor(np.linalg.inv(c2w_prev), dtype=torch.float32, device=device)
    # T_{t-1<-t}: source = current frame t (f_obs grid), target = previous frame t-1.
    R, tt = relative_pose_target_from_source(w2c_prev, w2c_t)
    f_static, fs_valid = rigid_flow(obs, fx, fy, cx, cy, R, tt)
    valid = fs_valid & torch.isfinite(fo).all(dim=-1)
    residual = (((fo - f_static) ** 2).sum(dim=-1).clamp_min(0.0).sqrt())[valid]
    return fo, f_static, valid, residual


def probe_sequence(seq_dir, calib, floors, flow_subdir, thresh, max_frames, stride, device):
    fx, fy, cx, cy = calib["fx"], calib["fy"], calib["cx"], calib["cy"]
    depth_scale = float(calib["depth_scale"])
    frames = load_tum_associations(seq_dir)
    idx = frozen_flow_index(os.path.join(seq_dir, flow_subdir))
    if not idx:
        raise SystemExit(
            f"no frozen flow under {os.path.join(seq_dir, flow_subdir)} -- "
            f"run scripts/build_flow_raft.py first"
        )
    limit = len(frames) if max_frames <= 0 else min(len(frames), max_frames)

    per_floor = {f: {"frac": [], "conc": [], "n_flag": []} for f in floors}
    resid_med, resid_p90, rows = [], [], []
    n_used = 0
    for t in range(1, limit, max(1, stride)):
        stem = os.path.splitext(os.path.basename(frames[t]["depth_path"]))[0]
        path = idx.get(stem)
        if path is None:
            continue  # flow not built for this frame (e.g. beyond the built prefix)
        depth = np.asarray(Image.open(frames[t]["depth_path"]), dtype=np.float32) / depth_scale
        f_obs = load_frozen_flow(path)
        fo, f_static, valid, residual = frame_static_flow(
            depth, f_obs, frames[t]["c2w"], frames[t - 1]["c2w"], fx, fy, cx, cy, device
        )
        if int(valid.sum().item()) == 0:
            continue
        n_used += 1
        rv = residual.detach().cpu().numpy()
        rp = _percentiles(rv, (50, 90))
        resid_med.append(rp["p50"])
        resid_p90.append(rp["p90"])
        row = {"frame": t, "stem": stem, "n_valid": int(valid.sum().item()),
               "resid_med_px": rp["p50"], "resid_p90_px": rp["p90"]}
        for floor in floors:
            e_flow, flow_valid = assemble_flow_consensus(
                [fo], [f_static], [valid], scale_floor=float(floor),
            )
            frac, n_flag = flagged_fraction(e_flow, flow_valid, thresh)
            flagged_np = ((e_flow > thresh) & flow_valid.bool()).detach().cpu().numpy()
            conc = largest_component_fraction(flagged_np)
            per_floor[floor]["frac"].append(frac)
            per_floor[floor]["conc"].append(conc)
            per_floor[floor]["n_flag"].append(n_flag)
            row[f"frac@{floor}"] = frac
            row[f"conc@{floor}"] = conc
        rows.append(row)

    summary = {
        "sequence_dir": os.path.abspath(seq_dir),
        "n_frames_used": n_used,
        "e_thresh": thresh,
        "flow_subdir": flow_subdir,
        "residual_px": {
            "median_of_frame_median": float(np.median(resid_med)) if resid_med else float("nan"),
            "median_of_frame_p90": float(np.median(resid_p90)) if resid_p90 else float("nan"),
        },
        "floors": {},
    }
    for floor in floors:
        fr = np.asarray(per_floor[floor]["frac"], dtype=np.float64)
        fr = fr[np.isfinite(fr)]
        cc = np.asarray(per_floor[floor]["conc"], dtype=np.float64)
        summary["floors"][str(floor)] = {
            "frac_mean": float(fr.mean()) if fr.size else float("nan"),
            "frac_median": float(np.median(fr)) if fr.size else float("nan"),
            "frac_p90": float(np.percentile(fr, 90)) if fr.size else float("nan"),
            "frac_max": float(fr.max()) if fr.size else float("nan"),
            "conc_median": float(np.median(cc)) if cc.size else float("nan"),
        }
    return summary, rows


def print_table(label, summary):
    r = summary["residual_px"]
    print(f"\n===== {label}  ({summary['n_frames_used']} frames,  "
          f"e_flow>{summary['e_thresh']} )  =====")
    print(f"  raw ||f_obs-f_static|| px: median-of-median={r['median_of_frame_median']:.3f}  "
          f"median-of-p90={r['median_of_frame_p90']:.3f}")
    print(f"  {'floor(px)':>9} {'frac_med':>9} {'frac_p90':>9} {'frac_max':>9} "
          f"{'frac_mean':>9} {'conc_med':>9}")
    for floor, s in summary["floors"].items():
        print(f"  {float(floor):>9.2f} {s['frac_median']:>9.4f} {s['frac_p90']:>9.4f} "
              f"{s['frac_max']:>9.4f} {s['frac_mean']:>9.4f} {s['conc_median']:>9.3f}")


def resolve_calib(config_path):
    if config_path:
        cfg = load_config(config_path)
        c = cfg["Dataset"]["Calibration"]
        return {k: float(c[k]) for k in ("fx", "fy", "cx", "cy", "depth_scale")}
    return {k: float(CALIB_BONN[k]) for k in ("fx", "fy", "cx", "cy", "depth_scale")}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sequence-dir", required=True)
    ap.add_argument("--config", default=None,
                    help="dataset config for Calibration (omit -> CALIB_BONN)")
    ap.add_argument("--flow-subdir", default="flow_raft")
    ap.add_argument("--floors", type=float, nargs="+", default=DEFAULT_FLOORS,
                    help="flow_scale_floor sweep (px)")
    ap.add_argument("--e-thresh", type=float, default=0.5, help="e_flow mover-call threshold")
    ap.add_argument("--max-frames", type=int, default=0, help="0 = all associated frames")
    ap.add_argument("--stride", type=int, default=1, help="subsample probed frames (pairs stay t,t-1)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--label", default=None)
    ap.add_argument("--out", default="workspace/dynamic-3dgs-slam/04-ours/data/reliability_floor")
    args = ap.parse_args()

    import torch

    device = args.device if (args.device == "cpu" or torch.cuda.is_available()) else "cpu"
    label = args.label or os.path.basename(os.path.normpath(args.sequence_dir))
    calib = resolve_calib(args.config)
    summary, rows = probe_sequence(
        args.sequence_dir, calib, list(args.floors), args.flow_subdir,
        args.e_thresh, args.max_frames, args.stride, device,
    )
    summary["label"] = label
    summary["calib"] = calib
    print_table(label, summary)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"floor_sweep_{label}.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    if rows:
        with open(os.path.join(args.out, f"floor_sweep_{label}.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"  wrote {args.out}/floor_sweep_{label}.{{json,csv}}")


if __name__ == "__main__":
    main()
