# P2-SF self-frozen de-confounding control — seed-0 outcome

> **状态**：screening（单 seed），**未下分支判决，campaign 已收工（不跑 `--phase full`）**。
> 预注册 `p2sf_selffrozen_prereg.md`（§1–§7 跑前冻结，§8 = 跑中 addendum，写于 1/8 run 时）。
> 判据 = §3 逐条转写，保真边界 **import 不 re-fit**。
> **上限（§4.4，硬）**：本对照只能 **weaken / leave-unchanged** H-D 的 INDETERMINATE，**永不能 upgrade**。
> **§5b/§7 = 定稿**（两轮四审：readout 双审 + regime-patch 复审，共 4 份审查 + 2 份综合）。
> GO/KILL 与叙事 = 用户保留；"停手写 limitation、不跑 `--phase full`" = 两轮四审一致**推荐**，
> **待用户最终确认**（本文件按推荐路线归档，若用户改判则本节按新决定修订）。

## 1. 跑了什么

8 run（pt1 + balloon2 × {C, B} × {prune, deferred} × seed 0），2026-08-02 11:01:34 → 13:08:10，
**8/8 exit 0**，~16 min/run（共 ~2.1h，快于预算的 ~4h）。装置 commit `98b80ac`，
readout `46bbf42` / `1ee0631` / `694429d`。原始 `results/runs/P2/P2-SF/`。

- **variant C（主判分支）**：两臂都注入**自家 prune 臂**的自跟踪轨迹（`trj_full_final.json`），
  完全对称，只差 `lifecycle_mode`。保留真实 ~11cm regime。
- **variant B（sensitivity，非分支）**：两臂都用 dataset GT 冻结（`Oracle.gt_pose`）。

## 2. 装置闸门（全过）

- **注入 provenance gate = EXACT**：C-prune replay 逐位复现源 P2-T run 的全轨迹 ATE ——
  pt1 **11.0087 = 11.0087**、balloon2 **5.1265 = 5.1265**（4 dp）。
  **这正是被 abandon 的 RGD 借用轨迹路线永远过不了的那道闸**（1.11cm anchor 残差 / 无时间戳 /
  580-vs-583 帧）⇒ self-frozen 按设计绕开了 frame-correspondence 死结。
- **variant B 构造验证**：ATE **0.0**、std 0.0、RPE 0.0、path_length_ratio 恰好 100.0。
  即 hermes 预警的 **0cm 完美跟踪 regime shift** 如实出现。
- **ATE canary 两臂逐 run 恒等**（C 下 = prune 自跟踪 ATE；B 下 = 0）⇒ 按构造，**报而不判**。

## 3. 主结果表（seed 0，`R_G^F = G_def/G_prune`；guardrail 正号 = deferred 更差）

| variant | seq | G_prune | G_def | **R_G^F** | per-KF 比* | vac_depth Δ (界 1.56) | vac_psnr Δ (界 0.28) | KF p/d |
|---|---|---|---|---|---|---|---|---|
| **C** 主 | pt1 | 56915 | 20592 | **0.3618** | 0.4230 | **+2.423 破界** | +0.083 界内 | 76/65 |
| **C** 主 | balloon2 | 24381 | 13833 | **0.5674** | 0.5972 | +0.188 界内 | +0.185 界内 | 60/57 |
| **B** 副 | pt1 | 13258 | 9766 | **0.7366** | 0.8024 | −1.317 界内 | −0.135 界内 | 61/56 |
| **B** 副 | balloon2 | 26427 | 7440 | **0.2815** | 0.2920 | +0.063 界内 | +0.252 界内 | 56/54 |

\* per-KF 比 = (G_def/KF_def)/(G_prune/KF_prune)。**DESCRIPTIVE / post-hoc / 非预注册**，
仅用于给 §4.8 混淆定量上界（与 S6REPL §4.4 同等地位：可作描述，**不得写成判决**）。
KF 差分别解释了距 1 的 **10% / 7% / 25% / 1%**。

**自跟踪对照量**（3-seed 主表）：pt1 `R_G` = **0.794**；balloon2 `R_G` = **0.910（INDETERMINATE）**。
序列属性：pt1 = hard-tracking、mask 覆盖 29.9%；balloon2 = easy-tracking、mask 覆盖 59.4%。

**equivalence band（§8.1 跑前钉死）**：pooled sd_log = **0.0629** ⇒ ±1sd = ratio **[0.9390, 1.0649]**。
**四格全部落在带外。**

## 4. 候选账本 + 关键帧

