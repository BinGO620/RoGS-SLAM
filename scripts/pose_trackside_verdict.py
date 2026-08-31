#!/usr/bin/env python3
"""exp37 verdict -- does the trackside channel reduce the dynamics-specific per-frame
tracking penalty on ``balloon``?

Pre-registration: results/evidence/pose_trackside_prereg.md, committed at 364da26c BEFORE
this file existed. Every threshold below is a LITERAL COPY of a number registered there,
each annotated with the section it comes from. Nothing is re-fitted here: the machinery
(RPE caliper, strata construction, penalty) is IMPORTED from the calibration script so the
treatment arm is measured with byte-identical code to the controls.

Read the prereg's section 1 before quoting any result: the estimand is NOT a
higher-resolution ATE. Calibration showed ATE effect size and per-frame RPE effect size are
not monotone across sequences, so NOTHING here may be phrased as "trackside does / does not
explain the 2.3 cm ATE gap".

Usage: conda run -n monogs-ours python scripts/pose_trackside_verdict.py
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
    split_plain,
)

SEQ = "balloon"                      # prereg 7.1: the ONLY sequence this estimand can judge
TREATMENT = "results/runs/PBA/pba_trackside_only_{seq}_seed{seed}"
CONTROLS = {                         # same roots the calibration used, same priority order
    "A_eboth_T2":  ["results/runs/T2/T2-QUOTA-3090/eboth_{seq}_seed{seed}"],
    "A_eboth_PBA": ["results/runs/PBA/eboth_{seq}_seed{seed}"],
    "B_insoff":    ["results/runs/PBA/pba_tracking_only_{seq}_seed{seed}"],
    "C_mapoff":    ["results/runs/PBA/pba_mapping_off_{seq}_3090_seed{seed}",
                    "results/runs/PBA/pba_mapping_off_{seq}_seed{seed}"],
    "D_maskfree":  ["results/runs/T2/T2-QUOTA-3090/control_maskfree_{seq}_seed{seed}",
                    "results/runs/PBA/control_maskfree_{seq}_seed{seed}"],
}

# ---- registered constants (prereg sections 4-6). DO NOT RECOMPUTE, DO NOT ADJUST. ----
REG = {
    "motion_matched": {                       # PRIMARY  (prereg 3, 5, 6)
        "p_inert": 0.3911,                    # = P(D maskfree)
        "p_material": 0.1510,                 # = maskON group mean
        "floor": 0.0831,                      # |dP| max over the 4 same-cfg+seed repeats
        "spacing": 0.2401,
        "stop": 0.1200,                       # 0.5 x spacing -> INDETERMINATE
        "two_floor": 0.1662,
        "maskon_min_run": 0.0669,             # for the ANOMALY guard
        "gate_b_min_gap": 0.1532,             # G-B as measured in calibration
        "gate_b_gap": 0.2580,
    },
    "plain": {                                # SENSITIVITY only -- may not flip the verdict
        "p_inert": 0.6236,
        "p_material": 0.4199,
        "floor": 0.0727,
        "spacing": 0.2037,
        "stop": 0.1019,
        "two_floor": 0.1454,
        "maskon_min_run": 0.3803,
        "gate_b_min_gap": 0.1465,
        "gate_b_gap": 0.2233,
    },
}
ANCHOR_TOL_CM = 5e-3                          # prereg G-A
ROLL_OFFSETS = (109, 219, 329)                # prereg G-C
COVERAGE_MIN = 0.95                           # prereg G-E


def _arm_runs(pats, seq, seed):
    for pat in (pats if isinstance(pats, list) else [pats]):
        hits = _load_runs(pat.format(seq=seq, seed=seed))
        if hits:
            return pat.format(seq=seq, seed=seed), hits
    return None, []


def load(seq):
    """{arm: {seed: [(run_id, rpe_per_frame)]}} plus the per-run anchor check."""
    out, anchor = {}, []
    for arm, pats in list(CONTROLS.items()) + [("E_trackside", [TREATMENT])]:
        out[arm] = {}
        for seed in SEEDS:
            pat, hits = _arm_runs(pats, seq, seed)
            if not hits:
                continue
            csv_by_id = _csv_rows(pat)
            got = []
            for run_id, trj in hits:
                _ids, est, gt = _poses(trj)
                rpe_pf, ate_rms, rpe_rms = _evo_metrics(est, gt)
                ref = csv_by_id.get(run_id)
                anchor.append((f"{arm}/s{seed}/{run_id}", ate_rms,
                               ref["ate"] if ref else None,
                               rpe_rms, ref["rpe"] if ref else None))
                got.append((run_id, rpe_pf))
            out[arm][seed] = got
    return out, anchor


def decide(pe_mean, pe_range, pe_vs_d, cfg):
    """The registered decision rule, in the registered order. Stop rule fires FIRST."""
    if pe_range > cfg["stop"]:
        return ("INDETERMINATE",
                f"range(P(E)) {pe_range:.4f} > stop {cfg['stop']:.4f} "
                "(prereg 6 step 0: do not read a label, do not add seeds)")
    if pe_mean < cfg["maskon_min_run"] - cfg["floor"]:
        return ("ANOMALY",
                f"P(E) {pe_mean:.4f} beats the best mask-ON run by more than a floor "
                "(prereg 6: treat as an apparatus doubt, do not label)")
    d_on = abs(pe_mean - cfg["p_material"])
    d_off = abs(pe_mean - cfg["p_inert"])
    if d_on <= cfg["floor"] and d_off >= cfg["two_floor"] and pe_vs_d == 3:
        return ("TRACKSIDE-MATERIAL",
                f"d_on {d_on:.4f} <= floor {cfg['floor']:.4f}, d_off {d_off:.4f} >= "
                f"{cfg['two_floor']:.4f}, per-seed P(E)<P(D) 3/3")
    if d_off <= cfg["floor"] and d_on >= cfg["two_floor"]:
        return ("TRACKSIDE-INERT",
                f"d_off {d_off:.4f} <= floor {cfg['floor']:.4f}, "
                f"d_on {d_on:.4f} >= {cfg['two_floor']:.4f}")
    return ("PARTIAL", f"d_on {d_on:.4f} and d_off {d_off:.4f} both exceed the floor "
                       f"{cfg['floor']:.4f}")


def main():
    runs, anchor = load(SEQ)

    area = _pair_area(_dyn_area(SEQ), len(runs["E_trackside"][0][0][1]))
    step = gt_step_cm(_gt_of(None, SEQ), len(area))
    splits = {"motion_matched": split_motion_matched(area, step),
              "plain": split_plain(area, step)}

    print("=" * 78)
    print(f"exp37 -- trackside channel vs the dynamic per-frame tracking penalty ({SEQ})")
    print("prereg: results/evidence/pose_trackside_prereg.md @ 364da26c")

    # ---------------------------------------------------------------- gates
    gates = {}
    bad = [a for a in anchor if a[2] is None or a[4] is None
           or abs(a[1] - a[2]) > ANCHOR_TOL_CM or abs(a[3] - a[4]) > ANCHOR_TOL_CM]
    worst = max((max(abs(a[1] - a[2]), abs(a[3] - a[4]))
                 for a in anchor if a[2] is not None and a[4] is not None), default=None)
    gates["G-A anchor"] = (not bad, f"{len(anchor)} runs, max|delta| {worst:.5f} cm, "
                                    f"{len(bad)} failures")
    ok = np.isfinite(area)
    gates["G-E coverage"] = (ok.mean() >= COVERAGE_MIN,
                             f"{int(ok.sum())}/{len(area)} pairs = {ok.mean() * 100:.1f}%")

    def parm(arm, st):
        return [penalty(g[1], st) for seed in SEEDS for g in runs[arm].get(seed, [])]

    for vname, st in splits.items():
        cfg = REG[vname]
        on = [v for a in ("A_eboth_T2", "A_eboth_PBA", "B_insoff") for v in parm(a, st)]
        off = [v for a in ("C_mapoff", "D_maskfree") for v in parm(a, st)]
        mg, gp = min(off) - max(on), float(np.mean(off) - np.mean(on))
        gates[f"G-B positive ({vname})"] = (
            mg > 0 and gp >= 2 * cfg["floor"],
            f"min-gap {mg:+.4f} (registered {cfg['gate_b_min_gap']:+.4f}), "
            f"gap {gp:+.4f} (registered {cfg['gate_b_gap']:+.4f}) vs 2xfloor "
            f"{2 * cfg['floor']:.4f}")

    rolled_ok = 0
    cfg_mm = REG["motion_matched"]
    for offn in ROLL_OFFSETS:
        st = split_plain(np.roll(area, offn), step)
        on = [v for a in ("A_eboth_T2", "A_eboth_PBA", "B_insoff") for v in parm(a, st)]
        off = [v for a in ("C_mapoff", "D_maskfree") for v in parm(a, st)]
        gp = float(np.mean(off) - np.mean(on))
        if gp <= 0 or abs(gp) < 0.5 * cfg_mm["gate_b_gap"]:
            rolled_ok += 1
    gates["G-C invalidation"] = (rolled_ok >= 2,
                                 f"{rolled_ok}/3 rolled offsets fail to reproduce the gap")

    print("-" * 78)
    for k, (passed, detail) in gates.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {k:26s} {detail}")
    if not all(p for p, _ in gates.values()):
        print("\n>>> NO VERDICT (apparatus gate) -- prereg section 4")
        return

    # ---------------------------------------------------------------- reading
    result = {}
    for vname, st in splits.items():
        cfg = REG[vname]
        pe = {s: [penalty(g[1], st) for g in runs["E_trackside"].get(s, [])] for s in SEEDS}
        pd_ = {s: [penalty(g[1], st) for g in runs["D_maskfree"].get(s, [])] for s in SEEDS}
        flat_e = [v for s in SEEDS for v in pe[s]]
        vs_d = sum(1 for s in SEEDS if pe[s] and pd_[s] and np.mean(pe[s]) < np.mean(pd_[s]))
        pe_mean, pe_range = float(np.mean(flat_e)), float(np.ptp(flat_e))
        verdict, why = decide(pe_mean, pe_range, vs_d, cfg)

        tag = "PRIMARY" if vname == "motion_matched" else "SENSITIVITY"
        print("=" * 78)
        print(f"{tag} -- {vname}")
        for a in ("A_eboth_T2", "A_eboth_PBA", "B_insoff", "C_mapoff",
                  "E_trackside", "D_maskfree"):
            vv = parm(a, st)
            if vv:
                mark = " <-- treatment" if a == "E_trackside" else ""
                print(f"  P {a:12s} " + " ".join(f"{v:+.4f}" for v in vv)
                      + f"   mean {np.mean(vv):+.4f}{mark}")
        print(f"  point predictions: H-inert {cfg['p_inert']:+.4f}  "
              f"H-material {cfg['p_material']:+.4f}  (spacing {cfg['spacing']:.4f}, "
              f"floor {cfg['floor']:.4f})")
        print(f"  P(E) mean {pe_mean:+.4f}  range {pe_range:.4f}  "
              f"per-seed P(E)<P(D) {vs_d}/3")
        share = ((cfg["p_inert"] - pe_mean) / (cfg["p_inert"] - cfg["p_material"]))
        print(f"  trackside share of the dynamic penalty s = {share * 100:.0f}%"
              f"   (readable only if >=35%, prereg section 5)")
        print(f"  >>> {verdict}: {why}")
        result[vname] = {"P_E": [round(v, 4) for v in flat_e], "P_E_mean": pe_mean,
                         "P_E_range": pe_range, "per_seed_better_than_D": vs_d,
                         "share_pct": round(share * 100, 1), "verdict": verdict,
                         "why": why}

    out = "results/evidence/pose_trackside_verdict.json"
    json.dump({"sequence": SEQ, "prereg_commit": "364da26c",
               "gates": {k: {"pass": bool(p), "detail": d} for k, (p, d) in gates.items()},
               "readings": result}, open(out, "w"), indent=2)
    print("=" * 78)
    print(f"wrote {out}")
    print("Scope (prereg section 7): balloon only. f3_wk_xyz has no covariate; pt1 is not")
    print("judgeable. This is a per-frame tracking statement, NOT an ATE attribution.")


if __name__ == "__main__":
    main()
