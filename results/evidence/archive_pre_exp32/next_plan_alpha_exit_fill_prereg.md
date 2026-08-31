# Pre-registration — α-driven EXIT+FILL lifecycle (Fork B)

> Status: **LOCKED** (2026-07-27, user-approved "开始实验吧，按照你的建议来"). Binding commitment device — headline/arms/KILL fixed pre-hoc; GO/KILL narrative reserved for user.
> Proposed plan_id: **R2-P02** (successor line to R2-P01 oracle-admission).
> Code commit at drafting: a3eaa22. Zero GPU / zero code changed to produce this doc.

## 0. Why pre-register
项目历史反复出现"效果不好就换个能赢的指标/退一步"的模式（ATE→建图→deferred→compactness）。
预注册 = 开工前把 headline 指标、消融臂、KILL 规则钉死，用**证据**决定 GO/KILL，而不是事后挑赢的。
这份文档就是那个 commitment device。GO/KILL 的最终叙事判断**保留给用户**（同 P0-QUAD/PROBE 纪律）。

## 1. Hypothesis (falsifiable)
deferred 输给 prune 的病根是**"出"侧缺失**：物体走后残留高斯的清理回退到原始 prune，deferred 只有硬"进"侧隔离。
**H1 (core):** 在 deferred 的硬进侧隔离之上，加 α 驱动的**主动清除(出)+背景恢复(补)**，能在**腾空区 ghost 指标**上打赢 prune（prune 在 R2-P01-E2 上 0/5 赢我们的那个指标）。
**H1a:** 出侧(D)先要打赢 passive deferred(B)——证明 α-exit 机制非空转。
**H1b:** 补侧(E)是打赢 *prune* 的关键——腾空区无静态可保护，D≈prune 的删除，靠"补"填洞才低 depth_l1。

## 2. Locked design decisions (user-approved 2026-07-27)
- **(a)** Headline = **ghost(腾空区残留) + 保真度**；compactness 收为"α 机制天然副产品"，同表出现，不当卖点。
- **(b)** tracking-side α + densification 门控 → **Future Work**（3 周内不做）。
- **(c) Fork B**：保留 deferred **硬进侧隔离**（novelty 审计 doc-03 唯一认可的点）；α **只用于出+补**，不软化进侧。

## 3. Grounding facts (verified read-only, 2026-07-27)
- `static_prob`/`static_obs_count`/`unmapped_score` 已是 per-Gaussian tensor 且全程 plumbed
  (`gaussian_model.py:101-103,910,1193,1237,664/830`)。`utils/static_prob.py` 已有 render-splat
  (`render_static_prob_map`) + EMA 更新 (`update_static_prob_from_evidence`, β=0.9)。**当前 inert**
  (StaticProb/TriReliability 均 disabled → 常数 0.7)，唯一现存消费者是 tracking down-weight。
  → α 的存储/EMA/splat 是**复用**；出侧 clear + 补侧 fill 是**唯一新代码**。
- `reset_opacity_nonvisible(visibility_filters)` (`gaussian_model.py:726`) 已是**带 mask 的定向 opacity-reset**
  → 出侧机制 A 是它的小变体 (mask = 低α ∧ 遮挡背景)。
- 渲染 opacity 是纯 Python tensor 传入 rasterizer (`gaussian_renderer/__init__.py:134`) → 若需要 σ'=α·σ 可 Python 预乘，不碰 CUDA。
- **free-space carving / KD-tree 背景填充：全仓库无现成**（出侧 B + 补侧从零写）。
- **α₀/证据信号 robust 化**：`reliability_signal.robust_anomaly` 默认 `scale_floor=0` → near-static 帧 MAD 塌缩、
  噪声级残差饱和 (mv_no_box2 +435% 病根)。修复杠杆已存在：正的 `geo_scale_floor`(m)/`flow_scale_floor`(px)。
  Fork B 出侧只在**持续**低α (EMA + `static_obs_count≥N`) 才触发 → 天然抗单帧塌缩。

## 4. Ablation arms (Fork B — 全部保持硬 deferred 进侧；消融的是"出"和"补")
> 注：这不同于 next-plan §6.3 原 A–E（那版 C 是 soft-α 进侧，属 Fork A）。Fork B 重排如下。

| arm | 进 (entry) | α 作用 | 出 (exit) | 补 (fill) | 隔离的贡献 |
|----|----|----|----|----|----|
| **A. prune** | insert-then-prune | — | 粗暴 prune | ✗ | baseline 对照 |
| **B. deferred** | 硬候选隔离 | — | 被动(原始 prune) | ✗ | 现有 R1-P01 candidate |
| **C. defer+α(观测)** | 硬候选隔离 | EMA 累积+记录，**不动作** | 被动 | ✗ | placebo：证明 α 记账本身≈B |
| **D. defer+α-exit** | 硬候选隔离 | 驱动主动清除 | opacity-reset + free-space carve (持续低α) | ✗ | **出侧**贡献 |
| **E. defer+α-exit+fill** | 硬候选隔离 | 驱动清除+填充 | 同 D | 腾空区 KD-tree 背景恢复 | **补侧**贡献 = 完整方法 |

