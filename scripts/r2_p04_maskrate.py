#!/usr/bin/env python
"""R2-P04-MASKRATE: does the HARD-MASK arm reach arm B's Gaussian budget?

Why this campaign exists
------------------------
External review raised a structural objection to the project's compactness claim: a hard
semantic mask is a strict SUBSET of what the deferred arm admits -- a masked pixel never even
becomes a candidate -- so a mask-blocking competitor's map should be **no larger** than arm B's,
and plausibly smaller. If that holds, "deferred is more compact" is a statement about
insert-then-prune specifically, not about dynamic-SLAM map admission in general.

The objection does not touch any existing verdict, and the reason is checkable rather than
rhetorical: **no arm in the 46 accounted runs of R2-P03 ever enabled ``SemanticMask``.** SWEEP,
DECOMP and S6REPL all inherit from ``oracle_{prune,deferred}_balloon.yaml``, whose resolved
config carries ``SemanticMask.enabled: false`` (pinned in
``tests/test_r2_p04_maskrate_configs.py::test_both_anchors_have_the_mask_off``). So B-vs-A -55%
is a measurement against insert-then-prune, and the hard-mask comparison is one this project has
never made and never claimed. This campaign makes it, in-campaign, config-only.

The ONE question (rate axis)
----------------------------
    Q  Does ``M_mask`` reach ``B_deferred``'s mean Gaussian count?

Pre-declared readings (``results/evidence/r2_p04_maskrate.md`` §2, committed BEFORE the first
run -- a result may not be given its meaning after it is seen):

    (M1) M's rate <= B's mean  => the review's prediction HOLDS. The paper must then scope the
                                  compactness claim explicitly to insert-then-prune and state
                                  the hard-mask comparator as a measured limitation -- ours,
                                  self-reported, before a reviewer raises it.
    (M2) M's rate ~ B's        => inside the rate noise band; the honest statement is that the
                                  two admission strategies land on the same budget by different
                                  routes, and compactness stops being a differentiator vs hard
                                  masking (it remains one vs insert-then-prune).
    (M3) M's rate > B's mean   => the prediction FAILS and the subset argument does not survive
                                  contact with this stack. That is the strongest outcome for the
                                  project, and precisely because it is surprising it may NOT be
                                  written as a win without the keyframe column: a mask that
                                  over-fires changes covisibility and therefore keyframe count,
                                  and a rate advantage bought with less coverage is not a rate
                                  advantage (SWEEP's S6 caveat, KF 18/18/16 < 19/19/19).

In all three cases the two decision metrics are read under the SAME imported bounded
non-inferiority rule as the three closed campaigns; a rate number without its fidelity columns
is not a result here.

What this campaign CANNOT say, declared in advance
--------------------------------------------------
It cannot measure **recovery** -- whether deferred confirmation can restore static content that
a mask false-positively blocked. That was the original design, and the code forbids it:
``apply_semantic_insertion_gate`` zeroes person-mask depth inside ``add_new_keyframe``
(``utils/slam_frontend.py:299,309``), and that same array is what reaches
``_classify_new_keyframe``, where ``valid = isfinite(observed) & (observed > 0.01)`` drops the
zeroed pixels and ``uncertain`` -- the only set ``_add_typed_batch`` ever sees -- is gated by
``static_valid``. Independently ``compute_static_evidence`` sets ``static_valid = valid &
(~semantic)`` (``utils/static_evidence.py:137-138``), so a mask pixel is excluded twice over. A
mask+deferred arm would therefore report ~0 recovery **by construction**, which is an apparatus
artifact, not a null result. Measuring recovery needs a quarantine-instead-of-discard code path;
that is a new mechanism and a separate pre-registration. ``scripts/r2_p04_mask_fp_anchor.py``
sizes the question offline (zero GPU) so the cost of that mechanism can be judged before it is
built.

Also deliberately absent: no pressure knob from R2-P03 appears here (``ttl_keyframes``,
``gaussian_th``, ``densify_grad_threshold`` and the candidate cap all sit at their defaults on
every arm, pinned by the contract test). This campaign adds ONE mechanism to the R2-P03 control
and reads the rate axis. One sequence, one frozen trajectory, PSNR ~14.5 regime, 3-seed sd at
2 df.

Discipline (README + ``02-method.md`` non-negotiables)
------------------------------------------------------
* **New experiment ID.** A new config file and a new arm mean a new ID; nothing here is appended
  to SWEEP's / DECOMP's / S6REPL's results, reports or evidence.
* **Post-hoc, non-preregistered.** Chosen after seeing three campaigns and an external review.
  It does not join the pre-declared ladder and cannot alter the R2-P02 H1 record.
* **Both anchors re-run in-campaign.** Ratios on this stack drift up to ~30% (measured:
  +21% / +29% / -23%), so A0 and B are re-run beside M rather than read across campaigns.
* **Anchors reused by identity, not copied**, from ``scripts/r2_p03_decomp.ANCHORS``.
* **Decision rule imported, not copied**, from ``scripts/r2_p03_sweep_readout.py``.
* **3 seeds on every arm** (SWEEP §8: one seed decided a dominance verdict wrongly in both
  directions at once).
* Worktree must be clean before GPU; live code frozen for the duration.

Phases
------
    python scripts/r2_p04_maskrate.py --phase dry                    # E0, no GPU
    python scripts/r2_p04_maskrate.py --phase run                    # all arms x seeds 0,1,2
    python scripts/r2_p04_maskrate.py --phase run --arms M_mask
    python scripts/r2_p04_maskrate.py --phase report                 # no GPU

Harness gates G1-G4 and the per-run record schema are **imported** from
``scripts/r2_p03_sweep.py``, so the same code policed all four campaigns; its gate lines land in
``<out_dir>/sweep.log`` (the imported ``log()`` owns that filename). This campaign adds **G5**,
which it needs and the others did not: proof from the run's own console log that the semantic
insertion gate FIRED. Without G5 a mask arm that silently resolved the mask off is
indistinguishable from a legitimate null, and the campaign's whole question is a null-vs-null
comparison.

GO/KILL and narrative remain the user's (prereg §9). This script prints measurements and
mechanical gate verdicts only.
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.check_arm_activity import check_run  # noqa: E402
from scripts.r2_p02_preflight_pose import (  # noqa: E402  -- same metric 口径 as R2-P03
    PY,
    RGD_ATE_CM,
    RGD_ATE_TOL_CM,
    parse_run,
)
from scripts.r2_p03_decomp import ANCHORS as DECOMP_ANCHORS  # noqa: E402  -- by identity
from scripts.r2_p03_sweep import (  # noqa: E402  -- one harness for every campaign
    LEDGER_KEYS,
    check_config_echo,
    gate_records,
    log,
    read_ledger,
)

OUT_DIR = "results/runs/R2-P04/R2-P04-MASKRATE"
RESULTS = "maskrate_results.jsonl"

MR = "configs/rgbd/experiments/r2_p04_maskrate"

# arm -> (config, {resolved config key: the value the run must have used})
#
# Two frozen anchors referenced by identity (so this campaign's B is the same file whose rows
# the earlier campaigns reported) plus the one new arm this campaign introduces:
#
#   A0_prune    insert-then-prune control, verbatim -- the mask arm's base and the R2-P03 control
#   B_deferred  the operating point whose budget is under test, verbatim
#   M_mask      A0 + the repo's existing mask-both setting, nothing else
#
# The knob dict is what G2 re-checks against the config each run actually DUMPED, so an arm that
# silently fell back to a default is caught in the record rather than in the results table.
# SemanticMask.enabled is boolean in the yaml; check_config_echo compares via float(), and
# float(True) == 1.0, so the declared value is written as 1 to keep that comparison honest.
ANCHORS = {
    "A0_prune": DECOMP_ANCHORS["A0_prune"],
    "B_deferred": DECOMP_ANCHORS["B_deferred"],
}
CELLS = {
    "M_mask": (
        f"{MR}/maskrate_m_mask_balloon.yaml",
        {
            "SemanticMask.enabled": 1,
            "SemanticMask.mask_mapping": 1,
            "SemanticMask.mask_insertion": 1,
        },
    ),
}
ALL_ARMS = {**ANCHORS, **CELLS}

# Arms whose console log MUST contain the semantic insertion gate line (G5).
MASK_SIDE = {"M_mask"}

# The pair the pre-declared question is about: the mask arm and the budget it must reach.
CORE_ARMS = ["B_deferred", "M_mask"]

# utils/slam_frontend.py:387-390 -- "Semantic insertion gate frame {i}: {n} person px zeroed"
GATE_LINE = re.compile(
    r"Semantic insertion gate frame (\d+): (\d+) person px zeroed", re.MULTILINE
)


def mask_gate_evidence(console_path):
    """G5: did the semantic insertion gate actually zero pixels, per the run's own log?

    Returns (frames, pixels_total). A mask arm with frames == 0 did not mask anything: either
    the config resolved the gate off or Mask R-CNN never fired, and in both cases the arm is a
    duplicate of arm A wearing the mask's name. That failure mode is invisible in the rate table
    -- it looks exactly like "the mask changed nothing" -- which is why it is a gate and not a
    footnote.
    """
    if not os.path.isfile(console_path):
        return 0, 0
    with open(console_path, encoding="utf-8", errors="replace") as f:
        hits = GATE_LINE.findall(f.read())
    return len(hits), sum(int(n) for _, n in hits)


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
    """One run + its full provenance record. Same schema and gates as R2-P03, plus G5."""
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
    gate_frames, gate_px = mask_gate_evidence(console)
    record = {
        "arm": arm, "seed": seed, "config": config, "knobs": knobs,
        "exit": code, "minutes": round(minutes, 1), "run_dir": run_root,
        "pose_frozen": pose_frozen,
        "config_echo_ok": echo_ok, "config_echo": echo_detail,
        "activity_verdict": verdict, "activity_detail": detail,
        "mask_gate_frames": gate_frames, "mask_gate_px": gate_px,
        "metrics": metrics, "candidate_ledger": read_ledger(run_root),
    }
    with open(os.path.join(out_dir, RESULTS), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    log(f"END   {arm} seed{seed} exit={code} {minutes:.1f}min "
        f"G={metrics.get('refined_num_gaussians')} ate={ate} "
        f"vac_depth={metrics.get('static_vacated_depth_l1_pen_cm')} "
        f"vac_psnr={metrics.get('static_vacated_psnr')} "
        f"mask_gate={gate_frames}f/{gate_px}px "
        f"pose_frozen={pose_frozen} config_echo={'ok' if echo_ok else 'FAIL: ' + echo_detail}",
        out_dir)
    return record


def gate_mask_side(records, out_dir=OUT_DIR):
    """G5 over a batch: every mask arm must show the insertion gate firing, and every
    non-mask arm must show it NOT firing (a leaked mask would contaminate the anchors)."""
    ok = True
    for r in records:
        if r.get("dry_run"):
            continue
        tag = f"{r['arm']}/s{r['seed']}"
        frames, px = r.get("mask_gate_frames", 0), r.get("mask_gate_px", 0)
        if r["arm"] in MASK_SIDE:
            if frames <= 0 or px <= 0:
                log(f"GATE FAIL {tag}: semantic insertion gate never fired "
                    f"({frames} frames / {px} px) -- this arm silently degenerated into "
                    f"arm A and its rate is NOT a hard-mask measurement", out_dir)
                ok = False
            else:
                log(f"GATE ok   {tag}: insertion gate fired on {frames} keyframes, "
                    f"{px} person px zeroed ({px / max(frames, 1):.0f}/kf)", out_dir)
        elif frames > 0:
            log(f"GATE FAIL {tag}: anchor arm shows the insertion gate firing "
                f"({frames} frames) -- the mask leaked into a control", out_dir)
            ok = False
    return ok


def mechanism_report(out_dir=OUT_DIR):
    """Report-only: what did the mask do to the candidate lifecycle, and by how much?

    The mask arm runs arm A's lifecycle, so its candidate ledger is directly comparable to
    ``A0_prune``'s. Two things are worth stating in the log rather than derived later:

    * the mask REMOVES candidates upstream (a zeroed pixel fails the ``observed > 0.01``
      validity test in ``_classify_new_keyframe``), so ``candidate_total`` should fall relative
      to A0 -- that drop is the mechanism by which a hard mask is a subset of deferred, made
      visible instead of argued;
    * how many person pixels the gate actually zeroed per keyframe, which is the scale of the
      intervention and the number the offline FP anchor is compared against.
    """
    records = load_records(out_dir)
    base = [r for r in records if r["arm"] == "A0_prune" and r.get("exit") == 0]
    ref = ({k: statistics.mean([(r["candidate_ledger"] or {}).get(k) or 0 for r in base])
            for k in LEDGER_KEYS} if base else None)
    for arm in ALL_ARMS:
        rows = [r for r in records if r["arm"] == arm and r.get("exit") == 0]
        if not rows:
            continue
        got = {k: statistics.mean([(r["candidate_ledger"] or {}).get(k) or 0 for r in rows])
               for k in LEDGER_KEYS}
        frames = [r.get("mask_gate_frames", 0) for r in rows]
        px = [r.get("mask_gate_px", 0) for r in rows]
        gate_txt = (f", insertion gate {statistics.mean(frames):.1f} kf / "
                    f"{statistics.mean(px):.0f} px "
                    f"({statistics.mean(px) / max(statistics.mean(frames), 1):.0f}/kf)"
                    if arm in MASK_SIDE else "")
        delta = ""
        if ref and arm != "A0_prune":
            drop = got["candidate_total"] - ref["candidate_total"]
            delta = (f", candidate_total {ref['candidate_total']:.0f} -> "
                     f"{got['candidate_total']:.0f} ({drop:+.0f} vs A0)")
        log(f"MECH {arm}: candidate_total {got['candidate_total']:.0f}, "
            f"promoted {got['promoted']:.0f}, expired {got['expired']:.0f}, "
            f"pruned {got['pruned']:.0f}, pending_final {got['pending_final']:.0f}"
            f"{delta}{gate_txt}", out_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phase", choices=["dry", "run", "report"], required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--arms", nargs="+", default=None,
                        help=f"default: every arm ({', '.join(ALL_ARMS)}); the minimum that "
                             f"answers the pre-declared question is {' '.join(CORE_ARMS)}")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    os.chdir(ROOT)
    out_dir = args.out_dir
    arms = args.arms or list(ALL_ARMS)
    unknown = [a for a in arms if a not in ALL_ARMS]
    if unknown:
        parser.error(f"unknown arm(s) {unknown}; have {sorted(ALL_ARMS)}")

    if args.phase == "report":
        return subprocess.call([PY, "scripts/r2_p04_maskrate_readout.py",
                               "--out-dir", out_dir])

    # Seed-major, as in DECOMP/S6REPL: a campaign interrupted part-way still holds every arm at
    # the same seed count, so a half-finished arm is never compared against a complete one.
    plan = [(arm, seed) for seed in args.seeds for arm in arms]

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()

    if args.phase == "dry":
        print(f"# DRY RUN -- R2-P04-MASKRATE  commit={commit}"
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
        print("  G5 mask fired   : M_mask's console log shows the semantic insertion gate "
              "zeroing person px; the anchors' logs must NOT show it")
        print("  MECH (report)   : candidate_total vs A0 (the mask removes candidates "
              "upstream) + person px zeroed per keyframe")
        print("\n## decision rule: IMPORTED from scripts/r2_p03_sweep_readout.py "
              "(margins 1.56 cm / 0.28 dB, rate-then-fidelity dominance) -- unchanged")
        print("## pre-declared readings: results/evidence/r2_p04_maskrate.md §2 "
              "(M1 rate <= B / M2 inside band / M3 rate > B, and why M3 needs the KF column)")
        print("## NOT measurable here (§3): recovery of mask false positives -- masked pixels "
              "are zeroed upstream of candidate formation, so a mask+deferred arm would report "
              "~0 recovery by construction. Offline sizing: scripts/r2_p04_mask_fp_anchor.py")
        return 0

    if dirty:
        log(f"REFUSING to launch: worktree dirty at {commit}. Campaign discipline requires a "
            f"frozen checkpoint before GPU (02-method.md non-negotiables).", out_dir)
        return 3
    log(f"==== MASKRATE phase=run arms={arms} seeds={args.seeds} commit={commit} "
        f"GPU={os.environ.get('CUDA_VISIBLE_DEVICES', '0')} ====", out_dir)

    already = done_pairs(out_dir)
    records = []
    for arm, seed in plan:
        if (arm, seed) in already:
            log(f"SKIP {arm} seed{seed}: already on disk with exit 0", out_dir)
            continue
        records.append(run_one(arm, seed, out_dir))
    gate_records(records, out_dir, fatal=False)
    gate_mask_side(records, out_dir)
    mechanism_report(out_dir)
    log(f"==== MASKRATE phase=run DONE ({len(records)} new run(s)) ====", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
