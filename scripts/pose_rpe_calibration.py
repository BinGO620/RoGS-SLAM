#!/usr/bin/env python3
"""Calibration for a per-frame POSE-side estimand (exp37) -- runs BEFORE any threshold.

WHY THIS EXISTS
---------------
exp36 closed the mask-channel decomposition at its apparatus limit. On ``balloon`` the
trackside arm E sat between the two point predictions and E's own seed range (1.54 cm) ate
the 2.72 cm spacing, so the prereg's stop rule fired => INDETERMINATE. Adding seeds cannot
fix that: the gate compares a MEAN DIFFERENCE against a WITHIN-ARM RANGE, and a range only
grows with n (exp35 criterion #12). The only way out is a different ESTIMAND, which is a
NEW question and needs its own pre-registration (exp33 criterion #10).

The rendering side already narrowed where the answer can live: on ``balloon`` the static-band
PSNR of arms C / E / D is identical to two decimals (20.39), i.e. their MAPS are
indistinguishable. So if E-vs-D's 2.3 cm is real, it is carried by the POSE trajectory.

WHY RPE, AND NOT "ATE BUT PER-FRAME"
------------------------------------
Channel (1) -- the only thing E adds over D besides the T2 candidate set -- is a hard mask
inside the per-frame tracking solve (live only while ``tracking_itr < warmup_iters=10`` of
``tracking_itr_num=100``). It acts on the per-frame increment. RPE measures exactly that:

  * it is GAUGE-FREE (invariant to the global rigid alignment ATE needs), so no alignment
    coupling between arms;
  * it is a CONSECUTIVE DIFFERENCE of GT poses, so the ~10-19 mm per-frame GT nuisance that
    made P1c's GT-referenced endpoint unreadable largely cancels (that nuisance is a slowly
    varying bias; RPE differences it away). This is the structural reason P1/P1b/P1c failed
    and this does not inherit the failure;
  * it has ~N per-run samples instead of ATE's one.

WHAT THIS SCRIPT MUST NOT DO
----------------------------
It must not look at arm E. E is the treatment; its reading belongs after the prereg is
committed. ``ARMS_CALIB`` therefore excludes it and ``_assert_no_treatment_arm`` fails loudly
if anything reintroduces it. The floors and the reachability computed here are what the
prereg is then allowed to condition its thresholds on (exp32 criteria #3 and #4).

FRAMES ARE NOT INDEPENDENT
--------------------------
Per-frame RPE within one run is autocorrelated, so a paired test over ~440 "samples" would
manufacture significance. This script therefore does not assume any parametric null: it
measures the null EMPIRICALLY from run pairs that differ in nothing at all --
same config, same seed, run twice -- and (separately labelled) from cross-campaign repeats
of the same config. Whatever autocorrelation does to the statistic, it does to the null too.

Usage:  conda run -n monogs-ours python scripts/pose_rpe_calibration.py
"""

import csv
import glob
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

# ---------------------------------------------------------------- arms (E EXCLUDED)
# arm -> list of (root-relative glob) in priority order; {seed} substituted.
ARMS_CALIB = {
    "A_eboth_T2":  ["results/runs/T2/T2-QUOTA-3090/eboth_{seq}_seed{seed}"],
    "A_eboth_PBA": ["results/runs/PBA/eboth_{seq}_seed{seed}"],
    "B_insoff":    ["results/runs/PBA/pba_tracking_only_{seq}_seed{seed}"],
    "C_mapoff":    ["results/runs/PBA/pba_mapping_off_{seq}_3090_seed{seed}",
                    "results/runs/PBA/pba_mapping_off_{seq}_seed{seed}"],
    "D_maskfree":  ["results/runs/T2/T2-QUOTA-3090/control_maskfree_{seq}_seed{seed}",
                    "results/runs/PBA/control_maskfree_{seq}_seed{seed}"],
}
TREATMENT_ARM_MARKERS = ("trackside",)   # must never appear in calibration
SEQUENCES = ("balloon", "f3_wk_xyz", "pt1")
SEEDS = (0, 1, 2)

