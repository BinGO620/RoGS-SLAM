#!/usr/bin/env python
"""R2-P03-S6REPL: does S6's dominance over arm B replicate, and what did ``gaussian_th`` do?

Why this campaign exists
------------------------
Two closed campaigns leave exactly one load-bearing statement resting on a cross-campaign
comparison, and it happens to be the statement the whole decision tree hangs from.

``R2-P03-SWEEP`` (22 runs, commits ``9c5f8a4``+``6b37845``) ended with **1/6 rungs dominating
arm B**: ``S6_maxpress`` at **0.63xB**, degradations -0.176 cm / -0.043 dB, both inside the
pre-declared margins. That single rung is what puts ``02-method.md``'s decision tree in
narrative **D**.

``R2-P03-DECOMP`` (15 runs, commit ``5e789a5``) decomposed two of S6's three knobs in one
campaign: the generic densify throttle **alone** does nothing (``D1`` = 0.98xA0), ``ttl``=1
alone = 1.37xB, both together (``D2``) = 1.07xB while failing the vacated-PSNR margin. It could
not test the third knob, ``Training.gaussian_th`` = 0.9, because S6 lived in the previous
campaign -- so "gth carried most of S6's dominance" was left as a **cross-campaign inference**
(D2 1.07xB here vs S6 0.63xB there).

And DECOMP measured why that inference is not safe: re-running SWEEP's ``S2`` config file
verbatim moved its **ratio** to the in-campaign B anchor from 1.13xB to 1.37xB, **+21%**, and
B-vs-A0 compactness read -55.2% / -54.3% / -46.6% across three campaigns. Ratios are more
stable than absolutes on this stack; they are not stable. A 0.63-vs-1.07 gap read across two
campaigns is therefore an inference of exactly the kind ``README.md``'s 跨 campaign 比较禁令
forbids from carrying a verdict.

This campaign closes both holes in one launch, so that neither answer needs a cross-campaign
step:

    Q1  gth's contribution  = S6 vs D2, both here, 3 seeds each. The contract test
        tests/test_r2_p03_decomp_configs.py::test_d2_is_s6_minus_the_native_opacity_prune
        already pins that these two configs differ in EXACTLY ``Training.gaussian_th``, which
        is what licenses reading the contrast as that knob's contribution.
    Q2  does the dominance REPLICATE? = S6 vs an in-campaign B anchor under the imported
        dominance rule. S6's verdict currently rests on one campaign, with a rate CV of 33%,
        on a stack whose ratios drift ~20%.

Pre-declared readings (``results/evidence/r2_p03_s6repl.md`` §2, committed BEFORE the first
run -- a result may not be given its meaning after it is seen):

    Q1 (a) S6 clearly below D2  => gaussian_th carries a measurable share of the dominance;
                                   "only 1 of S6's 3 knobs is a native prune" must then be
                                   paired with how much that one knob did.
       (b) S6 ~ D2 (inside band) => gth contributed nothing measurable; S6's dominance is the
                                   ttl+densify combination, i.e. DECOMP's D2 row, and the
                                   0.63-vs-1.07 gap was campaign drift rather than gth.
       (c) S6 clearly above D2   => gth raised the rate; report as measured.
    Q2 (R1) S6 dominates B again => the SWEEP verdict replicates across independent campaigns.
       (R2) S6 misses B's mean   => it does NOT replicate. SWEEP's in-campaign verdict is not
                                   deleted (it was a legitimate measurement); the honest
                                   statement becomes "dominated in 1 of 2 campaigns".
       (R3) S6 reaches B's rate
            but breaks a margin  => this resurrects the claim SWEEP RETRACTED as a single-seed
                                   artifact; the retraction must then be revisited explicitly,
                                   not silently reversed.

Discipline (README + ``02-method.md`` non-negotiables)
------------------------------------------------------
* **New experiment ID.** Adding a rung is a new ID; nothing here is appended to
  ``R2-P03-SWEEP``'s or ``R2-P03-DECOMP``'s results, reports or evidence files.
* **Post-hoc, non-preregistered.** Chosen after seeing both campaigns. Does not join the
  pre-declared ladder and cannot alter the R2-P02 H1 record.
* **The anchor is re-run in-campaign.** That is the entire point: 9 runs instead of 3 exist so
  that both answers are within-campaign contrasts.
* **Configs are reused verbatim, not copied.** ``S6_maxpress`` is SWEEP's frozen file and
  ``D2_ttl1_densify`` is DECOMP's, by identity -- pinned in
  ``tests/test_r2_p03_s6repl_configs.py``. No new config file is introduced by this campaign.
* **Decision rule imported, not copied**, from ``scripts/r2_p03_sweep_readout.py``.
* **3 seeds on every arm** (SWEEP §8: one seed decided a dominance verdict wrongly in both
  directions at once).
* Worktree must be clean before GPU; live code frozen for the duration.

What 9 runs cannot say (scoped deliberately, stated in advance): there is **no A0 anchor in
this campaign**, so nothing here extends the B-vs-A0 compactness series to a fourth campaign
and no rate can be expressed x A0. One sequence, one frozen trajectory, PSNR ~14.5 regime,
3-seed sd at 2 df.

Phases
------
    python scripts/r2_p03_s6repl.py --phase dry                     # E0, no GPU
    python scripts/r2_p03_s6repl.py --phase run                     # all arms x seeds 0,1,2
    python scripts/r2_p03_s6repl.py --phase run --arms S6_maxpress
    python scripts/r2_p03_s6repl.py --phase report                  # no GPU

Harness gates (G1-G4) and the per-run record schema are **imported** from
``scripts/r2_p03_sweep.py``, so the same code policed all three campaigns; its gate lines land
in ``<out_dir>/sweep.log`` (the imported ``log()`` owns that filename; this runner writes no
log of its own).

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
from scripts.r2_p02_preflight_pose import (  # noqa: E402  -- same metric 口径 as SWEEP/DECOMP
    PY,
    RGD_ATE_CM,
    RGD_ATE_TOL_CM,
    parse_run,
)
from scripts.r2_p03_decomp import CELLS as DECOMP_CELLS  # noqa: E402  -- D2, by identity
from scripts.r2_p03_sweep import (  # noqa: E402  -- one harness for all three campaigns
    LEDGER_KEYS,
    LEVELS as SWEEP_LEVELS,
    check_config_echo,
    gate_records,
    log,
    read_ledger,
)

OUT_DIR = "results/runs/R2-P03/R2-P03-S6REPL"
RESULTS = "s6repl_results.jsonl"

OA = "configs/rgbd/experiments/r2_oracle_admission"

# arm -> (config, {resolved config key: the value the run must have used})
#
# Every entry is a FROZEN config from an earlier campaign, referenced by identity rather than
# copied, so the two contrasts this campaign makes are between the same files that produced the
# rows they are being compared with:
#
#   S6_maxpress      SWEEP's dominating rung, verbatim  (ttl=1 + gth=0.9 + densify=5e-4)
#   D2_ttl1_densify  DECOMP's interaction cell, verbatim (ttl=1 + densify=5e-4)  == S6 - gth
#   B_deferred       the operating point under test, exactly as R2-P02/SWEEP/DECOMP ran it
#
# tests/test_r2_p03_s6repl_configs.py pins the identities and re-asserts that S6 and D2 differ
# in exactly Training.gaussian_th; run_one re-checks each knob against the config the run
# actually dumped, so an arm that silently fell back to a default is caught in the record.
ANCHORS = {
    "B_deferred": (f"{OA}/oracle_deferred_balloon.yaml", {}),
}
CELLS = {
    "D2_ttl1_densify": DECOMP_CELLS["D2_ttl1_densify"],
    "S6_maxpress": SWEEP_LEVELS["S6_maxpress"],
}
ALL_ARMS = {**ANCHORS, **CELLS}

# Both cells set ttl_keyframes=1, so both must show the degenerate candidate lifecycle DECOMP
# measured (promoted == 0 on every seed). gaussian_th is a POST-insertion prune, so S6's
# candidate ledger must also match D2's -- if it does not, the pair is not gth-isolated and the
# Q1 contrast cannot be read as declared.
CANDIDATE_SIDE = {"D2_ttl1_densify", "S6_maxpress"}

# The minimum set that answers Q1 (gth's contribution) without the B anchor.
CORE_ARMS = ["D2_ttl1_densify", "S6_maxpress"]


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
    """One run + its full provenance record. Same schema and gates as SWEEP and DECOMP."""
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
    """Report-only: is the S6/D2 pair gth-isolated, and is the ttl lifecycle degenerate?

    ``gaussian_th`` prunes AFTER insertion, so it must not touch the candidate ledger: SWEEP's
    two gth rungs left it unchanged (24025 / 23321 vs A0's 23695). Here that expectation is
    checked as a difference between S6 and D2 -- the two arms whose only declared difference is
    that knob. And both arms run ttl=1, where DECOMP measured ``promoted`` == 0 on every seed;
    if that degeneracy does not reproduce, the "the baseline must degenerate into
    insert-everything-then-delete" statement needs qualifying.
    """
    records = load_records(out_dir)
    per_arm = {}
    for arm in CELLS:
        rows = [r for r in records if r["arm"] == arm and r.get("exit") == 0]
        if not rows:
            continue
        per_arm[arm] = {k: statistics.mean([r["candidate_ledger"].get(k) or 0 for r in rows])
                        for k in LEDGER_KEYS}
        promoted = [(r["candidate_ledger"] or {}).get("promoted") for r in rows]
        degenerate = all(p == 0 for p in promoted if p is not None)
        ttl_note = ("degenerate ttl lifecycle as in DECOMP" if degenerate else
                    "promoted > 0 -- the ttl degeneracy did NOT reproduce, qualify the claim")
        per_seed = "/".join("-" if p is None else str(int(p)) for p in promoted)
        log(f"MECH {arm}: promoted per seed = {per_seed} [{ttl_note}], "
            f"pending_final {per_arm[arm]['pending_final']:.0f}, "
            f"candidate_total {per_arm[arm]['candidate_total']:.0f}, "
            f"pruned {per_arm[arm]['pruned']:.0f}", out_dir)

    if len(per_arm) == 2:
        d2, s6 = per_arm["D2_ttl1_densify"], per_arm["S6_maxpress"]
        moved = [k for k in ("candidate_total", "pending_final", "expired", "pruned")
                 if abs(s6[k] - d2[k]) > 0.02 * max(d2[k], 1.0)]
        note = ("candidate ledger UNCHANGED vs D2 -- gth acted post-insertion as expected"
                if not moved else
                "moved: " + ",".join(moved) + "  <-- gth moved the candidate ledger: the S6/D2 "
                "pair is not gth-isolated on the mechanism side, read Q1 with that caveat")
        log(f"MECH S6 vs D2 (only declared difference = Training.gaussian_th 0.7->0.9): "
            f"pending_final {d2['pending_final']:.0f} -> {s6['pending_final']:.0f}, "
            f"candidate_total {d2['candidate_total']:.0f} -> {s6['candidate_total']:.0f}, "
            f"pruned {d2['pruned']:.0f} -> {s6['pruned']:.0f} [{note}]", out_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phase", choices=["dry", "run", "report"], required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--arms", nargs="+", default=None,
                        help=f"default: every arm ({', '.join(ALL_ARMS)}); the Q1-only core is "
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
        return subprocess.call([PY, "scripts/r2_p03_s6repl_readout.py", "--out-dir", out_dir])

    # Seed-major, as in DECOMP: a campaign interrupted part-way still holds every arm at the
    # same seed count, so a half-finished arm is never compared against a complete one.
    plan = [(arm, seed) for seed in args.seeds for arm in arms]

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()

    if args.phase == "dry":
        print(f"# DRY RUN -- R2-P03-S6REPL  commit={commit}"
              f"{'  WORKTREE DIRTY (commit before launching)' if dirty else ''}")
        print(f"# out_dir={out_dir}")
        print(f"# {len(plan)} runs x ~13 min = ~{13 * len(plan)} min")
        print("\n## planned runs")
        for arm, seed in plan:
            run_one(arm, seed, out_dir, dry_run=True)
        print("\n## gates (harness assertions only -- an arm that loses fidelity is a RESULT)")
        print(f"  G1 pose frozen  : ate_rmse_cm == {RGD_ATE_CM} ± {RGD_ATE_TOL_CM} on every run")
        print("  G2 knobs live   : the config the run DUMPED carries the arm's knob values")
        print("  G3 support      : vacated support/frames non-zero")
        print("  G4 rate exists  : refined_num_gaussians present")
        print("  MECH (report)   : ttl degeneracy (promoted == 0) on both cells, and S6's "
              "candidate ledger == D2's (gth is a post-insertion prune)")
        print("\n## decision rule: IMPORTED from scripts/r2_p03_sweep_readout.py "
              "(margins 1.56 cm / 0.28 dB, rate-then-fidelity dominance) -- unchanged")
        print("## pre-declared readings: results/evidence/r2_p03_s6repl.md §2 "
              "(Q1 = gth's contribution, Q2 = does the dominance replicate)")
        return 0

    if dirty:
        log(f"REFUSING to launch: worktree dirty at {commit}. Campaign discipline requires a "
            f"frozen checkpoint before GPU (02-method.md non-negotiables).", out_dir)
        return 3
    log(f"==== S6REPL phase=run arms={arms} seeds={args.seeds} commit={commit} "
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
    log(f"==== S6REPL phase=run DONE ({len(records)} new run(s)) ====", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
