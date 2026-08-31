#!/usr/bin/env python3
"""Insertion-channel verdict: completes the 2x2 factorial of the semantic mask (exp35).

exp34's PBA verdict located 44-80% of the mask's ATE benefit in the BA channel
(``mask_mapping``) and left an explicit gap: the remaining 20-56% sits in
``mask_insertion`` and/or tracking, unseparated. This script reads the fourth cell.

                 | mask_insertion=ON      | mask_insertion=OFF
    -------------|------------------------|--------------------------
    mapping=ON   | eboth      (control)   | tracking_only  <- exp35
    mapping=OFF  | PBA        (exp34)     | maskfree       (control)

    share_insertion = (ATE_trackingonly - ATE_eboth) / (ATE_maskfree - ATE_eboth)

Label mapping (pre-registered in results/evidence/insertion_channel_prereg.md §4;
the PBA prereg got this inverted once, so it is spelled out): removing a component
and seeing ATE get WORSE is what implicates that component. share -> 1 means
insertion carries the benefit; share -> 0 means the benefit is not in insertion.

Thresholds and gates are INHERITED, not re-fitted:
  * resolvability gate + RESOLVE_RATIO      <- scripts/pba_verdict.py (criterion 8)
  * per-sequence readable floor = 1/ratio   <- prereg §3 (NOT a single global cutoff)

Usage:
  python scripts/insertion_verdict.py --pba results/runs/PBA \
      --controls results/runs/T2/T2-QUOTA-3090
"""

import argparse
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

# Inherit the gate and the ATE extractor from the PBA verdict rather than restating them,
# so the two campaigns are judged by byte-identical rules (the discipline R2-P03 set).
from scripts.pba_verdict import RESOLVE_RATIO, _collect  # noqa: E402

# Sequences that passed the resolvability gate in exp34. mv_no_box (ratio 0.54) is
# excluded by the prereg before any treatment arm is read.
SEQUENCES = ("balloon", "f3_wk_xyz", "pt1")

# pt1 was declared descriptive-only in the exp34 corroboration batch (its mask-free arm
# spans the 38-63cm "everyone fails" band). Carried forward verbatim.
DESCRIPTIVE_ONLY = ("pt1",)


def _controls_for(seq, pba_root, ctl_root):
    """eboth/maskfree live in T2-QUOTA for balloon, in PBA for the corroboration seqs."""
    out = {}
    for arm, pat in (("eboth", f"eboth_{seq}_seed*"),
                     ("maskfree", f"control_maskfree_{seq}_seed*")):
        found = _collect(ctl_root, pat) or _collect(pba_root, pat)
        out[arm] = found
    return out


