# P2-SF seed-0 readout — codex + hermes 综合（2026-08-02）

> 输入：同一份 `consult_brief_p2sf_readout.md` packet 同时发 codex（MCP, gpt-5.5/high, read-only）
> 与 hermes（CLI, -t web,file,terminal）。原文见 `consult_codex_p2sf_readout.md` /
> `consult_hermes_p2sf_readout.md`。本文件是**我方综合**，不是任一审查者的原文。
> GO/KILL + 叙事 = 用户保留；本文件给推荐与数，不替用户决定。

## 0. 两审一致点（这是载荷所在）

两条独立审查在四个判决性问题上**完全收敛**，且互为补强：

1. **序列级共线盲点未解决**（双方一致）。pair 内位姿恒等关掉了 *within-pair* tracking-difficulty
   通道，但 pt1(hard+low-cov) × balloon2(easy+high-cov) 仍是 n=2 的共线设计，给不出
   "效应是否随 coverage/difficulty 变"的斜率。hermes 精确化了分歧口径：pair 内冻结解决了
   "pair 内差异是 tracking 还是 lifecycle"，没解决"为什么 pt1 比 balloon2 更极端"——后者正是
   H-D 的 stratifier 归因核心。
2. **§4.8 在 4/4 触发 ⇒ `R_G^F` 不是干净的 admission-efficiency 度量**（双方一致）。它是
   "admission policy × KF schedule"的联合效应，4/4 触发意味着**没有干净对照格**。
3. **~35% KF 预算下降切断（codex：大幅削弱；hermes：切断）与自跟踪主表的桥**。exact-ATE
   replay 只验证了**位姿注入**，没验证**实验等价**。C 不在自跟踪的 116/94 KF budget 上，
   而是 76/60（≈⅔），所以"frozen 0.794→0.362 是放大"是 apples-to-oranges。
4. **per-KF "explains X%" 数字要删**（双方一致）。它依赖"G 与 KF 线性、KF 可交换"的未验证
   假设；G/KF 在 C-pt1=749 vs C-balloon2=406（差 1.85×）证明该假设不成立。它是**有方向指示、
   无定量意义**的描述统计。

⇒ **两审对 Q6 的排序一致**：
1. **就此停手写成 limitation**（hermes 第一优先；codex 第二优先＝"若 KF 冻结不可行则停手"）
2. 修 KF schedule 再跑（codex 第一优先；hermes 第二优先）
3. **`--phase full` 直接补 seed 1-2 = 最差选项**（双方一致：补 seed 只缩置信区间，修不了
   任何装置级裂缝；"稳定地测了一个受污染的量"不增加叙事力）

**关键：codex 明说"I would not authorize `--phase full` as currently configured"**；hermes
明说"不值得 4.3h"。

## 1. 两审分歧点（精确化，不是推翻）

| 点 | hermes | codex | 能了断的证据 |
|---|---|---|---|
| amplification 解读 | 不 license tracker-orthogonal 通道；KF-budget 替代账户**同向预测**放大 | 列了 6 个替代账户（含非线性增长、endogenous KF 放大、denominator effects），同向预测 | **冻结 KF indices 重跑**：若 amplification 仍在→codex 偏乐观对；若塌回 1 附近→hermes 对 |
| B/C rank reversal | "测不同东西"（pt1 绝对值 4.3× 跳变 + 秩翻转） | "regime 依赖/不可迁移"，撤回"disagreement=partial mediation" | intermediate-pose variant（hermes：provenance 问题使实践不可行⇒只能成 limitation） |
| 补 seed 判断分歧 | 是判断分歧（不值得） | 可能更倾向确认方向 | 无——非事实分歧 |

**双方都不认为分歧能在 08-04 叙事门前了断**。hermes 的判词："停手写 limitation，除非 KF
冻结在 08-04 前能做完——后者做不到就别补 seed。"

## 2. 措辞审计：需要删/改的具体句子（双方点名）

