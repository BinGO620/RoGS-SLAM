我已经读完三份文件。在回答前先确认一个事实问题：brief §3 说 equivalence band "写于 1/8 runs done"，而 prereg §8 addendum 也说写于第 1 个 run 完成时、任一 ratio 不可计算前。两处自洽。但 brief §3 最后一句把 band 来源写成 "pooled within-campaign sd of paired log(G_def/G_prune) across three prior frozen-pose campaigns (SWEEP 0.0382, DECOMP 0.0845, MASKRATE 0.0572)"，而 prereg §8.1 的表列出的是三个 **R2-P03/R2-P04** campaign，主骨干是 **rtoff**、序列是 **balloon**、注入位姿是 **RGD**。这跟 P2-SF 本身（monogs 骨干、pt1/balloon2、prune-self-trajectory）是三个维度都不同的 regime。这一点后面会用到。

下面逐条对抗性回答。

---

# P2-SF seed-0 readout 对抗性审查

## 总体立场

我（hermes）当初提出的盲点是：**mask 覆盖率与 tracking 难度共线，pt1/pt2 既是高覆盖又是 hard-tracking，所以 n=6 自跟踪主表无法把"lifecycle 改 map"和"lifecycle 通过 tracking 质量 改 map"分开**。P2-SF 的设计意图是冻结位姿、关掉 tracking-difficulty 这个通道，看 map-level 差异是否存活。

读完 seed-0 数据后我的判断是：**数据方向性令人意外地一致，但有三个结构性裂缝使它无法承担"共线盲点已解决"的叙事，且其中两个裂缝补 seed 修不了**。下面具体说。

---

## Q1 — 共线盲点真的解决了吗？放大能否被解读？

### 观察到的事实

冻结位姿后，两个序列的 R_G^F 都从自跟踪值 **远离 1**，不是趋近 1：
- pt1: 0.794 → 0.362 (C)
- balloon2: 0.910 → 0.567 (C), → 0.282 (B)

一个"compactness 全是 tracking-difficulty artifact"的账户预测冻结后会衰减回 1。观测到的反向运动。这是真实的、值得记录的信号。

### 这个观测允许说什么

允许说：**在 pt1 和 balloon2 上、当位姿被冻结到 prune 臂自跟踪轨迹时，deferred 仍产出更小的 map，且差距比自跟踪时更大**。仅此。这是 prune-conditioned estimand（prereg §4.6 明示），不是"lifecycle 在一般意义上 tracker-orthogonal"。

### 这个观测不允许说什么（也是 brief 里我担心往 upgrade 滑的地方）

**"Amplification licenses tracker-orthogonal mapping channel" 这个措辞太强。** 放大有一个不依赖 tracker-orthogonal 通道的替代解释，brief §5.Q1 自己也问到了它但没回答：

> 替代账户：冻结位姿同时削掉了 ~35% 的关键帧预算（pt1 116→76, balloon2 94→60）。更少的 KF = 更少的 add-and-refine 机会 = prune 臂的"先插后剪"机制损失了它最依赖的 refine 机会，而 deferred 的"暂存再决定"机制对少 KF 更鲁棒。这时 R_G^F 测的不是"lifecycle 在等位姿下扰动 map"，而是"lifecycle 对**少 KF 的 mapping schedule** 的不同响应"。

这个账户**也预测放大**——因为它把 prune 臂从它自跟踪时的有利 schedule（多 KF）搬到一个对它不利的 schedule（少 KF），所以 prune 的 G_prune 膨胀相对 deferred 更明显。它不要求任何 tracker-orthogonal 通道存在，只需要"prune 机制对 KF 数量更敏感"。

**这个替代账户与 §4.8 ambiguity trigger 是同一个东西的另一面**，而 §4.8 在 4/4 pair 上都触发了（brief observation 7）。所以在当前装置下，amplification 与"共线盲点已解决"**逻辑上不互斥但证据上不可分离**。我不同意 brief 隐含的"放大 ⇒ tracker-orthogonal 通道"的推理链——放大同时被 (a) tracker-orthogonal 通道存活 和 (b) KF-budget 混淆 两个账户预测，数据无法区分二者。

