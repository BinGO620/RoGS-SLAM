数据核对完毕，所有绝对值与 delta 均对得上（补丁的 vac_psnr/vac_depth 与原 CSV 一致；第三列它叫 "static_psnr(non-vac)" 但实际填的是 `static_psnr` 整图均值，不是 `static_nonvacated_psnr`，这是补丁的标签错误，但不影响任何裁决——9dB 的 regime 跳变在 vacated 上和整图上同时成立）。下面是 4 个问题的对抗性裁决。

---

# P2-SF regime patch 复审

## 总体立场

这个补丁在两审 packet 之上加的不是新数据，是一个**视角切换**：从 Δ-only（两审已经看到且已经判了）切到绝对值 regime。这个切换本身是合法的，但它问的 4 个问题里有 2 个（Q1、Q2）**指向一个我在双审时没核对的承重假设**，所以它不是噪声。具体说：Q2 是真问题，Q1 是 Q2 的推论，Q3/Q4 是双审已结论的强化重述。逐条如下。

先确认我自己的原始立场，因为用户明确要求我指名。在 `consult_hermes_selffrozen.md`（设计期，跑前）我主张的是 **C 主 B 副**，理由写在 Q2：B 的 0cm GT pose 是 regime shift，可能**压住正在测的 pose-map-feedback 通道**，所以 NO-MAP-EFFECT 在 B 下不可解释；C 保留 11cm 真实 regime。codex 当初主张 B 主（因果最干净）。裁决是 C 主 B 副。我在双审 readout（`consult_hermes_p2sf_readout.md`）里**没有推翻这个 C 主 B 副的判断**——我把它作为既成事实接受，转而集中火力在 KF schedule 混淆和桥接切断上。

补丁的 Q2 问的就是：C 主 B 副这个判断，在 regime 错配这个新视角下，是否应该反过来。

---

## Q1 — 继承的 0.28dB/1.56cm 边界源自 14.5dB regime，C 臂在 21-24dB，C-pt1 的 depth breach 能不能用继承边界判？

**裁决：不能作 breach 定性，但也不能作"假 breach"开脱。判 indeterminate-breach，且这个 indeterminacy 是承重的。**

核对我追到的边界来源链：

- `r2_p03_sweep.md` §1 line 67-68 明写：1.56cm = **1× self-tracked null sd 1.559**，0.28dB = **1× null sd 0.278**。这两个 null sd 来自 `r2_p02_e2.md` §8.1 的 **7 个 balloon 自跟踪/注入 replicate**（`static_vacated_psnr` null mean 21.103、null sd 0.278；`static_vacated_depth_l1_pen_cm` null mean 23.425、null sd 1.559）。
- 这 7 个 replicate 的 PSNR 绝对值在 20.65-21.78（见 `r2_p02_e2_metric_calibration.txt`），即 **~21dB regime**。注意：SWEEP/DECOMP/S6REPL 三个 frozen-pose campaign 的 balloon 跑在 RGD 注入轨迹上，绝对 PSNR **~14.5dB**（`r2_p03_decomp.md` line 120、`r2_p03_s6repl.md` line 178、`r2_p04_maskrate.md` line 138 三处都写明 "PSNR ≈ 14.5 regime"）。

这里有一个**补丁自己都没抓到的更深的裂缝**：继承边界 0.28/1.56 的 null sd（1.559/0.278）来自 **~21dB 的 balloon 自跟踪+注入混合 replicate**，而 SWEEP/DECOMP/S6REPL 这三个被当作"源 regime"的 frozen-pose campaign 实际跑在 **14.5dB** 上。补丁说"继承边界源自 14.5dB regime"——这个说法**不精确**。继承边界的 null sd 源自 21dB 的 E2 replicate；14.5dB 只是 SWEEP/DECOMP 那条线自己的绝对 PSNR。`prereg §8.1` 的 equivalence band（0.0629）确实来自那三个 14.5dB campaign 的 ratio sd，但**保真 margin（0.28/1.56）的 null sd 不是**。

这意味着补丁 Q1 的措辞要修正，但**结论方向不变甚至更强**：

- C 臂 vac_psnr 绝对值 24.4（pt1）/ 21.5（balloon2）。C-balloon2 的 21.5 **恰好落在 0.278 null sd 的源 regime（~21dB）**——这条边界对 C-balloon2 **是适用的**。C-pt1 的 24.4 在源 regime 之上 ~3dB，边界适用性存疑但偏差不大。
- B 臂 vac_psnr 15.0-15.5。这**远低于** 0.278 null sd 的源 regime（~21dB），差 ~6dB。补丁说 B 落在 14.5dB≈源 regime——**对 equivalence band（ratio sd）对，对保真 margin（null sd）错**。B 的保真 margin 同样是从 21dB regime 借来的，不是 14.5dB 的。

