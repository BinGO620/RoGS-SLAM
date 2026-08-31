# 预注册 —— RPE 分离区间 (1.572, 1.717) 的新序列外推检验（exp47, 2026-08-26）

> **跑前注册。** 本文件在 held-out 序列的 mask-free / combined 两臂 run 存在之前
> commit，此后不改。判据、序列集、N 读数、判决规则全部先写死（§3–§5），
> 读数脚本（§7）与判决由后续 commit 落地。

## 0. ⚠ 效力声明（先说清，沿用 exp37 格式）

**已看过的**：区间本身。`(1.572, 1.717)`、中点 **1.6445** 读自定义它的同一批
18 序列（`rpe_stratification_rule_test.json`，2026-08-25）。这不是盲注册——
区间是上一轮的**拟合产物**，本轮就是对它的**第一次 out-of-sample 检验**。

**未看过的（全部）**：
1. 5 条 held-out 序列上我方两臂的任何 ATE / RPE —— **零 run 已存在**（§6 审计过
   results/runs 全目录）；
2. 这些序列的 N 值与 RPE 值；
3. 任何会泄漏方向的信息。

⇒ 标签：**「区间已知（来自 dev 集）、held-out 完全未见的预先指定分析」**。
区间本身**不再拟合**：阈值在看到任何 held-out 数据之前锁定为 dev 集中点
**τ = 1.6445 cm/frame**（§3），本轮无任何可调参数。

## 1. 被检验的命题（来自 rpe_stratification_rule_test.md 判决 B + 自限 #1）

**命题 P**：mask-free 臂自身的 per-frame RPE（translation, cm/frame）能把
「语义 mask 冗余」与「语义 mask 必需」的序列分开，分离带在 dev 18 序列上为
(1.572, 1.717) 无重叠（17/17 决定格 + 1 排除格若计入也一致）。

**P 不是什么**（自限 #2 必须随行）：RPE 需要**先跑 mask-free 臂**才可算 ⇒
它是**事后诊断**，不是先验 selector。本轮检验的是它的**跨序列外推力**，
不是它的部署价值。

**为什么值得**：dev 集上 17 点完全分离仍可能是过拟合（18 序列不是很多）。
若 held-out 也分离，规则从「描述性」升级为「有跨序列证据的判据」；
若不分离，判决报告分离带宽度是伪影（exp46 判据 #26：两点定的阈值是
拟合非检验 —— 本轮正是把 17 点升级为真检验的动作）。

## 2. Held-out 序列集（跑前锁定，5 条）

选择规则（按此筛，不挑结果——此时两臂数据均为零）：
从 `/data/Datasets` 的 BONN + TUM 全集中，取**不在 dev 18 序列内**、
**GT 完整**、**flow_raft 已预计算**（ReliabilitySignal 硬门需要）、且
**未被我方 mask-free/combined 臂跑过**的序列。

| # | 序列 | 数据集 | 帧数(rgb) | flow | 选择理由 |
|---|---|---|---:|---:|---|
| H1 | `moving_obstructing_box` (obox) | BONN | 590 | 589 | 纯物+人手持遮挡搬动；sequences.yaml 早已列为「机制压力测试」补充位 |
| H2 | `moving_obstructing_box2` (obox2) | BONN | 783 | 783 | 同上，更长 |
| H3 | `synchronous` | BONN | 332 | 332 | 最短；两人同步走 + 搬箱，动态密度高 |
| H4 | `f2_desk_with_person` | TUM | 4067 | 3582 | TUM fr2 动态；dev 集唯一缺席的 fr2 动态序列 |
| H5 | `f3_long_office_household` | TUM | 2585 | 2463 | 长序列静态为主的混合场景；dev 集无此类型 |

**排除记录**（为什么不是别的）：
- `crowd3` / `balloon_tracking(2)` / `placing_*` / `removing_*` / `kidnapping_*`：
  **无 flow_raft**，补建即超零 GPU 起步范围（可作后续 Phase 扩展）；
- `f1_desk` / `f2_xyz` / `f1_room` 等：fr1 静态类已在 dev 集（f1_desk）或无 flow（f1_room）；
- `f3_walking_static` / `f3_sitting_static`：无 flow_raft；
- Replica：exp44 已跑 vanilla/combined（office0/room0）——**combined 已存在** ⇒
  不满足「两臂均未跑」，且 exp44 已判 combined 双稳态；排除并记录。

