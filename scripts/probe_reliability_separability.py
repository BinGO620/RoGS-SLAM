#!/usr/bin/env python3
"""Does the reliability signal actually separate dynamic from static pixels? (gap 2)

WHY THIS EXISTS. The paper's mechanism claim -- ``s=(1-e_flow)(1-v*g)`` down-weights
dynamic pixels at the Gaussian-map admission layer -- currently rests on (a) ATE outcomes
and (b) a qualitative 5-panel figure whose s panels are a FLOW-ONLY approximation, because
the geometry term was never archived. P7 says geometry is the strongest cue on 3/4
sequences, so the headline mechanism figure omits the cue P7 calls most important. A
reviewer will hit that seam. This probe measures the thing directly.

WHAT IT MEASURES. Per frame, it rebuilds s with the ONLINE function itself
(``utils.reliability_signal.compute_reliability_tracking_weight``, the same code the SLAM
calls, including the same Cauchy weight), in all three fusion modes (both / flow-only /
geometry-only), and scores the per-pixel dynamic evidence ``1-s`` against the frozen
GT-pose motion-consistency mask ``dynamic_mask_gtmc/`` (method-independent, never seen by
the method). Reported per sequence and per mode:

  * AUC of ``1-s`` as a dynamic-pixel detector (0.5 = no separation),
  * separation ratio mean(1-s | dynamic) / mean(1-s | static),
  * the same two for the tracking weight ``w`` (what actually multiplies the residual),
  * the dynamic-pixel fraction, so a degenerate frame cannot masquerade as a good AUC.

HONEST APPROXIMATION (state it in the paper, do not bury it): the render used for
``render_depth`` / ``opacity`` comes from the run's TERMINAL map (final PLY) at the run's
own estimated poses, not from the online map as it stood at frame t. The formula and the
inputs f_obs / obs_depth are exactly the online ones; the map is not. This over-states the
geometry cue where the terminal map is better converged than the online one, and it is
still far closer to the truth than the flow-only figure it replaces.

Usage (2060 is plenty; ~1-2 min/sequence at stride 5):
  python scripts/probe_reliability_separability.py --runs-root /tmp/mech_runs --stride 5
"""

import argparse
import glob
import json
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.probe_hole_ghost import load_run, render_frame  # noqa: E402
from utils.reliability_signal import (  # noqa: E402
    compute_reliability_tracking_weight,
    get_reliability_signal_config,
    relative_pose_target_from_source,
)

# short name -> (dataset dir, regime label). Runs are the mask-free MRCS arm (WP-A K1R1L1).
SEQUENCES = {
    "mv_no_box2": ("/data/Datasets/Bonn/rgbd_bonn_moving_nonobstructing_box2", "纯物"),
    "pt2": ("/data/Datasets/Bonn/rgbd_bonn_person_tracking2", "纯人（mask-free 成功）"),
    "pt1": ("/data/Datasets/Bonn/rgbd_bonn_person_tracking", "纯人（mask-free 失败边界）"),
    "balloon": ("/data/Datasets/Bonn/rgbd_bonn_balloon", "混合"),
}
MODES = ("both", "flow-only", "geometry-only")