def verdict(pba_root, ctl_root):
    report = {}
    for seq in SEQUENCES:
        arms = _controls_for(seq, pba_root, ctl_root)
        arms["tracking_only"] = _collect(pba_root, f"pba_tracking_only_{seq}_seed*")
        arms["pba"] = _collect(pba_root, f"pba_mapping_off_{seq}*seed*")

        vals = {k: np.array([v for _n, v in a], dtype=float) for k, a in arms.items()}
        if vals["eboth"].size == 0 or vals["maskfree"].size == 0:
            report[seq] = {"status": "NO CONTROLS"}
            continue

        e, f = float(vals["eboth"].mean()), float(vals["maskfree"].mean())
        total = f - e
        spread = max(float(vals["eboth"].ptp()), float(vals["maskfree"].ptp()))
        ratio = (total / spread) if spread > 0 else float("inf")

        row = {
            "descriptive_only": seq in DESCRIPTIVE_ONLY,
            "n": {k: int(v.size) for k, v in vals.items()},
            "ate": {k: (None if v.size == 0 else round(float(v.mean()), 3))
                    for k, v in vals.items()},
            "per_seed": {k: [round(x, 3) for x in v.tolist()] for k, v in vals.items()},
            "total_effect_cm": round(total, 3),
            "within_arm_spread_cm": round(spread, 3),
            "resolve_ratio": round(ratio, 2),
            "resolvable": bool(total >= RESOLVE_RATIO * spread),
            # prereg §3: the floor is per-sequence, = 1/ratio, not one global number
            "readable_floor": round(1.0 / ratio, 3) if ratio not in (0, float("inf")) else 0.0,
        }

        if vals["tracking_only"].size and abs(total) > 1e-9:
            t = float(vals["tracking_only"].mean())
            row["share_insertion"] = round((t - e) / total, 3)
            row["above_readable_floor"] = bool(row["share_insertion"] > row["readable_floor"])
        if vals["pba"].size and abs(total) > 1e-9:
            p = float(vals["pba"].mean())
            row["share_BA"] = round((p - e) / total, 3)

        # ---- 2x2 decomposition (prereg §5): only computable with all four cells ----
        if vals["tracking_only"].size and vals["pba"].size:
            t, p = float(vals["tracking_only"].mean()), float(vals["pba"].mean())
            main_ins = 0.5 * ((t - e) + (f - p))
            main_map = 0.5 * ((p - e) + (f - t))
            interaction = (f - p) - (t - e)
            # Recovery fractions: starting from maskfree, how much of the joint benefit
            # does each channel recover ALONE? These are the duals of the shares
            # (recovery_mapping == 1 - share_insertion) and they are the unambiguous way
            # to state overlap, so they are reported instead of an "additive/synergy" word.
            #
            # !! The prereg §5 gloss is misleading and is corrected here. It labelled
            # interaction > 0 as "super-additive => 必须两条都有" (need both). That English
            # gloss does not follow: the interaction sign is frame-dependent (positive in
            # damage terms == sub-additive in benefit terms), and when one channel alone
            # already recovers ~all of the benefit, "need both" is exactly backwards. The
            # measured quantity and the threshold (|interaction| vs spread) are unchanged;
            # only the verbal label is replaced by the recovery fractions below.
            rec_map = (f - t) / total if abs(total) > 1e-9 else None
            rec_ins = (f - p) / total if abs(total) > 1e-9 else None
            overlap = (rec_map + rec_ins - 1.0) if None not in (rec_map, rec_ins) else None
            row["factorial"] = {
                "insertion_main_effect_cm": round(main_ins, 3),
                "mapping_main_effect_cm": round(main_map, 3),
                "interaction_cm": round(interaction, 3),
                "interaction_vs_spread": (round(abs(interaction) / spread, 2)
                                          if spread > 0 else float("inf")),
                "recovery_mapping_alone": round(rec_map, 3) if rec_map is not None else None,
                "recovery_insertion_alone": round(rec_ins, 3) if rec_ins is not None else None,
                # >0 means the two channels protect overlapping things
                "overlap": round(overlap, 3) if overlap is not None else None,
                "reading": (
                    "independent (each channel recovers a disjoint part)"
                    if overlap is not None and abs(overlap) < 0.10 else
                    "overlapping (their solo recoveries sum past 100%)"
                    if overlap is not None and overlap > 0 else
                    "incomplete (solo recoveries sum below 100%: part of the benefit needs both)"
                ),
                "shares_sum": (round(row.get("share_BA", 0) + row.get("share_insertion", 0), 3)
                               if "share_BA" in row and "share_insertion" in row else None),
            }
        report[seq] = row

    _print(report)
    return {"verdict": _decide(report), "sequences": report}


