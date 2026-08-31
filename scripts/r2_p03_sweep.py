#!/usr/bin/env python
"""R2-P03-SWEEP: can a harder-pruned arm A reach arm B's operating point?

Why this campaign exists
------------------------
R2-P02's three pre-registered gates all failed; ``02-method.md`` §P0 runs the prereg §6
fallback, whose load-bearing number is the compactness corollary: **arm B (deferred) builds
a 55% smaller map than arm A (insert-then-prune) at fidelity that differs by 0.00x its own
noise**. External review named the single most likely rejection reason:

    "deferred insertion trivially creates fewer Gaussians, but the authors do not show that
     the removed capacity corresponds specifically to dynamic contamination rather than
     general under-reconstruction or an **under-tuned pruning baseline**."

The second half of that sentence is a measurable claim, and this script measures it. Arm A is
swept along ITS OWN prune/admission knobs until its Gaussian count brackets arm B's ~11.3k,
under the same frozen RGD trajectory the pre-flight used (``Oracle.pose_file``,
``cam_rot_delta = cam_trans_delta = 0``), and the resulting rate-distortion ladder is compared
against B's single operating point.

    dominated  => "just tune prune harder" is a valid attack; the compactness headline falls
                  (narrative D), and we would rather learn that here than from a reviewer.
    not dominated => the attack is answered with data.

Non-preregistered (``02-method.md`` marks it as such, and the paper must too). It does not
touch the H1 record: no gate here can rehabilitate or worsen a pre-registered checkpoint.

What is pre-declared, before any GPU time (this file is committed before the first run)
---------------------------------------------------------------------------------------
* the ladder (``LEVELS``) and its knob values, pinned by ``tests/test_r2_p03_sweep_configs.py``;
* the decision family and its non-inferiority margins (``scripts/r2_p03_sweep_readout.py``:
  PRIMARY depth 1.56 cm, vacated PSNR 0.28 dB -- one self-tracked null sd each, from
  ``results/evidence/r2_p02_e2_metric_calibration.txt``);
* the dominance rule (readout ``DOMINANCE``): fewer Gaussians on the mean AND degradation
  within margin on both decision metrics;
* the seed-promotion rule for ``--phase confirm``: **rate only**, never fidelity, so the
  ladder cannot be selected on the outcome it is being judged by.

Anchors are re-run inside this campaign rather than reused from
``R2-P02-PREFLIGHT-rgd``. The pre-flight's own arm-A note records a measured 1.5-2.0 cm
cross-campaign shift on this arm with its config unchanged -- the same order as the 1.56 cm
non-inferiority margin, so a cross-campaign fidelity comparison could manufacture or mask a
dominance verdict. Both anchors and every rung therefore run at one commit, one harness, one
machine.

Phases
------
    python scripts/r2_p03_sweep.py --phase dry       # E0, no GPU
    python scripts/r2_p03_sweep.py --phase anchors   # A0 + B x seeds 0,1,2   (6 runs)
    python scripts/r2_p03_sweep.py --phase pilot     # 6 rungs x seed 0       (6 runs)
    python scripts/r2_p03_sweep.py --phase confirm   # promoted rungs x seeds 1,2
    python scripts/r2_p03_sweep.py --phase report    # no GPU (delegates to the readout)

GO/KILL and narrative remain the user's (prereg §9). This script prints measurements and
mechanical gate verdicts only.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.check_arm_activity import _load_config, _resolve_run_dir, check_run  # noqa: E402
from scripts.r2_p02_preflight_pose import (  # noqa: E402  -- same metric 口径 as the pre-flight
    PY,
    RGD_ATE_CM,
    RGD_ATE_TOL_CM,
    parse_run,
)

OUT_DIR = "results/runs/R2-P03/R2-P03-SWEEP"
RESULTS = "sweep_results.jsonl"

OA = "configs/rgbd/experiments/r2_oracle_admission"
SW = "configs/rgbd/experiments/r2_p03_sweep"

# --- the ladder -----------------------------------------------------------------------
# Anchors carry NO knobs: they are the campaign arms verbatim, so their rows are directly
# comparable to R2-P02-PREFLIGHT-rgd as a cross-campaign sanity check while the in-campaign
# rows do the actual work.
ANCHORS = {
    "A0_prune": (f"{OA}/oracle_prune_balloon.yaml", {}),
    "B_deferred": (f"{OA}/oracle_deferred_balloon.yaml", {}),
}

# level -> (config, {resolved config key: value the run must have used})
# Single source of truth: tests/test_r2_p03_sweep_configs.py imports this dict and pins the
# resolved-config diff of every rung against it; run_one re-checks it against the config each
# run actually dumped, so a rung that silently fell back to the arm-A default is caught in the
# record rather than in the Pareto table.
LEVELS = {
    "S1_ttl2": (f"{SW}/sweep_s1_ttl2_balloon.yaml", {"DeferredCommit.ttl_keyframes": 2}),
    "S2_ttl1": (f"{SW}/sweep_s2_ttl1_balloon.yaml", {"DeferredCommit.ttl_keyframes": 1}),
    "S3_cap1000": (
        f"{SW}/sweep_s3_cap1000_balloon.yaml",
        {"DeferredCommit.max_candidates_per_keyframe": 1000},
    ),
    "S4_gth080": (f"{SW}/sweep_s4_gth080_balloon.yaml", {"Training.gaussian_th": 0.8}),
    "S5_gth090": (f"{SW}/sweep_s5_gth090_balloon.yaml", {"Training.gaussian_th": 0.9}),
    "S6_maxpress": (
        f"{SW}/sweep_s6_maxpress_balloon.yaml",
        {
            "DeferredCommit.ttl_keyframes": 1,
            "Training.gaussian_th": 0.9,
            "opt_params.densify_grad_threshold": 0.0005,
        },
    ),
}
ALL_ARMS = {**ANCHORS, **LEVELS}

# Candidate-side rungs must move the candidate ledger; native-prune rungs need not (they act
# after insertion). Checked as a mechanism signature, reported not fatal -- an inert rung is
# still a legitimate data point, but it must never be read as "prune tuned harder, no effect".
CANDIDATE_SIDE = {"S1_ttl2", "S2_ttl1", "S3_cap1000", "S6_maxpress"}
LEDGER_KEYS = (
    "candidate_total",
    "candidate_overflow",
    "promoted",
    "rejected",
    "expired",
    "pruned",
    "pending_peak",
    "pending_final",
    "immediate_insert",
    "prune_immediate_insert",
)

# How many rungs get seeds 1 and 2 in --phase confirm. Rate-only promotion (see _promote).
CONFIRM_LEVELS = 4


def log(msg, out_dir=OUT_DIR):
    line = f"[{time.strftime('%F %T')}] {msg}"
    print(line, flush=True)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "sweep.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _flat(node, prefix=""):
    out = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(_flat(value, f"{prefix}{key}." if prefix else f"{key}."))
        return out
    out[prefix[:-1]] = node
    return out


def read_ledger(run_root):
    """The deferred-commit candidate accounting the run wrote (mechanism evidence)."""
    resolved = _resolve_run_dir(run_root)
    if resolved is None:
        return {}
    path = os.path.join(resolved, "deferred_commit_summary.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        summary = json.load(f)
    return {k: summary.get(k) for k in LEDGER_KEYS}


def check_config_echo(run_root, knobs):
    """G2: did the run actually use the knob values this rung declares?

    Reads the config the run dumped next to its own artifacts, not the yaml on disk -- the
    only place that proves what the process resolved. Returns (ok, detail).
    """
    resolved = _resolve_run_dir(run_root)
    if resolved is None:
        return False, "no resolved config.yml under the run root"
    config = _load_config(resolved)
    if config is None:
        return False, "config.yml unreadable"
    flat = _flat(config)
    bad = []
    for key, expected in knobs.items():
        got = flat.get(key)
        if got is None or float(got) != float(expected):
            bad.append(f"{key}={got!r} (want {expected!r})")
    if bad:
        return False, "; ".join(bad)
    return True, ("no knobs (anchor)" if not knobs else
                  "; ".join(f"{k}={v}" for k, v in knobs.items()))


def load_records(out_dir=OUT_DIR):
    path = os.path.join(out_dir, RESULTS)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def done_pairs(out_dir=OUT_DIR):
    """(arm, seed) pairs already on disk with exit 0 -- so a phase can be resumed."""
    return {(r["arm"], r["seed"]) for r in load_records(out_dir) if r.get("exit") == 0}


def run_one(arm, seed, out_dir=OUT_DIR, dry_run=False):
    config, knobs = ALL_ARMS[arm]
    run_root = os.path.join(out_dir, f"{arm}_seed{seed}")
    console = os.path.join(out_dir, f"{arm}_seed{seed}.consolelog")
    cmd = [PY, "slam.py", "--config", config, "--eval",
           "--seed", str(seed), "--results-root", run_root]
    if dry_run:
        print(f"  {' '.join(cmd)}")
        return {"arm": arm, "seed": seed, "cmd": cmd, "dry_run": True}

    log(f"START {arm} seed{seed} knobs={knobs or '-'} -> {run_root}", out_dir)
    env = dict(os.environ)
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    env.pop("PYTORCH_CUDA_ALLOC_CONF", None)  # crashes MonoGS multiprocess CUDA sharing
    started = time.time()
    with open(console, "w", encoding="utf-8") as log_file:
        code = subprocess.call(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=env)
    minutes = (time.time() - started) / 60.0

    metrics = parse_run(run_root)
    verdict, detail = check_run(run_root)
    echo_ok, echo_detail = check_config_echo(run_root, knobs)
    ate = metrics.get("ate_rmse_cm")
    pose_frozen = ate is not None and abs(ate - RGD_ATE_CM) <= RGD_ATE_TOL_CM
    record = {
        "arm": arm, "seed": seed, "config": config, "knobs": knobs,
        "exit": code, "minutes": round(minutes, 1), "run_dir": run_root,
        "pose_frozen": pose_frozen,
        "config_echo_ok": echo_ok, "config_echo": echo_detail,
        "activity_verdict": verdict, "activity_detail": detail,
        "metrics": metrics, "candidate_ledger": read_ledger(run_root),
    }
    with open(os.path.join(out_dir, RESULTS), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    log(f"END   {arm} seed{seed} exit={code} {minutes:.1f}min "
        f"G={metrics.get('refined_num_gaussians')} ate={ate} "
        f"vac_depth={metrics.get('static_vacated_depth_l1_pen_cm')} "
        f"vac_psnr={metrics.get('static_vacated_psnr')} "
        f"pose_frozen={pose_frozen} config_echo={'ok' if echo_ok else 'FAIL: ' + echo_detail}",
        out_dir)
    return record


# ---------------------------------------------------------------------------
# Gates. Every one is a HARNESS assertion (did the run do what the config says),
# never a hypothesis assertion -- a rung that prunes hard and loses fidelity is a
# RESULT, and must not abort the campaign.
# ---------------------------------------------------------------------------

def gate_records(records, out_dir=OUT_DIR, fatal=True):
    ok = True
    for r in records:
        tag = f"{r['arm']}/s{r['seed']}"
        if r["exit"] != 0:
            log(f"GATE FAIL {tag}: exit={r['exit']}", out_dir)
            ok = False
        if not r["pose_frozen"]:
            log(f"GATE FAIL {tag}: ate={r['metrics'].get('ate_rmse_cm')} != "
                f"{RGD_ATE_CM} ±{RGD_ATE_TOL_CM} -- trajectory NOT frozen", out_dir)
            ok = False
        if not r["config_echo_ok"]:
            log(f"GATE FAIL {tag}: knobs did not take effect -- {r['config_echo']}", out_dir)
            ok = False
        support = r["metrics"].get("static_vacated_support_px_mean")
        frames = r["metrics"].get("static_vacated_frames_scored")
        if not support or not frames:
            log(f"GATE FAIL {tag}: vacated support={support} frames={frames}", out_dir)
            ok = False
        if r["metrics"].get("refined_num_gaussians") is None:
            log(f"GATE FAIL {tag}: no refined_num_gaussians -- nothing to place on the "
                f"rate axis", out_dir)
            ok = False
        if ok:
            log(f"GATE ok   {tag}: G={r['metrics'].get('refined_num_gaussians')} "
                f"ate={r['metrics'].get('ate_rmse_cm')} knobs[{r['config_echo']}]", out_dir)
    if not ok and fatal:
        log("==== ABORT: a gate failed. A sweep on a harness that did not do what the "
            "config says answers nothing. ====", out_dir)
    return ok


def mechanism_report(out_dir=OUT_DIR):
    """Report-only: did the candidate-side rungs actually move the candidate ledger?"""
    records = load_records(out_dir)
    base = [r for r in records if r["arm"] == "A0_prune"]
    if not base:
        return
    ref = {k: statistics.mean([r["candidate_ledger"].get(k) or 0 for r in base])
           for k in LEDGER_KEYS}
    for level in LEVELS:
        rows = [r for r in records if r["arm"] == level]
        if not rows:
            continue
        got = {k: statistics.mean([r["candidate_ledger"].get(k) or 0 for r in rows])
               for k in LEDGER_KEYS}
        moved = [k for k in ("candidate_total", "pending_final", "expired", "pruned")
                 if abs(got[k] - ref[k]) > 0.02 * max(ref[k], 1.0)]
        note = "moved: " + ",".join(moved) if moved else "candidate ledger UNCHANGED vs A0"
        if level in CANDIDATE_SIDE and not moved:
            note += "  <-- candidate-side rung with an inert ledger: read with care"
        log(f"MECH {level}: pending_final {ref['pending_final']:.0f} -> "
            f"{got['pending_final']:.0f}, candidate_total {ref['candidate_total']:.0f} -> "
            f"{got['candidate_total']:.0f}, pruned {ref['pruned']:.0f} -> {got['pruned']:.0f} "
            f"[{note}]", out_dir)


def _promote(out_dir=OUT_DIR):
    """Rate-only promotion rule, pre-declared before any data existed.

    Rank the rungs by |G(seed 0) - mean G(B anchor)| and take the CONFIRM_LEVELS nearest,
    forcing at least one rung on each side of the anchor when both sides are non-empty. The
    rule reads the RATE axis only; fidelity -- the axis the dominance verdict is decided on --
    never enters the selection, so the ladder cannot be picked to look good.
    """
    records = load_records(out_dir)
    anchor = [r["metrics"].get("refined_num_gaussians") for r in records
              if r["arm"] == "B_deferred" and r["exit"] == 0]
    anchor = [v for v in anchor if v is not None]
    if not anchor:
        return [], None
    target = statistics.mean(anchor)
    rate = {}
    for level in LEVELS:
        hits = [r["metrics"].get("refined_num_gaussians") for r in records
                if r["arm"] == level and r["seed"] == 0 and r["exit"] == 0]
        hits = [v for v in hits if v is not None]
        if hits:
            rate[level] = hits[-1]
    if not rate:
        return [], target
    below = sorted([lv for lv in rate if rate[lv] <= target], key=lambda lv: target - rate[lv])
    above = sorted([lv for lv in rate if rate[lv] > target], key=lambda lv: rate[lv] - target)
    picked = []
    if below:
        picked.append(below[0])
    if above:
        picked.append(above[0])
    rest = sorted([lv for lv in rate if lv not in picked],
                  key=lambda lv: abs(rate[lv] - target))
    picked += rest[: max(0, CONFIRM_LEVELS - len(picked))]
    return picked, target


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phase",
                        choices=["dry", "anchors", "pilot", "confirm", "report"],
                        required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--levels", nargs="+", default=None,
                        help="override the rungs (default: all of LEVELS; in --phase confirm "
                             "the rate-only promotion rule decides)")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    os.chdir(ROOT)
    out_dir = args.out_dir
    levels = args.levels or list(LEVELS)
    unknown = [lv for lv in levels if lv not in ALL_ARMS]
    if unknown:
        parser.error(f"unknown arm(s) {unknown}; have {sorted(ALL_ARMS)}")

    if args.phase == "report":
        return subprocess.call([PY, "scripts/r2_p03_sweep_readout.py",
                                "--out-dir", out_dir])

    if args.phase == "anchors":
        plan = [(arm, seed) for seed in args.seeds for arm in ANCHORS]
    elif args.phase == "pilot":
        plan = [(lv, args.seeds[0]) for lv in levels]
    elif args.phase == "confirm":
        promoted, target = _promote(out_dir)
        if args.levels:
            promoted = levels
        if not promoted:
            print("nothing to confirm: run --phase anchors and --phase pilot first")
            return 2
        # target is None when --levels names rungs before any B anchor exists on disk
        # (a legitimate top-up invocation against a fresh out_dir).
        anchor_txt = f"{target:.0f} Gaussians" if target is not None else "not yet measured"
        log(f"PROMOTION ({'explicit --levels' if args.levels else 'rate-only'}, "
            f"target = B anchor mean {anchor_txt}): {promoted}", out_dir)
        plan = [(lv, seed) for seed in args.seeds[1:] for lv in promoted]
    else:  # dry
        plan = ([(arm, seed) for seed in args.seeds for arm in ANCHORS]
                + [(lv, args.seeds[0]) for lv in levels])

    if args.phase == "dry":
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        print(f"# DRY RUN -- R2-P03-SWEEP  commit={commit}"
              f"{'  WORKTREE DIRTY (commit before launching)' if dirty else ''}")
        print(f"# out_dir={out_dir}")
        print(f"# anchors+pilot = {len(plan)} runs x ~13 min = ~{13 * len(plan)} min; "
              f"confirm adds {CONFIRM_LEVELS} rungs x 2 seeds = {2 * CONFIRM_LEVELS} runs")
        print("\n## planned runs")
        for arm, seed in plan:
            run_one(arm, seed, out_dir, dry_run=True)
        print("\n## gates (harness assertions only -- a rung that loses fidelity is a RESULT)")
        print(f"  G1 pose frozen  : ate_rmse_cm == {RGD_ATE_CM} ± {RGD_ATE_TOL_CM} on every run")
        print("  G2 knobs live   : the config the run DUMPED carries the rung's knob values")
        print("  G3 support      : vacated support/frames non-zero (else fidelity is scored "
              "on nothing)")
        print("  G4 rate exists  : refined_num_gaussians present")
        print("  MECH (report)   : candidate-side rungs must move the deferred ledger")
        print("\n## pre-declared decision rule: scripts/r2_p03_sweep_readout.py "
              "(margins 1.56 cm / 0.28 dB, rate-then-fidelity dominance)")
        return 0

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        log(f"REFUSING to launch: worktree dirty at {commit}. Campaign discipline requires a "
            f"frozen checkpoint before GPU (02-method.md non-negotiables).", out_dir)
        return 3
    log(f"==== SWEEP phase={args.phase} seeds={args.seeds} commit={commit} "
        f"GPU={os.environ.get('CUDA_VISIBLE_DEVICES', '0')} ====", out_dir)

    already = done_pairs(out_dir)
    records = []
    for arm, seed in plan:
        if (arm, seed) in already:
            log(f"SKIP {arm} seed{seed}: already on disk with exit 0", out_dir)
            continue
        records.append(run_one(arm, seed, out_dir))
    gate_records(records, out_dir, fatal=False)
    mechanism_report(out_dir)
    log(f"==== SWEEP phase={args.phase} DONE ({len(records)} new run(s)) ====", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
