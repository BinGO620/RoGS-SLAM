#!/usr/bin/env python3
"""M0: does the Task-2 exclusion_mask actually leave a non-degenerate MAD domain?

WHY THIS EXISTS (results/evidence/mrcs_retrofit_feasibility.md, NEXT_SESSION_PROMPT.md §1.2).
Task 2 hard-removes ``exclusion_mask`` pixels from the scale domain of
``cauchy_tracking_weight``. Every removed pixel has ``d > 0.5`` by construction
(``e_flow > 0.5 => d >= e_flow``), so the removal can only RAISE the share of pixels whose
``d`` is exactly 0 -- and ``robust_anomaly`` pins a large exactly-zero mass by design (it
returns 0 at or below the frame median, and 0 on every invalid pixel). Once that share
crosses 50%, ``median(d) = 0`` AND ``MAD(d) = 0``, so ``tau`` collapses to ``eps`` and
``w`` degenerates into a hard binary mask -- the exact pathology Task 2 exists to avoid.

    zero_frac_after = zero_frac_before / (1 - excl_frac)
    Task 2 is live only while zero_frac_after < 0.5.

Measured on the flow channel alone, tau is ALREADY collapsed, so the question can only be
answered in ``both`` mode, which needs ``v*g`` and therefore a render. This probe supplies
it OFFLINE: re-render the run's terminal map at the run's own estimated poses, rebuild the
signal with the ONLINE function (``compute_reliability_tracking_weight``), and report the
before/after statistics. NO online source file is touched.

HONEST APPROXIMATION (same one reliability_separability_verdict.md declares): the render
comes from the TERMINAL map, not the online map as it stood at frame t. Note the marginal
zero-fractions are pinned near 1/2 by the median rule regardless of map quality, so this
approximation moves the JOINT zero-fraction (how the two cues' zero-sets overlap) rather
than the marginals -- the quantity under test is the joint, so read it as an estimate.

POSE CONVENTION. ``trj_est`` is c2w (``eval_utils.save_final_tracking_raw`` stores
``inv(w2c)``). The online path feeds ``relative_pose_target_from_source(w2c_prev, w2c_cur)``
(slam_frontend.py:1111-1113), i.e. T_{t-1<-t}. This probe reproduces that exactly.

Usage:
  python scripts/probe_mad_exclusion.py --run-dir <run> --seq-dir <dataset> --label balloon
"""

import argparse
import glob
import json
import os
import sys

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.probe_hole_ghost import load_run, render_frame  # noqa: E402
from utils.reliability_signal import (  # noqa: E402
    _MAD_CONST,
    fuse_static_evidence,
    geometric_anomaly,
    get_reliability_signal_config,
    assemble_flow_consensus,
    relative_pose_target_from_source,
    rigid_flow,
)
from utils.semantic_mask import compute_semantic_dynamic_mask  # noqa: E402


def tau_of(d):
    """Exactly cauchy_tracking_weight's scale, on whatever domain is passed in."""
    if d.numel() == 0:
        return float("nan"), float("nan"), float("nan")
    med = d.median()
    mad = (d - med).abs().median()
    return float(med), float(mad), float(med + _MAD_CONST * mad + 1e-6)


def flow_index(seq_dir, subdir="flow_raft"):
    return {
        os.path.splitext(os.path.basename(p))[0]: p
        for p in glob.glob(os.path.join(seq_dir, subdir, "*.npy"))
    }


