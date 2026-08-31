#!/usr/bin/env python3
"""P3-DENSIFY-TAIL: does densify_grad_threshold control the op<0.01 tail width?

Why this campaign exists
------------------------
``papers/mmm/mechanism.md`` §2 argues that the terminal-map op<0.01 tail is a steady-state
product of the ADC loop: each densify round clones/splits high-gradient Gaussians, the offspring
inherit the parent's opacity logit, and nothing globally re-opacifies them — so a lower densify
threshold (more spawns per round) should produce a WIDER tail, and a higher threshold a NARROWER
one. ``papers/mmm/theory.md`` proves the tail is zero-cost to delete (weight <1% / occlusion
<~1% / bounded mass).

This is the **predictive, mechanism-isolation** experiment: if the theory is correct, the
observable ``frac_op_lt_001`` (fraction of final-map Gaussians with sigmoid opacity < 0.01)
must move monotonically with the densify threshold. If it does, terminal compression stops being
"an observation with a plausible story" and becomes a *controlled* phenomenon with a *demonstrated*
cause — a qualitatively stronger paper. If it does not, the mechanism claim is falsified.

Three arms, differing ONLY in ``opt_params.densify_grad_threshold``:
    LO  = 0.0001  (half default)   -> predicted WIDER tail,  higher frac_op_lt_001
    BASE = 0.0002 (default)        -> reference (P2-T's prune arm, re-run here)
    HI  = 0.0005  (2.5x default)   -> predicted NARROWER tail, lower frac_op_lt_001

``BASE`` is P2-T's prune run config, imported by identity from ``scripts.r2_p2_t.ARMS`` (never
borrowed from P2-T's rows — same cross-campaign discipline as P3-S6X). ``LO``/``HI`` derive
from the same run config by ``inherit_from`` and add exactly the knife, so the resolved diff vs
BASE is structurally just the knob. ``tests/test_p3_densify_tail_configs.py`` pins all of it at E0.

Pre-registration (dispositions fixed before the first run): ``results/evidence/p3_densify_tail_prereg.md``.

Phases
------
  python scripts/p3_densify_tail.py --phase dry      # E0, no GPU
  python scripts/p3_densify_tail.py --phase seed0    # batch 1: 6 seqs × 3 arms × seed 0 = 18 runs
  python scripts/p3_densify_tail.py --phase full     # batch 2: seeds 1,2 = 36 runs (USER GO REQUIRED)
  python scripts/p3_densify_tail.py --phase resume   # re-run any (seq,arm,seed) not yet exit-0
  python scripts/p3_densify_tail.py --phase report   # no GPU — delegates to the readout

``--phase seed0`` deliberately does NOT chain into ``full``: single seed is screening and decides
nothing (discipline ⑤). GO/KILL remain the user's. This script prints measurements and gates only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.check_arm_activity import _load_config, _resolve_run_dir, check_run  # noqa: E402
from scripts.r2_p02_preflight_pose import PY, RGD_ATE_CM, parse_run  # noqa: E402
from scripts.r2_p03_sweep import check_config_echo  # noqa: E402
from scripts.r2_p2_t import ARMS as P2T_ARMS  # noqa: E402
from scripts.r2_p2_t import SEQS as P2T_SEQS  # noqa: E402

OUT_DIR = "results/runs/P3/P3-DENSIFY-TAIL"
RESULTS = "p3_densify_tail_results.jsonl"
TAIL = "configs/rgbd/experiments/p3_densify_tail"
DENSIFY = "opt_params.densify_grad_threshold"

# The three arms. LO/HI templates add exactly ONE knob over the P2-T prune anchor.
ARMS = {
    "lo": (f"{TAIL}/p3_densify_tail_lo_{{}}.yaml", {DENSIFY: 0.0001}),
    "base": (P2T_ARMS["prune"], {}),               # P2-T prune twin, by identity, RE-RUN here
    "hi": (f"{TAIL}/p3_densify_tail_hi_{{}}.yaml", {DENSIFY: 0.0005}),
}
ARM_ORDER = ("lo", "base", "hi")
SEQS = list(P2T_SEQS)  # identity with the main table's 6 dynamic sequences

CATASTROPHIC_ATE_CM = 100.0
CATASTROPHIC_G_MULT = 3.0
STOPGO_ATE_CM = 50.0
STOPGO_COLLAPSE_COUNT = 2


def log(msg, out_dir=OUT_DIR):
    line = f"[{time.strftime('%F %T')}] {msg}"
    print(line, flush=True)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "p3_densify_tail.log"), "a", encoding="utf-8") as f:
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
    """Same inverted pose gate as P3-S6X: prove the run tracked for itself."""
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


def find_final_ply(run_root):
    """Locate the final_after_opt point_cloud.ply under a run root (or None)."""
    resolved = _resolve_run_dir(run_root)
    if resolved is None:
        return None
    cand = os.path.join(resolved, "point_cloud", "final_after_opt", "point_cloud.ply")
    return cand if os.path.isfile(cand) else None


def opacity_stats(ply, config):
    """Load a final PLY and return the sigmoid-opacity tail fractions (zero-GPU-ish, CUDA load).

    Uses the GaussianModel loader + get_opacity(sigmoid), matching mc_terminal_comp_3seed.py.
    Requires the run's dumped config for sh_degree. Returns a dict of fractions.
    """
    from gaussian_splatting.scene.gaussian_model import GaussianModel  # local to avoid top-load
    from munch import munchify
    import torch

    sh_degree = 3 if config.get("Training", {}).get("spherical_harmonics") else 0
    model = GaussianModel(sh_degree, config=config)
    model.load_ply(ply)
    sig = torch.sigmoid(model._opacity).reshape(-1).detach().float()
    n = int(sig.shape[0])
    if n == 0:
        return {"n_total": 0, "frac_op_lt_001": float("nan"), "frac_op_lt_005": float("nan"),
                "frac_op_lt_010": float("nan"), "frac_op_ge_090": float("nan")}
    def frac(th):
        return float((sig < th).float().mean().item())
    return {
        "n_total": n,
        "frac_op_lt_001": round(frac(0.01), 6),
        "frac_op_lt_005": round(frac(0.05), 6),
        "frac_op_lt_010": round(frac(0.10), 6),
        "frac_op_ge_090": round(float((sig >= 0.90).float().mean().item()), 6),
    }


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
    ply = find_final_ply(run_root)
    op_stats = None
    if ply is not None:
        config_dump = _load_config(_resolve_run_dir(run_root)) or {}
        try:
            op_stats = opacity_stats(ply, config_dump)
        except Exception as exc:
            op_stats = {"error": str(exc)}
    record = {
        "arm": arm, "seq": seq, "seed": seed, "config": config, "knobs": knobs,
        "exit": code, "minutes": round(minutes, 1), "run_dir": run_root,
        "self_tracked": self_ok, "self_tracked_detail": self_detail,
        "config_echo_ok": echo_ok, "config_echo": echo_detail,
        "activity_verdict": verdict, "activity_detail": detail,
        "opacity_stats": op_stats,
        "metrics": metrics,
    }
    with open(os.path.join(out_dir, RESULTS), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    lt = op_stats.get("frac_op_lt_001") if op_stats else None
    log(f"END   {tag} exit={code} {minutes:.1f}min G={metrics.get('refined_num_gaussians')} "
        f"ate={ate} frac_lt_001={lt} "
        f"self_tracked={self_ok} config_echo={'ok' if echo_ok else 'FAIL: ' + echo_detail}",
        out_dir)
    return record


def gate_records(records, out_dir=OUT_DIR, fatal=False):
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
            bad.append("G4 no refined_num_gaussians")
        if not r.get("opacity_stats"):
            bad.append("G5 no opacity_stats (final PLY missing or unreadable)")
        if r["activity_verdict"] == "FAIL":
            bad.append(f"G6 activity={r['activity_detail']}")
        if bad:
            ok = False
            log(f"GATE FAIL {tag}: " + " | ".join(bad), out_dir)
        else:
            log(f"GATE ok   {tag}: G={m.get('refined_num_gaussians')} "
                f"ate={m.get('ate_rmse_cm')} frac_lt_001="
                f"{r['opacity_stats'].get('frac_op_lt_001')} {r['config_echo']}", out_dir)
    if not ok and fatal:
        log("==== ABORT: a harness gate failed. ====", out_dir)
    return ok


def anchor_coverage(records, out_dir=OUT_DIR):
    """Every (seq, seed) with a lo/hi cell must ALSO have base in THIS campaign."""
    have = {(r["seq"], r["arm"], r["seed"]) for r in records if r.get("exit") == 0}
    missing = []
    for seq, arm, seed in sorted(have):
        if arm == "base":
            continue
        if (seq, "base", seed) not in have:
            missing.append(f"{seq}/s{seed}: no in-campaign base anchor for {arm} cell")
    for line in missing:
        log(f"ANCHOR MISSING {line} -- that cell is NOT readable "
            f"(borrowing P2-T's row is forbidden: cross-campaign ratios drift ~30%)", out_dir)
    if not missing:
        log("ANCHOR ok: every lo/hi cell has the base anchor re-run in THIS campaign", out_dir)
    return not missing


def catastrophic_flag(records, out_dir=OUT_DIR):
    by = {}
    for r in records:
        if r.get("exit") != 0:
            continue
        by.setdefault((r["seq"], r["arm"]), []).append(r)
    import statistics as st
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
    tot = []
    for arm in ("lo", "hi"):
        tot += per_arm.get(arm, [])
    if len(tot) >= STOPGO_COLLAPSE_COUNT:
        log("==== SEED0 SIGNAL: lo/hi collapsed on >=2 seqs. Single seed => SCREENING, "
            "NOT a verdict (discipline ⑤). Report; batch 2 needs user GO. ====", out_dir)
    else:
        log("==== SEED0 SIGNAL: no widespread lo/hi collapse. Single seed => SCREENING, "
            "NOT a verdict (discipline ⑤). Report; batch 2 needs user GO. ====", out_dir)


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
        return subprocess.call([PY, "scripts/p3_densify_tail_readout.py", "--out-dir", out_dir])

    def tranche(seeds):
        return [(seq, arm, seed) for seed in seeds for seq in seqs for arm in arms]

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()

    if args.phase == "dry":
        plan = tranche((0, 1, 2))
        print(f"# DRY RUN -- P3-DENSIFY-TAIL  commit={commit}"
              f"{'  WORKTREE DIRTY (commit before launching)' if dirty else ''}")
        print(f"# out_dir={out_dir}")
        print(f"# matrix: {len(seqs)} seqs x {len(arms)} arms x 3 seeds = {len(plan)} runs")
        print("# batch 1 = seed0 (18 runs, ~9h on 2060); batch 2 = seeds 1,2 (36 runs) "
              "needs user GO")
        print("\n## planned runs (seed0 first)")
        for seq, arm, seed in tranche((0,)):
            run_one(arm, seq, seed, out_dir, dry_run=True)
        print("\n## harness gates")
        print("  G1 exit 0 / G2 self-tracked / G3 knobs live / G4 rate exists")
        print("  G5 opacity_stats present (final_after_opt PLY read) / G6 activity not FAIL")
        print("  ANCHOR: every lo/hi cell has an in-campaign base anchor")
        print("## decision rule: results/evidence/p3_densify_tail_prereg.md §2.4 "
              "(CONFIRMED / PARTIAL / FALSIFIED per seq, monotone in frac_op_lt_001)")
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

    log(f"==== P3-DENSIFY-TAIL phase={args.phase} commit={commit} seqs={seqs} arms={arms} "
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
    log(f"==== P3-DENSIFY-TAIL phase={args.phase} DONE ({len(records)} new run(s)) ====", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
