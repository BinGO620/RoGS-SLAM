#!/usr/bin/env python3
"""Efficiency self-comparison + seed-stability tables (zero-GPU, from artifacts on disk).

Two gaps the paper currently cannot answer, both closable without a single new run:

  (4) EFFICIENCY. The main table has no FPS/VRAM column. Comparing our FPS against
      competitors is off-limits (different hardware, locked project rule), but the
      SELF-comparison -- what our three components cost relative to the same backbone
      without them, on the SAME 3090 -- is both legitimate and the first thing a
      reviewer asks after "you added RAFT + three modules".

  (5) STABILITY. A 3-seed mean ATE hides whether a run is reproducible or bistable.
      pt1 (+-8.5 cm) and crowd2 (+-26.0 cm) are exactly the cases where the mean is
      the wrong summary. We report the per-sequence seed spread (max/min ratio) so the
      reader sees instability instead of inferring it.

Arms are recovered from campaign directory naming:
  vanilla   WPA/*/wpa_<seq>_K0R0L0_seed<k>      (kernel OFF, mask OFF)
  mask-free P6/P6-18SEQ|P6-MASKOFF-3SEED/<seq>_maskoff_seed<k>
  combined  P6/P6-MASON|P6-MASON-8SEQ/<seq>_combined_seed<k>
  MRCS(WPA) WPA/*/wpa_<seq>_K1R1L1_seed<k>      (mask-free twin inside WP-A)
  mask-only WPM/*/wpm_<seq>_maskonly_seed<k>    (WP-M, this session)

Usage:
  python scripts/build_efficiency_stability_tables.py --runs-root /tmp/wpm_pull \
      --out results/evidence/efficiency_stability_tables.md
"""

import argparse
import csv
import glob
import os
import re
import statistics


# matched against the run directory BASENAME (anchored: a path-level match would swallow
# the campaign prefix into the sequence name)
ARM_PATTERNS = [
    (re.compile(r"^wpa_(?P<seq>.+)_K0R0L0_seed(?P<seed>\d)$"), "vanilla (K0R0L0)"),
    (re.compile(r"^wpa_(?P<seq>.+)_K1R1L1_seed(?P<seed>\d)$"), "mask-free (WP-A K1R1L1)"),
    (re.compile(r"^wpm_(?P<seq>.+)_maskonly_seed(?P<seed>\d)$"), "mask-only (WP-M)"),
    (re.compile(r"^(?P<seq>.+)_maskoff_seed(?P<seed>\d)$"), "mask-free"),
    (re.compile(r"^(?P<seq>.+)_combined_seed(?P<seed>\d)$"), "combined (mask-ON)"),
]

EFF_FIELDS = ("online_fps", "online_peak_gpu_memory_gb", "online_num_gaussians", "online_time_s")
TRK_FIELDS = ("ate_rmse_cm", "rpe_trans_rmse_cm", "path_length_ratio")


def classify(run_dir):
    name = os.path.basename(run_dir)
    for pattern, arm in ARM_PATTERNS:
        m = pattern.match(name)
        if m:
            return arm, m.group("seq"), int(m.group("seed"))
    return None, None, None


def read_row(path):
    """Last row = the LATEST completed run of that seed.

    The roll-up CSV is append-only, so a seed that was run twice has two rows. We take
    the latest, which is the same rule `build_18seq_main_table.read_ate` now uses, so the
    two tables can never disagree on which run a number came from
    (see results/evidence/main_table_provenance_audit.md).
    """
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[-1] if rows else None


def num(row, key):
    if row is None:
        return None
    v = row.get(key, "")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect(runs_root):
    records = {}
    for tracking in glob.glob(f"{runs_root}/**/tables/tracking_raw.csv", recursive=True):
        run_dir = os.path.dirname(os.path.dirname(tracking))
        arm, seq, seed = classify(run_dir)
        if arm is None:
            continue
        trk = read_row(tracking)
        eff = read_row(os.path.join(run_dir, "tables", "efficiency_raw.csv"))
        if trk is None or (trk.get("status") or "").upper() not in ("OK", ""):
            continue
        rec = {"seed": seed}
        rec.update({k: num(trk, k) for k in TRK_FIELDS})
        rec.update({k: num(eff, k) for k in EFF_FIELDS})
        records.setdefault((seq, arm), []).append(rec)
    return records