def analyse(run_dir, seq_dir, label, stride, e_thresh, want_semantic, max_frames):
    cfg, dataset, gaussians, trj = load_run(run_dir, seq_dir)
    rc = get_reliability_signal_config(cfg)
    geo_floor = float(rc.get("geo_scale_floor", 0.0))
    flow_floor = float(rc.get("flow_scale_floor", 0.0))
    mode = str(rc.get("mode", "both"))

    pose_by_id = {int(f): np.asarray(T, dtype=np.float64)
                  for f, T in zip(trj["trj_id"], trj["trj_est"])}
    ids = sorted(pose_by_id)
    flows = flow_index(seq_dir, rc.get("flow_subdir", "flow_raft"))

    rows = []
    for k, fid in enumerate(ids):
        if k == 0 or k % stride:
            continue
        stem = os.path.splitext(os.path.basename(dataset.depth_paths[fid]))[0]
        if stem not in flows:
            continue
        prev_id = ids[k - 1]
        _, opacity, render_depth = render_frame(
            dataset, gaussians, cfg, pose_by_id[fid], fid
        )
        dev = render_depth.device
        obs_depth = torch.from_numpy(
            np.asarray(Image.open(dataset.depth_paths[fid]), dtype=np.float32)
            / dataset.depth_scale
        ).to(dev)
        f_obs = torch.from_numpy(np.load(flows[stem]).astype(np.float32)).to(dev)
        if f_obs.shape[:2] != obs_depth.shape[-2:]:
            continue

        # T_{t-1<-t} from w2c poses -- the ONLINE convention (slam_frontend.py:1111-1113)
        w2c_cur = torch.from_numpy(np.linalg.inv(pose_by_id[fid])).float().to(dev)
        w2c_prev = torch.from_numpy(np.linalg.inv(pose_by_id[prev_id])).float().to(dev)
        R, t = relative_pose_target_from_source(w2c_prev, w2c_cur)

        obs = obs_depth.squeeze()
        ren = render_depth.squeeze()
        opa = opacity.squeeze()
        g = geometric_anomaly(obs, ren, scale_floor=geo_floor)
        f_static, fs_valid = rigid_flow(
            obs, dataset.fx, dataset.fy, dataset.cx, dataset.cy, R, t
        )
        valid = fs_valid & torch.isfinite(f_obs).all(dim=-1)
        e_flow, flow_valid = assemble_flow_consensus(
            [f_obs], [f_static], [valid], scale_floor=flow_floor
        )
        s = fuse_static_evidence(g, e_flow, opa, mode=mode)
        d = (1.0 - s.detach().float().clamp(0.0, 1.0))

        e_filled = torch.nan_to_num(e_flow, nan=0.0)
        excl_flow = flow_valid & (e_filled > e_thresh)

        sem = None
        if want_semantic:
            image, _, _ = dataset[fid]                       # (3,H,W) float [0,1]
            m = compute_semantic_dynamic_mask(cfg, image)
            if m is not None:
                sem = m.squeeze(0).to(dev, torch.bool)
        excl_sem = (sem | excl_flow) if sem is not None else None

        row = {"label": label, "frame": int(fid), "mode": mode}
        m0, a0, t0 = tau_of(d.reshape(-1))
        z0 = float((d == 0).float().mean())
        w0 = 1.0 / (1.0 + (d / t0) ** 2)
        row.update({"mad_zero_frac_before": z0, "mad_median_before": m0,
                    "mad_mad_before": a0, "mad_tau_before": t0,
                    "mean_w_before": float(w0.mean())})

        for tag, ex in (("flow", excl_flow), ("semflow", excl_sem)):
            if ex is None:
                continue
            keep = ~ex
            kept = d[keep]
            m1, a1, t1 = tau_of(kept.reshape(-1))
            z1 = float((kept == 0).float().mean()) if kept.numel() else float("nan")
            w1 = 1.0 / (1.0 + (d / t1) ** 2) if np.isfinite(t1) and t1 > 0 else w0
            row.update({
                f"mad_excl_frac_{tag}": float(ex.float().mean()),
                f"mad_zero_frac_after_{tag}": z1,
                f"mad_median_after_{tag}": m1,
                f"mad_tau_after_{tag}": t1,
                f"mean_w_after_{tag}": float(w1.mean()),
                f"mad_live_{tag}": int(bool(np.isfinite(z1) and z1 < 0.5)),
            })
        if sem is not None:
            row["sem_frac"] = float(sem.float().mean())
        rows.append(row)
        if len(rows) % 10 == 0:
            print(f"  [{label}] {len(rows)} frames", flush=True)
        if max_frames and len(rows) >= max_frames:
            break
    return rows


def summarise(rows, label):
    if not rows:
        return {"label": label, "frames": 0}
    def col(k):
        v = [r[k] for r in rows if k in r and r[k] == r[k]]
        return np.array(v) if v else np.array([np.nan])
    out = {"label": label, "frames": len(rows), "mode": rows[0]["mode"]}
    for k in ("mad_zero_frac_before", "mad_median_before", "mad_tau_before", "mean_w_before"):
        out[k + "_mean"] = float(np.nanmean(col(k)))
    for tag in ("flow", "semflow"):
        if f"mad_zero_frac_after_{tag}" not in rows[0]:
            continue
        out[f"excl_frac_{tag}_mean"] = float(np.nanmean(col(f"mad_excl_frac_{tag}")))
        za = col(f"mad_zero_frac_after_{tag}")
        out[f"zero_frac_after_{tag}_mean"] = float(np.nanmean(za))
        out[f"zero_frac_after_{tag}_p50"] = float(np.nanpercentile(za, 50))
        out[f"zero_frac_after_{tag}_p95"] = float(np.nanpercentile(za, 95))
        out[f"tau_after_{tag}_mean"] = float(np.nanmean(col(f"mad_tau_after_{tag}")))
        out[f"mean_w_after_{tag}"] = float(np.nanmean(col(f"mean_w_after_{tag}")))
        live = col(f"mad_live_{tag}")
        out[f"LIVE_FRAC_{tag}"] = float(np.nanmean(live))   # ← 拍板① 的判决量
    if "sem_frac" in rows[0]:
        out["sem_frac_mean"] = float(np.nanmean(col("sem_frac")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--seq-dir", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--e-thresh", type=float, default=0.5)
    ap.add_argument("--max-frames", type=int, default=40)
    ap.add_argument("--semantic", action="store_true",
                    help="also evaluate exclusion = semantic | (e_flow>thr) (combined arm)")
    ap.add_argument("--out", default="results/evidence/m0_mad_exclusion")
    args = ap.parse_args()

    rows = analyse(args.run_dir, args.seq_dir, args.label, args.stride,
                   args.e_thresh, args.semantic, args.max_frames)
    summary = summarise(rows, args.label)
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"m0_{args.label}.json"), "w") as fh:
        json.dump({"summary": summary, "rows": rows, "run_dir": args.run_dir}, fh, indent=2)
    print(f"  wrote {args.out}/m0_{args.label}.json")


if __name__ == "__main__":
    main()