| cell | promoted (prune/def) | commit_queued (def) |
|---|---|---|
| C-pt1 | 203 / 171 | 168 |
| C-balloon2 | 163 / 155 | 153 |
| B-pt1 | 53 / 43 | 30 |
| B-balloon2 | 71 / 54 | 41 |

- **§4.8 ambiguity trigger 四格全触发**，且 **deferred 臂关键帧一律更少**
  ⇒ `R_G^F` 测的是**总 lifecycle mapping-policy 效应，不是纯 admission efficiency**。
- **冻结位姿不冻结关键帧选择**：exact-pose replay 下 KF 仍从 **116→76**（pt1）、**94→60**（balloon2）
  ≈ **−35%** ⇒ variant C 是在自跟踪约 **⅔ 的 mapping 预算**上测这个对比。

## 5a. 双审前的原始观察记录（**已被审查修订，仅存档**；定稿解读见 §5b）

> ⚠ 本节是双审**前**写下的观察清单，其中 4 条措辞被两轮四审点名修订（就地标注，不删除）。
> **引用本实验一律引 §5b，不得引本节原文。**

1. ~~**四格全 <1 且全在带外**~~，四格方向都与自跟踪同号。
   **[修订]** band 源自 14.5dB regime ⇒ B 两格"带外"calibration-干净，C 两格降级为"方向性"；
   "sign 与自跟踪一致"跨 KF budget 无机制含义（codex）。
2. ~~冻结位姿下对比**变强而非收敛到 1**~~（pt1 0.794→0.362 C；balloon2 0.910→0.567 C、→0.282 B）。
   **[撤回措辞]** 跨 KF budget（116→76 / 94→60）的 apples-to-oranges 比较；"strengthens/
   collapses"字样作废（两审一致）。数字本身保留，仅作不同 budget 下的描述。
3. **两 variant 的序列排序翻转**：C 说 pt1 更极端（0.362 < 0.567），B 说 balloon2 更极端
   （0.282 < 0.737）。**[维持，且升级]** = B/C noncommensurate 的证据轴之一。
4. **pt1 上两 variant 的绝对图规模差 4.3×**（C-prune 56915 vs B-prune 13258），而 balloon2 相当。
   **[维持，且升级]** 第二轮又加 fidelity 轴：vac_psnr 跨 variant ~9dB（≈8× MSE）。
5. B 臂 lifecycle 活性显著更低（promoted 43–71 vs 155–203；commit_queued 30/41 vs 168/153）。
   **[维持]**
6. ~~8 次保真比较只有 1 处破界~~（C-pt1 depth +2.423）；B-balloon2 psnr +0.252 逼近 0.28。
   **[修订分母]** 正确表述 = **4 个配对格中 1 格破界**（codex：按 metric 轴计数会把 breach
   显得更稀有）。breach 本身判 indeterminate-breach（§5b.5）。
7. ~~**两序列形状不同**：C-pt1 = trade（compactness 收益 + 保真代价）；C-balloon2 = 干净收益~~。
   **[撤回措辞]** 不得把 breach 格与 clean 格并列为"两种合法 shape"（hermes）；不得称
   benefit/trade（codex）。中性表述见 §5b.5。

## 5b. 结构解读（两轮四审后定稿）

第一轮双审（`consult_{codex,hermes}_p2sf_readout.md`）+ 第二轮 regime-patch 复审
（`consult_{codex,hermes}_p2sf_regime_patch.md`）；综合 `consult_synthesis_p2sf_readout.md`。
**两轮四审在全部判决性问题上收敛，无翻转。**

1. **序列级共线盲点未解决。** pair 内位姿恒等关掉了 *within-pair* tracking 通道（真实、
   应记录），但 pt1(hard+low-cov)×balloon2(easy+high-cov) 仍是 n=2 共线设计，给不出
   "效应随 coverage/difficulty 变"的斜率——这正是 H-D 的 stratifier 归因核心。
2. **§4.8 在 4/4 触发 ⇒ `R_G^F` 是 mapping-policy 联合效应，非纯 admission efficiency。**
   没有干净对照格。per-KF 归一（§3 表）只有方向指示意义（G/KF 跨序列差 1.85× ⇒ 线性
   假设不成立），"explains X%" 措辞作废。
3. **~35% KF 预算下降切断与自跟踪主表的桥。** exact-ATE replay 验证的是**位姿注入**，
   不是**实验等价**。"0.794→0.362 = 放大"是跨 budget 的 apples-to-oranges，该措辞作废；
   改写为"四格均 <1、方向与自跟踪一致，但在降低 ~35% 的 KF 预算上测得，不可与自跟踪
   R_G 直接比较"。
