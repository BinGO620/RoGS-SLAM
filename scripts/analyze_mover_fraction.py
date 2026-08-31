#!/usr/bin/env python3
"""GT-pose motion-consistency mover-fraction diagnostic (eval-only, CPU, method-independent).

For each frame ``t`` of a Bonn RGB-D sequence, estimate the fraction of pixels
that belong to a MOVING object, expressed as a fraction of valid (mappable)
depth pixels -- i.e. the mover fraction of the MAP the SLAM back-end would ingest.

Method (doc-10 kill-risk #2 precondition): a pixel of frame ``t`` is a "mover"
iff, after back-projecting it to a world point with the GROUND-TRUTH pose and
reprojecting into temporal neighbours ``s in {t-2,t-1,t+1,t+2}``, the reprojected
depth disagrees with the neighbour's observed depth by ``> thresh`` in ``>=
persist`` of the neighbours where a comparison was available. Multi-neighbour
agreement is exactly what separates a genuine mover (persistently inconsistent)
from an occlusion boundary (transiently inconsistent in ~1 neighbour). GT poses
only => independent of any SLAM estimate or learned mask.

Why this number matters: doc-10 says MAD-style threshold-free fusion breaks when
> 50% of pixels are dynamic. ``moving_obstructing_box(2)`` is the make-or-break
primary sequence; if the share of frames with mover-fraction > 0.5 exceeds half,
we add a lower-dynamic fallback control sequence (balloon / moving_no_box) before
committing to it as the headline.

Caveat: works in raw (distorted) pixel space with a pinhole model. Bonn lens
distortion (k1~0.04) is small and largely cancels between adjacent same-lens
frames, which is adequate for a coarse >50%-type decision (not a per-pixel mask).
"""

import argparse
import csv
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.geometry_metrics import load_tum_associations  # noqa: E402

# Bonn shares one calibration across sequences (configs/rgbd/bonn/base_config.yaml).
CALIB = dict(
    fx=542.822841, fy=542.576870, cx=315.593520, cy=237.756098,
    depth_scale=5000.0, width=640, height=480,
)

SEQUENCES = {
    "moving_obstructing_box": "datasets/bonn/rgbd_bonn_moving_obstructing_box",
    "moving_obstructing_box2": "datasets/bonn/rgbd_bonn_moving_obstructing_box2",
    # calibration / false-positive-floor references (static scene, camera moving)
    "static": "datasets/bonn/rgbd_bonn_static",
    "static_close_far": "datasets/bonn/rgbd_bonn_static_close_far",
    "person_tracking2": "datasets/bonn/rgbd_bonn_person_tracking2",
}


def load_sequence(dataset_path):
    frames = load_tum_associations(dataset_path)  # [{rgb_path, depth_path, c2w}]
    depths = [
        np.asarray(Image.open(f["depth_path"]), dtype=np.float32) / CALIB["depth_scale"]
        for f in frames
    ]
    c2w = np.stack([np.asarray(f["c2w"], dtype=np.float64) for f in frames])
    return depths, c2w