所以 Q1 的精确答案是：

1. **C-pt1 的 depth breach +2.423 破 1.56**：1.56 的 null sd（1.559）源自在 ~21dB regime 下 7 个 balloon replicate 的 depth 抖动。C-pt1 在 24.4dB，比源 regime 高 3dB。保真差的 noise floor 在不同 PSNR regime 下不是常数——高 PSNR 下 depth-L1 的 pixel-level 灵敏度更高，理论上同源扰动可能产生更小的 cm 差（因为渲染更锐），所以 1.56 在 24dB 下可能是**偏松**的边界（即 breach 更可能是真 breach，不是假 breach）。但这只是定性推断，没有 24dB regime 下的 null sd 实测。**判 indeterminate-breach：不否定 breach 存在，但否定它可以用 1.56 定性为"deferred 伤保真"。**
2. **B 的所有保真读数**：vac_psnr 15.0-15.5 远在 21dB 源 regime 之下，0.28dB 的 null sd 在 15dB regime 下几乎肯定**不是 0.278**——低 PSNR 下 pixel-level noise 更大，null sd 应该更大。所以 B 的保真 margin 被**低估**（边界偏紧），B-balloon2 的 +0.252 逼近 0.28 **更可能是噪声不是真 breach**。这反而对 B 有利，但不改变双审"B 测不同东西"的结论。

**一句话**：补丁 Q1 的 regime 归属措辞有误（0.28/1.56 的 null sd 源自 21dB 的 E2 replicate，不是 14.5dB 的 SWEEP/DECOMP），但结论方向成立——继承边界对 C-pt1 的 24dB 适用性存疑（偏松可能），对 B 的 15dB 适用性也存疑（偏紧可能）。C-pt1 的 depth breach **既不能定性为真 breach 也不能开脱为假 breach**，在 24dB-regime null sd 实测前判 indeterminate。这个修正**不改变双审任何结论**，因为双审本来就没把 C-pt1 breach 当判决证据（hermes readout Q5 已写"n=1 seed 不解读机制"）。

---

## Q2 — B 落在继承边界源 regime（15dB≈14.5dB），C 不落（21-24dB）。这是否翻转 C 主 B 副？

**裁决：不翻转。补丁这里的推理有一个混淆——它把 equivalence band 的源 regime 和保真 margin 的源 regime 当成同一个，它们不是。但即使纠正这个混淆，Q2 仍然暴露了一个双审没正面回答的真问题，我要重述立场。**

先拆补丁 Q2 的混淆。补丁说"继承边界源自 14.5dB regime，B 落 15dB≈源，C 落 21-24dB 错配"。核对：

- **equivalence band（0.0629，用于 R_G^F 判别）**：源自 SWEEP/DECOMP/MASKRATE 三个 frozen-pose campaign 的 ratio sd，那三个确实跑在 ~14.5dB（balloon+RGD）。B 的 15dB 在 PSNR 绝对值上接近 14.5dB——**对 band 而言 B 确实更近源 regime**。✓
- **保真 margin（0.28/1.56，用于 guardrail）**：如 Q1 所述，null sd 源自 E2 的 ~21dB replicate。C-balloon2 的 21.5dB **更近源 regime**，B 的 15dB 错配。✗

所以补丁 Q2 的"边界"是一个**歧义词**：对 R_G^F 的 equivalence band，B 更适用；对保真 margin，C-balloon2 更适用（C-pt1 24dB 偏高，B 15dB 偏低，都不太适用）。补丁把两个边界混成一个"14.5dB regime"来论证 B 更适用，**这是一个真实的逻辑错误**。

但——这是关键——**即使纠正这个错误，Q2 仍然指向一个我在设计期和双审期都没正面处理的问题**：

**R_G^F（primary observable）的 equivalence band 源自 14.5dB regime。B 的 PSNR 15dB 落在源 regime，C 的 21-24dB 不落。这意味着 R_G^F 的判别性（"四格全在带外"）在 B 上是 band-适用的，在 C 上是 band-错配的。**

