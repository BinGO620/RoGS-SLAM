# P2-T 3090 verdict (远程双 RTX 3090, 2026-08-09) — 论文正式 ATE

> 36/36 run 全部 exit0（6 动态序列 × {prune,deferred} × 3 seed）。3090 是论文正式硬件；
> 主文只报 prune 臂，deferred 列进 supplementary（Table S.1）。
> 数值 = `tracking_raw.csv ate_rmse_cm`（全轨迹）与 `efficiency_raw.csv refined_num_gaussians` 的 3-seed 均值。
> 36 run 原始目录已回拉本地 `results/runs/P2/P2-T_3090/`。

## Main table (3-seed mean ± own sd, 3090)

| seq | prune G±sd | deferred G±sd | prune ATE±sd | deferred ATE±sd | G_def/G_prune |
|---|---|---|---|---|---|
| balloon | 35513±5595 | 22378±1850 | **3.06**±0.14 | 3.29±0.17 | 0.630 |
| balloon2 | 45197±9443 | 24808±1741 | **5.28**±0.11 | 5.67±0.38 | 0.549 |
| mv_no_box | 41568±4202 | 30805±3155 | **2.66**±0.12 | 3.19±0.15 | 0.741 |
| mv_no_box2 | 62266±10864 | 54028±9193 | **5.14**±0.28 | 6.18±0.94 | 0.868 |
| pt1 | 53915±5319 | 39739±1855 | **10.04**±0.58 | 14.91±3.29 | 0.737 |
| pt2 | 69718±20027 | 44246±4415 | **10.44**±0.84 | 15.93±4.55 | 0.635 |

## competitive floor (prune-only, 3090)

**balloon 3.06 cm / mv_no_box 2.66 cm** —— 介于 RGD-SLAM 2.26 与 DG-SLAM 3.65 之间。
pt1/pt2 仍是 10 cm+，诚实报告。

## vs 2060 开发数（同量级同方向，3090 版为正文）

| seq | 2060 ATE | 3090 ATE | 方向 |
|---|---|---|---|
| balloon | 3.07 | **3.06** | 持平 |
| balloon2 | 5.22 | **5.28** | 持平 |
| mv_no_box | 2.58 | **2.66** | 持平 |
| mv_no_box2 | 4.68 | **5.14** | 略升 |
| pt1 | 10.97 | **10.04** | 略降 |
| pt2 | 10.35 | **10.44** | 持平 |

全部同量级同方向 ⇒ 3090 数字可直接上正文替换 2060 版。seed0 单点已验证无损（前会话），
这次是 36-run 全量一致。

## ATE no-harm 50% band (deferred vs prune)

| seq | deferred/prune ATE % worse | band |
|---|---|---|
| balloon | +7.5% | ok |
| balloon2 | +7.4% | ok |
| mv_no_box | +19.9% | ok |
| mv_no_box2 | +20.2% | ok |
| pt1 | +48.5% | ok (接近带边) |
| pt2 | **+52.6%** | **FLAG** (>50%) |

deferred ATE ≥ prune 6/6 同号（与 2060 版一致）；pt2 破 50% no-harm 带。维持
"conditional Pareto frontier" 定位（**不是** "deferred wins"），完整双臂表进
supplementary Table S.1。

## H-D (lifecycle 适用域边界) — 维持 INDETERMINATE

G_def/G_prune <1 全部序列（6/6），方向与 2060 版一致；pt1 由 0.794→0.737。但覆盖率秩的
(a)/(b) 翻转触发 prereg §4 ⇒ H-D 三分支仍 **INDETERMINATE**（不升级 CONFIRMED，因低覆盖
方向是 exploratory，非同向秩相关）。**不构成"验证成立"，只作可证伪 gating 假设的方向观察**。

## Decision

1. **主文 §4.5 换用 3090 prune 列**（balloon 3.06 / mv_no_box 2.66）。
2. **§4.1 硬件行 2060 → RTX 3090**。
3. Abstract / Intro-contribution-3 / Conclusion 的 ATE 引用同步更新。
4. supplementary §S.1 换 3090 双臂表。
5. G 数（prune backbone）在 §4.5 / supplementary 一并更新（避免旧 2060 G 与 3090 G 混用）。
