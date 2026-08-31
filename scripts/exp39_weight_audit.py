#!/usr/bin/env python
"""exp39 S2 — mapping-weight shape audit (zero campaign cost, detector inference only).

Answers two questions **before** any GPU batch is dispatched:

1. **How large is the scale confound?** `get_loss_mapping_rgbd` normalises by the full
   H*W pixel count while `slam_backend` adds a fixed-scale isotropic regulariser, so
   raising the dynamic-pixel floor raises the photometric term's magnitude *and* its
   ratio to that regulariser. The scale-matched control arm exists to separate the two
   (codex adversarial review, 2026-08-22). This script measures how big the correction
   c = Sw(soft)/Sw(hard) actually is per floor -- i.e. whether that control is buying
   a large confound or a rounding error.

2. **What is A2's ceiling?** The soft arm re-weights the *semantic* (person) mask. On
   balloon the mover is a person AND a balloon, and COCO-person cannot see the balloon.
   Scoring the weight field against the frozen held-out GTMC motion-consistency mask
   bounds how much of the truly-dynamic area the arm can act on at all.

Both the mask backend and the loss's pixel-validity rules are taken **by import / by
transcription from the run-time definitions**, not re-derived, so the audit cannot
drift from what the run does.

Writes results/evidence/exp39_weight_audit.{md,json} (+ per-frame CSV).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

import cv2
import numpy as np
import torch
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402
from utils.gtmc_mask import frozen_mask_index, load_frozen_mask  # noqa: E402
from utils.mapping_weight import weight_stats  # noqa: E402
from utils.semantic_mask import compute_semantic_dynamic_mask  # noqa: E402

# The arm whose SemanticMask block the Phase-0 treatment inherits. Reading the mask
# backend from the run config -- not duplicating it -- keeps audit and run in lockstep.
ARM_CFG = "configs/rgbd/experiments/t2_mad_quota/t2_eboth_balloon.yaml"
EVIDENCE_MD = "results/evidence/exp39_weight_audit.md"
EVIDENCE_JSON = "results/evidence/exp39_weight_audit.json"
CSV_OUT = "results/evidence/exp39_weight_audit_perframe.csv"

SEQS = {"balloon": "datasets/bonn/rgbd_bonn_balloon"}
FLOORS = [0.0, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0]

# Frozen exp22 anchor (results/evidence/archive_pre_exp32/hd_coverage_anchor.md, cov (a),
# 438 frames). Reproducing it is this audit's apparatus gate: same mask backend, same
# frozen GTMC, same estimator => same number. Comparable only at stride 1.
FROZEN_COV_A = {"balloon": 0.482}
COV_A_TOL = 0.01


def associations(dataset_path):
    """[(rgb_rel, depth_rel)] from the association table the dataset ships."""
    pairs = []
    with open(os.path.join(dataset_path, "associations.txt"), encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4:
                pairs.append((parts[1], parts[3]))
    return pairs


def frame_masks(dataset_path, rgb_rel, depth_rel, config, device):
    """(rgb_valid, depth_valid, dynamic) bool tensors, matching the loss's rules."""
    # Transcribed from get_loss_mapping_rgbd: RGB validity is a boundary test on the GT
    # image, depth validity is gt_depth > 0.01 after the dataset's depth_scale.
    rgb_thresh = float(config["Training"]["rgb_boundary_threshold"])
    depth_scale = float(config["Dataset"]["Calibration"]["depth_scale"])

    image = np.asarray(Image.open(os.path.join(dataset_path, rgb_rel)).convert("RGB"))
    gt_image = torch.from_numpy(image).to(device=device, dtype=torch.float32)
    gt_image = (gt_image / 255.0).permute(2, 0, 1)

    raw_depth = cv2.imread(
        os.path.join(dataset_path, depth_rel), cv2.IMREAD_UNCHANGED
    ).astype(np.float32) / depth_scale
    gt_depth = torch.from_numpy(raw_depth).to(device=device)[None]

    rgb_valid = (gt_image.sum(dim=0) > rgb_thresh)[None]
    depth_valid = gt_depth > 0.01
    dynamic = compute_semantic_dynamic_mask(config, gt_image)
    return rgb_valid, depth_valid, dynamic.to(device=device).view_as(rgb_valid)