GTMC_SEQ_DIR = "/data/Datasets/Bonn/rgbd_bonn_{seq}"
# run-dir sequence token -> dataset dir token. f3_wk_xyz ships 0 GTMC masks, so the
# covariate -- and therefore the penalty estimand -- does not exist on that sequence.
GTMC_SEQ_DIRNAME = {"balloon": "balloon", "pt1": "person_tracking"}


def _assert_no_treatment_arm():
    for arm, pats in ARMS_CALIB.items():
        for p in pats:
            for marker in TREATMENT_ARM_MARKERS:
                if marker in p or marker in arm:
                    raise AssertionError(
                        f"calibration must not read the treatment arm: {arm} -> {p}"
                    )


# ---------------------------------------------------------------- trajectory + RPE
def _load_runs(pattern):
    """[(run_id, trj_path)] for every timestamped run under a run dir, sorted by run_id.

    A run dir can hold MORE THAN ONE run: exp36 found four balloon dirs with the same
    config+seed executed twice. Those repeats are the whole point here -- they are the
    cleanest possible null -- so this returns all of them instead of silently taking one.
    """
    out = []
    for outer in sorted(glob.glob(pattern)):
        for trj in sorted(glob.glob(os.path.join(outer, "**", "plot",
                                                 "trj_full_final.json"), recursive=True)):
            run_id = os.path.basename(os.path.dirname(os.path.dirname(trj)))
            out.append((run_id, trj))
    return out


def _poses(trj_path):
    with open(trj_path) as fh:
        d = json.load(fh)
    assert d["trajectory_protocol_version"] == "full-estimated-v1", d.get(
        "trajectory_protocol_version")
    est = [np.asarray(m, dtype=np.float64) for m in d["trj_est"]]
    gt = [np.asarray(m, dtype=np.float64) for m in d["trj_gt"]]
    return d["trj_id"], est, gt


def _evo_metrics(est, gt):
    """Per-pair RPE (cm) and the two RMSEs, built EXACTLY as utils/eval_utils.py does.

    ``trj_full_final.json`` stores the very lists fed to ``_evaluate_trajectories``, so this
    reproduces the shipped ``ate_rmse_cm`` / ``rpe_trans_rmse_cm`` rather than inventing a
    second caliper. The equality is checked per run (the faithfulness anchor the
    ``--fast`` rendering batches could not get).
    """
    from evo.core import metrics, trajectory
    from evo.core.trajectory import PosePath3D

    traj_ref = PosePath3D(poses_se3=gt)
    traj_est = PosePath3D(poses_se3=est)
    traj_est_aligned = trajectory.align_trajectory(traj_est, traj_ref, correct_scale=False)

    ape = metrics.APE(metrics.PoseRelation.translation_part)
    ape.process_data((traj_ref, traj_est_aligned))
    rpe = metrics.RPE(metrics.PoseRelation.translation_part)
    rpe.process_data((traj_ref, traj_est_aligned))
    return (np.asarray(rpe.error, dtype=np.float64) * 100.0,
            ape.get_all_statistics()["rmse"] * 100.0,
            rpe.get_all_statistics()["rmse"] * 100.0)


def _csv_rows(outer_pattern):
    """{run_id: {ate, rpe}} from tables/tracking_raw.csv across matching run dirs."""
    out = {}
    for outer in sorted(glob.glob(outer_pattern)):
        path = os.path.join(outer, "tables", "tracking_raw.csv")
        if not os.path.isfile(path):
            continue
        for row in csv.DictReader(open(path)):
            rid = row.get("run_id")
            try:
                out[rid] = {"ate": float(row["ate_rmse_cm"]),
                            "rpe": float(row["rpe_trans_rmse_cm"])}
            except (KeyError, TypeError, ValueError):
                pass
    return out