关键对比：**C vs B**(placebo)、**D vs B**(出侧打赢 deferred, H1a)、**E vs D**(补侧增益)、**E vs A**(完整方法打赢 prune = headline, H1/H1b)。

## 5. Metrics (exact fields)
- **PRIMARY (headline, ghost):** `static_vacated_depth_l1_pen_cm` (mapping_raw col47, **lower better**),
  报 `static_vacated_support_px_mean`(col ~46) 证明 support>0。仅 Bonn 动态序列(有 GTMC mask)。
- **CO-PRIMARY (保真度):** `static_depth_l1_pen_cm`(col36, lower better) + `fscore_5cm`(col51, higher better)。
- **GUARDRAIL (no-harm):** static f1_desk(--eval)/f2_xyz(--fast) 的 `ate_rmse_cm`、`fscore_5cm`、PSNR 不退步；
  动态 `ate_rmse_cm`(tracking_raw col8) 无灾难。
- **COROLLARY (compactness, 报告不作 gate):** `online_num_gaussians`(eff col12)/`refined_num_gaussians`(col16)/
  `online_peak_gpu_memory_gb`(col11)/`online_fps`(col9)。
- **AUX:** `static_psnr`, `psnr`。

## 6. Pre-registered KILL rule (falsifiable, checkpointed)
噪声带定义：某指标的 **seed-to-seed 标准差**（由 ≥2 seed 估计）。"赢"= 差值方向一致且 |margin| > 噪声带。

- **CHECKPOINT-1 (arm D, ~08-02, balloon ×2 seed):** 若 D 在 `static_vacated_depth_l1_pen_cm` 上**打不赢 B(deferred)**
  （margin 未超噪声带 或 双 seed 方向不一致）→ α-exit 机制空转 → 先修 exit（carve/reset 阈值/信号），
  修不动则该分支 **KILL**。
- **CHECKPOINT-2 (arm E, ~08-05, balloon ×2 seed):** 若 E **打不赢 A(prune)** on `static_vacated_depth_l1_pen_cm`
  （margin 未超噪声带 或 双 seed 方向翻转，重演 balloon seed-flip）→ **核心假设 H1 证伪** → KILL exit/fill headline。
  退路：compactness 推论 + 干净负结果（诚实报告），**不**改 headline 去挑别的赢指标。
- **保真度否决：** 即使 ghost 赢，若 CO-PRIMARY 在主判据序列系统性退步(≥3/4 变差超噪声带) → 不能声称"更干净"，降级。
- **多 seed 纪律：** balloon 是历史双稳态序列；GO 需 ≥2 seed 同向，禁止单 seed 宣胜（吸取 deferred balloon seed-flip 教训）。

## 7. Sequences & seeds (E 阶梯)
- **R2-P02-E0** (2060, 无 GPU-SLAM)：α→exit/fill 接线 dry-run + 单测 + `git diff --check` + ruff + compileall。
- **R2-P02-E1** (2060)：100 帧 smoke，arm B/D/E 各一，只验运行安全（无崩溃/OOM/NaN）。
- **R2-P02-E2** (2060, **make-or-break**)：balloon × {A,B,D,E} × seed{0,1}（C placebo seed0）。跑 CHECKPOINT-1/2。
- **R2-P02-E3** (3090, 仅 E2 过 GO 后, 用户批)：{A,B,D,E} × {balloon(2),mv_no_box(2),pt2} × seed{0,1,2}
  + static no-harm f1_desk/f2_xyz + **Oracle 注入 pose-controlled 行**（复用 R2-P01 注入，测强轨迹下 ghost/compactness delta）。
- 主判据序列 = balloon(2) + mv_no_box(2)（README 层级；obox 系列仅压力测试）。

## 8. Novelty honesty (论文必须写的边界)
- **不声称** "per-Gaussian 动态概率"为创新（static_prob 已存在、审计判拥挤，撞 BDGS/DAGS）。
- **声称** = 硬 deferred 进侧隔离(已 bless) + α 驱动**进-出-补闭环的出/补两段**(LPM opacity-reset / MAGS carve / GGD fill 的组合改造，α 保护静态不误删)。
- ATE 非贡献（借 RGD 轨迹），报 no-harm。tracking-α / densify 门控 = Future Work。

## 9. Decision reserved for user
GO/KILL 与叙事方向的最终判断 = 用户。本文档只钉客观 gate；E2 出数后停下汇报，不自行宣布 GO/KILL。
