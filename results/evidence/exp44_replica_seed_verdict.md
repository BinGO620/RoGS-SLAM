# exp44 Replica 种子扩展结果 —— 完成（2026-08-24，RTX 3090）

## 装置

- 12 run：office0 + room0 × vanilla + combined × seed1/2（seed0 已有）。
- 单进程（`_sp`）+ `use_gui=False`；full-eval（含 color refinement）。
- 远程 `EXP44_replica_full/datasets_replica/`；本地只回拉 `tracking_raw.csv` + `psnr/after_opt/`（本轮判决不依赖 plot/PLY）。
- 预注册：`exp44_replica_prereg.md`（commit `102f6ddd`，先于任何 run）。

## 结果总表（含 seed0 合并）

### ATE（cm）

| 臂 | office0 s0 | office0 s1 | office0 s2 | **office0 mean** | room0 s0 | room0 s1 | room0 s2 | **room0 mean** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| vanilla | 0.365 / 0.382† | 0.368 | 0.353 | **0.367±0.012** | 0.263 / 0.499† | 0.485 | 0.231 | **0.369±0.142** |
| combined | 0.917 | 9.097 | 1.447 | **3.820±4.58** | 0.328 | 1.516 | 0.318 | **0.721±0.689** |
| published Ours(sp) | 0.36 | — | — | 0.36 | 0.33 | — | — | 0.33 |

> † vanilla seed0 各有两次 run（首轮锚点 + 种子扩展批次重跑），office0 两次一致（0.365/0.382），
> room0 两次分裂（0.263/0.499）—— 见下方双峰判读。

### 渲染（after_opt，3-seed 均值）

| 臂 | 序列 | PSNR↑ | SSIM↑ | LPIPS↓ | DepthL1(cm)↓ |
|---|---|---:|---:|---:|---:|
| vanilla | office0 | **43.0** | **0.983** | **0.043** | **4.4** |
| combined | office0 | 37.8 | 0.957 | 0.128 | 9.5 |
| vanilla | room0 | 35.5 | 0.956 | 0.078 | 5.7 |
| combined | room0 | 35.0 | 0.949 | 0.098 | 6.3 |

## 判读

### 1. vanilla office0 = 高度可复现

mean 0.367 ± 0.012（CV 3.4%），published 0.36（+2%），四 run 全在 [0.353, 0.382]。
**结论不变**：office0 可作为 Replica 可比性锚点。

### 2. vanilla room0 = 双峰（核心新发现）

四次 run 落入两个不重叠的 basin：
- **低支**：s0-run1 0.263、s2 0.231（均值 0.247，与 published 0.33 可比甚至更优）
- **高支**：s0-run2 0.499、s1 0.485（均值 0.492，偏离 published +49%）

两支间无中间值，KF-ATE 同样分裂（0.32/0.33 vs 0.51/0.53）。
⇒ room0 的 ±51% 偏离**不是连续漂移，是双稳态**——与 exp26（balloon 同 config 同 seed 2.99 vs 33.70）同源，是 MonoGS async mapping 的 run-to-run 非确定性在 Replica 上的实例。
**对论文的影响**：room0 绝对值不可信，但**内部对比（vanilla vs combined）仍合法**（同条件抽到同一 basin 的概率在 3 seed 下可评估）。

### 3. combined office0 = 双稳态 + 更差

s1 落崩溃支（9.10 cm），s0/s2 在正常支（0.92/1.45）。
CV 120%；均值 3.82 远差于 vanilla 0.367。
**三场景一致**：combined 在静态 Replica 上**不帮忙且引入崩溃风险**——与 FULLKERN "静态 6/6 变差" + P6 mask-off "静态不帮忙" 交叉验证通过。

### 4. combined room0 = 双稳态但均值方向偶然有利

s1 落崩溃支（1.52），s0/s2 在正常支（0.33/0.32）。
均值 0.72 vs vanilla 0.369 = combined 更差，但 s0/s2 单看 combined 反而略优。
**与 office0 矛盾**，不可合并报单一方向——正确表述是"两场景 combined 均双稳态，office0 一致更差，room0 方向不一致"。

## 论文 limitation 写法（预注册 §5 已承诺）

> On static Replica scenes, our combined backbone (with semantic mask) is **worse and less stable**
> than vanilla: office0 ATE 3.82±4.58 vs 0.37±0.01 (10× worse mean, CV 120% vs 3%);
> room0 also exhibits bistability (s1 collapses to 1.52 cm vs 0.32 cm for s0/s2).
> Our method is designed for dynamic scenes; on purely static environments the additional
> modules (RobustTracking, ReliabilitySignal, DynamicKeyframe) introduce instability
> without benefit.

## 新增判据（registry 待补）

| # | 判据 | 来源 |
|---|---|---|
| 28 | Replica 全静态 combined 双稳态+更差 = limitation，不隐藏 | exp44 |
| 29 | vanilla 自身也有双稳态（room0 双 basin）—— MonoGS async 在任何数据集上都可触发 | exp44 |

## 自限

- 2 场景 × 3 seed，Replica 全静态，不声称对动态场景的结论。
- room0 双稳态使绝对值比较不可信；office0 可信。
- 跑的不是 `_sp` 而是 `single_thread`+`use_gui=False`（经 OOM 修复后的配置），对口 published `Ours(sp)` 行。
