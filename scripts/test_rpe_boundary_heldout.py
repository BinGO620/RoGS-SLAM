"""Out-of-sample test of the mask-free RPE stratification rule (preregistered, exp47).

Preregistration: results/evidence/rpe_boundary_heldout_prereg.md (committed BEFORE any
held-out run existed). Everything below is fixed by that document; this script only
implements it:

  §3  RPE(h)    = mean over 3 seeds of mask-free rpe_trans_rmse_cm  (cm/frame)
      N(h)      = mean(ATE_maskfree) / mean(ATE_combined)
      N >= 1.5 necessary, N <= 1.2 redundant, in between ambiguous (excluded)
      prediction at the LOCKED dev midpoint tau = 1.6445: RPE > tau => necessary
  §4  CONFIRMED  A = D and D >= 3
      PARTIAL    A/D >= 4/5 and all miss cells adjacent (near-boundary)
      REFUTED    A/D <= 3/5, or a REVERSE BIG MISS (RPE > tau and N <= 0.8)
      INCONCLUSIVE  D < 3
  §6  bistability abort: any arm with 3-seed range > 3x the median range across the
      5 sequences => that sequence is flagged bistable, reported separately, and does
      NOT enter the hit-rate numerator/denominator.

Provenance (§5): RPE/ATE are read by the same authoritative order as the dev round --
per-run CSV preferred, else the roll-up row whose run_id matches the timestamp dir,
else the LAST roll-up row (roll-up is append-only and chronological; the last row is
the latest run). Four cells were run twice (same seed, both OK -- see evidence .md);
the latest-run rule is the project-wide one and is applied uniformly, with the first
run's values also reported so the duplicate cannot hide anything.

Run from the repo root:
    python scripts/test_rpe_boundary_heldout.py
"""
import csv
import json
import os
import statistics
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(_ROOT)

RUNROOT = os.path.join("results", "runs", "RPE-BOUNDARY", "rpe-heldout")
TAU = 1.6445            # prereg §3, locked dev midpoint -- NOT refitted here
NEC_HI, NEC_LO = 1.5, 1.2
REVERSE_MISS_N = 0.8    # prereg §4: RPE > tau and N <= 0.8 => REFUTED outright
BISTABLE_X = 3.0        # prereg §6: seed range > 3x median range => bistable

# prereg §2, order as listed there. Run-dir names use the launcher's short names
# (long_office, not long_office_household); the underlying dataset is
# rgbd_dataset_freiburg3_long_office_household (config inherits configs/rgbd/tum/f3_office.yaml).
SEQS = [
    ("moving_obstructing_box", "obox"),
    ("moving_obstructing_box2", "obox2"),
    ("synchronous", "synchronous"),
    ("desk_with_person", "f2_desk_with_person"),
    ("long_office", "f3_long_office_household"),
]
SEEDS = ["0", "1", "2"]