# ---------------------------------------------------------------- dynamic-area covariate
def _dyn_area(seq, cache="results/evidence/pose_rpe_dynarea.json"):
    """{frame index -> held-out GT dynamic-area fraction}, or None with no GTMC masks.

    Frame indices come from the project's own caliper (``t3_semalpha_verdict.stem_index``,
    which keys on the depth stem that both the dataset loader and the mask builder use), NOT
    from sorted-filename order: balloon has 438 masks for 439 frames because GTMC needs
    neighbours +/-2, so position i in a sorted listing is not frame i.
    """
    if seq not in GTMC_SEQ_DIRNAME:
        return None
    seq_dir = GTMC_SEQ_DIR.format(seq=GTMC_SEQ_DIRNAME[seq])
    if not os.path.isdir(os.path.join(seq_dir, "dynamic_mask_gtmc")):
        return None
    if os.path.isfile(cache):
        blob = json.load(open(cache))
        if seq in blob:
            return {int(k): v for k, v in blob[seq].items()}
    import cv2
    from scripts.t3_semalpha_verdict import stem_index
    frac = {}
    for idx, path in sorted(stem_index(seq_dir).items()):
        m = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if m is not None:
            frac[int(idx)] = float((m > 0).mean())
    blob = json.load(open(cache)) if os.path.isfile(cache) else {}
    blob[seq] = frac
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(blob, open(cache, "w"))
    return frac


def _pair_area(frac, n_pairs):
    """Covariate for RPE pair i (frames i, i+1) = max of the two frames' dynamic area.

    ``max`` because the pair's relative pose is corrupted if EITHER endpoint is corrupted.
    Pairs missing a mask at either endpoint get NaN and are reported, never silently dropped.
    """
    out = np.full(n_pairs, np.nan)
    for i in range(n_pairs):
        a, b = frac.get(i), frac.get(i + 1)
        if a is not None and b is not None:
            out[i] = max(a, b)
    return out


# ---------------------------------------------------------------- collect
def collect():
    runs = {}          # (seq, arm, seed) -> [(run_id, rpe_per_frame, ate, rpe_rmse, n)]
    anchor = []        # (label, ate_recomputed, ate_csv, rpe_recomputed, rpe_csv)
    for seq in SEQUENCES:
        for arm, pats in ARMS_CALIB.items():
            for seed in SEEDS:
                got = []
                for pat in pats:
                    p = pat.format(seq=seq, seed=seed)
                    hits = _load_runs(p)
                    if not hits:
                        continue
                    csv_by_id = _csv_rows(p)
                    for run_id, trj in hits:
                        _, est, gt = _poses(trj)
                        rpe_pf, ate_rms, rpe_rms = _evo_metrics(est, gt)
                        ref = csv_by_id.get(run_id)
                        anchor.append((f"{seq}/{arm}/s{seed}/{run_id}", ate_rms,
                                       ref["ate"] if ref else None, rpe_rms,
                                       ref["rpe"] if ref else None))
                        got.append((run_id, rpe_pf, ate_rms, rpe_rms, len(est)))
                    break        # first root that has the arm wins (exp36 convention)
                if got:
                    runs[(seq, arm, seed)] = got
    return runs, anchor


def penalty(rpe, st):
    """Within-run dynamic penalty: median RPE(high dynamic) - median RPE(low dynamic).

    The registered PRIMARY (results/evidence/pose_trackside_prereg.md §3). It is a contrast
    INSIDE one run, so any arm-level global offset (map quality, overall drift) differences
    out and what survives is the dynamics-specific part of the tracking error.
    """
    return float(np.median(rpe[st["hi"][:len(rpe)]]) - np.median(rpe[st["lo"][:len(rpe)]]))


def split_plain(a, _step):
    ok = np.isfinite(a)
    thr = float(np.nanmedian(a[ok]))
    return {"lo": ok & (a <= thr), "hi": ok & (a > thr)}


def split_motion_matched(a, step, nbins=4):
    """Split on dynamic area WITHIN GT-step quartiles, so hi and lo are speed-matched.

    High-dynamic frames also carry faster camera motion (balloon corr = +0.210, pt1 much
    worse), so a plain median split partly scores speed sensitivity. On pt1 the plain gap
    +0.1925 collapses to +0.0716 once speed is matched -- which is why this, not plain, is
    the registered primary.
    """
    ok = np.isfinite(a)
    lo = np.zeros_like(ok)
    hi = np.zeros_like(ok)
    edges = np.nanpercentile(step[ok], np.linspace(0, 100, nbins + 1))
    for b in range(nbins):
        upper = (step <= edges[b + 1]) if b == nbins - 1 else (step < edges[b + 1])
        inb = ok & (step >= edges[b]) & upper
        if inb.sum() < 4:
            continue
        t = float(np.nanmedian(a[inb]))
        lo |= inb & (a <= t)
        hi |= inb & (a > t)
    return {"lo": lo, "hi": hi}