**dev 集泄漏审计**：5 条序列在 `rpe_stratification_rule_test.json` 的 rows 中
**均不出现**（dev 18 = f1_desk, f2_xyz, f3_office, f2_person, f3_st_{hf,rpy,xyz},
f3_wk_{hf,rpy,xyz}, balloon, balloon2, crowd, crowd2, mv_no_box, mv_no_box2,
pt1, pt2）。

**我方两臂零接触审计**（2026-08-26 实测 results/runs 全目录）：
`find results/runs -name "*obox*" -o -name "*synchronous*" -o -name "*desk_with_person*" -o -name "*long_office*"`
⇒ **0 命中**（P0-QUAD 曾跑过 obox，但那是 deferred×RT 四象限消融——
无 SemanticMask、无 ReliabilitySignal、无 DynamicKeyframe，与本轮 N 估计量的
分子分母无关，且其结论「semi-stable」只涉及那四臂间差异）。
⇒ **held-out 上 N 的分子分母（两臂 ATE）与 RPE 均未见过。**

## 3. 预测规则（先写死，后读数）

对每条 held-out 序列 h：

```
RPE(h)      = mask-free 臂 3 seed 的 rpe_trans_rmse_cm 均值        (cm/frame)
ATE_mf(h)   = mask-free 臂 3 seed 的 ate_rmse_cm 均值               (cm)
ATE_cb(h)   = combined 臂 3 seed 的 ate_rmse_cm 均值                (cm)
N(h)        = ATE_mf(h) / ATE_cb(h)
```

**N 的判决带**（逐字沿用 dev 轮定义，不改）：
- `N ≥ 1.5` ⇒ mask **necessary**
- `N ≤ 1.2` ⇒ mask **redundant**
- `1.2 < N < 1.5` ⇒ **ambiguous，排除、不硬塞**（dev 轮 f3_st_hf 先例）

**预测**（τ = 1.6445，dev 中点，锁定）：
- `RPE(h) > 1.6445` ⇒ 预测 **necessary**
- `RPE(h) ≤ 1.6445` ⇒ 预测 **redundant**

**一个提醒**（dev 轮教训，非本轮判据）：dev 集上 ambiguous 带内那格（f3_st_hf）
按其 RPE 预测是 redundant、若计入则一致 ⇒ 排除只让规则更保守。本轮 ambiguous
格同样只排除、不计入命中率分子分母。

## 4. 判决规则（先写死：什么算过、什么算不过）

设 D = 决定格数（5 减去 ambiguous 格数），命中数 A = 预测与 N 判决一致的格数。

| 判决 | 条件 | 含义 |
|---|---|---|
| **CONFIRMED** | A = D 且 D ≥ 3 | 分离规则跨序列成立 |
| **PARTIAL** | A/D ≥ 4/5 且错格全部相邻（错在边界附近） | 方向对、精度不够 ⇒ 区间需重估（记 Deviation，不算过关） |
| **REFUTED** | A/D ≤ 3/5，或出现「RPE 高但 mask 冗余」的反向大错（N ≤ 0.8 而 RPE > τ） | 分离是 dev 集伪影 |
| **INCONCLUSIVE** | D < 3（ambiguous ≥ 3） | 数据不足，扩序列后重判 |

**为什么不是 100% 才算过**：dev 轮自己是 17/17，若外推连 1 格都不许错，
等于要求新序列的动态构成与 dev 完全同分布——那外推就没有意义。4/5 +
无反向大错是「方向正确且无致命反例」的最低线；**但 PARTIAL 不允许宣称
「判据成立」，只允许宣称「值得扩大检验」**。

**反向大错单列**的原因：RPE 低但 mask 必需（dev 的四条 DISAGREE 均属此类，
是旧 2.5 阈值的死因）本轮规则容忍为普通错；但 **RPE 高（>τ）而 N ≤ 0.8**
（mask 不仅不必要、开了反而坏 1.25× 以上）是规则从未见过的方向，
出现即 REFUTED——这说明 RPE 高只是「序列难」的代理，不是「mask 有用」的预测器。

## 5. 装置与 provenance（沿用主表纪律，逐字引用）

- **RPE/ATE 读数**：与 `scripts/test_rpe_stratification_rule.py` 同一实现——
  per-run `tracking_raw.csv` 优先、同文件多 run 取 run_id 匹配、否则最后一行；
  ATE = `ate_rmse_cm`（全轨迹，项目硬规则：headline = tracking_raw.csv 的
  ate_rmse_cm，不是 console RMSE）。
- **seed 发现**：glob 到 run 目录后按 `*_seed<N>` 解析，每格 3 seed；
  **latest-run 规则**（每 seed 多 timestamp 取最新且要求 config.yml 存在）
  与主表 `discover()` 一致——**复用主表脚本的函数，不另写一套**。
