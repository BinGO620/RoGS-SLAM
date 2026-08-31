#!/usr/bin/env python
"""Read EXP51 f3_st_hf submit results.

Reads `tables/tracking_raw.csv` for each arm/seed and reports the full-trajectory ATE
(`ate_rmse_cm`, evo -a Horn), escape status (<5 cm), plus KF count / FPS where present.

Not a decision script: it only transcribes ATE. The verdict (Branch-1..4) is fixed in
`results/evidence/exp51_f3_submit_prereg.md` and is filled by hand from this readout.
"""

import argparse
import csv
import json
import os
import sys

SEEDS = ["0", "1", "2"]
ARMS = ["A1", "A2", "B1", "B2"]
DEFAULT_ROOT = "results/runs/EXP51/f3_submit"


def read_ate(run_dir):
    path = os.path.join(run_dir, "tables", "tracking_raw.csv")
    if not os.path.isfile(path):
        return None, "MISSING tracking_raw.csv"
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = "ate_rmse_cm"
            if key in row and row[key] not in ("", None):
                try:
                    return float(row[key]), "OK"
                except ValueError:
                    return None, f"bad value {row[key]!r}"
    return None, "no ate_rmse_cm row"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--json", default=None, help="write machine-readable result json")
    args = ap.parse_args()

    table = {}
    for arm in ARMS:
        for seed in SEEDS:
            run_dir = os.path.join(args.root, f"{arm}_seed{seed}")
            ate, status = read_ate(run_dir)
            table[f"{arm}_seed{seed}"] = {"ate": ate, "status": status}

    print("=== EXP51 f3_st_hf full-trajectory ATE (cm, evo -a Horn) ===")
    print(f"{'arm':<6}{'seed0':>9}{'seed1':>9}{'seed2':>9}{'mean':>9}{'escape':>8}{'status'}")
    for arm in ARMS:
        vals = []
        ok = True
        for seed in SEEDS:
            ate = table[f"{arm}_seed{seed}"]["ate"]
            vals.append(ate)
            if ate is None:
                ok = False
        mean = sum(vals) / len(vals) if ok and all(v is not None for v in vals) else None
        escaped = (
            sum(1 for v in vals if v is not None and v < 5.0) if ok else None
        )
        print(f"{arm:<6}"
              + "".join(f"{('%.2f' % v) if v is not None else '---':>9}" for v in vals)
              + f"{('%.2f' % mean) if mean is not None else '---':>9}"
              + f"{('%d/3' % escaped) if escaped is not None else '---':>8}"
              + "  " + ("OK" if ok else "INCOMPLETE"))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(table, fh, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
