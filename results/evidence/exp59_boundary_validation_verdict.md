# EXP59 判决 — boundary band 新序列验证（6 序列 × 2 臂 × 3 seed = 36 run）

> 收割：2026-08-29；`exp59.done = ALL_DONE rc=0`（15:59:03），36/36 run rc=0，
> 36 份 `tables/tracking_raw.csv` 已同步至 `results/runs_remote_cache/EXP59/`。
> 预注册：`exp59_boundary_validation_prereg.md`（GPU run 前冻结）。
> 判决人：本会话按预注册 §5 规则机械套用，无自由裁量。

## 1. 逐序列读数（3-seed mean；RPE = mask-free 臂 `rpe_trans_rmse_cm`）

| 序列 | mf RPE | mf ATE | cb ATE | N | 预注册分支 | 判 |
|---|---:|---:|---:|---:|---|---|
| crowd3 | 2.696 | 11.08±4.13 | 1.58±0.05 | **7.00** | RPE>1.717 且 N>1.5 | **consistent-necessary** |
| kidnapping_box | 1.495 | 4.41±0.16 | 4.45±0.08 | 0.99 | RPE<1.572 且 N≤1.2 | **consistent-redundant** |
| kidnapping_box2 | 1.397 | 5.47±0.10 | 5.37±0.09 | 1.02 | RPE<1.572 且 N≤1.2 | **consistent-redundant** |
| balloon_tracking | 2.102 | 5.34±0.17 | 5.95±0.06 | **0.90** | 无匹配分支 | **miss**（预测 necessary，实测 redundant） |
| balloon_tracking2 | 2.460 | 25.10±2.65 | 23.48±4.31 | 1.07 | 无匹配分支 | **miss**（预测 necessary，实测 ambiguous） |
| placing_nonobstructing_box | 2.725 | 6.80±1.65 | 1.62±0.02 | **4.20** | RPE>1.717 且 N>1.5 | **consistent-necessary** |

## 2. 逐 seed 稳健性

- **balloon_tracking（miss，稳健）**：mf ATE 5.16/5.51/5.36 全低于 cb 5.89/6.01/5.95，
  逐 seed N = 0.87/0.93/0.90 全 <1；RPE 2.084/2.133/2.088 全 >τ。低离散，miss 成立。
- **balloon_tracking2（miss，弱化）**：cb 双稳态（18.58/25.21/26.66），逐 seed N =
  1.22/0.97/1.05；两臂都差（18–28 cm），N 的判别力本身受限。
- crowd3：mf seed0 6.51 vs seed1/2 14.56/12.16 有离散，但 cb 全部 ≈1.6 → N=7.0 稳健。
- placing_nonobstructing_box：mf RPE 2.094/3.047/3.034 离散大但全部 >1.717；N=4.2 稳健。

## 3. 对照预注册三问

1. **方向验证**：4/6 与 band 预测一致。τ 的方向性 out-of-sample 支持从第一轮
   held-out 的 4/4 弱化为合计 **8/10**；两条 miss 均为 RPE>τ 预测 necessary 而实测
   N≤1.2，集中在 balloon_tracking* 类型序列。
2. **位置验证（首要目标）**：**0 个带内点**（6 条 RPE 分布 1.397–2.696，无一落入
   (1.572, 1.717)）。band 位置仍然不可判——与第一轮 held-out 相同的结局。
3. **反例**：无。按冻结门槛（RPE>1.717 且 N≤0.8，或反向）0 例。

## 4. miss 方向分析（写进正文的关键 nuance）

两条 miss 都是**保守方向**：RPE>τ → 诊断会建议开 mask → 实际 mask-free 更好 →
代价是白开 mask（balloon_tracking 上 5.95 vs 5.34 cm，损失 0.6 cm），**不是**漏开
mask 导致失败。危险方向（RPE 低于带 → 关 mask → mask 实为必需 → 崩）本轮 0 例。
因此该诊断作为"何时可以放心不开 mask"的规则，在本轮 6 序列上**没有危险错误**；
作为"何时应该开 mask"的规则，它有 2/6 的误报。

## 5. 对正文/S8 的同步指令

- manuscript_v3 §5.5：out-of-sample 支持从"5 序列 4/4"改为"两轮共 10 条新序列、
  8/10 一致、0 带内点、0 反例；2 miss 保守方向（balloon_tracking* 类型）"。
- manuscript_v3 §6 scope 段：band 位置仍未检验 + 方向性有 2/6 保守误报。
- supplementary S8：追加 EXP59 六序列逐 seed 表。
- Conclusion："passed a pre-registered held-out check" → "passed two pre-registered
  held-out checks, with two conservative-direction misses"。

## 6. 红线核对

- 6 条新序列未混入 18 序列分母 ✓
- 未追加/替换序列 ✓
- 反例如实报告（以 miss 形式）✓
- 3-seed 描述性，无显著性检验 ✓
