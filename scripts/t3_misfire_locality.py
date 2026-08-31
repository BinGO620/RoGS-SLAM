#!/usr/bin/env python3
"""T3 misfire LOCALITY diagnostic — is the kill-line breach a real misfire or a
mask-definition artifact? (exp32, 2026-08-20)

The misfire guardrail asks what share of overridden Gaussians project into GT-STATIC
pixels. On balloon that came back 83.8% against a 5% kill-line, and a number that
extreme has to be attacked before it is believed. There are two very different worlds
that produce a high number:

  (a) ARTIFACT. GT-MC marks only pixels whose OBSERVED motion is inconsistent with ego
      motion, so a slow torso, or the 7 px of mask dilation, sits just OUTSIDE the GT-MC
      silhouette while still belonging to the moving object. Then the overrides would
      cluster a few pixels away from GT-MC-dynamic territory.
  (b) REAL. The overrides land on genuinely static structure -- far from anything the
      GT says is moving.

Distance to the nearest GT-MC-dynamic pixel separates them, and a random-pixel baseline
on the same frames says how much of any clustering is just "the mover is large".

Usage:
    python scripts/t3_misfire_locality.py --run <run_dir> --seq-dir <dataset seq dir>
"""

import argparse
import csv
import glob
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def frame_to_mask(seq_dir):
    from utils.geometry_metrics import load_tum_associations
    frames = load_tum_associations(seq_dir)
    masks = {os.path.splitext(os.path.basename(p))[0]: p
             for p in glob.glob(os.path.join(seq_dir, "dynamic_mask_gtmc", "*.png"))}
    out = {}
    for i, f in enumerate(frames):
        stem = os.path.splitext(os.path.basename(f["depth_path"]))[0]
        if stem in masks:
            out[i] = masks[stem]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="T3 run dir (or its inner run dir)")
    ap.add_argument("--seq-dir", required=True)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    hits = glob.glob(os.path.join(args.run, "**", "alpha_semantic", "overrides.csv"),
                     recursive=True)
    if not hits:
        raise SystemExit(f"no overrides.csv under {args.run}")
    with open(sorted(hits)[0], newline="") as fh:
        rows = list(csv.DictReader(fh))

    idx = frame_to_mask(args.seq_dir)
    cache, dists, fracs, unmatched = {}, [], [], 0
    for r in rows:
        mp = idx.get(int(r["kf_uid"]))
        if mp is None:
            unmatched += 1
            continue
        if mp not in cache:
            m = np.array(Image.open(mp)) > 127
            cache[mp] = (ndimage.distance_transform_edt(~m), float(m.mean()))
        dt, frac = cache[mp]
        u, v = int(round(float(r["u"]))), int(round(float(r["v"])))
        if not (0 <= u < dt.shape[1] and 0 <= v < dt.shape[0]):
            unmatched += 1
            continue
        dists.append(float(dt[v, u]))
        fracs.append(frac)

    d = np.array(dists)
    rng = np.random.default_rng(args.seed)
    base = []
    for dt, _ in cache.values():
        vs = rng.integers(0, dt.shape[0], 200)
        us = rng.integers(0, dt.shape[1], 200)
        base.extend(dt[vs, us].tolist())
    b = np.array(base)

    out = {
        "n_overrides": int(d.size), "n_frames": len(cache), "n_unmatched": unmatched,
        "gtmc_dynamic_frac_mean": float(np.mean(fracs)) if fracs else None,
        "inside_gtmc_dynamic": float((d == 0).mean()),
        "baseline_inside": float((b == 0).mean()),
        "within_px": {int(t): float((d <= t).mean()) for t in (2, 5, 10, 15, 20, 30, 50, 100)},
        "baseline_within_15px": float((b <= 15).mean()),
        "median_dist_px": float(np.median(d)), "p90_dist_px": float(np.percentile(d, 90)),
        "max_dist_px": float(d.max()), "baseline_median_dist_px": float(np.median(b)),
    }
    print(json.dumps(out, indent=2))
    print(f"\nenrichment vs random pixel: inside {out['inside_gtmc_dynamic']:.1%} vs "
          f"{out['baseline_inside']:.1%} = {out['inside_gtmc_dynamic'] / max(out['baseline_inside'], 1e-9):.2f}x")
    print("far-field share (>15 px from ANY moving pixel): "
          f"{1 - out['within_px'][15]:.1%}  -- this is the part no mask-boundary story explains")

    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print(f"wrote {args.json_out}")


if __name__ == "__main__":
    main()
