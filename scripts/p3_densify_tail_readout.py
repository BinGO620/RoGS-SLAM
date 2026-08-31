#!/usr/bin/env python3
"""P3-DENSIFY-TAIL readout: the per-sequence frac_op_lt_001 table + the branch call.

The decision family is the PRE-REGISTERED monotone rule (results/evidence/p3_densify_tail_prereg.md §2.4):
  CONFIRMED  : LO > BASE > HI strictly, all three pairwise gaps > 0.005 (0.5pp)
  PARTIAL    : LO > BASE alone OR BASE > HI alone (one gap), or a gap <= 0.005
  FALSIFIED  : monotonicity violated in either direction (LO <= BASE or BASE <= HI
               in effect, i.e., not (LO > BASE and BASE > HI))

This readout reports the numbers and the branch per seq; the CAMPAIGN-level call
(6/6 vs falsified) is made from the prereg §2.4 + this table together.

Usage: python scripts/p3_densify_tail_readout.py [--out-dir results/runs/P3/P3-DENSIFY-TAIL]
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = "results/runs/P3/P3-DENSIFY-TAIL"
GAP = 0.005  # prereg §2.4: >0.005 = a real move (0.5 percentage points)
ARM_ORDER = ("lo", "base", "hi")


def load(out_dir: Path) -> dict:
    """{seq: {arm: {seed: row}}} for exit-0 runs with opacity_stats."""
    path = out_dir / "p3_densify_tail_results.jsonl"
    out: dict = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("exit") != 0 or not row.get("opacity_stats"):
            continue
        out.setdefault(row["seq"], {}).setdefault(row["arm"], {})[int(row["seed"])] = row
    return out


def _mean_frac(rows):
    vals = [r["opacity_stats"].get("frac_op_lt_001") for r in rows.values()
            if r["opacity_stats"].get("frac_op_lt_001") is not None]
    return st.mean(vals) if vals else None


def branch(lo, base, hi):
    """Pre-registered branch rule (prereg §2.4). lo/base/hi are mean frac_op_lt_001."""
    if lo is None or base is None or hi is None:
        return "—"
    monotone_ok = (lo - base > GAP) and (base - hi > GAP)
    if monotone_ok:
        return "CONFIRMED"
    if (lo - base > GAP) or (base - hi > GAP):
        return "PARTIAL"
    return "FALSIFIED"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    data = load(out_dir)

    print(f"# P3-DENSIFY-TAIL readout — {out_dir}")
    print(f"# pre-registered rule (results/evidence/p3_densify_tail_prereg.md §2.4):")
    print(f"#   CONFIRMED: LO > BASE > HI, all gaps > {GAP};  PARTIAL: one real gap;  "
          f"FALSIFIED: monotonicity violated")
    print(f"# frac_op_lt_001 = fraction of final-map Gaussians with sigmoid(opacity) < 0.01\n")

    print("## Tail fraction (frac_op_lt_001, 3-seed mean ± own sd)")
    print("| seq | LO | BASE | HI | branch |")
    print("|---|---|---|---|---|")
    verdicts = []
    for seq in sorted(data):
        rows = {arm: data[seq].get(arm, {}) for arm in ARM_ORDER}
        if not all(rows.values()):
            print(f"| {seq} | (incomplete) | | | — |")
            continue
        m = {arm: _mean_frac(rows[arm]) for arm in ARM_ORDER}
        sds = {arm: (st.pstdev([r["opacity_stats"]["frac_op_lt_001"] for r in rows[arm].values()])
                     if len(rows[arm]) > 1 else 0.0) for arm in ARM_ORDER}
        br = branch(m["lo"], m["base"], m["hi"])
        verdicts.append((seq, br))
        print(f"| {seq} | {m['lo']:.4f}±{sds['lo']:.4f} | {m['base']:.4f}±{sds['base']:.4f} | "
              f"{m['hi']:.4f}±{sds['hi']:.4f} | **{br}** |")

    print("\n## Secondary: frac_op_lt_005 (should move LESS than frac_op_lt_001 if effect is tail-specific)")
    print("| seq | LO | BASE | HI |")
    print("|---|---|---|---|")
    for seq in sorted(data):
        rows = {arm: data[seq].get(arm, {}) for arm in ARM_ORDER}
        if not all(rows.values()):
            continue
        f005 = {arm: st.mean([r["opacity_stats"].get("frac_op_lt_005") for r in rows[arm].values()
                              if r["opacity_stats"].get("frac_op_lt_005") is not None])
                for arm in ARM_ORDER}
        print(f"| {seq} | {f005['lo']:.4f} | {f005['base']:.4f} | {f005['hi']:.4f} |")

    print("\n## Tertiary: frac_op_ge_090 (should stay stable if effect is tail-specific)")
    print("| seq | LO | BASE | HI |")
    print("|---|---|---|---|")
    for seq in sorted(data):
        rows = {arm: data[seq].get(arm, {}) for arm in ARM_ORDER}
        if not all(rows.values()):
            continue
        f090 = {arm: st.mean([r["opacity_stats"].get("frac_op_ge_090") for r in rows[arm].values()
                              if r["opacity_stats"].get("frac_op_ge_090") is not None])
                for arm in ARM_ORDER}
        print(f"| {seq} | {f090['lo']:.4f} | {f090['base']:.4f} | {f090['hi']:.4f} |")

    print("\n## Campaign-level (per prereg §2.4)")
    confirmed = sum(1 for _, br in verdicts if br == "CONFIRMED")
    partial = sum(1 for _, br in verdicts if br == "PARTIAL")
    falsified = sum(1 for _, br in verdicts if br == "FALSIFIED")
    print(f"  CONFIRMED: {confirmed} · PARTIAL: {partial} · FALSIFIED: {falsified}")
    if falsified >= 3:
        print("  >>> >=3 FALSIFIED => mechanism claim FALSIFIED as a general claim.")
    elif falsified >= 1:
        print("  >>> >=1 FALSIFIED => sequence-dependent at best; mechanism claim weakened.")
    else:
        print("  >>> no FALSIFIED => mechanism claim supported (all seq CONFIRMED or PARTIAL).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
