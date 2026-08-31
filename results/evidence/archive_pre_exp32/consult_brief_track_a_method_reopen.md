# CONSULT BRIEF — 是否放弃"必须现在写作"硬约束、重开方法期（轨道A）

> 2026-08-09。用户偏向 A（重开方法期），要求对抗审查。日期锚：CCF-C ddl **2026-08-31**（3 周）。
> 本 brief 供 codex(MCP) + hermes(CLI) 双审。**不要恭维、不要替我决策，给可证伪的判断与基线概率。**

## 0. 需要你回答的问题（按重要性排序）

1. **A 是否有正期望值？** 给定下面第 3 节的"死清单"，是否还存在**任何**方法方向，能在
   3 周（或放弃 8/31、延到下一个 CCF-C 窗口）内产出真方法贡献？如果没有，直说没有。
2. 若 A 有方向，**哪一个期望值最高**？要给出：可证伪假设、最小判决装置（run 数/GPU 时）、
   失败模式、以及"它为什么不会重复死清单里的失败"。
3. **A 与 B 是否真的互斥？** 现稿 almost-ready。是否应该 A+B 并行（现稿投出去 + 同时开方法线），
   还是并行会污染/预占更强论文的贡献（self-preemption 风险）？
4. **诚实基线**：这个项目已 ~18 轮实验、几乎全负。重开方法期的成功概率你怎么估？
   在什么条件下你会建议"接受当前窄实证结果、不再重开"？

## 1. 项目与基座

- Dynamic 3DGS SLAM，基座 = **MonoGS**（Matsuki et al. CVPR 2024），在其上加动态模块。
- 硬件：本地 RTX 2060 6GB（实测上界 4.09GB，够跑全部论文数）+ 远程双 RTX 3090。
  一个 54-run campaign ≈ 28h。瓶颈是**时间不是显存**。
- 硬约束：`slam.py` / `gaussian_splatting/` 声明为**不可动实体**；判决必须 3 seed；
  预注册纪律（跑前定裁决规则，不可事后改）；比值跨 campaign 漂 ~30%。
- CLAUDE.md 原文：**"目标 CCF-C，但 MMM 等具体 venue 非必投；实验方法达标后才定投期"**
  ⇒ 8/31 不是项目硬约束，是写作期自加的。这一点对 A 的合法性很关键。

## 2. 现稿（B 的产物）与它的根本弱点

现稿定位 = **narrow-empirical characterization**，codex R1→R7 七轮审已全闭环，almost-ready：

- **核心发现**：MonoGS 的 **terminal color refinement**（后端 26000-iter 纯光度优化，
  `opt_before`→`opt_after` 两个 checkpoint 之间）会把 **8–18%** 的终图高斯软选择到
  `sigmoid(opacity) < 0.01`；删掉它们**零渲染代价**（18 图中 17 图 |dPSNR| ≤ 0.0003 dB，最差 −0.0025）。
- **专一性对照**（这是最强的一块）：同数量删 random = −0.2~−1.0 dB，删 high-op = −1.6~−5.7 dB，
  删 low-op cohort ≤ 0.003 dB。18 图 × 2 rate × random 10 draws。
- **cohort 累计权重证书**：每像素累计 compositing weight，W_p99 全部 <2%（typical <1%）。
- artifact：序列化 bytes 减 9–16%（明确写成 storage/transfer，不是 runtime/compression）。
- 骨干 floor：自跟踪 6 序列不崩（balloon 3.06cm / mv_no_box 2.66cm；person 序列 10cm+）。

**用户刚点破的根本问题（我已核实代码）**：

1. 这个 `color_refinement` 是 **MonoGS 原生自带**（upstream first commit `7c4ce90` 就有，
   硬编码 26000 iter，我们只把迭代数做成可配置项）。**不是我们的机制。**
2. 它**不是所有 3DGS SLAM 都有**的环节。在线剪枝路线（MGS-SLAM / Speedy-Splat / PUP-3DGS，
   正是我们 Related Work 点名对比的那批）没有终端纯光度 refinement ⇒ **不会有这个 cohort**。
   所以现象连"dynamic 3DGS SLAM 的"都不是，是"带 MonoGS 式终端 refinement 的前端的"。
