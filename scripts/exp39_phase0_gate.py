#!/usr/bin/env python
"""exp39 Phase-0 gate readout.

Evaluates the pre-registered gates and decision rule in
``results/evidence/exp39_phase0_prereg.md`` against the two Phase-0 runs. Thresholds are
imported from the pre-registration values below and MUST NOT be edited after the runs --
if a gate fails, the verdict is NO VERDICT, not a wider tolerance.

Documented substitution (G-3b): the pre-registration asks for ``applied_frac`` from the
run, but the probe records gradient attribution only. The equivalent run-time measurement
is the semantic insertion gate's per-keyframe ``person px zeroed`` line -- the same mask,
same backend, same dilation, logged by the run itself. The substitution is recorded here
and in the verdict rather than silently dropped.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- pre-registered constants (exp39_phase0_prereg.md, committed before the runs) ----
MASS_SHARE = 0.034          # dynamic pixels' weight-mass share at floor=0.25 (from S2 audit)
INERT_SHARE = MASS_SHARE / 3  # 1.1%: below this the mechanism did not reach the optimiser
RESHAPE_FACTOR = 2.0        # pose_to_map_ratio may not move by more than this
MIN_ROWS = 20
MASK_AREA_EXPECTED = 0.122
MASK_AREA_TOL = 0.04
TOTAL_PX = 640 * 480        # Bonn frame

PERSON_PX = re.compile(r"(\d+) person px zeroed")


def load_probe(run_dir):
    paths = glob.glob(os.path.join(run_dir, "**", "mapping_probe.json"), recursive=True)
    if not paths:
        return None
    with open(sorted(paths)[-1], encoding="utf-8") as f:
        return json.load(f)["rows"]


def mask_area_from_console(run_dir):
    """Per-keyframe semantic mask area fraction, read from the run's own log."""
    areas = []
    for path in glob.glob(os.path.join(run_dir, "**", "console.log"), recursive=True):
        with open(path, encoding="utf-8", errors="replace") as f:
            areas += [int(m) / TOTAL_PX for m in PERSON_PX.findall(f.read())]
    return areas


def summarise(rows):
    def med(key):
        values = [r[key] for r in rows if r.get(key) is not None]
        return st.median(values) if values else None

    return {
        "rows": len(rows),
        "floor": rows[0]["floor"] if rows else None,
        "dyn_share_map": med("dyn_share_map"),
        "dyn_share_pose": med("dyn_share_pose"),
        "pose_to_map_ratio": med("pose_to_map_ratio"),
        "max_dyn_share_map": max(
            (r["dyn_share_map"] for r in rows if r.get("dyn_share_map") is not None),
            default=None,
        ),
        "max_dyn_share_pose": max(
            (r["dyn_share_pose"] for r in rows if r.get("dyn_share_pose") is not None),
            default=None,
        ),
    }


def evaluate(hard, soft, hard_areas, soft_areas):
    """Returns (verdict, gates, notes). Pure -- unit-tested with known-bad inputs."""
    gates = {}

    # G-2 negative control: the hard arm deletes dynamic pixels, so their gradient share
    # must be EXACTLY zero. "Small" is a failure: it would mean the probe is measuring
    # something other than what it claims.
    gates["G-2 negative control"] = (
        hard["max_dyn_share_map"] == 0.0 and hard["max_dyn_share_pose"] == 0.0
    )
    gates["G-3a probe coverage"] = hard["rows"] >= MIN_ROWS and soft["rows"] >= MIN_ROWS
    areas = hard_areas + soft_areas
    mean_area = st.mean(areas) if areas else None
    gates["G-3b mask area vs audit"] = (
        mean_area is not None
        and abs(mean_area - MASK_AREA_EXPECTED) <= MASK_AREA_TOL
    )
    gates["G-0 floors as registered"] = hard["floor"] == 0.0 and soft["floor"] == 0.25

    notes = {"mask_area_mean": mean_area}

    if not all(gates.values()):
        return "NO VERDICT", gates, notes

    share_map = soft["dyn_share_map"]
    share_pose = soft["dyn_share_pose"]
    ratio_shift = (
        soft["pose_to_map_ratio"] / hard["pose_to_map_ratio"]
        if hard["pose_to_map_ratio"]
        else None
    )
    notes["ratio_shift"] = ratio_shift

    if ratio_shift is not None and (
        ratio_shift > RESHAPE_FACTOR or ratio_shift < 1.0 / RESHAPE_FACTOR
    ):
        return "MECHANISM-RESHAPING", gates, notes
    if min(share_map, share_pose) < INERT_SHARE:
        return "MECHANISM-INERT", gates, notes
    if min(share_map, share_pose) > MASS_SHARE:
        return "MECHANISM-LIVE", gates, notes
    return "PARTIAL", gates, notes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", default=os.path.join(ROOT, "results/runs/EXP39"))
    args = parser.parse_args()

    arms = {}
    for name, tag in (("hard", "exp39_hard_balloon"), ("soft", "exp39_soft025_balloon")):
        run_dirs = glob.glob(os.path.join(args.runs_root, "**", tag), recursive=True)
        if not run_dirs:
            sys.exit(f"missing run for arm {name} ({tag}) under {args.runs_root}")
        rows = load_probe(run_dirs[0])
        if not rows:
            sys.exit(f"no mapping_probe.json for arm {name}")
        arms[name] = (summarise(rows), mask_area_from_console(run_dirs[0]))

    verdict, gates, notes = evaluate(
        arms["hard"][0], arms["soft"][0], arms["hard"][1], arms["soft"][1]
    )

    out = {
        "verdict": verdict,
        "gates": gates,
        "notes": notes,
        "arms": {k: v[0] for k, v in arms.items()},
        "thresholds": {
            "mass_share": MASS_SHARE,
            "inert_share": INERT_SHARE,
            "reshape_factor": RESHAPE_FACTOR,
        },
    }
    path = os.path.join(ROOT, "results/evidence/exp39_phase0_gate.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
