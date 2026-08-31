#!/usr/bin/env python3
"""PBA verdict: which channel carries the mask benefit -- BA/mapping, or the rest?

Ablation logic (this is the corrected reading; see the note below):

    eboth     mask_mapping=ON , mask_insertion=ON    -> best ATE
    PBA       mask_mapping=OFF, mask_insertion=ON    -> the intervention
    maskfree  no mask at all                         -> worst ATE

    share_BA = (ATE_PBA - ATE_eboth) / (ATE_maskfree - ATE_eboth)

``share_BA -> 1``: removing the BA-side mask alone loses the whole benefit, i.e. the BA
channel carries it. ``share_BA -> 0``: the benefit survives without the BA-side mask, i.e.
it is carried elsewhere (insertion / tracking). This is ordinary ablation logic --
degradation on removal is evidence that the removed component was carrying the effect.

  !! CORRECTION. ``results/evidence/pba_ba_coupling_prereg.md`` §"判决规则" attached the
  branch labels the wrong way round (it read "ATE stays low" as supporting the BA
  hypothesis, when a surviving ATE means the BA channel was NOT needed). The measured
  quantities and the thresholds are unaffected; only the label mapping was inverted, and
  it is corrected here. The thresholds below are the prereg's, re-expressed on the
  normalized share so they transfer across sequences.

Resolvability gate, computed BEFORE reading the treatment arm (criterion 8: condition the
reachable domain on the experiment's actual scale): a sequence can only decompose the
benefit if the total effect clears the within-arm seed spread by RESOLVE_RATIO.

Usage:
  python scripts/pba_verdict.py --pba results/runs/PBA --controls results/runs/T2/T2-QUOTA-3090
"""

import argparse
import csv
import glob
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

RESOLVE_RATIO = 3.0      # total effect must be >= 3x the within-arm spread
SHARE_MOSTLY_BA = 0.60   # share_BA >= this -> the BA channel carries most of it
SHARE_MOSTLY_OTHER = 0.20


def _ate(run_dir):
    path = os.path.join(run_dir, "tables", "tracking_raw.csv")
    if not os.path.isfile(path):
        return None
    rows = list(csv.DictReader(open(path)))
    if not rows or not rows[0].get("ate_rmse_cm"):
        return None
    return float(rows[0]["ate_rmse_cm"])


def _opacity(run_dir):
    plies = glob.glob(os.path.join(run_dir, "**", "final", "point_cloud.ply"), recursive=True)
    if not plies:
        return None
    from scripts.map_profile import profile          # noqa: E402
    return float(profile(plies[0])["opacity"]["mean"])


def _collect(root, pattern):
    out = []
    for d in sorted(glob.glob(os.path.join(root, pattern))):
        a = _ate(d)
        if a is not None:
            out.append((os.path.basename(d), a))
    return out


def verdict(pba_root, ctl_root, sequences=("balloon", "mv_no_box")):
    report = {}
    for seq in sequences:
        arms = {
            "eboth": _collect(ctl_root, f"eboth_{seq}_seed*"),
            "maskfree": _collect(ctl_root, f"control_maskfree_{seq}_seed*"),
            "pba": _collect(pba_root, f"pba_mapping_off_{seq}*seed*"),
        }
        vals = {k: np.array([v for _n, v in a], dtype=float) for k, a in arms.items()}
        if vals["eboth"].size == 0 or vals["maskfree"].size == 0:
            report[seq] = {"status": "NO CONTROLS"}
            continue

        e, f = float(vals["eboth"].mean()), float(vals["maskfree"].mean())
        total = f - e
        spread = max(float(vals["eboth"].ptp()), float(vals["maskfree"].ptp()))
        resolvable = total >= RESOLVE_RATIO * spread

        row = {
            "n": {k: int(v.size) for k, v in vals.items()},
            "ate": {k: (None if v.size == 0 else round(float(v.mean()), 3))
                    for k, v in vals.items()},
            "per_seed": {k: [round(x, 3) for x in v.tolist()] for k, v in vals.items()},
            "total_effect_cm": round(total, 3),
            "within_arm_spread_cm": round(spread, 3),
            "resolve_ratio": round(total / spread, 2) if spread > 0 else float("inf"),
            "resolvable": bool(resolvable),
        }
        if vals["pba"].size:
            p = float(vals["pba"].mean())
            row["share_BA"] = round((p - e) / total, 3) if abs(total) > 1e-9 else None
        report[seq] = row

    # ---- print ----
    hdr = (f"{'sequence':12s} {'eboth':>7s} {'PBA':>7s} {'maskfree':>9s} | {'total':>7s} "
           f"{'spread':>7s} {'ratio':>6s} {'resolv':>7s} | {'share_BA':>8s}")
    print(hdr + "\n" + "-" * len(hdr))
    for seq, r in report.items():
        if r.get("status"):
            print(f"{seq:12s} {r['status']}")
            continue
        a = r["ate"]
        pba = f"{a['pba']:7.2f}" if a["pba"] is not None else f"{'--':>7s}"
        sh = r.get("share_BA")
        print(f"{seq:12s} {a['eboth']:7.2f} {pba} {a['maskfree']:9.2f} | "
              f"{r['total_effect_cm']:7.2f} {r['within_arm_spread_cm']:7.2f} "
              f"{r['resolve_ratio']:6.2f} {str(r['resolvable']):>7s} | "
              + (f"{sh:8.3f}" if sh is not None else f"{'--':>8s}"))
    print("\nshare_BA = (PBA - eboth)/(maskfree - eboth): the fraction of the mask benefit "
          "that the\n  BA/mapping channel carries. 1 = all of it, 0 = none of it.")
    print(f"resolvable = total effect >= {RESOLVE_RATIO}x the within-arm seed spread "
          "(computed before\n  reading the treatment arm; an unresolvable sequence cannot "
          "decompose anything).")

    usable = [(s, r) for s, r in report.items()
              if not r.get("status") and r["resolvable"] and r.get("share_BA") is not None]
    if not usable:
        v, why = "NO VERDICT", "no sequence both resolvable and complete"
    else:
        shares = [r["share_BA"] for _s, r in usable]
        if all(s >= SHARE_MOSTLY_BA for s in shares):
            v = "BA-CHANNEL-DOMINANT"
            why = (f"removing only the BA-side mask costs {min(shares):.0%}-{max(shares):.0%} "
                   f"of the whole mask benefit on {len(usable)} resolvable sequence(s)")
        elif all(s <= SHARE_MOSTLY_OTHER for s in shares):
            v = "BA-CHANNEL-MINOR"
            why = f"the benefit survives without the BA-side mask (share {shares})"
        else:
            v = "PARTIAL"
            why = (f"share_BA = {shares} -- the BA channel carries part of it, the rest "
                   f"sits in insertion/tracking")
    print(f"\nVERDICT: {v}  --  {why}")
    blob = {"verdict": v, "why": why, "sequences": report}
    return blob


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pba", default="results/runs/PBA")
    ap.add_argument("--controls", default="results/runs/T2/T2-QUOTA-3090")
    ap.add_argument("--out", default="results/evidence/pba_verdict.json")
    args = ap.parse_args()
    blob = verdict(args.pba, args.controls)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(blob, fh, indent=2)


if __name__ == "__main__":
    main()
