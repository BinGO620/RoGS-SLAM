#!/usr/bin/env python3
"""P3-S6X: does ``S6_maxpress`` still beat arm B once the regime can charge it for the map?

Why this campaign exists
------------------------
``S6_maxpress`` is the single configuration that ever pressed below arm B's operating point —
0.63×B in ``R2-P03-SWEEP`` and 0.81×B in ``R2-P03-S6REPL``, per-seed 3/3 both times, with both
fidelity degradations inside the pre-declared margins. It is the reason the compactness headline
is dead: a *tuned baseline* reached our budget without paying for it.

But every one of those 46 runs shared one regime, and the regime has a hole in it:

  * one sequence (Bonn balloon), PSNR ≈ 14.5;
  * an **injected** RGD trajectory (``Oracle.pose_file`` set, camera lrs zeroed), so
    ``ate_rmse_cm`` read **2.0618 on all 46 runs** — identical for every arm, by construction.

S6's core knob is ``ttl_keyframes=1``, and ``R2-P03-DECOMP`` measured what it does to the prune
arm's lifecycle: ``promoted`` drops to **0 on every seed** and the candidate residue collapses
**23927 → 5000**. The arm gets its rate by degenerating into insert-everything-then-delete-one-
keyframe-later. Under a frozen trajectory a degraded map **cannot** feed back into the pose, so
whatever that degeneration costs tracking was **structurally uncharged**. Self-tracked, it can be
charged. That is the entire content of this campaign — same knobs, a regime with a bill.

The pre-registered question (``results/evidence/p3_s6x_prereg.md`` §2, committed before run 1):
under self-tracking, on the combined backbone, across all 6 dynamic sequences — **does S6's rate
advantage survive, and does its ATE hold?**

What the apparatus does and does not allow
------------------------------------------
* **Three arms, one knob group.** ``s6`` = the P2-T prune run config **plus** exactly the three
  ``S6_maxpress`` knobs, whose values are imported by identity from
  ``scripts.r2_p03_sweep.LEVELS``; the two anchors are P2-T's frozen run configs, imported by
  identity from ``scripts.r2_p2_t.ARMS``. This campaign introduces no anchor config.
  ``tests/test_p3_s6x_configs.py`` pins all of it at E0.
* **Both anchors are re-run here.** They are NOT read from P2-T's rows. Same-config ratios on
  this stack have been measured drifting +21% / +29% / −23% between campaigns (README's
  cross-campaign ban); a comparison whose anchor lives in another campaign cannot carry a verdict.
  The readout reads only this campaign's ``p3s6x_results.jsonl``.
* **The pose gate is INVERTED relative to R2-P03.** There the harness asserted the trajectory was
  frozen; here it asserts every arm genuinely self-tracked (empty ``Oracle.pose_file``, non-zero
  camera lrs, ATE not pinned at the injected constant). A run that silently froze would answer
  the old question again.
* **Decision rule imported, not copied** from ``scripts/r2_p03_sweep_readout.py`` (1.56 cm /
  0.28 dB, rate-then-fidelity dominance) — byte-identical to the four R2-P03 campaigns — plus an
  ATE column, which is the new information: in the frozen regime it was a constant.
* **Harness gates never abort on a result.** An arm that prunes hard and loses fidelity, or that
  drifts, is the measurement. Only "the run did not do what the config says" is fatal.

Phases
------
  python scripts/p3_s6x.py --phase dry      # E0, no GPU — prints the plan + gates
  python scripts/p3_s6x.py --phase seed0    # batch 1: 6 seqs × 3 arms × seed 0 = 18 runs
  python scripts/p3_s6x.py --phase full     # batch 2: seeds 1,2 = 36 runs (USER GO REQUIRED)
  python scripts/p3_s6x.py --phase resume   # re-run any (seq,arm,seed) not yet exit-0
  python scripts/p3_s6x.py --phase report   # no GPU — delegates to the readout

``--phase seed0`` deliberately does **not** chain into ``full``: single seed is screening and
decides nothing (discipline ⑤ — a rung on the decision path needs 3 seeds before a conclusion is
written down; SWEEP's S6 single seed once decided a verdict wrongly in both directions at once).
GO/KILL and narrative remain the user's. This script prints measurements and mechanical gate
verdicts only.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.check_arm_activity import _load_config, _resolve_run_dir, check_run  # noqa: E402
from scripts.r2_p02_preflight_pose import PY, RGD_ATE_CM, parse_run  # noqa: E402
from scripts.r2_p03_sweep import check_config_echo, read_ledger  # noqa: E402
from scripts.r2_p03_sweep import LEVELS as SWEEP_LEVELS  # noqa: E402
from scripts.r2_p2_t import ARMS as P2T_ARMS  # noqa: E402
from scripts.r2_p2_t import SEQS as P2T_SEQS  # noqa: E402

OUT_DIR = "results/runs/P3/P3-S6X"
RESULTS = "p3s6x_results.jsonl"
S6X = "configs/rgbd/experiments/p3_s6x"

# The knob group under migration, by identity from the campaign that measured it. If SWEEP's
# rung is ever edited this campaign fails E0 rather than quietly migrating a different baseline.
S6_KNOBS = SWEEP_LEVELS["S6_maxpress"][1]

# arm -> (run-config template keyed by sequence, {resolved key: value the run must have used})
#
#   prune     P2-T's control twin, RE-RUN HERE (never borrowed from P2-T's rows)
#   deferred  P2-T's method twin,  RE-RUN HERE (never borrowed from P2-T's rows)
#   s6        the same prune config + exactly the three S6_maxpress knobs
#
# The anchors' templates are P2-T's own, imported rather than restated, so an anchor cannot
# silently become a near-copy of the row it is supposed to reproduce.
ARMS = {
    "prune": (P2T_ARMS["prune"], {}),
    "deferred": (P2T_ARMS["deferred"], {}),
    "s6": (f"{S6X}/p3s6x_s6_{{}}.yaml", S6_KNOBS),
}
ARM_ORDER = ("prune", "deferred", "s6")
SEQS = list(P2T_SEQS)  # identity with the main table's 6 dynamic sequences — no seq shopping

# Catastrophic-run thresholds, inherited from P2-T (prereg §7): a seed is FLAGGED and KEPT.
CATASTROPHIC_ATE_CM = 100.0
CATASTROPHIC_G_MULT = 3.0
# seed-0 information gate. Not an auto-abort: batch 2 needs the user's GO either way.
STOPGO_ATE_CM = 50.0
STOPGO_COLLAPSE_COUNT = 2


def log(msg, out_dir=OUT_DIR):
    line = f"[{time.strftime('%F %T')}] {msg}"
    print(line, flush=True)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "p3s6x.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def seq_cfg(arm, seq):
    return ARMS[arm][0].format(seq)


def load_records(out_dir=OUT_DIR):
    path = os.path.join(out_dir, RESULTS)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def done_triples(out_dir=OUT_DIR):
    return {(r["arm"], r["seq"], r["seed"]) for r in load_records(out_dir) if r.get("exit") == 0}


def check_self_tracked(run_root, ate):
    """The R2-P03 pose gate, INVERTED: prove the run tracked for itself.

    Reads the config the process actually dumped (not the yaml on disk, which only proves what
    was asked for) and requires an empty ``Oracle.pose_file``, ``gt_pose`` off and non-zero
    camera-delta learning rates. Also refuses an ATE sitting on the injected constant 2.0618:
    the frozen regime is the thing this campaign exists to leave, so silently re-entering it
    would answer the old question with the new question's label on it.
    """
    resolved = _resolve_run_dir(run_root)
    if resolved is None:
        return False, "no resolved config.yml under the run root"
    config = _load_config(resolved)
    if config is None:
        return False, "config.yml unreadable"
    bad = []
    oracle = config.get("Oracle") or {}
    if oracle.get("pose_file"):
        bad.append(f"Oracle.pose_file={oracle.get('pose_file')!r} (trajectory injected)")
    if oracle.get("gt_pose"):
        bad.append("Oracle.gt_pose=True (GT pose injected)")
    lrs = ((config.get("Training") or {}).get("lr") or {})
    for key in ("cam_rot_delta", "cam_trans_delta"):
        value = lrs.get(key)
        if value is None or float(value) <= 0.0:
            bad.append(f"Training.lr.{key}={value!r} (pose frozen)")
    if ate is not None and abs(ate - RGD_ATE_CM) <= 1e-3:
        bad.append(f"ate_rmse_cm=={ate} == the injected RGD constant")
    if bad:
        return False, "; ".join(bad)
    return True, "self-tracked (pose_file empty, gt_pose off, cam lrs > 0)"


def keyframe_count(run_root):
    """Keyframes the run kept. Endogenous covariate, reported not decided on.

    Both prior campaigns measured S6 covering the sequence with FEWER keyframes than the anchors
    (16/18/18 and 18/18/16 against 19/19/19), so part of its rate advantage is less coverage.
    Under self-tracking the keyframe schedule is also a tracking-relevant quantity, which is why
    it is recorded per run rather than summarised.
    """
    resolved = _resolve_run_dir(run_root)
    if resolved is None:
        return None
    path = os.path.join(resolved, "plot", "trj_final.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return len(json.load(f)["trj_id"])
    except (KeyError, ValueError, OSError):
        return None


def run_one(arm, seq, seed, out_dir=OUT_DIR, dry_run=False):
    config = seq_cfg(arm, seq)
    knobs = ARMS[arm][1]
    tag = f"{seq}_{arm}_seed{seed}"
    run_root = os.path.join(out_dir, tag)
    console = os.path.join(out_dir, f"{tag}.consolelog")
    cmd = [PY, "slam.py", "--config", config, "--eval",
           "--seed", str(seed), "--results-root", run_root]
    if dry_run:
        print(f"  {' '.join(cmd)}")
        return {"arm": arm, "seq": seq, "seed": seed, "cmd": cmd, "config": config,
                "knobs": knobs, "dry_run": True}

    log(f"START {tag} knobs={knobs or '-'} -> {run_root}", out_dir)
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
    self_ok, self_detail = check_self_tracked(run_root, ate)
    record = {
        "arm": arm, "seq": seq, "seed": seed, "config": config, "knobs": knobs,
        "exit": code, "minutes": round(minutes, 1), "run_dir": run_root,
        "self_tracked": self_ok, "self_tracked_detail": self_detail,
        "config_echo_ok": echo_ok, "config_echo": echo_detail,
        "activity_verdict": verdict, "activity_detail": detail,
        "keyframes": keyframe_count(run_root),
        "metrics": metrics, "candidate_ledger": read_ledger(run_root),
    }
    with open(os.path.join(out_dir, RESULTS), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    log(f"END   {tag} exit={code} {minutes:.1f}min G={metrics.get('refined_num_gaussians')} "
        f"ate={ate} kf={record['keyframes']} "
        f"vac_depth={metrics.get('static_vacated_depth_l1_pen_cm')} "
        f"vac_psnr={metrics.get('static_vacated_psnr')} "
        f"self_tracked={self_ok} config_echo={'ok' if echo_ok else 'FAIL: ' + echo_detail}",
        out_dir)
    return record


def gate_records(records, out_dir=OUT_DIR, fatal=False):
    """HARNESS assertions only. Losing fidelity or drifting is a RESULT, never an abort."""
    ok = True
    for r in records:
        tag = f"{r['seq']}/{r['arm']}/s{r['seed']}"
        m = r["metrics"]
        bad = []
        if r["exit"] != 0:
            bad.append(f"G1 exit={r['exit']}")
        if not r["self_tracked"]:
            bad.append(f"G2 not self-tracked -- {r['self_tracked_detail']}")
        if not r["config_echo_ok"]:
            bad.append(f"G3 knobs did not take effect -- {r['config_echo']}")
        if m.get("refined_num_gaussians") is None:
            bad.append("G4 no refined_num_gaussians (nothing on the rate axis)")
        if m.get("ate_rmse_cm") is None:
            bad.append("G5 no ate_rmse_cm (the column this campaign exists for)")
        support = m.get("static_vacated_support_px_mean")
        frames = m.get("static_vacated_frames_scored")
        if not support or not frames:
            bad.append(f"G6 vacated support={support} frames={frames}")
        if r["activity_verdict"] == "FAIL":
            bad.append(f"G7 activity={r['activity_detail']}")
        if bad:
            ok = False
            log(f"GATE FAIL {tag}: " + " | ".join(bad), out_dir)
        else:
            log(f"GATE ok   {tag}: G={m.get('refined_num_gaussians')} "
                f"ate={m.get('ate_rmse_cm')} kf={r.get('keyframes')} knobs[{r['config_echo']}]",
                out_dir)
    if not ok and fatal:
        log("==== ABORT: a harness gate failed. A migration test on a harness that did not do "
            "what the config says answers nothing. ====", out_dir)
    return ok


def anchor_coverage(records, out_dir=OUT_DIR):
    """Every (seq, seed) that has an s6 row must have BOTH anchors in THIS campaign.

    The cross-campaign ban is the reason 18 runs exist instead of 6. If an anchor is missing the
    readout has nothing legitimate to compare against for that cell, and borrowing P2-T's row
    would be exactly the prohibited move — so it is surfaced here, loudly, rather than papered
    over at readout time.
    """
    have = {(r["seq"], r["arm"], r["seed"]) for r in records if r.get("exit") == 0}
    missing = []
    for seq, arm, seed in sorted(have):
        if arm != "s6":
            continue
        for anchor in ("prune", "deferred"):
            if (seq, anchor, seed) not in have:
                missing.append(f"{seq}/s{seed}: no in-campaign {anchor} anchor")
    for line in missing:
        log(f"ANCHOR MISSING {line} -- that cell is NOT readable "
            f"(borrowing P2-T's row is forbidden: cross-campaign ratios drift ~30%)", out_dir)
    if not missing:
        log("ANCHOR ok: every s6 cell has both anchors re-run in THIS campaign", out_dir)
    return not missing


def catastrophic_flag(records, out_dir=OUT_DIR):
    """Flag (never drop) catastrophic seeds; per (seq, arm) median over completed seeds."""
    by = {}
    for r in records:
        if r.get("exit") != 0:
            continue
        by.setdefault((r["seq"], r["arm"]), []).append(r)
    for (seq, arm), rows in by.items():
        gs = [r["metrics"].get("refined_num_gaussians") for r in rows
              if r["metrics"].get("refined_num_gaussians") is not None]
        if not gs:
            continue
        med = st.median(gs)
        for r in rows:
            ate = r["metrics"].get("ate_rmse_cm")
            g = r["metrics"].get("refined_num_gaussians")
            if ((ate is not None and ate > CATASTROPHIC_ATE_CM)
                    or (g is not None and med > 0 and g > CATASTROPHIC_G_MULT * med)):
                log(f"CATASTROPHIC {seq}/{arm}/s{r['seed']}: ate={ate} G={g} "
                    f"(arm-med {med:.0f}) -- KEPT, flagged, not dropped", out_dir)


def seed0_signal(records, out_dir=OUT_DIR):
    """Information gate after batch 1. Reports; it does not decide and does not chain.

    A collapse here is not a verdict — it is the direction, at n=1, on the axis the frozen regime
    could not show. Whether it is worth 36 more runs to make it judgment-grade is the user's call.
    """
    per_arm = {}
    for r in records:
        if r.get("seed") != 0 or r.get("exit") != 0:
            continue
        ate = r["metrics"].get("ate_rmse_cm")
        if ate is not None and ate > STOPGO_ATE_CM:
            per_arm.setdefault(r["arm"], []).append(f"{r['seq']}({ate:.1f}cm)")
    for arm in ARM_ORDER:
        hits = per_arm.get(arm, [])
        log(f"SEED0 collapse (>{STOPGO_ATE_CM}cm) on {arm}: {len(hits)} seq"
            + (f" -- {', '.join(hits)}" if hits else ""), out_dir)
    s6_hits = len(per_arm.get("s6", []))
    if s6_hits >= STOPGO_COLLAPSE_COUNT:
        log(f"==== SEED0 SIGNAL: s6 collapsed on {s6_hits} seqs. Single seed => SCREENING, "
            f"NOT a verdict (discipline ⑤). Report to the user; batch 2 needs their GO. ====",
            out_dir)
    else:
        log("==== SEED0 SIGNAL: no widespread s6 collapse. Single seed => SCREENING, NOT a "
            "verdict (discipline ⑤). Report to the user; batch 2 needs their GO. ====", out_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", required=True,
                    choices=["dry", "seed0", "full", "resume", "report"])
    ap.add_argument("--seqs", nargs="+", default=None, help=f"default: {' '.join(SEQS)}")
    ap.add_argument("--arms", nargs="+", default=None, help=f"default: {' '.join(ARM_ORDER)}")
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    os.chdir(ROOT)
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    seqs = args.seqs or SEQS
    arms = args.arms or list(ARM_ORDER)
    unknown = [a for a in arms if a not in ARMS] + [s for s in seqs if s not in SEQS]
    if unknown:
        ap.error(f"unknown arm/seq {unknown}; arms={sorted(ARMS)} seqs={SEQS}")

    if args.phase == "report":
        return subprocess.call([PY, "scripts/p3_s6x_readout.py", "--out-dir", out_dir])

    # seq-major, arms back-to-back inside a (seq, seed): the three rows of one comparison run
    # under the same clock and the same live code, which is the point of re-running the anchors.
    def tranche(seeds):
        return [(seq, arm, seed) for seed in seeds for seq in seqs for arm in arms]

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()

    if args.phase == "dry":
        plan = tranche((0, 1, 2))
        print(f"# DRY RUN -- P3-S6X  commit={commit}"
              f"{'  WORKTREE DIRTY (commit before launching)' if dirty else ''}")
        print(f"# out_dir={out_dir}")
        print(f"# matrix: {len(seqs)} seqs x {len(arms)} arms x 3 seeds = {len(plan)} runs")
        print("# batch 1 = seed0 tranche (18 runs, ~9.5h on the 2060 at P2-T's measured "
              "~25-44 min/run); batch 2 = seeds 1,2 (36 runs) and needs the user's GO")
        print(f"# knob group under migration (by identity from SWEEP): {S6_KNOBS}")
        print("\n## planned runs (batch 1 first)")
        for seq, arm, seed in tranche((0,)):
            run_one(arm, seq, seed, out_dir, dry_run=True)
        print("\n## harness gates (assertions about the RUN, never about the hypothesis)")
        print("  G1 exit 0")
        print("  G2 SELF-TRACKED  : dumped config has empty Oracle.pose_file, gt_pose off, "
              f"cam lrs > 0, and ate != the injected constant {RGD_ATE_CM}")
        print("  G3 knobs live    : the config the run DUMPED carries the arm's knob values")
        print("  G4 rate exists   : refined_num_gaussians present")
        print("  G5 ATE exists    : ate_rmse_cm present (tracking_raw.csv, full trajectory)")
        print("  G6 support       : vacated support/frames non-zero")
        print("  G7 activity      : check_arm_activity not FAIL")
        print("  ANCHOR           : every s6 cell has BOTH anchors re-run in THIS campaign")
        print("## flagged, never dropped: ATE>100cm or G>3x arm-median")
        print("## decision rule: IMPORTED from scripts/r2_p03_sweep_readout.py "
              "(1.56cm / 0.28dB, rate-then-fidelity dominance) + the new ATE column")
        print("## pre-declared dispositions: results/evidence/p3_s6x_prereg.md §2 "
              "(fixed before run 1; not editable afterwards)")
        return 0

    if dirty:
        log(f"REFUSING to launch: worktree dirty at {commit}. Campaign discipline requires a "
            f"frozen commit before GPU (起跑前必须 commit).", out_dir)
        return 3

    if args.phase == "seed0":
        plan = tranche((0,))
    elif args.phase == "full":
        plan = tranche((1, 2))
    else:  # resume
        plan = tranche((0, 1, 2))

    log(f"==== P3-S6X phase={args.phase} commit={commit} seqs={seqs} arms={arms} "
        f"GPU={os.environ.get('CUDA_VISIBLE_DEVICES', '0')} ====", out_dir)

    already = done_triples(out_dir)
    records = []
    for seq, arm, seed in plan:
        if (arm, seq, seed) in already:
            log(f"SKIP {seq}/{arm}/s{seed}: already on disk with exit 0", out_dir)
            continue
        records.append(run_one(arm, seq, seed, out_dir))

    gate_records(records, out_dir)
    everything = load_records(out_dir)
    anchor_coverage(everything, out_dir)
    catastrophic_flag(everything, out_dir)
    if args.phase == "seed0":
        seed0_signal(everything, out_dir)
        log("Batch 1 complete. Run `--phase report`, report to the user, and STOP: batch 2 "
            "(seeds 1/2) is not launched from here (discipline ⑥ + ⑤).", out_dir)
    log(f"==== P3-S6X phase={args.phase} DONE ({len(records)} new run(s)) ====", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
