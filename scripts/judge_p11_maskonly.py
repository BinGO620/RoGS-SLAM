#!/usr/bin/env python3
"""judge_p11_maskonly.py — P11 sparse-KF mask-only 三路判决 (exp28, 2026-08-19)

判据（跑前冻结，来自 NEXT_SESSION_PROMPT.md exp27 交接 + WP-M/WP-A 参照值）：

  稳定性判据 (f3_st_hf 不崩): 每 seed ATE ≤ 10 cm 记为活。
    参照: combined 29.43±8.00 (崩), WP-M mask-only 5.46±1.61 (活), vanilla exp26 4/5 崩。
    "不崩" = 3/3 seed 活。
  动态增益判据 (balloon): mean ATE 相对 WP-A vanilla 38.35 改善 ≥ 2× (即 mean ≤ 19.2)。
    参照: WP-M mask-only 2.95, combined 3.06。
  泛化参考 (mv_no_box vs vanilla 6.36; f2_xyz 健康线 < 5 cm) — 不进主判据，只报告。

  路径 A: 不崩 且 balloon 有改善 → mask-only 成立，写 3DGS-specific evaluation
  路径 B: 不崩 且 balloon 无改善 → 增益来自 reliability/dense KF，做 queue-aware + ego-protected
  路径 C: f3_st_hf 仍崩 (任一 seed > 10) → 问题在 MonoGS 底层，调整论文定位

输出: results/evidence/p11_maskonly_verdict.md
"""
import csv, math, statistics
from pathlib import Path

ROOT = Path("/data/monogs-ours/results/runs/P11/P11-MASKONLY-2060")
OUT = Path("/data/monogs-ours/results/evidence/p11_maskonly_verdict.md")
SEQS = ["f3_st_hf", "balloon", "f2_xyz", "mv_no_box"]
SEEDS = [0, 1, 2]
COLLAPSE_CM = 10.0
VANILLA = {"balloon": 38.35, "mv_no_box": 6.36}  # WP-A K0R0L0 同协议 3-seed mean
WPM_MASKONLY = {"f3_st_hf": 5.46, "balloon": 2.95, "f2_xyz": 1.71, "mv_no_box": 3.87}
COMBINED = {"f3_st_hf": 29.43, "balloon": 3.06, "f2_xyz": 1.93, "mv_no_box": 2.66}

def read_row(p):
    rows = list(csv.DictReader(open(p)))
    return rows[0] if rows else None

data = {}
for seq in SEQS:
    for seed in SEEDS:
        d = ROOT / f"{seq}_p11maskonly_seed{seed}" / "tables"
        t = d / "tracking_raw.csv"
        e = d / "efficiency_raw.csv"
        rec = {"ate": None, "fps": None, "ngauss": None, "frames": None}
        if t.exists():
            r = read_row(t)
            if r:
                try: rec["ate"] = float(r["ate_rmse_cm"])
                except (ValueError, KeyError): pass
        if e.exists():
            r = read_row(e)
            if r:
                for k, col in [("fps", "online_fps"), ("ngauss", "num_gaussians"), ("frames", "num_frames")]:
                    try: rec[k] = float(r[col])
                    except (ValueError, KeyError): pass
        data[(seq, seed)] = rec

missing = [(s, sd) for (s, sd), r in data.items() if r["ate"] is None]
lines = ["# P11 sparse-KF mask-only 判决 — exp28 (2026-08-19)", "",
         f"> 自动生成 `scripts/judge_p11_maskonly.py`。判据冻结见脚本头。run 根 = `{ROOT}`。", ""]
if missing:
    lines += [f"**⚠ UNRESOLVED: {len(missing)}/12 run 缺 tracking_raw.csv**: {missing}", ""]

lines += ["## 表 1 — 逐 run ATE(cm) / FPS / Gaussians", "",
          "| 序列 | seed0 | seed1 | seed2 | mean±sd | WP-M maskonly | combined | vanilla |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
means = {}
for seq in SEQS:
    ates = [data[(seq, s)]["ate"] for s in SEEDS]
    ok = [a for a in ates if a is not None]
    m = statistics.mean(ok) if ok else float("nan")
    sd = statistics.stdev(ok) if len(ok) > 1 else 0.0
    means[seq] = (m, sd, ates)
    fmt = lambda a: f"{a:.2f}" if a is not None else "—"
    lines.append(f"| {seq} | {fmt(ates[0])} | {fmt(ates[1])} | {fmt(ates[2])} | "
                 f"{m:.2f}±{sd:.2f} | {WPM_MASKONLY[seq]} | {COMBINED[seq]} | "
                 f"{VANILLA.get(seq, '—')} |")

lines += ["", "## 表 2 — 效率 (mean over completed seeds)", "",
          "| 序列 | online FPS | num_gaussians | frames |", "|---|---:|---:|---:|"]
for seq in SEQS:
    recs = [data[(seq, s)] for s in SEEDS]
    def mfield(k):
        v = [r[k] for r in recs if r[k] is not None]
        return f"{statistics.mean(v):.3f}" if v else "—"
    lines.append(f"| {seq} | {mfield('fps')} | {mfield('ngauss')} | {mfield('frames')} |")

# 判决
alive = [a is not None and a <= COLLAPSE_CM for a in means["f3_st_hf"][2]]
stable = all(alive) and len(alive) == 3
bal_mean = means["balloon"][0]
bal_gain = (not math.isnan(bal_mean)) and bal_mean <= VANILLA["balloon"] / 2

if missing:
    verdict = "UNRESOLVED（run 不全，不判）"
elif not stable:
    verdict = "路径 C — f3_st_hf 仍崩溃：问题在 MonoGS 底层 / 数据，调整论文定位"
elif bal_gain:
    verdict = "路径 A — mask-only 成立：dense KF + reliability 是过度工程；下一步写 3DGS-specific evaluation"
else:
    verdict = "路径 B — 静态稳但动态无增益：增益来自 reliability / dense KF；下一步 queue-aware budget + ego-protected reliability"

lines += ["", "## 判决", "",
          f"- f3_st_hf 逐 seed 活(≤{COLLAPSE_CM}cm): {alive} → 稳定性 {'PASS' if stable else 'FAIL'}",
          f"- balloon mean {bal_mean:.2f} vs vanilla {VANILLA['balloon']} (≥2× 改善线 {VANILLA['balloon']/2:.1f}): "
          f"{'PASS' if bal_gain else 'FAIL'}",
          "", f"**判决: {verdict}**", ""]

OUT.write_text("\n".join(lines))
print("\n".join(lines))