4. **B/C = noncommensurate controlled regimes（不可通约的受控 regime）。** 证据两轴同向：
   G_prune 跨 variant 4.3×（pt1 56915 vs 13258）+ vac_psnr 跨 variant ~9dB（24.4 vs 15.0
   ≈ 8× MSE）。是 pose-regime × mapping-policy **交互**，不是位姿质量单独。B 不能校准、
   解释、或推翻 C；B 只作 regime-extremity 存在性旁证，不作定量 sensitivity。
   **C 主 B 副不翻转**（estimand 轴裁决；B 的 band-calibration 优势是另一轴，见 §5.6）。
5. **C-pt1 depth +2.423 = indeterminate-breach。** 机械上超预注册边界（1.56 写死，不得
   事后换阈值），但校准迁移未知（margin 的 null sd 源自 ~21dB E2 replicate，C-pt1 在
   24.4dB，无该 regime 实测 null sd）。既不写成"deferred 伤保真"也不开脱为假阳性。
   它出现在 hard-tracking 序列上、与 tracking-difficulty 通道预测一致（hermes）——
   KF 未冻结前不解读机制。
6. **两条 calibration caveat（第二轮新增，第一轮漏写）：**
   - equivalence band 0.0629 源自 14.5dB regime ⇒ **B 两格"带外"判别 calibration-干净，
     C 两格降级为"方向性"**；
   - 保真 margin 1.56/0.28 的 null sd 源自 ~21dB regime ⇒ C-balloon2（21.5dB）适用、
     C-pt1（24.4dB）偏高、B（15dB）偏低。
   ⇒ **C-balloon2 是四格中唯一"保真边界源 regime 适用"的格**，其两 guardrail 均在界内。
7. **vacated guardrail 在 P2-SF 下不是 arm-discriminating 量**（C-pt1 一处 region
   reversal 足证非全图保真稳定 proxy）；非 primary，不影响 H-D 判决。codex 旧判
   "vacated 是唯一 calibrated-usable contrast"在 P2-SF 语境正式撤回。

**收窄后的 estimand**：在 prune-conditioned、降低 ~35% KF 预算的 frozen replay 下，
seed 0 显示同方向的 lifecycle-associated map-size 差异。这是对 tracking-difficulty
共线盲点的**部分回应**（pair 内通道关闭），不是解决。

## 6. 已登记的装置缺陷（campaign 期间未改，收工后修）

`scripts/r2_p2_sf.py::_extract` 自写取数未 import 通用 `parse_run`，**四处错**（见 prereg §8.2）
⇒ `p2sf_results.jsonl` 的 metric 字段全空（`exit` 有效）。**run 完整性不受影响**，
`scripts/r2_p2_sf_readout.py` 已用 `parse_run` + `keyframe_count` 从 run 目录全量重算。
**runner 修复 = campaign 收工后的装置维护，不动任何判据。**

## 7. 判决（定稿，两轮四审背书）

- **不下分支**（§4.2 单 seed = screening）。四格判别性触发了 §7 的 `--phase full` 条件，
  但**两轮四审一致拒绝授权**（codex 原话 "I would not authorize `--phase full` as
  currently configured"；hermes "不值得 4.3h"；第二轮双双维持）：4 道结构性裂缝
  （序列级共线 / KF schedule / 预算桥接 / B-C regime 错配）全是装置级或 calibration 级，
  **补 seed 一个都修不了**。→ **`--phase full` 不跑，seed0 即收工。**
- **H-D 维持 INDETERMINATE——未 weaken 未 upgrade**（§4.4 上限守住）。
- **estimand 披露不变**："lifecycle effect when replaying a prune-generated trajectory"
  （prune-conditioned, post-treatment），并追加"at ~⅔ of the self-tracked KF budget"。
- **写作口径**：本对照进论文 = **limitation 一节 + 方向性佐证一句**，共 9 条 limitation
  （7 条第一轮 + 2 条 calibration caveat，全文见 `consult_synthesis_p2sf_readout.md` §9）。
  叙事 D′ 维持 "sequence-dependent boundary"；**不得引用** prereg §6 "站得住" 措辞、
  "strengthens/collapses"、per-KF "explains X%"、"8 comparisons 只 1 breach" 分母。
- **下一篇的干净装置需求**（不进本篇）：matched KF schedules + regime-specific repeated
  null controls + 预先指定 pose-error 梯度；且 KF 冻结修不了 B/C regime 错配。
