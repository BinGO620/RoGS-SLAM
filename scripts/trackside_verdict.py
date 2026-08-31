#!/usr/bin/env python3
"""Trackside-channel verdict (exp36): splits exp34's unexplained residual in two.

Pre-registration: results/evidence/trackside_channel_prereg.md (committed before run 1).
Channel inventory (why this cell exists): results/evidence/semantic_mask_channel_inventory.md

    arm                       SemanticMask                       role
    A eboth                   enabled, map=T,  ins=T             control (best)
    C pba_mapping_off         enabled, map=F,  ins=T             exp34 intervention
    D control_maskfree        enabled=False (kills 4 channels)    control (worst)
    E pba_trackside_only      enabled, map=F,  ins=F             <- exp36

The residual exp34/35 could not attribute, R = 1 - share_BA - share_insertion, splits
EXACTLY (algebraic identity, not an approximation):

    (D - E)/(D - A)   +   (E - C)/(D - A)   =   (D - C)/(D - A)  =  R
    recovery_trackside    share_ins_mapoff

so ONE reading of E answers both. H-inert (exp35's "the residual is channel overlap")
predicts E ~ D; H-material (this script's predecessor's own verdict text, "it can only be
in the tracking side") predicts E ~ C. The two point predictions are printed next to the
measurement so the prereg can be falsified rather than reinterpreted.

Floors are DUAL-ARM aware, which is a correction the prereg registers: exp34/35 sized the
readable floor from the two CONTROL arms only, while the treatment arm without
``mask_mapping`` is strongly bistable (pba_mapping_off f3_wk_xyz seeds: 6.56/9.95/23.73,
ptp 17.16 = 71% of that sequence's total effect). A floor built from control spread alone
understates the noise on the very quantity being read.

Usage:
  python scripts/trackside_verdict.py --pba results/runs/PBA \
      --controls results/runs/T2/T2-QUOTA-3090
"""

import argparse
import glob
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from scripts.pba_verdict import RESOLVE_RATIO, _ate  # noqa: E402


def _ate_all_repeats(run_dir):
    """Every row in ``tables/tracking_raw.csv``, not just the first.

    PROVENANCE (found in exp36, applies retroactively to exp34/35): four balloon run dirs
    hold TWO rows -- the same config+seed run twice -- and ``_ate`` (inherited) returns
    ``rows[0]``, i.e. the earlier repeat. The judged arm ``pba_mapping_off_balloon`` is
    among them: seed1 = 8.545 / 7.732, seed2 = 8.031 / 7.551 (6-10% apart, which is
    ordinary run-to-run nondeterminism for this backbone -- exp26 measured 2.99 vs 33.70
    at one point). So share_BA on balloon depends on an unstated repeat choice
    (0.672 with rows[0], 0.624 averaging repeats). This function exists so the choice is
    reported as a sensitivity instead of hidden in a helper.
    """
    import csv
    path = os.path.join(run_dir, "tables", "tracking_raw.csv")
    if not os.path.isfile(path):
        return []
    out = []
    for row in csv.DictReader(open(path)):
        v = row.get("ate_rmse_cm")
        if v:
            try:
                out.append(float(v))
            except ValueError:
                pass
    return out


SEQUENCES = ("balloon", "f3_wk_xyz", "pt1")
DESCRIPTIVE_ONLY = ("pt1",)           # carried forward verbatim from exp34/35
PAIRED_DIRECTION_MIN = 5              # prereg §5: >=5/6 paired seeds must agree
SEEDS = (0, 1, 2)


def _by_seed(root_a, root_b, pattern, all_repeats=False):
    """{seed: ate} for the first root that has the arm.

    ``all_repeats=False`` reproduces exp34/35 byte-for-byte (first CSV row).
    ``all_repeats=True`` averages every repeat of that seed -- the sensitivity read.
    """
    out = {}
    for seed in SEEDS:
        for root in (root_a, root_b):
            hits = sorted(glob.glob(os.path.join(root, pattern.format(seed=seed))))
            for d in hits:
                if all_repeats:
                    vals = _ate_all_repeats(d)
                    if vals:
                        out[seed] = float(np.mean(vals))
                        break
                else:
                    a = _ate(d)
                    if a is not None:
                        out[seed] = a
                        break
            if seed in out:
                break
    return out


