# P11 sparse-KF mask-only 判决 — exp28 (2026-08-19)

> 自动生成 `scripts/judge_p11_maskonly.py`。判据冻结见脚本头。run 根 = `/data/monogs-ours/results/runs/P11/P11-MASKONLY-2060`。

**⚠ UNRESOLVED: 12/12 run 缺 tracking_raw.csv**: [('f3_st_hf', 0), ('f3_st_hf', 1), ('f3_st_hf', 2), ('balloon', 0), ('balloon', 1), ('balloon', 2), ('f2_xyz', 0), ('f2_xyz', 1), ('f2_xyz', 2), ('mv_no_box', 0), ('mv_no_box', 1), ('mv_no_box', 2)]

## 表 1 — 逐 run ATE(cm) / FPS / Gaussians

| 序列 | seed0 | seed1 | seed2 | mean±sd | WP-M maskonly | combined | vanilla |
|---|---:|---:|---:|---:|---:|---:|---:|
| f3_st_hf | — | — | — | nan±0.00 | 5.46 | 29.43 | — |
| balloon | — | — | — | nan±0.00 | 2.95 | 3.06 | 38.35 |
| f2_xyz | — | — | — | nan±0.00 | 1.71 | 1.93 | — |
| mv_no_box | — | — | — | nan±0.00 | 3.87 | 2.66 | 6.36 |

## 表 2 — 效率 (mean over completed seeds)

| 序列 | online FPS | num_gaussians | frames |
|---|---:|---:|---:|
| f3_st_hf | — | — | — |
| balloon | — | — | — |
| f2_xyz | — | — | — |
| mv_no_box | — | — | — |

## 判决

- f3_st_hf 逐 seed 活(≤10.0cm): [False, False, False] → 稳定性 FAIL
- balloon mean nan vs vanilla 38.35 (≥2× 改善线 19.2): FAIL

**判决: UNRESOLVED（run 不全，不判）**