def _print(report):
    hdr = (f"{'sequence':12s} {'eboth':>7s} {'trkOnly':>8s} {'PBA':>7s} {'maskfree':>9s} | "
           f"{'total':>7s} {'spread':>7s} {'ratio':>6s} {'resolv':>7s} | "
           f"{'floor':>6s} {'shr_ins':>8s} {'shr_BA':>7s}")
    print(hdr + "\n" + "-" * len(hdr))
    for seq, r in report.items():
        if r.get("status"):
            print(f"{seq:12s} {r['status']}")
            continue
        a = r["ate"]
        def _f(x, w):
            return f"{x:{w}.2f}" if x is not None else f"{'--':>{w}s}"
        si = r.get("share_insertion")
        sb = r.get("share_BA")
        tag = " (descriptive)" if r["descriptive_only"] else ""
        print(f"{seq:12s} {_f(a['eboth'],7)} {_f(a['tracking_only'],8)} {_f(a['pba'],7)} "
              f"{_f(a['maskfree'],9)} | {r['total_effect_cm']:7.2f} {r['within_arm_spread_cm']:7.2f} "
              f"{r['resolve_ratio']:6.2f} {str(r['resolvable']):>7s} | "
              f"{r['readable_floor']:6.3f} "
              + (f"{si:8.3f}" if si is not None else f"{'--':>8s}") + " "
              + (f"{sb:7.3f}" if sb is not None else f"{'--':>7s}") + tag)

    print("\nshare_insertion = (trackingOnly - eboth)/(maskfree - eboth): the fraction of the")
    print("  mask benefit carried by the INSERTION channel. 1 = all of it, 0 = none.")
    print("floor = 1/ratio = the per-sequence noise floor on any share (prereg §3): a share")
    print("  below it is not readable on that sequence, however suggestive it looks.")

    print("\n2x2 factorial decomposition (prereg §5):")
    for seq, r in report.items():
        fa = (r or {}).get("factorial")
        if not fa:
            continue
        print(f"  {seq}")
        print(f"    main effects   insertion {fa['insertion_main_effect_cm']:+7.2f} cm | "
              f"mapping {fa['mapping_main_effect_cm']:+7.2f} cm | "
              f"interaction {fa['interaction_cm']:+7.2f} cm "
              f"({fa['interaction_vs_spread']:.2f}x spread)")
        print(f"    solo recovery  mapping alone {fa['recovery_mapping_alone']:.1%} | "
              f"insertion alone {fa['recovery_insertion_alone']:.1%} | "
              f"overlap {fa['overlap']:+.1%}")
        print(f"    reading        {fa['reading']}")


def _decide(report):
    """Prereg §4: >=2/3 resolvable sequences must agree. pt1 is descriptive-only."""
    judgable = [(s, r) for s, r in report.items()
                if not r.get("status") and r["resolvable"]
                and r.get("share_insertion") is not None and not r["descriptive_only"]]
    if not judgable:
        return {"label": "NO VERDICT",
                "why": "no judgable sequence has both controls and the tracking_only arm"}

    above = [s for s, r in judgable if r["above_readable_floor"]]
    below = [s for s, r in judgable if not r["above_readable_floor"]]
    shares = {s: r["share_insertion"] for s, r in judgable}

    # The prereg requires agreement across >=2 judgable sequences. A single sequence is
    # a screening read, never a verdict (hard discipline (5): single-seed/single-sequence
    # does not issue a verdict) -- report it as incomplete rather than let n=1 pass.
    if len(judgable) < 2:
        return {"label": "INCOMPLETE (screening only)",
                "why": (f"only {len(judgable)} judgable sequence has the tracking_only arm "
                        f"({shares}); the prereg requires >=2 to agree before a verdict"),
                "judgable": [s for s, _ in judgable], "shares": shares}

    if len(above) == len(judgable):
        label = "INSERTION-CHANNEL-MATERIAL"
        why = (f"share_insertion clears the per-sequence readable floor on all "
               f"{len(judgable)} judgable sequences: {shares}")
    elif len(below) == len(judgable):
        label = "INSERTION-CHANNEL-NEGLIGIBLE"
        why = (f"share_insertion sits at or below the readable floor on every judgable "
               f"sequence ({shares}) => the 20-56% gap is NOT in insertion; it can only be "
               f"in the tracking side. Next target = tracking-side isolation.")
    else:
        label = "INDETERMINATE"
        why = f"sequences disagree: above floor {above}, below floor {below} ({shares})"
    return {"label": label, "why": why, "judgable": [s for s, _ in judgable],
            "shares": shares}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pba", default="results/runs/PBA")
    ap.add_argument("--controls", default="results/runs/T2/T2-QUOTA-3090")
    ap.add_argument("--out", default="results/evidence/insertion_verdict.json")
    args = ap.parse_args()
    blob = verdict(args.pba, args.controls)
    v = blob["verdict"]
    print(f"\nVERDICT: {v['label']}  --  {v['why']}")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(blob, fh, indent=2)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
