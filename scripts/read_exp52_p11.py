#!/usr/bin/env python
"""Read EXP52 results: P11 mask-only revalidation vs MRCS+async50 matched arm.

Reads `tables/tracking_raw.csv` for each arm/seed and reports the full-trajectory ATE
(`ate_rmse_cm`, evo -a Horn), RPE, escape status (<5 cm), plus online FPS / Gaussian
count (efficiency_raw.csv) and KF count (plot/trj_final.json trj_id length).

Not a decision script: it only transcribes readings. The verdict (G0-G3, Branch-1..4)
is frozen in `results/evidence/exp52_p11_prereg.md` and is filled by hand from this
readout into `results/evidence/exp52_p11_verdict.md`.
"""

import argparse
import csv
import glob
import json
import os
import statistics
import sys

SEEDS = ["0", "1", "2"]
ARMS = ["P11F", "P11B", "M50B"]
DEFAULT_ROOT = "results/runs/EXP52/p11_matched"

# exp28 (2026-08-19, 3090 preread anchors) and EXP51 A2 for side-by-side reading.
ANCHORS = {
    "P11F": {"exp28_mean": 4.04, "exp28_sd": 0.63, "exp28": [3.4618, 3.9370, 4.7093]},
    "P11B": {"exp28_mean": 3.18, "exp28_sd": 0.46, "exp28": [3.7115, 2.8575, 2.9787]},
    "M50B": {"note": "f3_st_hf side reuses EXP51 A2: 2.9378/2.3943/20.2845 (2/3 escape)"},
}


def read_csv_field(path, fields):
    if not os.path.isfile(path):
        return {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out = {}
            for key in fields:
                value = row.get(key)
                if value not in ("", None):
                    try:
                        out[key] = float(value)
                    except ValueError:
                        out[key] = value
            if out:
                return out
    return {}


def read_run(run_dir):
    rec = {}
    tracking = read_csv_field(
        os.path.join(run_dir, "tables", "tracking_raw.csv"),
        ("ate_rmse_cm", "rpe_trans_rmse_cm", "status"),
    )
    rec.update(tracking)
    efficiency = read_csv_field(
        os.path.join(run_dir, "tables", "efficiency_raw.csv"),
        ("online_fps", "num_gaussians"),
    )
    rec.update(efficiency)
    kf_jsons = glob.glob(os.path.join(run_dir, "datasets_*", "*", "seed_*", "*", "plot", "trj_final.json"))
    if kf_jsons:
        try:
            with open(kf_jsons[0], encoding="utf-8") as fh:
                rec["kf_count"] = len(json.load(fh).get("trj_id", []))
        except (OSError, ValueError):
            pass
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--json", default=None, help="write machine-readable result json")
    args = ap.parse_args()

    table = {}
    for arm in ARMS:
        for seed in SEEDS:
            run_dir = os.path.join(args.root, f"{arm}_seed{seed}")
            table[f"{arm}_seed{seed}"] = read_run(run_dir)

    print("=== EXP52 full-trajectory ATE (cm, evo -a Horn) ===")
    header = f"{'arm':<6}" + "".join(f"{'s' + s + ':ate':>10}" for s in SEEDS) + f"{'mean':>9}{'sd':>8}{'escape':>8}{'KF':>12}{'FPS':>8}{'gauss':>10}  status"
    print(header)
    for arm in ARMS:
        rows = [table[f"{arm}_seed{s}"] for s in SEEDS]
        ates = [r.get("ate_rmse_cm") for r in rows]
        complete = all(a is not None for a in ates)
        mean = statistics.mean(ates) if complete else None
        sd = statistics.stdev(ates) if complete and len(ates) > 1 else None
        escaped = sum(1 for a in ates if a is not None and a < 5.0)
        kfs = [r.get("kf_count") for r in rows]
        fpss = [r.get("online_fps") for r in rows]
        gauss = [r.get("num_gaussians") for r in rows]

        def fmt(values, spec="%.2f"):
            return "".join(f"{(spec % v) if isinstance(v, float) else (str(v) if v is not None else '---'):>10}" for v in values)

        status = "OK" if complete and all(r.get("status") == "OK" for r in rows) else (
            "PARTIAL" if any(ates) else "MISSING"
        )
        print(
            f"{arm:<6}"
            + fmt(ates)
            + f"{('%.2f' % mean) if mean is not None else '---':>9}"
            + f"{('%.2f' % sd) if sd is not None else '---':>8}"
            + f"{escaped}/3".rjust(8)
            + f"{('/'.join(str(k) if k is not None else '-' for k in kfs)):>12}"
            + f"{(statistics.mean(fpss) if all(isinstance(f, float) for f in fpss) else float('nan')):>8.3f}"
            + f"{(int(statistics.mean(gauss)) if all(isinstance(g, float) for g in gauss) else 0):>10}"
            + "  " + status
        )

    print("\n=== anchors (for the verdict, not replacements) ===")
    for arm in ARMS:
        anchor = ANCHORS.get(arm, {})
        if "exp28" in anchor:
            print(f"{arm}: exp28 3090 preread = {anchor['exp28']} (mean {anchor['exp28_mean']}±{anchor['exp28_sd']})")
        else:
            print(f"{arm}: {anchor.get('note', '')}")
    print("EXP51 A2 (f3_st_hf MRCS+async50): 2.9378/2.3943/20.2845, 2/3 escape; 6-seed 5/6, median 2.8103")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(table, fh, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
