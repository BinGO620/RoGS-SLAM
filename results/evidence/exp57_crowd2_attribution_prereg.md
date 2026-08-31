# EXP57 预注册 — P11+mask_insertion 单变量臂（crowd2）

> 版本：2026-08-29；本文件在任何 EXP57 GPU run 前冻结并 commit。
> 正式 GPU 仅限 jiangwenheng 双 RTX 3090，每卡固定串行 worker。
> 主指标：完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`（evo `-a` Horn）。

## 1. 目的

EXP56 判决 INSERTION-NEEDED：双变量臂（DynKF+Reliability）4.55±1.38 仍远超 Combined
2.11，说明 `mask_insertion` 是 crowd2 上 Combined 优势的必要成分。但 `mask_insertion`
的**单独**贡献从未被测量（EXP54/56 只测了 DynKF 和 Reliability）。

本实验补上最后一个单变量臂 **P11+mask_insertion**（其余与 P11 相同，仅开
`SemanticMask.mask_insertion=true`），完成 crowd2 的三开关完整闭合。

## 2. 冻结臂定义

继承 EXP54 的 P11 基线 resolved 配置，唯一方法介入 = `SemanticMask.mask_insertion=true`
（DynamicKeyframe / ReliabilitySignal 保持 off）。

新配置：`configs/rgbd/experiments/exp57_crowd2_attribution/exp57_p11_mask_insertion_crowd2.yaml`

既有数据复用不重跑：P11（EXP53）、+DynKF（EXP54）、+Reliability（EXP54）、
双变量（EXP56）、Combined（EXP53）。

## 3. 矩阵

```text
1 arm × 1 sequence × 3 seeds = 3 runs（crowd2 only）
```

## 4. 硬门

- EXPECTED_HEAD 门 + tracked worktree 干净；
- flow 预检（crowd2 flow_raft 已存在）；
- resolved config.yml 断言：`SemanticMask.mask_insertion=true` 且
  `DynamicKeyframe.enabled=false` 且 `ReliabilitySignal.enabled=false`。

## 5. 判读（冻结）

地板 = max(0.43, 0.06 × max(本臂均值, Combined 2.1086))。

| 分支 | 条件 | 解读 |
|---|---|---|
| INSERTION-SUFFICIENT | |本臂均值 − 2.1086| < 0.43 | mask_insertion 单独即可恢复 Combined；组件阶梯完全闭合 |
| INSERTION-CONTRIBUTES | 本臂均值 < P11 6.89 − 0.43 且 ≥ Combined + 0.43 | mask_insertion 有实质贡献但不充分；与双变量互补 |
| INSERTION-NEUTRAL | 本臂均值 ≥ P11 − 0.43 | mask_insertion 单独无贡献；需要与其他组件交互 |

三种结果都不改变 EXP56 的 INSERTION-NEEDED 判决（mask_insertion 必要性已由双变量
不充分 + Combined 充分的对比确立）。

## 6. 禁止事项

- 不追加 seed；不跑 mv_no_box（已闭合）；
- 不因结果中途改配置；不与其他 campaign 合并统计。
