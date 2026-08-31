#!/usr/bin/env python3
"""R2-P02-T (P2-T): the paper's main table, full-SLAM self-tracked, combined backbone.

This is NOT a screening run. It is the table that goes in the paper: 7 Bonn sequences × 2
lifecycle arms (prune / deferred) × 3 seeds, all self-tracked (``Oracle.pose_file=""``,
non-zero camera learning rates — amendment #01 §4 forbids a frozen-pose main table).

The two arms differ ONLY in ``Mapping.lifecycle_mode`` (the combined backbone's own twin;
``tests/test_p2_combined_twin_configs.py`` + ``tests/test_r2_p2_t_configs.py`` pin this).
Every main-table difference is therefore attributable to the lifecycle, not to tracking /
masking / keyframing / window differences that happened to travel with it.

It also serves, as a side effect and at no extra GPU cost, as the prospective internal check
for the H-D hypothesis (``results/evidence/hd_coverage_prereg.md``): the per-sequence
G_def/G_prune ratio is read against the pre-frozen coverage rank
(``results/evidence/hd_coverage_anchor.md``). H-D is NOT a verdict here; the readout reports
the ratio + branch per seq, the three-branch H-D call is made by the user from the prereg.

Pre-declared before any GPU time (committed before the first run):
  * the arm/sequence/seed matrix (``ARMS``, ``SEQS``);
  * the decision family and margins — IMPORTED from the SWEEP readout (1.56 cm / 0.28 dB),
    not copied, so the口径 cannot drift from the four R2-P03 campaigns;
  * the G_def/G_prune ratio + rate-noise-band indeterminacy rule;
  * the catastrophic-run rule (§7 of the H-D prereg): exploded seeds are KEPT, shown per-seed,
    never silently dropped; seed-0 tranche runs first with a stop/go checkpoint.

Phases
------
  python scripts/r2_p2_t.py --phase dry       # E0, no GPU — prints the plan + gates
  python scripts/r2_p2_t.py --phase seed0     # 7 seqs × 2 arms × seed 0 (14 runs) + stop/go
  python scripts/r2_p2_t.py --phase full       # remaining seeds 1,2 (28 runs)
  python scripts/r2_p2_t.py --phase resume     # re-run any (arm,seq,seed) not yet exit-0
  python scripts/r2_p2_t.py --phase report     # no GPU — delegates to the readout

GO/KILL + narrative remain the user's (prereg §9). This script prints measurements and
mechanical gate verdicts only.
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

# Same metric口径 as every R2-P03 campaign: import, do not copy.
from scripts.r2_p02_preflight_pose import parse_run  # noqa: E402
from scripts.check_arm_activity import check_run  # noqa: E402

PY = "/data/conda_envs/monogs-ours/bin/python"
OUT_DIR = "results/runs/P2/P2-T"
RESULTS = "p2t_results.jsonl"
P2 = "configs/rgbd/experiments/p2_render"

# --- the matrix -----------------------------------------------------------------------
# prune / deferred are the combined backbone's own twin (lifecycle is the ONLY diff).
# 6 dynamic seqs (the H-D coverage set) + f1_desk static sanity (no mover => coverage
# undefined, excluded from H-D, kept in the main table per 02-method P2).
ARMS = {
    "prune": f"{P2}/p2s_combined_prune_{{}}.yaml",
    "deferred": f"{P2}/p2s_combined_deferred_{{}}.yaml",
}
SEQS = ["balloon", "balloon2", "mv_no_box", "mv_no_box2", "pt1", "pt2"]
STATIC_SEQ = "f1_desk"  # TUM fr1_desk via the same backbone — static no-harm row

# f1_desk uses a TUM base config, not a Bonn one. The combined backbone run config for it
# does not exist yet under p2_render/; if it is missing at launch, seed0 reports it and the
# main table proceeds with the 6 dynamic seqs (static row is a no-harm add-on, not load-bearing).
F1DESK_CFG = {  # resolved later; placeholder keys filled by _resolve_static()
    "prune": None,
    "deferred": None,
}

# Catastrophic-run thresholds (prereg §7). A seed is flagged CATASTROPHIC but KEPT.
CATASTROPHIC_ATE_CM = 100.0
CATASTROPHIC_G_MULT = 3.0  # G > 3× that seq's arm-median => flagged
# seed-0 stop/go: if >= this many seqs' backbone collapses (non-catastrophic ATE>50cm) on
# seed0, stop and report rather than blindly spending the remaining ~14h.
STOPGO_COLLAPSE_COUNT = 2
STOPGO_ATE_CM = 50.0


def log(msg, out_dir=OUT_DIR):
    line = f"[{time.strftime('%F %T')}] {msg}"
    print(line, flush=True)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "p2t.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _resolve_static():
    """Locate f1_desk run configs if they exist; else leave None (main table drops the row)."""
    cand = {
        "prune": "configs/rgbd/experiments/p2_render/p2s_combined_prune_f1_desk.yaml",
        "deferred": "configs/rgbd/experiments/p2_render/p2s_combined_deferred_f1_desk.yaml",
    }
    for arm, path in cand.items():
        if os.path.isfile(path):
            F1DESK_CFG[arm] = path


def seq_cfg(arm, seq):
    if seq == STATIC_SEQ:
        _resolve_static()
        cfg = F1DESK_CFG[arm]
        if cfg is None:
            return None
        return cfg
    return ARMS[arm].format(seq)


def done_pairs(out_dir=OUT_DIR):
    return {(r["arm"], r["seq"], r["seed"]) for r in load_records(out_dir) if r.get("exit") == 0}


def load_records(out_dir=OUT_DIR):
    path = os.path.join(out_dir, RESULTS)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run_one(arm, seq, seed, out_dir=OUT_DIR, dry_run=False):
    config = seq_cfg(arm, seq)
    tag = f"{seq}_{arm}_seed{seed}"
    run_root = os.path.join(out_dir, tag)
    console = os.path.join(out_dir, f"{tag}.consolelog")
    cmd = [PY, "slam.py", "--config", config, "--eval",
           "--seed", str(seed), "--results-root", run_root]
    if dry_run:
        print(f"  {' '.join(cmd)}")
        return {"arm": arm, "seq": seq, "seed": seed, "cmd": cmd, "dry_run": True,
                "config": config}

    log(f"START {tag} -> {run_root}", out_dir)
    env = dict(os.environ)
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    env.pop("PYTORCH_CUDA_ALLOC_CONF", None)  # crashes MonoGS multiprocess CUDA sharing
    started = time.time()
    with open(console, "w", encoding="utf-8") as log_file:
        code = subprocess.call(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=env)
    minutes = (time.time() - started) / 60.0

    metrics = parse_run(run_root)
    verdict, detail = check_run(run_root)
    ate = metrics.get("ate_rmse_cm")
    record = {
        "arm": arm, "seq": seq, "seed": seed, "config": config, "exit": code,
        "minutes": round(minutes, 1), "run_dir": run_root,
        "activity_verdict": verdict, "activity_detail": detail, "metrics": metrics,
    }
    with open(os.path.join(out_dir, RESULTS), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    log(f"END   {tag} exit={code} {minutes:.1f}min G={metrics.get('refined_num_gaussians')} "
        f"ate={ate} vac_depth={metrics.get('static_vacated_depth_l1_pen_cm')} "
        f"vac_psnr={metrics.get('static_vacated_psnr')} activity={verdict}", out_dir)
    return record


def gate_records(records, out_dir=OUT_DIR, fatal=True):
    """HARNESS assertions only. A run that loses fidelity is a RESULT, never an abort."""
    ok = True
    for r in records:
        tag = f"{r['seq']}/{r['arm']}/s{r['seed']}"
        m = r["metrics"]
        if r["exit"] != 0:
            log(f"GATE FAIL {tag}: exit={r['exit']}", out_dir)
            ok = False
        # activity: prune/deferred arms have no AlphaLifecycle => SKIP is correct; only FAIL aborts
        if r["activity_verdict"] == "FAIL":
            log(f"GATE FAIL {tag}: activity={r['activity_detail']}", out_dir)
            ok = False
        if m.get("refined_num_gaussians") is None:
            log(f"GATE FAIL {tag}: no refined_num_gaussians", out_dir)
            ok = False
        if ok:
            log(f"GATE ok   {tag}: G={m.get('refined_num_gaussians')} ate={m.get('ate_rmse_cm')} "
                f"activity={r['activity_verdict']}", out_dir)
    if not ok and fatal:
        log("==== ABORT: a harness gate failed. A main table on a harness that did not do what "
            "the config says answers nothing. ====", out_dir)
    return ok


def catastrophic_flag(records, out_dir=OUT_DIR):
    """Flag (not drop) catastrophic seeds. Per-seq, per-arm median over completed seeds."""
    by = {}
    for r in records:
        if r.get("exit") != 0:
            continue
        by.setdefault((r["seq"], r["arm"]), []).append(r)
    for (seq, arm), rs in by.items():
        gs = [r["metrics"].get("refined_num_gaussians") for r in rs
              if r["metrics"].get("refined_num_gaussians") is not None]
        if not gs:
            continue
        med = st.median(gs)
        for r in rs:
            ate = r["metrics"].get("ate_rmse_cm")
            g = r["metrics"].get("refined_num_gaussians")
            cat = ((ate is not None and ate > CATASTROPHIC_ATE_CM) or
                   (g is not None and med > 0 and g > CATASTROPHIC_G_MULT * med))
            if cat:
                log(f"CATASTROPHIC {seq}/{arm}/s{r['seed']}: ate={ate} G={g} "
                    f"(arm-med {med:.0f}) — KEPT, flagged, not dropped", out_dir)


def seed0_stopgo(records, out_dir=OUT_DIR):
    """After the seed-0 tranche: if >=2 seqs collapsed (non-catastrophic ATE>50cm), stop."""
    collapses = 0
    for r in records:
        if r.get("seed") != 0 or r.get("exit") != 0:
            continue
        ate = r["metrics"].get("ate_rmse_cm")
        if ate is not None and ate > STOPGO_ATE_CM:
            collapses += 1
    if collapses >= STOPGO_COLLAPSE_COUNT:
        log(f"==== STOP/GO: {collapses} seqs collapsed (ATE>{STOPGO_ATE_CM}cm) on seed0 — "
            f"STOPPING before seeds 1/2. Report and let the user decide. ====", out_dir)
        return False
    log(f"==== STOP/GO: {collapses} seq collapse(s) on seed0 (threshold {STOPGO_COLLAPSE_COUNT}) "
        f"— PROCEED to seeds 1/2. ====", out_dir)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", required=True,
                    choices=["dry", "seed0", "full", "resume", "report"])
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--seed0-only-check", action="store_true",
                    help="re-run the stop/go verdict on existing seed0 records (no new runs)")
    args = ap.parse_args()
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    if args.phase == "report":
        return subprocess.call([PY, "scripts/r2_p2_t_readout.py", "--out-dir", out_dir])

    # the full plan: arm-major within each (seq, seed) so the twin pair runs back-to-back
    # (same live-code state, minimal clock drift between the two halves of a comparison)
    plan = [(seq, arm, seed)
            for seed in (0, 1, 2)
            for seq in (SEQS + ([STATIC_SEQ] if F1DESK_CFG.get("prune") else []))
            for arm in ("prune", "deferred")]

    if args.phase == "dry":
        _resolve_static()
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        print(f"# DRY RUN -- P2-T  commit={commit}"
              f"{'  WORKTREE DIRTY (commit before launching)' if dirty else ''}")
        print("# out_dir="+str(out_dir))  # noqa: F541
        print("# plan: 6 dyn seqs x 2 arms x 3 seeds = 36 runs (+static row if config exists)")
        print("# est ~21-25 h on 2060 (self-track ~25-28 min/run x 42, +teardown flake)")
        print("\n## planned runs (seed0 tranche first):")
        for seq, arm, seed in plan:
            run_one(arm, seq, seed, out_dir, dry_run=True)
        print("\n## gates (harness only): exit0 / activity not FAIL / refined_num_gaussians present")
        print("## stop/go: seed0 tranche — >=2 seqs ATE>50cm (non-catastrophic) => STOP")
        print("## catastrophic: ATE>100cm or G>3x arm-median => flagged + KEPT")
        print("## decision rule (imported): scripts/r2_p2_t_readout.py "
              "(margins 1.56cm/0.28dB, rate-then-fidelity dominance)")
        return 0

    if args.phase == "seed0-only-check":
        recs = load_records(out_dir)
        seed0_stopgo([r for r in recs if r.get("seed") == 0], out_dir)
        return 0

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        log(f"REFUSING to launch: worktree dirty at {commit}. Campaign discipline requires a "
            f"frozen commit before GPU (起跑前必须 commit).", out_dir)
        return 3

    already = done_pairs(out_dir)
    _resolve_static()

    if args.phase == "seed0":
        tranche = [(seq, arm, 0) for seq in (SEQS + ([STATIC_SEQ] if F1DESK_CFG.get("prune") else []))
                   for arm in ("prune", "deferred")]
    elif args.phase == "full":
        tranche = [(seq, arm, seed) for seed in (1, 2)
                   for seq in (SEQS + ([STATIC_SEQ] if F1DESK_CFG.get("prune") else []))
                   for arm in ("prune", "deferred")]
    else:  # resume
        tranche = plan

    log(f"==== P2-T phase={args.phase} commit={commit} "
        f"GPU={os.environ.get('CUDA_VISIBLE_DEVICES', '0')} ====", out_dir)

    records = []
    for seq, arm, seed in tranche:
        if (arm, seq, seed) in already:
            log(f"SKIP {seq}/{arm}/s{seed}: already exit 0", out_dir)
            continue
        records.append(run_one(arm, seq, seed, out_dir))

    gate_records(records, out_dir, fatal=False)
    catastrophic_flag(load_records(out_dir), out_dir)
    if args.phase == "seed0":
        proceed = seed0_stopgo(load_records(out_dir), out_dir)
        if not proceed:
            log("Seed-0 stop/go triggered. Run `--phase report` and report to user before "
                "spending seeds 1/2.", out_dir)
            return 4
    log(f"==== P2-T phase={args.phase} DONE ({len(records)} new run(s)) ====", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
