# DBAphoto step2 — reliability-weighted geometric oracle 结论
> 2026-08-03 | branch `dba-photo-weighted` | commits ac678ef→d60796c
> codex 复审：019fc47b（设计）、019fc6be（门控设计 8 条）、019fc738（KILL bug）、019fc7e1（GN 结果）

## 门控问题
给 DBA-lite 的几何项加 reliability 权重能否改善跟踪？前提：DBA `_edge_two_sided`（:179）
从没用过 reliability；在线 `static_conf=(1-w)` 已乘进 RGB+depth（`slam_utils.py:447`）→
photo-BA+reliability 冗余，几何项才是非冗余遗漏。

## step1（已完成，commit 80563e1）
4 个 stash run 落盘 exact-online w_map + warmup 渲染上下文 + prev/cur W2C。
安全 tag `v2.0-dba-photo-step1-clean` @ 80563e1（退路）。

## step2 oracle：reliability-weighted GEOMETRIC oracle

### 方法（全采纳 codex 019fc6be 8 条意见）
- FATAL-1：GT 在 KF0 处刚体对齐到 online（`Tgt'_k = Tgt_k @ inv(Tgt_0) @ Ton_0`）。
- FATAL-2：主指标 = fixed-support sweep（t=0 inlier 集+edge 集+分母冻结）；
  dynamic-support（真实 solver opt_cost）作诊断，两者须同向才 GO。
- FATAL-3：初始方向测试 = fixed-support fixed-weight 定向导数 `g₀ᵀδ_GT`。
- IMP-4：target w 冻结在 t=0 对应上（pose-dependent w 为敏感度诊断）。
- NIT-8：主 verdict 排除 KF0-src 边。
- 3 个实现 bug（codex 019fc738）修复后（commit 687af1b）：
  - Bug1：`_edge_weighted_resid_at_t` 改用 `_reproject_fixed`（不重 gate）+ OOB carry-forward。
  - Bug2：per_edge 数组按 frozen edges 对齐（边身份配对），bootstrap 改 per-edge resample。
  - Bug3：cond_kill 加 `R_dynamic>=1 AND dir_deriv>=0` 要求（局部下降存在→INCONCLUSIVE）。

### oracle 结果（修复后，commit d60796c）
t-grid = {0,.02,.05,.1,.2,.5,.75,1}，margin=2%，per-edge bootstrap B=2000

| run | R_fixed | R_dyn | d1(C.02-C0) | d2(C.05-C.02) | dir_deriv | gt_better | ATE cm |
|---|---|---|---|---|---|---|---|
| balloon s0 | 140.6 | 3.095 | +0.0042 | +0.075 | **−0.171** | 0/253 | 3.03 |
| balloon s1 | 140.8 | 3.130 | +0.0051 | +0.072 | **−0.174** | 0/253 | 3.10 |
| mv_no_box s0 | 252.3 | 7.115 | +0.0040 | +0.052 | **−0.069** | 0/457 | 2.57 |
| mv_no_box s1 | 257.7 | 7.172 | +0.0043 | +0.052 | **−0.072** | 0/457 | 2.69 |

per-run CI（lower bound）：balloon ~122–149；mv_no_box ~228–286（全 >>1）。

**VERDICT: INCONCLUSIVE（4/4 incl）**
- fixed-support d1/d2>0（t=0→0.02→0.05 单调升），R_fixed=140–258（GT 残差远高）。
- 但 dir_deriv<0（GN 局部方向指向 GT）且 dynamic t=0→0.02 降（0.0622→0.0597）。
- codex 019fc738 裁决：fixed vs dynamic/dir_deriv 不同向 = 浅盆信号；
  固定 m0 把 online 位姿选的对应 decorrelate 放大（非真实 objective 信号）；
  **fixed-support 不该当主指标**；R_dyn=3–7 = GT 不在同一有用盆，但局部 GN 方向向 GT。

### balloon s0 fixed vs dynamic sweep
```
t      C_fixed   n_fix   C_dynamic  n_dyn
0.00   0.0622    253     0.0622     253
0.02   0.0664    253     0.0597↓    253   <- dynamic 局部降，fixed 升
0.05   0.1419    253     0.0638     253
1.00   8.7462    253     0.1925     190
```

## GN step test（codex 019fc738 建议的端到端测试）

### 方法
- 从 online 位姿出发，5 步 LM（lm_prior=0，geometry-only）。
- 每步 dynamic IRLS（inlier+MAD+w_rel 每步重算）。
- KF0 gauge-fixed，接受步仅当 cost 降。
- 指标：dynamic cost + GT-ATE（camera-center RMSE vs GT，KF0 gauge）。

