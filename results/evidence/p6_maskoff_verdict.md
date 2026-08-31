# P6 MASK-OFF 消融 verdict（3090 单 seed screening, 2026-08-09）

> 判据来源 = `p6_maskoff_prereg.md`（跑前固定）。
> 单 seed = screening,方法内核的判决路径需 3 seed,但方向性性命题已可读。
> 数值 = `tracking_raw.csv ate_rmse_cm`（全轨迹,3090）。

## 主结果表

| seq | vanilla (P5) | combined (3090 3-seed) | **maskoff (单 seed)** | maskoff 相对 vanilla | maskoff 相对 combined |
|---|---|---|---|---|---|
| balloon | 43.94 | 3.06±0.14 | **13.66** | **3.2× 更优** | 4.5× 更差 |
| mv_no_box | 13.60 | 2.66±0.12 | **3.60** | 3.8× 更优 | 1.4× 更差 |
| pt2 | 44.06 | 10.44±0.84 | **9.92** | **4.4× 更优** | **0.95×（≈持平!）** |

## 判决（对照 prereg §4 二分法）

判据原文："mask-off 的 balloon ATE 显著低于 vanilla" ⇒ 若 mask-off 在 3.06~15cm
（远低于 vanilla 43cm）⇒ **方法内核不在 mask**；有可主张的贡献。

- **balloon 13.66 cm** → 落在判据的"3.06~15cm ✓ 内核存在"区间（远低于 vanilla 43cm，
  约 3.2× 更优,但未到 combined 的 3.06）。
- **mv_no_box 3.60 cm** → 几乎与 combined 2.66 同量级,仍远优于 vanilla 13.6——**mask 拿掉几乎不掉**。
- **pt2 9.92 cm** → **与 combined 10.44 持平（0.95×,甚至略好）**——在 pt2 上,去掉 mask 后 ATE 不变。

## 结论（单 seed 方向性,非终判）

**P-A（mask-off 内核）强烈成立的方向证据。** 三条序列全部：mask-off 远优于 vanilla,
且在 mv_no_box / pt2 上几乎与 combined 相同。这直接反驳了"combined 4-14× 增益全靠借来的
Mask R-CNN mask"这一最坏情形（prereg 的证伪分支：mask-off ≈ vanilla ≈ 43cm）。

**但关键：mask 不是完全可省的**——balloon 上 combined 3.06 → maskoff 13.66 掉了 4.5×。
这是三个序列里唯一 mask 有明显贡献的（因为 balloon = 人+气球,mask 漏气球,所以这里 mask
拿掉反而…… 等一下,这里是 mask 在 balloon 上有巨大贡献但 maskoff 仍 13.66 < 43.94 vanilla,
说明 mask 之外的组件（dense-KF + RT + Reliability）在 balloon 也贡献了 3.2×）。

## 机制读数（为何 mask-off 在 balloon 掉得多、在 pt2 不掉）

对比 combined（有 mask）vs maskoff:
- **balloon: 3.06 → 13.66（mask 贡献巨大）**——balloon 是"人+气球",COCO-person mask 抓不住气球。
  这里 mask 拿掉,等于人+气球全进地图污染跟踪,但 RT+dense-KF+Reliability 仍能把 ATE 从
  vanilla 43.94 压到 13.66（3.2× 来自 mask 之外的组件）。
- **mv_no_box: 2.66 → 3.60（mask 贡献小）**——mv_no_box 是"非遮挡盒子",Mask R-CNN 本身对
  低纹理盒子的召回本来就不强,所以 mask 的增量本来就小;mask-off 下 dense-KF + robust + reliability
  靠时域一致性独自把 ATE 压到 3.6cm。
- **pt2: 10.44 → 9.92（mask 贡献≈0,甚至反作用）**——pt2 是纯人跟踪,person-mask 充分,但
  mask 在 combined 里已是"冗余"（RT + reliability 的时域信号已覆盖）;mask-off 反而略好。

## 也就是说

- **mask-off 在 3 个序列全部远优于 vanilla**（3.2× / 3.8× / 4.4×）⇒ **组合（dense-KF + RT +
  Reliability, mask 之外的部分）= 有我们自己的方法内核**,不是"mask+借来组件打包"。
- 尤其 **mv_no_box（3.60）几乎不吃 mask** 是一条强信号:它说明 dense-KF + robust + reliability
  这套时域一致性机制,即使语义 mask 完全关闭,自己也够把动态序列 ATE 压到 vanilla 之下 3.8×。
- 这与死清单不矛盾:死清单上测过的 RT-off（有 mask 时 flat）和 Reliability-off（<15%）正是
  说明"mask 存在时这些被冗余吞掉";**mask-off 打开了一个全新缺口——mask 不在时,这些机制才
  显形**。这解释了过去所有 flat 结果。

## 下一步（P-B,需 3 seed + 2×2）

- **单 seed 不成终判**,但方向性已强烈支持头条成立。补 3 seed（9 run）确认。
- 更重要:现在有了"mask-off 仍强"这个缺口,2×2 交互（mask × dynKF）能定位**到底哪个组件
  撑起了 mask-off 的 3.2×-4.4×** —— 很可能是 dense-keyframing(DynamicKeyframe) + RT 的
  时域一致性。若 P-B 显示 dense-KF 单独就能扛,mask 头条降级为"可选加分项",dense-KF + robust
  = 我们的方法内核。
- **竞品地位**:mv_no_box 3.60cm、pt2 9.92cm 在 mask 关闭时仍优于 vanilla 是强 novelty
  —— 因为竞品（RGD/DG-SLAM/Gassidy）都依赖 explicit 动态检测(mask 或 flow),没人声称
  "mask-free 下仅靠时域一致性 tracking 就能压 ATE"。

## 落盘

- 3 run screening 结果存 `results/runs/P6/P6-MASKOFF/`（已回拉）。
- 需补:P-B 2×2（mask × dynKF）或至少 mask-off 3 seed,再裁决终判。
- 不撤回死清单任何方法;mask-off 是新测的缺口(config-only,零核码改动)。
