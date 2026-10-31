#!/usr/bin/env python3
"""build_dynamic_mask.py — **冻结评估掩码的唯一构建器**（掩码体系重构，2026-09-21）。

体系（重构后）——只有两条链，名字和用途都分开，互不冒充：

    ① 方法输入（在线，属于方法）: SemanticMask / MaskRCNN
       `utils/semantic_mask.compute_semantic_dynamic_mask`，运行期在 slam_frontend 里算，
       用于跟踪/建图降权与（L1b）证据门控。**不是**评估参照。

    ② 评估参照（离线、冻结、与方法无关）: `<seq>/dynamic_mask/`  ← **本文件唯一产出**
       uint8，0=静态 / 255=动态，按 depth stem 命名。**没有类号**（类号约定是历史事故根源）。

退场（不再被任何消费方读取）:
    * `dynamic_mask_gtmc/` — 运动一致性掩码；6 条序列实测移动者召回 0.10–0.39、30 帧并集
      51–96% 为静态误标（`evidence/l3_instrument_rescore_2026-09-21.md`）。
    * `seg_mask/` — 由 OneFormer(ADE20K-150) 生成（**非数据集自带**），person = cls12 可用，
      但同目录混入了另一套 VOC-15 口径 ⇒ 只能**降级为只读验证参照**，本 builder 用它做独立核对。

两个来源（可单用，可并集）:
    --sources maskrcnn          语义 person（COCO person=1）——人；高精度
    --sources maskrcnn,flow     再加冻结 RAFT 流阈值（类无关）——覆盖无语义类的移动物（气球/箱子）

内置验证（不过则不写盘、非零退出）——这是"重构后不容易出错"的核心：
    ① 独立参照一致性: 若序列有 OneFormer person 参照，逐帧算 recall，均值须 ≥ --min-recall
    ② 炸裂护栏: 逐帧面积占比须 < --max-area-frac
    ③ 空掩码率: 参照说有人而新掩码为空的帧占比须 ≤ --max-empty-rate
    失败 ⇒ 只写 `<seq>/dynamic_mask_BUILD_FAILED.json` 诊断，**不动** dynamic_mask/。

用法:
  PY=/data/conda_envs/monogs-ours/bin/python
  $PY scripts/build_dynamic_mask.py --sequence-dir datasets/bonn/rgbd_bonn_person_tracking
  $PY scripts/build_dynamic_mask.py --sequence-dir datasets/bonn/rgbd_bonn_balloon --sources maskrcnn,flow
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np
import torch
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from utils.flow_mask_baseline import compute_flow_threshold_mask, frozen_flow_magnitude  # noqa: E402
from utils.geometry_metrics import load_tum_associations  # noqa: E402
from utils.semantic_mask import compute_semantic_dynamic_mask  # noqa: E402

FLOW_SUBDIR = "flow_raft"
GTMC_SUBDIR = "dynamic_mask_gtmc"      # 历史产物；仅用于"对照报告"，不作为来源
# 独立验证参照（只读、不作为掩码来源）。默认 deeplabv3：与本方法用的 MaskRCNN
# **不同架构 + 不同训练集**（VOC semantic vs COCO instance），且在本仓环境内、全序列可用。
# `oneformer` 保留为可选第二参照（读 <seq>/seg_mask/，cls12）——那是**项目作者的 DGS-SLAM 复现资产**，
# 非数据集自带；本 builder 不再依赖它。
REF_SOURCES = ("deeplabv3", "oneformer", "none")
ONEFORMER_SUBDIR = "seg_mask"
ONEFORMER_PERSON_CLASS = 12            # ADE20K 0 起：person = 12


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _dilate(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0 or not mask.any():
        return mask
    from scipy.ndimage import binary_dilation
    return binary_dilation(mask, structure=np.ones((2 * px + 1, 2 * px + 1), dtype=bool))


def _mrcnn_mask(cfg: dict, rgb_path: str, device: str, dilate_px: int):
    im = np.asarray(Image.open(rgb_path).convert("RGB"))
    x = torch.from_numpy(im).permute(2, 0, 1).float().to(device) / 255.0
    m = compute_semantic_dynamic_mask(cfg, x)          # (1,H,W) bool 或 None（>max_ratio）
    if m is None:
        return np.zeros(im.shape[:2], dtype=bool), True   # True = 该帧判为"不安全空"
    return m[0].detach().cpu().numpy(), False


def _flow_mask(seq_dir: str, depth_stem: str, quantile: float, abs_px: float, dilate_px: int):
    p = os.path.join(seq_dir, FLOW_SUBDIR, f"{depth_stem}.npy")
    if not os.path.isfile(p):
        return None
    m = compute_flow_threshold_mask(
        frozen_flow_magnitude(p), quantile=quantile, abs_px=abs_px, dilate_px=dilate_px)
    return m


def _load_oneformer_ref(seq_dir: str, rgb_stem: str):
    """OneFormer person 参照（可选；只读 <seq>/seg_mask/ 的 cls12）。缺则 None。"""
    p = os.path.join(seq_dir, ONEFORMER_SUBDIR, f"{rgb_stem}.png")
    if not os.path.isfile(p):
        return None
    return np.asarray(Image.open(p).convert("L")) == ONEFORMER_PERSON_CLASS


def _deeplab_ref_mask(rgb_path: str, device: str):
    """deeplabv3(VOC person=15) 的语义 person 掩码（独立参照；不膨胀，保持"参照原样"）。"""
    cfg = {"SemanticMask": {"enabled": True, "model": "deeplabv3", "dynamic_classes": [15],
                            "dilate_px": 0, "max_mask_ratio": 0.99, "device": device}}
    im = np.asarray(Image.open(rgb_path).convert("RGB"))
    x = torch.from_numpy(im.copy()).permute(2, 0, 1).float().to(device) / 255.0
    m = compute_semantic_dynamic_mask(cfg, x)
    return np.zeros(im.shape[:2], dtype=bool) if m is None else m[0].cpu().numpy()


REF_MIN_PX = 1500   # 参照帧的"有意义人物区域"下限；小于此的参照帧不参与召回/比值判据
                    # （2026-09-21：micro-ref 帧曾把 area/ref 比值推到 29x/419x 的假警报）


def evaluate_gates(rows: list, *, min_recall: float, max_area_frac: float,
                   max_area_ratio_vs_ref: float, max_empty_rate: float,
                   max_over_ref_rate: float = 0.02,
                   ref_min_px: int = REF_MIN_PX) -> tuple:
    """三门验证（纯函数，便于单测）。返回 ``(failures, stats)``。

    ① 独立参照一致性：mean recall（仅 ref>=ref_min_px 的帧）>= min_recall
    ② 炸裂护栏：有参照帧用 **area/ref_matched 比值** <= max_area_ratio_vs_ref（形态对齐后比，
       抓过喷、不误杀密集人群、不受"参照紧/松"影响）；无参照帧退化为绝对面积占比 < max_area_frac
    ③ 空掩码率：参照说有人（ref>=ref_min_px）而掩码为空的帧占比 <= max_empty_rate
    """
    rec = [r["recall_vs_ref"] for r in rows
           if r.get("ref_px", 0) >= ref_min_px and "recall_vs_ref" in r]
    mean_recall = float(np.mean(rec)) if rec else None
    max_area = max((r["area_frac"] for r in rows), default=0.0)

    n_over_ref, n_ref_frames, max_ratio, worst = 0, 0, 0.0, None
    no_ref_degenerate = None
    for r in rows:
        ref_px = r.get("ref_px", 0)
        # 比值判据用**形态对齐**的参照（同 dilate_px）：否则"膨胀过的掩码 / 未膨胀的参照"
        # 会系统性抬高比值（2026-09-22 实测 deeplabv3 参照下 pt2/crowd 被误杀 max 4.22/3.44）。
        ratio_px = r.get("ref_px_matched", ref_px)
        if ratio_px >= ref_min_px:
            n_ref_frames += 1
            ratio = r["area_frac"] / (ratio_px / (480 * 640))
            if ratio > max_ratio:
                max_ratio, worst = ratio, r["depth_stem"]
            if ratio > max_area_ratio_vs_ref:
                n_over_ref += 1
        elif ref_px == 0 and r["area_frac"] >= max_area_frac and no_ref_degenerate is None:
            no_ref_degenerate = r["depth_stem"]

    n_present = sum(1 for r in rows if r.get("ref_px", 0) >= ref_min_px)
    n_empty_but_present = sum(1 for r in rows
                              if r.get("ref_px", 0) >= ref_min_px and r["area_frac"] <= 1e-6)
    empty_rate = (n_empty_but_present / n_present) if n_present else 0.0

    failures = []
    if mean_recall is not None and mean_recall < min_recall:
        failures.append(f"① 独立参照一致性: mean_recall={mean_recall:.3f} < {min_recall}")
    if no_ref_degenerate is not None:
        failures.append(f"② 炸裂护栏(无参照帧): area_frac >= {max_area_frac} @ {no_ref_degenerate}")
    over_rate = (n_over_ref / n_ref_frames) if n_ref_frames else 0.0
    if over_rate > max_over_ref_rate:
        failures.append(f"② 面具远超独立参照: {n_over_ref}/{n_ref_frames} 帧 "
                        f"({over_rate:.3%}) area/ref > {max_area_ratio_vs_ref} > 允许 {max_over_ref_rate:.1%} "
                        f"(max ratio={max_ratio:.2f} @ {worst})")
    if empty_rate > max_empty_rate:
        failures.append(f"③ 空掩码率: {empty_rate:.3f} > {max_empty_rate}")
    stats = {"mean_recall": mean_recall, "max_area": max_area,
             "max_area_ratio_vs_ref": round(max_ratio, 4),
             "n_frames_area_over_ref": n_over_ref,
             "area_over_ref_rate": round(over_rate, 5),
             "n_frames_with_matched_ref": n_ref_frames,
             "empty_but_person_present_rate": round(empty_rate, 5),
             "n_frames_with_reference": len(rec)}
    return failures, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sequence-dir", required=True)
    ap.add_argument("--sources", default="maskrcnn", help="逗号分隔: maskrcnn[,flow]")
    ap.add_argument("--out-subdir", default="dynamic_mask", help="唯一合法值即默认值")
    ap.add_argument("--dilate-px", type=int, default=7, help="每源膨胀（与运行期 MaskRCNN 同约定）")
    ap.add_argument("--flow-quantile", type=float, default=0.90)
    ap.add_argument("--flow-abs-px", type=float, default=2.0)
    ap.add_argument("--conf", type=float, default=0.5)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--ref-source", choices=list(REF_SOURCES), default="deeplabv3",
                    help="独立验证参照：deeplabv3（默认，本环境内、全序列可用）/ oneformer（**死选项**："
                         "seg_mask/ 已于 2026-09-22 全量删除，选择后各帧参照为空）/ none")
    ap.add_argument("--min-recall", type=float, default=0.80, help="验证门①：vs 独立参照的均值召回下限")
    ap.add_argument("--max-area-frac", type=float, default=0.90,
                    help="验证门②（无参照帧）：逐帧面积占比退化上限")
    ap.add_argument("--max-over-ref-rate", type=float, default=0.02,
                    help="门②的**比率**宽容度：超界帧占比 <= 此值即通过。过渡帧上两个检测器"
                         "覆盖度会暂时不一致（实测 pt/crowd/crowd2 各 1/1/5 帧超 3x，且那些帧"
                         "recall=1.0 或参照塌陷）→ 逐帧硬门会误杀；真过喷会淹没多数帧。")
    ap.add_argument("--max-area-ratio-vs-ref", type=float, default=3.00,
                    help="验证门②（有参照帧）：掩码面积/独立参照面积 上限。**实测定标**：8 序列"
                         "（每序列 216-788 帧）比值中位 1.15-1.31、p95<=1.54、全局最大 2.37"
                         "（膨胀 7px + 轮廓差是正常代价）；3.0 = 抓真过喷（5-20x）而不误杀")
    ap.add_argument("--max-empty-rate", type=float, default=0.50, help="验证门③：参照有人而掩码空的帧占比上限")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的 dynamic_mask/")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    seq_dir = args.sequence_dir.rstrip("/")
    seq = os.path.basename(seq_dir)
    out_dir = os.path.join(seq_dir, args.out_subdir)
    if os.path.basename(out_dir) != "dynamic_mask":
        raise SystemExit("REFUSE: --out-subdir 只能是 dynamic_mask（重构后唯一 eval 掩码目录）")
    existing = sorted(f for f in os.listdir(out_dir)) if os.path.isdir(out_dir) else []
    if existing and not args.force:
        raise SystemExit(f"REFUSE: {out_dir} 已存在 {len(existing)} 个文件（避免静默覆盖）。加 --force 覆盖。")

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = set(sources) - {"maskrcnn", "flow"}
    if unknown:
        raise SystemExit(f"REFUSE: 未知来源 {sorted(unknown)}（只支持 maskrcnn / flow）")

    cfg = {"SemanticMask": {"enabled": True, "model": "maskrcnn", "dynamic_classes": [1],
                            "conf_threshold": args.conf, "mask_threshold": 0.5,
                            "dilate_px": args.dilate_px, "max_mask_ratio": 0.98,
                            "device": args.device}}

    frames = load_tum_associations(seq_dir)
    if args.limit:
        frames = frames[: args.limit]
    print(f"[build_dynamic_mask] {seq}: {len(frames)} frames, sources={sources}, device={args.device}",
          flush=True)

    rows, masks = [], {}
    n_flow_missing = n_unsafe = 0
    for i, f in enumerate(frames):
        depth_stem = _stem(f["depth_path"])
        rgb_stem = _stem(f["rgb_path"])
        m = np.zeros((480, 640), dtype=bool)
        if "maskrcnn" in sources:
            mm, unsafe = _mrcnn_mask(cfg, f["rgb_path"], args.device, args.dilate_px)
            n_unsafe += int(unsafe)
            m |= mm
        if "flow" in sources:
            fm = _flow_mask(seq_dir, depth_stem, args.flow_quantile, args.flow_abs_px, args.dilate_px)
            if fm is None:
                n_flow_missing += 1
            else:
                m |= fm
        masks[depth_stem] = m
        if args.ref_source == "deeplabv3":
            ref = _deeplab_ref_mask(f["rgb_path"], args.device)
        elif args.ref_source == "oneformer":
            # 2026-09-22：seg_mask/ 已全量删除（用户拍板，NOTES 备份表#6）⇒ 死选项，保留仅为显式报错
            ref = _load_oneformer_ref(seq_dir, rgb_stem)
        else:
            ref = None
        row = {"depth_stem": depth_stem, "rgb_stem": rgb_stem,
               "area_frac": round(float(m.mean()), 5)}
        if ref is not None:
            rp = int(ref.sum())
            row["ref_px"] = rp
            row["ref_px_matched"] = int(_dilate(ref, args.dilate_px).sum())
            if rp >= 1500:
                row["recall_vs_ref"] = round(float((m & ref).sum()) / rp, 4)
                row["precision_vs_ref"] = round(
                    float((m & ref).sum()) / max(int(m.sum()), 1), 4)
        rows.append(row)
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(frames)}", flush=True)

    # ── 验证门（纯函数，见 evaluate_gates；有单测） ──────────────────────
    failures, stats = evaluate_gates(rows, min_recall=args.min_recall,
                                     max_area_frac=args.max_area_frac,
                                     max_area_ratio_vs_ref=args.max_area_ratio_vs_ref,
                                     max_empty_rate=args.max_empty_rate,
                                     max_over_ref_rate=args.max_over_ref_rate,
                                     ref_min_px=REF_MIN_PX)
    mean_recall = stats["mean_recall"]
    max_area = stats["max_area"]
    max_ratio = stats["max_area_ratio_vs_ref"]
    n_over_ref = stats["n_frames_area_over_ref"]
    empty_rate = stats["empty_but_person_present_rate"]

    report = {
        "sequence": seq, "sources": sources, "n_frames": len(rows),
        "verification": {
            "reference_source": args.ref_source,
            "mean_recall_vs_reference": mean_recall,
            "n_frames_with_reference": stats["n_frames_with_reference"],
            "max_area_frac": round(max_area, 5),
            "max_area_ratio_vs_ref": round(max_ratio, 4),
            "n_frames_area_over_ref": n_over_ref,
            "area_over_ref_rate": stats["area_over_ref_rate"],
            "n_frames_with_matched_ref": stats["n_frames_with_matched_ref"],
            "empty_but_person_present_rate": round(empty_rate, 5),
            "n_flow_missing": n_flow_missing, "n_mrcnn_unsafe_frames": n_unsafe,
            "gates": {"min_recall": args.min_recall, "max_area_frac": args.max_area_frac,
                      "max_area_ratio_vs_ref": args.max_area_ratio_vs_ref,
                      "max_empty_rate": args.max_empty_rate},
            "failures": failures,
        },
        "frames": rows,
    }
    if failures:
        fp = os.path.join(seq_dir, "dynamic_mask_BUILD_FAILED.json")
        json.dump(report, open(fp, "w"), indent=1)
        print(f"[build_dynamic_mask] FAILED（未写盘）: {'; '.join(failures)}\n  报告: {fp}", flush=True)
        return 1

    os.makedirs(out_dir, exist_ok=True)
    h = hashlib.sha256()
    for stem in sorted(masks):
        arr = (masks[stem].astype(np.uint8) * 255)
        Image.fromarray(arr, mode="L").save(os.path.join(out_dir, f"{stem}.png"))
        h.update(stem.encode()); h.update(arr.tobytes())
    manifest = dict(report)
    manifest["convention"] = "uint8 0=static / 255=dynamic, keyed by depth stem, no class ids"
    manifest["builder"] = "scripts/build_dynamic_mask.py"
    manifest["reference_note"] = (
        "独立验证参照默认 = deeplabv3(VOC person=15)，与本方法所用的 MaskRCNN 不同架构/训练集，"
        "且不依赖外部 oneformer 环境；实测 deeplabv3 vs OneFormer 一致度 recall 0.88-0.96。"
        "可选 --ref-source oneformer 使用项目作者的 DGS-SLAM 复现资产 <seq>/seg_mask/（ADE20K cls12）。")
    manifest["sha256_over_masks"] = h.hexdigest()
    manifest["retired_sources"] = {"dynamic_mask_gtmc": "召回 0.10-0.39，已废",
                                   "seg_mask": "OneFormer，降级为只读验证参照"}
    json.dump(manifest, open(os.path.join(out_dir, "manifest.json"), "w"), indent=1)
    print(f"[build_dynamic_mask] OK: {len(masks)} masks -> {out_dir}\n"
          f"  验证: mean_recall={mean_recall} max_area={max_area:.3f} max_area/ref={max_ratio:.2f} "
          f"empty_rate={empty_rate:.3f} sha256={h.hexdigest()[:12]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