### 结果
| run | cost_ratio | ate_gt t0→t5 | Δate | accepted |
|---|---|---|---|---|
| balloon s0 | 0.539 | 85.86→84.00 | **−1.86** | 5/5 |
| balloon s1 | 0.542 | 85.85→83.80 | **−2.05** | 5/5 |
| mvn s0 | 0.538 | 98.37→98.46 | **+0.09** | 5/5 |
| mvn s1 | 0.540 | 98.09→97.75 | **−0.35** | 5/5 |

脚本判 GO（3/4 run Δate <−0.1cm），但 codex 019fc7e1 **推翻**：

**VERDICT（codex 019fc7e1）: INCONCLUSIVE / 对 3→1.5cm 目标按 NO-GO**

原因：
1. **指标不匹配（致命）**：85–98cm 是 KF0-aligned SE(3) camera-center RMSE，不能跟
   2.6–3.0cm Umeyama-ATE 比。−1.85cm 不证明 headline ATE 下降。
2. **预注册 GO 条件未满足**：ATE 非单调（balloon iter2 反转，mvn s0 变差 +0.09）。
3. **46% cost 降是弱证据**：动态 IRLS 每步换 objective，cost 可因 support/scale 变化而降。
4. **gauge-like 运动可能**：lm_prior=0 + KF0 固定，solver 可做绕 KF0 的近全局形变。

## 未完成（下个会话决定是否做）

> **⚠ 已完成并已推翻本节的乐观读法（2026-08-03，见 `p2_dba_gn_umeyama_prereg.md` §4）。**
> 指标修复做了，落 **(R-NOGO) 干净 NO-GO**：把同一批 GN 位姿放进 headline 口径
> （evo SE(3)-Umeyama，`utils.eval_utils._evaluate_trajectories` by import）后，
> ATE **大幅变坏**：balloon 3.03→12.63cm、mv_no_box 2.69→6.07cm，
> **9/9（3 run × 3 读数）最优迭代 = iter 0 = online 位姿本身**。
> 下面写的 "Sim(3)-Umeyama" 也已修正为 **SE(3)（无尺度）** —— 这些是 RGB-D run，
> headline 本身 `correct_scale=False`，放开尺度会得到不可比且偏乐观的数。

**codex 019fc7e1 的下一步**（指标修复，不需重跑 SLAM）：
- 保存 GN 每步 KF 位姿，用 Sim(3)-Umeyama 协议重算 per-iter ATE（与 online ATE 同口径）。
- 分解每步 update 成全局 Sim(3) + 残余形变，报 aligned ATE + RPE。
- 若 Umeyama-ATE 也无可靠改善 → **干净 NO-GO**，路线①关门，跟踪维持 P2-T。
- 若有改善 → 再扫小 lm_prior，报多个 prior 强度结果。
这需要重跑 GN ~1min（加 pose 保存），再离线 Umeyama 计算（无 GPU）。

## 当前 git 状态
```
tag  v2.0-dba-photo-step1-clean → 80563e1 (退路)
HEAD d60796c (step2 代码 + GN 测试 + 3 bug 修复)
测试：59 个 CPU 单测全过（tests/test_dba_geo_weighted.py + 回归）
```

## 结论摘要（迁移用）

> **⚠ 本节的 "INCONCLUSIVE" 已于 2026-08-03 升级为干净 NO-GO**
> （`p2_dba_gn_umeyama_prereg.md` §5）。下面三条保留原文作记录，读时按该文件走。
> 关键更正：「浅盆信号 / dir_deriv<0 指向 GT」是在 **KF0-gauge** 口径下测的，
> 而该口径的 online 基线 85.86cm 里约 **96% 是全局对齐量**（同批位姿 Umeyama 下仅 3.03cm）。
> 端到端测下来，沿该方向走会把轨迹**扭坏** 3.4–9.7cm ⇒ 不是"没调好"，是目标函数方向不对。
> **cost 类数据（fixed/dynamic sweep、R_fixed、R_dyn、bootstrap CI）不受影响**——
> 它们是 cost 不是 ATE，无 gauge 依赖；受影响的只有 `_ate_proxy`/`gt_ate` 与
> `dir_deriv` 的 GT 目标（`_gauge_align_gt` 锚在 KF0）。

- 路线①（给 DBA 几何项加 reliability 权重）：**INCONCLUSIVE，不能判干净 KILL 也不能 GO**。
- 浅盆信号：dynamic objective 局部指向 GT（dir_deriv<0，dynamic t=0→0.02 降），
  但终端 R_dyn=3–7（GT 不在同一有用盆）；cost 可降 46%，但 ATE 改善序列依赖 + 指标混淆。
- **用户决定**：做 Umeyama 指标修复（~1min GN rerun + 离线计算）得干净结论，
  或直接判 NO-GO 存档，跟踪维持 P2-T，转向其他改进方向。
- DO NOT CHANGE H-D / P2-T 已定记录。这是 non-preregistered 探索。
