"""Does the pt1/pt2 'RPE > 2.5 cm/frame => the mask becomes necessary' rule generalise?

The paper skeleton derives a stratification threshold of ~2.5 cm/frame from exactly TWO
sequences -- pt2 (mask-free RPE 1.57, mask redundant) and pt1 (2.89, mask necessary) --
and defends it as "not arbitrary, it comes from a controlled pair". But a threshold placed
between the only two points that define it is fitted, not tested: with n=2 every value in
(1.57, 2.89) separates them equally well. This script tests the rule on all 18 sequences,
whose RPE and ATE are already on disk, so the claim is either confirmed out-of-sample or
retracted before a reviewer does it for us.

Rule under test, as a falsifiable prediction:
    mask-free RPE >  2.5 cm/frame  =>  mask NECESSARY
    mask-free RPE <= 2.5 cm/frame  =>  mask REDUNDANT
with necessity read from the two arms we already have,
    N = ATE(mask-free) / ATE(combined),
    N >= 1.5 -> necessary,  N <= 1.2 -> redundant,  else ambiguous (excluded, not forced).

Provenance: seeds are discovered and each cell's ATE is read through the main-table
builder's OWN functions (discover / read_ate), so this check cannot diverge from the
table's latest-run-per-cell rule. RPE is read from the same per-run CSV that read_ate
prefers, by the same authoritative order.
"""
import csv
import os
import statistics
import sys

# The table builder uses repo-root-relative paths, so run from the repo root and put
# scripts/ on the path rather than the other way round.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(_ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import build_18seq_main_table as B  # noqa: E402

THRESH_RPE = 2.5
NEC_HI, NEC_LO = 1.5, 1.2


