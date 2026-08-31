#!/usr/bin/env python3
"""P2-RT spike — does the PROBE2-RT ReliableTracking (RGD adaptive-weight) ATE win
reproduce on the CURRENT combined maskboth prune backbone?

PROBE2-RT (results/evidence/probe2_reliable_tracking.md, 2026-07-23) screened
ReliableTracking OFF↔ON on the *open-set* prune base and got variance-separated
ATE wins (balloon −41%, mv_no_box −45/−51%, pt2 −42%). But ReliableTracking is
NOT enabled in the paper main-table backbone (method_combined_maskboth_prune →
base_config ReliableTracking.enabled: false); P2-T was measured WITHOUT it.
Whether the win transfers to the maskboth backbone is untested. This spike runs
the RT-on twin on the 3 PROBE2-RT win sequences (balloon / mv_no_box / pt1) at
seed 0 and compares ATE to the P2-T prune control (2.87 / 2.58 / 10.97 cm).

Single seed ⇒ SCREENING ONLY (incubation rule ⑤). No verdict written from this.
The control numbers are IMPORTED from P2-T (already 3-seed, same backbone minus
the RT knob) — no GPU spent re-running the control.

Phases
------
  python scripts/r2_p2_rt_spike.py --phase dry      # print the plan, no GPU
  python scripts/r2_p2_rt_spike.py --phase run      # 3 runs (balloon/mv_no_box/pt1 seed0)
  python scripts/r2_p2_rt_spike.py --phase report   # no GPU — ATE table vs P2-T control
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

from scripts.r2_p02_preflight_pose import parse_run  # noqa: E402

PY = "/data/conda_envs/monogs-ours/bin/python"
OUT_DIR = "results/runs/P2/P2-RT-SPIKE"
RESULTS = "p2rt_spike_results.jsonl"
P2 = "configs/rgbd/experiments/p2_render"

# RT-on twin configs (method_combined_maskboth_prune_rton). Sequence → config.
SEQS = {
    "balloon": f"{P2}/p2s_combined_prune_rton_balloon.yaml",
    "mv_no_box": f"{P2}/p2s_combined_prune_rton_mv_no_box.yaml",
    "pt1": f"{P2}/p2s_combined_prune_rton_pt1.yaml",
}

# P2-T prune control ATE (cm), 3-seed mean ± sd (p2t_verdict_final.md).
# These are the numbers to beat / match; IMPORTED, not re-run.
CONTROL_ATE = {
    "balloon": {"mean": 3.07, "sd": 0.14, "seed0": 2.8686},
    "mv_no_box": {"mean": 2.58, "sd": 0.05, "seed0": 2.515},
    "pt1": {"mean": 10.97, "sd": 0.03, "seed0": 11.0087},
}

# PROBE2-RT open-set base win magnitudes (for "does it transfer" reference, NOT the gate).
PROBE2_OPENSEET_WIN = {
    "balloon": -0.41,
    "mv_no_box": -0.45,
    "pt1": None,  # PROBE2 used pt2 not pt1; pt1 is the proxy here
}


def run_one(seq, seed, out_dir=OUT_DIR, dry_run=False):
    config = SEQS[seq]
    tag = f"{seq}_prune_rton_seed{seed}"
    run_root = os.path.join(out_dir, tag)
    console = os.path.join(out_dir, f"{tag}.consolelog")
    cmd = [PY, "slam.py", "--config", config, "--eval",
           "--seed", str(seed), "--results-root", run_root]
    if dry_run:
        print(f"  {' '.join(cmd)}")
        return {"seq": seq, "seed": seed, "cmd": cmd, "dry_run": True, "config": config}

    os.makedirs(out_dir, exist_ok=True)
    print(f"START {tag} -> {run_root}", flush=True)
    env = dict(os.environ)
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    env.pop("PYTORCH_CUDA_ALLOC_CONF", None)  # crashes MonoGS multiprocess CUDA sharing
    started = time.time()
    with open(console, "w", encoding="utf-8") as log_file:
        code = subprocess.call(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=env)
    minutes = (time.time() - started) / 60.0

    metrics = parse_run(run_root)
    ate = metrics.get("ate_rmse_cm")
    record = {
        "seq": seq, "seed": seed, "config": config, "exit": code,
        "minutes": round(minutes, 1), "run_dir": run_root, "metrics": metrics,
    }
    with open(os.path.join(out_dir, RESULTS), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    print(f"END   {tag} exit={code} {minutes:.1f}min ate={ate} "
          f"G={metrics.get('refined_num_gaussians')}", flush=True)
    return record


def report(out_dir=OUT_DIR):
    path = os.path.join(out_dir, RESULTS)
    if not os.path.isfile(path):
        print("no runs yet")
        return 1
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    print("\n=== P2-RT spike: ReliableTracking ON vs P2-T prune control (seed0) ===\n")
    print(f"{'seq':<12} {'RT-on ate':>10} {'control mean±sd':>18} {'control seed0':>14} {'Δ vs mean':>10}")
    print("-" * 70)
    for r in records:
        seq = r["seq"]
        ate = r["metrics"].get("ate_rmse_cm")
        ctrl = CONTROL_ATE.get(seq, {})
        cm, cs = ctrl.get("mean"), ctrl.get("sd")
        c0 = ctrl.get("seed0")
        delta = f"{(ate - cm):+.2f}" if (ate is not None and cm is not None) else "n/a"
        print(f"{seq:<12} {str(ate):>10} {f'{cm}±{cs}' if cm else 'n/a':>18} "
              f"{str(c0):>14} {delta:>10}")
    print("\nSingle seed ⇒ SCREENING ONLY. Direction reference (not gate): "
          "PROBE2 open-set wins balloon −41%, mv_no_box −45%.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--phase", choices=["dry", "run", "report"], default="dry")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if args.phase == "dry":
        print("=== P2-RT spike plan (3 runs, seed0) ===")
        for seq in SEQS:
            run_one(seq, args.seed, dry_run=True)
        print(f"\nControl (IMPORTED from P2-T, no GPU): {CONTROL_ATE}")
        return 0
    if args.phase == "run":
        os.makedirs(OUT_DIR, exist_ok=True)
        for seq in SEQS:
            run_one(seq, args.seed)
        return report()
    if args.phase == "report":
        return report()


if __name__ == "__main__":
    sys.exit(main())