def auc(scores_pos, scores_neg, max_n=200000):
    """Rank-based AUC, subsampled so a 300k-pixel frame stack stays cheap."""
    if len(scores_pos) == 0 or len(scores_neg) == 0:
        return float("nan")
    rng = np.random.default_rng(0)
    if len(scores_pos) > max_n:
        scores_pos = rng.choice(scores_pos, max_n, replace=False)
    if len(scores_neg) > max_n:
        scores_neg = rng.choice(scores_neg, max_n, replace=False)
    allv = np.concatenate([scores_pos, scores_neg])
    order = allv.argsort()
    ranks = np.empty(len(allv), dtype=np.float64)
    ranks[order] = np.arange(1, len(allv) + 1)
    n_pos, n_neg = len(scores_pos), len(scores_neg)
    return float((ranks[:n_pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def mask_index(seq_dir):
    out = {}
    for p in glob.glob(os.path.join(seq_dir, "dynamic_mask_gtmc", "*.png")):
        out[os.path.splitext(os.path.basename(p))[0]] = p
    return out


def flow_index(seq_dir):
    out = {}
    for p in glob.glob(os.path.join(seq_dir, "flow_raft", "*.npy")):
        out[os.path.splitext(os.path.basename(p))[0]] = p
    return out


def analyse(name, run_dir, seq_dir, stride):
    from PIL import Image

    cfg, dataset, gaussians, trj = load_run(run_dir, seq_dir)
    rc = get_reliability_signal_config(cfg)
    geo_floor = float(rc.get("geo_scale_floor", 0.0))
    flow_floor = float(rc.get("flow_scale_floor", 0.0))

    pose_by_id = {int(f): np.asarray(T, dtype=np.float64)
                  for f, T in zip(trj["trj_id"], trj["trj_est"])}
    ids = sorted(pose_by_id)
    masks, flows = mask_index(seq_dir), flow_index(seq_dir)

    acc = {m: {"dyn": [], "sta": [], "wdyn": [], "wsta": []} for m in MODES}
    n_used, dyn_frac = 0, []
    for k, fid in enumerate(ids):
        if k == 0 or k % stride:
            continue
        stem = os.path.splitext(os.path.basename(dataset.depth_paths[fid]))[0]
        if stem not in masks or stem not in flows:
            continue
        prev_id = ids[k - 1]
        _, opacity, render_depth = render_frame(dataset, gaussians, cfg, pose_by_id[fid], fid)
        obs_depth = torch.from_numpy(
            np.asarray(Image.open(dataset.depth_paths[fid]), dtype=np.float32)
            / dataset.depth_scale
        ).to(render_depth.device)
        f_obs = torch.from_numpy(np.load(flows[stem]).astype(np.float32)).to(render_depth.device)
        if f_obs.shape[:2] != obs_depth.shape[-2:]:
            continue
        R, t = relative_pose_target_from_source(
            torch.from_numpy(pose_by_id[fid]).float(),
            torch.from_numpy(pose_by_id[prev_id]).float(),
        )
        dyn = np.asarray(Image.open(masks[stem])) > 0
        if dyn.mean() < 1e-4 or dyn.mean() > 0.9:
            continue  # degenerate frame: no mover, or mask covers everything
        dyn_t = torch.from_numpy(dyn).to(render_depth.device)

        for mode in MODES:
            s, w, _, _ = compute_reliability_tracking_weight(
                obs_depth.squeeze(), render_depth.squeeze(), opacity.squeeze(), f_obs,
                R.to(render_depth.device), t.to(render_depth.device),
                dataset.fx, dataset.fy, dataset.cx, dataset.cy,
                geo_scale_floor=geo_floor, flow_scale_floor=flow_floor, mode=mode,
            )
            ev = (1.0 - s).detach()          # dynamic evidence
            wv = w.detach()
            acc[mode]["dyn"].append(ev[dyn_t].float().cpu().numpy())
            acc[mode]["sta"].append(ev[~dyn_t].float().cpu().numpy())
            acc[mode]["wdyn"].append(wv[dyn_t].float().cpu().numpy())
            acc[mode]["wsta"].append(wv[~dyn_t].float().cpu().numpy())
        dyn_frac.append(float(dyn.mean()))
        n_used += 1
        if n_used % 20 == 0:
            print(f"  [{name}] {n_used} frames", flush=True)

    rows = []
    for mode in MODES:
        d = np.concatenate(acc[mode]["dyn"]) if acc[mode]["dyn"] else np.array([])
        s_ = np.concatenate(acc[mode]["sta"]) if acc[mode]["sta"] else np.array([])
        wd = np.concatenate(acc[mode]["wdyn"]) if acc[mode]["wdyn"] else np.array([])
        ws = np.concatenate(acc[mode]["wsta"]) if acc[mode]["wsta"] else np.array([])
        rows.append({
            "sequence": name, "mode": mode, "frames": n_used,
            "dyn_pixel_frac": float(np.mean(dyn_frac)) if dyn_frac else float("nan"),
            "auc_1_minus_s": auc(d, s_),
            "sep_ratio_1_minus_s": float(d.mean() / s_.mean()) if len(s_) and s_.mean() > 0 else float("nan"),
            "mean_w_dynamic": float(wd.mean()) if len(wd) else float("nan"),
            "mean_w_static": float(ws.mean()) if len(ws) else float("nan"),
            "w_suppression": float(ws.mean() / wd.mean()) if len(wd) and wd.mean() > 0 else float("nan"),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", default="/tmp/mech_runs")
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--out", default="results/evidence/reliability_separability.json")
    ap.add_argument("--sequences", nargs="*", default=list(SEQUENCES))
    args = ap.parse_args()

    torch.set_grad_enabled(False)
    all_rows = []
    for name in args.sequences:
        seq_dir, regime = SEQUENCES[name]
        run_dir = os.path.join(args.runs_root, name)
        if not os.path.isfile(os.path.join(run_dir, "config.yml")):
            print(f"skip {name}: no run at {run_dir}")
            continue
        print(f"== {name} ({regime}) ==", flush=True)
        rows = analyse(name, run_dir, seq_dir, args.stride)
        for r in rows:
            r["regime"] = regime
            print(f"  {r['mode']:<14} AUC={r['auc_1_minus_s']:.3f} "
                  f"sep={r['sep_ratio_1_minus_s']:.2f} "
                  f"w_static/w_dyn={r['w_suppression']:.2f} (n={r['frames']})", flush=True)
        all_rows += rows

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
