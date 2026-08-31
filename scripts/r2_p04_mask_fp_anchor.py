#!/usr/bin/env python3
"""How much static content does the hard mask permanently discard? (offline, no SLAM)

This is the denominator the recovery question needs, and it is measured WITHOUT running the
campaign, because the campaign cannot measure it. ``R2-P04-MASKRATE`` establishes whether a
hard-mask arm reaches arm B's Gaussian budget; it deliberately does NOT claim anything about
*recovery* -- restoring static background that the mask blocked by mistake -- because in this
codebase masked pixels are zeroed in ``add_new_keyframe`` upstream of candidate formation, so a
mask+deferred arm would report ~0 recovery by construction (see ``r2_p04_maskrate.md`` §3).

Making recovery measurable needs a quarantine-instead-of-discard code path: a new mechanism, a
day of work, and its own pre-registration. That is only worth building if there is enough
wrongly-blocked static content to recover. This script measures how much, by comparing the
detector the mask arm actually uses against the frozen dynamic oracle the evaluation actually
scores against:

    person mask   Mask R-CNN, with the SAME parameters the mask arm resolves (read out of
                  ``configs/rgbd/experiments/r2_p04_maskrate/maskrate_m_mask_balloon.yaml``,
                  not duplicated here, so the two can never drift apart)
    ground        ``dynamic_mask_gtmc/`` -- the frozen, method-independent GT-pose
                  motion-consistency mask that ``utils/eval_utils.py`` scores every arm on

    FP  = person AND (NOT gtmc) AND depth-valid    <- blocked, but scored as static background
    FN  = gtmc AND (NOT person) AND depth-valid    <- dynamic, but the mask lets it in

FP is the ceiling on what any recovery mechanism could ever win back, expressed as a fraction of
the static support set the decision metrics are computed over. Depth validity is required
because a pixel with no depth was never insertable in the first place, so blocking it costs
nothing.

**GTMC is a frozen oracle, not ground truth, and on THIS sequence its known failure mode
inflates FP.** Its own manifest records: "momentarily-still or depth-invalid mover regions
under-flag on the per-frame motion test (balloon standing person unmasked while still)". Where
GTMC misses a still person, Mask R-CNN flagging that person is *correct* and still counts as FP
here. So the headline FP number is an UPPER bound on recoverable static content, and a large
part of it may be the oracle's under-flagging rather than the detector's over-firing.

To keep that confound from being invisible, FP is split by whether the mover has been at that
pixel *near this frame in time*:

    FP-inside-window   the mover was flagged there within +-W frames => most likely a
                       still-mover under-flag by GTMC, i.e. the mask was probably right and
                       there is nothing to recover
    FP-outside-window  the mover was never flagged there in that window => genuine static
                       background over-masked by the detector, i.e. actually recoverable

**FP-outside-window is the number that decides whether the quarantine mechanism is worth
building.** It is reported per frame and in total, with per-frame percentiles, because a
sequence mean can hide a few catastrophic frames (a false detection on a chair) behind a
harmless average.

The window is bounded on purpose. The obvious discriminator -- the SEQUENCE-WIDE union of GTMC
masks -- **saturates on this sequence and cannot discriminate**: the balloon mover roams, so the
union reaches ~91% of the image and almost nothing is left "outside" it. ``utils/eval_utils.py``
records the same effect for the pre-registered vacated mask ("on a 439-frame sequence where the
mover roams (Bonn balloon) it grows to 84% of the static support / 66% of the image"). Both
splits are reported, with the global one labelled by its own union coverage so a saturated
discriminator can never be read as a substantive zero.

Usage:
  python scripts/r2_p04_mask_fp_anchor.py                          # balloon, cuda
  python scripts/r2_p04_mask_fp_anchor.py --device cpu             # no GPU contention
  python scripts/r2_p04_mask_fp_anchor.py --limit 40               # quick smoke

Writes ``results/evidence/r2_p04_mask_fp_anchor.md`` + a per-frame CSV. Zero SLAM runs, no map,
no seeds: detector inference only, so it neither needs nor consumes a campaign slot.
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

MASK_CONFIG = "configs/rgbd/experiments/r2_p04_maskrate/maskrate_m_mask_balloon.yaml"
EVIDENCE = "results/evidence/r2_p04_mask_fp_anchor.md"
CSV_OUT = "results/evidence/r2_p04_mask_fp_anchor_perframe.csv"


def associations(dataset_path):
    """[(rgb_rel, depth_rel)] from ``associations.txt``.

    The two mask spaces are keyed differently -- ``dynamic_mask_gtmc/`` by DEPTH stem (as the
    eval loader indexes it) and the RGB the detector runs on by RGB stem -- so the pairing has
    to come from the association table the dataset ships, not from sorting two directories and
    hoping they line up.
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
    """Depth-valid mask: a pixel with no depth was never insertable, so masking it costs
    nothing and it must not be counted as recoverable content."""
    arr = np.asarray(Image.open(os.path.join(dataset_path, depth_rel)))
    return (arr.astype(np.float32) / depth_scale) > 0.01


