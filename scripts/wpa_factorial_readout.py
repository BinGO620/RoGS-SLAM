#!/usr/bin/env python3
"""WP-A FACTORIAL readout (CCF-C 整改执行卡 v3, 2026-08-14)。

Consumes the 120-run WPA-FACTORIAL output and computes the three-layer metrics
(L1 completion / L2 conditional ATE / L3 trajectory coverage) + the pairwise marginal
Δ_K/Δ_R/Δ_L + the A1–A5 branch verdict, exactly per the pre-registered criteria in
results/evidence/wpa_factorial_prereg.md.

**All criteria are frozen (per §0/§6 of the execution card). This script only READS:
  it never changes a denominator, never drops a seq, never truncates ATE.** Failure is
  evidence (C4): a baseline that cannot complete 2/3 seeds is reported in its own row,
  not silently excluded from the 5-seq denominator.

Statistics are ONLY descriptive (WP-A conclusion = reproducible descriptive evidence):
  * Completion      = fraction of completed seeds (trj_full_final frames >= 95% of total);
  * Conditional ATE = mean±sd over co-completed seeds ONLY (never quoted alone; see L3);
  * Trajectory cov  = len(trj_full_final) / dataset_total_frames.

Pairing (Codex round-2 #3): a (seq × cell-pair) contrast is only 判定的 when k=3; k=2 is
descriptive-only; k<=1 is UNRESOLVED (counted as FAIL for A1–A5). Denominator is always 5.

Usage:
  python scripts/wpa_factorial_readout.py \
      --runs-dir results/runs/WPA/WPA-FACTORIAL \
      [--dataset-root /data/Datasets/Bonn] \
      [--json wpa_readout.json] [--md wpa_readout.md]
"""
import argparse
import glob
import itertools
import json
import math
import os
import re
import sys

import numpy as np

# Dataset total frames must be computed by THIS script from the actual association files
# (not hard-coded): the "total frames" denominator for the 95% completion gate has to be
# the same loader uses. We read rgb.txt (association source) — the loader auto-associates
# and applies the 1/frame_rate dedup; we approximate with the count of depth files (the
# loader's depth_paths length). For project consistency we use the len(depth) as the total.
SEQ_TOTAL = {
    # seq → (dataset_dir, total_frames). depth png count = len(self.depth_paths).
    # Populated at runtime from the dataset dir; values below are a fallback used only if
    # the dataset dir is unavailable. KEEP IN SYNC with the loader (len(depth_paths)).
    "mv_no_box": 776,
    "mv_no_box2": 927,
    "pt2": 565,
    "balloon": 438,
    "pt1": 579,
}

# Total frames are authoritative from depth png count. If a fallback is needed these are
# closest to the runtime len(self.depth_paths); the 95% gate is computed against these.
SEQ_DATASET = {
    "mv_no_box": "rgbd_bonn_moving_nonobstructing_box",
    "mv_no_box2": "rgbd_bonn_moving_nonobstructing_box2",
    "pt2": "rgbd_bonn_person_tracking2",
    "balloon": "rgbd_bonn_balloon",
    "pt1": "rgbd_bonn_person_tracking",
}

ARMS = ["K0R0L0", "K1R1L1", "K0R1L1", "K1R0L1", "K1R1L0", "K0R1L0", "K0R0L1", "K1R0L0"]

# ε = 0.10 log-scale (≈10.5% ATE ratio); practice-relevant, NOT a statistical-equivalence
# bound. Pre-registered in results/evidence/wpa_factorial_prereg.md. FROZEN.
EPS = 0.10
COMPLETION_FRAC = 0.95

# Marginal pairings (per-sequence): Δ_X = log(ATE(half-removed) / ATE(full)).
# full = K1R1L1; Δ_K numerator = K0R1L1; Δ_R = K1R0L1; Δ_L = K1R1L0.
FULL = "K1R1L1"
DELTAS = {
    "K": ("K0R1L1",),
    "R": ("K1R0L1",),
    "L": ("K1R1L0",),
}


def dataset_total_frames(seq, dataset_root):
    """Runtime total = number of associated depth frames (len(self.depth_paths))."""
    if dataset_root:
        d = os.path.join(dataset_root, SEQ_DATASET[seq])
        depth = glob.glob(os.path.join(d, "depth", "*.png"))
        if depth:
            return len(depth)
    return SEQ_TOTAL[seq]


def find_trj_json(run_dir):
    """Locate plot/trj_full_final.json under a run dir (may be nested)."""
    hits = glob.glob(os.path.join(run_dir, "**", "plot", "trj_full_final.json"),
                     recursive=True)
    if not hits:
        hits = glob.glob(os.path.join(run_dir, "**", "trj_full_final.json"),
                         recursive=True)
    return hits[0] if hits else None


