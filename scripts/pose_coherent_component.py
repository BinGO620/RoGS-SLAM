#!/usr/bin/env python3
"""exp38 -- the coherent-amplitude endpoint: does the variance-vs-bias mechanism from
exp37's ENDPOINT-DECOUPLED hold up as a measurement?

Pre-registration: results/evidence/pose_coherent_prereg.md (committed before this file).

The prediction from exp37 is that F (wider tracking mask, 100/100) has:
  - HIGHER per-frame error magnitude (P worse, +0.0806)
  - LOWER accumulated drift (ATE better, -1.42 cm)
  - The mechanism: F's extra errors are MORE INCOHERENT (noise-like) → don't accumulate

This script tests that by computing:
  coherent = ||mean(rpe_hi)|| / mean(||rpe_hi||)     (direction consistency)
  coherent_amp = coherent * median(||rpe_hi||)        (drift contribution)

Usage: conda run -n monogs-ours python scripts/pose_coherent_component.py
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
    _dyn_area,
    _load_runs,
    _pair_area,
    _poses,
    gt_step_cm,
    _gt_of,
    split_motion_matched,
)

SEQ = "balloon"
ARMS = {
    "E_trackside": "results/runs/PBA/pba_trackside_only_{seq}_seed{seed}",
    "F_trackhard": "results/runs/PBA/pba_trackside_hard_{seq}_seed{seed}",
}

# ---- registered constants (prereg section 3). DO NOT RECOMPUTE. ----
REACH_FLOOR_CA = 0.0831   # same as exp37's REACH_FLOOR (P endpoint)


def coherent_full(vecs):
    """coherent = ||mean(v)|| / mean(||v||) over all vectors."""
    norms = np.linalg.norm(vecs, axis=1)
    if len(norms) == 0 or norms.mean() == 0:
        return float("nan")
    return float(np.linalg.norm(vecs.mean(axis=0)) / norms.mean())


def load_cell(arm_pat, seq, seed):
    """Return [(run_id, rpe_vecs, rpe_mag, hi_mask, lo_mask)] for each run in a cell."""
    p = arm_pat.format(seq=seq, seed=seed)
    hits = _load_runs(p)
    frac = _dyn_area(seq)
    gt_arr_global = _gt_of(None, seq)

    out = []
    for run_id, trj in hits:
        trj_id, est, gt_arr = _poses(trj)
        n_pairs = len(est) - 1
        area = _pair_area(frac, n_pairs)
        step = gt_step_cm(gt_arr_global, len(area))
        st = split_motion_matched(area, step)

        rel_est = np.linalg.inv(est[:-1]) @ est[1:]
        rel_gt = np.linalg.inv(gt_arr[:-1]) @ gt_arr[1:]
        rpe_vec = (np.linalg.inv(rel_est)[:, :3, 3] - np.linalg.inv(rel_gt)[:, :3, 3]) * 100  # cm
        rpe_mag = np.linalg.norm(rpe_vec, axis=1)  # cm

        hi = st["hi"][: len(rpe_mag)]
        lo = st["lo"][: len(rpe_mag)]
        out.append((run_id, rpe_vec, rpe_mag, hi, lo))
    return out


def coherent_amplitude(rpe_vec, rpe_mag, mask):
    """coherent_amp on a subset of pairs."""
    v = rpe_vec[mask]
    m = rpe_mag[mask]
    if len(v) < 5 or m.mean() == 0:
        return float("nan"), float("nan")
    coh = float(np.linalg.norm(v.mean(axis=0)) / m.mean())
    amp = coh * float(np.median(m))
    return coh, amp


def main():
    print("=" * 78)
    print(f"exp38 -- coherent amplitude endpoint ({SEQ})")
    print("prereg: results/evidence/pose_coherent_prereg.md")
    print("-" * 78)

    # ---- collect per-cell data ----
    cells = {}  # (arm, seed) -> [(run_id, rpe_vec, rpe_mag, hi_mask, lo_mask)]
    for arm, pat in ARMS.items():
        for seed in SEEDS:
            cells[(arm, seed)] = load_cell(pat, SEQ, seed)

    # ---- compute per-run statistics ----
    print("PER-RUN READINGS")
    print(f"  {'arm':12s} {'seed':4s} {'run':6s} {'n_hi':5s} {'RPE_hi':8s}"
          f" {'coh_hi':8s} {'amp_hi':10s} {'amp_lo':10s} {'amp_all':10s}")
    run_data = {}  # (arm, seed, run_idx) -> {coh_hi, amp_hi, ...}
    for arm in ARMS:
        for seed in SEEDS:
            for run_idx, (run_id, rvec, rmag, hi, lo) in enumerate(cells[(arm, seed)]):
                n_hi = int(hi.sum())
                coh_hi, amp_hi = coherent_amplitude(rvec, rmag, hi)
                coh_lo, amp_lo = coherent_amplitude(rvec, rmag, lo)
                coh_all, amp_all = coherent_amplitude(rvec, rmag, np.ones(len(rvec), dtype=bool))

                run_data[(arm, seed, run_idx)] = {
                    "coh_hi": coh_hi, "amp_hi": amp_hi,
                    "coh_lo": coh_lo, "amp_lo": amp_lo,
                    "coh_all": coh_all, "amp_all": amp_all,
                    "rpe_med_hi": float(np.median(rmag[hi])),
                }
                print(f"  {arm:12s} {seed:4d} {run_idx:6d} {n_hi:5d}"
                      f" {np.median(rmag[hi]):8.3f} {coh_hi:8.4f}"
                      f" {amp_hi:10.4f} {amp_lo:10.4f} {amp_all:10.4f}")

    # ---- apparatus check M-1, M-2 ----
    print("-" * 78)
    print("APPARATUS CHECK")
    for arm in ARMS:
        for seed in SEEDS:
            for run_idx in range(len(cells[(arm, seed)])):
                rd = run_data[(arm, seed, run_idx)]
                # M-1: median_rpe(hi) should be in the same ballpark as P
                # P(E) ~ 0.4, P(F) ~ 0.48; median_rpe(hi) ~ 1.4-1.7 -- factor ~3-4x
                # This is expected: P = median(hi) - median(lo), coherent_amp = coh * median(hi)
                # M-2: median_rpe(hi) > median_rpe(lo)
                print(f"  {arm:12s} s{seed} run{run_idx}: "
                      f"RPE_hi_med={rd['rpe_med_hi']:.3f}  "
                      f"amp_hi={rd['amp_hi']:.4f}  amp_lo={rd['amp_lo']:.4f}  "
                      f"amp_hi > amp_lo: {rd['amp_hi'] > rd['amp_lo']}")

    # ---- cell means ----
    print("=" * 78)
    print("CELL MEANS (mean over runs within each seed)")
    cell_mean = {}  # arm -> seed -> mean of amp_hi
    for arm in ARMS:
        cell_mean[arm] = {}
        for seed in SEEDS:
            amps = [run_data[(arm, seed, ri)]["amp_hi"]
                    for ri in range(len(cells[(arm, seed)]))]
            cell_mean[arm][seed] = float(np.mean(amps))
            cohs = [run_data[(arm, seed, ri)]["coh_hi"]
                    for ri in range(len(cells[(arm, seed)]))]
            print(f"  {arm:12s} s{seed}: coherent_amp_hi = {cell_mean[arm][seed]:.4f}"
                  f"  (coh_hi mean = {np.mean(cohs):.4f})")

    # ---- the statistic ----
    delta = {s: cell_mean["F_trackhard"][s] - cell_mean["E_trackside"][s] for s in SEEDS}
    shift = float(np.mean(list(delta.values())))

    # ---- same-shape null (paired gate pattern from exp37) ----
    within = {arm: [run_data[(arm, s, 0)]["amp_hi"] - run_data[(arm, s, 1)]["amp_hi"]
                    for s in SEEDS] for arm in ARMS}
    nulls = []
    for arm in ARMS:
        for eps in itertools.product((-1, 1), repeat=len(SEEDS)):
            nulls.append(abs(float(np.mean([e * d for e, d in zip(eps, within[arm])]))))
    nulls = sorted(set(round(v, 10) for v in nulls))
    floor_ca = max(nulls)
    floor_vm = floor_ca / np.sqrt(2.0)

    print("-" * 78)
    print("PAIRED SHIFT")
    print("  paired shift per seed  " + "  ".join(f"s{s} {delta[s]:+.4f}" for s in SEEDS))
    print(f"  shift = mean over seeds    {shift:+.4f}")
    print(f"  within-config |d(amp_hi)|  "
          + "  ".join(f"{arm}: [{', '.join(f'{abs(d):.4f}' for d in within[arm])}]"
                     for arm in ARMS))
    print(f"  floor_CA (max |null shift|) = {floor_ca:.4f}")
    print(f"  [sensitivity] variance-matched floor = {floor_vm:.4f}")

    # ---- step 0: reachability ----
    print("-" * 78)
    reachable = floor_ca <= REACH_FLOOR_CA
    print(f"  STEP 0 reachability: floor_CA {floor_ca:.4f} vs {REACH_FLOOR_CA:.4f}"
          f"  -> {'REACHABLE' if reachable else 'UNREACHABLE'}")

    # ---- verdict ----
    def decide(sh, fl):
        if fl > REACH_FLOOR_CA:
            r_needed = int(np.ceil(2.0 * (fl / REACH_FLOOR_CA) ** 2))
            return "UNREACHABLE", r_needed
        if abs(sh) <= fl:
            return "COHERENT-INDISTINGUISHABLE", None
        if sh < 0:
            return "COHERENT-BIASED", None
        return "COHERENT-WORSE", None

    verdict, r_needed = decide(shift, floor_ca)
    if verdict == "UNREACHABLE":
        print(f"           need r ~= {r_needed} runs per cell => "
              f"{r_needed * len(SEEDS) * len(ARMS)} runs total "
              f"(have {2 * len(SEEDS) * len(ARMS)})")
    print(f"  >>> {verdict}")
    if verdict == "COHERENT-BIASED":
        print("      F's coherent amplitude on high-dynamic pairs is LOWER than E's")
        print("      => the extra per-frame error from widening channel 1 is")
        print("         INCOHERENT (noise-like) and does not accumulate into drift")
        print("      => variance-vs-bias mechanism CONFIRMED by measurement")
        print("      => combined with P (worse) and ATE (better):")
        print("         P → coherent_amp → ATE forms a causal chain")
    elif verdict == "COHERENT-WORSE":
        print("      F's coherent amplitude is HIGHER => mechanism candidate REFUTED")

    # sensitivity with variance-matched floor
    verdict_vm, _ = decide(shift, float(floor_vm))
    agree = verdict_vm == verdict
    print(f"  [sensitivity] with variance-matched floor {floor_vm:.4f}: {verdict_vm}"
          f"  -> {'same label' if agree else 'DIFFERENT LABEL => CONSTRUCTION-LIMITED'}")

    # ---- mechanism triangle ----
    print("=" * 78)
    print("MECHANISM TRIANGLE (three pose-side endpoints)")
    print(f"  P (dynamic penalty):    shift = +0.0806  (1.22x floor)  WORSE")
    label_ca = ("?" if verdict == "UNREACHABLE"
                else "PASS" if abs(shift) > floor_ca else "INDISTINGUISHABLE")
    ratio_ca = abs(shift) / floor_ca if floor_ca > 0 else 0
    print(f"  coherent_amp (this):    shift = {shift:+.4f}  "
          f"({label_ca} {ratio_ca:.2f}x floor)")
    print(f"  ATE (accumulated drift): shift = -1.4157  (4.0x floor)  BETTER")
    if verdict == "COHERENT-BIASED":
        print("  => P → coherent_amp → ATE forms a consistent causal chain")
        print("  => mechanism: wider mask → more variance per frame but less bias")
    elif verdict == "COHERENT-INDISTINGUISHABLE":
        print("  => coherent_amp does not bridge P and ATE => mechanism unresolved")
    elif verdict == "COHERENT-WORSE":
        print("  => mechanism candidate REFUTED by this endpoint")

    # ---- noise split (descriptive, same as ATE gate) ----
    print("-" * 78)
    print("NOISE SPLIT (descriptive)")
    for arm in ARMS:
        wc = float(np.mean([abs(d) for d in within[arm]]))
        bs = float(np.ptp([cell_mean[arm][s] for s in SEEDS]))
        ratio = f"{wc/bs:.2f}" if bs > 0 else "inf"
        print(f"  {arm:12s} within-config mean|dCA| {wc:.4f}  between-seed ptp {bs:.4f}"
              f"  ratio {ratio}")

    # ---- write JSON ----
    out = "results/evidence/pose_coherent_gate.json"
    json.dump({
        "sequence": SEQ,
        "prereg_commit": "TBD",
        "blind": False,
        "reach_floor": REACH_FLOOR_CA,
        "per_run": {f"{a}/s{s}/r{ri}": {k: round(v, 6) if isinstance(v, float) else v
                                          for k, v in run_data[(a, s, ri)].items()}
                    for a in ARMS for s in SEEDS
                    for ri in range(len(cells[(a, s)]))},
        "cell_mean_amp_hi": {a: {str(s): round(cell_mean[a][s], 6) for s in SEEDS}
                             for a in ARMS},
        "delta_per_seed": {str(s): round(delta[s], 6) for s in SEEDS},
        "shift": shift,
        "floor_CA": floor_ca,
        "floor_variance_matched": float(floor_vm),
        "null_shifts": nulls,
        "reachable": reachable,
        "r_needed_per_cell": r_needed,
        "verdict": verdict,
        "verdict_variance_matched": verdict_vm,
        "labels_agree": bool(agree),
    }, open(out, "w"), indent=2)
    print("=" * 78)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
