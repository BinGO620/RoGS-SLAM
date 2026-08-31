# RPE 边界 held-out 判决 — CONFIRMED（exp47 收数，2026-08-27）

> **预注册执行的读数报告。** 判据、序列集、判决分支全部先写死于
> `rpe_boundary_heldout_prereg.md`（commit `be5f6d3c`，早于任何 held-out run 存在）。
> 本文只登记执行结果。读数脚本 `scripts/test_rpe_boundary_heldout.py`；
> JSON `rpe_boundary_heldout.json`。

## 0. 批次执行事实

- **30/30 run 全部完成**（`ALL_DONE missing=0`，远程 jiangwenheng 3090×2，2026-08-27 02:35 CST），
  全部 status=OK，无 OOM、无 config 错误。
- **4 个格子同 seed 跑了两次**（launcher 两段历史：第一段跑了 obox/obox2 seed0 后中断，
  第二段 17:28 起 SKIP 已完成的、补跑其余；`maskfree_synchronous_seed0` 与
  `combined_desk_with_person_seed2` 因中段重启各 RUN 两次）。rollup append-only、两行均 OK
  ⇒ 属**同 seed 复跑**（项目规则 = latest-run），非崩溃重试。四个格子的两次值全部
  留在 JSON `duplicate_runs_latest_rule` 字段，**不静默**。
  Sensitivity：first-run 规则下五格预测/观测**无一变化**（obox2 N 1.62→1.66 仍 necessary）。
- 数据已 rsync 回本地 `results/runs/RPE-BOUNDARY/rpe-heldout/`（排除 `datasets_*`
  帧产物，保留 tables/ + consolelog + done 文件；远程副本保留）。

## 1. 逐序列结果（预注册 §3 口径：3-seed 均值）

| 序列 | mf RPE | mf ATE | cb ATE | N | 预测(τ=1.6445) | 实测 | 判 |
|---|---:|---:|---:|---:|---|---|---|
| obox | 2.117 | 35.23 | 24.78 | 1.42 | necessary | **ambiguous(带内)** | 排除 |
| obox2 | 2.068 | 31.59 | 19.48 | 1.62 | necessary | necessary | **AGREE** |
| synchronous | 2.424 | 65.43 | 0.47 | 138.97 | necessary | necessary | **AGREE** |
| f2_desk_with_person | 0.602 | 6.10 | 6.48 | 0.94 | redundant | redundant | **AGREE** |
| f3_long_office_household | 0.456 | 1.71 | 1.56 | 1.09 | redundant | redundant | **AGREE** |

- **判决（预注册 §4）：CONFIRMED** —— A = D = 4（D≥3 门过），无反向大错
  （无 RPE>τ 且 N≤0.8 的格子）。
- **双稳态门（§6）：未触发**。最大极差 obox combined 12.15 cm（18.2–30.3）=
  2.86× 中位极差 4.25，低于 3× 门（余量 0.14×）。
- ambiguous 格 obox（N=1.42，带内）按预注册排除；**排除方向保守**——若按带中点 1.35
  归边它落 necessary 侧、与预测一致（dev 轮 f3_st_hf 同款情形）。

## 2. 判决的可读范围（必须随 claim 走）

1. **CONFIRMED 的含义 = 4 个判决格外推全对**，不是「规则已建成判据」。它是 dev-18
   拟合带的**第一次 out-of-sample 检验**，n=5、descriptive（项目规则：n=3/cell 无 CI）。
   倍数仍不可宣称「判据成立」→ 只有本判决的 CONFIRMED 分支允许说
   **「分离规则在 5 条未见序列上 4/4 判决格 + 1 带内格（计入则 5/5）一致」**。
2. **仍是 post-hoc 诊断**：RPE 要先跑 mask-free 臂才可算，不是可部署的 a-priori
   selector。这一限定原文照抄预注册 §1，本轮不改变它。
3. **synchronous 的 N=139 是极端格**（mask-free 65.43 vs combined 0.47）：它一致但
   信息量低（任何能分开好坏的指标都会对）。真正扛判决的是 obox2（N=1.62，刚过
   1.5 线）和两条 redundant 格（N 0.94/1.09 干净落在冗余侧）。
4. **obox 落带内（N=1.42）本身是信息**：dev 集分离带 (1.572,1.717) 的 RPE 侧在本轮
   无重叠区间可检（5 点 RPE 分布 0.456/0.602/2.068/2.117/2.424，带内无点）——
   本轮检验的是**阈值方向**，不是带边界位置。

## 3. 门单测（预注册 §7.2：喂已知坏值）

12/12 PASS：空输入/2 格→INCONCLUSIVE；反向大错→REFUTED（即使其余全对）；
全对→CONFIRMED；4/5 对+近边界错→PARTIAL；4/5 对+远边界错→REFUTED；3/5→REFUTED；
N=1.5/1.2/1.35 边界三态；RPE==τ→redundant；实际判决复现。

## 4. 下游动作（预注册 §9：过 ⇒ 支撑段落，不触发写作决策）

- manuscript §5.5 边界陈述**获得 out-of-sample 支撑**：措辞升级为
  「区间在 5 条 held-out 序列（4 判决格 + 1 带内格计入则 5/5）上一致」，
  仍保留 post-hoc 诊断限定与 n=5 descriptive 限定。
- §6 Limitations 的「区间无 held-out 检验」一条**到期**，改写为已检但样本小。
- **不写稿、不定投期**（最高准则；预注册 §9 两个方向都不触发写作决策）。

## 5. provenance

- run 目录：`results/runs/RPE-BOUNDARY/rpe-heldout/rpeh_{arm}_{seq}_seed{N}/`
  （`long_office` 目录名 = `f3_long_office_household` 序列，config 继承
  `configs/rgbd/tum/f3_office.yaml`，读数脚本内已映射）。
- 读数：rollup `tables/tracking_raw.csv`，latest-run 权威顺序（与主表
  `discover()/read_ate()` 同规则）；per-run CSV 在 rsync 排除的 `datasets_*` 下，
  rollup 行已含 run_id 可复核。
- 判决门实现：`scripts/test_rpe_boundary_heldout.py::verdict_of`；
  JSON：`results/evidence/rpe_boundary_heldout.json`。