def audit_frame(rgb_valid, depth_valid, dynamic, gtmc, floors):
    """Per-floor weight-mass / ESS readings plus the GTMC-scored coverage."""
    static = ~dynamic
    row = {}
    for floor in floors:
        s_rgb = weight_stats(rgb_valid, static, floor)
        s_depth = weight_stats(depth_valid, static, floor)
        hard_rgb = weight_stats(rgb_valid, static, 0.0)["weight_mass"]
        hard_depth = weight_stats(depth_valid, static, 0.0)["weight_mass"]
        row[f"c_rgb@{floor}"] = s_rgb["weight_mass"] / max(hard_rgb, 1e-8)
        row[f"c_depth@{floor}"] = s_depth["weight_mass"] / max(hard_depth, 1e-8)
        row[f"ess_frac@{floor}"] = s_rgb["ess_frac"]
    row["sem_area_frac"] = weight_stats(rgb_valid, static, 0.0)["dynamic_frac"]
    row["depth_valid_frac"] = float(depth_valid.to(torch.float32).mean().item())

    if gtmc is not None:
        # Ceiling: how much of the truly-dynamic area does the semantic mask cover, and
        # how much dynamic area survives at full weight because the detector missed it?
        gt = gtmc.view_as(dynamic)
        dyn = dynamic
        inter = float((gt & dyn).sum().item())
        gt_sum = float(gt.sum().item())
        row["gtmc_area_frac"] = float(gt.to(torch.float32).mean().item())
        row["gtmc_recall"] = inter / gt_sum if gt_sum > 0 else None
        row["gtmc_missed_frac"] = (
            float((gt & ~dyn).to(torch.float32).mean().item()) if gt_sum > 0 else None
        )
        # Pixel sums for the faithfulness anchor: hd_coverage_anchor's cov(a) is
        # Σcovered / Σmover summed over the sequence, NOT a mean of per-frame ratios.
        row["_inter_px"] = inter
        row["_gtmc_px"] = gt_sum
        row["_mask_px"] = float(dyn.sum().item())
        row["_total_px"] = float(dyn.numel())
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stride", type=int, default=5)
    parser.add_argument("--config", default=ARM_CFG)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    config = load_config(os.path.join(ROOT, args.config))
    device = torch.device(args.device)

    all_rows, summary = [], {}
    for seq, rel_path in SEQS.items():
        dataset_path = os.path.join(ROOT, rel_path)
        pairs = associations(dataset_path)
        gtmc_index = frozen_mask_index(os.path.join(dataset_path, "dynamic_mask_gtmc"))

        rows = []
        for i, (rgb_rel, depth_rel) in enumerate(pairs):
            if i % args.stride:
                continue
            stem = os.path.splitext(os.path.basename(depth_rel))[0]
            gtmc_path = gtmc_index.get(stem)
            gtmc = (
                torch.from_numpy(load_frozen_mask(gtmc_path)).to(device)
                if gtmc_path
                else None
            )
            rgb_valid, depth_valid, dynamic = frame_masks(
                dataset_path, rgb_rel, depth_rel, config, device
            )
            row = audit_frame(rgb_valid, depth_valid, dynamic, gtmc, FLOORS)
            row.update({"seq": seq, "frame": i, "stem": stem})
            rows.append(row)

        keys = [k for k in rows[0] if k not in ("seq", "frame", "stem") and not k.startswith("_")]
        inter_px = sum(r.get("_inter_px", 0.0) for r in rows)
        gtmc_px = sum(r.get("_gtmc_px", 0.0) for r in rows)
        mask_px = sum(r.get("_mask_px", 0.0) for r in rows)
        total_px = sum(r.get("_total_px", 0.0) for r in rows)
        summary[seq] = {
            "frames": len(rows),
            "gtmc_covered": sum(1 for r in rows if r.get("gtmc_recall") is not None),
            # cov(a), transcribed from hd_coverage_anchor.py: pixel-summed over the
            # sequence. This is the faithfulness anchor -- it must reproduce the frozen
            # exp22 value, otherwise the audit's mask pipeline is misaligned and none of
            # the floor readings below can be trusted either.
            "cov_a_pixelsum": (inter_px / gtmc_px) if gtmc_px > 0 else None,
            # What the floor knob actually re-admits: of the pixels the hard mask
            # deletes, how many are NOT flagged dynamic by the held-out GTMC mask.
            "mask_fp_share": ((mask_px - inter_px) / mask_px) if mask_px > 0 else None,
            "mask_area_pixelsum": (mask_px / total_px) if total_px > 0 else None,
            "gtmc_area_pixelsum": (gtmc_px / total_px) if total_px > 0 else None,
            **{
                k: float(np.mean([r[k] for r in rows if r.get(k) is not None]))
                for k in keys
                if any(r.get(k) is not None for r in rows)
            },
        }
        all_rows.extend(rows)

    os.makedirs(os.path.join(ROOT, "results/evidence"), exist_ok=True)
    with open(os.path.join(ROOT, CSV_OUT), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    with open(os.path.join(ROOT, EVIDENCE_JSON), "w", encoding="utf-8") as f:
        json.dump({"stride": args.stride, "floors": FLOORS, "summary": summary}, f, indent=2)

    lines = [
        "# exp39 S2 — mapping-weight shape audit (零 GPU 批量，仅检测器推理)",
        "",
        f"> 装置 = `scripts/exp39_weight_audit.py`；mask backend by import 自 `{args.config}`；",
        f"> stride={args.stride}；GTMC = 冻结 held-out 运动一致性掩码。",
        "",
    ]
    for seq, s in summary.items():
        anchor = FROZEN_COV_A.get(seq)
        cov_a = s.get("cov_a_pixelsum")
        gate = "N/A"
        if anchor is not None and cov_a is not None:
            gate = "PASS" if abs(cov_a - anchor) <= COV_A_TOL else "FAIL"
        lines += [
            f"## {seq}（{s['frames']} 帧，其中 {s['gtmc_covered']} 帧有 GTMC）",
            "",
            f"### 装置门 G-A（忠实性锚）：{gate}",
            "",
            f"cov(a) 逐像素求和 = **{cov_a:.4f}** vs exp22 冻结值 {anchor}"
            f"（容差 {COV_A_TOL}）。口径 = `hd_coverage_anchor.py` 的 Σcovered/Σmover。",
            "> 不过门 ⇒ 本文件下方所有读数一律作废（mask 管线与既有锚不是同一个对象）。",
            "",
            "### 权重形态",
            "",
            f"- 语义 mask 面积占比：**{s['sem_area_frac']:.4f}**",
            f"- GTMC 真动态面积占比：**{s.get('gtmc_area_frac', float('nan')):.4f}**",
            f"- 逐帧召回均值（次要口径，非锚）：**{s.get('gtmc_recall', float('nan')):.4f}**",
            f"- GTMC 中被漏掉的面积占全图：**{s.get('gtmc_missed_frac', float('nan')):.4f}**"
            "  ← A2 碰不到的动态面积",
            "",
            "### floor 旋钮实际在动什么（对设计的直接后果）",
            "",
            f"硬 mask 删掉的像素里，**{s.get('mask_fp_share', float('nan')):.1%} 未被 GTMC 判为动态**"
            f"（mask 面积 {s.get('mask_area_pixelsum', float('nan')):.4f} vs GTMC 面积 "
            f"{s.get('gtmc_area_pixelsum', float('nan')):.4f}）。",
            "",
            "⇒ 抬 floor 主要**放回的是 mask 的假阳（多为瞬时静止的人体像素）**，不是真动态像素；",
            "这正是方差-偏置机制预言会**降方差而少付偏置**的那一类观测。",
            "",
            "> **诚实边界**：GTMC 量的是「该瞬间运动不一致」，不是「将来会不会动」。",
            "> 一个此刻静止的人**仍会移动**，把它烤进地图依然有害 ⇒ 假阳份额**不可**直接读成"
            "「这些像素放回来是安全的」，只能读成「floor 旋钮的作用面主要落在这批像素上」。",
            "",
            "| floor | c_rgb（光度项尺度） | c_depth | ESS_frac |",
            "|---:|---:|---:|---:|",
        ]
        for floor in FLOORS:
            lines.append(
                f"| {floor} | {s[f'c_rgb@{floor}']:.4f} | "
                f"{s[f'c_depth@{floor}']:.4f} | {s[f'ess_frac@{floor}']:.4f} |"
            )
        lines.append("")
    with open(os.path.join(ROOT, EVIDENCE_MD), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
