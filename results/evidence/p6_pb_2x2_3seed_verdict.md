# P-B 2×2 (mask × dynKF) 消融 — 3-seed 终判（3090, 2026-08-09）

> 装置 `tests/test_p6_pb_ablation_configs.py`（5 pass）。seed0 已在 P-B screening，
> 补 seeds 1/2 完成。数值 = `tracking_raw.csv ate_rmse_cm`（全轨迹,3090）。
> 这是"mask-free 时域一致性 bundle"头条的定位核心实验。

## 完整 2×2 表（cm）

| mask \\ dynKF | dynKF ON | dynKF OFF |
|---|---|---|
| **mask ON**  balloon | **3.06±0.14** | **3.03**（2.80/3.25/3.04） |
| **mask OFF** balloon | **12.11±1.90** | **13.48**（13.34/12.72/14.37） |
| **mask ON**  mv_no_box | **2.66±0.12** | **3.15**（3.38/3.03/3.05） |
| **mask OFF** mv_no_box | **3.09±0.37** | **3.90**（3.59/4.52/3.60） |

## 判决

**1. balloon（人+气球,混合 mover）—— mask 是绝对主导轴。**
- mask ON 两格（3.06 / 3.03）远优于 mask OFF 两格（12.11 / 13.48）。
- dynKF 轴效应≈0（3.06 vs 3.03）。⇒ **balloon 上 dense-keyframing 不是驱动,mask 是**。
- 因果：balloon 的动态 mask → 挡住人+气球进地图,RT/reliability 再处理残余;mask 一关,气球污染回 12cm。

**2. mv_no_box（纯物,背景干净）—— bundle 是内核,单一组件都不是。**
- 四格全 ≈3cm（2.66 / 3.15 / 3.09 / 3.90）。
- **mask 轴效应小**（2.66→3.15 = +0.5cm;3.09→3.90 = +0.8cm）；
- **dynKF 轴效应小**（2.66→3.09 = +0.4cm;3.15→3.90 = +0.75cm）。
- ⇒ **没有任何单一组件是 mv_no_box 的真正内核**。~3cm 来自 **bundle 的组合鲁棒时域采样**：
  RobustTracking(huber) + Reliability(时域减权) + dense-KF(覆盖),彼此冗余。拿走任何一个,
  bundle 仍 ~3cm;全拿走才回 vanilla 13.6cm。

**3. 与 P6 的交叉。** P6 显示"mask-free 仍强"(mv 3.09 vs vanilla 13.6);P-B 进一步显示
"mask-free 且 dynKF-free 也仍强"(mv 3.90)。⇒ **mv_no_box 的 ATE 内核 = RobustTracking + Reliability
这个鲁棒时域减权组合本身**,不依赖 mask 也不依赖 dynKF。

## 对头条的最终定位

**头条 = "mask-free 时域一致性 bundle 的动态 3DGS SLAM"**,但必须如实说清适用域:

- **诚实主张 A（mv_no_box / 纯物/低纹理）**：dense-KF + RT + Reliability 的 bundle 不依赖语义
  分割,把动态序列从 vanilla 13.6 压到 3.1-3.9cm;且**每个组件单独关掉都不崩**（组合才是内核）。
- **诚实主张 B（balloon / 混合 mover）**：mask 仍是主导（3cm vs 12cm）;bundle 在 mask 不存在时
  仍把 vanilla 43.9 压到 12cm（3.6×）,但没有 mask 那么强。
- **不可写**（防止审稿人反打）：不该说"dense-KF 是内核"(balloon 上 dynKF 无关)、
  不该说"mask 无用"(balloon 上 mask 是主导)、不该说"bundle 在任何序列都最优"(pt2 未测多seed)。

## 竞品差异化（这轮实验给的方法贡献）

竞品（RGD/DG/Gassidy/DAGS/BDGS）都依赖 explicit 动态检测（YOLO/mask/flow 分割）。
**没有任何竞品声称"鲁棒时域采样 + 稠密关键帧的 bundle,在无语义分割下把动态序列压到 3cm,
且逐组件关掉都不崩"**。这才是"我们自己的方法内核"——不是单一 magic component,而是一个
**可冗余、鲁棒的时域采样系统**。这是 framework-general（不依赖分割网络）+ dynamic-relevant。

## 落盘
- 完整 3-seed 数据: `results/runs/P6/P6-PB/`（已回拉）。
- 本文件 = P-B 3-seed 终判证据。
- 头条方向: `idea_exploration_maskfree_temporal.md` + 本文件。