这反过来影响什么？影响双审里 hermes 和 codex 都接受的一个事实陈述："四格全 <1 且全在带外"（brief observation 1）。这个陈述在 B 上成立（band 适用），在 C 上**band 适用性存疑**——C 的 R_G^F 是否真的"在带外"取决于 21-24dB regime 下的 ratio sd 是不是还是 0.0629，而这个 sd **没有实测**。

那这会不会翻转 C 主 B 副？**不会**，理由如下，而且我要指名这是我立场的修正不是坚持：

1. **C 主 B 副的原始理由（regime preservation：B 的 0cm 压住 pose-map-feedback 通道）仍然成立**。这个理由不依赖 band 适用性，它依赖的是"被测现象本身是 regime-dependent"（R2-P01-E2 证明 PSNR 15 vs 23）。补丁的 regime 错配论点是关于**测量工具的 calibration**（band/margin 是否适用），不是关于**被测现象是否存活**。这是两个不同层面。C 在 21-24dB 测到 R_G^F=0.36-0.57，这个读数本身的存在不依赖 band；band 只影响"能否判别性地说它在带外"。即使 C 的 band 错配导致"带外"判别失效，C 仍然显示了同方向 map-size 差异——只是判别力度从"判别性"降到"方向性"。

2. **但补丁 Q2 暴露的是：B 在 band-适用 regime 下，R_G^F 的判别性反而比 C 更可信**。B-pt1 0.737、B-balloon2 0.282 都在 14.5dB 源 regime 的 band（[0.939,1.065]）外，这个"带外"判别是 calibration-干净的。C 的"带外"判别是 calibration-存疑的。**所以在 R_G^F 这个 primary observable 上，B 的判别性证据比 C 强。**

3. **这和 C 主 B 副不矛盾**。C 主的理由是 estimand 真实性（11cm regime 是自跟踪的真实 regime，B 的 0cm 是人造 regime）。B 副的理由是 calibration 干净但 estimand 偏离。**C 的 estimand 更对，B 的 calibration 更对**——这两个维度不互斥，双审的 C 主 B 副裁决是在 estimand 维度上选 C，不是在 calibration 维度上选 C。补丁 Q2 的论点是在 calibration 维度上选 B，这是**对的但回答的是不同问题**。

**我的立场重述**：

- **C 主 B 副的 estimand 层面裁决不变**。C 的 11cm regime 是自跟踪主表的真实 regime，B 的 0cm 是 regime shift。这个判断和 band/margin 的 calibration 无关。
- **但我承认补丁 Q2 暴露了一个双审没写明的事**：在 R_G^F 的判别性（band-适用）层面，B 的证据比 C 强；在保真 margin 的适用性层面，C-balloon2 比 B 强，C-pt1 和 B 都存疑。这意味着**双审 observation 1"四格全在带外"在 C 上是 calibration-存疑的**，应该降级为"四格方向一致，B 两格 band-适用判别性成立，C 两格 band 错配仅方向性成立"。这个降级不改变任何分支判决（单 seed 不下分支），但它应该写进 limitation。
- **这不构成"反过来 B 主 C 副"的理由**。codex 当初主张 B 主是因果 exogeneity 论证，不是 calibration 论证。如果现在用 calibration 论证翻成 B 主，等于换了一个论据支持 codex 原结论——但 codex 原结论（B 主）的真正问题是 estimand 偏离（0cm 压住通道），calibration 干净修不了 estimand 偏离。所以**B 在 calibration 上更可信，但在 estimand 上仍然偏；C 在 estimand 上对，在 calibration 上偏**。这是两个轴的 trade-off，不是一个轴的翻转。

**对用户问题的直接回答**：补丁 Q2 的 regime 错配论点**不会让我把 C 主 B 副翻成 B 主 C 副**。但它**会让我在 limitation 里加一条**：R_G^F 的 equivalence band 源自 14.5dB regime，C 臂在 21-24dB regime 下 band 适用性存疑，C 的"带外判别性"应降级为"方向性"。同时保真 margin 的 null sd 源自 21dB regime（不是补丁说的 14.5dB），C-balloon2 适用、C-pt1 和 B 都存疑。这两条 calibration caveat 是双审漏写的，补丁抓到了方向但归因有误。

---

## Q3 — 9dB regime 跳变是否是 codex/hermes "B/C 测不同东西"的更强证据？是否进一步坐实"停手写 limitation"？

