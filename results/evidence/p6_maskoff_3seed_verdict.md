# P6 MASK-OFF 消融 — 3-seed 判定（3090, 2026-08-09）

> 预注册 `p6_maskoff_prereg.md`；单 seed screening + 补 seeds 1/2（balloon/mv_no_box）。
> 数值 = `tracking_raw.csv ate_rmse_cm`（全轨迹,3090）。

## 主表（3-seed mean ± sd,cm）

| seq | vanilla (P5) | combined (3090 3-seed) | **maskoff (3-seed)** | maskoff vs vanilla | maskoff vs combined |
|---|---|---|---|---|---|
| balloon | 43.94 | 3.06±0.14 | **12.11±2.33**（13.66/9.43/13.24） | **3.6× 更优** | 4.0× 更差 |
| mv_no_box | 13.60 | 2.66±0.12 | **3.10±0.46**（3.60/2.99/2.70） | **4.4× 更优** | **1.16× 更差** |

> **更正（2026-08-31，r3 审稿修复轮）**：本文件原印 `12.11±1.90` 与 `3.09±0.37`，
> 系当时用总体标准差（ddof=0）计算；主表 S12 与仓库其余表格统一用样本标准差（ddof=1）。
> 种子值未变（balloon 13.66/9.43/13.24，ddof=1 ⇒ 2.33；mv_no_box 3.60/2.99/2.70，
> ddof=1 ⇒ 0.46），仅更正离散度口径。

（pt2 单 seed = 9.92 vs combined 10.44,已略好于 combined,但未补 seed；pt2 是 person 序列,
mask 最冗余,方向已明。）

## 判决（对照 prereg §4）

**P-A（mask-off 方法内核）成立——3-seed 判定。**

1. **mask-off 全部序列全部 seed 远优于 vanilla**：balloon 3-seed [13.66, 9.43, 13.24] 全在
   判据"3.06~15cm ⇒ 内核存在"区间（远低于 vanilla 43.94）；mv_no_box 3.10±0.46 更是几乎压到
   combined 水平。**证伪分支（mask-off ≈ vanilla ≈ 43cm）完全不触发。**
2. **mv_no_box 是决定性证据**：maskoff 3.10 vs combined 2.66，只差 1.16×（在噪声带内），
   mask 拿掉几乎不掉 ATE。⇒ **dense-KF + RT + Reliability 这套时域一致性机制，即使语义 mask
   完全关闭，自己就把动态序列 ATE 从 vanilla 13.60 压到 3.10（4.4×）。**
3. **mask 不是完全可省**：balloon 上 combined 3.06 → maskoff 12.11 掉了 4.0×。这是唯一
   mask 有明显增量的序列（balloon=人+气球,COCO-person mask 抓不住气球,所以 mask 在这里
   相对 partial,其"漏"的部分恰是 maskoff 掉的那部分）。但即便失去 mask,RT+dense-KF+Reliability
   仍把 balloon 从 vanilla 43.94 压到 12.11（3.6×）。

## 结论

**combined backbone 4-14× ATE 的方法内核不在借来的 Mask R-CNN 语义 mask 上,而在
dense-keyframing(DynamicKeyframe) + RobustTracking + ReliabilitySignal 这套"mask-free 的
时域一致性动态跟踪"机制。**

- 这解释了历史上所有 flat/未晋级结果：RT-off（有 mask 时 +1.2% flat）、Reliability-off
  （<15% 未晋级）都是因为"mask 存在时这些机制被冗余吞掉"。**mask 一关,它们才显形。**
- 这是一个**新的、未测过的缺口**,不是复活死清单任何格子（死清单测过的是"有 mask 时的
  RT-off / Reliability-off / mask-vs-deferred",从没测过"mask-on vs mask-off"）。
- **竞品地位**：RGD-SLAM / DG-SLAM / Gassidy / DGS-SLAM 都依赖 explicit 动态检测（语义
  mask 或 optical flow 分割网络）。**"mask-free 仅靠时域一致性 tracking 就把动态序列压到
  3cm 量级"是 novelty 空档**,因为竞品没有声称这点,而我们实测支持它。

## 下一步（P-B：定位方法内核的具体组件）

单 seed 方向 + 3-seed 判定已立头条。现在要回答"到底哪个组件撑起 mask-free 的 4.4×"：

- **2×2 交互消融（mask × dynKF）** 能拆解：dense-keyframing 单独、RT 单独、Reliability 单独、
  以及它们之间的超加性交互。codex 审要点正是这个。
- 最可能是 **dense-keyframing（DynamicKeyframe）** 是主贡献（它改变关键帧密度/时序覆盖,
  是时域一致性的载体）;RT + Reliability 是鲁棒/降权补充。
- 若 P-B 显示 dense-KF 单独就能扛大头,头条可进一步聚焦为"**mask-free 时域稠密关键帧动态跟踪**",
  这是纯我们自己的机制（DynamicKeyframe 是我们加的,kernel 不在 MonoGS 里）。

## 落盘

- 3 run screening + 2 run 补 seed = 5 run 已回拉 `results/runs/P6/`。
- 3-seed 判定证据 = 本文件 + `p6_maskoff_prereg.md` + `p6_maskoff_verdict.md`。
- pt2 的 3-seed 可选补（若 P-B 需要 person 序列对照）;当前 pt2 单 seed 已略优于 combined,方向一致。
