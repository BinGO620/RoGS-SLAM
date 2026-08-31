#!/usr/bin/env python3
"""P2-SF self-frozen de-confounding control runner.

Resolves variant C's sentinel ``__PRUNE_TRAJ__`` per (seq, seed) to the P2-T prune run's
``trj_full_final.json``, writes a resolved config into the run dir, and calls ``slam.py``.
Variant B (GT-pose) has no sentinel and is called directly on its base config.

Matrix (seed-0 screening first):
  * variants: C (prune-trajectory injection, PRIMARY branch) + B (GT-pose, SENSITIVITY)
  * arms: prune, deferred (lifecycle is the ONLY diff within a variant)
  * seqs: pt1 (hard-tracking + moderate-cov), balloon2 (easy-tracking + highest-cov)
  * seeds: 0 first; expand to 1,2 only if MAP-EFFECT/REVERSED fires

  python scripts/r2_p2_sf.py --phase seed0   # 2 seqs x {C,B} x 2 arms x seed 0 = 8 runs
  python scripts/r2_p2_sf.py --phase full     # seeds 1,2 (16 runs) — only after seed-0 readout
  python scripts/r2_p2_sf.py --phase resume   # re-run any (variant,arm,seq,seed) not yet exit-0

Observables (map-level, NOT ATE — ATE is a construction canary under frozen pose):
  * PRIMARY: refined_num_gaussians -> R_G^F = G_def^F / G_prune^F (paired-seed log-ratio)
  * GUARDRAIL: vac_depth (<=1.56cm), vac_psnr (<=0.28dB) — inherited from r2_p03_sweep_readout
  * ATE: canary only (identical across arms by construction; reported but not an outcome)

See results/evidence/p2sf_selffrozen_prereg.md + consult_synthesis_selffrozen.md.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PY = "/data/conda_envs/monogs-ours/bin/python"
OUT_DIR = "results/runs/P2/P2-SF"
RESULTS = "p2sf_results.jsonl"
P2T_DIR = "results/runs/P2/P2-T"
SENTINEL = "__PRUNE_TRAJ__"

P2 = "configs/rgbd/experiments/p2_render"

# (variant, arm, seq) -> base config path
CONFIGS = {
    ("c", "prune", "pt1"): f"{P2}/p2sf_c_prune_pt1.yaml",
    ("c", "deferred", "pt1"): f"{P2}/p2sf_c_deferred_pt1.yaml",
    ("c", "prune", "balloon2"): f"{P2}/p2sf_c_prune_balloon2.yaml",
    ("c", "deferred", "balloon2"): f"{P2}/p2sf_c_deferred_balloon2.yaml",
    ("b", "prune", "pt1"): f"{P2}/p2sf_b_prune_pt1.yaml",
    ("b", "deferred", "pt1"): f"{P2}/p2sf_b_deferred_pt1.yaml",
    ("b", "prune", "balloon2"): f"{P2}/p2sf_b_prune_balloon2.yaml",
    ("b", "deferred", "balloon2"): f"{P2}/p2sf_b_deferred_balloon2.yaml",
}
SEQS = ["pt1", "balloon2"]
VARIANTS = ["c", "b"]
ARMS = ["prune", "deferred"]

# prune trj_full_final.json location pattern per (seq, seed)
PRUNE_TRAJ_DIRNAME = {
    "pt1": "p2s_combined_prune_pt1",
    "balloon2": "p2s_combined_prune_balloon2",
}


def log(msg, out_dir=OUT_DIR):
    line = f"[{time.strftime('%F %T')}] {msg}"
    print(line, flush=True)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "p2sf.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def resolve_prune_traj(seq, seed):
    """Find the P2-T prune run's trj_full_final.json for (seq, seed)."""
    pattern = os.path.join(
        P2T_DIR, f"{seq}_prune_seed{seed}", "datasets_bonn",
        PRUNE_TRAJ_DIRNAME[seq], f"seed_{seed}", "*", "plot", "trj_full_final.json")
    matches = glob.glob(pattern)
    if not matches:
        return None
    return matches[0]


def resolve_config(variant, arm, seq, seed, run_root):
    """For variant C, write a resolved config with the real pose_file into run_root.
    For variant B, return the base config path (no sentinel)."""
    base = CONFIGS[(variant, arm, seq)]
    if variant == "b":
        return base
    # variant C: resolve sentinel
    traj = resolve_prune_traj(seq, seed)
    if traj is None:
        raise FileNotFoundError(
            f"no prune trj_full_final.json for {seq} seed{seed} "
            f"(P2-T prune run missing?)")
    with open(base, encoding="utf-8") as f:
        text = f.read()
    resolved_text = text.replace(SENTINEL, traj)
    os.makedirs(run_root, exist_ok=True)
    resolved_path = os.path.join(run_root, "resolved_config.yaml")
    with open(resolved_path, "w", encoding="utf-8") as f:
        f.write(resolved_text)
    return resolved_path


