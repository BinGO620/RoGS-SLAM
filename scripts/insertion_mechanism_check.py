#!/usr/bin/env python3
"""Post-hoc mechanism check for the insertion intervention (exp35).

WHY THIS EXISTS. The pre-registered gate G3 (insertion_channel_prereg.md §2) asked for
``n_gaussians(tracking_only) > n_gaussians(eboth)`` as the mechanism-direction check, on
the reasoning that switching the insertion gate off lets dynamic Gaussians into the map.
That gate FAILED (5/9 seed-pairs in the expected direction -- a coin flip).

G3 was mis-specified, for two reasons that were both knowable before dispatch:
  1. exp34's own PLY autopsy had already measured that Gaussian COUNT is insensitive to
     mask changes (+-4% over 6 pairs) while OPACITY moves consistently (6/6 down). The
     gate therefore keyed on the one quantity that campaign showed does not respond.
  2. These configs run ``Mapping.lifecycle_mode = prune`` (verified from the resolved
     config), so Gaussians that ARE inserted can be pruned again before the final save.
     A steady-state count cannot track a per-keyframe insertion decision.

The intervention itself is verified DIRECTLY and unambiguously by G1/G2, which are
log-level, not proxy: the insertion gate logs 0 firings in every treatment run and
67-151 firings in every control run. That is what licenses reading the ATE.

This script adds the observable exp34 showed IS sensitive, as a POST-HOC substitute.
It is explicitly NOT a pre-registered gate and cannot rescue or overturn G3; it is
reported so the mechanism claim rests on a quantity that can actually move.

Usage:
  python scripts/insertion_mechanism_check.py
"""

import glob
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from scripts.map_profile import profile  # noqa: E402

SEQS = ("balloon", "f3_wk_xyz", "pt1")
SEEDS = (0, 1, 2)
ROOTS = ("results/runs/PBA", "results/runs/T2/T2-QUOTA-3090")


def _ply(arm, seq, seed):
    for root in ROOTS:
        hits = glob.glob(os.path.join(root, f"{arm}_{seq}_seed{seed}",
                                      "**", "final", "point_cloud.ply"), recursive=True)
        if hits:
            return sorted(hits)[-1]
    return None


def main():
    rows, summary = [], {}
    for seq in SEQS:
        pairs = []
        for seed in SEEDS:
            a = _ply("pba_tracking_only", seq, seed)
            b = _ply("eboth", seq, seed)
            if not (a and b):
                continue
            pa, pb = profile(a), profile(b)
            row = {
                "seq": seq, "seed": seed,
                "n_trk": int(pa["n_gaussians"]), "n_eboth": int(pb["n_gaussians"]),
                "op_trk": float(pa["opacity"]["mean"]), "op_eboth": float(pb["opacity"]["mean"]),
            }
            row["d_n_pct"] = 100.0 * (row["n_trk"] - row["n_eboth"]) / row["n_eboth"]
            row["d_op"] = row["op_trk"] - row["op_eboth"]
            rows.append(row)
            pairs.append(row)
        if pairs:
            summary[seq] = {
                "n_higher_in_trk": sum(1 for r in pairs if r["d_n_pct"] > 0),
                "opacity_lower_in_trk": sum(1 for r in pairs if r["d_op"] < 0),
                "pairs": len(pairs),
                "median_abs_d_n_pct": round(float(np.median([abs(r["d_n_pct"]) for r in pairs])), 2),
                "median_d_op": round(float(np.median([r["d_op"] for r in pairs])), 4),
            }

    print(f"{'seq':<12} {'seed':<5} {'n_trk':>8} {'n_eboth':>8} {'dn%':>8} "
          f"{'op_trk':>8} {'op_eboth':>9} {'d_op':>8}")
    print("-" * 74)
    for r in rows:
        print(f"{r['seq']:<12} {r['seed']:<5} {r['n_trk']:>8} {r['n_eboth']:>8} "
              f"{r['d_n_pct']:>+8.1f} {r['op_trk']:>8.4f} {r['op_eboth']:>9.4f} {r['d_op']:>+8.4f}")

    print("\nper-sequence tally (tracking_only vs eboth):")
    for seq, s in summary.items():
        print(f"  {seq:<12} count higher {s['n_higher_in_trk']}/{s['pairs']}  "
              f"(median |dn| {s['median_abs_d_n_pct']}%)   "
              f"opacity lower {s['opacity_lower_in_trk']}/{s['pairs']}  "
              f"(median d_op {s['median_d_op']:+.4f})")

    tot = len(rows)
    n_dir = sum(1 for r in rows if r["d_n_pct"] > 0)
    op_dir = sum(1 for r in rows if r["d_op"] < 0)
    print(f"\nG3 as pre-registered (count higher in tracking_only): {n_dir}/{tot}  -> FAILED")
    print(f"post-hoc substitute (opacity lower in tracking_only):  {op_dir}/{tot}")
    print("\nNeither tally licenses the ATE reading on its own. G1/G2 do: insertion-gate")
    print("firings were 0/0/0 in every treatment run and 67-151 in every control run.")

    out = "results/evidence/insertion_mechanism_check.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump({"rows": rows, "summary": summary,
                   "G3_prereg_count_direction": f"{n_dir}/{tot}",
                   "posthoc_opacity_direction": f"{op_dir}/{tot}"}, fh, indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