def agg(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None, None, 0
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mean, sd, len(vals)


def fmt(mean, sd, k, nd=2):
    if mean is None:
        return "—"
    return f"{mean:.{nd}f}±{sd:.{nd}f}" if k > 1 else f"{mean:.{nd}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", default="/tmp/wpm_pull")
    ap.add_argument("--out", default="results/evidence/efficiency_stability_tables.md")
    args = ap.parse_args()

    records = collect(args.runs_root)
    seqs = sorted({s for s, _ in records})
    arms = ["vanilla (K0R0L0)", "mask-free (WP-A K1R1L1)", "mask-free",
            "combined (mask-ON)", "mask-only (WP-M)"]
    arms = [a for a in arms if any(a == arm for _, arm in records)]

    out = []
    out.append("# 效率自比 + seed 稳定性表（零 GPU，全部来自已有 run 产物）\n")
    out.append("> 自动生成：`scripts/build_efficiency_stability_tables.py`。"
               "**FPS/VRAM 只做我们自己各臂之间的同硬件自比，永不与竞品并列**"
               "（竞品硬件不同，项目硬规则）。\n")
    out.append("> 重复 run 规则：同一 seed 若跑过多次，取**最新**那次——与 `build_18seq_main_table.py` "
               "同规则，两表不会对不上（见 `main_table_provenance_audit.md`）。\n")
    out.append("> 口径：`efficiency_raw.csv` 的 `online_*` 字段（在线相位，含分割与在线跟踪/建图，"
               "不含离线精修/渲染/几何评测）；ATE 取 `tracking_raw.csv` 全轨迹 `ate_rmse_cm`。\n")

    out.append("\n## 表 A —— 在线效率自比（3-seed mean±sd）\n")
    out.append("| 序列 | 臂 | online FPS | peak VRAM (GB) | 高斯数 | 在线时长 (s) | n |")
    out.append("|---|---|---:|---:|---:|---:|---:|")
    for seq in seqs:
        for arm in arms:
            recs = records.get((seq, arm))
            if not recs:
                continue
            fps = agg([r["online_fps"] for r in recs])
            mem = agg([r["online_peak_gpu_memory_gb"] for r in recs])
            ng = agg([r["online_num_gaussians"] for r in recs])
            t = agg([r["online_time_s"] for r in recs])
            out.append(
                f"| {seq} | {arm} | {fmt(*fps, nd=3)} | {fmt(*mem, nd=3)} | "
                f"{fmt(*ng, nd=0)} | {fmt(*t, nd=0)} | {fps[2]} |"
            )

    out.append("\n## 表 B —— seed 稳定性（均值之外必须同看的那一列）\n")
    out.append("| 序列 | 臂 | ATE (cm) | seed 极差比 max/min | RPE (cm/frame) | 路径长比 | n |")
    out.append("|---|---|---:|---:|---:|---:|---:|")
    for seq in seqs:
        for arm in arms:
            recs = records.get((seq, arm))
            if not recs:
                continue
            ates = [r["ate_rmse_cm"] for r in recs if r["ate_rmse_cm"] is not None]
            ate = agg(ates)
            spread = (max(ates) / min(ates)) if len(ates) > 1 and min(ates) > 0 else None
            rpe = agg([r["rpe_trans_rmse_cm"] for r in recs])
            plr = agg([r["path_length_ratio"] for r in recs])
            flag = " ⚠" if spread is not None and spread >= 2.0 else ""
            out.append(
                f"| {seq} | {arm} | {fmt(*ate)} | "
                f"{'—' if spread is None else f'{spread:.2f}×{flag}'} | "
                f"{fmt(*rpe)} | {fmt(*plr, nd=1)} | {ate[2]} |"
            )

    out.append("\n> ⚠ = 同一配置下 3 个 seed 的 ATE 极差 ≥2×，**该格的均值不可单独引用**，"
               "必须与极差同写（pt1/crowd2 是已知的双稳态格）。\n")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"wrote {args.out}  ({len(records)} 个 (序列,臂) 组合)")


if __name__ == "__main__":
    main()
