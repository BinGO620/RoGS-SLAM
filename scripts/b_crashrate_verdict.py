#!/usr/bin/env python3
"""Candidate B Phase 0 verdict: is the mask-free bistability seed-driven or timing-driven?

Applies the rule pre-registered in
``results/evidence/candidateB_crashrate_preregistration.md`` §4. Introduces no threshold.

Block T = identical config AND identical seed, repeated. Block S = distinct seeds.
If block T splits as much as block S, the spread is asynchronous-scheduling noise, and a
seed-averaged ATE is not an estimator of a method effect on this backbone.

Usage:
  python scripts/b_crashrate_verdict.py --root results/runs/B/B-CRASHRATE-3090
"""

import argparse
import csv
import glob
import json
import os

import numpy as np

COLLAPSE_CM = 50.0      # pre-registered (prereg §3)
SPLIT_RATIO = 1.5       # pre-registered (prereg §4)
STABLE_RATIO = 1.1


def _ate(run_dir):
    """Full-trajectory ATE from tables/tracking_raw.csv -- never the console keyframe RMSE."""
    path = os.path.join(run_dir, "tables", "tracking_raw.csv")
    if not os.path.isfile(path):
        return None
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        for k in ("ate_rmse_cm", "ATE_RMSE_cm", "ate_rmse"):
            if k in r and r[k] not in ("", None):
                try:
                    return float(r[k])
                except ValueError:
                    pass
    return None


def collect(root):
    blocks = {"T": {}, "S": {}}
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.isdir(d):
            continue
        name = os.path.basename(d)
        b = name[0] if name[:1] in ("T", "S") and "_" in name else None
        if b is None:
            continue
        a = _ate(d)
        if a is not None:
            blocks[b][name] = a
    return blocks


def _stats(vals):
    v = np.array(sorted(vals), dtype=float)
    if v.size == 0:
        return None
    return {
        "n": int(v.size), "min": float(v.min()), "max": float(v.max()),
        "median": float(np.median(v)),
        "ratio": float(v.max() / v.min()) if v.min() > 0 else float("inf"),
        "iqr": float(np.percentile(v, 75) - np.percentile(v, 25)),
        "collapse_rate": float((v > COLLAPSE_CM).mean()),
        "values": [float(x) for x in v],
    }


def verdict(root):
    blocks = collect(root)
    st = {b: _stats(list(v.values())) for b, v in blocks.items()}
    for b in ("T", "S"):
        s = st[b]
        label = ("timing only (same config, same seed)" if b == "T"
                 else "seed + timing (distinct seeds)")
        print(f"block {b} -- {label}")
        if not s:
            print("  (no runs)")
            continue
        print(f"  n={s['n']}  ate_rmse_cm: " + " ".join(f"{x:.2f}" for x in s["values"]))
        print(f"  min={s['min']:.2f} max={s['max']:.2f} median={s['median']:.2f} "
              f"max/min={s['ratio']:.2f} IQR={s['iqr']:.2f} "
              f"collapse(>{COLLAPSE_CM:.0f}cm)={s['collapse_rate']:.0%}")

    T, S = st["T"], st["S"]
    if not T or not S or T["n"] < 3 or S["n"] < 3:
        v, why = "INCOMPLETE", "fewer than 3 runs in a block"
    elif T["ratio"] >= SPLIT_RATIO:
        v = "T-CONFIRMED (timing-driven)"
        why = (f"identical config AND seed still spans {T['min']:.1f}-{T['max']:.1f} cm "
               f"(max/min {T['ratio']:.2f}) => a seed-averaged ATE is not an estimator of a "
               f"method effect on the mask-free backbone; mask-free judgements must be "
               f"restated as crash rates")
    elif T["ratio"] <= STABLE_RATIO and S["ratio"] >= SPLIT_RATIO:
        v = "S-CONFIRMED (seed-driven)"
        why = (f"repeats are stable (max/min {T['ratio']:.2f}) while seeds split "
               f"({S['ratio']:.2f}) => the multi-seed protocol is sound but under-powered")
    elif T["ratio"] <= STABLE_RATIO and S["ratio"] <= STABLE_RATIO:
        v = "NEITHER (did not reproduce)"
        why = (f"both blocks stable (T {T['ratio']:.2f}, S {S['ratio']:.2f}): the 44->97 cm "
               f"spread did not reproduce in {T['n'] + S['n']} runs; treat the T2 crowd2 "
               f"numbers as unexplained until the source is found")
    else:
        v, why = "INDETERMINATE", f"T max/min {T['ratio']:.2f}, S max/min {S['ratio']:.2f}"
    print(f"\nVERDICT: {v}  --  {why}")
    blob = {"verdict": v, "why": why, "blocks": st, "runs": blocks}
    with open(os.path.join(root, "b_crashrate_verdict.json"), "w") as fh:
        json.dump(blob, fh, indent=2)
    return blob


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="results/runs/B/B-CRASHRATE-3090")
    verdict(ap.parse_args().root)


if __name__ == "__main__":
    main()