### 与 codex 的预期分歧点

codex 预期会与我一致认为"序列级共线仍未解决"。我同意。但我想把分歧点精确化：**不是"identical within-pair poses 没解决共线"——pair 内位姿确实恒等，pair 内 tracking-difficulty 通道确实关掉了**。没解决的是**序列级**共线：我们仍然只有 hard-tracking (pt1) 和 easy-tracking (balloon2) 两个序列，所以"效应大小是否随 tracking-difficulty 变化"这个序列级问题，n=2 给不出任何斜率信息。pair 内冻结解决了"pair 内差异是 tracking 还是 lifecycle"的问题，但没解决"为什么 pt1 比 balloon2 更极端"的问题——后者仍是 coverage-vs-difficulty 共线。

codex 若反对，反对点会是：pair 内恒等位姿已经足够回答"lifecycle 是否 tracker-orthogonally 扰动 map"这个**机制存在问题**，序列级共线只影响"stratifier 选 mask-coverage 还是 tracking-difficulty"这个**归因问题**，而 H-D 本来就是 stratifier 假设。我的反驳是：brief §1 把 H-D 定义为"choose lifecycle by semantic-mask coverage"，所以归因问题是 H-D 的核心，不是附属。能了断这个分歧的证据是：**在 tracking-difficulty 持平、coverage 不同的两个序列上跑**（例如两个 easy-tracking 序列，一高一低 coverage），看效应是否随 coverage 变。当前 pt1/balloon2 给不了这个。

---

## Q2 — §4.8 在 4/4 触发，R_G^F 还是不是 admission-efficiency 度量？

### 我的判决：在当前装置下不是

R_G^F = G_def/G_prune 在两臂 KF 数不同时，度量的是 **总 lifecycle mapping-policy 效应**（admission policy × KF schedule 的联合），不是纯 admission efficiency。这是 prereg §4.8 自己写明的，不是我的新发现。问题在于 4/4 触发意味着**每一格都受污染**，没有干净对照格可用。

### per-KF normalization 的评价

per-KF ratio = (G_def/KF_def)/(G_prune/KF_prune) 是 **post-hoc、未预注册**（brief §4 表注自己标了）。它做了一件合理的事：把 KF 数不等导致的"纯规模差"剥离。但它做不了一件它看起来在做的事——它**假设 G 与 KF 是线性关系**，即每个 KF 贡献约等的 G。这个假设没有依据：prune 臂的 G/KF 在 C-pt1 是 56915/76=749，在 C-balloon2 是 24381/60=406，差 1.85×，说明 G/KF 强烈依赖序列内容和 KF 的空间分布，不是常数。所以 per-KF ratio 是一个 **有方向指示意义、无定量意义的描述统计**。

brief §4 说"KF gap explains 10%/7%/25%/1% of the distance from 1"——这个数字是从 `(R_G - per_KF_ratio)/(R_G - 1)` 算的吧？它依赖上面那个线性假设。**我建议这个百分比不进任何叙事，只在 limitation 里写"KF schedule 不等，per-KF 归一给出方向性 bound 但依赖未验证的线性假设"**。

### 更好的预承诺方法

唯一干净的方法是 **冻结 KF indices**，不是冻结 KF 数。prereg §4.8 和 synthesis 都写了"freeze keyframe indices if feasible"。**装置事实是没人去试是否 feasible**。brief §3 只报了 KF 数变化，没报是否尝试过强制两臂用同一组 KF indices。这是装置层面最大的未完成项。如果 KF indices 能冻结（在 prune 臂自跟踪 schedule 上取并集或交集，强制 deferred 用同一组），R_G^F 才是干净的 admission-efficiency 度量。否则它永远是 mapping-policy 联合度量。

---

## Q3 — 35% KF 预算下降是否切断与自跟踪主表的桥？

### 我的判决：切断。C 不是自跟踪结果的控制，是另一个实验。

