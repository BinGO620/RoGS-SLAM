#!/usr/bin/env python3
"""exp37 -- the ATE endpoint for the F arm: where does accumulated drift go when channel 1
is widened from 10/100 to 100/100 tracking iterations?

Pre-registration: results/evidence/pose_trackside_ate_prereg.md, committed at f9fa31ea BEFORE
this file existed. Every threshold below is a literal copy from it.

Read the prereg's section 0 first. This is NOT a blind registration: F's first three ATEs
(7.4447 / 6.9805 / 7.8344) and E's (8.18 / 9.72 / 9.40) were already printed as provenance in
an earlier round, so "F's mean is lower" was known going in. Two consequences are enforced:
  * the decision rule is SYMMETRIC in sign -- no one-sided test, no directional point
    prediction;
  * no sign-consistency rule (per-seed signs are printed as context only).
What was genuinely unseen: the six repeat ATEs, and the whole denominator.

Same shape as scripts/pose_trackside_paired_gate.py on purpose, so the two endpoints (the
per-frame dynamic penalty and ATE) are measured with the same caliper and can be read side by
side -- which is what a decoupling claim requires.

Usage: conda run -n monogs-ours python scripts/pose_trackside_ate_gate.py
"""

import csv
import glob
import itertools
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

SEQ = "balloon"
ARMS = {
    "E_trackside": "results/runs/PBA/pba_trackside_only_{seq}_seed{seed}",
    "F_trackhard": "results/runs/PBA/pba_trackside_hard_{seq}_seed{seed}",
}
CONTEXT_ARMS = {                      # descriptive only -- NOT single-variable against F
    "C_mapoff":   "results/runs/PBA/pba_mapping_off_{seq}*seed{seed}",
    "D_maskfree": "results/runs/T2/T2-QUOTA-3090/control_maskfree_{seq}_seed{seed}",
}
SEEDS = (0, 1, 2)
CHANNEL_KEYS = ("enabled", "mask_mapping", "mask_insertion", "hard_tracking_mask")

# ---- registered constants (prereg sections 3-4). DO NOT RECOMPUTE, DO NOT RELAX. ----
REACH_FLOOR_ATE = 0.55        # 6% (project-wide floor, CLAUDE.md) x E's published base 9.10 cm
# already-settled companion reading from the paired gate (prereg section 4)
SHIFT_P = 0.0806
FLOOR_P = 0.0662


def cells(pattern):
    """{seed: [(run_id, ate, channel_flags)]} -- every row of every run dir for that cell."""
    out = {}
    for seed in SEEDS:
        rows = []
        for outer in sorted(glob.glob(pattern.format(seq=SEQ, seed=seed))):
            path = os.path.join(outer, "tables", "tracking_raw.csv")
            if not os.path.isfile(path):
                continue
            flags_by_id = {}
            for cfg in glob.glob(os.path.join(outer, "**", "config.yml"), recursive=True):
                rid = os.path.basename(os.path.dirname(cfg))
                try:
                    import yaml
                    sem = (yaml.safe_load(open(cfg)) or {}).get("SemanticMask", {})
                    flags_by_id[rid] = tuple(bool(sem.get(k, False)) for k in CHANNEL_KEYS)
                except Exception:
                    pass
            for r in csv.DictReader(open(path)):
                try:
                    rows.append((r.get("run_id"), float(r["ate_rmse_cm"]),
                                 flags_by_id.get(r.get("run_id")),
                                 r.get("success_threshold_cm"), r.get("dataset")))
                except (KeyError, TypeError, ValueError):
                    pass
        if rows:
            out[seed] = rows
    return out