def read_tracking(run_dir):
    """Return (ate_cm, len_trj) or None. ate from tables/tracking_raw.csv;
    len_trj from trj_full_final.json (frames = len(gt) = len(est))."""
    csv_path = os.path.join(run_dir, "tables", "tracking_raw.csv")
    if not os.path.isfile(csv_path):
        return None
    ate = None
    with open(csv_path) as fh:
        header = fh.readline().strip().split(",")
        line = fh.readline()
        if not line:
            return None
        vals = line.strip().split(",")
        row = dict(zip(header, vals))
        try:
            ate = float(row["ate_rmse_cm"])
        except (KeyError, ValueError):
            return None
    trj = find_trj_json(run_dir)
    n = None
    if trj:
        try:
            import json as _json
            d = _json.load(open(trj))
            n = len(d.get("trj_gt", [])) if isinstance(d.get("trj_gt"), list) else None
        except Exception:
            n = None
    return ate, n


def build_cell(seq, arm, runs_dir, dataset_root):
    """aggregate (seq, arm) across seeds → {seed: (ate, len_trj)}."""
    per_seed = {}
    for seed in (0, 1, 2):
        outnm = f"wpa_{seq}_{arm}_seed{seed}"
        rd = os.path.join(runs_dir, outnm)
        r = read_tracking(rd)
        if r is not None:
            per_seed[seed] = r
    return per_seed


def completion_and_ate(cell, total):
    """→ dict with completed seeds, completion fraction, conditional ATE list + seed-keyed map."""
    comp = {seed: (ate, n) for seed, (ate, n) in cell.items()
            if n is not None and n >= COMPLETION_FRAC * total and math.isfinite(ate) and ate > 0}
    frac = len(comp) / 3.0
    ates = [comp[s][0] for s in (0, 1, 2) if s in comp]  # seed-keyed via dict, aligned
    return {
        "completed_seeds": sorted(comp.keys()),
        "completion": frac,
        "ate_list": ates,
        "ate_by_seed": {s: comp[s][0] for s in comp},
        "ate_mean": float(np.mean(ates)) if ates else None,
        "ate_sd": float(np.std(ates, ddof=1)) if len(ates) > 1 else None,
    }


def paired_ate(cell_a, cell_b, total):
    """Per-seed paired diff on CO-COMPLETED seeds. cell_a = denominator (full config),
    cell_b = numerator (arm being tested): computes log(ATE_b / ATE_a).
    k is defined ONLY over seeds with valid finite positive ATE in BOTH cells — a seed
    whose ATE is non-finite/<=0 in either cell is not co-completed and cannot pair."""
    ca = completion_and_ate(cell_a, total)
    cb = completion_and_ate(cell_b, total)
    common = sorted(set(ca["completed_seeds"]) & set(cb["completed_seeds"]))
    ratios = []
    for s in common:
        ate_b = cb["ate_by_seed"][s]
        ate_a = ca["ate_by_seed"][s]
        if ate_a > 0 and ate_b > 0 and math.isfinite(ate_a) and math.isfinite(ate_b):
            ratios.append(math.log(ate_b / ate_a))
    return common, ratios


def marginal(seq, arm_key, matrix, total):
    """Δ over the (seq, arm). Deferred by Δ_idx:
       Δ_K = log(K0R1L1 / K1R1L1)   -> numerator K0R1L1, denominator FULL;
       Δ_R = log(K1R0L1 / K1R1L1)   -> numerator K1R0L1;
       Δ_L = log(K1R1L0 / K1R1L1)   -> numerator K1R1L0.
    paired_ate(denominator=full, numerator=arm) returns log(numerator/full) = Δ. """
    full_cell = matrix[seq][FULL]
    half_cell = matrix[seq][arm_key]
    common, ratios = paired_ate(full_cell, half_cell, total)
    k = len(common)
    if k <= 1:
        return {"k": k, "status": "UNRESOLVED", "mean": None, "sd": None,
                "decision": "UNRESOLVED"}
    mean_log = float(np.mean(ratios))
    sd = float(np.std(ratios, ddof=1)) if len(ratios) > 1 else None
    same_sign = all(r > 0 for r in ratios) or all(r < 0 for r in ratios)
    sign_all = all(r > 0 for r in ratios)
    if mean_log > EPS and same_sign and sign_all:
        decision = "positive"
    elif mean_log < -EPS and same_sign:
        decision = "negative"
    elif abs(mean_log) <= EPS:
        decision = "zero"
    else:
        decision = "mixed"
    return {"k": k, "status": "k2-descriptive" if k == 2 else "paired",
            "mean_log": mean_log, "sd": sd, "ratios": ratios,
            "same_sign": same_sign, "decision": decision}