逻辑链：
1. 自跟踪主表里 prune 臂在 pt1 有 116 个 KF，那是它"自己的"schedule，它的 G_prune=56915 是在 116 KF 下产出的。
2. C 里同一个 prune 臂被放到 76 KF 的 schedule 上，G_prune 还是叫"G_prune"但已经是 76-KF-regime 的产物。
3. R_G^F = G_def(65 KF)/G_prune(76 KF) 与自跟踪 R_G = G_def(116 KF regime)/G_prune(116 KF regime) **不在同一个 mapping budget 上**。

所以"自跟踪 0.794 → frozen 0.362，效应放大"这个比较 **apples-to-oranges**。放大的一部分（可能大部分）来自 prune 臂从 116 KF 掉到 76 KF 时 G_prune 没等比例下降（prune 机制对 KF 削减不敏感，因为它的 G 主要来自初始 splat 而非后续 refine），而 deferred 臂的 G_def 对 KF 削减更敏感（少 KF = 少 promote 机会）。这又回到 Q1 的替代账户。

**C 能声称的只有："在 76/65 KF budget 下，deferred 比 prune 紧凑"**。它不能声称"在自跟踪的 116 KF budget 下，冻结位姿后 deferred 仍比 prune 紧凑"——后者才是控制自跟踪结果的实验，而它没跑。

### 这是否致命

对"证明 tracker-orthogonal 通道存在"不致命——只要 G 数在等位姿下不同，就有某个 map-level 通道。对"把这个结果桥接回自跟踪主表的 compactness 叙事"**致命**。brief §4 observation 2 那句"the contrast strengthens rather than collapses toward 1"隐含了桥接，但桥接在 KF 预算不等时不成立。**这句要改**。

---

## Q4 — variant 间 rank reversal 是 informative 还是其中一个在测别的东西？

### 观察 3 重述

- C: pt1 (0.362) 比 balloon2 (0.567) 更极端
- B: balloon2 (0.282) 比 pt1 (0.737) 更极端
- pt1 的绝对 map 大小在 C/B 间差 4.3× (56915 vs 13258)，balloon2 几乎不变 (24381 vs 26427)

### 我的判决：这是"两个 variant 在测不同东西"的强证据，不是 codex 说的"informatively disagree"

codex 当初说"concordance across B and C = strong; disagreement = informative"。这个框架成立的前提是 B 和 C 测同一个 estimand、只是 regime extremity 不同。**rank reversal + pt1 绝对值 4.3× 跳变**不符合这个前提。如果只是 regime extremity 差异，你会期望**绝对值变、相对秩不变**。秩翻转 + 单序列绝对值跳变说明 B 和 C 在 pt1 上激活了完全不同的 mapping 动力学。

具体说：pt1 在 C (11cm 位姿) 下 prune 臂 G=56915，在 B (0cm 位姿) 下 prune 臂 G=13258。**同一个序列、同一个 lifecycle、只换位姿质量，prune 的 map 大小差 4.3×**。这本身就是"位姿质量强烈影响 map 大小"的证据——而这正是 P2-SF 想关掉的通道。它没关掉，至少在 pt1 的 prune 臂上没关掉，因为 B 和 C 的位姿质量差距太大。

这引出一个更不舒服的推论：**B 不是 C 的 regime-extremity 版本，B 是一个不同的实验**。prereg §1 把 B 定位为"sensitivity"是对的，但 sensitivity 的前提是主实验的 estimand 在 B 下仍有意义。如果 B 下 pt1 的 map 缩到 1/4，B 测的可能是"在几乎不需要 mapping 校正的完美位姿下 lifecycle 还有多大差别"——这跟 C 测的"在真实位姿下 lifecycle 是否 tracker-orthogonally 扰动 map"是不同问题。

### 能了断的证据