两审都判 brief 的措辞**在往 upgrade 滑**，尽管反复声明 §4.4 上限。需删/改：

| 句子 | 问题 | 处置 |
|---|---|---|
| "P2-SF is the de-confounding control: ... so any surviving map-level difference cannot come from the arms tracking differently." | 读者会外推到序列级 | 加限定：**within-pair**；序列级共线 n=2 未解决 |
| "Under frozen pose the contrast strengthens rather than collapsing toward 1." | 跨 KF budget 比较＝apples-to-oranges；隐含 upgrade 推理 | **删** "strengthens"/"collapses"，改纯描述："remains below 1 in all 4 cells ... at reduced KF budgets, not directly comparable to self-tracked R_G" |
| "A pure 'compactness is a tracking-difficulty artifact' account predicts attenuation." | 该预测依赖"冻结位姿不动其它"的不变性假设，而 35% KF 下降直接违背它 | 改为"attenuation 预测在两个不可分账户（tracker-orthogonal vs KF-budget）下都未成立；数据无法区分二者" |
| "All 4 cells <1 and outside the band; agree in sign with self-tracked." | sign 一致跨 budget 不等于机制一致；band 来自另一 regime 非本 setup 的 null | 保留事实，删 sign 比较，或显式标注"sign agreement across different KF budgets is not mechanistically informative" |
| "KF gap explains 10%/7%/25%/1% of the distance from 1." | 依赖未验证线性假设 | **删**；limitation 写"per-KF 归一给方向性 bound 但依赖未验证线性假设" |
| "Only one guardrail breach in 8 comparisons." | 错误分母（按 metric 轴而非 pair 计数） | 改"1 of 4 paired cells breached；B-balloon2 PSNR 逼近 margin" |
| prereg §6 "CONCORDANT MAP-EFFECT ⇒ ... 'lifecycle 直接改变 mapping' 站得住" | 接近 upgrade | 预注册已 frozen 不改，但**叙事不得引用"站得住"措辞**，须用 synthesis §1 的更弱版本 |

## 3. 我方综合结论（ceiling-compliant，两审背书）