def _arms(seq, pba_root, ctl_root, all_repeats=False):
    kw = {"all_repeats": all_repeats}
    return {
        "A_eboth": _by_seed(ctl_root, pba_root, f"eboth_{seq}_seed{{seed}}", **kw),
        "C_mapoff": _by_seed(pba_root, ctl_root, f"pba_mapping_off_{seq}*seed{{seed}}", **kw),
        "D_maskfree": _by_seed(ctl_root, pba_root, f"control_maskfree_{seq}_seed{{seed}}", **kw),
        "E_trackside": _by_seed(pba_root, ctl_root, f"pba_trackside_only_{seq}_seed{{seed}}", **kw),
    }


def _stats(d):
    v = np.array([d[s] for s in sorted(d)], dtype=float)
    return (float(v.mean()), float(v.ptp()), v.size) if v.size else (None, None, 0)


def verdict(pba_root, ctl_root):
    report = {}
    for seq in SEQUENCES:
        arms = _arms(seq, pba_root, ctl_root)
        st = {k: _stats(v) for k, v in arms.items()}
        row = {
            "descriptive_only": seq in DESCRIPTIVE_ONLY,
            "n": {k: st[k][2] for k in st},
            "ate": {k: (round(st[k][0], 3) if st[k][0] is not None else None) for k in st},
            "ptp": {k: (round(st[k][1], 3) if st[k][1] is not None else None) for k in st},
            "per_seed": {k: {s: round(v, 3) for s, v in sorted(arms[k].items())} for k in arms},
        }
        a, d = st["A_eboth"][0], st["D_maskfree"][0]
        c, e = st["C_mapoff"][0], st["E_trackside"][0]
        if None in (a, d):
            row["status"] = "NO CONTROLS"
            report[seq] = row
            continue

        total = d - a
        ctl_spread = max(st["A_eboth"][1], st["D_maskfree"][1])
        row["total_effect_cm"] = round(total, 3)
        row["control_spread_cm"] = round(ctl_spread, 3)
        row["resolve_ratio"] = round(total / ctl_spread, 2) if ctl_spread > 0 else float("inf")
        row["resolvable"] = bool(total >= RESOLVE_RATIO * ctl_spread)

        if c is not None:
            row["residual_R"] = round((d - c) / total, 3)          # = 1 - share_BA - share_ins
            row["predict_H_inert_E"] = round(d, 3)                 # trackside buys nothing
            row["predict_H_material_E"] = round(c, 3)              # trackside buys the residual
            row["prediction_gap_cm"] = round(d - c, 3)

        if e is None:
            row["status"] = "E ARM MISSING"
            report[seq] = row
            continue

        # ---- primary estimand + dual-arm-aware floor (prereg §3 correction, §5) --------
        f_trk = max(st["D_maskfree"][1], st["E_trackside"][1]) / total if total else float("inf")
        row["recovery_trackside"] = round((d - e) / total, 3)
        row["floor_trackside"] = round(f_trk, 3)
        row["trackside_above_floor"] = bool(abs(row["recovery_trackside"]) > f_trk)
        if c is not None:
            f_ins = max(st["C_mapoff"][1], st["E_trackside"][1]) / total
            row["share_ins_mapoff"] = round((e - c) / total, 3)
            row["floor_ins_mapoff"] = round(f_ins, 3)
            row["ins_mapoff_above_floor"] = bool(abs(row["share_ins_mapoff"]) > f_ins)
            # arithmetic self-check: the two halves must sum to the residual
            row["partition_check"] = round(
                row["recovery_trackside"] + row["share_ins_mapoff"] - row["residual_R"], 4)
            # prereg §5: E's own spread must not eat the gap between the two predictions
            gap = abs(d - c)
            row["E_spread_vs_gap"] = round(st["E_trackside"][1] / gap, 2) if gap else None
            row["E_spread_swamps_gap"] = bool(gap and st["E_trackside"][1] > 0.5 * gap)

        # ---- paired per-seed direction (bistability-robust, prereg §3/§5) -------------
        shared = sorted(set(arms["E_trackside"]) & set(arms["D_maskfree"]))
        signs = [arms["E_trackside"][s] - arms["D_maskfree"][s] for s in shared]
        row["paired_vs_maskfree"] = {
            "seeds": shared,
            "delta_cm": [round(x, 3) for x in signs],
            "n_better": int(sum(1 for x in signs if x < 0)),
            "n": len(signs),
        }
        shared_c = sorted(set(arms["E_trackside"]) & set(arms["C_mapoff"]))
        row["paired_vs_mapoff"] = {
            "seeds": shared_c,
            "delta_cm": [round(arms["E_trackside"][s] - arms["C_mapoff"][s], 3) for s in shared_c],
        }

        # ---- repeat-selection sensitivity (see _ate_all_repeats docstring) -------------
        alt = _arms(seq, pba_root, ctl_root, all_repeats=True)
        sa = {k: _stats(v) for k, v in alt.items()}
        if all(sa[k][0] is not None for k in ("A_eboth", "D_maskfree", "E_trackside")):
            ta = sa["D_maskfree"][0] - sa["A_eboth"][0]
            row["sensitivity_repeats_averaged"] = {
                "ate": {k: round(sa[k][0], 3) for k in sa if sa[k][0] is not None},
                "recovery_trackside": round((sa["D_maskfree"][0] - sa["E_trackside"][0]) / ta, 3)
                if ta else None,
                "residual_R": (round((sa["D_maskfree"][0] - sa["C_mapoff"][0]) / ta, 3)
                               if sa["C_mapoff"][0] is not None and ta else None),
            }
        report[seq] = row

    _print(report)
    return {"verdict": _decide(report), "sequences": report}