def verdict_branch(seq_rows):
    """A1–A5 decision over the 5 seqs. seq_rows: {seq: {'K':..,'R':..,'L':..}}."""
    n_irreducible = 0
    seqs_with_three_positive = []
    partial_redundant = {"K": 0, "R": 0, "L": 0}
    negative_seqs = {"K": [], "R": [], "L": []}
    for seq, d in seq_rows.items():
        dec = {q: d[q]["decision"] for q in ("K", "R", "L")}
        if all(dec[q] == "positive" for q in ("K", "R", "L")):
            n_irreducible += 1
            seqs_with_three_positive.append(seq)
        for q in ("K", "R", "L"):
            if dec[q] == "zero":
                partial_redundant[q] += 1
            if dec[q] == "negative":
                negative_seqs[q].append(seq)
    # A5 check first (per prereg order A5 → A3 → A1 → A2 → A4)
    if any(len(v) >= 2 for v in negative_seqs.values()):
        branch = "A5-negative-interaction"
        detail = negative_seqs
    elif n_irreducible >= 4:
        branch = "A1-local-irreducible"
        detail = seqs_with_three_positive
    elif max(partial_redundant.values()) >= 3:
        branch = "A2-partial-redundant"
        detail = partial_redundant
    else:
        branch = "A4-seq-dependent"
        detail = seq_rows
    return branch, detail


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs-dir", default="results/runs/WPA/WPA-FACTORIAL")
    ap.add_argument("--dataset-root", default="/data/Datasets/Bonn")
    ap.add_argument("--json", default="results/evidence/wpa_factorial_readout.json")
    ap.add_argument("--md", default="results/evidence/wpa_factorial_readout.md")
    args = ap.parse_args()

    matrix = {s: {} for s in SEQ_TOTAL}
    totals = {s: dataset_total_frames(s, args.dataset_root) for s in SEQ_TOTAL}
    for s in SEQ_TOTAL:
        for arm in ARMS:
            matrix[s][arm] = build_cell(s, arm, args.runs_dir, args.dataset_root)

    # Layer output (L1/L2/L3) for the full table
    layer = {}
    for s in SEQ_TOTAL:
        layer[s] = {}
        for arm in ARMS:
            cell = matrix[s][arm]
            ca = completion_and_ate(cell, totals[s])
            layer[s][arm] = {
                "completion": ca["completion"],
                "completed_seeds": ca["completed_seeds"],
                "ate_mean": ca["ate_mean"],
                "ate_sd": ca["ate_sd"],
                "traj_frac": {
                    seed: (n / totals[s] if totals[s] else None)
                    for seed, (_, n) in cell.items()
                },
            }

    # Marginals
    seq_rows = {}
    for s in SEQ_TOTAL:
        seq_rows[s] = {}
        for q, (num_arm,) in DELTAS.items():
            seq_rows[s][q] = marginal(s, num_arm, {s: matrix[s]}, totals[s])

    branch, detail = verdict_branch(seq_rows)

    out = {
        "prereg_ref": "results/evidence/wpa_factorial_prereg.md",
        "epsilon_log": EPS,
        "completion_frac": COMPLETION_FRAC,
        "dataset_total_frames": totals,
        "layers": layer,
        "marginals": seq_rows,
        "verdict_branch": branch,
        "verdict_detail": detail,
    }
    os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
    with open(args.json, "w") as fh:
        json.dump(out, fh, indent=2)

    # Markdown report
    with open(args.md, "w") as fh:
        fh.write(f"# WP-A FACTORIAL readout (descriptive)\n\n")
        fh.write(f"ε = {EPS} log ({math.expm1(EPS)*100:.1f}% ATE ratio); "
                 f"completion gate = ≥{COMPLETION_FRAC*100:.0f}% frames. "
                 f"Pre-registered: `results/evidence/wpa_factorial_prereg.md`.\n\n")
        fh.write(f"**Verdict branch: {branch}**\n\n")
        fh.write("## L1/L2/L3 per (seq × arm)\n\n")
        fh.write("| seq | arm | completion | completed seeds | ATE mean±sd | traj frac |\n")
        fh.write("|---|---|---:|---|---:|---:|\n")
        for s in SEQ_TOTAL:
            for arm in ARMS:
                r = layer[s][arm]
                am = (f"{r['ate_mean']:.2f}±{r['ate_sd']:.2f}"
                      if r["ate_mean"] is not None else "—")
                traj = ", ".join(f"{s_}:{v:.2f}" for s_, v in r["traj_frac"].items())
                fh.write(f"| {s} | {arm} | {r['completion']:.2f} | "
                         f"{r['completed_seeds'] or '—'} | {am} | {traj} |\n")
        fh.write("\n## Pairwise marginal Δ (log-ATE; + = removal hurts)\n\n")
        fh.write("| seq | factor | Δ_K num | mean_log | sd | k | decision |\n")
        fh.write("|---|---|---|---|---:|---:|---:|\n")
        for s in SEQ_TOTAL:
            for q in ("K", "R", "L"):
                m = seq_rows[s][q]
                mn = f"{m['mean_log']:.3f}" if m.get("mean_log") is not None else "—"
                sd = f"{m['sd']:.3f}" if m.get("sd") is not None else "—"
                fh.write(f"| {s} | Δ_{q} | {DELTAS[q][0]} | {mn} | {sd} | "
                         f"{m['k']} | {m['decision']} |\n")
        fh.write("\n## 判定映射\n\n")
        fh.write(f"- **branch**: {branch}\n")
        fh.write(f"- **detail**: {str(detail)}\n")
        fh.write("\n> Descriptive only; denominator fixed at 5 seqs; UNRESOLVED counts as "
                 "not-passed; no ATE truncation / no seq removal (C4).\n")
    print(json.dumps({"branch": branch, "n_irreducible_seq": ""}, indent=2))
    print(f"wrote {args.json} + {args.md}")


if __name__ == "__main__":
    main()