> The seed-0 screen does not falsify a lifecycle-associated map-size difference under
> shared pose input. Because keyframe schedules diverged on all four pairs, mapping budgets
> dropped ~35% versus self-tracked, one fidelity margin was breached, and only one seed was
> run, the control does **not** isolate admission efficiency and does **not** resolve the
> sequence-level coverage/tracking-difficulty collinearity. **H-D remains INDETERMINATE —
> neither weakened nor upgraded.** (codex 原话综合 + hermes 最终建议 #7)

**estimand 收窄为**：在 prune-conditioned、低 KF 预算的 frozen replay 下，seed 0 显示同向的
lifecycle-associated map-size 差异。这是**对原始盲点的部分回应**（pair 内 tracking 通道关掉），
不是解决（序列级共线 + KF schedule 未冻结 + 预算降 35% + B/C 测不同东西 四道结构性裂缝）。

## 4. 给用户的推荐（不替用户决定）

**推荐 = 停手写 limitation，不上 `--phase full`。** 理由：

- 两审一致把"补 seed"列末位，codex 明确拒绝授权 `--phase full` as configured。
- 4 道结构性裂缝全是装置级，补 seed 一个都修不了。
- 4.3h GPU 在 08-04 叙事门 / 08-06 写作硬启动前的时间机会成本高；花在 limitation 文字上比花
  在 seed 1-2 上对论文更有利（hermes）。
- 即使 KF indices 冻结工程上可行（未验证），它需要改 `slam.py`/`slam_frontend.py` 的 keyframe
  逻辑 + 自己的预注册，**几乎肯定超 08-04 叙事门**（hermes）。若用户判断窗口允许，可作为
  **下一篇**的干净装置，不进本篇。

**本篇 limitation 该写的 7 条**（hermes 最终建议，两审背书）：
1. pair 内冻结位姿，关掉 within-pair tracking-difficulty 通道＝对原始盲点的部分回应；
2. 序列级 coverage-vs-difficulty 共线（n=2）未解决；
3. KF schedule 未冻结（§4.8 4/4 触发），R_G^F 是 mapping-policy 联合效应非纯 admission；
4. frozen KF 预算降 ~35%，frozen-pose R_G^F 与自跟踪 R_G 不在同一 budget，不可直接比较；
5. B/C rank reversal + pt1 绝对值 4.3× 跳变 ⇒ B 可能测不同 estimand，B 作 sensitivity 的前提不成立；
6. C-pt1 depth breach 出现在 hard-tracking 序列上，与 tracking-difficulty 通道预测一致，未冻结 KF 前不解读机制；
7. H-D 维持 INDETERMINATE，本对照未 weaken 也未 upgrade。

## 5. 我将据此执行（用户已开自动模式）

1. 把上述 7 条 limitation + 收窄后的 estimand 写进 `p2sf_selffrozen_outcome.md` §5/§7（填回预留空位）；
2. 按表 §2 删/改 brief 与 readout 里的越界措辞（**不改预注册 §1–§7 frozen 文本**，只改 readout
   输出与 outcome 文件散文）；
3. 同步 HANDOFF / 02-method / 03-results / registry / memory；
4. commit + push；
5. **不发起 `--phase full`**；runner `_extract` 缺陷留到 campaign 收工后修（装置维护，不动判据）。

---

# 第二轮：regime-patch 复审（2026-08-02，双审收回后数据核对新发现）

> 输入 = `consult_brief_p2sf_regime_patch.md`（4 问）。原文
> `consult_codex_p2sf_regime_patch.md`（codex 结果存于 MCP thread `019fc292-…`，全文
> 已录入本节）与 `consult_hermes_p2sf_regime_patch.md`。触发 = 第一轮 packet 只给了
> 两臂 Δ、没给跨 variant 绝对值；核对时发现 vac_psnr 绝对值 B/C 之间差 ~9dB。

## 6. 我方补丁的两处错误（两审独立抓到，已接受）

1. **provenance 混淆（承重）**：补丁把"继承边界源自 14.5dB regime"当前提——**错**。
   两条边界来源不同：
   - **保真 margin（1.56cm/0.28dB）** = E2 的 **7 个 balloon replicate（~21dB regime）** 的
     1× null sd（`r2_p02_e2_metric_calibration.txt:13-14`：depth mean 23.425/sd 1.559；
     psnr mean 21.103/sd 0.278）。⇒ **C-balloon2（21.5dB）落在源 regime，B（15dB）离最远**
     ——与补丁 Q2 前提正好相反。
   - **equivalence band（0.0629）** = SWEEP/DECOMP/MASKRATE 三个 **14.5dB** campaign 的
     paired ratio sd。⇒ **B（15dB）落在源 regime，C（21-24dB）错配**。
   - 补丁把两个边界混成一个"14.5dB"论证 B 更适用 = 逻辑错误（hermes 指名）。
2. **"四象限 sign 乱跳"夸大**：两审各自用原始 CSV 重算——实际是 **1–2 格 region
   reversal**（C-pt1 vacated 差/nonvacated 好；B-balloon2 两区一致 deferred 差），不是
   4 格系统翻转。补丁第三列还标错（填 `static_psnr` 整图均值、标成 non-vacated）。

## 7. 第二轮四问裁决（两审一致）

| 问 | 裁决 |
|---|---|
| Q1 C-pt1 +2.423 breach？ | **indeterminate-breach**：机械上是（预注册规则写死 1.56，不得事后换阈值叫"假 breach"），但校准有效性未知（单 seed 无 C-specific null sd；PSNR 均值变化≠方差迁移；hermes 定性推断 24dB 下 1.56 可能偏松 ⇒ 更可能真 breach，但无实测）。写成"预注册边界超出 + 校准迁移未知"。 |
| Q2 B 升主？ | **不升**。codex：B 只匹配一个标量均值，pose/KF/lifecycle/map-scale 全不同 = calibration by coincidence；B 不能校准、解释、或推翻 C；**两 variant 可比性同时降级**。hermes：calibration 与 estimand 是**两个轴**——C estimand 对（11cm 真实 regime）calibration 存疑，B calibration（对 band）好 estimand 偏（0cm 压通道）；C 主 B 副是 estimand 轴的裁决，不被 calibration 轴翻转。 |
| Q3 9dB 强化"测不同东西"？ | **是（9dB≈8× MSE，比 G 的 4.3× 更强），且是第二轴佐证**（map-size 轴 + fidelity 轴同向跳变 = 整个 mapping regime 平移）。但 codex：不是"位姿质量单独"，是 **pose-regime × mapping-policy 交互**。hermes：还**削弱了"修 KF 再跑"的价值**（KF 冻结修不了 regime 错配）⇒ 边际支持"停手"优先于"修 KF"。判决不变。 |
| Q4 vacated 还 arm-discriminating？ | **在 P2-SF 下不是**（C-pt1 一处 region reversal 已够证明 raw vacated PSNR 非全图保真稳定 proxy），但它非 primary，不影响 H-D 判决。**codex 旧判"vacated 是唯一 calibrated-usable contrast"在 P2-SF 语境下正式撤回**（hermes 主张，codex 自己也降级为"可作预注册描述 guardrail / 未校准 equivalence / 非机制证据"）。 |

## 8. hermes 的新增发现（第一轮双审漏写、本轮补上）

**R_G^F 判别性的 band 适用性在 B/C 间不对称**：equivalence band 源自 14.5dB regime ⇒
B 两格（15dB）的"带外"判别 **calibration-干净**；C 两格（21-24dB）的"带外"判别
**calibration-存疑**，应降级为"方向性"。⇒ 第一轮 observation 1"四格全在带外"须改写为：
"四格方向一致；B 两格 band-适用判别性成立；C 两格 band 错配、仅方向性成立"。
（这不翻转 C 主 B 副——见 Q2 两轴论——但必须进 limitation。）

## 9. 最终 limitation 清单（7 + 2 = 9 条，两轮四审背书）

第一轮 7 条（§4）不变，追加：

8. **R_G^F equivalence band（0.0629）源自 14.5dB regime（balloon+RGD+rtoff）**：C 臂
   （21-24dB）band 适用性存疑 ⇒ C 的"带外判别性"降级为"方向性"；B（15dB）band 适用较好。
9. **保真 margin（1.56cm/0.28dB）的 null sd 源自 ~21dB regime（E2 7-replicate）**：
   C-balloon2（21.5dB）适用、C-pt1（24.4dB）偏高、B（15dB）偏低；C-pt1 depth breach 在
   24dB-regime null sd 实测前判 **indeterminate-breach**。

## 10. 判决汇总（两轮四审全一致，无翻转）

- **H-D 维持 INDETERMINATE**——未 weaken 未 upgrade（§4.4 上限守住）。
- **不下 P2-SF 分支**（单 seed screening）。
- **不跑 `--phase full`**（两轮四审全拒绝：补 seed 修不了装置级/calibration 级裂缝）。
- **C 主 B 副不翻转**（estimand 轴裁决；B 的 calibration 优势是另一个轴，记入 limitation #8）。
- **B/C = 不可通约的受控 regime**（noncommensurate controlled regimes，codex 措辞）——
  B 不再当 C 的定量 sensitivity 写，只作 regime-extremity 存在性旁证。
- 下一篇的干净装置需求：**matched KF schedules + regime-specific repeated null controls +
  预先指定的 pose-error 梯度**（codex），且须意识到 KF 冻结修不了 B/C regime 错配（hermes）。
