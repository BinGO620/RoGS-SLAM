# exp26 w≡1 因果判据 — 预注册（跑前冻结）

> **冻结于 2026-08-17，发 run 之前提交。** 结果回来只填实测，不改判据。

## 要判什么

`results/evidence/exp26_static_collapse_rootcause.md` 里，**已证**的是：

- (a) `cauchy_tracking_weight` 的 w 对 s 的绝对水平**严格不变**（数值：s∈[0.97,1] 与
  s∈[0.10,1] 的 mean_w 同为 0.7438、w<0.5 比例同为 0.1303）
- (b) 8 条序列（4 静 4 动）实测 mean_w 全在 0.57-0.66，静态动态无差别
- (c) f3_st_hf：vanilla MonoGS 2.80cm vs ours 35.59cm
- (d) 崩溃是 frame 371 的**离散**事件；该处 GT 帧间平移进全序列前 5%，
  `flow_valid_frac` 掉 20%，且此量在四个 run 里逐帧完全相同（序列属性）

**未证的是那条因果链**：「静态帧上被丢掉的 ~38% 光度信号，导致了 371 处的崩溃」。
本 run 就判这一条。

## 装置

`ReliabilitySignal.tracking_downweight_off: true`（default-off），只把 tracking loss 里的
`reliability_soft` 置零 ⇒ `static_conf ≡ 1`。信号照常算、照常落盘、照常喂 map 路径；
损失仍走同一条 soft 分支，RobustTracking(huber) 保持开。
**与对照臂唯一差别 = 权重值本身。**

## 对照

同机（jiangwenheng 3090）、同 async 模式、同 config 家族（`method_combined_maskoff_prune`）：

| FULLKERN mask-free f3_st_hf | seed0 **36.09** / seed1 **35.16** / seed2 **35.52** |
|---|---|

n=3 稳定崩，故 **1 个 w≡1 run 即足以判别**——不需要 seed 扫。

## 冻结判据

| 结果 | 判决 | 行动 |
|---|---|---|
| **ATE < 5cm 且 frame 371 处 plot/stats 无翻倍** | **下权重即病因，因果坐实** | 修 tau（帧自适应 → 绝对），走 no-harm 路线 |
| **ATE ≥ 20cm 且仍在 371 翻倍** | 下权重不是（唯一）病因 | 回定位，不改 tau；查 map 路径 / KF 选择 |
| ATE < 5cm **但**在 371 仍翻倍后自愈 | 部分成立 | 记为部分，补 2 seed |
| 5–20cm | INDETERMINATE | 补 2 seed 再判 |

## 自证要求（跑完必查，不合格则本 run 作废）

1. `frames.csv` 必须有 `tracking_downweight_off` 列且全 = 1
2. 同一 `frames.csv` 的 `mean_w` 仍应在 0.57-0.66（信号照常计算，只是没被施加）
   —— 若 mean_w 变成 1.0，说明改错了地方（把信号本身关了）
3. `plot/stats_*.json` 覆盖到 frame 371 附近

## 实测（2026-08-18 回填，判据未改）

| 项 | 值 |
|---|---|
| ATE (cm) | **35.99** |
| frame 346 → 371 | **1.34 → 3.02**（翻倍） |
| 之后 | 396: 10.19 → 421: 18.71 → 471: 27.02 |
| 终 ATE | 35.99 |
| `tracking_downweight_off` 全 1？ | ✅ 1077/1077 帧 = 1 |
| `mean_w`（应仍 ~0.6） | ✅ **0.6278**（信号照常算，只是没被施加） |
| run | `results/runs/P8/P8-EXP26-W1/f3_st_hf_w1_seed0/.../2026-08-18-00-24-40` |

**判决 = 第二行分支：下权重不是（唯一）病因。**

对照（同机同 async 同 config 家族）：control 36.09 / 35.16 / 35.52 → w≡1 **35.99**。
**把可靠性下权重完全去掉，f3_st_hf 照样在同一帧 371 崩到同一量级。**

⇒ `exp26_static_collapse_rootcause.md` §5 里标注为「推断」的那条因果链
（"静态帧上被丢掉的 ~38% 光度信号导致 371 处崩溃"）**被本 run 证伪**。

**仍然成立**（本 run 不触碰）：w 对 s 绝对水平严格不变（数值证）、
8 序列 mean_w 恒在 0.57-0.66、静态也丢 ~38% 信号。
这些是真实测量，只是**不是 f3_st_hf 崩溃的原因**。tau 该不该改是独立问题，
但**不能再用"它导致静态崩溃"来论证**。

**行动**：按判据 = 回定位，不改 tau；查 map 路径 / KF 选择。