def gt_step_cm(gt, n):
    """GT inter-frame translation magnitude (cm) for RPE pair i, i.e. frames i -> i+1."""
    return np.asarray([np.linalg.norm((np.linalg.inv(gt[i]) @ gt[i + 1])[:3, 3])
                       for i in range(len(gt) - 1)])[:n] * 100.0


def _gt_of(_runs, seq):
    """GT poses for a sequence (identical across arms -- it is the dataset's ground truth)."""
    for pats in ARMS_CALIB.values():
        for pat in pats:
            for seed in SEEDS:
                hits = _load_runs(pat.format(seq=seq, seed=seed))
                if hits:
                    return _poses(hits[0][1])[2]
    raise RuntimeError(f"no trajectory found for {seq}")


# ---------------------------------------------------------------- the statistic
def stat(rpe_x, rpe_y, strata=None):
    """Paired per-frame RPE contrast between two runs of the SAME sequence.

    Median difference (cm) and per-frame sign rate -- median and sign, never the mean,
    because RPE is heavy-tailed and one tracking slip would otherwise decide the number.
    ``strata`` is an optional {name: boolean pair-mask} from the method-independent dynamic
    area covariate; the same statistic is returned per stratum so the null can be sized on
    the very stratum the verdict will be read on (exp33 criterion #8: a gate must be
    reachable ON THE SCALE IT IS APPLIED).
    """
    n = min(len(rpe_x), len(rpe_y))
    d = rpe_x[:n] - rpe_y[:n]
    out = {"all": (float(np.median(d)), float(np.mean(d > 0)), n)}
    for name, m in (strata or {}).items():
        mm = m[:n]
        out[name] = ((float(np.median(d[mm])), float(np.mean(d[mm] > 0)), int(mm.sum()))
                     if mm.any() else (float("nan"), float("nan"), 0))
    return out


def _strata(seq, n_pairs):
    """{'lo': mask, 'hi': mask} from the held-out dynamic area, split at its own median.

    Method-independent and identical for every arm: the split is a property of the frozen
    GTMC annotation, never of any run's output.
    """
    frac = _dyn_area(seq)
    if frac is None:
        return {}, None
    area = _pair_area(frac, n_pairs)
    ok = np.isfinite(area)
    if not ok.any():
        return {}, None
    thr = float(np.nanmedian(area[ok]))
    return {"lo": ok & (area <= thr), "hi": ok & (area > thr)}, (area, thr)


def _fmt(s, keys):
    return "  ".join(
        f"{k} {s[k][0]:+.4f}/{s[k][1]:.3f}" if k in s and s[k][2] else f"{k} --" for k in keys
    )


