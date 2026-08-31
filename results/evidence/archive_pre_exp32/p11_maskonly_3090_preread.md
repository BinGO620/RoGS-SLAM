# P11 mask-only 3090 跨机复现 — 12-run 完整预读（exp28, 2026-08-19 04:42 收口）

> **性质：预读，非正式判决。** 正式三路判决由 2060 预注册批（判决机）收口后
> `scripts/judge_p11_maskonly.py` 出（判据冻结见该脚本头）。本文件只回答
> "3090 复现臂上判据会怎么落"。run 根 = 远程 `results/runs/P11/P11-MASKONLY-3090`，
> 12/12 done missing=0，全部满帧（f3_st_hf 1078 / balloon 439 / f2_xyz 3397 / mv_no_box 778）。

臂 = P11 sparse-KF mask-only：vanilla KF + mask_mapping + huber；
DynamicKeyframe/ReliabilitySignal/mask_insertion 全 OFF。
与 WP-M maskonly 旧臂的 diff 恰为 {RobustTracking ON, mask_insertion OFF}。

## 逐 run ATE(cm)

| 序列 | seed0 | seed1 | seed2 | mean±sd | WP-M maskonly | combined | vanilla |
|---|---:|---:|---:|---:|---:|---:|---:|
| f3_st_hf | 3.46 | 3.94 | 4.71 | **4.04±0.63** | 5.46±1.61 | 29.43±8.00 | exp26 4/5 崩 |
| balloon | 3.71 | 2.86 | 2.98 | **3.18±0.46** | 2.95±0.20 | 3.06±0.14 | 38.35±2.66 |
| f2_xyz | 1.67 | 1.62 | 1.70 | **1.66±0.04** | 1.71±0.14 | 1.93±0.03 | — |
| mv_no_box | 3.52 | 3.68 | 3.71 | **3.64±0.10** | 3.87±0.47 | 2.66±0.12 | 6.36±1.85 |

## 效率（mean）

| 序列 | online FPS | num_gaussians | KF 数 (seed0/1/2) |
|---|---:|---:|---|
| f3_st_hf | 0.351 | 83,304 | 58 / 61 / 62 |
| balloon | 0.365 | 20,803 | 20 / 21 / 21 |
| f2_xyz | 0.639 | 32,436 | 97 / 97 / 95 |
| mv_no_box | 0.416 | 31,227 | 35 / 33 / 34 |

### KF 稀疏化对照（f3_st_hf, 1078 帧）

| 臂 | KF 数 | 说明 |
|---|---:|---|
| P10 async10（DynamicKeyframe ON, gap_cap=5） | 216 | dense KF，exp27 "饿死后端" 的那一档 |
| P10 async50（同 dense KF 策略，mapping 预算 5×） | 107 | 预算变大→地图更好→需要的 KF 变少 |
| **P11 sparse mask-only** | **58-62** | vanilla KF 策略 |

> **诚实更正**：交接书 exp27 预期 "KF 应回到 ~20"。实测只有 balloon 是 ~20；
> f3_st_hf 是 ~60（对 dense 216 = **3.6× 稀疏**），f2_xyz ~96（3397 帧长序列）。
> "~20" 是序列相关的，不是全局值。稀疏化方向成立，倍数需按序列报。
> KF 数取自 `plot/trj_final.json` 的 `trj_id` 长度。


## 判据试落（3090 数据）

- **稳定性 (f3_st_hf ≤10cm 每 seed)**: 3/3 活 (3.46/3.94/4.71)，且优于 WP-M 旧臂 5.46，
  无 frame-371 崩溃（1078 帧满帧）→ **PASS**
- **动态增益 (balloon mean ≤ 19.2)**: 3.18，对 vanilla 38.35 = **12.1×** → **PASS**
- 泛化参考: mv_no_box 3.64 vs vanilla 6.36 (1.7×)；f2_xyz 1.66 < 5 健康线。

**→ 3090 上路径 A 成立**：mask-only 既稳又保留全部动态增益；dense KF + reliability
在此判据下 = 过度工程。RobustTracking-ON + mask_insertion-OFF 两处规格差异无副作用
（f3_st_hf 4.04 vs WP-M 5.46 甚至略优，sd 也更小）。

## 保留意见（为什么还不是正式判决）

1. **判决权在 2060**：exp27 证明硬件依赖真实存在（async50: 3090 5/5 稳 vs 2060 2/3）。
   f3_st_hf 稳定性必须在 2060 上 3/3 活才算数。2060 已有早期信号：balloon_seed0 2.72
   （14×）、f2_xyz_seed0 1.64，均健康；f3_st_hf 3 seed 未出。
2. seed 数 = 3，f3_st_hf 崩溃历来 seed 敏感（exp26 vanilla 4/5 崩）。
3. mv_no_box 相对 combined (2.66) 略差 (3.64)，reliability/dense KF 在部分动态 regime
   仍有增量价值——路径 A 成立不等于 reliability 无用，与 codex "可选增强" 定位一致。

## 2060 侧现状（判决机，2026-08-19 12:28 起真正开跑）

**事故记录**：2060 上 P11 批在 01:23-12:28 之间一个 run 都没起——占槽的 P10 async150_seed2
在 01:37 OOM 后进程卡在 `futex_wait` 永不退出（前端抛异常、backend join 死锁），
白占 11 小时。根因是我 01:23-02:14 窗口把并发开到 2（Mask R-CNN 每 run ~2.9GB，6GB 卡不够），
既打死了自己的 f3_st_hf_seed0，也打死了这个 P10 run 并留下僵尸。已 kill -9 清理，批改串行
（MAX_PARALLEL=1, commit d15bf80f）。**通用教训**：OOM 不一定让 MonoGS 进程退出，
串行闸只看进程数会被僵尸永久堵死；派发后必须验证"真的起了 run"，不能只看 launcher 活着。

**已有 2060 数据**（并发窗口里幸存的两个 run，产物完好，已被 SKIP 不重跑）：

| run | ATE(cm) | 对照 |
|---|---:|---|
| balloon seed0 | **2.72** | vs vanilla 38.35 = **14.1×**；3090 同 run 3.71 |
| f2_xyz seed0 | **1.64** | 健康线 <5；3090 同 run 1.67（跨机一致） |

剩 10 run 串行跑（f3_st_hf ×3 是判据核心），预计 ~15-18h。

## 若 2060 复核通过，下一步（路径 A 剧本）

1. 写 3DGS-specific evaluation：为什么 3DGS 比 feature SLAM 更需要 mask-guided
   （candidate: densification 把瞬态观测固化为 Gaussian，feature SLAM 只是匹配失败）。
2. 可选增强验证：ego-protected reliability 在动态序列上的额外增益。
3. Option B (queue-aware budget) 工程修复照做（codex 要求，防 artifact 污染对比）。
