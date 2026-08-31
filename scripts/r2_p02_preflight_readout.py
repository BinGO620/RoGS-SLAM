#!/usr/bin/env python3
"""R2-P02 pre-flight four-arm readout (A/B/D/E x 3 seeds, rgd frozen pose).

Reads results/runs/R2-P02/R2-P02-PREFLIGHT-rgd/preflight_results.jsonl and prints
the pre-registered gate table. Every contrast is reported against the LARGER of
the two arms' own 3-seed sd (the conservative denominator used throughout this
campaign) plus the per-seed sign count -- prereg 6 forbids single-seed claims,
so a contrast with a flipped sign is inside the band regardless of its mean.

Headline metric = static_vacated_psnr (amendment #01 A, written pre-data).
Usage: python scripts/r2_p02_preflight_readout.py
"""
from __future__ import annotations

import json
import statistics as st
from pathlib import Path

JSONL = Path("results/runs/R2-P02/R2-P02-PREFLIGHT-rgd/preflight_results.jsonl")
ARMS = ["A_prune", "B_deferred", "D_exit", "E_exit_fill"]
HEADLINE = "static_vacated_psnr"

# (metric, higher_is_better)
METRICS = [
    ("static_vacated_psnr", True),
    ("static_nonvacated_psnr", True),
    ("static_psnr", True),
    ("static_ssim", True),
    ("static_vacated_depth_l1_pen_cm", False),
    ("static_depth_l1_pen_cm", False),
    ("refined_num_gaussians", False),
    ("online_peak_gpu_memory_gb", False),
    ("online_fps", True),
    ("ate_rmse_cm", False),
]

# Pre-registered contrasts. (label, treat, ctrl, gate)
CONTRASTS = [
    ("CHECKPOINT-2 (H1)", "E_exit_fill", "A_prune", "E beats prune on headline"),
    ("CHECKPOINT-1 (H1a)", "D_exit", "B_deferred", "exit beats deferred"),
    ("H1b", "E_exit_fill", "D_exit", "fill is the key"),
    ("compactness corollary", "B_deferred", "A_prune", "deferred vs prune (historical -57%)"),
    ("E vs B", "E_exit_fill", "B_deferred", "full method vs deferred"),
]


def load() -> dict[str, dict[int, dict]]:
    out: dict[str, dict[int, dict]] = {a: {} for a in ARMS}
    for line in JSONL.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        arm = row.get("arm")
        if arm not in out:
            continue
        out[arm][int(row["seed"])] = row.get("metrics", row)
    return out


def series(data, arm, metric):
    vals = []
    for seed in sorted(data[arm]):
        v = data[arm][seed].get(metric)
        if isinstance(v, (int, float)):
            vals.append(float(v))
    return vals


def sd(vals):
    return st.stdev(vals) if len(vals) > 1 else float("nan")


def main() -> None:
    data = load()

    print(f"# R2-P02 pre-flight four-arm readout  (headline = {HEADLINE})\n")
    print("## Per-arm, per-seed\n")
    have = [a for a in ARMS if data[a]]
    print("| arm | n | " + " | ".join(m for m, _ in METRICS) + " |")
    print("|---" * (len(METRICS) + 2) + "|")
    for arm in have:
        cells = []
        for metric, _ in METRICS:
            v = series(data, arm, metric)
            cells.append(f"{st.mean(v):.4g} ± {sd(v):.3g}" if len(v) > 1 else
                         (f"{v[0]:.4g}" if v else "-"))
        print(f"| {arm} | {len(data[arm])} | " + " | ".join(cells) + " |")

    print(f"\n## Raw {HEADLINE} per seed\n")
    for arm in have:
        v = series(data, arm, HEADLINE)
        print(f"- **{arm}**: " + " / ".join(f"{x:.4f}" for x in v) +
              f"   (mean {st.mean(v):.4f}, own sd {sd(v):.4f})")

    print("\n## Pre-registered contrasts on the headline\n")
    print("| contrast | gate | diff | /larger own sd | per-seed sign | verdict |")
    print("|---|---|---|---|---|---|")
    for label, treat, ctrl, gate in CONTRASTS:
        t, c = series(data, treat, HEADLINE), series(data, ctrl, HEADLINE)
        if not t or not c:
            print(f"| {label} | {gate} | - | - | - | **not run** |")
            continue
        diff = st.mean(t) - st.mean(c)
        denom = max(sd(t), sd(c))
        ratio = abs(diff) / denom if denom == denom and denom > 0 else float("nan")
        n = min(len(t), len(c))
        same = sum(1 for i in range(n) if (t[i] - c[i]) > 0) if diff > 0 else \
               sum(1 for i in range(n) if (t[i] - c[i]) < 0)
        ok = ratio > 1.0 and same == n
        print(f"| {label} | {gate} | {diff:+.4f} | {ratio:.2f} | {same}/{n} | "
              f"**{'clears' if ok else 'inside band'}** |")

    print("\n## Every metric, treatment vs its pre-registered control\n")
    for label, treat, ctrl, _ in CONTRASTS:
        if not data[treat] or not data[ctrl]:
            continue
        print(f"\n### {label}: {treat} - {ctrl}\n")
        print("| metric | ctrl | treat | diff | /larger own sd | sign | better? |")
        print("|---|---|---|---|---|---|---|")
        for metric, hib in METRICS:
            t, c = series(data, treat, metric), series(data, ctrl, metric)
            if not t or not c:
                continue
            diff = st.mean(t) - st.mean(c)
            denom = max(sd(t), sd(c))
            ratio = abs(diff) / denom if denom == denom and denom > 0 else float("nan")
            n = min(len(t), len(c))
            better = [(t[i] - c[i]) > 0 if hib else (t[i] - c[i]) < 0 for i in range(n)]
            print(f"| {metric} {'↑' if hib else '↓'} | {st.mean(c):.4g} | {st.mean(t):.4g} | "
                  f"{diff:+.4g} | {ratio:.2f} | {sum(better)}/{n} | "
                  f"{'treat' if (diff > 0) == hib else 'ctrl'} |")

    print("\n---\nGO/KILL and narrative direction are the user's call (pre-registration 9).")


if __name__ == "__main__":
    main()