3. 因此现稿的贡献形状 = **对基座自带机制的一个 artifact 的表征**，不是方法贡献。
   （codex R3 自己的措辞：最弱环 = "artifact 仅是效用非算法"。）
4. 机制上还有一层：freeze-opacity 反事实显示，冻结 opacity 后尾巴 12.8%→3.7% 但
   **PSNR −0.53 dB、N +35%** ⇒ 软选择是 refinement 的**补偿机制**，不是"堆积的浪费"。
   所以**不存在可省的在线算力**（这也正是"online compaction / compute savings"进禁词表的原因）。

## 3. 死清单（历代方法迭代的裁决，全部有多 seed 或机制证据）

| 方法 | 裁决 | 死因 |
|---|---|---|
| DeferredCommit（候选延迟提交生命周期）| 死 | 6/6 序列 ATE 更差；reject/expire 两臂过滤同构；dedup 闸吃掉 80-89% promotion ⇒ 10× 欠播种 |
| FullFramePose（全帧 PnP 位姿提议）| NEGATIVE | f3_wk_xyz +41.3% 变差、f2 timeout |
| CoarsePoseInit（const_vel 粗位姿初始化）| 证伪 | 长序列正反馈漂移积分器（弱光度精修消不掉外推速度）|
| masked_icp | 负 | 掩码后 ICP 仍无稳定增益 |
| eviction（观测反驳驱逐）| NO-GO | 已复核到 deferred 臂仍无信号；vac_excess ≈ 0 |
| α-carve | 死 | 闸门不可达（需 n≥12，obs_max=11）|
| RobustTracking | flat | +1.2%（vs 目标 −41%）；被 mask_mapping+mask_insertion 冗余吞掉 |
| ReliabilitySignal | 未晋级 | −2.9%/−5.8% < 预登记 15% 门槛 |
| DBA-lite photo-weighted BA | 干净 NO-GO | reliability w 在线已同时加权 RGB+depth ⇒ 离线复用是重复信号 |
| S6 旋钮组（ttl/densify/gth）| scope 结果 | 6 序列里 4/6 rate 到了但**两项保真都破**；ttl=1 使生命周期退化成"全插再全删"|
| compactness headline | 死 | prune 加压扫掠追平了 deferred（S6 0.63–0.81×B）⇒ "只有 deferred 到得了"塌 |
| **H-D hybrid**（按 mask 覆盖率逐 KF 选 lifecycle）| **INDETERMINATE（唯一未被证伪的）** | 3 个可判序列 <1 同向、无反例，但覆盖率秩在 pt1/pt2 翻转、Spearman ρ=+0.257 p=0.62；**且覆盖率与 tracking-difficulty 共线**（hermes 上轮指出的最锋利盲点）|

**已知的真 gap（三次确认）**：我们 ATE ~3cm vs SOTA 1.5cm，差距在 **BA backend**
（MonoGS 没有真正的 BA/loop closure）。但"tracking 方向"在项目死清单上（不回炉）。

## 4. 两个选项

- **A（用户偏向）**：去掉"必须现在写作"约束，重开方法期。代价：新 campaign（多序列 × 3 seed）、
  H-D 的 per-KF 分流是**真核码改动**（撞"不可动实体"约束）、共线混淆需要新序列才能打破、
  3 周内几乎不可能出 3-seed 判决 ⇒ 实质是放弃 8/31、押后一个投稿窗口。
- **B**：现稿以窄实证 + 展望投出（H-D 作为"可证伪假设 + 已冻结的 gating 信号"写进 future work，
  这正是 codex/hermes 上轮一致推荐的 D′ 叙事），8/30 投，H-D 留下一篇。

## 5. 你必须遵守的边界

- 不要建议复活死清单上已多 seed 判死的方法，除非你能指出**具体的、之前没测过的**机制差异。
- 不要建议"再多跑几个 seed 看看"作为方向。
- 不要建议放宽预注册/判据来让结果变好看。
- 如果你认为诚实答案是"A 没有正期望值、该收 B"，请直接说，并给出你的理由与反例条件。
