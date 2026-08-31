# TRC 时域一致性信号可分离性 de-risk（2060 离线，零训练）

> 2026-08-09 exp-v3-11。脚本 = `scripts/probe_flow_separability.py`。
> 目的：TRC（Temporal Residual Consensus）gate 是否 well-posed——即 mask-free 的
> 多帧 flow 异常一致性，能否把 dynamic 像素与 static 像素分开。

## 信号定义

逐像素 `anom = |frozen_obs_flow - static_ego_flow|`（可靠性信号的 core anomaly），
再对 trailing K 帧做 `kframe_consensus`（trajectory-aligned lower-median persistence，代码已在
`utils/reliability_signal.py:208`）。若无此机制已是一步到位，则 gate 不成立 → 收窄。

## 结果（balloon, GTMC-dynamic vs GTMC-static 像素）

| K 窗（一致性帧数） | flow-anomaly @dynamic | flow-anomaly @static | sep ratio |
|---|---|---|---|
| K=1（单帧，当前可靠性信号） | 5.59±4.01 | 3.29±1.85 | **1.70** |
| K=3 | 5.02 | 3.27 | 1.54 |
| K=5 | 3.98 | 3.33 | 1.20 |
| K=8 | 3.31 | 3.33 | **0.99（完全不可分）** |

## 判决

**⚠ K-window consensus 没有增强分离，反而衰减。** 这推翻了我"多帧一致性会sharpening TRC gate"的初判：
- K=1 单帧 anomaly 的 separation（1.70）已经超过可靠性信号实际用时的效果（那次的 15% 门槛未过，
  但那是 s→w 的 Cauchy 聚合问题，不是信号本身不可分——见 memory reliability-signal-selectivity）。
- 随 K 增大，dynamic 的 anomaly 被 lower-median 压到接近 static（dynamic 像素的异常不是 K 帧持续高，
  而是间歇 spike，median 把它抹掉）→ K 越大越不可分。

## 含义（诚实）

1. **多帧 median consensus 不是动态检测的增强器**——它把短暂/间歇的动态签名抹平了。
   "TRC 残差记忆门控"如果基于 trailing median persistence，在 balloon 上会越来越钝（K=8 完全不可分）。
2. **单帧 anomaly（K=1）反而是可分离的信号**（ratio 1.70，但这是 balloon 的"人+气球"二合一场景）。
   可靠性信号没晋级不是因为信号不分,而是 s→w 的 Cauchy 聚合（static 多数像素主导 + geo floor 稀释）。
3. **若要把时域一致性用起来**，不是 median over time per-pixel，而是**沿光流 track the same physical point** 
   （当前 probe 是 fixed-pixel median，没 warp）——真正 trajectory-aligned 的持久性可能才分离。这是下一步可测的。
   （kframe_consensus 的 docstring 明确要求"TRAJECTORY-ALIGNED anomaly stack"，我这里是 no-warp 的 proxy，
   所以这个负数结论是 proxy-level，不完全封死真 trajectory-aligned）。

## 对头条的影响

- **不能把 TRC 当作"mask-free 动态检测"的直接增强**（审稿人会找到这个衰减）。
- TRC 的可行用法改成**单帧 anomaly 的即时 gate**（不用 trailing median），且聚合盯 s→w 的选择性修复
  （fixed/percentile tau + raise geo floor——这正是 memory reliability-signal-selectivity 里已记的修复方向）。
- 头条仍 = mask-free 时域一致性 bundle（dense-KF+RT+Reliability 的组合鲁棒采样），但方法叙述绝不写
  "多帧一致性动态检测会增强"，而写"单帧残差 + 鲁棒聚合的 bundle"。
- 这个负结果本身可作为 paper 的 honest ablation（"we tested temporal-median consensus; it DEGRADES
  separation K=1→8 ratio 1.70→0.99, so we use instantaneous residual + robust track not temporal median"）——
  审稿人加分项（自己报负结果、不藏）。

## 下一步（若要继续）
- 真正的 trajectory-aligned consensus（沿 RAFT flow backward-warp 累积同一物理点）再用一次,
  若仍不可分则彻底关 TRC 增强路，收在 bundle。
