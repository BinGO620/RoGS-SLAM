#!/usr/bin/env python3
"""exp37 apparatus gate -- is the dynamic penalty P sensitive to a TRACKING-side intervention?

Pre-registration: results/evidence/pose_trackside_prereg_addendum.md (commit 2985dd07,
BEFORE the first run). This file only executes the rule registered there; it introduces no
threshold of its own and re-fits nothing -- the floor, the split construction and the
reference value P(E) are all imported or copied from exp37.

Why it exists: exp37 judged TRACKSIDE-INERT, but its only positive control was a
MAPPING-side channel (``mask_mapping``). Without a tracking-side positive control, "INERT"
cannot be distinguished from "the estimand is blind to the tracking side".

The intervention: ``hard_tracking_mask: true`` keeps the hard semantic mask in the tracking
loss for all 100 iterations instead of the first 10 (utils/slam_utils.py:126-153).

Registered rule -- direction is deliberately NOT predicted, the gate only asks whether P moves:
    |P(E-hard) - P(E)| >  0.0831  ->  APPARATUS-TRACKING-SENSITIVE  (exp37's verdict stands)
    |P(E-hard) - P(E)| <= 0.0831  ->  APPARATUS-TRACKING-BLIND      (exp37 degrades to descriptive)
    range(P(E-hard)) > 0.1200     ->  NO VERDICT (stop rule, checked first)

Usage: conda run -n monogs-ours python scripts/pose_trackside_hard_gate.py
"""

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
ARMS = {
    "E_trackside":  "results/runs/PBA/pba_trackside_only_{seq}_seed{seed}",
    "F_trackhard":  "results/runs/PBA/pba_trackside_hard_{seq}_seed{seed}",
    # context only, never part of the gate arithmetic
    "A_eboth":      "results/runs/T2/T2-QUOTA-3090/eboth_{seq}_seed{seed}",
    "D_maskfree":   "results/runs/T2/T2-QUOTA-3090/control_maskfree_{seq}_seed{seed}",
}

# ---- registered constants (addendum section 4; identical to exp37's PRIMARY). ----
FLOOR = 0.0831            # |dP| max over the 4 same-config+seed repeats, motion-matched
P_E = 0.3996              # exp37 measured mean P(E)
STOP = 0.1200             # 0.5 x spacing
ANCHOR_TOL_CM = 5e-3      # gate H-3


def load():
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
                got.append((run_id, rpe_pf, ate_rms))
            out[arm][seed] = got
    return out, anchor


def main():
    runs, anchor = load()
    if not runs.get("F_trackhard"):
        print("F_trackhard (pba_trackside_hard_balloon_seed*) not on disk yet -- "
              "pull the batch's plot/trj_full_final.json first.")
        return

    n_pairs = len(next(iter(runs["F_trackhard"].values()))[0][1])
    area = _pair_area(_dyn_area(SEQ), n_pairs)
    step = gt_step_cm(_gt_of(None, SEQ), len(area))
    st = split_motion_matched(area, step)

    print("=" * 78)
    print("exp37 apparatus gate -- tracking-side positive control (balloon, motion-matched)")
    print("prereg addendum: results/evidence/pose_trackside_prereg_addendum.md @ 2985dd07")

    bad = [a for a in anchor if a[2] is None or a[4] is None
           or abs(a[1] - a[2]) > ANCHOR_TOL_CM or abs(a[3] - a[4]) > ANCHOR_TOL_CM]
    worst = max((max(abs(a[1] - a[2]), abs(a[3] - a[4]))
                 for a in anchor if a[2] is not None and a[4] is not None), default=float("nan"))
    print(f"  H-3 anchor: {len(anchor)} runs, max|delta| {worst:.5f} cm, {len(bad)} failures"
          f"  -> {'PASS' if not bad else 'FAIL'}")
    if bad:
        for b in bad[:5]:
            print(f"      {b[0]}")
        print("\n>>> NO VERDICT (gate H-3)")
        return

    print("-" * 78)
    per_arm = {}
    for arm in ("A_eboth", "E_trackside", "F_trackhard", "D_maskfree"):
        vals, ates = [], []
        for seed in SEEDS:
            for g in runs[arm].get(seed, []):
                vals.append(penalty(g[1], st))
                ates.append(g[2])
        if not vals:
            continue
        per_arm[arm] = vals
        mark = "  <-- positive control" if arm == "F_trackhard" else ""
        print(f"  P {arm:13s} " + " ".join(f"{v:+.4f}" for v in vals)
              + f"   mean {np.mean(vals):+.4f}   (ATE "
              + "/".join(f"{a:.2f}" for a in ates) + f"){mark}")

    pf = per_arm["F_trackhard"]
    pf_mean, pf_range = float(np.mean(pf)), float(np.ptp(pf))
    shift = abs(pf_mean - P_E)

    print("-" * 78)
    print(f"  P(E) reference (exp37)      {P_E:+.4f}")
    print(f"  P(E-hard) measured          {pf_mean:+.4f}   range {pf_range:.4f}")
    print(f"  |shift|                     {shift:.4f}   vs floor {FLOOR:.4f}"
          f"   = {shift / FLOOR:.2f}x")

    if pf_range > STOP:
        verdict, why = ("NO VERDICT (stop rule)",
                        f"range(P(E-hard)) {pf_range:.4f} > {STOP:.4f}")
    elif shift > FLOOR:
        verdict, why = ("APPARATUS-TRACKING-SENSITIVE",
                        f"|shift| {shift:.4f} > floor {FLOOR:.4f} => the estimand does "
                        "respond to a tracking-side intervention; exp37's TRACKSIDE-INERT "
                        "stands, narrowed to 'channel (1) buys nothing WITHIN its 10/100 scope'")
    else:
        verdict, why = ("APPARATUS-TRACKING-BLIND",
                        f"|shift| {shift:.4f} <= floor {FLOOR:.4f} => amplifying the tracking "
                        "channel 10x in scope does not move the estimand; exp37's verdict "
                        "DEGRADES TO DESCRIPTIVE and must not be read as a mechanism claim")
    print(f"  >>> {verdict}: {why}")

    out = "results/evidence/pose_trackside_hard_gate.json"
    json.dump({"sequence": SEQ, "prereg_commit": "2985dd07",
               "floor": FLOOR, "P_E_reference": P_E, "stop": STOP,
               "per_arm": {k: [round(x, 4) for x in v] for k, v in per_arm.items()},
               "P_F_mean": pf_mean, "P_F_range": pf_range, "shift": shift,
               "shift_over_floor": shift / FLOOR,
               "anchor_max_abs_delta": worst, "verdict": verdict, "why": why},
              open(out, "w"), indent=2)
    print("=" * 78)
    print(f"wrote {out}")
    print("Phase 0 discipline: this gate reads the MECHANISM (does P move), not ATE. The ATE")
    print("column is printed for provenance only and carries no part of the decision.")


if __name__ == "__main__":
    main()
