# 预注册：frozen-pose pt1 de-confounding control（map-level，2026-08-02）

> **状态**：探索性、前瞻性、机制性对照（mechanistic control on seen data）。
> **不是**主表臂，**不是** H-D 的确认实验，**不能**升级 H-D（只能 weaken / leave-unchanged）。
> 生成日期：2026-08-02（P2-T 36/36 即将完成、任何 frozen-pose GPU run 之前）。
> 由 codex + hermes 双审查设计（`consult_synthesis_frozenpose.md`）。
> GO/KILL + 叙事 = 用户保留。

## 0. 这是什么，以及它刻意不是什么

hermes 在 P2-T readout 审查中打出盲点：coverage 与 **tracking difficulty** 共线（prereg §6.1 只列了 class-composition 共线）。pt1/pt2 既是高覆盖纯人序列，**又是 hard-tracking 序列**（长快速人体运动，MonoGS 3090 baseline 自己就接近 tracking 极限）。当 backbone 接近 tracking 极限时，**任何** lifecycle 扰动都会 cost ATE——与 mask 覆盖无关。

⇒ H-D 机制故事（"mask 漏 ⇒ deferred 有动态可挡 ⇒ compactness"）与替代故事（"难跟踪 seq 对任何 lifecycle 变化都 ATE 脆 ⇒ deferred 在那 cost ATE 与 mask 无关"）在 n=6 自跟踪数据上预测**同一模式**，不可区分。

本对照用 **frozen-pose**（RGD published trajectory + backend cam-lr=0）移除 tracking 这个变量，隔离 map-level 的 arm 效应。

**它刻意不是什么**（codex + hermes 一致封堵）：

1. **不是 ATE 实验。** frozen-pose 下 ATE **按构造恒等**于两臂（`oracle_pose.py` + `slam_frontend.py:905`：`oracle_skip` 在 itr 0 置位，不触碰 `R_gt/T_gt`；R2-P01-E2 实测 balloon frozen-pose ATE 2.0618cm 到 4dp，两臂全 seed 全等）。**"deferred 是否仍 cost ATE under frozen pose" 的答案预定为零**——把它当 outcome 是 null 实验 + 类别错误（"cost 消失"既符合"tracking artifact"也符合"map-level 效应太小不足以在 pose 钉死时动 ATE"）。**ATE 在此是 canary（= injected-tracker ATE ±0.02，G1 gate），不是 outcome。**
2. **不是 H-D 确认。** n=1 单序列、map-level only。只能 **weaken 或 leave-unchanged** 自跟踪 H-D INDETERMINATE 判决，不能 confirm。
3. **不是独立验证。** pt1 是已见数据（P2-T 跑过）。标 "mechanistic control on seen data"。
4. **不是 coverage→ratio 因果证明。** surviving 的 map-level 对比只说明 lifecycle 在该 trajectory 下直接改变 mapping；**不**说明 mask coverage 导致该效应。

## 1. 正确的观测量（map-level，非 ATE）

| 量 | 角色 | 说明 |
|---|---|---|
| `refined_num_gaussians` (G_def/G_prune) | **PRIMARY** | compactness 对比是否在 pose-map feedback 关闭后存活？R2-P01-E2 已测 deferred 13/14 对更少高斯 |
| `static_vacated_depth_l1_pen_cm` | SECONDARY | 等 pose 下 deferred 是否降保真？R2-P01-E2 fidelity co-primary gate 未过（仅 pt2 4/4），所以这是真实 arm-discriminating 轴 |
| `static_vacated_psnr` | SECONDARY | 同上 |
| `ate_rmse_cm` | **CANARY（非 outcome）** | = injected-tracker ATE ±0.02；两臂按构造相等 |
| KF count + indices, VRAM/FPS, inserted/promoted/expired/pruned, static PSNR | 记录 | codex: frozen pose **不一定**冻结 DynamicKeyframe 决策；若 KF schedule 两臂不同，R_G^F 测的是总 lifecycle-induced mapping-policy 效应（含 coverage 改变），非纯 admission efficiency |

**保真边界 INHERITED（不 re-fit）**：import `r2_p03_sweep_readout` 的 1.56cm / 0.28dB（与 P2-T 同）。不在 pt1 frozen-pose 上定新边界 = post-hoc threshold fitting。

## 2. 注入轨迹审计（codex guardrail #6，跑前完成）