def load_rgb(dataset_path, rgb_rel, device):
    arr = np.asarray(Image.open(os.path.join(dataset_path, rgb_rel)).convert("RGB"))
    return torch.from_numpy(arr).permute(2, 0, 1).float().div_(255.0).to(device)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", default=MASK_CONFIG,
                        help="the mask arm's config -- detector params are READ from it")
    parser.add_argument("--device", default=None, help="override SemanticMask.device")
    parser.add_argument("--limit", type=int, default=None, help="first N frames only (smoke)")
    parser.add_argument("--window", type=int, default=15,
                        help="primary temporal half-window W (frames) for the near-in-time GTMC "
                             "union; the sequence-wide union saturates on balloon (~91%% of the "
                             "image) and cannot discriminate (default: 15)")
    parser.add_argument("--windows", type=int, nargs="+", default=[5, 15, 30],
                        help="all half-windows to report, in ONE detector pass. The headline "
                             "number is window-dependent, so it is never reported alone "
                             "(default: 5 15 30)")
    parser.add_argument("--evidence", default=EVIDENCE)
    parser.add_argument("--csv", default=CSV_OUT)
    args = parser.parse_args()
    os.chdir(ROOT)

    config = load_config(args.config)
    if args.device:
        config["SemanticMask"]["device"] = args.device
    sem = config["SemanticMask"]
    dataset_path = config["Dataset"]["dataset_path"]
    depth_scale = float(config["Dataset"]["Calibration"]["depth_scale"])
    subdir = config["Results"]["static_bg_mask_subdir"]

    index = frozen_mask_index(os.path.join(dataset_path, subdir))
    pairs = associations(dataset_path)
    if args.limit:
        pairs = pairs[: args.limit]
    if not index or not pairs:
        print(f"missing inputs: {len(index)} frozen masks, {len(pairs)} associations")
        return 1

    print(f"# mask FP anchor: {sem['model']} (dilate {sem['dilate_px']}px, classes "
          f"{sem['dynamic_classes']}) vs frozen {subdir}")
    print(f"# {len(pairs)} associated frames from {dataset_path}, device={sem.get('device')}")

    # Load every frozen mask once (439 x 640x480 bool = ~135 MB), because both the global union
    # and each frame's temporal window are computed over them.
    frozen = []
    for _, depth_rel in pairs:
        stem = os.path.splitext(os.path.basename(depth_rel))[0]
        path = index.get(stem)
        frozen.append(None if path is None else load_frozen_mask(path))
    present = [m for m in frozen if m is not None]
    if not present:
        print("no frozen mask matched any associated depth frame")
        return 1
    union = np.logical_or.reduce(present)
    windows = sorted(set(list(args.windows) + [int(args.window)]))
    W = int(args.window)
    print(f"# GTMC sequence union covers {100 * union.mean():.1f}% of the image "
          f"({'SATURATED — the global split cannot discriminate' if union.mean() > 0.5 else 'usable'})")
    print(f"# temporal half-windows = {windows} frames (primary W={W})")

    rows = []
    skipped = 0
    for i, (rgb_rel, depth_rel) in enumerate(pairs):
        stem = os.path.splitext(os.path.basename(depth_rel))[0]
        gtmc = frozen[i]
        if gtmc is None:
            skipped += 1
            continue
        # "Has the mover been here NEAR THIS FRAME": union over [i-W, i+W]. Bounded, so unlike
        # the sequence-wide union it still discriminates on a sequence where the mover roams.
        # Every window is evaluated in this one detector pass, because the headline number is
        # window-dependent and must never be quoted without its sensitivity.
        near_by_w = {}
        for w in windows:
            near = [m for m in frozen[max(i - w, 0): i + w + 1] if m is not None]
            near_by_w[w] = np.logical_or.reduce(near) if near else gtmc
        valid = load_depth_valid(dataset_path, depth_rel, depth_scale)
        image = load_rgb(dataset_path, rgb_rel, sem.get("device") or "cuda")
        person_t = compute_semantic_dynamic_mask(config, image)
        person = (np.zeros_like(gtmc) if person_t is None
                  else person_t.squeeze(0).cpu().numpy().astype(bool))
        if person.shape != gtmc.shape:
            skipped += 1
            continue

        static_support = valid & (~gtmc)          # what the decision metrics are scored over
        fp = person & (~gtmc) & valid             # blocked, yet scored as static background
        fn = gtmc & (~person) & valid             # dynamic, yet the mask admits it
        row = {
            "frame": i,
            "rgb": rgb_rel,
            "depth_stem": stem,
            "person_px": int(person.sum()),
            "gtmc_px": int(gtmc.sum()),
            "valid_px": int(valid.sum()),
            "static_support_px": int(static_support.sum()),
            "fp_px": int(fp.sum()),
            "fp_inside_union_px": int((fp & union).sum()),
            "fp_outside_union_px": int((fp & (~union)).sum()),
            "fn_px": int(fn.sum()),
        }
        for w, near in near_by_w.items():
            row[f"fp_outside_w{w}_px"] = int((fp & (~near)).sum())
        rows.append(row)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(pairs)} frames")

    if not rows:
        print("no frame produced a comparison")
        return 1

    os.makedirs(os.path.dirname(args.csv), exist_ok=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return report(rows, sem, subdir, dataset_path, union, skipped, args, windows)


def _pct(num, den):
    return 100.0 * num / den if den else float("nan")


def report(rows, sem, subdir, dataset_path, union, skipped, args, windows):
    """Write the evidence file. Totals are pixel-summed over frames (a per-frame-mean of
    ratios would let near-empty frames outvote the frames where the mask actually fires)."""
    W = int(args.window)
    keys = ["person_px", "gtmc_px", "valid_px", "static_support_px", "fp_px",
            "fp_inside_union_px", "fp_outside_union_px", "fn_px"]
    keys += [f"fp_outside_w{w}_px" for w in windows]
    total = {k: sum(r[k] for r in rows) for k in keys}
    primary = f"fp_outside_w{W}_px"
    per_frame_out = sorted(_pct(r[primary], max(r["static_support_px"], 1)) for r in rows)

    def q(p):
        if not per_frame_out:
            return float("nan")
        return per_frame_out[min(int(p * len(per_frame_out)), len(per_frame_out) - 1)]

    # Worst frame by the SAME quantity the percentiles above are computed on (% of that
    # frame's own static support), so the two lines cannot disagree.
    worst = max(rows, key=lambda r: _pct(r[primary], max(r["static_support_px"], 1)))
    out = [
        "# R2-P04 offline anchor: how much static content does the hard mask discard?",
        "",
        "> Zero GPU-campaign cost (detector inference only, no SLAM, no map, no seeds).",
        f"> Generated by `scripts/r2_p04_mask_fp_anchor.py` from `{args.config}`.",
        f"> Per-frame CSV: `{args.csv}`",
        "",
        "## Why this exists",
        "",
        "`R2-P04-MASKRATE` answers whether a hard-mask arm reaches arm B's Gaussian budget. It "
        "deliberately does **not** claim anything about *recovery* — restoring static "
        "background the mask blocked by mistake — because this codebase makes that "
        "unmeasurable by configuration: `apply_semantic_insertion_gate` zeroes person depth "
        "inside `add_new_keyframe`, and `_classify_new_keyframe` then drops those pixels at "
        "`valid = isfinite(observed) & (observed > 0.01)`, upstream of the `uncertain` set that "
        "is the only thing candidacy is ever formed from. A mask+deferred arm would therefore "
        "report ~0 recovery **by construction** — an apparatus artifact, not a null result.",
        "",
        "Measuring recovery needs a quarantine-instead-of-discard code path: a new mechanism "
        "plus its own pre-registration. This file measures whether there is enough "
        "wrongly-blocked static content to justify building it.",
        "",
        "## Setup",
        "",
        f"- detector: **{sem['model']}**, classes `{sem['dynamic_classes']}`, dilate "
        f"**{sem['dilate_px']}px** — read out of the mask arm's own config, so the two cannot "
        f"drift apart",
        f"- reference: frozen **`{subdir}`** (the method-independent mask `utils/eval_utils.py` "
        f"scores every arm against)",
        f"- sequence: `{dataset_path}`, **{len(rows)} frames** compared"
        + (f" ({skipped} skipped: no frozen mask or shape mismatch)" if skipped else ""),
        "- depth validity required throughout: a pixel with no depth was never insertable, so "
        "blocking it costs nothing",
        "",
        "## Result",
        "",
        "| quantity | pixels | % of static support |",
        "|---|---|---|",
        f"| static support (depth-valid ∧ ¬GTMC) | {total['static_support_px']:,} | 100% |",
        f"| mask blocks it, GTMC calls it static (**FP**) | {total['fp_px']:,} | "
        f"**{_pct(total['fp_px'], total['static_support_px']):.2f}%** |",
        f"| └ **of that, mover NOT there within ±{W} frames (recoverable)** | "
        f"{total[primary]:,} | "
        f"**{_pct(total[primary], total['static_support_px']):.2f}%** |",
        f"| GTMC dynamic that the mask admits (**FN**) | {total['fn_px']:,} | — |",
        "",
        "**Window sensitivity — the headline number moves with W, so it is never quoted "
        "alone:**",
        "",
        "| half-window ±W | recoverable FP | % of static support |",
        "|---|---|---|",
    ] + [
        f"| ±{w}{' (primary)' if w == W else ''} | {total[f'fp_outside_w{w}_px']:,} | "
        f"**{_pct(total[f'fp_outside_w{w}_px'], total['static_support_px']):.2f}%** |"
        for w in windows
    ] + [
        f"| sequence-wide union | {total['fp_outside_union_px']:,} | "
        f"{_pct(total['fp_outside_union_px'], total['static_support_px']):.2f}% "
        f"— **SATURATED, do not quote** ({100 * union.mean():.1f}% of the image) |"
        if union.mean() > 0.5 else
        f"| sequence-wide union | {total['fp_outside_union_px']:,} | "
        f"{_pct(total['fp_outside_union_px'], total['static_support_px']):.2f}% |",
        "",
        "",
        f"Detector coverage {_pct(total['person_px'], total['valid_px']):.2f}% of valid pixels; "
        f"GTMC coverage {_pct(total['gtmc_px'], total['valid_px']):.2f}%.",
        "",
        f"Per-frame recoverable FP at ±{W}, as % of that frame's static support "
        "(a sequence mean can hide a few catastrophic frames behind a harmless average):",
        "",
        f"- median **{q(0.5):.2f}%**, p90 **{q(0.9):.2f}%**, max **{max(per_frame_out):.2f}%**",
        f"- worst frame `{worst['depth_stem']}`: {worst[primary]:,} px "
        f"({_pct(worst[primary], max(worst['static_support_px'], 1)):.2f}%)",
        "",
        "## How to read this — and how not to",
        "",
        "**GTMC is a frozen oracle, not ground truth, and on this sequence its known failure "
        "mode inflates FP.** Its own `manifest.json` records that "
        "\"momentarily-still or depth-invalid mover regions under-flag on the per-frame motion "
        "test (balloon standing person unmasked while still)\". Wherever GTMC misses a still "
        "person, Mask R-CNN flagging that person is **correct** and is nevertheless counted as "
        "FP here. The total FP row is therefore an **upper bound**, and the temporal split "
        "exists to quarantine that confound: a pixel the mover occupied within a few frames is "
        "most likely a still-mover under-flag, so the mask was probably right and there is "
        "nothing there to recover.",
        "",
        f"**The recoverable-FP row is the decision number.** It is where the mover was not flagged "
        f"within ±{W} frames, so the detector fired on background that was static at "
        f"the time and the content is genuinely lost. It is a **ceiling** on what any recovery "
        f"mechanism could win back, not an estimate: a real mechanism would recover only the "
        f"part that survives cross-frame confirmation.",
        "",
        "**Why not the sequence-wide union.** It is the obvious discriminator and it does not "
        "work here: the balloon mover roams, so the union covers "
        f"{100 * union.mean():.1f}% of the image and its 'outside' bucket is empty for a "
        "geometric reason. `utils/eval_utils.py` documents the same saturation for the "
        "pre-registered vacated mask (grows to 84% of the static support on this sequence). A "
        "near-zero number from a saturated discriminator is not evidence of a small effect, and "
        "the window exists so the split can actually discriminate. The window length is a "
        "judgement call, not a pre-registered constant — vary it with `--window` before leaning "
        "on the number.",
        "",
        "Even this is an upper bound for a second reason: pixels are not Gaussians. Insertion "
        "downsamples, and a blocked pixel adjacent to an admitted one may cost no map coverage "
        "at all. Treat the percentage as an order of magnitude for a go/no-go on the quarantine "
        "mechanism, not as a predicted fidelity delta.",
        "",
        "Descriptive and non-preregistered. It measures the dataset and the detector, not any "
        "arm, so it decides nothing on its own and does not touch the R2-P02 H1 record. "
        "GO/KILL remains the user's.",
        "",
    ]
    os.makedirs(os.path.dirname(args.evidence), exist_ok=True)
    with open(args.evidence, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("\n".join(out[out.index("## Result"):]))
    print(f"written: {args.evidence}\nwritten: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