**裁决：是更强证据，但"更强"是程度词不是定性词。双审已经判"测不同东西"并判"停手写 limitation"，9dB 跳变是把双审用的 4.3×（G_prune 绝对值跳变）证据从 map-size 轴延伸到 fidelity 轴。它不是新证据，是同一结论的第二轴佐证。坐实程度：边际增加，不改变判决。**

具体对抗：

- 双审 hermes readout Q4 的核心证据是 **G_prune 跨 variant 4.3× 跳变**（C-pt1 56915 vs B-pt1 13258）。这是 map-size 轴。
- 补丁的 9dB 跳变是 **vac_psnr 跨 variant 跳变**（C-pt1 24.4 vs B-pt1 15.0）。这是 fidelity 轴。
- 两个轴同时跳变，且跳变方向一致（B 整体 PSNR 低 ~9dB、B 的 G 也小 ~4.3× on pt1），说明 B 和 C 不是"同 estimand 不同 extremity"而是"不同 regime 下的不同 mapping 动力学"。这**确实比单一轴的 4.3× 更强**，因为单轴跳变可能被解释为"prune 机制对位姿质量的敏感度"，双轴同向跳变说明是**整个 mapping regime 平移**。

但——这是关键——**双审已经用 4.3× 单轴证据下了"测不同东西"的判决**。补丁的 9dB 是把这个判决的证据基础从 1 轴扩到 2 轴，判决本身不变。所以 Q3 的答案是：**是更强证据，但不改变"停手写 limitation"的判决**——因为那个判决在双审时已经基于 4.3× 成立了。

补丁 Q3 隐含一个更强的主张：9dB 跳变可能让"停手写 limitation"从"最保守选项"变成"唯一选项"。我不这么看。双审 codex 的第一优先是"修 KF schedule 再跑"，hermes 的第一优先是"停手"。9dB 跳变不改变 KF schedule 修复的可行性判断——KF 冻结修的是 R_G^F 的 admission-efficiency 纯度，修不了 B/C 的 regime 错配。所以即使 KF 冻结做完了，B/C 测不同东西的问题仍在。**9dB 跳变反而削弱了"修 KF 再跑"的价值**——因为修 KF 后你得到的仍然是一个 14.5dB regime（B）和一个 21-24dB regime（C）的对比，band/margin 适用性问题仍在。这**边际支持 hermes 的"停手"优先于 codex 的"修 KF"**，但双审综合已经把"停手"列为第一优先（synthesis §4），所以仍然是程度加强不是判决翻转。

---

## Q4 — vacated vs non-vacated sign 翻转是否意味着 vacated guardrail 在 frozen-pose 下不再是 arm-discriminating 量？

**裁决：是。但这个结论双审已经隐含了，补丁把它显式化了。vacated guardrail 在当前装置下不是 arm-discriminating 量，但它本来就不是 primary observable——R_G^F 才是。所以 Q4 的杀伤力有限。**

核对补丁的 sign 翻转表（我用原始 CSV 重算确认）：

- C-pt1 vacated: deferred depth 更差 (+2.423)；non-vacated static_psnr: deferred 更好 (24.31 vs 23.72，但注意这是 nonvacated_psnr 不是 static_psnr，补丁第三列标签有误——见下)
- B-pt1 vacated: deferred depth 更好 (−1.317)；non-vacated: deferred psnr 更好
- B-balloon2 vacated psnr: prune 更好 (+0.252，即 deferred 更差)

补丁第三列标 "static_psnr(non-vac)" 但填的是 `static_psnr`（整图均值）。真正的 `static_nonvacated_psnr` 是：C-pt1 prune 23.72 / deferred 24.31；C-balloon2 prune 28.08 / deferred 28.19；B-pt1 prune 18.06 / deferred 18.36；B-balloon2 prune 21.54 / deferred 21.25。用真正的 nonvacated_psnr 看，sign 模式是：C-pt1 deferred 更好(+0.59)、C-balloon2 deferred 更好(+0.11)、B-pt1 deferred 更好(+0.30)、B-balloon2 prune 更好(−0.30)。**vacated 和 non-vacated 的 sign 确实不一致**（C-pt1 vacated deferred 差、nonvacated deferred 好；B-balloon2 vacated deferred 差、nonvacated deferred 差——这个一致）。

补丁的 sign 翻转论点在 C-pt1 上成立（vacated 差 / nonvacated 好），在 B-balloon2 上不成立（两者都 deferred 差）。所以"四象限乱跳"是夸大——**是 1-2 格翻转，不是 4 格**。但 1-2 格翻转已经够说明问题：vacated guardrail 的 sign 不稳定。

