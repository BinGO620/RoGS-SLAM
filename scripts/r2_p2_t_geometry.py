#!/usr/bin/env python3
"""P2-T geometry post-process: attach F@5cm / accuracy / completion to each run.

The main table (02-method.md P2) commits an "F@5cm" column. The P2-T runs already wrote
their `final_after_opt/point_cloud.ply` and the full trajectory, but the geometry eval
(`utils.geometry_metrics.evaluate_run_geometry`) was not wired into the run-time config,
so the TSDF mesh + F-score vs the Bonn official GT ply never got produced. This script
fills that gap OFFLINE, per run, without re-running SLAM.

It needs GPU briefly (``render_gaussian_mesh.py`` renders each Gaussian to a depth map to
fuse a TSDF mesh — hardcoded cuda). So it MUST NOT run concurrently with a SLAM campaign
on the 6GB 2060 (it would OOM). Run it when the GPU is free (seeds 1/2 done or a gap).

Per run it writes:
  * ``geometry/tsdf_mesh.ply`` + ``geometry/mesh_metadata.json`` (idempotent — skips if present)
  * ``mapping_geometry_metrics_v2.json`` (the full metric blob)
  * a row appended to ``p2t_geometry.csv`` (per run: fscore_5cm, accuracy_cm, completion_cm,
    precision_ratio, pose_source, protocol_eligible)

Protocol (mirrors the R2-P01 geometry path, ``utils/geometry_metrics.py``):
  * reconstruction = TSDF mesh surface sampled to 200k points (NOT raw Gaussian centers);
  * GT = Bonn official ``rgbd_bonn_groundtruth_1mm_section.ply``;
  * alignment = ``T_g = T_ROS^{-1} T_0 T_ROS T_m`` (ROS-body vs optical);
  * threshold 5cm; a run whose pose_source is keyframe_fallback is protocol-ineligible and
    its F-score is MISSING (the full trajectory was unavailable).

Usage:
  python scripts/r2_p2_t_geometry.py                     # all exit-0 P2-T runs
  python scripts/r2_p2_t_geometry.py --seqs balloon pt2  # subset
  python scripts/r2_p2_t_geometry.py --smoke             # one run only, verify pipeline
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PY = "/data/conda_envs/monogs-ours/bin/python"
OUT_DIR = "results/runs/P2/P2-T"
RESULTS_JSONL = "p2t_results.jsonl"
GEO_CSV = "results/runs/P2/P2-T/p2t_geometry.csv"
GEO_FIELDS = ["seq", "arm", "seed", "run_tag", "exit", "fscore_5cm", "accuracy_cm",
              "completion_cm", "completion_ratio", "precision_ratio", "pose_source",
              "protocol_eligible", "mesh_vertices", "mesh_faces", "geometry_eval_time_s",
              "notes"]


def load_records(out_dir=OUT_DIR):
    path = os.path.join(out_dir, RESULTS_JSONL)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def resolve_run_dir(record, out_dir=OUT_DIR):
    """The run_dir in the jsonl is the results-root; the actual run artifacts live one
    level deeper under datasets_bonn/<config>/seed_<s>/<timestamp>. Mirror
    scripts.check_arm_activity._resolve_run_dir."""
    root = record.get("run_dir", "")
    if not root:
        return None
    # walk for the config.yml that proves a real run lived here
    for dirpath, _dirs, files in os.walk(root):
        if "config.yml" in files and os.path.isfile(os.path.join(dirpath, "mapping_geometry_metrics_v2.json")):
            return dirpath  # already done
        if "config.yml" in files:
            return dirpath
    return None


def already_done(run_dir):
    return bool(run_dir and os.path.isfile(os.path.join(run_dir, "mapping_geometry_metrics_v2.json")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--seqs", nargs="+", default=None,
                   help="subset of sequences (default: all exit-0 runs)")
    ap.add_argument("--smoke", action="store_true",
                   help="one run only — verify the pipeline end-to-end before the batch")
    ap.add_argument("--seq", default=None, help="single sequence (with --smoke)")
    ap.add_argument("--force", action="store_true", help="re-run even if metrics json exists")
    args = ap.parse_args()
    os.chdir(ROOT)

    records = [r for r in load_records(args.out_dir) if r.get("exit") == 0]
    if args.seqs:
        records = [r for r in records if r["seq"] in args.seqs]
    if args.smoke:
        if args.seq:
            records = [r for r in records if r["seq"] == args.seq][:1]
        else:
            records = records[:1]
    if not records:
        print("no exit-0 runs to process")
        return 1

    print(f"# P2-T geometry post-process: {len(records)} run(s) "
          f"{'(SMOKE)' if args.smoke else ''}")
    print("# GPU REQUIRED (render_gaussian_mesh hardcodes cuda) — do NOT run concurrent "
          "with a SLAM campaign.")

    rows_out = []
    n_done = n_skip = n_fail = 0
    for r in records:
        tag = f"{r['seq']}_{r['arm']}_seed{r['seed']}"
        run_dir = resolve_run_dir(r, args.out_dir)
        if run_dir is None:
            print(f"  {tag}: SKIP (no resolved run dir with config.yml)")
            n_skip += 1
            continue
        if already_done(run_dir) and not args.force:
            with open(os.path.join(run_dir, "mapping_geometry_metrics_v2.json"), encoding="utf-8") as f:
                m = json.load(f)
            print(f"  {tag}: already done (fscore={m.get('fscore')})")
            rows_out.append(_row_from(tag, r, m))
            n_skip += 1
            continue

        print(f"  {tag}: evaluating ... ({run_dir})")
        started = time.time()
        try:
            proc = subprocess.run(
                [PY, "-c", (
                    "import sys; sys.path.insert(0,'.'); "
                    "from utils.geometry_metrics import evaluate_run_geometry, "
                    "update_mapping_raw_for_run; "
                    f"m = evaluate_run_geometry({run_dir!r}); "
                    "print('FSCORE', m.get('fscore'), 'ACC', m.get('accuracy_cm'))"
                )],
                capture_output=True, text=True, timeout=1800,
            )
            print(proc.stdout.strip())
            if proc.returncode != 0:
                print(f"  {tag}: FAIL (exit {proc.returncode})\n{proc.stderr[-800:]}")
                n_fail += 1
                continue
            with open(os.path.join(run_dir, "mapping_geometry_metrics_v2.json"), encoding="utf-8") as f:
                m = json.load(f)
            rows_out.append(_row_from(tag, r, m))
            n_done += 1
            print(f"  {tag}: DONE in {time.time()-started:.0f}s  "
                  f"fscore={m.get('fscore')} acc={m.get('accuracy_cm')} "
                  f"pose_source={m.get('pose_source')}")
        except subprocess.TimeoutExpired:
            print(f"  {tag}: TIMEOUT (30min)")
            n_fail += 1
        except Exception as e:
            print(f"  {tag}: ERROR {e}")
            n_fail += 1

    # write the per-run csv
    if rows_out:
        os.makedirs(os.path.dirname(GEO_CSV), exist_ok=True)
        with open(GEO_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=GEO_FIELDS)
            w.writeheader()
            for row in rows_out:
                w.writerow({k: row.get(k, "") for k in GEO_FIELDS})
        print(f"\nwrote {GEO_CSV} ({len(rows_out)} rows)")
    print(f"\n# done={n_done}  skipped={n_skip}  failed={n_fail}")
    return 0 if n_fail == 0 else 2


def _row_from(tag, record, m):
    return {
        "seq": record["seq"], "arm": record["arm"], "seed": record["seed"],
        "run_tag": tag, "exit": record.get("exit"),
        "fscore_5cm": m.get("fscore"),
        "accuracy_cm": m.get("accuracy_cm"),
        "completion_cm": m.get("completion_cm"),
        "completion_ratio": m.get("completion_ratio"),
        "precision_ratio": m.get("precision_ratio"),
        "pose_source": m.get("pose_source"),
        "protocol_eligible": m.get("protocol_eligible"),
        "mesh_vertices": m.get("mesh_vertices"),
        "mesh_faces": m.get("mesh_faces"),
        "geometry_eval_time_s": m.get("geometry_eval_time_s"),
        "notes": m.get("notes_suffix", ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())
