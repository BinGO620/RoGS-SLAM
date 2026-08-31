#!/usr/bin/env python3
"""Rendering-side readout of the BA-channel intervention (exp35 Task 2).

Question. exp34's PBA verdict located 44-80% of the *ATE* gain in the BA-side mask
(``mask_mapping``) and listed "this experiment only measures ATE, rendering untested"
as honest boundary #3. This closes that boundary using the SAME runs' final PLYs,
re-rendered offline (scripts/render_pba_3090.sh -> posthoc_fullframe).

Readout, mirroring the ATE share so the two are directly comparable:

    share_BA^metric = (M_PBA - M_eboth) / (M_maskfree - M_eboth)

-> 1 = the BA channel carries the whole rendering effect; -> 0 = it carries none.
Signed so that it is orientation-free: it is a ratio of the same difference direction,
so metrics where lower is better (LPIPS, depth-L1) need no sign flip.

Decomposability gate (inherited from exp34, judged per metric, NOT re-fitted):
the total effect |M_maskfree - M_eboth| must exceed 3x the within-arm seed range,
else that sequence/metric pair decomposes nothing and the share is not reported.

Usage:
  python scripts/pba_render_verdict.py [--json results/evidence/pba_rendering_metrics.json]
"""

import argparse
import json
from collections import defaultdict

METRICS = (
    # (key, label, lower_is_better)
    ("psnr", "PSNR", False),
    ("ssim", "SSIM", False),
    ("lpips", "LPIPS", True),
    ("depth_l1", "Depth-L1", True),
)
ARMS = ("eboth", "PBA", "maskfree")
DECOMP_MIN_RATIO = 3.0   # exp34 criterion (8): total effect >= 3x within-arm range


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _range(xs):
    xs = [x for x in xs if x is not None]
    return (max(xs) - min(xs)) if len(xs) > 1 else None


def load(path):
    cells = defaultdict(dict)          # seq -> arm -> list of per-seed dicts
    for r in json.load(open(path)):
        cells[r["seq"]].setdefault(r["arm"], []).append(r)
    return cells


def analyse(cells):
    out = {}
    for seq in sorted(cells):
        arms = cells[seq]
        if not all(a in arms for a in ARMS):
            out[seq] = {"status": "incomplete",
                        "have": sorted(arms), "missing": [a for a in ARMS if a not in arms]}
            continue
        per_metric = {}
        for key, label, lower_better in METRICS:
            vals = {a: [r[key] for r in arms[a]] for a in ARMS}
            m = {a: _mean(vals[a]) for a in ARMS}
            if any(m[a] is None for a in ARMS):
                per_metric[label] = {"status": "no-data"}
                continue
            total = m["maskfree"] - m["eboth"]
            # widest within-arm seed range across the three arms = the noise this
            # decomposition has to beat (same construction as the ATE gate)
            ranges = [r for r in (_range(vals[a]) for a in ARMS) if r is not None]
            worst_range = max(ranges) if ranges else None
            ratio = (abs(total) / worst_range) if worst_range else float("inf")
            entry = {
                "eboth": round(m["eboth"], 4),
                "PBA": round(m["PBA"], 4),
                "maskfree": round(m["maskfree"], 4),
                "total_effect": round(total, 4),
                "worst_within_arm_range": round(worst_range, 4) if worst_range else None,
                "decomp_ratio": round(ratio, 2),
                "decomposable": ratio >= DECOMP_MIN_RATIO,
                "lower_is_better": lower_better,
                # does the mask help this metric at all? (eboth better than maskfree)
                "mask_helps": (m["eboth"] < m["maskfree"]) if lower_better else (m["eboth"] > m["maskfree"]),
                "monotone_eboth_PBA_maskfree": (
                    m["eboth"] < m["PBA"] < m["maskfree"] if lower_better
                    else m["eboth"] > m["PBA"] > m["maskfree"]
                ),
            }
            entry["share_BA"] = (round((m["PBA"] - m["eboth"]) / total, 3)
                                 if entry["decomposable"] and total != 0 else None)
            entry["readable_floor"] = round(1.0 / ratio, 3) if ratio not in (0, float("inf")) else 0.0

            # ---- per-seed paired readout ------------------------------------------
            # The mean-vs-range gate above compares a mean difference against a spread,
            # so it does NOT become passable by adding seeds -- it is a statement about
            # per-run spread, not about the precision of the mean. When it fails we can
            # still ask the weaker, threshold-free question the project uses elsewhere
            # ("逐 seed 同号"): holding the seed fixed, does the intervention move the
            # metric the same direction every time? Arms share seed values, so this is
            # the same pairing WP-B / R2-P03 use for cross-arm comparison.
            by_seed = {a: {r["seed"]: r[key] for r in arms[a]} for a in ARMS}
            common = sorted(set(by_seed["eboth"]) & set(by_seed["PBA"]) & set(by_seed["maskfree"]))
            per_seed, signs = {}, []
            for s in common:
                e, p, f = by_seed["eboth"][s], by_seed["PBA"][s], by_seed["maskfree"][s]
                if None in (e, p, f) or (f - e) == 0:
                    continue
                sh = (p - e) / (f - e)
                per_seed[s] = round(sh, 3)
                # "mask ON is better than PBA" in this metric's own orientation
                signs.append((p - e) < 0 if lower_better else (p - e) > 0)
            entry["share_BA_per_seed"] = per_seed
            # sign convention: True = removing the BA mask degraded this metric
            n_degraded = sum(1 for s in signs if not s) if lower_better else sum(1 for s in signs if s)
            degraded = [(by_seed["PBA"][s] - by_seed["eboth"][s]) for s in per_seed]
            worse = [d > 0 if lower_better else d < 0 for d in degraded]
            entry["seeds_degraded_by_removing_BA_mask"] = f"{sum(worse)}/{len(worse)}"
            entry["per_seed_sign_consistent"] = len(worse) > 0 and (all(worse) or not any(worse))
            per_metric[label] = entry
        out[seq] = {"status": "complete", "metrics": per_metric}
    return out


