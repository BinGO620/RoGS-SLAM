# EXP59 预注册 — boundary band 新序列验证（6 基准外序列 × 2 臂 × 3 seed = 36 run）

> 版本：2026-08-29；本文件在任何 EXP59 GPU run 前冻结并 commit。
> 正式 GPU 仅限 jiangwenheng 双 RTX 3090。主指标：`tracking_raw.csv` 的
> `ate_rmse_cm` 与 `rpe_trans_rmse_cm`。

## 1. 目的

§5.6/Limitations §7 的 boundary 诊断：mask-free RPE 把 mask-redundant 与
mask-necessary 两组分得完全不重叠（0.222–1.572 vs 1.717–2.980），预注册中点
τ=1.6445 在 5 条 held-out 序列上 4/4 判决格一致。**未验证的是 band 的位置**
（held-out RPE 无一落在 (1.572, 1.717) 带内）——这是 Limitations §7 明示的
future work。

本实验在 6 条**从未参与任何 campaign** 的 BONN 序列上跑 2 臂，测：
1. mask-free RPE 是否继续分离两组（方向验证）；
2. 是否有 RPE 落入 band 内（位置验证——band 位置可判的唯一方式）。

## 2. 序列冻结（基准外，绝不混入 18 序列分母）

crowd3, kidnapping_box, kidnapping_box2, balloon_tracking, balloon_tracking2,
placing_nonobstructing_box。全部 BONN 官方 GT；flow 需现建（build_flow_raft.py）。

## 3. 矩阵

```text
6 sequences × 2 arms (mask-free, combined) × 3 seeds = 36 runs
```

## 4. 硬门

- EXPECTED_HEAD + worktree 干净；
- 每 run resolved config 断言臂 identity（SemanticMask.enabled true/false）。

## 5. 判读（冻结，描述性）

对每条新序列计算 mask-free RPE 与 N = ATE(mask-free)/ATE(combined)：
- RPE > 1.717 且 N > 1.5 → 与 band 预测一致（necessary 侧）；
- RPE < 1.572 且 N ≤ 1.2 → 一致（redundant 侧）；
- RPE 落入 (1.572, 1.717) → **band 内点**——直接检验 band 位置（首要目标）；
- 任何 RPE > 1.717 但 N ≤ 0.8（或反向）→ 反例，band 规则被反驳。

汇总结论无论方向都写入 §5.6/S8 作为 out-of-sample 证据；正例不夸大、反例
不隐藏。3-seed 描述性，无显著性检验。

## 6. 禁止事项

- 结果不得混入 18 序列主表或任何既有均值；
- 不因初步结果追加/替换序列；
- 反例如实报告（本实验的首要价值之一就是找反例）。
