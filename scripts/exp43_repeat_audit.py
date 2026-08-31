#!/usr/bin/env python3
"""exp43 Phase -1 —— 全盘 within-config 重复跑盘点（零 GPU）。

## 问题

竞品论文一律报 3-seed 均值，**没有一篇报崩溃率**。本项目却反复撞到同一件事：
同 config 同 seed 重复跑，ATE 可以差一倍以上（B-CRASHRATE 37.0→73.1；exp26 2.99→33.70）。
若这个信号在全盘数据上普遍且强，它就是一条**我们独有、竞品未报**的贡献轴；
若它只在少数臂上出现，就当场判死，不再投入。

## 口径

- **重复 = 同 method（config 身份）+ 同 sequence + 同 seed 的多次 run。**
  两种来源都算：① 多个 run 目录；② 同一个 `tracking_raw.csv` 里的多行
  （exp36 发现过：同 config 同 seed 跑两次写进同一目录）。
- 主统计量 = `ratio = max/min`（对量纲不敏感，跨序列可比），
  次统计量 = `ptp`、`cv`。
- **不定义"崩溃"的绝对阈值**——不同序列量纲差 10 倍以上，绝对阈值会把
  难序列全判成崩。改报 ratio 分布，让强度自己说话。
- 对照量 = **between-seed 离散**（同 method 同 sequence、跨 seed 的 ratio），
  用于回答"within-config 抖动是不是只是 seed 方差的影子"。

## 判读（跑前写死）

设 R = within-config ratio 的分布：
  * median(R) ≥ 1.5 且 n_groups ≥ 20        → **信号强**，值得立项
  * 1.2 ≤ median(R) < 1.5，或强信号集中在少数序列 → **regime-dependent**，需按序列分层再判
  * median(R) < 1.2                          → **判死**，不再投入

并列必须同报：within vs between 的比较（exp37 在 balloon 上测到 between 主导 3.6×，
若全盘也如此，则"崩溃率"叙事的独特性下降——那只是普通的 seed 敏感）。

用法：conda run -n monogs-ours python scripts/exp43_repeat_audit.py
"""

import csv
import glob
import json
import os
import re
from collections import defaultdict

import numpy as np

ROOT = "results/runs"


def campaign_of(csv_path):
    """results/runs/<CAMPAIGN>/... -> CAMPAIGN (two levels, e.g. P6/P6-FULLKERN).

    PROVENANCE GATE (added after the first pass produced a contaminated verdict):
    the same `method` string does NOT mean the same effective configuration across
    the project's history. The first pass's top groups (10-19x) paired 2026-08-10/12
    runs against 2026-08-16/17 `*FULLKERN*` runs -- i.e. runs made BEFORE and AFTER
    exp24's flow-sync repair, where ReliabilitySignal was silently a no-op (w==1)
    because the frozen flow index was empty (registry row EXP24-FLOWSYNC). That is a
    documented systematic kernel-ON/OFF delta, not run-to-run nondeterminism.
    Restricting repeats to the same campaign directory keeps code + frozen assets
    + hardware fixed, which is what "same config" has to mean here.
    """
    parts = os.path.normpath(csv_path).split(os.sep)
    try:
        i = parts.index("runs")
    except ValueError:
        return "?"
    return "/".join(parts[i + 1:i + 3])


def collect():
    """(method, sequence, seed, campaign) -> [ate, ...] plus provenance."""
    groups = defaultdict(list)
    n_files = n_rows = 0
    for path in glob.glob(os.path.join(ROOT, "**", "tracking_raw.csv"), recursive=True):
        n_files += 1
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    ate = row.get("ate_rmse_cm")
                    if not ate:
                        continue
                    try:
                        v = float(ate)
                    except ValueError:
                        continue
                    if not np.isfinite(v) or v <= 0:
                        continue
                    key = (
                        (row.get("method") or "").strip(),
                        (row.get("sequence") or "").strip(),
                        (row.get("seed") or "").strip(),
                        campaign_of(path),
                    )
                    groups[key].append({"ate": v, "run_id": (row.get("run_id") or "").strip(), "csv": path})
                    n_rows += 1
        except Exception:
            continue
    return groups, n_files, n_rows


def dedup_runs(entries):
    """One physical run = one (run_id) ; same run_id appearing in several csv copies
    (results are rsynced/copied around) must not be counted as a repeat."""
    seen = {}
    for e in entries:
        rid = e["run_id"] or f"__norid__{e['ate']:.6f}"
        # keep first occurrence; identical run_id with identical ate is the same run
        if rid not in seen:
            seen[rid] = e
    return list(seen.values())