def _print(report):
    print("ATE by arm (cm; mean over available seeds)\n")
    hdr = (f"{'sequence':11s} {'A eboth':>8s} {'C mapoff':>9s} {'E trkside':>10s} "
           f"{'D maskfree':>11s} | {'total':>7s} {'R resid':>8s} | "
           f"{'rec_trk':>8s} {'floor':>6s} {'ins@off':>8s} {'floor':>6s}")
    print(hdr + "\n" + "-" * len(hdr))
    for seq, r in report.items():
        a = r["ate"]

        def _f(x, w):
            return f"{x:{w}.2f}" if x is not None else f"{'--':>{w}s}"
        tag = " (descriptive)" if r["descriptive_only"] else ""
        if r.get("status") == "NO CONTROLS":
            print(f"{seq:11s} NO CONTROLS")
            continue
        print(f"{seq:11s} {_f(a['A_eboth'],8)} {_f(a['C_mapoff'],9)} {_f(a['E_trackside'],10)} "
              f"{_f(a['D_maskfree'],11)} | {r['total_effect_cm']:7.2f} "
              f"{r.get('residual_R', float('nan')):8.3f} | "
              f"{_f(r.get('recovery_trackside'),8)} {_f(r.get('floor_trackside'),6)} "
              f"{_f(r.get('share_ins_mapoff'),8)} {_f(r.get('floor_ins_mapoff'),6)}{tag}")

    print("\nrec_trk = (D-E)/(D-A): what the tracking side buys ALONE.")
    print("ins@off = (E-C)/(D-A): what insertion buys in the mapping-OFF regime.")
    print("The two sum to R by construction; floors are max(ptp of the two compared arms)/total.")

    print("\npoint predictions vs measurement (prereg §4, written before the run):")
    for seq, r in report.items():
        if r.get("predict_H_inert_E") is None or r["ate"].get("E_trackside") is None:
            continue
        print(f"  {seq:11s} H-inert E~{r['predict_H_inert_E']:6.2f} | "
              f"H-material E~{r['predict_H_material_E']:6.2f} | "
              f"measured E = {r['ate']['E_trackside']:6.2f} "
              f"(E ptp {r['ptp']['E_trackside']:.2f} = {r.get('E_spread_vs_gap')}x the gap)")

    print("\npaired per-seed (bistability-robust; means are unreliable on the map-OFF arms):")
    for seq, r in report.items():
        p = r.get("paired_vs_maskfree")
        if not p:
            continue
        print(f"  {seq:11s} E-D per seed {p['delta_cm']} -> {p['n_better']}/{p['n']} better than maskfree")
        q = r.get("paired_vs_mapoff")
        if q:
            print(f"  {'':11s} E-C per seed {q['delta_cm']} (insertion's effect with mapping off)")

    checks = [r.get("partition_check") for r in report.values() if r.get("partition_check") is not None]
    if checks:
        worst = max(abs(x) for x in checks)
        print(f"\npartition identity residual (must be ~0, float tolerance): max |err| = {worst:.4f}")