def read_rpe(tsd):
    """RPE of the ONE run `tsd`, by read_ate's authoritative order (per-run CSV first)."""
    stamp = os.path.basename(tsd.rstrip(os.sep))
    rows = []
    per_run = os.path.join(tsd, "tracking_raw.csv")
    try:
        if os.path.isfile(per_run):
            with open(per_run, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        else:
            parts = tsd.split(os.sep)
            runroot = os.sep.join(parts[:-4])
            csvp = os.path.join(runroot, "tables", "tracking_raw.csv")
            if not os.path.isfile(csvp):
                return None
            with open(csvp, encoding="utf-8") as fh:
                allrows = list(csv.DictReader(fh))
            rows = [r for r in allrows
                    if (r.get("run_id") or "").strip() == stamp] or allrows[-1:]
        vals = [float(r["rpe_trans_rmse_cm"]) for r in rows
                if (r.get("rpe_trans_rmse_cm") or "").strip()]
        return vals[-1] if vals else None
    except Exception:
        return None


def cell(tsds):
    ates, rpes = [], []
    for _seed, tsd in tsds.items():
        a = B.read_ate(tsd)
        if a:
            ates.append(a[0])
        r = read_rpe(tsd)
        if r is not None:
            rpes.append(r)
    return ates, rpes


def main():
    disc = B.discover()
    print(f"{'seq':12s} {'mf RPE':>8s} {'mf ATE':>8s} {'comb ATE':>9s} {'N':>6s} "
          f"{'predicted':>10s} {'observed':>10s}  verdict")
    print("-" * 82)

    agree = disagree = ambiguous = 0
    rows = []
    for seq in B.SEQORDER:
        d = disc.get(seq, {})
        mf, mo = d.get("maskfree"), d.get("maskon")
        if not mf or not mo:
            print(f"{seq:12s}  (arm missing, skipped)")
            continue
        a_mf, r_mf = cell(mf)
        a_mo, _ = cell(mo)
        if not a_mf or not a_mo or not r_mf:
            print(f"{seq:12s}  (no usable rows, skipped)")
            continue
        rpe = statistics.mean(r_mf)
        ate_mf, ate_mo = statistics.mean(a_mf), statistics.mean(a_mo)
        n = ate_mf / ate_mo if ate_mo else float("nan")

        predicted = "necessary" if rpe > THRESH_RPE else "redundant"
        observed = ("necessary" if n >= NEC_HI else
                    "redundant" if n <= NEC_LO else "ambiguous")
        if observed == "ambiguous":
            verdict = "- (in band)"
            ambiguous += 1
        elif observed == predicted:
            verdict = "AGREE"
            agree += 1
        else:
            verdict = "**DISAGREE**"
            disagree += 1

        rows.append((seq, rpe, ate_mf, ate_mo, n, predicted, observed))
        print(f"{seq:12s} {rpe:8.3f} {ate_mf:8.2f} {ate_mo:9.2f} {n:6.2f} "
              f"{predicted:>10s} {observed:>10s}  {verdict}")

    print("-" * 82)
    decided = agree + disagree
    print(f"decided {decided}   AGREE {agree}   DISAGREE {disagree}   "
          f"ambiguous(excluded) {ambiguous}")
    if decided:
        print(f"rule accuracy on decided cells: {agree}/{decided} = {agree / decided:.0%}")

    nec = sorted((r[1], r[0]) for r in rows if r[6] == "necessary")
    red = sorted((r[1], r[0]) for r in rows if r[6] == "redundant")
    print()
    print("mask-NECESSARY, by mask-free RPE:", [f"{s} {v:.2f}" for v, s in nec])
    print("mask-REDUNDANT, by mask-free RPE:", [f"{s} {v:.2f}" for v, s in red])
    best = None
    if nec and red:
        separable = nec[0][0] > red[-1][0]
        print(f"  necessary range [{nec[0][0]:.2f}, {nec[-1][0]:.2f}]   "
              f"redundant range [{red[0][0]:.2f}, {red[-1][0]:.2f}]")
        print(f"  SEPARABLE BY ANY SINGLE RPE THRESHOLD: {separable}")
        if separable:
            best = (red[-1][0] + nec[0][0]) / 2
            print(f"  => a threshold anywhere in ({red[-1][0]:.2f}, {nec[0][0]:.2f}) "
                  f"separates all decided cells; midpoint {best:.2f} cm/frame.")
            print(f"  => the skeleton's {THRESH_RPE} cm/frame is ABOVE that interval, "
                  f"which is why it misclassifies "
                  f"{[s for v, s in nec if v <= THRESH_RPE]}.")
            print("  ⚠ FITTED, NOT VALIDATED: the interval is read off the same 18 "
                  "sequences that define it. No held-out sequence tests it, and "
                  "computing mask-free RPE requires RUNNING the mask-free arm, so this "
                  "is a post-hoc diagnostic, not a deployable a-priori selector.")

    # also report what the excluded ambiguous cells would have done, so the exclusion
    # can never be suspected of propping the rule up
    # also report the excluded ambiguous cells and what they WOULD have given, so the
    # exclusion can never be suspected of propping the rule up
    amb = [r for r in rows if r[6] == "ambiguous"]
    if amb:
        print()
        print("ambiguous cells (excluded by the pre-stated band) and what they'd give:")
        for seq, rpe, a_mf, a_mo, n, pred, _obs in amb:
            side = "redundant" if n < (NEC_LO + NEC_HI) / 2 else "necessary"
            note = "would AGREE" if side == pred else "would DISAGREE"
            print(f"  {seq:12s} RPE {rpe:.2f}  N {n:.2f}  nearer '{side}'  "
                  f"vs predicted '{pred}'  => {note}")

    out = os.path.join("results", "evidence", "rpe_stratification_rule_test.json")
    payload = {
        "rule_under_test": f"mask-free RPE > {THRESH_RPE} cm/frame => mask necessary",
        "necessity_definition": {"N": "ATE(mask-free)/ATE(combined)",
                                 "necessary": f"N >= {NEC_HI}",
                                 "redundant": f"N <= {NEC_LO}",
                                 "ambiguous": f"{NEC_LO} < N < {NEC_HI} (excluded)"},
        "counts": {"decided": decided, "agree": agree, "disagree": disagree,
                   "ambiguous_excluded": ambiguous},
        "separating_interval": ([red[-1][0], nec[0][0]] if (nec and red and
                                                            nec[0][0] > red[-1][0])
                                else None),
        "midpoint_threshold": best,
        "rows": [{"seq": r[0], "rpe_maskfree": round(r[1], 3),
                  "ate_maskfree": round(r[2], 2), "ate_combined": round(r[3], 2),
                  "N": round(r[4], 2), "predicted": r[5], "observed": r[6]}
                 for r in rows],
        "scope": ("Threshold is FITTED to these 18 sequences; no held-out set. "
                  "mask-free RPE requires running the mask-free arm => diagnostic, "
                  "not an a-priori selector. n=3 seeds per cell, descriptive only."),
    }
    import json
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