def mover_fraction(depths, c2w, calib, thresh, neighbors, persist, dmax, abs_mode=False):
    fx, fy, cx, cy = calib["fx"], calib["fy"], calib["cx"], calib["cy"]
    H, W = calib["height"], calib["width"]
    n = len(depths)
    w2c = np.linalg.inv(c2w)
    uu, vv = np.meshgrid(np.arange(W), np.arange(H))
    uu = uu.ravel()
    vv = vv.ravel()

    rows = []  # (t, n_valid, n_mover, n_covered)
    for t in range(n):
        z = depths[t].ravel()
        valid = np.isfinite(z) & (z > 0.0) & (z <= dmax)
        n_valid = int(valid.sum())
        if n_valid == 0:
            rows.append((t, 0, 0, 0))
            continue
        zt = z[valid]
        xw = c2w[t] @ np.stack(
            [(uu[valid] - cx) * zt / fx, (vv[valid] - cy) * zt / fy, zt, np.ones_like(zt)],
            axis=0,
        )  # 4 x M world points

        inconsistent = np.zeros(n_valid, dtype=np.int32)
        covered = np.zeros(n_valid, dtype=np.int32)
        for dn in neighbors:
            s = t + dn
            if s < 0 or s >= n:
                continue
            xs = w2c[s] @ xw  # 4 x M in neighbour camera frame
            zs = xs[2]
            front = zs > 1e-6
            safe = np.where(front, zs, 1.0)
            us = np.rint(fx * xs[0] / safe + cx).astype(np.int64)
            vs = np.rint(fy * xs[1] / safe + cy).astype(np.int64)
            inside = front & (us >= 0) & (us < W) & (vs >= 0) & (vs < H)
            in_idx = np.nonzero(inside)[0]
            if in_idx.size == 0:
                continue
            dobs = depths[s][vs[inside], us[inside]]
            good = np.isfinite(dobs) & (dobs > 0.0) & (dobs <= dmax)
            g_idx = in_idx[good]
            covered[g_idx] += 1
            # Signed (occlusion-robust) test: a STATIC back-projected point can only be
            # occluded (observed CLOSER, delta<0) or consistent -- never observed FARTHER.
            # delta = observed - expected > +thresh means the expected surface has
            # vanished (we see past it) => it moved. This rejects static occlusion
            # boundaries, which are the dominant false positive of the abs-residual test.
            delta = dobs[good] - zs[inside][good]
            if abs_mode:
                delta = np.abs(delta)
            inconsistent[g_idx] += (delta > thresh).astype(np.int32)

        n_mover = int((inconsistent >= persist).sum())
        rows.append((t, n_valid, n_mover, int((covered >= 1).sum())))
    return rows


def summarize(name, rows):
    frac = np.array(
        [m / v if v > 0 else 0.0 for _, v, m, _ in rows], dtype=np.float64
    )
    n = len(frac)
    print(f"\n===== {name}  ({n} frames) =====")
    print(
        f"mover-fraction  mean={frac.mean():.3f}  median={np.median(frac):.3f}  "
        f"p90={np.percentile(frac, 90):.3f}  max={frac.max():.3f}"
    )
    for lo in (0.3, 0.5):
        k = int((frac > lo).sum())
        print(f"  frames with fraction > {lo:.0%}:  {k}/{n}  ({k / n:.1%})")
    # decile histogram
    edges = np.linspace(0.0, 1.0, 11)
    counts, _ = np.histogram(frac, bins=edges)
    peak = max(1, counts.max())
    print("  histogram (mover-fraction bins):")
    for i in range(10):
        bar = "#" * int(round(40 * counts[i] / peak))
        print(f"    [{edges[i]:.1f},{edges[i + 1]:.1f})  {counts[i]:4d}  {bar}")
    over50 = int((frac > 0.5).sum())
    verdict = "EXCEEDS half -> add fallback control seq" if over50 > n / 2 else "below half -> OK as primary"
    print(f"  DECISION: >50%-fraction frames = {over50}/{n} ({over50 / n:.1%})  =>  {verdict}")
    return frac


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--thresh", type=float, default=0.05, help="depth residual (m) for inconsistency")
    ap.add_argument("--persist", type=int, default=2, help="min neighbours inconsistent to call a mover")
    ap.add_argument("--neighbors", type=int, nargs="+", default=[-2, -1, 1, 2])
    ap.add_argument("--dmax", type=float, default=15.0, help="max valid depth (m)")
    ap.add_argument("--abs", dest="abs_mode", action="store_true",
                    help="use abs residual (contaminated by static occlusion); default is signed contradiction")
    ap.add_argument("--out", default="workspace/dynamic-3dgs-slam/04-ours/data/mover_fraction")
    ap.add_argument("--sequences", nargs="+", default=list(SEQUENCES))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    for name in args.sequences:
        path = SEQUENCES[name]
        if not os.path.isdir(path):
            print(f"SKIP {name}: missing {path}")
            continue
        depths, c2w = load_sequence(path)
        rows = mover_fraction(
            depths, c2w, CALIB, args.thresh, tuple(args.neighbors), args.persist,
            args.dmax, abs_mode=args.abs_mode,
        )
        summarize(name, rows)
        csv_path = os.path.join(args.out, f"{name}.csv")
        with open(csv_path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["frame", "n_valid", "n_mover", "n_covered", "mover_fraction"])
            for t, v, m, c in rows:
                w.writerow([t, v, m, c, f"{(m / v) if v > 0 else 0.0:.6f}"])
        print(f"  wrote {csv_path}")


if __name__ == "__main__":
    main()