- **臂定义**：mask-free = `method_combined_maskoff_prune.yaml`
  （SemanticMask.enabled: false，其余逐字节 = combined）；
  combined = `method_combined_maskboth_prune.yaml`。
  **唯一差异 = SemanticMask.enabled**，由 `tests/test_p6_maskoff_configs.py`
  钉住（该合同测试已存在，直接复用，不另写）。
- **语义 mask 来源**：在线模型（maskrcnn，combined 臂配置内置），
  **不依赖离线 seg_mask 目录** ⇒ held-out 序列无需额外 mask 资产（已核实
  `utils/semantic_mask.py:128` 走 `_load_model`，无文件读取路径）。
- **flow 硬门**：`assert_reliability_flow_available`（7b89ff81）在 run 内
  abort 而非 no-op——5 条序列 flow 已就绪（§2 表）。
- **运行环境**：远程 3090（jiangwenheng），全长度 run；
  **--fast 即 --eval**（2060/3090 已知，headline ATE 口径不受影响）。

## 6. Run 矩阵与分阶预算（遵守 Phase 制度）

**Phase 0 不适用**（无新机制：两臂 config 均为已验证冻结组合，
本轮是**估计量的外推检验**，不是机制自检）。
**直接按 Phase 1 立项**：

| 项 | 值 |
|---|---|
| run 数 | 5 序列 × 2 臂 × 3 seed = **30 run** |
| 预算 | 3090 单卡串行 ~20-25 GPU·h（f2_desk_with_person 4067 帧是长尾，约 8-10h/臂/3seed） |
| 中止条件 | 任一臂某序列 3 seed 极差 > 3× 中位极差（双稳态嫌疑）⇒ 该序列标记 bistable、单列报告、**不进命中率**（mask-free 底座已知双稳态，crowd2 单臂内 44→97cm 先例——**mask-free 主线判决必须看崩溃率口径**，沿用项目硬约束） |
| 不做的事 | 不跑 vanilla（N 不经 vanilla 分母）；不建新 flow；不改任何 config 常数 |

## 7. 读数与判决产物（跑后落地，此处只登记形状）

1. `scripts/test_rpe_boundary_heldout.py` —— 读数脚本：复用主表 discover/read_ate
   与 test_rpe_stratification_rule 的 read_rpe，输出
   `results/evidence/rpe_boundary_heldout.json` + `.md`（与 dev 轮同构：
   逐序列表 RPE/N/预测/实测/判决 + §4 规则的总判决）。
2. 单测：给判决门喂已知坏值（空目录 / 缺 CSV / 全 ambiguous / 反向大错格），
   一个从不失败的门不是门（exp37 判据，沿用）。
3. registry 登记：RPE-BOUNDARY-HELDOUT 一行，GPU 列按实跑填。
4. 写作下游：manuscript §5.5 与 §6 的措辞按判决四分支（CONFIRMED/PARTIAL/
   REFUTED/INCONCLUSIVE）各有对应模板，**跑完再改稿，不预写结论句**。

## 8. 预注册自检清单（exp32 判据七条对照）

| # | 判据 | 本轮落实 |
|---|---|---|
| 1 | 零假设+阈值注册 | §3 τ=1.6445 锁定；§4 四分支判决条件先写死 |
| 2 | 死线确认可测 | N 的两侧（两臂 ATE）均可测：run 落盘即得；RPE 同源 |
| 3 | 先量地板 | 不适用（无效应量比较）——但双稳态中止条件（§6）承担同等防误读职能 |
| 4 | 先算可达域 | dev 集两类先验比例 9:8 ⇒ 5 格期望 2-3 格/类，D≥3 可达 |
| 5 | 容差按精度 | 判决带沿用 dev 轮 N≥1.5/≤1.2，与本轮精度无关（读数精度=run 精度） |
| 6 | 极端反打 | 反向大错（RPE>τ 且 N≤0.8）单列 REFUTED（§4） |
| 7 | 点火≠有用 | §4 PARTIAL 分支明确不许宣称判据成立 |

## 9. 与最高准则的关系

本检验不写稿、不定投期。它的产出有两种：过 ⇒ §5.5 的边界陈述获得
out-of-sample 支撑（支撑段落，不是新头条）；不过 ⇒ Deviation 报告
「分离带是 18 序列伪影」，§5.5 措辞降级。**两个方向都是对诚实适用域的
贡献，都不触发写作决策。**
