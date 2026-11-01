#!/usr/bin/env python
"""verify_table1.py — 从 results/runs/P6/**/tracking_raw.csv 重算论文1 Table 1，
与 results/evidence/table1_18seq_ate.csv 逐格核对。

规则：对表中每格（mean±std, n=3 seeds），在 run 组（按 tracking_raw 的 sequence 字段
分组）中找「序列名匹配 + mean 差 <0.02cm（表值舍入容差）+ std 匹配」的组。
表值由 3-seed 样本 std（ddof=1）四舍五入而来，两种 std 口径都接受。

已知边界（见 PROVENANCE.md）：tar 归档只含 P6 家族的判据小件，vanilla（MonoGS 原版）
与 rgd（对照方法）两列的 run 工件不在其中——这两列预期报 NO-RUN-IN-REPO，
其数字以 evidence CSV 为准（来源登记见 MMM2027 deliverable）。
"""
import csv
import glob
import os
import re
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T1 = os.path.join(ROOT, "results", "evidence", "table1_18seq_ate.csv")
COLS = ("vanilla", "maskfree", "combined", "rgd")


def parse_cell(cell):
    m = re.match(r"([0-9.]+)±([0-9.]+)", (cell or "").strip())
    return (float(m.group(1)), float(m.group(2))) if m else None


def main():
    table = list(csv.DictReader(open(T1)))
    rows = []
    # 数据源 1：P6 布局 runs/<family>/<exp>/datasets_x/<run>/seed_N/<ts>/tracking_raw.csv → family = -7
    # 数据源 2：WPB 布局 runs/<family>/<exp>/tables/tracking_raw.csv → family = -4
    for pat, fam_idx in (("results/runs/*/*/*/datasets_*/**/tracking_raw.csv", -7),
                         ("results/runs/*/*/tables/tracking_raw.csv", -4)):
        for f in glob.glob(os.path.join(ROOT, pat), recursive=True):
            family = f.split(os.sep)[fam_idx]
            for r in csv.DictReader(open(f)):
                try:
                    rows.append((family, r["sequence"], float(r["ate_rmse_cm"])))
                except (KeyError, ValueError):
                    continue
    groups = {}
    for family, seq, ate in rows:
        groups.setdefault((family, seq), []).append(ate)

    matched, no_run = 0, 0
    print(f"runs: {len(rows)} 行 / {len(groups)} 组")
    print(f"{'seq':14}{'col':9}{'table':>14}  {'run 组':38} verdict")
    for row in table:
        seq = row["seq"]
        for col in COLS:
            cell = parse_cell(row[col])
            if not cell:
                continue
            m, s = cell
            hit = None
            # 双重分组匹配：① (family, sequence) 精确；② 仅 sequence 合并
            # （论文批次有"跨族补种子"历史：如 balloon/maskfree 的 3 seeds 分属
            #   P6-MASKOFF 与 P6-MASKOFF-3SEED，按族分组会拆散）
            merged = {}
            for (family, name), ates in groups.items():
                merged.setdefault(name, []).extend(ates)
            for pool in (groups, merged):
                for key, ates in pool.items():
                    name = key[1] if isinstance(key, tuple) else key
                    if not re.search(rf"(^|_){re.escape(seq)}(_|$)", name):
                        continue
                    gm = st.mean(ates)
                    ss = st.stdev(ates) if len(ates) > 1 else 0.0
                    ps = st.pstdev(ates) if len(ates) > 1 else 0.0
                    if abs(gm - m) < 0.02 and (abs(ss - s) < 0.03 or abs(ps - s) < 0.03):
                        tag = f"{key[0]}/{key[1]}" if isinstance(key, tuple) else f"(跨族合并){name}"
                        hit = (tag, len(ates), gm, ss)
                        break
                if hit:
                    break
            if hit:
                matched += 1
                print(f"{seq:14}{col:9}{m:>7.2f}±{s:<5.2f}  {hit[0]:38} n={hit[1]} {hit[2]:.2f}±{hit[3]:.2f}  MATCH")
            else:
                no_run += 1
                print(f"{seq:14}{col:9}{m:>7.2f}±{s:<5.2f}  {'—':38} NO-RUN-IN-REPO")
    print(f"\n核对完成：MATCH={matched}  NO-RUN-IN-REPO={no_run}")
    print("说明：combined/maskfree 列应全部 MATCH；vanilla/rgd 列无 run 工件属预期（见文件头说明）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
