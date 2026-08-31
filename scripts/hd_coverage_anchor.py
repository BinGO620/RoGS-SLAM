#!/usr/bin/env python3
"""H-D coverage anchor: per-sequence "how much of the mover does the person mask cover?"

Zero SLAM, zero map, zero seeds — detector inference + frozen GTMC oracle only. This is the
offline stratifier the H-D hypothesis (``results/evidence/hd_coverage_prereg.md``) is checked
against. It does NOT itself test H-D; it supplies the per-sequence coverage number that the
pre-registered monotone-order prediction is evaluated against.

WHY THIS IS NOT A DEPLOYABLE GATE (oracle-stratified, not observable):
    The mover region is given by ``dynamic_mask_gtmc/`` — the frozen GT-pose
    motion-consistency mask that the EVALUATION scores against. At deployment time the system
    does not know the true mover region, so "person mask coverage of the mover" is NOT a
    quantity any online gate can compute. This script measures an ORACLE stratifier for an
    applicability hypothesis ("two mechanisms have different domains"), not a realisable
    gating signal. The deployable-proxy question is explicitly future work.

DEFINITIONS (frozen here, before any P2-T read):
    GTMC        frozen GT-pose motion-consistency mask (method-independent eval oracle)
    PERSON      Mask R-CNN COCO person mask, with the SAME params the combined backbone
                resolves (read out of its config, never duplicated), incl. the 7px dilate
    VALID       depth > 0.01 m (a pixel with no depth was never insertable)
    mover       GTMC ∧ VALID                     (the true dynamic region, depth-valid)
    covered     PERSON ∧ mover                   (the part of the mover the mask catches)
    FN          mover ∧ ¬PERSON                  (the mover the mask LETS IN — the leak)
    coverage    Σ covered / Σ mover   (pixel-summed over the sequence, NOT a per-frame mean)

COVERAGE IS THE H-D STRATIFIER. The prediction (see prereg) is a MONOTONE ORDER on coverage
vs the G_def/G_prune ratio, NOT a binary threshold:
    high coverage  (mask catches the mover)  =>  expected G_def/G_prune > 1  (prune better)
    low  coverage  (mask leaks the mover)    =>  expected G_def/G_prune < 1  (deferred better)

No threshold is fit to the data here. Thresholding after looking at balloon/pt2 would be
two-point training; the prereg uses the RANK ORDER only.

ARM-INDEPENDENT FRAME SAMPLING (critical):
    Coverage is computed over EVERY associated frame (the full video), NOT over either arm's
    own keyframes. The two arms select different keyframes and walk different trajectories,
    so per-arm KF coverage is endogenous to the arm and cannot be read as a "dose" of mask
    leakage. Full-video coverage is arm-independent; it is what the prediction is stated on.

SENSITIVITY (window + denominator):
    GTMC is a frozen oracle, not ground truth. Its known failure mode (see
    ``r2_p04_mask_fp_anchor.md``): momentarily-still movers under-flag, so "mover" misses
    still-but-present people, which inflates the apparent leak. To keep that confound
    visible, coverage is reported under THREE mover definitions that bracket the oracle's
    under-flagging:
      (a) per-frame GTMC                  — the strict oracle (under-flags still movers)
      (b) ±15-frame GTMC union            — a mover "counts" if GTMC flagged it within ±15 fr
      (c) sequence-wide GTMC union        — the roaming-mover upper bound (saturates on
                                            balloon; reported with its union coverage so a
                                            saturated number is never read as a sharp value)
    The headline H-D stratifier is (a); (b)/(c) are the sensitivity band. A prediction whose
    RANK flips between (a) and (b) is declared INDETERMINATE (prereg §three-branch).

Usage:
  python scripts/hd_coverage_anchor.py                       # all P2-T sequences, cuda
  python scripts/hd_coverage_anchor.py --device cpu          # no GPU contention
  python scripts/hd_coverage_anchor.py --seqs balloon pt2    # subset

Writes ``results/evidence/hd_coverage_anchor.md`` + ``..._perframe.csv`` (per-frame, per-seq).
Zero campaign cost; detector inference only.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import numpy as np
import torch
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402
from utils.gtmc_mask import frozen_mask_index, load_frozen_mask  # noqa: E402
from utils.semantic_mask import compute_semantic_dynamic_mask  # noqa: E402

# The combined backbone is the method P2-T actually runs. Its SemanticMask block IS the
# person mask the backbone deploys at run time (maskrcnn / person / dilate 7 / both
# consumers). Reading it from the method config — not duplicating it — guarantees the
# stratifier cannot drift from the run-time mask.
BACKBONE_CFG = "configs/rgbd/experiments/active/candidate/method_combined_maskboth_deferred.yaml"
EVIDENCE = "results/evidence/hd_coverage_anchor.md"
CSV_OUT = "results/evidence/hd_coverage_anchor_perframe.csv"

# P2-T dynamic sequences that have BOTH a frozen GTMC mask and a dataset. f1_desk (static
# sanity) has no mover so coverage is undefined — excluded from H-D, kept in the main table.
# balloon/pt2 are the SEEN sequences (generated the hypothesis); the rest are UNSEEN.
SEQS = {
    "balloon": "datasets/bonn/rgbd_bonn_balloon",
    "balloon2": "datasets/bonn/rgbd_bonn_balloon2",
    "mv_no_box": "datasets/bonn/rgbd_bonn_moving_nonobstructing_box",
    "mv_no_box2": "datasets/bonn/rgbd_bonn_moving_nonobstructing_box2",
    "pt1": "datasets/bonn/rgbd_bonn_person_tracking",
    "pt2": "datasets/bonn/rgbd_bonn_person_tracking2",
}
WINDOWS = [15]            # primary temporal-union half-window for sensitivity (b)
# the sequence-wide union is always also reported (c)
SEEN = {"balloon", "pt2"}  # generated the hypothesis; not independent tests


def associations(dataset_path):
    """[(rgb_rel, depth_rel)] from ``associations.txt``.

    GTMC masks are keyed by DEPTH stem (as the eval loader indexes them); the detector runs
    on RGB. Pairing must come from the association table the dataset ships, not from sorting
    two directories and hoping they line up (mirrors r2_p04_mask_fp_anchor.py).
    """
    path = os.path.join(dataset_path, "associations.txt")
    pairs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4:
                pairs.append((parts[1], parts[3]))
    return pairs


def load_depth_valid(dataset_path, depth_rel, depth_scale):
    arr = np.asarray(Image.open(os.path.join(dataset_path, depth_rel)))
    return (arr.astype(np.float32) / depth_scale) > 0.01


def load_rgb(dataset_path, rgb_rel, device):
    arr = np.asarray(Image.open(os.path.join(dataset_path, rgb_rel)).convert("RGB"))
    return torch.from_numpy(arr).permute(2, 0, 1).float().div_(255.0).to(device)


def pct(num, den):
    return 100.0 * num / den if den else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=BACKBONE_CFG,
                    help="combined backbone config — person-mask params READ from it")
    ap.add_argument("--device", default=None, help="override SemanticMask.device")
    ap.add_argument("--seqs", nargs="+", default=list(SEQS), choices=list(SEQS),
                    help="subset of sequences (default: all P2-T dynamic seqs)")
    ap.add_argument("--limit", type=int, default=None, help="first N frames per seq (smoke)")
    ap.add_argument("--evidence", default=EVIDENCE)
    ap.add_argument("--csv", default=CSV_OUT)
    args = ap.parse_args()
    os.chdir(ROOT)

    config = load_config(args.config)
    if args.device:
        config["SemanticMask"]["device"] = args.device
    sem = config["SemanticMask"]
    device = sem.get("device") or "cuda"

    # The method config carries SemanticMask/Results but NOT Dataset/Calibration (those come
    # from the per-sequence base config). Pull depth_scale + the GTMC subdir from a resolved
    # run config of the same backbone so the stratifier matches run-time eval exactly. Bonn
    # depth_scale is constant across the suite (5000), but read it rather than hardcode.
    run_cfg = load_config("configs/rgbd/experiments/p2_render/p2s_combined_deferred_pt2.yaml")
    depth_scale = float(run_cfg["Dataset"]["Calibration"]["depth_scale"])
    subdir = run_cfg["Results"]["static_bg_mask_subdir"]

    print(f"# H-D coverage anchor: {sem['model']} person-mask vs frozen GTMC, device={device}")
    print(f"# sequences: {args.seqs}")

    rows = []          # per-frame CSV rows
    summary = []       # per-sequence aggregates

    for short, dpath in [(s, SEQS[s]) for s in args.seqs]:
        seq_dir = os.path.join(ROOT, dpath) if not os.path.isabs(dpath) else dpath
        # the dataset_path in configs is repo-relative; resolve against ROOT
        if not os.path.isdir(seq_dir):
            seq_dir = dpath  # already absolute (e.g. /data/Datasets/...)
        index = frozen_mask_index(os.path.join(seq_dir, subdir))
        pairs = associations(seq_dir)
        if args.limit:
            pairs = pairs[: args.limit]
        if not index or not pairs:
            print(f"  {short}: SKIP (masks={len(index)} pairs={len(pairs)})")
            continue

        # load every frozen mask once; build the sequence-wide union + per-window unions
        frozen = []
        for _, depth_rel in pairs:
            stem = os.path.splitext(os.path.basename(depth_rel))[0]
            frozen.append(None if stem not in index else load_frozen_mask(index[stem]))
        present = [m for m in frozen if m is not None]
        if not present:
            print(f"  {short}: SKIP (no frozen mask matched any frame)")
            continue
        seq_union = np.logical_or.reduce(present)
        # windowed union per frame index
        def windowed_union(i, w):
            near = [m for m in frozen[max(i - w, 0): i + w + 1] if m is not None]
            return np.logical_or.reduce(near) if near else frozen[i]

        n_frames = 0
        sum_mover = sum_mover_w = sum_mover_seq = 0
        sum_covered = sum_covered_w = sum_covered_seq = 0
        sum_fn = 0
        sum_valid = 0
        union_cov = float(seq_union.mean())
        print(f"  {short}: {len(pairs)} frames, GTMC seq-union covers {100*union_cov:.1f}% of image"
              f"{' (SATURATED)' if union_cov > 0.5 else ''}")

        for i, (rgb_rel, depth_rel) in enumerate(pairs):
            gtmc = frozen[i]
            if gtmc is None:
                continue
            valid = load_depth_valid(seq_dir, depth_rel, depth_scale)
            image = load_rgb(seq_dir, rgb_rel, device)
            person_t = compute_semantic_dynamic_mask(config, image)
            person = (np.zeros_like(gtmc) if person_t is None
                      else person_t.squeeze(0).cpu().numpy().astype(bool))
            if person.shape != gtmc.shape:
                continue

            mover = gtmc & valid
            covered = person & mover
            fn = mover & (~person)
            mover_w = windowed_union(i, WINDOWS[0]) & valid
            covered_w = person & mover_w
            mover_seq = seq_union & valid
            covered_seq = person & mover_seq

            n_frames += 1
            sum_mover += int(mover.sum())
            sum_covered += int(covered.sum())
            sum_mover_w += int(mover_w.sum())
            sum_covered_w += int(covered_w.sum())
            sum_mover_seq += int(mover_seq.sum())
            sum_covered_seq += int(covered_seq.sum())
            sum_fn += int(fn.sum())
            sum_valid += int(valid.sum())

            rows.append({
                "seq": short, "frame": i, "depth_stem": os.path.splitext(os.path.basename(depth_rel))[0],
                "mover_px": int(mover.sum()), "covered_px": int(covered.sum()),
                "mover_w15_px": int(mover_w.sum()), "covered_w15_px": int(covered_w.sum()),
                "mover_seq_px": int(mover_seq.sum()), "covered_seq_px": int(covered_seq.sum()),
                "fn_px": int(fn.sum()), "valid_px": int(valid.sum()),
            })
            if (i + 1) % 100 == 0:
                print(f"    {short} {i+1}/{len(pairs)}")

        cov = pct(sum_covered, sum_mover)
        cov_w = pct(sum_covered_w, sum_mover_w)
        cov_seq = pct(sum_covered_seq, sum_mover_seq)
        leak = pct(sum_fn, sum_mover)
        summary.append({
            "seq": short, "n_frames": n_frames, "seen": short in SEEN,
            "union_cov_pct": 100 * union_cov,
            "coverage_perframe_pct": cov,
            "coverage_w15_pct": cov_w,
            "coverage_seq_pct": cov_seq,
            "leak_fn_pct": leak,
            "sum_mover_px": sum_mover, "sum_fn_px": sum_fn,
        })
        print(f"  {short}: coverage(a per-frame)={cov:.1f}%  (b ±15fr)={cov_w:.1f}%  "
              f"(c seq-union)={cov_seq:.1f}%  | leak(FN)={leak:.1f}%  "
              f"{'[SEEN]' if short in SEEN else '[UNSEEN]'}")

    if not summary:
        print("no sequence produced a comparison")
        return 1

    os.makedirs(os.path.dirname(args.csv), exist_ok=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    write_evidence(args.evidence, sem, device, summary, WINDOWS, args)
    return 0


def write_evidence(path, sem, device, summary, windows, args):
    lines = [
        "# H-D coverage anchor: per-sequence person-mask coverage of the mover (offline, no SLAM)",
        "",
        "> Zero campaign cost (Mask R-CNN inference + frozen GTMC oracle only).",
        f"> Generated by `scripts/hd_coverage_anchor.py` from `{args.config}` (combined backbone).",
        f"> Per-frame CSV: `{args.csv}`",
        "",
        "## What this is, and what it is NOT",
        "",
        "This supplies the per-sequence **coverage stratifier** the H-D hypothesis "
        "(`results/evidence/hd_coverage_prereg.md`) is checked against. It does NOT test H-D.",
        "",
        "**It is an ORACLE stratifier, not a deployable gate.** The mover region comes from the "
        "frozen GTMC eval mask; at run time the system does not know the true mover, so "
        "\"person-mask coverage of the mover\" is not computable online. The claim it supports "
        "is an *applicability* hypothesis (two mechanisms have different domains stratified by "
        "oracle coverage), NOT a realisable hybrid gating signal. A deployable proxy is future "
        "work and is out of scope for this paper.",
        "",
        "## Definitions (frozen before any P2-T read)",
        "",
        f"- detector: **{sem['model']}**, COCO person, dilate **{sem['dilate_px']}px** — read off "
        f"the combined backbone's own SemanticMask block (cannot drift from run time)",
        "- mover = GTMC ∧ depth-valid ; covered = PERSON ∧ mover ; leak(FN) = mover ∧ ¬PERSON",
        "- coverage = Σ covered / Σ mover, pixel-summed over the **full video** (arm-independent "
        "frame sampling — NOT either arm's own keyframes, which are endogenous to the arm)",
        "",
        "## Sensitivity: three mover definitions bracket the oracle's under-flagging",
        "",
        "GTMC under-flags momentarily-still movers, so per-frame coverage (a) understates how "
        "much the mask catches. (b)/(c) relax the mover definition; a prediction whose RANK "
        "**flips** between (a) and (b) is declared INDETERMINATE per the prereg three-branch rule.",
        "",
        "- **(a) per-frame GTMC** — strict oracle; the headline H-D stratifier",
        f"- **(b) ±{windows[0]}-frame GTMC union** — a mover counts if flagged within ±{windows[0]} fr",
        "- **(c) sequence-wide GTMC union** — roaming-mover upper bound (saturates on balloon; "
        "reported with its union coverage so a saturated value is never read as sharp)",
        "",
        "## Per-sequence result",
        "",
        "| seq | seen? | n_fr | GTMC seq-union % | cov (a) | cov (b ±15fr) | cov (c seq) | leak FN % |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| {s['seq']} | {'yes' if s['seen'] else '**no**'} | {s['n_frames']} | "
            f"{s['union_cov_pct']:.1f}{' (SAT)' if s['union_cov_pct']>50 else ''} | "
            f"**{s['coverage_perframe_pct']:.1f}%** | {s['coverage_w15_pct']:.1f}% | "
            f"{s['coverage_seq_pct']:.1f}% | {s['leak_fn_pct']:.1f}% |"
        )
    # monotone-order table for the prereg prediction
    order = sorted(summary, key=lambda s: s["coverage_perframe_pct"])
    lines += [
        "",
        "## Monotone-order stratifier (rank by headline coverage (a))",
        "",
        "The H-D prereg prediction is a RANK ORDER on coverage vs G_def/G_prune, NOT a "
        "threshold. This table fixes the coverage rank (a) **before** P2-T ratios exist, so the "
        "prediction can be checked without fitting any cut to the ratio data.",
        "",
        "| rank | seq (low→high coverage) | cov (a) | seen? | H-D predicted G_def/G_prune |",
        "|---|---|---|---|---|",
    ]
    for r, s in enumerate(order, 1):
        # high coverage => prune better => ratio > 1 ; low coverage => deferred better => < 1
        pred = "> 1 (prune better)" if s["coverage_perframe_pct"] >= 50 else "< 1 (deferred better)"
        lines.append(f"| {r} | {s['seq']} | {s['coverage_perframe_pct']:.1f}% | "
                     f"{'seen' if s['seen'] else 'unseen'} | {pred} |")
    lines += [
        "",
        "> The ≥50% cut in the prediction column is a DISPLAY convenience to label the two",
        "> regimes; the actual prereg test is the **Spearman rank correlation** between the",
        "> coverage column above and the P2-T G_def/G_prune column (sign + magnitude vs the",
        "> rate-noise band), with the three-branch (confirmed / indeterminate / falsified)",
        "> rule in `hd_coverage_prereg.md`. No threshold is fit to the ratios.",
        "",
        "## Caveats (must travel with any quote of these numbers)",
        "",
        "1. **Coverage and class-composition are collinear on this dataset.** pt1/pt2 are "
        "pure-person; balloon is person+object (the balloon); box seqs are person+object. The "
        "H-D prediction cannot distinguish \"mask sufficiency\" from \"person-only vs "
        "person+object\" at n=6; this is a stated limitation, not a resolvable confound here.",
        "2. **GTMC is a frozen oracle, not ground truth.** Its under-flagging of still movers "
        "is why three mover definitions are reported; (a) is a lower bound on true coverage.",
        "3. **Pixel ≠ Gaussian.** Coverage is a fraction of depth-valid mover pixels; the "
        "deferred arm down-samples at insertion, so the ratio G_def/G_prune is not predicted "
        "1:1 from coverage. Coverage orders the prediction; it does not predict the magnitude.",
        "4. **The box family is bistable** in self-tracking (HANDOFF运维教训). A coverage rank "
        "is well-defined regardless; the G_def/G_prune it is checked against may be noisy on "
        "those two sequences — the prereg three-branch rule handles an indeterminate ratio.",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nwrote {path} + {args.csv}")


if __name__ == "__main__":
    raise SystemExit(main())
