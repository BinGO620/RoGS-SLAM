#!/usr/bin/env python3
"""WP-HS Step 1: per-sequence person-area characterization (no GPU training, inference only).

Answers ONE question, frozen before any number is looked at (see
``results/evidence/wphs_person_area_characterization.md`` §Prereg):

    Does the sequence-level mean person-mask area ratio, thresholded at theta=20%,
    cleanly separate the P7 geometry-preferring sequences {balloon, mv_no_box2, pt2}
    from the P7 both-preferring sequence {mv_no_box}?

The statistic MUST be the same mask the mask-ON arm consumes, otherwise the
"selector is computable from what the system already has" claim is void:
Mask R-CNN ResNet50-FPN, COCO person=1, conf>=0.5, mask>=0.5, dilate_px=7
(``utils/semantic_mask.compute_semantic_dynamic_mask`` is called directly, not
reimplemented), over the exact frame list the SLAM consumes (``TUMParser``,
frame_rate=32) with the same undistortion (``TUMDataset.__getitem__``).

Usage:
  python scripts/wphs_person_area_stats.py \
      --out results/evidence/wphs_person_area_stats.json
"""

import argparse
import json
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_utils import load_config  # noqa: E402
from utils.dataset import load_dataset  # noqa: E402
from utils.semantic_mask import compute_semantic_dynamic_mask  # noqa: E402

# short name -> per-sequence config (dataset_path + calibration live there)
SEQUENCES = {
    "balloon": "configs/rgbd/bonn/balloon.yaml",
    "balloon2": "configs/rgbd/bonn/balloon2.yaml",
    "pt1": "configs/rgbd/bonn/person_tracking.yaml",
    "pt2": "configs/rgbd/bonn/person_tracking2.yaml",
    "mv_no_box": "configs/rgbd/bonn/moving_nonobstructing_box.yaml",
    "mv_no_box2": "configs/rgbd/bonn/moving_nonobstructing_box2.yaml",
}

# P7 3-seed verdict (results/evidence/p7_cuesplit_verdict.md): lowest-mean-ATE arm.
# pt1/balloon2 were NOT in P7 -> unknown, they are what H1 would predict on.
P7_BEST_ARM = {
    "balloon": "geo",
    "mv_no_box": "both",
    "mv_no_box2": "geo",
    "pt2": "geo",
    "balloon2": None,
    "pt1": None,
}

# The mask-ON contract, copied from configs/.../method_combined_maskboth_*.yaml.
MASK_CFG_DILATED = {
    "SemanticMask": {
        "enabled": True,
        "model": "maskrcnn",
        "dynamic_classes": [1],
        "dilate_px": 7,
        "conf_threshold": 0.5,
        "mask_threshold": 0.5,
        "max_mask_ratio": 1.01,  # never return None here: we WANT the raw ratio
    }
}
# robustness view only (not decision-bearing): undilated detector output
MASK_CFG_RAW = {
    "SemanticMask": dict(MASK_CFG_DILATED["SemanticMask"], dilate_px=0)
}


def sequence_stats(name, config_path, device, limit=None):
    config = load_config(config_path)
    dataset = load_dataset(None, config["Dataset"]["dataset_path"], config)
    n = len(dataset.color_paths) if limit is None else min(limit, len(dataset.color_paths))

    ratios_dil, ratios_raw = [], []
    for i in range(n):
        image = dataset[i][0]  # (3,H,W) float [0,1], undistorted exactly as SLAM sees it
        cfg_d = dict(MASK_CFG_DILATED)
        cfg_d["SemanticMask"] = dict(cfg_d["SemanticMask"], device=device)
        cfg_r = dict(MASK_CFG_RAW)
        cfg_r["SemanticMask"] = dict(cfg_r["SemanticMask"], device=device)

        m_dil = compute_semantic_dynamic_mask(cfg_d, image)
        m_raw = compute_semantic_dynamic_mask(cfg_r, image)
        ratios_dil.append(0.0 if m_dil is None else float(m_dil.float().mean()))
        ratios_raw.append(0.0 if m_raw is None else float(m_raw.float().mean()))
        if (i + 1) % 50 == 0:
            print(f"  [{name}] {i + 1}/{n}", flush=True)

    d = np.asarray(ratios_dil, dtype=np.float64)
    r = np.asarray(ratios_raw, dtype=np.float64)
    return {
        "sequence": name,
        "config": config_path,
        "dataset_path": config["Dataset"]["dataset_path"],
        "n_frames": int(n),
        "p7_best_arm": P7_BEST_ARM.get(name),
        # PRIMARY (decision-bearing): dilate_px=7, mean over frames
        "mean_ratio_dil7": float(d.mean()),
        "median_ratio_dil7": float(np.median(d)),
        "std_ratio_dil7": float(d.std(ddof=1)) if n > 1 else 0.0,
        "p10_ratio_dil7": float(np.percentile(d, 10)),
        "p90_ratio_dil7": float(np.percentile(d, 90)),
        "max_ratio_dil7": float(d.max()),
        # SECONDARY (robustness only)
        "mean_ratio_raw": float(r.mean()),
        "median_ratio_raw": float(np.median(r)),
        "detection_rate": float((r > 0.0).mean()),  # frames with any person pixel
        "per_frame_ratio_dil7": [round(float(v), 6) for v in d],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/evidence/wphs_person_area_stats.json")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--limit", type=int, default=None, help="debug: cap frames/sequence")
    ap.add_argument("--sequences", nargs="*", default=list(SEQUENCES))
    args = ap.parse_args()

    torch.set_grad_enabled(False)
    out = {
        "mask_contract": MASK_CFG_DILATED["SemanticMask"],
        "frame_source": "TUMParser (frame_rate=32) + TUMDataset undistortion — identical to SLAM",
        "sequences": {},
    }
    for name in args.sequences:
        print(f"== {name} ==", flush=True)
        out["sequences"][name] = sequence_stats(
            name, SEQUENCES[name], args.device, args.limit
        )
        s = out["sequences"][name]
        print(
            f"  -> mean={s['mean_ratio_dil7'] * 100:.2f}% "
            f"median={s['median_ratio_dil7'] * 100:.2f}% "
            f"det_rate={s['detection_rate'] * 100:.1f}% (n={s['n_frames']})",
            flush=True,
        )

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nwrote {args.out}")

    # compact table for the evidence doc
    print("\n| seq | P7 best arm | mean(dil7) | median | p10 | p90 | mean(raw) | det rate | n |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for name in args.sequences:
        s = out["sequences"][name]
        print(
            f"| {name} | {s['p7_best_arm'] or '—'} | {s['mean_ratio_dil7'] * 100:.2f}% "
            f"| {s['median_ratio_dil7'] * 100:.2f}% | {s['p10_ratio_dil7'] * 100:.2f}% "
            f"| {s['p90_ratio_dil7'] * 100:.2f}% | {s['mean_ratio_raw'] * 100:.2f}% "
            f"| {s['detection_rate'] * 100:.1f}% | {s['n_frames']} |"
        )


if __name__ == "__main__":
    main()