def main():
    A = {arm: cells(pat) for arm, pat in ARMS.items()}
    ctx = {arm: cells(pat) for arm, pat in CONTEXT_ARMS.items()}

    print("=" * 78)
    print(f"exp37 -- ATE endpoint, F track-hard vs E trackside ({SEQ})")
    print("prereg: results/evidence/pose_trackside_ate_prereg.md @ f9fa31ea")
    print("  NOT blind (prereg section 0): the rule is sign-symmetric and has no sign branch.")
    print("-" * 78)

    # ------------------------------------------------ gates
    gates = {}
    k1 = all(len(A[a].get(s, [])) == 2 and len({r[0] for r in A[a][s]}) == 2
             for a in ARMS for s in SEEDS)
    gates["K-1 r=2 per cell"] = (k1, "; ".join(
        f"{a}/s{s}={len(A[a].get(s, []))}" for a in ARMS for s in SEEDS))
    k2 = all(len({r[2] for r in A[a][s]}) == 1 and None not in {r[2] for r in A[a][s]}
             for a in ARMS for s in SEEDS)
    gates["K-2 repeats same cfg"] = (k2, "identical SemanticMask flags within every cell")
    fe, ff = A["E_trackside"][0][0][2], A["F_trackhard"][0][0][2]
    ndiff = sum(1 for i in range(len(CHANNEL_KEYS)) if fe[i] != ff[i])
    gates["K-3 single variable"] = (ndiff == 1, f"{ndiff} SemanticMask flag(s) differ "
                                                f"(E={fe}, F={ff})")
    cal = {(r[3], r[4]) for a in ARMS for s in SEEDS for r in A[a][s]}
    gates["K-4 one caliper"] = (len(cal) == 1, f"{len(cal)} distinct "
                                              f"(success_threshold_cm, dataset) combos")
    for k, (ok, d) in gates.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {k:22s} {d}")
    if not all(ok for ok, _ in gates.values()):
        print("\n>>> NO VERDICT (apparatus gate) -- prereg section 5")
        return

    # ------------------------------------------------ the statistic
    print("-" * 78)
    mean = {a: {} for a in ARMS}
    within = {a: [] for a in ARMS}
    for a in ARMS:
        for s in SEEDS:
            v = [r[1] for r in A[a][s]]
            mean[a][s] = float(np.mean(v))
            within[a].append(v[0] - v[1])
            print(f"  ATE {a:12s} s{s}  {v[0]:7.4f} / {v[1]:7.4f}   cell mean {mean[a][s]:7.4f}"
                  f"   |within| {abs(v[0] - v[1]):.4f}")
    for a, c in ctx.items():
        got = [f"{np.mean([r[1] for r in c[s]]):.2f}" for s in SEEDS if c.get(s)]
        if got:
            print(f"  [context, not single-variable] {a:12s} " + " / ".join(got))

    delta = {s: mean["F_trackhard"][s] - mean["E_trackside"][s] for s in SEEDS}
    shift = float(np.mean(list(delta.values())))
    nulls = sorted({round(abs(float(np.mean([e * d for e, d in zip(eps, within[a])]))), 10)
                    for a in ARMS for eps in itertools.product((-1, 1), repeat=len(SEEDS))})
    floor = max(nulls)
    floor_vm = floor / np.sqrt(2.0)

    print("-" * 78)
    print("  paired shift per seed  " + "  ".join(f"s{s} {delta[s]:+.4f}" for s in SEEDS))
    print(f"  shift_ATE = mean over seeds    {shift:+.4f} cm")
    print(f"  within-config |dATE|  E {[round(abs(d), 4) for d in within['E_trackside']]}"
          f"  F {[round(abs(d), 4) for d in within['F_trackhard']]}")
    print(f"  floor_ATE (max |null shift| over {len(nulls)} sign vectors) = {floor:.4f} cm")
    print(f"  [sensitivity] variance-matched floor = {floor_vm:.4f} cm "
          "(the null is sqrt(2) wide -- prereg section 2)")
    print(f"  [context, not a gate] per-seed sign: "
          f"{sum(1 for s in SEEDS if delta[s] < 0)}/3 negative (F better)")

    # ------------------------------------------------ step 0: reachability, then verdict
    def decide(sh, fl):
        if fl > REACH_FLOOR_ATE:
            return "UNREACHABLE", int(np.ceil(2.0 * (fl / REACH_FLOOR_ATE) ** 2))
        if abs(sh) <= fl:
            return "ATE-INDISTINGUISHABLE", None
        return ("ENDPOINT-DECOUPLED" if sh < 0 else "BOTH-ENDPOINTS-WORSE"), None

    print("-" * 78)
    print(f"  STEP 0 reachability: floor_ATE {floor:.4f} vs {REACH_FLOOR_ATE:.4f}"
          f"  -> {'REACHABLE' if floor <= REACH_FLOOR_ATE else 'UNREACHABLE'}")
    verdict, r_needed = decide(shift, floor)
    if verdict == "UNREACHABLE":
        assert r_needed is not None          # decide() always returns it on this branch
        print(f"           need r ~= {r_needed} runs per cell => "
              f"{r_needed * len(SEEDS) * len(ARMS)} runs total (have "
              f"{2 * len(SEEDS) * len(ARMS)}); prereg forbids relaxing 0.55")
    print(f"  >>> {verdict}")
    if verdict == "ENDPOINT-DECOUPLED":
        p_ok = SHIFT_P > FLOOR_P
        print(f"      companion endpoint (paired gate): shift_P {SHIFT_P:+.4f} vs floor_P "
              f"{FLOOR_P:.4f} -> {'above' if p_ok else 'below'}")
        print("      => the SAME single-variable intervention moves the two endpoints in")
        print("         OPPOSITE directions: worse per-frame tracking on dynamic frames,")
        print("         better accumulated drift." if p_ok else
              "      => companion reading does not clear its floor: downgrade to ATE-BETTER-ONLY")
        if not p_ok:
            verdict = "ATE-BETTER-ONLY"
        print("      MUST be quoted with the paired gate's three limits: margin 1.22x,")
        print("      the gate shows P MOVES not that the effect is per-seed consistent,")
        print("      and its floor is thin and seed2-dominated.")

    verdict_vm, _ = decide(shift, float(floor_vm))
    agree = verdict_vm == verdict or (verdict == "ATE-BETTER-ONLY"
                                      and verdict_vm == "ENDPOINT-DECOUPLED")
    print(f"  [sensitivity] with the variance-matched floor {floor_vm:.4f}: {verdict_vm}"
          f"  -> {'same label' if agree else 'DIFFERENT LABEL => CONSTRUCTION-LIMITED'}")

    # ------------------------------------------------ secondary, descriptive (prereg section 6)
    print("-" * 78)
    print("SECONDARY (descriptive, not a gate) -- balloon ATE noise split in two for the")
    print("first time. exp36 judged balloon ATE unresolvable using WITHIN-ARM RANGE, which")
    print("mixes these two layers. Which one dominates decides whether 'add seeds' or")
    print("'add repeats' is the right prescription NEXT time. exp36's verdict is unchanged.")
    split = {}
    for a in ARMS:
        wc = float(np.mean([abs(d) for d in within[a]]))
        bs = float(np.ptp([mean[a][s] for s in SEEDS]))
        split[a] = {"within_config_mean_abs": wc, "between_seed_ptp": bs,
                    "ratio_within_over_between": wc / bs if bs else None}
        print(f"  {a:12s} within-config mean|dATE| {wc:.4f}   between-seed ptp {bs:.4f}"
              f"   ratio {wc / bs:.2f}" if bs else "")
    tot_wc = float(np.mean([abs(d) for a in ARMS for d in within[a]]))
    tot_bs = float(np.mean([np.ptp([mean[a][s] for s in SEEDS]) for a in ARMS]))
    dom = "within-config (run-to-run)" if tot_wc > tot_bs else "between-seed"
    print(f"  pooled: within-config {tot_wc:.4f} vs between-seed {tot_bs:.4f} -> {dom} dominates")
    print(f"  => next time, the right prescription is "
          f"{'MORE REPEATS, not more seeds' if tot_wc > tot_bs else 'more seeds'}")

    out = "results/evidence/pose_trackside_ate_gate.json"
    json.dump({"sequence": SEQ, "prereg_commit": "f9fa31ea", "blind": False,
               "reach_floor": REACH_FLOOR_ATE,
               "gates": {k: {"pass": bool(p), "detail": d} for k, (p, d) in gates.items()},
               "cell_mean_ate": {a: {str(s): round(mean[a][s], 4) for s in SEEDS} for a in ARMS},
               "within_config_signed": {a: [round(d, 4) for d in within[a]] for a in ARMS},
               "delta_per_seed": {str(s): round(delta[s], 4) for s in SEEDS},
               "shift_ATE": shift, "floor_ATE": floor, "floor_variance_matched": float(floor_vm),
               "null_shifts": nulls, "verdict": verdict, "verdict_variance_matched": verdict_vm,
               "labels_agree": bool(agree), "r_needed_per_cell": r_needed,
               "noise_split": split,
               "pooled_within_config": tot_wc, "pooled_between_seed": tot_bs},
              open(out, "w"), indent=2)
    print("=" * 78)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
