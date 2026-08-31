# 离线长基线 ORB-PnP · 特征锚判别 — 预优化边精度（exp-v3-15, codex 019fefb9 §3）

> 2026-08-11。codex 建议的唯一低成本判别 = 用现成 static mask + RGB + 源帧深度做长基线 ORB-PnP，
> 加进 pose graph 看能否把 pt1 ATE 拉向基线。**先测预优化 PnP 边相对 GT 的精度**（这是锚可行的必要前提）。

## 装置
- 数据 = Bonn pt1（person_tracking），580 帧。节点 = 每 10 帧。
- ORB（1500 features）+ BF lowe(0.75) + 源帧深度反投影静态点（GTMC mask==0）+ `solvePnPRansac`+RefineLM。
- PnP 边 = 相对位姿 `inv(P_top)@P_bottom`，对 GT 算相对旋转误差（无预对齐，共享 gauge）。
- 复用现成 `full_frame_pose.py` 的 ORB/PnP 逻辑（跳过 map_precheck/rotation/translation gate，按 codex）。

## 结果（seed0, 离线, GPU 无关）
| offset | 接受边数 | PnP-vs-GT 相对旋转误差中位 | PnP-vs-GT 平移误差中位 |
|---|---|---|---|
| 15 | 48/55 | **12.8°** | 0.101 m |
| 30 | 42/54 | **17.4°** | 0.134 m |
| 60 | 21/51 | **39.0°** | 0.134 m |

## 判定
- **codex 自己定的锚可行门槛**（长边在 60/120 帧尺度须 rot_error median <3°、p90 <8°，见其原始 §3）：
  我们的 PnP 长边中位 12.8–39.0°、p90 29.6°+ ⇒ **比门槛差 4–13×**。
- ⇒ **ORB-PnP 长边在 pt1 这一低纹理/弱视差 person 场景下，精度远不足以当锚**。即便喂进 pose graph，
  这些含 12–39° 相对旋转噪声的边不但不能把轨迹拉向 GT，反而会给 LM 注入噪声（robust 损失下多数被
  拒绝或抹掉）。
- 这不是"缺独立观测源"（观测源 ORB+PnP 存在），而是**该观测在 pt1 的精度不达标**。
- 完整 pose-graph LM 结果跑完后补于 `summary_seed{0,1,2}.json`（预期 ≥ 或 ≈ 基线 9.16，若更差则
  进一步佐证"锚边噪声>收益"）。

## 完整 pose-graph LM 结果（seed0）
- 预优化 PnP 边相对 GT 旋转误差中位 **12.4°/17.1°/37.1°**（offset 15/30/60，RMSE 均 ~1.5px 但旋转噪声大）。
- **全边优化后 ATE = 9.42cm（≥ 基线 9.16，不改善，略劣）**；单 offset：15→9.16、30→9.28、60→9.00。
- offset60 单边略降到 9.00（在噪声带内，0.16cm），全边合并反而 9.42 ⇒ 锚边噪声抵消了微弱的单基线收益。
- **判语**：ORB-PnP 长边在 rotation 通道精度太差（12–39° vs codex 门槛 <3°），不能把轨迹拉向 GT。
  seeds 1/2 跑完后补，预期同量级（±0.2cm 不改善）。

## 3/3 seed 定稿（codex 判据执行）
| seed | baseline | 全边优化后 | offset60 单边 | 判词 |
|---|---|---|---|---|
| 0 | 9.16cm | 9.42cm | 9.00cm | 无益（略劣） |
| 1 | 9.31cm | 9.69cm | 9.19cm | 无益 |
| 2 | 8.99cm | 9.31cm | 8.84cm | 无益 |

- PnP 长边相对 GT 旋转误差中位 **12.4° / 17.1° / 37.1°**，p90 ≥29.6° —— 全 fail codex 阈值（median<3°, p90<8°）。
- **3/3 seed：pose-graph 全边合并后 ATE 均 ≥ baseline（无益）；无一降到 ≤7.2cm。** offset60 单边有 ~0.15cm
  噪声带内下降，但不足以构成方向的成立。
- **⇒ 特征锚方向按 codex 判据判死**（长边旋转误差与原 tracker 同量级或更差，且 ATE 不降）。
  long-horizon 位姿正则三候选（①平滑 ②航位推算 ③特征锚）全部离线/离线实验判死，探索彻底闭环。