def _decide(report):
    judgable = [(s, r) for s, r in report.items()
                if not r.get("status") and r.get("resolvable")
                and r.get("recovery_trackside") is not None and not r["descriptive_only"]]
    if len(judgable) < 2:
        return {"label": "INCOMPLETE (screening only)",
                "why": (f"{len(judgable)} judgable sequence(s) have the E arm; the prereg "
                        f"requires >=2 (hard discipline: one sequence never issues a verdict)"),
                "judgable": [s for s, _ in judgable]}

    swamped = [s for s, r in judgable if r.get("E_spread_swamps_gap")]
    above = [s for s, r in judgable if r["trackside_above_floor"]]
    below = [s for s, r in judgable if not r["trackside_above_floor"]]
    rec = {s: r["recovery_trackside"] for s, r in judgable}
    paired = sum(r["paired_vs_maskfree"]["n_better"] for _s, r in judgable)
    paired_n = sum(r["paired_vs_maskfree"]["n"] for _s, r in judgable)

    if swamped:
        return {"label": "INDETERMINATE",
                "why": (f"E's own seed spread exceeds half the gap between the two point "
                        f"predictions on {swamped} -> the arm cannot separate them at n=3 "
                        f"(prereg §5 stopping rule)"), "recovery": rec}
    if len(above) == len(judgable) and paired >= PAIRED_DIRECTION_MIN:
        return {"label": "TRACKSIDE-MATERIAL",
                "why": (f"recovery_trackside clears the dual-arm floor on all {len(judgable)} "
                        f"judgable sequences {rec} and {paired}/{paired_n} paired seeds beat "
                        f"maskfree => the residual is a third channel, not channel overlap; "
                        f"exp35's mechanism half ('insertion is the only defence with mapping "
                        f"off') is refuted by the partition"),
                "recovery": rec, "paired": f"{paired}/{paired_n}"}
    if len(below) == len(judgable):
        return {"label": "TRACKSIDE-NEGLIGIBLE",
                "why": (f"recovery_trackside sits at or below the dual-arm floor on every "
                        f"judgable sequence {rec} => the tracking-side mask buys nothing alone; "
                        f"by the partition identity the residual is insertion's effect in the "
                        f"mapping-OFF regime, which confirms exp35's mechanism reading "
                        f"interventionally"),
                "recovery": rec, "paired": f"{paired}/{paired_n}"}
    return {"label": "INDETERMINATE",
            "why": (f"sequences disagree: above floor {above}, below floor {below} ({rec}); "
                    f"paired direction {paired}/{paired_n}"), "recovery": rec}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pba", default="results/runs/PBA")
    ap.add_argument("--controls", default="results/runs/T2/T2-QUOTA-3090")
    ap.add_argument("--out", default="results/evidence/trackside_verdict.json")
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
