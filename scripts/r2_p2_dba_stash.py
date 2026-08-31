#!/usr/bin/env python3
"""P2-DBAphoto step1 — populate exact-online reliability weights for the DBA-lite
reliability-weighted geometric oracle (the real gate, per consult_codex_dbaphoto_design.md).

WHY. The original DBA oracle's photometric proxy is an UNWEIGHTED median grayscale
residual — it does not consume the reliability weight w. Codex's review (019fc47b)
established: (1) the offline-recompute-from-final-PLY path is fatally biased (map
co-adapts the online trajectory → uninterpretable gate); (2) the premise "reliability-
weighted photo-BA is a NEW objective" is FALSE — online already weights RGB+depth by
static_conf=(1-strength·(1-w)) (slam_utils.py:447). The genuinely-missing, NON-redundant
term is reliability-weighted GEOMETRY: DBA's KF-KF point-to-plane edge
(_edge_two_sided, dba_lite.py:179) has only residual-MAD robust weight, NEVER reliability.

So the real gate is: does the reliability-weighted GEOMETRIC objective prefer GT?
This script runs the stash apparatus (method_combined_maskboth_prune + stash_dba_weights)
to persist the EXACT online w_map + warmup render context per frame, so DBA-lite can
re-run the weighted-geometric oracle on the same weights the online tracker froze.

Phases
------
  python scripts/r2_p2_dba_stash.py --phase dry       # print the plan, no GPU
  python scripts/r2_p2_dba_stash.py --phase run       # 2 seqs x 2 seeds = 4 runs
  python scripts/r2_p2_dba_stash.py --phase report    # no GPU — verify snapshots written
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

PY = "/data/conda_envs/monogs-ours/bin/python"
OUT_DIR = "results/runs/P2/P2-DBA-STASH"
RESULTS = "p2dba_stash_results.jsonl"
P2 = "configs/rgbd/experiments/p2_render"

# 2 seqs (codex: >=2 seq for the gate) x 2 seeds (codex: >=2 seed).
SEQS = {
    "balloon": f"{P2}/p2s_combined_prune_dba_stash_balloon.yaml",
    "mv_no_box": f"{P2}/p2s_combined_prune_dba_stash_mv_no_box.yaml",
}
SEEDS = [0, 1]


def run_one(seq, seed, out_dir=OUT_DIR, dry_run=False):
    config = SEQS[seq]
    tag = f"{seq}_prune_dbastash_seed{seed}"
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
    env.pop("PYTORCH_CUDA_ALLOC_CONF", None)
    started = time.time()
    with open(console, "w", encoding="utf-8") as log_file:
        code = subprocess.call(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=env)
    minutes = (time.time() - started) / 60.0

    # verify snapshots were written
    snap_dir = None
    n_snaps = 0
    for root, _dirs, files in os.walk(run_root):
        if os.path.basename(root) == "dba_weight_snapshots":
            snap_dir = root
            n_snaps = sum(1 for f in files if f.endswith("_w.npy"))
            break
    ate = None
    try:
        trj = os.path.join(run_root, "tables", "tracking_raw.csv")
        if os.path.isfile(trj):
            import csv
            with open(trj) as f:
                r = list(csv.DictReader(f))
            if r:
                try:
                    ate = float(r[0].get("ate_rmse_cm"))
                except (TypeError, ValueError):
                    ate = None
    except Exception:
        pass
    record = {
        "seq": seq, "seed": seed, "config": config, "exit": code,
        "minutes": round(minutes, 1), "run_dir": run_root,
        "snap_dir": snap_dir, "n_snapshots": n_snaps, "ate_rmse_cm": ate,
    }
    with open(os.path.join(out_dir, RESULTS), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    print(f"END   {tag} exit={code} {minutes:.1f}min ate={ate} snaps={n_snaps}", flush=True)
    return record


def report(out_dir=OUT_DIR):
    path = os.path.join(out_dir, RESULTS)
    if not os.path.isfile(path):
        print("no runs yet")
        return 1
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    print("\n=== P2-DBAphoto step1: exact-online w_map stash ===\n")
    print(f"{'seq':<12} {'seed':>4} {'exit':>4} {'ate':>8} {'snaps':>6} {'min':>6}")
    print("-" * 48)
    for r in records:
        print(f"{r['seq']:<12} {r['seed']:>4} {r['exit']:>4} "
              f"{str(r.get('ate_rmse_cm')):>8} {r.get('n_snapshots', 0):>6} "
              f"{r.get('minutes', 0):>6}")
    n_ok = sum(1 for r in records if r["exit"] == 0 and r.get("n_snapshots", 0) > 0)
    print(f"\n{n_ok}/{len(records)} runs OK with snapshots. "
          f"Next: reliability-weighted geometric oracle on these stashed weights.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--phase", choices=["dry", "run", "report"], default="dry")
    args = parser.parse_args()
    if args.phase == "dry":
        print("=== P2-DBAphoto step1 stash plan (2 seqs x 2 seeds = 4 runs) ===")
        for seq in SEQS:
            for seed in SEEDS:
                run_one(seq, seed, dry_run=True)
        return 0
    if args.phase == "run":
        os.makedirs(OUT_DIR, exist_ok=True)
        for seq in SEQS:
            for seed in SEEDS:
                run_one(seq, seed)
        return report()
    if args.phase == "report":
        return report()


if __name__ == "__main__":
    sys.exit(main())
