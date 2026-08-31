#!/usr/bin/env python
"""exp39 Phase-1 readout — three arms, ATE against the project's noise floor.

Decision rule is transcribed from `results/evidence/exp39_phase0_prereg.md` §6, which was
committed before any Phase-0 or Phase-1 run. It is NOT re-derived here and must not be
edited after the runs:

  W better than H but NOT better than S  ->  the gain is loss SCALE; the weight-shape
                                             claim collapses.
  W still better than S                  ->  the continuous weight SHAPE itself has value.
  neither separable                      ->  softening buys no measurable mechanism gain.

"Better" is judged against the project's standing ATE noise floor of 6% relative -- a
value that predates exp39 (exp32: a 88.5% no-op arm still differed from its control by
6.2%), so nothing here is fitted to this campaign's data.

G-3b upgrade over Phase 0: Phase 0 compared the run's keyframe-only mask area against an
all-frames offline audit -- two different populations, and the gate passed by 0.0002.
Here the audit's per-frame CSV is restricted to the frames the probe actually scored
(by uid), making it a same-population comparison.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NOISE_FLOOR_REL = 0.06          # project-wide ATE noise floor (exp32), not fitted here
ARMS = ("hard", "soft025", "scale025")
SEQS = ("balloon", "mv_no_box")
AUDIT_CSV = os.path.join(ROOT, "results/evidence/exp39_weight_audit_perframe.csv")


def ate_from_run(run_dir):
    """Headline ATE = `ate_rmse_cm` in tracking_raw.csv (memory: monogs-ate-metric-gotcha;
    the console 'RMSE ATE' line is the keyframe-only number and is NOT the headline)."""
    hits = glob.glob(os.path.join(run_dir, "**", "tracking_raw.csv"), recursive=True)
    if not hits:
        return None
    with open(sorted(hits)[-1], encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    values = [float(r["ate_rmse_cm"]) for r in rows if r.get("ate_rmse_cm")]
    return values[-1] if values else None


def probe_rows(run_dir):
    hits = glob.glob(os.path.join(run_dir, "**", "mapping_probe.json"), recursive=True)
    if not hits:
        return []
    with open(sorted(hits)[-1], encoding="utf-8") as f:
        return json.load(f)["rows"]


def audit_area_for_uids(uids):
    """Offline mask area restricted to the frames the probe scored (same population)."""
    if not os.path.exists(AUDIT_CSV):
        return None
    with open(AUDIT_CSV, encoding="utf-8") as f:
        by_frame = {
            int(r["frame"]): float(r["sem_area_frac"])
            for r in csv.DictReader(f)
            if r.get("sem_area_frac")
        }
    matched = [by_frame[u] for u in uids if u in by_frame]
    return st.mean(matched) if matched else None


def collect(runs_root):
    out = {}
    for seq in SEQS:
        for arm in ARMS:
            tag = f"exp39_{arm}_{seq}"
            dirs = glob.glob(os.path.join(runs_root, "**", tag), recursive=True)
            if not dirs:
                continue
            rows = probe_rows(dirs[0])
            uids = sorted({r["uid"] for r in rows})
            out[(seq, arm)] = {
                "ate_cm": ate_from_run(dirs[0]),
                "probe_rows": len(rows),
                "applied_frac": (
                    st.median([r["applied_frac"] for r in rows if "applied_frac" in r])
                    if any("applied_frac" in r for r in rows)
                    else None
                ),
                "audit_area_same_frames": audit_area_for_uids(uids) if seq == "balloon" else None,
                "dyn_share_map": (
                    st.median([r["dyn_share_map"] for r in rows if r.get("dyn_share_map") is not None])
                    if rows
                    else None
                ),
            }
    return out


def classify(hard, soft, scale):
    """Three-branch rule (pre-registered). Returns (label, detail)."""
    if None in (hard, soft, scale):
        return "NO VERDICT", "missing ATE for at least one arm"
    band_h = abs(hard) * NOISE_FLOOR_REL
    band_s = abs(scale) * NOISE_FLOOR_REL
    beats_hard = (hard - soft) > band_h
    beats_scale = (scale - soft) > band_s
    if beats_hard and beats_scale:
        return "SHAPE-MATERIAL", "W beats both H and the scale-matched control S"
    if beats_hard and not beats_scale:
        return "SCALE-EXPLAINED", "W beats H but not S: the gain tracks loss scale"
    if not beats_hard and (soft - hard) > band_h:
        return "SOFT-WORSE", "W is worse than H beyond the noise floor"
    return "INDISTINGUISHABLE", "no pair separates beyond the 6% noise floor"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", default=os.path.join(ROOT, "results/runs/EXP39"))
    args = parser.parse_args()

    data = collect(args.runs_root)
    if not data:
        sys.exit(f"no exp39 runs under {args.runs_root}")

    report = {"noise_floor_rel": NOISE_FLOOR_REL, "sequences": {}}
    for seq in SEQS:
        arms = {arm: data.get((seq, arm)) for arm in ARMS}
        if any(v is None for v in arms.values()):
            report["sequences"][seq] = {"verdict": "NO VERDICT", "arms": arms}
            continue
        label, detail = classify(
            arms["hard"]["ate_cm"], arms["soft025"]["ate_cm"], arms["scale025"]["ate_cm"]
        )
        report["sequences"][seq] = {"verdict": label, "detail": detail, "arms": arms}

    path = os.path.join(ROOT, "results/evidence/exp39_phase1_gate.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nwrote {path}")
    print(
        "\nREMINDER: single seed per arm. Per the project's screening discipline this is a "
        "DIRECTION reading, not a verdict on effect size; |delta| under the 6% floor is "
        "unreadable and must not be reported as 'no difference' without that caveat."
    )


if __name__ == "__main__":
    main()
