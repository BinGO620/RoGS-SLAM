"""Arm-activity gate: FAIL a treatment arm whose treatment never executed.

R2-P02-E2 spent 9 GPU-runs (~3.5 h) comparing four arms that, because the alpha
exit pass was fed the wrong depth map, all ran the *same* algorithm. Every
metric was in range, every run exited 0, and the campaign's canary (a loose
plausibility band on the headline metric) reported PASS. The failure was
visible only as ``reset 0, carved 0`` inside a consolelog nobody re-read.

This script closes that hole. It reads the arm-activity counters the backend now
writes (``efficiency_raw.csv`` / ``backend_timing.json``) and asserts that a run
whose config *enables* a mechanism actually *exercised* it. A treatment arm with
zero activity is not a null result -- it is a replicate of the control, and its
numbers must never enter a contrast.

Usage
-----
    python scripts/check_arm_activity.py results/runs/R2-P02/R2-P02-E3/*/

Exit code 0 = every run's declared mechanism acted. Exit code 1 = at least one
run is inert (or its counters are missing, which is the same thing for the
purposes of trusting a contrast).
"""

import argparse
import csv
import glob
import json
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.alpha_lifecycle import alpha_lifecycle_mode  # noqa: E402

# Which counters a mode is contractually obliged to move. Derived from the same
# predicate the backend uses (``alpha_lifecycle_mode``) so the gate can never
# drift away from the mechanism it is policing.
EXIT_MODES = ("exit", "exit_fill")
FILL_MODES = ("exit_fill",)


def _load_config(run_dir):
    for name in ("config.yml", "config.yaml"):
        path = os.path.join(run_dir, name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    return None


def _load_counters(run_dir):
    """Prefer efficiency_raw.csv (the results-table channel that a reviewer sees);
    fall back to backend_timing.json (the source) for runs that skipped eval."""
    csv_path = os.path.join(run_dir, "efficiency_raw.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if rows and "alpha_exit_reset_total" in rows[-1]:
            return rows[-1], "efficiency_raw.csv"
    json_path = os.path.join(run_dir, "backend_timing.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f), "backend_timing.json"
    return None, None


def _as_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _resolve_run_dir(path):
    """Accept either a leaf run dir or a batch wrapper dir.

    ``run_monogs_batch`` nests the real artifacts under
    ``<wrapper>/<dataset>/<config>/seed_N/<timestamp>/``, so pointing the gate at
    the arm directory a human named must still work. Returns the single leaf that
    holds ``config.yml``, or None if there is not exactly one.
    """
    if os.path.exists(os.path.join(path, "config.yml")):
        return path
    hits = sorted(glob.glob(os.path.join(path, "**", "config.yml"), recursive=True))
    if len(hits) == 1:
        return os.path.dirname(hits[0])
    if len(hits) > 1:
        # Several runs under one wrapper: newest timestamp wins, matching how the
        # batch runner's own artifact check resolves a re-run.
        return os.path.dirname(hits[-1])
    return None


def check_run(run_dir):
    """Return (verdict, detail). verdict is PASS / FAIL / SKIP."""
    resolved = _resolve_run_dir(run_dir)
    if resolved is None:
        return "FAIL", "no resolved config.yml anywhere -- cannot tell which arm this is"
    run_dir = resolved
    config = _load_config(run_dir)
    if config is None:
        return "FAIL", "no resolved config.yml -- cannot tell which arm this is"

    try:
        mode = alpha_lifecycle_mode(config)
    except ValueError as exc:
        return "FAIL", f"invalid AlphaLifecycle.mode: {exc}"
    if mode == "off":
        # Control arms (prune / deferred) legitimately do nothing.
        return "SKIP", f"lifecycle-free arm (AlphaLifecycle.mode={mode!r})"

    counters, source = _load_counters(run_dir)
    if counters is None:
        return "FAIL", "lifecycle enabled but no activity counters were written"

    steps = _as_int(counters.get("alpha_lifecycle_steps"))
    skips = _as_int(counters.get("alpha_lifecycle_skips"))
    resets = _as_int(counters.get("alpha_exit_reset_total"))
    carves = _as_int(counters.get("alpha_carve_total"))
    fills = _as_int(counters.get("alpha_fill_inserted_total"))
    if steps is None:
        return "FAIL", f"activity counters absent from {source} (stale run?)"

    detail = (
        f"mode={mode} steps={steps} skips={skips} "
        f"reset={resets} carve={carves} fill={fills} [{source}]"
    )
    if steps == 0:
        return "FAIL", f"lifecycle enabled but never ran a step -- {detail}"
    if skips and skips == steps:
        return "FAIL", f"every lifecycle step raised and was swallowed -- {detail}"
    if mode in EXIT_MODES and not (resets or carves):
        return "FAIL", f"exit mechanism enabled but removed nothing -- {detail}"
    if mode in FILL_MODES and not fills:
        # Fill is gated behind a non-zero exit delta by design, so this is only
        # a failure once exit itself fired.
        if resets or carves:
            return "FAIL", f"exit fired but fill inserted nothing -- {detail}"
    return "PASS", detail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", help="run directories (globs ok)")
    parser.add_argument(
        "--strict-controls",
        action="store_true",
        help="also require control arms to report zero activity (parity check)",
    )
    args = parser.parse_args()

    expanded = []
    for pattern in args.run_dirs:
        hits = sorted(glob.glob(pattern)) or [pattern]
        expanded.extend(h.rstrip("/") for h in hits if os.path.isdir(h))
    if not expanded:
        print("no run directories matched", file=sys.stderr)
        return 1

    failures = 0
    width = max(len(os.path.basename(d)) for d in expanded)
    for run_dir in expanded:
        verdict, detail = check_run(run_dir)
        if verdict == "SKIP" and args.strict_controls:
            counters, source = _load_counters(_resolve_run_dir(run_dir) or run_dir)
            total = sum(
                _as_int((counters or {}).get(k)) or 0
                for k in ("alpha_exit_reset_total", "alpha_carve_total",
                          "alpha_fill_inserted_total")
            )
            if total:
                verdict, detail = "FAIL", f"control arm acted ({total} events) -- {source}"
        if verdict == "FAIL":
            failures += 1
        print(f"{verdict:4s} {os.path.basename(run_dir):{width}s}  {detail}")

    print()
    if failures:
        print(
            f"ARM-ACTIVITY GATE FAILED: {failures}/{len(expanded)} run(s) inert. "
            "Their metrics are replicates of the control, NOT a contrast -- do not "
            "report them as a checkpoint result."
        )
        return 1
    print(f"ARM-ACTIVITY GATE PASSED: {len(expanded)} run(s) checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
