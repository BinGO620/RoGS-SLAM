#!/usr/bin/env python3
"""Direct measurement of what DynamicKeyframe actually does to temporal coverage (gap 3).

WHY THIS EXISTS. "Coverage Sampling" is in the paper's title, but every piece of evidence
for it was at the ATE level (WP-A's Delta_K, P-B's dynKF axis). Nothing measured the
coverage itself, so a reviewer could fairly ask what the word is doing in the title.

WHAT IT MEASURES. Keyframe count per run, recovered from the per-keyframe rows of
``deferred_commit_events.csv`` (``source_kf`` column -- one distinct id per keyframe the
backend processed), divided by the run's trajectory length from
``plot/trj_full_final.json``. Pairs are taken inside WP-A's factorial: for each
(sequence, R, L, seed) the K1 run is paired against the K0 run, so the ONLY thing that
differs in a pair is DynamicKeyframe.

Run it where the run artifacts live (the 3090 box for WP-A):
  python scripts/measure_keyframe_coverage.py --root results/runs/WPA/WPA-FACTORIAL
"""

import argparse
import csv
import glob
import json
import os
import re
import statistics

RUN_PATTERN = re.compile(r"^wpa_(?P<seq>.+)_K(?P<K>\d)R(?P<R>\d)L(?P<L>\d)_seed(?P<seed>\d)$")


def trajectory_length(run_dir):
    path = os.path.join(run_dir, "plot", "trj_full_final.json")
    if not os.path.isfile(path):
        return None
    try:
        ids = json.load(open(path)).get("trj_id")
    except Exception:
        return None
    return len(ids) if isinstance(ids, list) else ids


def keyframe_count(events_csv):
    """Distinct keyframes the backend processed (one id per keyframe, many rows each)."""
    kfs = set()
    try:
        with open(events_csv) as f:
            for row in csv.DictReader(f):
                v = (row.get("source_kf") or "").strip()
                if v:
                    kfs.add(v)
    except Exception:
        return None
    return len(kfs)


def collect(root, depth_index):
    records = {}
    for events in glob.glob(f"{root}/*/datasets_*/*/seed_*/*/deferred_commit_events.csv"):
        run = events.split(os.sep)[depth_index]
        m = RUN_PATTERN.match(run)
        if not m:
            continue
        run_dir = os.path.dirname(events)
        n_kf = keyframe_count(events)
        n_frames = trajectory_length(run_dir)
        if not n_kf or not n_frames:
            continue
        records[(m["seq"], m["K"], m["R"], m["L"], m["seed"])] = (n_kf, n_frames)
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results/runs/WPA/WPA-FACTORIAL")
    args = ap.parse_args()

    depth_index = len(args.root.rstrip("/").split(os.sep))
    records = collect(args.root, depth_index)
    print(f"runs with keyframe records: {len(records)}")

    print("\n| 序列 | 关键帧数 K0→K1 | 倍数 | KF/帧 K0→K1 | 配对数 |")
    print("|---|---|---:|---|---:|")
    for seq in sorted({k[0] for k in records}):
        pairs = []
        for (s, K, R, L, seed), value in records.items():
            if s != seq or K != "1":
                continue
            base = records.get((s, "0", R, L, seed))
            if base:
                pairs.append((base, value))
        if not pairs:
            continue
        n0 = statistics.mean(p[0][0] for p in pairs)
        n1 = statistics.mean(p[1][0] for p in pairs)
        d0 = statistics.mean(p[0][0] / p[0][1] for p in pairs)
        d1 = statistics.mean(p[1][0] / p[1][1] for p in pairs)
        print(f"| {seq} | {n0:.0f} → {n1:.0f} | **{n1 / n0:.2f}×** | "
              f"{d0:.3f} → {d1:.3f} | {len(pairs)} |")


if __name__ == "__main__":
    main()
