# P2-SF 跑后补丁：vac_psnr/vac_depth 绝对值的 regime 分裂（两审未看到）

这是在双审已收回后做数据完整性核对时发现的。两审的 packet 只给了 Δ（两臂差），
没给绝对值跨 variant 对比。这个发现可能比 KF 混淆更根本，请复审。

## 数据

同一个序列、同一个 lifecycle、只换位姿质量（C=prune 11cm 自跟踪轨迹 / B=GT 0cm），
vacated 区的保真绝对值：

| cell | vac_psnr | vac_depth | static_psnr(non-vac) | G_prune |
|---|---|---|---|---|
| C-pt1 prune | 24.41 dB | 21.44 cm | 24.0 | 56915 |
| C-pt1 deferred | 24.33 | 23.87 | 24.0 | 20592 |
| C-balloon2 prune | 21.47 | 22.55 | 21.3 | 24381 |
| C-balloon2 deferred | 21.29 | 22.73 | 21.1 | 13833 |
| B-pt1 prune | 15.02 | 37.97 | 15.3 | 13258 |
| B-pt1 deferred | 15.15 | 36.66 | 15.4 | 9766 |
| B-balloon2 prune | 15.49 | 35.17 | 15.7 | 26427 |
| B-balloon2 deferred | 15.24 | 35.23 | 15.5 | 7440 |

## 关键结构

1. **vac_psnr 绝对值跨 variant 差 ~9 dB**（C-pt1 24.4 vs B-pt1 15.0；C-balloon2 21.4 vs B-balloon2 15.3）。
   同序列同 lifecycle 只换位姿质量，保真绝对值跳一个数量级档。
2. **R2-P03 继承边界来源的 regime = 14.07–14.95 dB**（SWEEP/DECOMP balloon frozen rtoff）。
   这与 **B 臂完全一致**（15.0–15.5），与 **C 臂完全错配**（21–24）。
3. **保真 sign 在 vacated/non-vacated/C/B 四象限里乱跳**：
   - C-pt1 vacated: deferred 更差(+2.423 depth)；non-vacated static_psnr: deferred 更好(24.31 vs 23.72)
   - B-pt1 vacated: deferred 更好(−1.317 depth)；non-vacated: deferred 更好
   - B-balloon2 vacated psnr: prune 更好(+0.252)
   强烈暗示保真差是 regime-driven 噪声，不是稳定的 lifecycle 信号。

## 待裁决问题

1. **继承的 0.28dB / 1.56cm 边界源自 14.5dB regime。C 臂在 24dB regime，其 vac_psnr own_sd
   几乎肯定不是 0.28dB。C-pt1 的 depth breach（+2.423 破 1.56）是否还能用继承边界判？
   是假 breach、还是被低估？**

2. **B 臂恰好落在继承边界的源 regime（15dB≈14.5dB），C 臂不落。这会不会让 B 反而是
   "边界适用"的那个、C 反而是"边界错配"的那个——与预注册"C 主 B 副"的裁决正好相反？**

3. **9dB 的 regime 跳变是否是 codex Q4 / hermes Q4 "B/C 测不同东西"的更强证据（比 G 的
   4.3× 跳变更强）？它是否进一步坐实"停手写 limitation、不上 full"？**

4. **vacated vs non-vacated 的 sign 翻转是否意味着 vacated guardrail 本身在 frozen-pose
   下已经不是 arm-discriminating 量（codex 原判 vacated 是唯一 calibrated-usable contrast）？**

背景不变：单 seed screening、§4.4 上限只能 weaken/leave-unchanged H-D、ATE 是 canary 非证据。
