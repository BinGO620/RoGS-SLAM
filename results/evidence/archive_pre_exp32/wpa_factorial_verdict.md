# WP-A 三因子全因子 —— 3-seed 正式判决（2026-08-14，exp-v3-18）

> **预注册判据冻结**（`results/evidence/wpa_factorial_prereg.md`，commit `bee241a`）。
> 120/120 完成，`wpa.done` `ALL_DONE ... missing=0`，全 5 序列 completion = 1.00（trj 100% ≥95% 闸），
> 每 cell k=3，分割只在共同完成 seed，分母固定 5。
> 本判决 = 可复现的描述性证据（3-seed/序列 ⇒ 逐序列 CI 弱，不作统计等价声称）。

## 一、判定（按 A5→A3→A1→A2→A4 顺序）

| 分支 | 条件 | 实测 | 判定 |
|---|---|---|---|
| **A5 负交互** | 某 Δ 在 ≥2/5 判负 | Δ_K 负仅 balloon（1/5）；Δ_R/Δ_L 无负 | ❌ 不触发 |
| **A3 单因子主导/加性** | 某单因子 ≥70% G(K1R1L1) 于 ≥3/5；或三 Δ 全 ≈0 | 无单一因子主导；三 Δ 不全 ≈0 | ❌ 不触发 |
| **A1 局部不可约** | 同序列 Δ_K/R/L 三者全正 ≥4/5 | **0/5 序列三者全正**（easy 上 R≈zero、balloon/pt1 上 K 负/混合） | ❌ 不触发 |
| **A2 部分冗余** | 某 Δ 在 ≥3/5 判 ≈0 | **Δ_R 在 3/5 判 zero（mv_no_box / mv_no_box2 / pt2）** | ✅ **触发** |
| **A4 序列依赖** | 分支跨序列不一致 | K(+,+,+,−,混合)/R(zero,zero,zero,+,+)/L(mix,mix,+ ,+,mix) 高度不一致 | （A2 已触发；A4 同时为真，作次要叙事） |

## 二、分支 = **A2-partial-redundant**（R 在 3/5 冗余）

**核心结论**：三组件**不是**"在完整配置处联合不可约"。**RobustTracking（huber）在 easy/medium 的
3 个序列（mv_no_box / mv_no_box2 / pt2）上是冗余的**——去掉它 ATE 基本不变（Δ_R≈0）。因此
**"R1 组件冗余指控"未被 A1 驳回**：完整配置的胜出不完全来自三组件的"协同"，R 在多数序列可省。

## 三、完整边际（k=3，mean±sd of per-seed log-ratio；正 = 去掉组件要退化）

| seq | Δ_K | Δ_R | Δ_L |
|---|---|---|---|
| mv_no_box（纯物·easy） | **+0.25** pos | 0.03 zero | 0.16 mixed |
| mv_no_box2（纯物·easy） | **+0.59** pos | −0.01 zero | 0.13 mixed |
| pt2（纯人·medium） | **+0.72** pos | −0.01 zero | **+0.17** pos |
| balloon（混合·medium） | **−0.18** neg | **+0.78** pos | **+0.29** pos |
| pt1（难人·hard） | −0.20 mixed | **+0.41** pos | 0.11 mixed |

L1/L2/L3 全表 + 8 格数值：`results/evidence/wpa_factorial_readout.{md,json}`（remote）。

## 四、诚实叙事（对论文的直接后果）

1. **"三组件联合必要"不成立** → 不能写 integration/system-design 贡献（C2）。
2. **K（dense-KF）是唯一在 easy 上不可约的杠杆**（3/5 同号正 +0.25/+0.59/+0.72），
   **但在 balloon（混合 mover）上有害**（Δ_K=−0.18，去掉更好）——dense-KF 的收益仅限纯物/纯人 regime。
3. **R（huber）在 easy/medium 冗余**（3/5 zero），**但在 balloon/pt1（难/mixed）不可约**（+0.78/+0.41）——
   R 的必要性随任务难度上升。**这实际推翻了"R 冗余"的单纯读法：R 是高难度 regime 的守卫**。
4. **L（Reliability）跨序列最稳的正向**（mv/mv2 mixed 但失衡，pt2/balloon positive）——
   L 是唯一在所有序列都不为负的组件，支持保留。
5. **因此"必要的组件集合"是 regime 依赖的**：
   - easy/medium：**{K} 必要、（L 次之）、R 冗余**；
   - 难/mixed（balloon/pt1）：**{R, 可能 L} 必要、K 有害/中性**。
   这正是 **A4 序列依赖**与 A2 部分冗余同时成立 —— 没有单一子集在所有 regime 都必要。

## 五、对写作的意义（WP-E 待落）

- **R1 的处置**：不是"协同成立驳回冗余"，而是"**组件非全局必要，但存在 regime 依赖的必要性**——
  不同任务难度下不同子集必要"。这本身是**有信息量的机制发现**，可写成 A4 序列依赖的
  **empirical 机制刻画**（不是"我们错了"，是"适用域必须按难度分层"）。
- 与既有 P6/P-B 一致：mv_no_box 上 bundle 组合冗余（R 可省）、balloon 上 mask/鲁棒主导（K 反而伤）。
- **必须落的分支命运**（执行卡 §4）：
  - 若走 **A4** → `empirical-study` 叙事（"mask-free 基线 + 设计启示 / 适用域难度分层"）；
  - 若坚持方法稿 → 主张收窄为"**dense-KF 在纯物/纯人 easy regime 的必要内核 + 难度依赖的 RobustTracking 守卫**"，
    并**不得**声称三组件联合必要。
- **禁止写**：超加性协同、三组件不可分整体、integrated necessary design（A1 不成立）。

## 六、残留风险（写进 limitation）

1. pt1 full 36.6 vs 骨架 44.0（**完整配置也救不回难 person**）——mask-free 在难 person 上仍是边界，
   K1R1L1 不显著优于 K0R0L0（Δ_K −0.20 mixed）。
2. 5 序列基于已知非 catastrophic 挑选，作用域限"本研究这 5 序列"，不外推 walking/crowd。
3. 3-seed 逐序列 CI 弱，结论为描述性证据。

## 可复核来源
- 完整数值：remote `results/evidence/wpa_factorial_readout.{md,json}`（120/120）
- 预注册：`results/evidence/wpa_factorial_prereg.md`
- 进度 screen：`results/evidence/wpa_factorial_screen_seed0_progress.md`
- 装置 codex 审查：`results/evidence/consult_codex_wpa_apparatus.md`