def stats(vals):
    v = np.asarray(sorted(vals), dtype=float)
    return {
        "n": int(v.size),
        "min": float(v.min()),
        "max": float(v.max()),
        "median": float(np.median(v)),
        "ratio": float(v.max() / v.min()),
        "ptp": float(v.max() - v.min()),
        "cv": float(v.std(ddof=1) / v.mean()) if v.size > 1 else 0.0,
        "values": [round(x, 4) for x in v],
    }


def main():
    groups, n_files, n_rows = collect()

    within = {}
    for key, entries in groups.items():
        runs = dedup_runs(entries)
        if len(runs) < 2:
            continue
        method, seq, seed, camp = key
        if not method or not seq:
            continue
        within[key] = stats([r["ate"] for r in runs])

    # between-seed control: same method+sequence+campaign, one value per seed
    by_ms = defaultdict(dict)
    for (method, seq, seed, camp), entries in groups.items():
        runs = dedup_runs(entries)
        if not runs or not method or not seq:
            continue
        by_ms[(method, seq, camp)][seed] = float(np.median([r["ate"] for r in runs]))
    between = {k: stats(list(d.values())) for k, d in by_ms.items() if len(d) >= 2}

    R = np.array([s["ratio"] for s in within.values()])
    B = np.array([s["ratio"] for s in between.values()])

    print("=" * 72)
    print("exp43 全盘 within-config 重复跑盘点（零 GPU）")
    print("=" * 72)
    print(f"扫描 {n_files} 个 tracking_raw.csv / {n_rows} 行 ⇒ "
          f"within-config 重复组 {len(within)} 个 · between-seed 组 {len(between)} 个")
    if R.size == 0:
        print("没有重复组，判死。")
        return

    def q(a, p):
        return float(np.percentile(a, p))

    print()
    print(f"【主统计量】within-config ratio = max/min，n={R.size} 组")
    print(f"   median {np.median(R):.3f} | mean {R.mean():.3f} | p75 {q(R,75):.3f} | p90 {q(R,90):.3f} | max {R.max():.3f}")
    for t in (1.2, 1.5, 2.0, 3.0):
        print(f"   ratio > {t:>3}: {int((R > t).sum()):>3}/{R.size}  ({100*(R > t).mean():.0f}%)")

    if B.size:
        print()
        print(f"【对照】between-seed ratio，n={B.size} 组")
        print(f"   median {np.median(B):.3f} | p75 {q(B,75):.3f} | p90 {q(B,90):.3f} | max {B.max():.3f}")
        print(f"   ⇒ within/between 中位数比 = {np.median(R)/np.median(B):.2f}")

    print()
    print("【最强的 12 组 within-config】")
    top = sorted(within.items(), key=lambda kv: -kv[1]["ratio"])[:12]
    for (method, seq, seed, camp), s in top:
        print(f"   {s['ratio']:5.2f}×  n={s['n']}  {seq[:30]:<30} seed{seed:<2} "
              f"[{s['min']:.2f} .. {s['max']:.2f}]  {camp[:24]}")

    # per-sequence breakdown: is the signal concentrated?
    per_seq = defaultdict(list)
    for (method, seq, seed, camp), s in within.items():
        per_seq[seq].append(s["ratio"])
    print()
    print("【按序列分层】(组数 ≥ 2 的序列，按 median ratio 排序)")
    rows = [(seq, len(v), float(np.median(v)), float(np.max(v))) for seq, v in per_seq.items() if len(v) >= 2]
    for seq, n, med, mx in sorted(rows, key=lambda r: -r[2])[:14]:
        print(f"   median {med:5.2f}× (max {mx:5.2f}×)  n={n:<3} {seq}")

    verdict = ("信号强 ⇒ 值得立项" if (np.median(R) >= 1.5 and R.size >= 20)
               else ("regime-dependent ⇒ 需分层再判" if np.median(R) >= 1.2 else "判死"))
    print()
    print(f"【判读】median(R) = {np.median(R):.3f}, n_groups = {R.size}  ⇒  {verdict}")

    out = {
        "n_csv_files": n_files, "n_rows": n_rows,
        "n_within_groups": len(within), "n_between_groups": len(between),
        "within_ratio": {"median": float(np.median(R)), "mean": float(R.mean()),
                          "p75": q(R, 75), "p90": q(R, 90), "max": float(R.max()),
                          "frac_gt_1_2": float((R > 1.2).mean()), "frac_gt_1_5": float((R > 1.5).mean()),
                          "frac_gt_2": float((R > 2.0).mean())},
        "between_ratio": ({"median": float(np.median(B)), "p75": q(B, 75), "p90": q(B, 90),
                            "max": float(B.max())} if B.size else None),
        "verdict": verdict,
        "groups": {f"{m}|{s}|{sd}|{c}": st for (m, s, sd, c), st in sorted(within.items(), key=lambda kv: -kv[1]["ratio"])},
    }
    dst = "results/evidence/exp43_repeat_audit.json"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\n-> {dst}")


if __name__ == "__main__":
    main()
