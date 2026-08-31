# EXP54 预注册：P11 单变量组件归因（crowd2 / mv_no_box）

> 版本：2026-08-28；本文件必须在任何 EXP54 GPU run 前冻结。
> 正式硬件仅限 jiangwenheng 双 RTX 3090，每卡单任务；本地 2060 不进入判决。

## 1. 目的

EXP53 证明 Combined 在 `crowd2` 和 `mv_no_box` 上优于 P11，但 P11→Combined 同时打开了三个开关：

- `DynamicKeyframe.enabled: false → true`；
- `ReliabilitySignal.enabled: false → true`；
- `SemanticMask.mask_insertion: false → true`。

EXP54 只回答前两个候选组件是否能解释当前差异。它不是新的全局冠军实验，也不重新跑 18 序列。

## 2. 冻结臂定义

所有新臂继承 EXP53 P11 的 resolved 配置，保持以下内容不变：相同数据集、`mask_mapping=true`、`mask_insertion=false`、RobustTracking Huber、`Mapping.lifecycle_mode=prune`、`DeferredCommit`、训练预算和评估配置。

| 臂 | 唯一方法介入 | 诊断 |
|---|---|---|
| P11（既有基线） | 无；复用 EXP53 `p11phase2` 同 HEAD 结果 | `KeyframeDiag` 未开启的历史基线 |
| P11 + DynKF | 仅 `DynamicKeyframe.enabled=true`（保留 `gap_cap=5`） | `KeyframeDiag.enabled=true` |
| P11 + Reliability | 仅 `ReliabilitySignal.enabled=true` | `KeyframeDiag.enabled=true` |

`P11 + Reliability` 的 `DeferredCommit.reliability_confirm=true` 继承自 P11 的 prune 合同；Reliability 开启后候选确认从整数 support/contradiction 变为加权 C±。因此该臂的 estimand 是 **Reliability 信号族联合效应**（tracking RGB/depth 降权 + 候选确认加权），不是纯 tracking down-weight。

`KeyframeDiag` 是只读 instrumentation，不参与 tracking、mapping 或 keyframe 决策；它记录逐帧 `covis/crisis` 原因和 projected-person 分解。它不构成第三个方法介入。

## 3. 矩阵

目标序列固定为 `crowd2`、`mv_no_box`；每个介入臂 seed `0/1/2`，共 12 个新增 run：

```text
2 sequences × 2 intervention arms × 3 seeds = 12 runs
```

P11 seed 结果复用 EXP53：不重复跑，不与其他 campaign 均值合并。

新配置：

- `configs/rgbd/experiments/exp54_component_attribution/exp54_p11_dynkf_{crowd2,mv_no_box}.yaml`
- `configs/rgbd/experiments/exp54_component_attribution/exp54_p11_reliability_{crowd2,mv_no_box}.yaml`

## 4. 指标与完成门

主指标冻结为完整轨迹 `tables/tracking_raw.csv:ate_rmse_cm`，evo `-a` Horn；报告每 seed、mean±sample sd（ddof=1）、ATE <5 cm 逃逸率。

每个 run 必须同时收集：

- `status=OK`、完整轨迹和 completion；
- KF 数、KF gap、`keyframe_diag.csv` 的 `trigger_reason` 计数；
- Reliability 臂的完整 `reliability_signal/frames.csv`、summary 和 flow coverage；
- DeferredCommit 的 candidate/promote/reject/expire/prune/overflow 统计；
- online FPS、Gaussian 数量和显存。

失败 run、flow 缺失、诊断文件缺失或配置漂移不自动补均值；先标为 unresolved。

## 5. 分阶段 GPU 纪律

### Phase 0：机制自检

先跑 `crowd2` seed0 的两个介入臂（2 run），只检查：run 完成、配置实际生效、DynKF 臂有 keyframe diagnostics、Reliability 臂有完整 flow/reliability artifact。Phase 0 不判 ATE 优劣。

### Phase 1：信号量级

Phase 0 全部通过后，跑剩余矩阵的一个目标序列（`crowd2` seeds1/2 + `mv_no_box` seed0，两个介入臂，共 6 run）。只看 ATE 是否明显超过既有同 seed 噪声地板以及 activity 是否完整；若两个介入都无可读信号，停止，不跑剩余 6 run。

### Phase 2：正式 3-seed 完整矩阵

只有 Phase 1 显示至少一个介入具有可读方向，才跑剩余 `mv_no_box` seeds1/2 的 4 run，完成 12-run矩阵并判决。若某臂在 Phase 0/1 出现配置或 artifact 失败，停跑并保留原始结果。

## 6. 预注册判读

相对每个序列已冻结的 EXP53 P11 基线 `P11_mean` 与 Combined 参考 `C_mean`，报告单变量介入均值和逐 seed 方向。使用 6% 的工程噪声地板 `max(0.43 cm, 0.06 × max(P11_mean, C_mean))` 作为描述性参考，不声称统计显著。

- `P11 + DynKF` 接近 Combined 而 `P11 + Reliability` 接近 P11：支持 DynKF 是主要解释，仍报告 insertion 未测。
- `P11 + Reliability` 接近 Combined 而 DynKF 接近 P11：支持 Reliability 信号族是主要解释。
- 两臂都恢复部分：保留 Combined bundle / regime split，不选单一冠军。
- 两臂都不能恢复：检查 `mask_insertion` 或交互，不能强行归因。

“接近”定义为介入均值与 Combined 均值的差不超过该序列地板；这只是预注册工程判读，不是显著性检验。

## 7. 禁止事项

- 不把 EXP53 的 P11→Combined 差值当成单组件效应；
- 不把 P-B、WP-A、P7 或 FULLKERN 的均值并入 EXP54；它们只作方向性历史参考；
- 不改共享 base、vanilla 默认、`gap_cap=5` 或现有 P11 配置；
- 不追加 seed，不用 2060/V100 数字进入正式均值；
- 不把 `ReliabilitySignal` 臂描述为纯 tracking 归因；
- 不在未完成 3-seed 矩阵前写正式组件胜负。

## 8. 当前预期

EXP53 零 GPU审计已确认：Combined 的五帧 KF 结构和 Reliability activity 可观察，但没有 `covis/crisis` 逐帧原因，不能做因果拆分。EXP54 的最小新增矩阵就是关闭这一缺口所需的定向证据，不是对全表的重新搜索。