RGD pt1 `trj_final.json`：580 帧，injected-tracker ATE vs GT = **5.48 cm**。
- 这是**干净**轨迹，非 collapse（pt2 的 RGD 是 26.30cm）。codex guardrail 满足：差的固定轨迹会改变 mapping regime 而非"移除 tracking difficulty"。
- 注意：RGD 的 5.48cm **优于**我们自跟踪 pt1 prune ATE 10.97cm ⇒ frozen-pose pt1 maps 建在**更好**的 tracking regime 上。记为 regime caveat，**不**是 arm-pair 对比的混淆（两 frozen-pose 臂共享同一 5.48cm 轨迹）。

## 3. 三分支（跑前钉死，observables 按 §1，ATE 不当 outcome）

对 frozen-pose pt1（seed 0 screening；MAP-EFFECT/REVERSED ⇒ 补 3 seed）：

| 分支 | 条件 | 解读 |
|---|---|---|
| **MAP-EFFECT** | R_G^F 可判（\|r−1\| > 2× own_sd）**且** vac_depth 或 vac_psnr arm-discriminating（>1× own_sd，同号） | deferred 独立于 tracking 扰动 map ⇒ H-D 机制故事存活；自跟踪 ATE cost 可能部分 tracking-coupled，但 map-level 通道存在 |
| **NO-MAP-EFFECT** | R_G^F 落带内 **且** 两保真指标都在 own_sd 内 | deferred 的自跟踪 ATE cost 合理归因 tracking-coupled，非 map-level ⇒ H-D 机制故事**减弱**；报为 scoped limitation，**不**声称 map-level 机制 |
| **REVERSED** | R_G^F 可判 <1（deferred 更小）on pt1 under frozen pose | 与 pt1 自跟踪 indeterminate/>1 矛盾 ⇒ pt1 自跟踪 compactness 是 tracking-coupled，非 coverage 效应 |

**band 参照**：R2-P03 balloon frozen-pose CV ~7.8% ⇒ 2× own_sd band。单 seed 时无法估 own_sd → seed 0 只判方向 + 是否明显远离 1；判别性结果补 3 seed 后再下分支。

## 4. 预声明护栏（both reviewers）

1. **ATE = canary 非 outcome。** 在 prereg 里写明构造恒等事实。不报 frozen-pose ATE "差"——没有。任何人把"deferred ATE cost 在 frozen pose 消失"读成 H-D 证据 = §0 类别错误。
2. **单 seed = screening。** 显式："seed 0，不下判决；MAP-EFFECT/REVERSED 触发 ⇒ 3 seed 确认后才进论文。" 不让单 seed frozen-pose 覆盖 3-seed 自跟踪主表。
3. **保真边界 inherited 不 re-fit。** import 1.56cm/0.28dB。
4. **不从本实验单独升级 H-D。** 上限 = weaken / leave-unchanged。
5. **Provenance：** pt1 已见 = "mechanistic control on seen data"，非独立测试。
6. **审计注入轨迹**（§2，已完成：5.48cm，干净）。

## 5. 与叙事的关系

本对照**不取消**叙事 D′（lifecycle applicability-boundary measurement）。它给 H-D 的 tracking-difficulty 共线盲点一个**直接的机制性检验**：
- MAP-EFFECT ⇒ 边界有 map-level 通道，叙事 D′ 的 "lifecycle 直接改变 mapping" 站得住，可在 limitations 里写"tracking-difficulty 共线已用 frozen-pose 部分排除"。
- NO-MAP-EFFECT ⇒ 边界可能由 tracking 驱动，叙事 D′ 降为"sequence-dependent boundary，mask-coverage 只是 candidate stratifier，tracking-difficulty 共线未排除"。
- REVERSED ⇒ pt1 自跟踪方向是 tracking-coupled，H-D 在 pt1 上的支持进一步减弱。

## 6. 配置与合同

- `configs/rgbd/experiments/p2_render/p2fp_combined_{prune,deferred}_pt1.yaml`（mirror p2s_*_pt1 + Oracle.pose_file + cam_lr=0）
- `tests/test_p2fp_frozen_pose_configs.py`（5 tests：overlay-vs-selftracked 只差 injection+freeze / twin 只差 lifecycle / pose freeze real / pose_file 存在 / backbone blocks 等于自跟踪 twin）—— **全部 PASS 2026-08-02**
- 跑：`slam.py --config p2fp_combined_prune_pt1.yaml --eval --seed 0 --results-root results/runs/P2/P2-FP/pt1_prune_seed0`（deferred 同理），GPU gap 跑（不能与 SLAM 并发）
