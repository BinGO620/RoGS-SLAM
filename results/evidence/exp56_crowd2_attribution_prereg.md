# EXP56 预注册 — crowd2 归因补全：P11+DynKF+Reliability 双变量臂

> 版本：2026-08-29；本文件在任何 EXP56 GPU run 前冻结并 commit。
> 正式 GPU 仅限 jiangwenheng 双 RTX 3090，每卡固定串行 worker。
> 主指标：完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`（evo `-a` Horn）。

## 1. 目的

EXP54 建立了 mv_no_box 的归因（DynKF 单变量充分），但 crowd2 的归因不完整：
DynKF（5.16）和 Reliability（6.00）单独都不足以恢复 Combined（2.11），剩余解释
= 组件交互或 `mask_insertion`。Limitations §9 因此必须声明"crowd-regime 增益
归因于 bundle 而非组件"。

本实验加跑**双变量臂 P11+DynKF+Reliability**（与 Combined 只差 `mask_insertion`）：

- 若双变量臂 ≈ Combined → crowd2 的增益 = DynKF+Reliability 交互，
  `mask_insertion` 排除 → Limitations §9 收窄为"仅 mask_insertion 未隔离"。
- 若双变量臂仍 ≫ Combined → `mask_insertion` 是必要成分 → 保留现有 bundle 归因。

## 2. 冻结臂定义

继承 EXP54 的 P11 基线 resolved 配置（同 EXP54 prereg §2），唯一方法介入 =
同时开启 `DynamicKeyframe.enabled=true` + `ReliabilitySignal.enabled=true`。
`mask_insertion` 保持 false（与 Combined 的唯一差异键）。

新配置：`configs/rgbd/experiments/exp56_crowd2_attribution/exp56_p11_dynkf_reliability_crowd2.yaml`

EXP54 的既有数据（P11 / +DynKF / +Reliability / Combined）**复用不重跑**。

## 3. 矩阵

```text
1 arm × 1 sequence × 3 seeds = 6 runs（crowd2 only）
```

## 4. 硬门

沿用 EXP54 runner 模式：
- EXPECTED_HEAD 门 + tracked worktree 干净；
- flow 预检（crowd2 的 flow_raft 已存在）；
- resolved config.yml 断言：`DynamicKeyframe.enabled=true` 且
  `ReliabilitySignal.enabled=true` 且 `SemanticMask.mask_insertion=false`。

## 5. 判读（冻结）

地板 = `max(0.43, 0.06 × max(双变量均值, Combined 2.1086))` = 0.43 cm（Combined 更低，
6%×2.11=0.13，故地板=0.43）。

| 分支 | 条件 | 结论 |
|---|---|---|
| INTERACTION-SUFFICIENT | |双变量均值 − 2.1086| < 0.43 | crowd2 增益 = DynKF×Reliability 交互；mask_insertion 排除 |
| INSERTION-NEEDED | 双变量均值 > 2.1086 + 0.43 | mask_insertion 是必要成分；bundle 归因保留 |
| PARTIAL | 介于其间 | 双变量部分恢复；三成分均贡献；bundle 归因保留并量化 |

三种结果都不改变 mv_no_box 结论和 §5.2 的 regime split 主叙事。

## 6. 禁止事项

- 不追加 seed；不跑 mv_no_box（已闭合）；
- 不因结果中途改配置；
- 不把 EXP54/56 的数字与 P-B/WP-A 合并统计。
