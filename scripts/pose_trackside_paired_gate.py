#!/usr/bin/env python3
"""exp37 paired apparatus gate -- does the dynamic penalty P respond to a TRACKING-side
intervention, judged with a floor that has the SAME SHAPE as the statistic?

Pre-registration: results/evidence/pose_trackside_paired_prereg.md (committed before the
first repeat run). This file executes that rule only.

READ THE PREREG'S SECTION 0 FIRST. This is NOT a blind registration: the three single-run
paired shifts (+0.0360/+0.1486/-0.0546) were computed post-hoc last round and written down.
Two consequences are enforced here:
  * NO sign-consistency rule is implemented -- the signs are already known, so a "k/3 agree"
    gate would be self-deception. Sign counts are printed as CONTEXT ONLY, never as a gate.
  * What was genuinely unseen is the DENOMINATOR: each arm's within-config paired floor,
    which the repeat batch buys.

Why pairing was not expected to be a magic fix (prereg section 1): pairing removes seed-level
common variation, but NOT run-to-run nondeterminism -- and F's spread looks like the latter.
That is exactly why step 0 is a REACHABILITY check, not a verdict.

The floor is built to the same shape as the statistic: for each arm and each sign vector
eps in {-1,+1}^3, a null shift is the mean over seeds of eps_s * (run_a - run_b) within the
SAME config+seed cell, so its expectation is zero and it inherits the same autocorrelation
and run-to-run noise as the real statistic.

Usage: conda run -n monogs-ours python scripts/pose_trackside_paired_gate.py
"""

import itertools
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from scripts.pose_rpe_calibration import (  # noqa: E402
    SEEDS,
    _csv_rows,
    _dyn_area,
    _evo_metrics,
    _gt_of,
    _load_runs,
    _pair_area,
    _poses,
    gt_step_cm,
    penalty,
    split_motion_matched,
)

SEQ = "balloon"
ARMS = {                                     # cell -> run dir pattern
    "E_trackside": "results/runs/PBA/pba_trackside_only_{seq}_seed{seed}",
    "F_trackhard": "results/runs/PBA/pba_trackside_hard_{seq}_seed{seed}",
}

# ---- registered constants (paired prereg sections 4-5). DO NOT RECOMPUTE. ----
REACH_FLOOR = 0.0831        # exp37's registered floor = the smallest shift it treats as real
ANCHOR_TOL_CM = 5e-3        # gate J-1
CHANNEL_KEYS = ("enabled", "mask_mapping", "mask_insertion", "hard_tracking_mask")


def load():
    """{arm: {seed: [(run_id, rpe_per_frame, ate, channel_flags)]}} + anchor rows."""
    out, anchor = {}, []
    for arm, pat in ARMS.items():
        out[arm] = {}
        for seed in SEEDS:
            p = pat.format(seq=SEQ, seed=seed)
            hits = _load_runs(p)
            if not hits:
                continue
            csv_by_id = _csv_rows(p)
            got = []
            for run_id, trj in hits:
                _ids, est, gt = _poses(trj)
                rpe_pf, ate_rms, rpe_rms = _evo_metrics(est, gt)
                ref = csv_by_id.get(run_id)
                anchor.append((f"{arm}/s{seed}/{run_id}", ate_rms,
                               ref["ate"] if ref else None,
                               rpe_rms, ref["rpe"] if ref else None))
                cfg_path = os.path.join(os.path.dirname(os.path.dirname(trj)), "config.yml")
                flags = None
                if os.path.isfile(cfg_path):
                    import yaml
                    sem = (yaml.safe_load(open(cfg_path)) or {}).get("SemanticMask", {})
                    flags = tuple(bool(sem.get(k, False)) for k in CHANNEL_KEYS)
                got.append((run_id, rpe_pf, ate_rms, flags))
            out[arm][seed] = got
    return out, anchor


def decide(shift, floor_paired, reach_floor=REACH_FLOOR):
    """The registered rule, in the registered order: reachability FIRST, then the contrast.

    No sign-consistency branch exists on purpose (prereg section 0: the signs were already
    seen post-hoc, so gating on them would be self-deception).
    """
    if floor_paired > reach_floor:
        r_needed = int(np.ceil(2.0 * (floor_paired / reach_floor) ** 2))
        return "UNREACHABLE", r_needed
    if abs(shift) > floor_paired:
        return "APPARATUS-TRACKING-SENSITIVE", None
    return "APPARATUS-TRACKING-BLIND", None


