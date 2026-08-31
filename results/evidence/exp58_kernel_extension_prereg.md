# EXP58 预注册 — kernel 消融扩展（4 新序列 × cauchy/gm × 3 seed = 24 run）

> 版本：2026-08-29；本文件在任何 EXP58 GPU run 前冻结并 commit。
> 正式 GPU 仅限 jiangwenheng 双 RTX 3090，每卡固定串行 worker。
> 主指标：完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`（evo `-a` Horn）。

## 1. 目的

EXP55 在 balloon/pt2 上判决 Huber 最优（pt2 上 cauchy +1.81 / gm +2.52 均 WORSE），
但只覆盖 2 序列，§3.3 的 caveat 写明"不外推其余 16 序列"。本扩展把 kernel 对比
扩到 4 个新序列，覆盖全部四个 regime：

- `mv_no_box`（object-only，Δ_R≈0 的 easy 族）
- `pt1`（hard person，Δ_R=+0.41）
- `f3_wk_hf`（walking 高动态）
- `crowd`（crowd 族第二序列）

若扩展后结论与 EXP55 一致（Huber ≥ 替代），§3.3 的"two-sequence"措辞升级为
"six-sequence, regime-spanning"。

## 2. 冻结臂定义

方法配置复用 EXP55 的 `method_combined_cauchy.yaml` / `method_combined_gm.yaml`
（唯一覆盖 RobustTracking.kernel，δ=0.1 不变，逐字节继承
`method_combined_maskboth_prune.yaml`）。**零新方法配置。**

新 run 配置（dataset inherit 对齐主表数据源的配置链）：

| 序列 | dataset inherit | 主表源 |
|---|---|---|
| mv_no_box | `configs/rgbd/bonn/moving_nonobstructing_box.yaml` | P2-T_3090 prune |
| pt1 | `configs/rgbd/bonn/person_tracking.yaml` | P6-MASON combined |
| f3_wk_hf | `configs/rgbd/tum/f3_wk_hf.yaml` | P6-FULLKERN |
| crowd | `configs/rgbd/bonn/crowd.yaml` | P6-FULLKERN |

huber 锚 = 主表现有 3-seed（同配置 identity、同硬件），不重跑。

## 3. 矩阵

```text
2 kernels × 4 sequences × 3 seeds = 24 runs
```

## 4. 硬门

- EXPECTED_HEAD（c544b940）+ tracked worktree 干净；
- flow 预检（4 序列 flow_raft 均已存在）；
- E0：resolved config.yml kernel == 预期（EXP55 同款双重断言）。

## 5. 判读（冻结，同 EXP55 §5）

地板 = max(0.43, 6% × max(锚均值, 臂均值))，逐 (序列, kernel) 报告。汇总判读：
- 4 序列全部 INDISTINGUISHABLE/WORSE → "Huber ≥ 替代"跨 regime 成立（升级措辞）；
- 任何 BETTER → kernel 选择 regime-dependent（新发现，需用户决策）。
跨 campaign 漂移纪律（~30%）与 3-seed 描述性 caveat 沿用 EXP55 §3。

## 6. 禁止事项

- 不追加 seed/序列；不重跑 huber 锚；不把 EXP58 与 EXP55 的均值合并统计
  （报告为两个 campaign 的同向证据）。