def read_run(arm, seq, seed):
    """Return (ate, rpe, run_id, all_rows) for one cell, latest-run authoritative.

    all_rows carries EVERY completed row of the roll-up (incl. superseded reruns) so
    duplicate runs are visible in the evidence file, never silently averaged.
    """
    d = os.path.join(RUNROOT, f"rpeh_{arm}_{seq}_seed{seed}")
    per_run = os.path.join(d, "tables", "tracking_raw.csv")
    if not os.path.isfile(per_run):
        return None
    try:
        with open(per_run, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except Exception:
        return None
    if not rows:
        return None
    # roll-up is append-only and chronological (verified: run_ids ascending); the
    # authoritative value for a cell with >1 row is the LATEST run, same rule as the
    # main table's discover()/read_ate().
    latest = rows[-1]
    try:
        return (float(latest["ate_rmse_cm"]), float(latest["rpe_trans_rmse_cm"]),
                latest["run_id"], rows)
    except (KeyError, ValueError):
        return None


def classify(n):
    if n >= NEC_HI:
        return "necessary"
    if n <= NEC_LO:
        return "redundant"
    return "ambiguous"


def verdict_of(cells):
    """Prereg §4 four-branch verdict. cells = decided rows only (ambiguous/bistable
    excluded)."""
    d = len(cells)
    if d < 3:
        return "INCONCLUSIVE"
    agree = [c for c in cells if c["predicted"] == c["observed"]]
    a = len(agree)
    # reverse big miss: RPE > tau but N <= 0.8 (mask actively hurts 1.25x+)
    if any(c["rpe"] > TAU and c["n"] <= REVERSE_MISS_N for c in cells):
        return "REFUTED"
    if a == d:
        return "CONFIRMED"
    if a / d >= 4 / 5:
        miss = [c for c in cells if c["predicted"] != c["observed"]]
        # "adjacent" misses: miss near the tau boundary, i.e. RPE within +-25% of tau
        # (prereg §4 PARTIAL: "all miss cells adjacent (near the boundary)")
        if all(abs(c["rpe"] - TAU) <= 0.25 * TAU for c in miss):
            return "PARTIAL"
    return "REFUTED"


def main():
    rows, ranges = [], []
    print(f"{'seq':26s} {'mf RPE':>8s} {'mf ATE':>8s} {'cb ATE':>8s} {'N':>6s} "
          f"{'pred':>10s} {'obs':>10s}  verdict   seeds(ranges)")
    print("-" * 108)

    for seq, short in SEQS:
        cell_runs = {}
        ates_mf, rpes_mf, ates_cb = [], [], []
        for seed in SEEDS:
            mf = read_run("maskfree", seq, seed)
            cb = read_run("combined", seq, seed)
            if not mf or not cb:
                print(f"{short:26s}  (missing run, aborting -- prereg expects 30/30)")
                sys.exit(2)
            ates_mf.append(mf[0]); rpes_mf.append(mf[1]); ates_cb.append(cb[0])
            cell_runs[seed] = {"mf": mf, "cb": cb}
        rpe = statistics.mean(rpes_mf)
        ate_mf, ate_cb = statistics.mean(ates_mf), statistics.mean(ates_cb)
        n = ate_mf / ate_cb if ate_cb else float("nan")
        predicted = "necessary" if rpe > TAU else "redundant"
        observed = classify(n)
        rng = max(ates_mf) - min(ates_mf)
        rng_cb = max(ates_cb) - min(ates_cb)
        ranges.append((short, max(rng, rng_cb)))
        verdict = ("-" if observed == "ambiguous" else
                   ("AGREE" if observed == predicted else "**DISAGREE**"))
        rows.append({"seq": short, "rpe": rpe, "ate_mf": ate_mf, "ate_cb": ate_cb,
                     "n": n, "predicted": predicted, "observed": observed,
                     "range_mf": rng, "range_cb": rng_cb})
        print(f"{short:26s} {rpe:8.3f} {ate_mf:8.2f} {ate_cb:8.2f} {n:6.2f} "
              f"{predicted:>10s} {observed:>10s}  {verdict:9s} "
              f"mf {min(ates_mf):.1f}-{max(ates_mf):.1f} cb {min(ates_cb):.1f}-{max(ates_cb):.1f}")

    # §6 bistability abort: range > 3x median of the 5 sequence ranges
    med = statistics.median(r for _, r in ranges)
    bistable = {s for s, r in ranges if r > BISTABLE_X * med}
    decided = [r for r in rows if r["observed"] != "ambiguous" and r["seq"] not in bistable]
    verdict = verdict_of(decided)

    print("-" * 108)
    print(f"bistable median range {med:.2f} cm; flagged (> {BISTABLE_X}x): "
          f"{sorted(bistable) or 'none'}")
    amb = [r["seq"] for r in rows if r["observed"] == "ambiguous"]
    print(f"decided {len(decided)}  ambiguous(excluded) {len(amb)} {amb}")
    print(f"VERDICT (prereg §4): {verdict}")

    # duplicates must stay visible (provenance §5 note in evidence)
    dups = {}
    for seq, short in SEQS:
        for seed in SEEDS:
            for arm in ("maskfree", "combined"):
                run = read_run(arm, seq, seed)
                if run and len(run[3]) > 1:
                    dups[f"{short}/{arm}/seed{seed}"] = [
                        {"run_id": r["run_id"], "ate": r["ate_rmse_cm"],
                         "rpe": r["rpe_trans_rmse_cm"]} for r in run[3]]

    out = os.path.join("results", "evidence", "rpe_boundary_heldout.json")
    payload = {
        "rule_under_test": f"mask-free RPE > {TAU} cm/frame => mask necessary "
                           f"(dev midpoint, preregistered 2026-08-26 be5f6d3c)",
        "verdict": verdict,
        "counts": {"decided": len(decided),
                   "agree": sum(1 for r in decided if r["predicted"] == r["observed"]),
                   "ambiguous_excluded": len(amb),
                   "bistable_excluded": sorted(bistable)},
        "rows": [{"seq": r["seq"], "rpe_maskfree": round(r["rpe"], 3),
                  "ate_maskfree": round(r["ate_mf"], 2),
                  "ate_combined": round(r["ate_cb"], 2), "N": round(r["n"], 2),
                  "predicted": r["predicted"], "observed": r["observed"],
                  "ate_range_maskfree": round(r["range_mf"], 2),
                  "ate_range_combined": round(r["range_cb"], 2)} for r in rows],
        "duplicate_runs_latest_rule": dups,
        "scope": ("First out-of-sample test of a band fitted on the dev-18 set "
                  "(rpe_stratification_rule_test.json). tau locked at dev midpoint "
                  "before any held-out run existed. n=3 seeds per cell, descriptive. "
                  "mask-free RPE requires running the mask-free arm => post-hoc "
                  "diagnostic, not a deployable a-priori selector."),
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