def main():
    _assert_no_treatment_arm()
    runs, anchor = collect()

    # ---- apparatus check 0: does our caliper reproduce the shipped numbers? ----
    print("=" * 78)
    print("ANCHOR: recomputed vs tracking_raw.csv (same construction as eval_utils)")
    bad = miss = 0
    worst = 0.0
    for label, a_r, a_c, r_r, r_c in anchor:
        if a_c is None or r_c is None:
            miss += 1
            continue
        da, dr = abs(a_r - a_c), abs(r_r - r_c)
        worst = max(worst, da, dr)
        if da > 5e-3 or dr > 5e-3:
            bad += 1
            print(f"  MISMATCH {label}: ate {a_r:.4f} vs {a_c:.4f} | "
                  f"rpe {r_r:.4f} vs {r_c:.4f}")
    print(f"  {len(anchor)} runs | mismatches={bad} | no-csv-row={miss} | "
          f"max|delta|={worst:.5f} cm")

    # ---- fixed, method-independent strata per sequence ----
    strata, cov = {}, {}
    for seq in SEQUENCES:
        any_run = next((v for k, v in runs.items() if k[0] == seq), None)
        if any_run is None:
            continue
        n_pairs = len(any_run[0][1])
        strata[seq], cov[seq] = _strata(seq, n_pairs)
    KEYS = ("all", "lo", "hi")

    print("=" * 78)
    print("DOSE-RESPONSE COVARIATE (held-out GTMC dynamic area, method-independent)")
    for seq in SEQUENCES:
        if cov.get(seq) is None:
            print(f"  {seq:10s} no GTMC masks -> strata UNAVAILABLE (overall read only)")
            continue
        area, thr = cov[seq]
        ok = np.isfinite(area)
        q = np.nanpercentile(area, [0, 25, 50, 75, 90, 100]) * 100
        print(f"  {seq:10s} pairs={len(area)} with-covariate={int(ok.sum())}"
              f"  area% p0/25/50/75/90/100 = " + "/".join(f"{v:.2f}" for v in q))
        print(f"             split at {thr * 100:.2f}%  ->  lo n={int(strata[seq]['lo'].sum())}"
              f"  hi n={int(strata[seq]['hi'].sum())}")

    # ---- the empirical null: pairs that differ in NOTHING ----
    print("=" * 78)
    print("NULL A -- same config, same seed, run twice (within one run dir)")
    null_a = {k: [] for k in KEYS}
    for (seq, arm, seed), got in sorted(runs.items()):
        if len(got) < 2:
            continue
        for i in range(len(got)):
            for j in range(i + 1, len(got)):
                s = stat(got[i][1], got[j][1], strata.get(seq))
                for k in KEYS:
                    if k in s and s[k][2]:
                        null_a[k].append(abs(s[k][0]))
                print(f"  {seq:10s} {arm:12s} s{seed} ATE {got[i][2]:6.2f}/{got[j][2]:6.2f}"
                      f" | {_fmt(s, KEYS)}")
    print("-" * 78)
    print("NULL B -- same config+seed, DIFFERENT campaign (T2 vs PBA eboth)")
    null_b = {k: [] for k in KEYS}
    for seq in SEQUENCES:
        for seed in SEEDS:
            a, b = runs.get((seq, "A_eboth_T2", seed)), runs.get((seq, "A_eboth_PBA", seed))
            if not a or not b:
                continue
            s = stat(a[0][1], b[0][1], strata.get(seq))
            for k in KEYS:
                if k in s and s[k][2]:
                    null_b[k].append(abs(s[k][0]))
            print(f"  {seq:10s} eboth  s{seed} ATE {a[0][2]:6.2f}/{b[0][2]:6.2f}"
                  f" | {_fmt(s, KEYS)}")
    print("-" * 78)
    print("NULL C -- same arm, DIFFERENT seed (unpaired reference, NOT the paired null)")
    null_c = {k: [] for k in KEYS}
    for seq in SEQUENCES:
        for arm in ARMS_CALIB:
            for i in SEEDS:
                for j in SEEDS:
                    if j <= i:
                        continue
                    a, b = runs.get((seq, arm, i)), runs.get((seq, arm, j))
                    if not a or not b:
                        continue
                    s = stat(a[0][1], b[0][1], strata.get(seq))
                    for k in KEYS:
                        if k in s and s[k][2]:
                            null_c[k].append(abs(s[k][0]))

    print("-" * 78)
    print("MEASURED FLOORS (|med_d|, cm) -- what a threshold may be conditioned on")
    for name, blob in (("A same-cfg+seed", null_a), ("B cross-campaign", null_b),
                       ("C cross-seed", null_c)):
        row = "  ".join(f"{k}: max {max(blob[k]):.4f} mean {np.mean(blob[k]):.4f} (n={len(blob[k])})"
                        for k in KEYS if blob[k])
        print(f"  {name:18s} {row}")

    # ---- positive control: the known total effect must be visible ----
    print("=" * 78)
    print("POSITIVE CONTROL -- D maskfree minus A eboth (the known 4-14x ATE effect)")
    for seq in SEQUENCES:
        for seed in SEEDS:
            a = runs.get((seq, "A_eboth_T2", seed)) or runs.get((seq, "A_eboth_PBA", seed))
            d = runs.get((seq, "D_maskfree", seed))
            if not a or not d:
                continue
            s = stat(d[0][1], a[0][1], strata.get(seq))
            print(f"  {seq:10s} s{seed} ATE {a[0][2]:6.2f}->{d[0][2]:6.2f}"
                  f" | {_fmt(s, KEYS)}")

    # ---- reachability arithmetic (criterion #4: compute it BEFORE registering) ----
    print("=" * 78)
    print("REACHABILITY -- can a trackside share be read at all?")
    for seq in SEQUENCES:
        tot = []
        for seed in SEEDS:
            a = runs.get((seq, "A_eboth_T2", seed)) or runs.get((seq, "A_eboth_PBA", seed))
            d = runs.get((seq, "D_maskfree", seed))
            if a and d:
                tot.append(stat(d[0][1], a[0][1], strata.get(seq)))
        if not tot:
            continue
        for k in KEYS:
            vals = [t[k][0] for t in tot if k in t and t[k][2]]
            if not vals:
                continue
            fl = max(null_a[k]) if null_a[k] else float("nan")
            print(f"  {seq:10s} {k:3s} total effect {np.mean(vals):+.4f} cm | floor(A) "
                  f"{fl:.4f} | effect/floor {abs(np.mean(vals)) / fl:.1f}x"
                  f" | share readable above floor >= {fl / abs(np.mean(vals)) * 100:.0f}%")

    # ---- candidate PRIMARY: the within-run dynamic penalty ----
    # P(X) = median RPE on high-dynamic pairs - median RPE on low-dynamic pairs, computed
    # INSIDE one run. It differences out any arm-level global offset (map quality, overall
    # drift), so what survives is the DYNAMICS-SPECIFIC part of the tracking error -- which
    # is the only part a dynamic-masking channel can be responsible for. The paired
    # cross-arm median above cannot separate those two.
    print("=" * 78)
    print("CANDIDATE PRIMARY -- within-run dynamic penalty P = med RPE(hi) - med RPE(lo)")

    for seq in SEQUENCES:
        if not strata.get(seq):
            print(f"  {seq:10s} strata unavailable -> penalty UNDEFINED on this sequence")
            continue
        for arm in ("A_eboth_T2", "A_eboth_PBA", "B_insoff", "C_mapoff", "D_maskfree"):
            vals = []
            for seed in SEEDS:
                got = runs.get((seq, arm, seed))
                if not got:
                    continue
                vals.append([penalty(g[1], strata[seq]) for g in got])
            if vals:
                flat = [v for vv in vals for v in vv]
                print(f"  {seq:10s} {arm:12s} P per seed "
                      + " ".join("/".join(f"{v:+.4f}" for v in vv) for vv in vals)
                      + f"   | mean {np.mean(flat):+.4f}")
    pnull = []
    for (seq, arm, seed), got in sorted(runs.items()):
        if len(got) < 2 or not strata.get(seq):
            continue
        ps = [penalty(g[1], strata[seq]) for g in got]
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                pnull.append(abs(ps[i] - ps[j]))
    if pnull:
        print(f"  -> |dP| null (same cfg+seed, n={len(pnull)}): max {max(pnull):.4f} "
              f"mean {np.mean(pnull):.4f} cm")

    # ---- confound check: is 'high dynamic area' also 'fast camera motion'? ----
    print("=" * 78)
    print("CONFOUND -- does the covariate track GT camera speed rather than dynamics?")
    for seq in SEQUENCES:
        if cov.get(seq) is None:
            continue
        area, _thr = cov[seq]
        gt = _gt_of(runs, seq)
        step = gt_step_cm(gt, len(area))
        ok = np.isfinite(area)
        r = float(np.corrcoef(area[ok], step[:len(area)][ok])[0, 1])
        st = strata[seq]
        print(f"  {seq:10s} corr(area, GT step) = {r:+.3f} | GT step cm: "
              f"lo med {np.median(step[st['lo']]):.3f}  hi med {np.median(step[st['hi']]):.3f}"
              f"  (n={int(ok.sum())})")

    # ---- confound control + invalidation control for the penalty ----
    # (a) MOTION-MATCHED: high-dynamic pairs also carry ~32% faster GT camera steps, so a
    #     plain median split partly measures speed sensitivity. Splitting on dynamic area
    #     WITHIN GT-step quartiles makes hi and lo nearly speed-identical, so what remains
    #     is dynamics. The confound is common to all arms and would cancel in a cross-arm
    #     comparison anyway; this checks that claim instead of asserting it.
    # (b) ROLLED: the same area series shifted in time. Same distribution, wrong timing =>
    #     the arm separation MUST collapse. Without this, "P separates the arms" could be
    #     any property of the frame ordering rather than of the dynamic pixels.
    print("=" * 78)
    print("PENALTY CONTROLS -- motion-matched split, and a time-rolled invalidation null")

    penalty_controls = {}
    for seq in SEQUENCES:
        if cov.get(seq) is None:
            continue
        area, _ = cov[seq]
        gt = _gt_of(runs, seq)
        step = gt_step_cm(gt, len(area))
        variants = {"plain": split_plain(area, step),
                    "motion_matched": split_motion_matched(area, step)}
        for k, off in (("rolled+109", 109), ("rolled+219", 219), ("rolled+329", 329)):
            variants[k] = split_plain(np.roll(area, off), step)
        for vname, st in variants.items():
            groups = {}
            for arm in ("A_eboth_T2", "A_eboth_PBA", "B_insoff", "C_mapoff", "D_maskfree"):
                vv = [penalty(g[1], st) for seed in SEEDS
                      for g in (runs.get((seq, arm, seed)) or [])]
                if vv:
                    groups[arm] = vv
            on = [v for a, vv in groups.items() if a.startswith(("A_", "B_")) for v in vv]
            off_ = [v for a, vv in groups.items() if a.startswith(("C_", "D_")) for v in vv]
            if not on or not off_:
                continue
            penalty_controls[f"{seq}/{vname}"] = {
                "maskON_mean": float(np.mean(on)), "maskOFF_mean": float(np.mean(off_)),
                "gap": float(np.mean(off_) - np.mean(on)),
                "min_gap": float(min(off_) - max(on))}
            # |dP| null under THIS split (a threshold must be sized on its own caliper)
            vnull = []
            for (s2, _arm, _sd), got in sorted(runs.items()):
                if s2 != seq or len(got) < 2:
                    continue
                ps = [penalty(g[1], st) for g in got]
                for i in range(len(ps)):
                    for j in range(i + 1, len(ps)):
                        vnull.append(abs(ps[i] - ps[j]))
            fl = max(vnull) if vnull else float("nan")
            penalty_controls[f"{seq}/{vname}"]["floor_max"] = fl
            penalty_controls[f"{seq}/{vname}"]["per_arm"] = {
                a: [round(v, 4) for v in vv] for a, vv in groups.items()}
            print(f"  {seq:9s} {vname:14s} maskON P {np.mean(on):+.4f}  maskOFF P "
                  f"{np.mean(off_):+.4f}  gap {np.mean(off_) - np.mean(on):+.4f}"
                  f"  min-gap {min(off_) - max(on):+.4f}  floor {fl:.4f}"
                  f"  gap/floor {abs(np.mean(off_) - np.mean(on)) / fl:.1f}x"
                  f"  | step lo/hi {np.median(step[st['lo']]):.3f}/"
                  f"{np.median(step[st['hi']]):.3f}")
            if not vname.startswith("rolled"):
                for a, vv in groups.items():
                    print(f"      {vname:14s} {a:12s} "
                          + " ".join(f"{v:+.4f}" for v in vv)
                          + f"   mean {np.mean(vv):+.4f}")

    out = "results/evidence/pose_rpe_calibration.json"
    json.dump({"null_a": null_a, "null_b": null_b, "null_c": null_c,
               "penalty_null": pnull, "penalty_controls": penalty_controls,
               "anchor_max_abs_delta": worst, "anchor_n": len(anchor),
               "anchor_mismatches": bad}, open(out, "w"), indent=2)
    print("=" * 78)
    print(f"wrote {out}")
    print("NOTE: arm E (trackside) was NOT read -- it is the treatment (see module docstring).")

    out = "results/evidence/pose_rpe_calibration.json"
    json.dump({"null_a": null_a, "null_b": null_b, "null_c": null_c,
               "anchor_max_abs_delta": worst, "anchor_n": len(anchor),
               "anchor_mismatches": bad},
              open(out, "w"), indent=2)
    print("=" * 78)
    print(f"wrote {out}")
    print("NOTE: arm E (trackside) was NOT read -- it is the treatment (see module docstring).")


if __name__ == "__main__":
    main()
