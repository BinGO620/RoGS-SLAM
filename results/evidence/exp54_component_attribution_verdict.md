# EXP54 判决 — P11 单变量组件归因（crowd2 / mv_no_box）

> 执行读数与判决，判据冻结见 `exp54_component_attribution_prereg.md`。
> 所有正式运行均在 `jiangwenheng` 双 RTX 3090 上完成；本地 cb(2060) 不纳入判决。
> 12/12 run `status=OK`、`rc=0`，无 OOM、配置错误或缺失结果。
>
> **勘误（2026-08-28 晚）**：初版判决中 mv_no_box seed1/seed2 的四个值
> （DynKF 2.6831/2.6472、Reliability 3.7282/3.6724）**无 run 产物来源，系转录错误**。
> 经与远程 `tables/tracking_raw.csv`、`keyframe_ate_rmse_cm`、console.log 三方核对
> （12/12 自洽，无覆盖、无口径替换），以下已全部改为 CSV 真值；crowd2 六值与
> mv_no_box seed0 初版即正确，未动。主判决不变（见 §2.2 修订后的判读）。

## 1. 正式矩阵

主指标：完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`（evo `-a` Horn 口径）。
逃逸定义：ATE < 5 cm。

| 序列 | 臂 | seed0 | seed1 | seed2 | mean (cm) | sample sd | 逃逸 |
|---|---|---:|---:|---:|---:|---:|---:|
| crowd2 | P11（EXP53 复用） | 7.9308 | 7.7350 | 5.0033 | **6.8897** | 1.6366 | 0/3 |
| crowd2 | Combined（EXP53 复用） | 2.0671 | 2.2005 | 2.0583 | **2.1086** | 0.0797 | 3/3 |
| crowd2 | P11+DynKF | 2.5614 | 6.3292 | 6.5805 | **5.1570** | 2.2514 | 1/3 |
| crowd2 | P11+Reliability | 8.4006 | 5.1200 | 4.4646 | **5.9951** | 2.1089 | 1/3 |
| mv_no_box | P11（EXP53 复用） | 3.4180 | 4.0247 | 3.5150 | **3.6526** | 0.3259 | 3/3 |
| mv_no_box | Combined（EXP53 复用） | 2.5598 | 2.6025 | 2.7384 | **2.6336** | 0.0933 | 3/3 |
| mv_no_box | P11+DynKF | 2.6635 | 2.7142 | 2.7514 | **2.7097** | 0.0441 | 3/3 |
| mv_no_box | P11+Reliability | 3.7231 | 3.2304 | 3.4377 | **3.4637** | 0.2474 | 3/3 |

## 2. 判据（逐序列）

### 2.1 crowd2

地板 = `max(0.43, 0.06 × max(6.8897, 2.1086))` = **0.43 cm**（此时 P11 远大于 Combined，地板不起作用）。

| 臂 | mean | delta vs P11 | 地板 | 解读 |
|---|---:|---:|---:|---|
| P11+DynKF | 5.1570 | −1.7327 | 0.43 | 不充分：未到 Combined 的 2.11 |
| P11+Reliability | 5.9951 | −0.8946 | 0.43 | 不充分：未到 Combined 的 2.11 |

DynKF 和 Reliability 两个单变量臂**都不能恢复 Combined 的优势**；均值上 DynKF 略好于 P11（−25%），但逐 seed 变异极大（2.56/6.33/6.58，sd=2.25），说明 crowd2 上仍存在显著的 seed 双稳态或组件交互。

**crowd2 结论：无法单独归因。** DynKF 和 Reliability 都不是充分条件，Combined 在 crowd2 上的优势需要两个组件共同作用，或还依赖 `mask_insertion`。

### 2.2 mv_no_box

地板 = `max(0.43, 0.06 × max(3.6526, 2.6336))` = **0.43 cm**。

| 臂 | mean | delta vs Combined | 地板 | 解读 |
|---|---:|---:|---:|---|
| P11+DynKF | 2.7097 | +0.0761 | 0.43 | **P11+DynKF ≈ Combined**（差 0.08 cm，在地板内）|
| P11+Reliability | 3.4637 | +0.8301 | 0.43 | P11+Reliability 与 P11 不可区分（差 0.19 cm，在地板内），Reliability 对 mv_no_box 无超出地板的边际贡献 |

**mv_no_box 结论：DynamicKeyframe 是主要可解释成分。** P11+DynKF 3-seed mean=2.71 与 Combined 2.63 差 0.08 cm，远在 0.43 地板内；逐 seed 差 ≤0.11 cm（2.66/2.71/2.75 vs Combined 2.56–2.74，仅 seed2 超出 Combined 上界 0.01 cm），方向完全一致。P11+Reliability 臂的 3.46 与 P11 的 3.65 差 0.19 cm，同样在地板内——注意该臂 sd=0.25（约为 DynKF 臂的 5.6×），逐 seed 读数为 3.72/3.23/3.44，方向一致性弱于 DynKF 臂；在此离散度下只能说"无可测量的边际贡献"，不能说"贡献为零"。

## 3. 效率与结构差异

| 序列 | 臂 | KF 数(seed0) | reliability frames | keyframe_diag rows | completed |
|---|---|---:|---:|---:|---:|
| crowd2 | P11+DynKF | 178 | 0 | 518 | ✓ |
| crowd2 | P11+Reliability | 95 | 894 | 878 | ✓ |
| mv_no_box | P11+DynKF | 156 | 0 | 467 | ✓ |
| mv_no_box | P11+Reliability | 44 | 778 | 717 | ✓ |

DynKF 臂的 KF 数接近 Combined（crowd2: 178 vs 179, mv_no_box: 156 vs 156），且 `keyframe_diag` 记录了 `crisis` 触发，证明 DynamicKeyframe 的五帧间隔确实在运行。Reliability 臂的 KF 数接近 P11（无 DynKF，仍走稀疏策略），同时 Reliability frames 完整，flow 覆盖充足。

## 4. 结论的正确表述

### 4.1 当前可声明的

1. **mv_no_box**：DynamicKeyframe 是 Combined 优势的**充分且可解释的单一来源**。P11 开启 DynKF 后达到 Combined 水平（2.71 vs 2.63，差 0.08 cm 在 0.43 地板内），Reliability 在该序列上没有超出地板的边际贡献（3.46 vs P11 3.65，差 0.19 cm 亦在地板内，但 sd=0.25 方向一致性弱）。这与 P-B 2×2 的方向一致（P-B 的 DynKF 正向 +0.49 cm，本轮 0.08 cm 更精确地将下界拉到 Combined 水平）。

2. **crowd2**：Combined 的优势**不能归因于单一组件**。DynKF 和 Reliability 各自都不充分（5.16 vs 2.11, 6.00 vs 2.11），且逐 seed 变异极大（sd > 2 cm）。这说明 crowd2 上存在**组件交互或第三变量效应**（如 `mask_insertion`、DeferredCommit confirmation 的联合路径），需要更复杂的归因设计或直接保留 Combined bundle。

3. **`mask_insertion` 仍未被隔离**：本次只测 DynKF 和 Reliability，`mask_insertion` 作为第三变量未被单独翻转。若要完整闭合 EXP53 的三个开关，需要在 `mv_no_box` 上追加 `P11+mask_insertion`（6 run），但当前 DynKF 的结果已足够强，追加的优先级较低。

### 4.2 当前方法定位（更新）

> **Combined 保持 crowd2 类复杂多人场景的主力；P11+DynamicKeyframe 可覆盖 mv_no_box 等纯物/低遮挡场景的大部分增益；P11 裸配置作为最简化参考，不进入正式主表。**

### 4.3 论文中的表述建议

- `mv_no_box`：可以说 "DynamicKeyframe captures the Combined advantage on pure-object sequences (2.71 vs 2.63 cm, within the 0.43 cm floor)"。
- `crowd2`：可以说 "The combined kernel shows synergy on crowd-heavy sequences; neither component alone recovers the full gain"。
- 不可以说 "DynamicKeyframe is the sole source of Combined gain" 或 "ReliabilitySignal contributes nothing"（后者现数据为 3.46 vs 3.65，方向甚至略正，只是离散度大、未超地板）。

## 5. 后续方向

1. 若 `crowd2` 的组件交互需要更明确的论文叙事，可追加 `P11+DynKF+Reliability` 的双变量臂（与 Combined 只差 `mask_insertion`），判断是否两个组件加起来就能恢复 Combined。
2. 若 `mv_no_box` 的 DynKF 结果被认为足够，论文可以将 `DynamicKeyframe` 作为该 regime 的主要组件，将 `ReliabilitySignal` 定位为其他 regime 的辅助或 robustness guard。
3. 不再跑额外的全矩阵；当前 12-run 数据量足以支撑 regime split 的组件叙事。