对抗性结论：

1. **vacated guardrail 确实不是 arm-discriminating 量**——但这个结论 codex 双审 readout Q5 已经隐含了（codex 说"don't call C-pt1 a benefit or a trade verdict"，理由就是保真差不稳定）。hermes 双审 readout Q5 也写了"breach 是负面信号"但没下"vacated 不是 arm-discriminating"的强结论。补丁把这个隐含结论显式化，是对的。
2. **但这不影响 primary observable**。R_G^F（G-count ratio）是 primary，vacated guardrail 是 secondary。双审的整个判决链建立在 R_G^F + KF schedule 上，不建立在 vacated guardrail 上。vacated guardrail 失效只影响"C-pt1 depth breach 怎么写"这一个子问题，不影响"H-D 是否 INDETERMINATE"。
3. **codex 原判"vacated 是唯一 calibrated-usable contrast"**——这个判词需要修正。如果 vacated sign 都不稳，它不是 calibrated-usable。但 codex 那句原话的上下文是针对 R2-P02-E2 的 ghost metric 讨论，不是针对 P2-SF。在 P2-SF 的 frozen-pose 下，vacated 的 calibration 来源（0.28/1.56 的 null sd）本身就有 regime 适用性问题（Q1），所以"vacated 是 calibrated-usable"在 P2-SF 下**本来就不成立**。补丁 Q4 是把这个本就不成立的判词正式埋了。

**一句话**：Q4 成立但杀伤有限。vacated guardrail 在 P2-SF 下不是 arm-discriminating 量，但它不是 primary，双审判决不依赖它。补丁把 codex 的"vacated 是唯一 calibrated-usable contrast"正式修正掉，是对的。

---

## 综合给用户的可执行结论

1. **Q2 不翻转 C 主 B 副**。C 主的理由是 estimand 真实性（11cm 是自跟踪真实 regime），B 副的理由是 0cm 是 regime shift。补丁的 regime 错配论点是 calibration 层面（band/margin 适用性），和 estimand 层面是两个轴，不互斥。但补丁暴露了双审漏写的 calibration caveat，应该补进 limitation。

2. **补丁 Q1/Q2 的 regime 归属有误**：0.28/1.56 的 null sd 源自 E2 的 ~21dB replicate（`r2_p02_e2.md` §8.1），不是 14.5dB 的 SWEEP/DECOMP。equivalence band 0.0629 才源自 14.5dB。补丁把两个边界混成一个"14.5dB regime"是逻辑错误，但结论方向（C 的 band 适用性存疑）成立。

3. **补丁第三列标签有误**：标 "static_psnr(non-vac)" 但填的是 `static_psnr`（整图均值）。真正的 `static_nonvacated_psnr` 不同。这不影响 9dB regime 跳变的结论（整图和 vacated 都跳 9dB），但影响 Q4 的 sign 翻转表——实际是 1-2 格翻转不是 4 格。

4. **9dB 跳变（Q3）是双审"测不同东西"判决的第二轴佐证，边际加强但不改变"停手写 limitation"判决**。它反而削弱了"修 KF 再跑"的价值（因为 KF 冻结修不了 regime 错配），边际支持 hermes"停手"优先于 codex"修 KF"。

5. **vacated guardrail（Q4）在 P2-SF 下不是 arm-discriminating 量**，但它不是 primary，不影响 H-D 判决。codex"vacated 是唯一 calibrated-usable contrast"在 P2-SF 下应正式撤回。

6. **双审的 7 条 limitation 应该加 2 条 calibration caveat**：
   - R_G^F equivalence band（0.0629）源自 14.5dB regime（balloon+RGD），C 臂在 21-24dB regime 下 band 适用性存疑，C 的"带外判别性"降级为"方向性"；B 在 15dB 接近源 regime，band 适用性较好。
   - 保真 margin（0.28/1.56）的 null sd 源自 ~21dB regime（E2 replicate），C-balloon2（21.5dB）适用、C-pt1（24.4dB）偏高、B（15dB）偏低，C-pt1 depth breach 在 24dB-regime null sd 实测前判 indeterminate。

7. **H-D 仍 INDETERMINATE，本对照未 weaken 也未 upgrade**。这个判决不变。

8. **不发起 `--phase full`**。这个判决不变。补丁的 4 个问题都不构成补 seed 的理由——它们全是装置级/calibration 级问题，补 seed 修不了。

没有改任何文件。以上均为复审意见。