def load_records(out_dir=OUT_DIR):
    path = os.path.join(out_dir, RESULTS)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def done_pairs(out_dir=OUT_DIR):
    return {(r["variant"], r["arm"], r["seq"], r["seed"]) for r in load_records(out_dir)
            if r.get("exit") == 0}


def run_one(variant, arm, seq, seed, out_dir=OUT_DIR, dry_run=False):
    tag = f"{seq}_{variant}_{arm}_seed{seed}"
    run_root = os.path.join(out_dir, tag)
    console = os.path.join(out_dir, f"{tag}.consolelog")
    try:
        config = resolve_config(variant, arm, seq, seed, run_root)
    except FileNotFoundError as e:
        log(f"SKIP {tag}: {e}")
        return {"variant": variant, "arm": arm, "seq": seq, "seed": seed,
                "exit": -1, "error": str(e)}
    cmd = [PY, "slam.py", "--config", config, "--eval",
           "--seed", str(seed), "--results-root", run_root]
    if dry_run:
        print(f"  {' '.join(cmd)}")
        return {"variant": variant, "arm": arm, "seq": seq, "seed": seed,
                "cmd": cmd, "dry_run": True, "config": config}
    log(f"START {tag} -> {run_root}")
    started = time.time()
    with open(console, "w", encoding="utf-8") as cout:
        proc = subprocess.run(cmd, stdout=cout, stderr=subprocess.STDOUT, timeout=5400)
    elapsed = (time.time() - started) / 60.0
    rec = _extract(variant, arm, seq, seed, run_root, proc.returncode, elapsed, config)
    with open(os.path.join(out_dir, RESULTS), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    log(f"END   {tag} exit={proc.returncode} {elapsed:.1f}min "
        f"G={rec.get('refined_num_gaussians')} ate={rec.get('ate_rmse_cm')} "
        f"vac_depth={rec.get('static_vacated_depth_l1_pen_cm')} "
        f"vac_psnr={rec.get('static_vacated_psnr_db')} variant={variant}")
    return rec


def _extract(variant, arm, seq, seed, run_root, exit_code, elapsed_min, config):
    """Pull G / ATE / vac metrics from the run's tracking_raw.csv + mapping_raw.csv."""
    rec = {"variant": variant, "arm": arm, "seq": seq, "seed": seed,
           "exit": exit_code, "elapsed_min": round(elapsed_min, 1),
           "config": config, "run_dir": run_root}
    if exit_code != 0:
        return rec
    # find the run's tables dir
    tables = glob.glob(os.path.join(run_root, "datasets_bonn", "*", "seed_*", "*", "tables"))
    if not tables:
        return rec
    tdir = tables[0]
    trk = os.path.join(tdir, "tracking_raw.csv")
    if os.path.isfile(trk):
        import csv
        with open(trk, encoding="utf-8") as f:
            row = next(csv.DictReader(f), {})
        for k in ("ate_rmse_cm", "rpe_trans_rmse_cm", "keyframe_ate_rmse_cm"):
            if row.get(k):
                rec[k] = float(row[k])
    mraw = os.path.join(tdir, "mapping_raw.csv")
    if os.path.isfile(mraw):
        import csv
        with open(mraw, encoding="utf-8") as f:
            row = next(csv.DictReader(f), {})
        for k in ("refined_num_gaussians", "static_vacated_depth_l1_pen_cm",
                  "static_vacated_psnr_db", "inserted_num_gaussians",
                  "promoted_num_gaussians", "pruned_num_gaussians",
                  "expired_num_gaussians", "num_keyframes"):
            if row.get(k) not in (None, "", "None"):
                try:
                    rec[k] = float(row[k])
                except ValueError:
                    rec[k] = row.get(k)
    return rec


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", choices=["seed0", "full", "resume"], default="seed0")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    os.chdir(ROOT)
    os.makedirs(args.out_dir, exist_ok=True)

    seeds = [0] if args.phase == "seed0" else [1, 2]
    done = done_pairs(args.out_dir)
    jobs = []
    for seed in seeds:
        for variant in VARIANTS:
            for arm in ARMS:
                for seq in SEQS:
                    key = (variant, arm, seq, seed)
                    if args.phase == "resume" and key in done:
                        continue
                    if args.phase in ("seed0", "full") and key in done:
                        continue
                    jobs.append((variant, arm, seq, seed))
    if not jobs:
        log(f"no jobs to run (phase={args.phase}, done={len(done)})")
        return 0
    log(f"phase={args.phase}: {len(jobs)} run(s) to go (done={len(done)})")
    if args.dry_run:
        for v, a, s, sd in jobs:
            run_one(v, a, s, sd, args.out_dir, dry_run=True)
        return 0
    for v, a, s, sd in jobs:
        try:
            run_one(v, a, s, sd, args.out_dir)
        except subprocess.TimeoutExpired:
            log(f"TIMEOUT {s}_{v}_{a}_seed{sd}")
        except Exception as e:  # noqa: BLE001
            log(f"ERROR {s}_{v}_{a}_seed{sd}: {e}")
    log(f"==== P2-SF phase={args.phase} DONE ====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