def main():
    runs, anchor = load()
    have = {a: sum(1 for s in SEEDS if len(runs[a].get(s, [])) >= 2) for a in ARMS}
    if min(have.values()) < len(SEEDS):
        print(f"repeats incomplete: cells with >=2 runs {have} (need 3 per arm). "
              "Pull the repeat batch's plot/trj_full_final.json first.")
        return

    n_pairs = len(runs["F_trackhard"][0][0][1])
    area = _pair_area(_dyn_area(SEQ), n_pairs)
    step = gt_step_cm(_gt_of(None, SEQ), len(area))
    st = split_motion_matched(area, step)

    print("=" * 78)
    print("exp37 PAIRED apparatus gate -- tracking-side positive control (balloon)")
    print("prereg: results/evidence/pose_trackside_paired_prereg.md")
    print("  NOT a blind registration -- see prereg section 0. No sign rule is applied.")
    print("-" * 78)

    # ---------------- gates ----------------
    gates = {}
    bad = [a for a in anchor if a[2] is None or a[4] is None
           or abs(a[1] - a[2]) > ANCHOR_TOL_CM or abs(a[3] - a[4]) > ANCHOR_TOL_CM]
    worst = max((max(abs(a[1] - a[2]), abs(a[3] - a[4]))
                 for a in anchor if a[2] is not None and a[4] is not None), default=float("nan"))
    gates["J-1 anchor"] = (not bad, f"{len(anchor)} runs, max|delta| {worst:.5f} cm, "
                                    f"{len(bad)} failures")

    j2 = []
    for arm in ARMS:
        for seed in SEEDS:
            fl = {r[3] for r in runs[arm][seed]}
            j2.append(len(fl) == 1 and None not in fl)
    gates["J-2 repeats same cfg"] = (all(j2),
                                     f"{sum(j2)}/{len(j2)} cells have identical SemanticMask "
                                     f"flags across their repeats")
    gates["J-4 single variable"] = (
        len({runs[a][0][0][3] for a in ARMS}) == 2
        and sum(1 for i, k in enumerate(CHANNEL_KEYS)
                if runs["E_trackside"][0][0][3][i] != runs["F_trackhard"][0][0][3][i]) == 1,
        "exactly one SemanticMask flag differs between the arms")

    for k, (ok, d) in gates.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {k:24s} {d}")
    if not all(ok for ok, _ in gates.values()):
        print("\n>>> NO VERDICT (apparatus gate)")
        return

    # ---------------- the statistic ----------------
    P = {a: {s: [penalty(r[1], st) for r in runs[a][s]] for s in SEEDS} for a in ARMS}
    print("-" * 78)
    for arm in ARMS:
        for seed in SEEDS:
            print(f"  P {arm:12s} s{seed}  "
                  + " / ".join(f"{v:+.4f}" for v in P[arm][seed])
                  + f"   cell mean {np.mean(P[arm][seed]):+.4f}"
                  + f"   |within| {abs(P[arm][seed][0] - P[arm][seed][1]):.4f}")

    delta = {s: float(np.mean(P["F_trackhard"][s]) - np.mean(P["E_trackside"][s])) for s in SEEDS}
    shift = float(np.mean(list(delta.values())))

    # same-shape null: mean over seeds of a WITHIN-cell difference, every sign vector
    within = {a: [P[a][s][0] - P[a][s][1] for s in SEEDS] for a in ARMS}
    nulls = []
    for arm in ARMS:
        for eps in itertools.product((-1, 1), repeat=len(SEEDS)):
            nulls.append(abs(float(np.mean([e * d for e, d in zip(eps, within[arm])]))))
    nulls = sorted(set(round(v, 10) for v in nulls))
    floor_paired = max(nulls)

    print("-" * 78)
    print("  paired shift per seed  " + "  ".join(f"s{s} {delta[s]:+.4f}" for s in SEEDS))
    print(f"  shift = mean over seeds        {shift:+.4f}")
    print(f"  within-config |dP|   E {[round(abs(d), 4) for d in within['E_trackside']]}"
          f"   F {[round(abs(d), 4) for d in within['F_trackhard']]}")
    print(f"  floor_paired (max |null shift| over {len(nulls)} distinct sign vectors) "
          f"= {floor_paired:.4f}")
    # ---- SELF-CORRECTION, written before the data landed, reported as a sensitivity ----
    # The prereg called this null "same shape" as the statistic. That is true STRUCTURALLY
    # (both are a mean over 3 seeds of a paired difference) but NOT in variance:
    #   real  Delta_s = difference of two CELL MEANS (r=2 each)  -> var (s2_E + s2_F)/2 = s2
    #   null  term    = difference of two SINGLE runs            -> var 2*s2
    # so the registered floor is sqrt(2) TOO WIDE. That is conservative for declaring
    # SENSITIVE, but it biases the reachability check toward CLOSING the route, which is not
    # a harmless direction. The registered rule is executed as written; the corrected floor is
    # printed beside it and, if the two disagree, the outcome is reported as construction-
    # limited rather than resolved in whichever direction is convenient.
    floor_corrected = floor_paired / np.sqrt(2.0)
    print(f"  [sensitivity] variance-matched floor = floor_paired/sqrt(2) "
          f"= {floor_corrected:.4f}  (the prereg's 'same shape' claim holds structurally, "
          f"not in variance)")
    # context only, explicitly NOT a gate (prereg section 0)
    print(f"  [context, not a gate] sign of paired shift: "
          f"{sum(1 for s in SEEDS if delta[s] > 0)}/3 positive")

    # ---------------- step 0: reachability, registered BEFORE the verdict ----------------
    print("-" * 78)
    reachable = floor_paired <= REACH_FLOOR
    print(f"  STEP 0 reachability: floor_paired {floor_paired:.4f} vs {REACH_FLOOR:.4f}"
          f"  -> {'REACHABLE' if reachable else 'UNREACHABLE'}")
    verdict, r_needed = decide(shift, floor_paired)
    if verdict == "UNREACHABLE":
        assert r_needed is not None          # decide() always returns it on this branch
        total = r_needed * len(SEEDS) * len(ARMS)
        print(f"           to reach it at ~1/sqrt(r): r ~= {r_needed} runs per cell "
              f"=> {total} runs total (have {2 * len(SEEDS) * len(ARMS)})")
        why = (f"floor_paired {floor_paired:.4f} > {REACH_FLOOR:.4f}: pairing did not buy "
               f"resolution because it cannot remove run-to-run nondeterminism (prereg "
               f"section 1). Route (a) is closed at this n; ~{r_needed} runs per cell would be "
               f"needed. Do NOT relax the threshold -- switch to candidate (b) or (c).")
    elif verdict == "APPARATUS-TRACKING-SENSITIVE":
        why = (f"|shift| {abs(shift):.4f} > floor_paired {floor_paired:.4f} => the estimand does "
               "respond to a tracking-side intervention; exp37's TRACKSIDE-INERT stands, "
               "narrowed to 'channel 1 buys nothing WITHIN its 10/100 scope'")
    else:
        why = (f"|shift| {abs(shift):.4f} <= floor_paired {floor_paired:.4f} with the gate "
               "REACHABLE => widening channel 1 tenfold does not move the estimand; exp37's "
               "verdict DEGRADES TO DESCRIPTIVE")
    print(f"  >>> {verdict}: {why}")

    # does the sqrt(2) conservatism change the label? (pre-specified sensitivity)
    verdict_corr, _ = decide(shift, float(floor_corrected))
    agree = verdict_corr == verdict
    print(f"  [sensitivity] with the variance-matched floor {floor_corrected:.4f}: "
          f"{verdict_corr}  -> {'same label' if agree else 'DIFFERENT LABEL'}")
    if not agree:
        print("      => the label depends on a construction detail the prereg got slightly")
        print("         wrong; report as CONSTRUCTION-LIMITED, do not pick the convenient one.")

    out = "results/evidence/pose_trackside_paired_gate.json"
    json.dump({"sequence": SEQ, "blind": False,
               "reach_floor": REACH_FLOOR, "floor_paired": floor_paired,
               "P": {a: {str(s): [round(v, 4) for v in P[a][s]] for s in SEEDS} for a in ARMS},
               "delta_per_seed": {str(s): round(delta[s], 4) for s in SEEDS},
               "shift": shift, "within_abs": {a: [round(abs(d), 4) for d in within[a]]
                                              for a in ARMS},
               "null_shifts": nulls, "reachable": reachable, "r_needed_per_cell": r_needed,
               "floor_variance_matched": float(floor_corrected),
               "verdict_variance_matched": verdict_corr, "labels_agree": bool(agree),
               "anchor_max_abs_delta": worst, "verdict": verdict, "why": why},
              open(out, "w"), indent=2)
    print("=" * 78)
    print(f"wrote {out}")
    print("Phase 0: mechanism only. ATE is not read here (the flagged F-arm ATE from the")
    print("previous batch still needs its own pre-registration).")


if __name__ == "__main__":
    main()