跑一个 **intermediate-pose variant**（比如注入 deferred 臂的自跟踪轨迹，或一个 5cm 级的中性轨迹），看 pt1 的 G_prune 是否随位姿质量单调变化。如果是，B/C 的 rank reversal 就是位姿质量对 prune 臂 map 大小的强非线性效应，不是 lifecycle 机制故事。如果否（中间位姿下 pt1 的 G_prune 回到 ~57000），那 B 是个 outlier regime、C 是主实验。但这个实验要新轨迹，provenance 问题回来——所以实践中**只能写成 limitation**。

---

## Q5 — pt1 depth breach (+2.423 vs 1.56) 怎么写？

### 事实

C-pt1 是 4 格里唯一 breach 的：depth +2.423 cm（gate 1.56），psnr +0.083 dB（ok）。形状是 compactness benefit (0.362) + fidelity harm (depth breach)。C-balloon2 是 clean-benefit (0.567 + 两个 guardrail ok)。B 两格都 ok。

### 怎么写

**不能写成"trade-off in one sequence"并暗示这是可接受的 cost**。原因：
1. n=1 seed，breach 可能是 seed-specific 噪声。
2. pt1 恰好是 hard-tracking 序列，breach 出现在 hard-tracking 序列上**复现了原始共线**——"deferred 在 hard-tracking 时省 map 但伤保真"正好是 tracking-difficulty 通道会预测的模式。即使位姿冻结了，KF schedule 没冻结，hard-tracking 序列的 KF schedule 更脆弱，所以 breach 仍可能间接来自 tracking-difficulty。这**不是** tracker-orthogonal 的证据，反而可能是"tracking-difficulty 通过 KF schedule 间接影响 map"的证据。

**建议写法**：
> C-pt1 出现 depth breach (+2.423 cm vs 1.56 cm inherited gate)。由于 (a) 单 seed 不可判，(b) breach 仅出现在 hard-tracking 序列上，与 tracking-difficulty 通道的预测一致，(c) KF schedule 未冻结（§4.8），此 breach 无法归因于 lifecycle 本身的保真代价，更可能是少-KF schedule 下 prune 臂被移出其有利 regime 的副产物。在 KF schedule 冻结前不解读此 breach 的机制。

### 与 brief 的措辞差异

brief §5.Q5 把它框成"two sequences, two shapes, n=1 seed each"——这个框法是中性的，可以。但它隐含的"trade-shaped vs clean-benefit-shaped"二分**暗示 trade 是一种合法 shape**。在 guardrail breach 的情况下，trade shape 意味着 deferred 在省 map 的同时**伤害了保真**，这直接削弱"deferred 是 free lunch"的叙事。不要把它和 clean-benefit 并列为两种合法 shape；breach 就是 breach，是负面信号。

---

## Q6 — 4.3h 补 seeds 1-2 vs 修 KF schedule vs 停手写 limitation

### 排序建议

**第一优先：就此停手写成 limitation。** 理由：

1. 补 seed **修不了** Q1-Q4 的任何结构性裂缝。共线盲点（Q1）、KF schedule 混淆（Q2）、桥接切断（Q3）、B/C 测不同东西（Q4）都是**装置级**问题，不是方差问题。3 seed 只能缩小 R_G^F 的置信区间，不能让 R_G^F 重新变成干净的 admission-efficiency 度量，不能重建与自跟踪主表的桥，不能解释 rank reversal。
2. 补 seed 后唯一能说多的是"方向在 3 seed 上稳定"——但方向稳定 + estimand 受污染 = 稳定地测了一个受污染的量，不增加叙事力。
3. 4.3h GPU 不算多，但叙事门 08-04、写作硬启动 08-06，时间机会成本高。这 4.3h 花在 limitation 文字上比花在 seed 1-2 上对论文更有利。

**第二优先（如果用户坚持要更多数据）：修 KF schedule 再跑，不要直接补 seed。** 如果 KF indices 能冻结（强制 deferred 用 prune 的 KF 集合），R_G^F 变成干净度量，那时再跑 3 seed 才有意义。但 KF 冻结需要改 slam.py 的 keyframe 逻辑，工程量未知，可能超 08-04 叙事门。如果工程上确认不可行，回到第一优先。

