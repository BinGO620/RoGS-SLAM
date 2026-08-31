#!/usr/bin/env python3
"""Freeze the GT-pose motion-consistency dynamic mask for a Bonn RGB-D sequence.

Produces the method-INDEPENDENT dynamic oracle the hole-safe static-background eval
(``utils/static_eval.py``) excludes -- required for the make-or-break PRIMARY
sequence ``moving_obstructing_box``, which ships no segmentation mask. Writes one bool
PNG per frame keyed by its DEPTH-file stem (timestamp), so the eval loader associates
a keyframe to its mask by timestamp regardless of how the run selected frames, plus a
``manifest.json`` recording the exact params + a sha256 of the whole stack (frozen +
hashed, doc-11) and a handful of RGB overlays for visual spot-checking.

Usage:
  python scripts/build_static_eval_mask.py \
      --sequence-dir /data/Datasets/Bonn/rgbd_bonn_moving_obstructing_box --overlays 6
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.geometry_metrics import load_tum_associations  # noqa: E402
from utils.gtmc_mask import (  # noqa: E402
    CALIB_BONN,
    build_dynamic_masks_robust,
    masks_sha256,
    robust_motion_seeds,
    undistort_depths,
    undistort_images,
)

# Robustness of this ONE universal parameter set (MAD constants + physical noise
# floors, no per-scene threshold) has been validated on 3 Bonn sequences only, spanning
# the three regimes that matter for the clean-map claim: an OBJECT-mover (the PRIMARY,
# mask-less moving_obstructing_box), a PERSON-mover (person_tracking2, cross-checkable
# against the shipped semantic person mask), and a fully-STATIC control (static_close_far,
# the false-positive floor). Recorded verbatim into every manifest so the freeze scope is
# on disk, not just asserted. Known limitation: camera-motion / motion-blur frames over-
# fill uniformly in the CONSERVATIVE (no-leak) direction -- movers never leak into
# "static"; only some static pixels are over-excluded, identically for every arm. A
# method-independent blur/motion frame-gate is a deferred P-A refinement, off the E1
# critical path (see 03-knowledges/11 §5 + 04-ours/02 Honest limitations).
VALIDATION = {
    "validated_on": ["moving_obstructing_box", "static_close_far", "person_tracking2"],
    "roles": {
        "moving_obstructing_box": "object-mover (PRIMARY; ships no seg_mask)",
        "person_tracking2": "person-mover (cross-check vs shipped semantic person mask)",
        "static_close_far": "fully-static control (false-positive floor)",
    },
    "n_bonn_eval_sequences": 20,
    "coverage": "3/20",
    "known_limitation": (
        "camera-motion / motion-blur frames over-fill uniformly in the conservative "
        "(no-leak) direction; movers never leak into 'static', only some static pixels "
        "are over-excluded (identically for every arm). Method-independent blur/motion "
        "frame-gate deferred -- off the E1 critical path. See 03-knowledges/11 §5 + "
        "04-ours/02 Honest limitations."
    ),
}


def _load(dataset_path):
    frames = load_tum_associations(dataset_path)
    depths, rgb_raw, stems, rgbs = [], [], [], []
    for f in frames:
        d = np.asarray(Image.open(f["depth_path"]), dtype=np.float32) / CALIB_BONN["depth_scale"]
        depths.append(d)
        rgb_raw.append(np.asarray(Image.open(f["rgb_path"]).convert("RGB")))
        stems.append(os.path.splitext(os.path.basename(f["depth_path"]))[0])
        rgbs.append(f["rgb_path"])
    c2w = np.stack([np.asarray(f["c2w"], dtype=np.float64) for f in frames])
    # Undistort depth + RGB into the pinhole/eval pixel space (the loader undistorts
    # RGB but not depth; the eval compares undistorted renders). Grayscale [0,1] images
    # feed the photometric rigid-warp residual.
    depths = undistort_depths(depths)
    images = [im.astype(np.float32).mean(axis=2) / 255.0 for im in undistort_images(rgb_raw)]
    return depths, images, c2w, stems, rgbs


def _valid_fraction(mask, depth, dmax):
    valid = np.isfinite(depth) & (depth > 0.0) & (depth <= dmax)
    nv = int(valid.sum())
    return (int((mask & valid).sum()) / nv) if nv else 0.0


def _save_overlay(rgb_path, mask, out_path):
    rgb = np.asarray(Image.open(rgb_path).convert("RGB"))
    rgb = undistort_images([rgb])[0].astype(np.float32)  # match the mask's undistorted space
    if rgb.shape[:2] != mask.shape:
        return
    tint = rgb.copy()
    tint[mask] = 0.45 * rgb[mask] + 0.55 * np.array([255.0, 0.0, 0.0])
    Image.fromarray(tint.astype(np.uint8)).save(out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sequence-dir", required=True)
    ap.add_argument("--out-subdir", default="dynamic_mask_gtmc")
    # universal (scene-independent) parameters: robustness constants + physical floors.
    ap.add_argument("--persist", type=int, default=2)
    ap.add_argument("--neighbors", type=int, nargs="+", default=[-2, -1, 1, 2])
    ap.add_argument("--dmax", type=float, default=15.0)
    ap.add_argument("--k-geo", type=float, default=2.5, help="MAD multiplier, geometric")
    ap.add_argument("--k-photo", type=float, default=2.5, help="MAD multiplier, photometric")
    ap.add_argument("--geo-floor", type=float, default=0.05, help="depth noise floor (m)")
    ap.add_argument("--photo-floor", type=float, default=0.02, help="grayscale noise floor")
    ap.add_argument("--min-seed-px", type=int, default=8)
    ap.add_argument("--min-seed-frac", type=float, default=0.05)
    ap.add_argument("--seed-open-radius", type=int, default=2)
    ap.add_argument("--close-radius", type=int, default=2)
    ap.add_argument("--dilate-radius", type=int, default=4)
    ap.add_argument("--overlays", type=int, default=0, help="save N evenly-spaced RGB overlays")
    args = ap.parse_args()

    depths, images, c2w, stems, rgbs = _load(args.sequence_dir)
    n = len(depths)
    print(f"loaded {n} frames from {args.sequence_dir}")

    seeds = robust_motion_seeds(
        depths, images, c2w, CALIB_BONN, tuple(args.neighbors), args.persist, args.dmax,
        args.k_geo, args.k_photo, args.geo_floor, args.photo_floor,
    )
    masks = build_dynamic_masks_robust(
        depths, images, c2w, CALIB_BONN, tuple(args.neighbors), args.persist, args.dmax,
        args.k_geo, args.k_photo, args.geo_floor, args.photo_floor,
        min_seed_px=args.min_seed_px, min_seed_frac=args.min_seed_frac,
        seed_open_radius=args.seed_open_radius, close_radius=args.close_radius,
        dilate_radius=args.dilate_radius,
    )

    out_dir = os.path.join(args.sequence_dir, args.out_subdir)
    os.makedirs(out_dir, exist_ok=True)
    for stem, m in zip(stems, masks):
        Image.fromarray((m.astype(np.uint8) * 255), mode="L").save(
            os.path.join(out_dir, f"{stem}.png")
        )

    seed_frac = np.array([_valid_fraction(s, d, args.dmax) for s, d in zip(seeds, depths)])
    mask_frac = np.array([_valid_fraction(m, d, args.dmax) for m, d in zip(masks, depths)])
    manifest = {
        "sequence_dir": os.path.abspath(args.sequence_dir),
        "n_frames": n,
        "method": "gtmc-robust: MAD geo&photo rigid-consistency seeds -> depth region-grow",
        "params": {
            "persist": args.persist, "neighbors": args.neighbors, "dmax": args.dmax,
            "k_geo": args.k_geo, "k_photo": args.k_photo, "geo_floor": args.geo_floor,
            "photo_floor": args.photo_floor, "min_seed_px": args.min_seed_px,
            "min_seed_frac": args.min_seed_frac, "seed_open_radius": args.seed_open_radius,
            "close_radius": args.close_radius, "dilate_radius": args.dilate_radius,
            "calib": CALIB_BONN,
        },
        "sha256": masks_sha256(masks),
        "validation": VALIDATION,
        "coverage_seeds": {
            "mean": float(seed_frac.mean()), "median": float(np.median(seed_frac)),
            "max": float(seed_frac.max()),
        },
        "coverage_mask": {
            "mean": float(mask_frac.mean()), "median": float(np.median(mask_frac)),
            "max": float(mask_frac.max()),
        },
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    if args.overlays > 0:
        ov_dir = os.path.join(out_dir, "_overlay")
        os.makedirs(ov_dir, exist_ok=True)
        for i in np.linspace(0, n - 1, min(args.overlays, n), dtype=int):
            _save_overlay(rgbs[i], masks[i], os.path.join(ov_dir, f"{stems[i]}.png"))

    print(
        f"wrote {n} masks -> {out_dir}\n"
        f"  seed  coverage (of valid-depth px): mean={seed_frac.mean():.3f} "
        f"median={np.median(seed_frac):.3f} max={seed_frac.max():.3f}\n"
        f"  mask  coverage (of valid-depth px): mean={mask_frac.mean():.3f} "
        f"median={np.median(mask_frac):.3f} max={mask_frac.max():.3f}\n"
        f"  sha256={manifest['sha256'][:16]}...  manifest+overlays in {out_dir}"
    )


if __name__ == "__main__":
    main()
