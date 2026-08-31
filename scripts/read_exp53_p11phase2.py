#!/usr/bin/env python
"""Read EXP53 results: P11 Phase-2 expansion vs the Combined arm.

Reads `tables/tracking_raw.csv` for each arm/seed, reports full-trajectory ATE
(`ate_rmse_cm`, evo -a Horn), escape (<5 cm), KF count / FPS / Gaussians, the
exp28 old-HEAD anchors, and the per-sequence P11-vs-Combined non-inferiority
reading (floor = max(0.43, 6% of the larger mean), frozen in the prereg).

Not a decision script: the verdict (G0-G3, Branch-1..4) is frozen in
`results/evidence/exp53_p11phase2_prereg.md` and filled by hand into
`results/evidence/exp53_p11phase2_verdict.md`.
"""

import argparse
import csv
import glob
import json
import os
import statistics

SEEDS = ["0", "1", "2"]
DEFAULT_ROOT = "results/runs/EXP53/p11phase2"

# sequence -> list of (arm_label, run_prefix). balloon P11 side = EXP52 reuse.
SEQUENCES = {
    "balloon": [("C", "balloon_C")],
    "balloon2": [("P11", "balloon2_P11"), ("C", "balloon2_C")],
    "crowd2": [("P11", "crowd2_P11"), ("C", "crowd2_C")],
    "mv_no_box": [("P11", "mvnobox_P11"), ("C", "mvnobox_C")],
    "f2_xyz": [("P11", "f2xyz_P11"), ("C", "f2xyz_C")],
}

# EXP52 P11B reuse (same-HEAD protocol) + exp28 old-HEAD P11 anchors (G0 only).
EXP52_P11B = {"ates": [3.0078, 3.2647, 3.0094]}
EXP28_ANCHORS = {
    "balloon2": [6.8911, 7.6097, 6.5164],
    "crowd2": [7.4778, 6.7345, 7.9303],
    "mv_no_box": [3.5241, 3.6809, 3.7144],
    "f2_xyz": [1.6711, 1.617, 1.7032],
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
    rec.update(read_csv_field(
        os.path.join(run_dir, "tables", "tracking_raw.csv"),
        ("ate_rmse_cm", "rpe_trans_rmse_cm", "status"),
    ))
    rec.update(read_csv_field(
        os.path.join(run_dir, "tables", "efficiency_raw.csv"),
        ("online_fps", "num_gaussians"),
    ))
    kf_jsons = glob.glob(os.path.join(run_dir, "datasets_*", "*", "seed_*", "*", "plot", "trj_final.json"))
    if kf_jsons:
        try:
            with open(kf_jsons[0], encoding="utf-8") as fh:
                rec["kf_count"] = len(json.load(fh).get("trj_id", []))
        except (OSError, ValueError):
            pass
    return rec


def fmt_ates(ates):
    return "/".join(f"{a:.2f}" if a is not None else "---" for a in ates)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    table = {}
    for seq, arms in SEQUENCES.items():
        for label, prefix in arms:
            for seed in SEEDS:
                table[f"{prefix}_seed{seed}"] = read_run(os.path.join(args.root, f"{prefix}_seed{seed}"))

    print("=== EXP53 full-trajectory ATE (cm, evo -a Horn) ===")
    print(f"{'seq':<11}{'arm':<5}{'s0/s1/s2':>20}{'mean':>9}{'sd':>8}{'esc':>6}{'KF':>14}{'FPS':>8}{'gauss':>9}")
    seq_means = {}
    for seq, arms in SEQUENCES.items():
        if seq == "balloon":
            p11_ates = EXP52_P11B["ates"]
            rows = []
            mean = statistics.mean(p11_ates)
            sd = statistics.stdev(p11_ates)
            kfs, fpss, gausses = [], [], []
            print(f"{seq:<11}{'P11':<5}{fmt_ates(p11_ates):>20}{mean:>9.2f}{sd:>8.2f}"
                  f"{sum(1 for a in p11_ates if a < 5)}/3".rjust(6)
                  + f"{'21/21/20(EXP52)':>14}" + f"{'0.871':>8}" + f"{'19861':>9}")
            seq_means[(seq, "P11")] = mean
        for label, prefix in arms:
            rows = [table[f"{prefix}_seed{s}"] for s in SEEDS]
            ates = [r.get("ate_rmse_cm") for r in rows]
            complete = all(a is not None for a in ates)
            mean = statistics.mean(ates) if complete else None
            sd = statistics.stdev(ates) if complete else None
            if mean is not None:
                seq_means[(seq, label)] = mean
            kfs = "/".join(str(r.get("kf_count")) if r.get("kf_count") is not None else "-" for r in rows)
            fps_vals = [r.get("online_fps") for r in rows]
            gauss_vals = [r.get("num_gaussians") for r in rows]
            fps = f"{statistics.mean(fps_vals):.2f}" if all(isinstance(f, float) for f in fps_vals) else "---"
            gauss = f"{int(statistics.mean(gauss_vals))}" if all(isinstance(g, float) for g in gauss_vals) else "---"
            print(f"{seq:<11}{label:<5}{fmt_ates(ates):>20}"
                  + (f"{mean:>9.2f}{sd:>8.2f}" if complete else f"{'---':>9}{'---':>8}")
                  + (f"{sum(1 for a in ates if a is not None and a < 5)}/3").rjust(6)
                  + f"{kfs:>14}{fps:>8}{gauss:>9}"
                  + ("" if complete else "  INCOMPLETE"))

    print("\n=== P11 vs Combined per-sequence non-inferiority (prereg G2) ===")
    print(f"{'seq':<11}{'P11 mean':>10}{'C mean':>10}{'floor':>8}{'delta':>9}{'reading':>14}")
    for seq in ("balloon", "balloon2", "crowd2", "mv_no_box", "f2_xyz"):
        p11 = seq_means.get((seq, "P11"))
        c = seq_means.get((seq, "C"))
        if p11 is None or c is None:
            print(f"{seq:<11}{'---':>10}{'---':>10}")
            continue
        floor = max(0.43, 0.06 * max(p11, c))
        delta = p11 - c
        if delta <= floor:
            reading = "P11 non-inferior" if delta > 0 else "P11 better"
        else:
            reading = "C better (>floor)" if c + floor < p11 else "borderline"
        print(f"{seq:<11}{p11:>10.2f}{c:>10.2f}{floor:>8.2f}{delta:>+9.2f}{reading:>16}")

    print("\n=== G0 anchor drift check (P11 side, exp28 old HEAD) ===")
    for seq, anchor in EXP28_ANCHORS.items():
        new = seq_means.get((seq, "P11"))
        if new is None:
            print(f"{seq}: pending")
            continue
        am = statistics.mean(anchor)
        asd = statistics.stdev(anchor)
        drift = abs(new - am)
        gate = max(2.0, 3 * asd)
        print(f"{seq}: new {new:.2f} vs anchor {am:.2f}±{asd:.2f} |drift|={drift:.2f} gate={gate:.2f} "
              f"{'OK' if drift <= gate else '*** G0 TRIGGER ***'}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(table, fh, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