**第三优先（最差选项）：直接补 seed 1-2 不修装置。** 只有在用户判断"3-seed 方向稳定本身对 limitation 叙事有加成"时才做。我认为加成很小，不值得 4.3h。

### 一句话

**停手写 limitation，除非 KF 冻结在 08-04 前能做完——后者做不到就别补 seed。**

---

## Q7 — 上限审计：哪里在往 upgrade 滑

### §4.4 ceiling 重述

prereg §4.4 + brief §2: 此对照只能 **weaken 或 leave-unchanged** H-D 的 INDETERMINATE 判决，**永远不能 upgrade**。n=2、map-level only、seen data。

### 需要删/改的具体句子

**1. Brief §4 observation 2（line 101-102）**
> "Under frozen pose the contrast **strengthens** rather than collapses toward 1 (pt1 0.794→0.362 under C; balloon2 0.910→0.567 under C, →0.282 under B)."

**问题**：这句隐含"冻结位姿后效应更强 ⇒ 通道更可能是 tracker-orthogonal ⇒ H-D 机制故事更可能成立"。这是 upgrade 方向的推理。且如 Q3 所述，比较不在同一 KF budget 上，"strengthens"是 apples-to-oranges。

**建议**：改为纯描述，不加方向性动词。"Under frozen pose, R_G^F remains below 1 in all 4 cells (0.362, 0.567, 0.737, 0.282). Note these are computed at reduced KF budgets (≈65% of self-tracked), so they are not directly comparable to the self-tracked R_G values." 删掉 "strengthens" 和 "collapses"。

**2. Brief §5 Q1（line 116-117）**
> "A pure 'compactness is a tracking-difficulty artifact' account predicts attenuation. What does the observed amplification license..."

**问题**：把"amplification"作为已成立的事实，并问它"license"什么——"license"这个词预设了 amplification 是证据性的。如 Q1 所述，amplification 有不依赖 tracker-orthogonal 通道的替代解释（KF-budget 混淆）。这个问题本身在诱导 reviewer 往 upgrade 答。

**建议**：改为 "A 'compactness is a tracking-difficulty artifact' account predicts attenuation under frozen pose. The observed movement away from 1 is consistent with this account being incomplete, but is also consistent with a KF-budget confound (§4.8 fires on 4/4). What can be said given these two accounts are not separable at n=2, seed-0?"

**3. Brief §1（line 22-23）**
> "P2-SF is the de-confounding control: freeze pose identically for both arms, so any surviving map-level difference cannot come from the arms tracking differently."

**问题**："any surviving map-level difference cannot come from the arms tracking differently" 在 pair 内是对的（pair 内位姿恒等），但**读者会外推到序列级**，以为 tracking-difficulty 共线整体被解决了。这正是我当初提的盲点，而它没被序列级解决（Q1）。

**建议**：加限定词。"P2-SF is the de-confounding control for **within-pair** tracking differences: freeze pose identically for both arms, so any surviving map-level difference cannot come from the arms tracking differently **within a pair**. **Sequence-level** coverage-vs-difficulty collinearity (the original blind spot) is not addressed by n=2."

**4. Brief §4 observation 1（line 100）**
> "All 4 cells are < 1 and outside the band; all 4 agree in sign with self-tracked."

**问题**："agree in sign with self-tracked" 暗示 frozen-pose 结果**支持**自跟踪结果的解读。但如 Q3，frozen-pose 在不同 KF budget 上，sign 一致不等于机制一致。这句本身是事实陈述，但放在 "Salient structure we can see but have deliberately not interpreted" 标题下，然后又列出"agree in sign"——列出本身就是一种轻量级解读。

**建议**：保留事实，删掉与自跟踪的 sign 比较，或显式标注"sign agreement across different KF budgets is not mechanistically informative"。

**5. Prereg §6（line 76）**
> "CONCORDANT MAP-EFFECT ⇒ 边界有 map-level 通道，叙事 D′ 的 'lifecycle 直接改变 mapping' 站得住"

