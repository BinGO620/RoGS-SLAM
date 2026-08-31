#!/usr/bin/env python
"""R2-P03-DECOMP: which of S6's three knobs produced its dominance over arm B?

Why this campaign exists
------------------------
``R2-P03-SWEEP`` closed at 22 runs with **1/6 rungs dominating arm B**: ``S6_maxpress`` at
0.63x B's map size, degradations -0.176 cm / -0.043 dB (both nominally better than B), inside
the pre-declared 1.56 cm / 0.28 dB margins. Mechanically that triggers ``02-method.md``'s
"P0 被支配" branch. But S6 moved **three knobs at once**:

    DeferredCommit.ttl_keyframes      5 -> 1      candidate-lifecycle ADMISSION BUDGET
    Training.gaussian_th            0.7 -> 0.9    native MonoGS opacity prune
    opt_params.densify_grad_threshold 2e-4 -> 5e-4  native densification gate

so "is the -54% compactness win deferred-specific?" is currently **unanswerable**, and that
question decides whether any mechanism claim survives into the paper. This campaign runs the
2x2 factorial {ttl_keyframes 1} x {densify_grad 5e-4} against an in-campaign B anchor. The
decisive cell is ``D1_densifyonly``: one generic knob that every 3DGS system has, no part of
the deferred arm's admission budget touched.

Pre-declared readings (written into ``results/evidence/r2_p03_decomp.md`` and committed
BEFORE the first run -- this project's standing discipline is that a result may not be given
its meaning after it is seen):

    D1 dominates B          => compactness is NOT deferred-specific; one generic densify knob
                               suffices. Narrative D hardens and P1 CENSUS most likely cannot
                               rescue the mechanism claim (it would only explain a win a
                               competitor gets by changing one line).
    D1 inside B's rate band => same substantive conclusion for the mechanism question
      (but above its mean)     (a tuned generic knob is statistically indistinguishable from
                               B), while the strict dominance verdict stays with S6 alone.
    D1 clearly above B      => S6's dominance had to borrow ttl=1, the deferred mechanism's own
                               admission budget. ``r2_p03_sweep.md`` §3.6's "the baseline only
                               reaches us by importing our admission budget" is upgraded from
                               narrative judgement to measurement, and P1 is worth running.

Discipline (README + ``02-method.md`` non-negotiables)
------------------------------------------------------
* **New experiment ID.** A changed config is a new ID; nothing here is appended to
  ``R2-P03-SWEEP``'s results, report, or evidence file.
* **Post-hoc, non-preregistered.** These cells were chosen after seeing SWEEP's data. They do
  not join the pre-declared ladder and cannot alter the R2-P02 H1 record.
* **Anchors re-run in-campaign.** Cross-campaign absolute drift on this stack is +12-15% in
  Gaussian count and +1.44 cm in vacated depth (92% of the margin) -- see
  ``r2_p03_sweep.md`` §5. Only ratios to the in-campaign anchor cross campaigns.
* **Decision rule imported, not copied**, from ``scripts/r2_p03_sweep_readout.py``, so it is
  byte-identical to the rule that judged SWEEP.
* **3 seeds on every cell.** SWEEP's lesson (§8): a single seed decided a dominance verdict
  wrongly in both directions at once.
* Worktree must be clean before GPU; live code is frozen for the duration.

Phases
------
    python scripts/r2_p03_decomp.py --phase dry                    # E0, no GPU
    python scripts/r2_p03_decomp.py --phase run                    # all cells x seeds 0,1,2
    python scripts/r2_p03_decomp.py --phase run --arms D1_densifyonly B_deferred
    python scripts/r2_p03_decomp.py --phase report                 # no GPU

Harness gates (G1-G4) and the per-run record schema are **imported** from
``scripts/r2_p03_sweep.py`` rather than re-implemented; gate lines therefore land in
``<out_dir>/sweep.log`` next to this runner's ``decomp.log``, which is the intended proof that
both campaigns were policed by the same code.

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

from scripts.check_arm_activity import check_run  # noqa: E402
from scripts.r2_p02_preflight_pose import (  # noqa: E402  -- same metric 口径 as SWEEP
    PY,
    RGD_ATE_CM,
    RGD_ATE_TOL_CM,
    parse_run,
)
from scripts.r2_p03_sweep import (  # noqa: E402  -- one harness for both campaigns
    LEDGER_KEYS,
    check_config_echo,
    gate_records,
    log,
    read_ledger,
)

OUT_DIR = "results/runs/R2-P03/R2-P03-DECOMP"
RESULTS = "decomp_results.jsonl"

OA = "configs/rgbd/experiments/r2_oracle_admission"
SW = "configs/rgbd/experiments/r2_p03_sweep"
DC = "configs/rgbd/experiments/r2_p03_decomp"

# arm -> (config, {resolved config key: the value the run must have used})
#
# The 2x2 factorial {ttl_keyframes 1} x {densify_grad 5e-4} on arm A, plus both campaign
# anchors. A0 is the "neither knob" cell of the factorial AND the control anchor; B is the
# operating point the dominance rule is evaluated against.
#
# D0 reuses the FROZEN SWEEP config verbatim (not a copy): the in-campaign ttl-only cell is
# then provably the same file that produced SWEEP's S2 row, and its re-run doubles as a
# same-config drift measurement against r2_p03_sweep.md §5.
#
# tests/test_r2_p03_decomp_configs.py imports this dict and pins every resolved-config diff
# against it; run_one re-checks it against the config each run actually dumped, so a cell that
# silently fell back to the arm-A default is caught in the record, not in the results table.
ANCHORS = {
    "A0_prune": (f"{OA}/oracle_prune_balloon.yaml", {}),
    "B_deferred": (f"{OA}/oracle_deferred_balloon.yaml", {}),
}
CELLS = {
    "D0_ttl1": (f"{SW}/sweep_s2_ttl1_balloon.yaml", {"DeferredCommit.ttl_keyframes": 1}),
    "D1_densifyonly": (
        f"{DC}/decomp_d1_densifyonly_balloon.yaml",
        {"opt_params.densify_grad_threshold": 0.0005},
    ),
    "D2_ttl1_densify": (
        f"{DC}/decomp_d2_ttl1_densify_balloon.yaml",
        {
            "DeferredCommit.ttl_keyframes": 1,
            "opt_params.densify_grad_threshold": 0.0005,
        },
    ),
}
ALL_ARMS = {**ANCHORS, **CELLS}

# The minimum set that answers the campaign's question (the user-specified 6-run core).
CORE_ARMS = ["B_deferred", "D1_densifyonly"]

# Cells whose knobs touch the candidate lifecycle: their ledger MUST move (reported, not fatal).
CANDIDATE_SIDE = {"D0_ttl1", "D2_ttl1_densify"}


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
    """One run + its full provenance record. Same schema and gates as R2-P03-SWEEP."""
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


def mechanism_report(out_dir=OUT_DIR):
    """Report-only: did each cell move the channel its knob names?

    ttl cells must move the candidate ledger; the densify-only cell must NOT (it acts on
    densification, downstream of admission) -- an inert ledger there is the expected
    signature, and a moved one would mean the cell is not what it claims to be.
    """
    records = load_records(out_dir)
    base = [r for r in records if r["arm"] == "A0_prune" and r.get("exit") == 0]
    if not base:
        log("MECH: no A0_prune runs on disk -- ledger comparison skipped", out_dir)
        return
    ref = {k: statistics.mean([r["candidate_ledger"].get(k) or 0 for r in base])
           for k in LEDGER_KEYS}
    for cell in CELLS:
        rows = [r for r in records if r["arm"] == cell and r.get("exit") == 0]
        if not rows:
            continue
        got = {k: statistics.mean([r["candidate_ledger"].get(k) or 0 for r in rows])
               for k in LEDGER_KEYS}
        moved = [k for k in ("candidate_total", "pending_final", "expired", "pruned")
                 if abs(got[k] - ref[k]) > 0.02 * max(ref[k], 1.0)]
        note = "moved: " + ",".join(moved) if moved else "candidate ledger UNCHANGED vs A0"
        if cell in CANDIDATE_SIDE and not moved:
            note += "  <-- ttl cell with an inert ledger: read with care"
        if cell not in CANDIDATE_SIDE and moved:
            note += "  <-- densify-only cell moved the candidate ledger: NOT knob-isolated"
        log(f"MECH {cell}: pending_final {ref['pending_final']:.0f} -> "
            f"{got['pending_final']:.0f}, candidate_total {ref['candidate_total']:.0f} -> "
            f"{got['candidate_total']:.0f}, pruned {ref['pruned']:.0f} -> {got['pruned']:.0f} "
            f"[{note}]", out_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phase", choices=["dry", "run", "report"], required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--arms", nargs="+", default=None,
                        help=f"default: every arm ({', '.join(ALL_ARMS)}); the 6-run core is "
                             f"{' '.join(CORE_ARMS)}")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    os.chdir(ROOT)
    out_dir = args.out_dir
    arms = args.arms or list(ALL_ARMS)
    unknown = [a for a in arms if a not in ALL_ARMS]
    if unknown:
        parser.error(f"unknown arm(s) {unknown}; have {sorted(ALL_ARMS)}")

    if args.phase == "report":
        return subprocess.call([PY, "scripts/r2_p03_decomp_readout.py", "--out-dir", out_dir])

    # Seed-major so that a campaign interrupted part-way still holds every arm at the same
    # seed count -- a half-finished cell must never be compared against a complete one.
    plan = [(arm, seed) for seed in args.seeds for arm in arms]

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()

    if args.phase == "dry":
        print(f"# DRY RUN -- R2-P03-DECOMP  commit={commit}"
              f"{'  WORKTREE DIRTY (commit before launching)' if dirty else ''}")
        print(f"# out_dir={out_dir}")
        print(f"# {len(plan)} runs x ~13 min = ~{13 * len(plan)} min")
        print("\n## planned runs")
        for arm, seed in plan:
            run_one(arm, seed, out_dir, dry_run=True)
        print("\n## gates (harness assertions only -- a cell that loses fidelity is a RESULT)")
        print(f"  G1 pose frozen  : ate_rmse_cm == {RGD_ATE_CM} ± {RGD_ATE_TOL_CM} on every run")
        print("  G2 knobs live   : the config the run DUMPED carries the cell's knob values")
        print("  G3 support      : vacated support/frames non-zero")
        print("  G4 rate exists  : refined_num_gaussians present")
        print("  MECH (report)   : ttl cells move the candidate ledger, the densify-only cell "
              "does not")
        print("\n## decision rule: IMPORTED from scripts/r2_p03_sweep_readout.py "
              "(margins 1.56 cm / 0.28 dB, rate-then-fidelity dominance) -- unchanged")
        print("## pre-declared readings: results/evidence/r2_p03_decomp.md §2")
        return 0

    if dirty:
        log(f"REFUSING to launch: worktree dirty at {commit}. Campaign discipline requires a "
            f"frozen checkpoint before GPU (02-method.md non-negotiables).", out_dir)
        return 3
    log(f"==== DECOMP phase=run arms={arms} seeds={args.seeds} commit={commit} "
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
    log(f"==== DECOMP phase=run DONE ({len(records)} new run(s)) ====", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