def report(res):
    print("=" * 96)
    print("BA-channel intervention, rendering side (exp35 Task 2)")
    print("share_BA = (M_PBA - M_eboth) / (M_maskfree - M_eboth);  1 = BA carries all, 0 = none")
    print("=" * 96)

    monotone_tally = defaultdict(lambda: [0, 0])   # label -> [monotone, judged]
    for seq, blob in res.items():
        if blob["status"] != "complete":
            print(f"\n{seq}: INCOMPLETE -- have {blob['have']}, missing {blob['missing']}")
            continue
        print(f"\n{seq}")
        print(f"  {'metric':<10} {'eboth':>9} {'PBA':>9} {'maskfree':>9} "
              f"{'total':>8} {'range':>7} {'ratio':>7} {'dec':>4} {'share_BA':>9} {'mono':>5}")
        for label, e in blob["metrics"].items():
            if e.get("status") == "no-data":
                print(f"  {label:<10} (no data)")
                continue
            share = f"{e['share_BA']:.3f}" if e["share_BA"] is not None else "  --  "
            print(f"  {label:<10} {e['eboth']:>9.4f} {e['PBA']:>9.4f} {e['maskfree']:>9.4f} "
                  f"{e['total_effect']:>8.4f} {e['worst_within_arm_range']:>7.4f} "
                  f"{e['decomp_ratio']:>7.2f} {'Y' if e['decomposable'] else 'n':>4} "
                  f"{share:>9} {'Y' if e['monotone_eboth_PBA_maskfree'] else 'n':>5}"
                  f"   removing BA mask degraded {e['seeds_degraded_by_removing_BA_mask']} seeds"
                  f"  per-seed share {list(e['share_BA_per_seed'].values())}")
            monotone_tally[label][1] += 1
            if e["monotone_eboth_PBA_maskfree"]:
                monotone_tally[label][0] += 1

    print("\n" + "-" * 96)
    print("monotone ordering eboth > PBA > maskfree (mask helps, BA carries part of it):")
    for label, (mono, judged) in monotone_tally.items():
        print(f"  {label:<10} {mono}/{judged}")
    print("-" * 96)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", default="results/evidence/pba_rendering_metrics.json")
    ap.add_argument("--out", default="results/evidence/pba_render_verdict.json")
    a = ap.parse_args()
    res = analyse(load(a.json))
    report(res)
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=2)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