**问题**：这是预注册里写的分支解读，不是 readout 里的新措辞。但它的措辞"站得住"已经接近 upgrade——它说 H-D 机制故事"成立"。在 §4.4 ceiling 下，CONCORDANT MAP-EFFECT 能说的是"cannot attribute to coverage vs tracking, remains stated limitation"（synthesis §1 line 17 写对了），不是"机制故事站得住"。

**建议**：这条在预注册里已 frozen，不建议改预注册。但 readout 和后续叙事**不得引用这句话的"站得住"措辞**；引用时必须用 synthesis §1 的更弱版本。

### 没有滑的措辞（给个平衡）

- Brief §2 "CEILING (hard): this control may only weaken or leave unchanged" —— 明确，没滑。
- Brief §3 "ATE = canary, NOT an outcome" —— 全程没把 ATE 当证据用，没滑。
- Brief §4 表注 per-KF ratio "DESCRIPTIVE, post-hoc, NOT pre-registered" —— 标注了，没滑。
- Prereg §4.4 本身 —— 没滑。

---

## 与 codex 的预期分歧总结

| 点 | hermes | 预期 codex | 能了断的证据 |
|---|---|---|---|
| 序列级共线是否解决 | 未解决（pair 内解决、序列级 n=2 给不出斜率） | 同意未解决 | tracking-difficulty 持平、coverage 不同的两序列对比（当前没有） |
| amplification 是否 license tracker-orthogonal 通道 | 不 license，KF-budget 替代账户同向预测 | 可能更倾向"放大是积极信号" | 冻结 KF indices 后重跑（Q2） |
| B/C rank reversal 是 informative 还是测不同东西 | 测不同东西（pt1 绝对值 4.3× 跳变） | 可能倾向"informatively disagree" | intermediate-pose variant（provenance 问题使不可行） |
| 补 seed 是否值得 | 不值得，停手写 limitation | 可能更倾向补 seed 确认方向 | 无——这是判断分歧不是事实分歧 |

最可能导致 codex 与我不同结论的点是 **amplification 的解读**：如果 codex 认为 KF-budget 混淆是二阶的（per-KF 归一后只解释 10-25%），amplification 的主体仍是 lifecycle 信号，codex 会比我更乐观。我的反驳是：per-KF 归一依赖未验证的线性假设（Q2），10-25% 这个数字本身不可信，所以"二阶"判断不成立。**能了断这个分歧的证据是冻结 KF indices 重跑——如果冻结后 amplification 仍在，codex 对；如果 amplification 塌回 1 附近，我对。**

---

## 最终建议

**停手。把以下写进 limitation：**

1. P2-SF 在 pair 内冻结了位姿，关掉了 within-pair tracking-difficulty 通道。这是对原始盲点的部分回应。
2. 但序列级 coverage-vs-difficulty 共线（n=2，pt1=hard+low-cov, balloon2=easy+high-cov）未解决，无法判断效应大小是否随 coverage 或 difficulty 变化。
3. KF schedule 未冻结（§4.8 在 4/4 触发），R_G^F 度量的是 mapping-policy 联合效应而非纯 admission efficiency。per-KF 归一是 post-hoc 描述统计，依赖未验证的线性假设。
4. 冻结位姿导致 KF 预算下降 ~35%，frozen-pose R_G^F 与自跟踪 R_G 不在同一 mapping budget 上，不可直接比较。observation 2 的"strengthens"措辞因此不成立。
5. B/C rank reversal + pt1 绝对值 4.3× 跳变表明 B 和 C 在 pt1 上可能测不同 estimand，B 作为 sensitivity 的前提（同 estimand、不同 regime extremity）不成立。
6. C-pt1 depth breach 出现在 hard-tracking 序列上，与 tracking-difficulty 通道预测一致，未冻结 KF 前不解读机制。
7. H-D 维持 INDETERMINATE。本对照未 weaken 也未 upgrade。

这比"放大 ⇒ 通道存在"的叙事弱，但它在评审时活得住。
