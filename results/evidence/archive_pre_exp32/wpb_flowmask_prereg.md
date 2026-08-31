# WP-B 中间地带 baseline — 预注册（2026-08-14，CCF-C 整改执行卡 v3 §4 WP-B）

> **本文件在 WP-B 第一个 run 之前 commit，首个 run 发出后判据/数值界/序列集合/分母冻结
> （护栏 6/17/18）。** WP-B 是 3090 后续工作包（T3，在 WP-A 之后）。本期先落预注册与装置规格，
> flow_mask 实现待 WP-A 起跑后 checkpoint 时实现（不干扰冻结的 WP-A 骨干）。

## 一、靶

审稿 R2：缺中间地带 baseline（只比 vanilla 与完整 SOTA）。增益来自"我们的方法"还是
"随便什么抗动态处理"？WP-B 用**同等 flow 信息下最朴素的可部署处理**（朴素 flow 阈值 mask）
做对照，回答这一点。

## 二、臂（三条，同 campaign 一起跑）

1. `vanilla` = `K0R0L0`（本 campaign 自己的锚，不借 WP-A 的行）
2. `flow-mask` = vanilla + 朴素 flow 阈值二值 mask（**无学习分割**）
3. `MRCS` = `K1R1L1`（mask-free 全开）

> 不合并 WP-A：与 WP-A 有 18 格重叠，但合并需 flow-mask 实现在 WP-A 起跑前完成，阻塞主力。
> **决定不合并**，重复 run 是 provenance 纪律的价格。

**公平性 caveat（写进 method 与 limitation）**：
- flow-mask 与 MRCS 用**同一套离线双向 RAFT flow**（未来帧可见、非因果、预计算）⇒ 衡量的是
  "在同等 flow 信息下，朴素阈值 vs MRCS 的差距"，**不**支持"在线可部署最简基线"结论。
- causal（forward-only）变体列为**后续工作第一项**（只需重跑本 WP 6 序列）。

## 三、flow-mask 构造（实现规格，T3 落实）

复用已冻结 `flow_raft/`。**说明**：严格执行卡的 "e_flow 分位阈值" 需要 ego-flow 相减
（需 poses/map），这会牵扯在冻结骨架上改 frontend。为控制干扰，本装置采用**自包含的朴素实现**：
对每帧观测后向 flow 幅度 `|f_obs|` 取分位阈值 → 二值化 → 膨胀（对齐 `dilate_px:7`）→
走现有 `SemanticMask` 消费路径（`mask_mapping` + `mask_insertion`），保证"唯一差异= mask 从哪来"。
> 若要在"同 e_flow 信号"口径上更贴合的朴素臂（对 |f_obs|-阈值与 e_flow-阈值两种在 dev 上各跑一
> 次对比，选更接近 MRCS 的读数）——此细节到 T3 实现时按最低干扰原则定，**判据/分支不受影响**。

实现落点 `utils/flow_mask_baseline.py` + `semantic_mask.py` 的 `source:"flow_threshold"` 分支（默认关）。
flow_threshold 开关在 WP-A 期间保持关闭 ⇒ 不影响冻结的 WP-A 骨干。

## 四、序列划分（族污染显式分层）

| 角色 | 序列 | 性质 |
|---|---|---|
| **dev**（仅选阈值） | `mv_no_box`, `balloon` | 不进判决 |
| **held-out ①（干净）** | `pt1`, `pt2` | pt 族未参与选阈值 ⇒ 主判据 |
| **held-out ②（同族）** | `mv_no_box2`, `balloon2` | 与 dev 同族 ⇒ 次级证据，单独成行，不与①合并 |

## 五、run 预算（42 run ≈ 10.5h，3090 双卡）

- **Pilot（选阈值，只在 dev）**：3 分位（p80/p90/p95）× 2 dev × seed0 = **6 run**（screening）
- **Confirm（三臂，只在 held-out）**：选定阈值 × 3 臂 × 4 held-out 序列 × 3 seed = **36 run**

## 六、阈值选择规则（跑前钉死）

- **目标函数**：dev 两序列 seed0 的 **ATE 几何平均最小**；
- **完成率优先（tie-breaking）**：任一 dev 序列**未完成**（帧数 < 95%）的阈值直接淘汰；
- **并列**（几何平均差 ≤ ε=0.10）⇒ 取中位 **p90**（写死）；
- 三阈值全淘汰 ⇒ WP-B 中止，如实记录"朴素 flow 阈值在 dev 上不可用"（本身是结果）。

## 七、判定（M2 + round-2 收紧）

配对 log-ATE 比值，实践相关界 **`δ = 0.20`**（log 尺度 ≈ **22%** ATE 比值，非 20%）。
> `δ` 依据 = 历史 run-to-run 波动带，是实践相关性阈值，非统计等价界。3 seed/序列 ⇒ 逐序列 CI 很弱；
> 所有结论表述为「可复现的描述性证据」，不作统计等价声称。

| 分支 | 条件（主判据 = held-out ① 2/2） | 处置 |
|---|---|---|
| **B1 MRCS 更好** | `log(ATE_flowmask/ATE_MRCS) > δ`，逐 seed 3/3 同号，① 2/2 | "优于同等 flow 信息下的朴素阈值基线"。主表加列 |
| **B2 未检出差异** | 配对差落 `[−δ,+δ]`，① 2/2 | 写"**在本分辨率下未检出差异**"，不写"等价"。贡献叙事退 empirical-study |
| **B3 朴素更好** | 反向超 δ，① 2/2 | 头条塌；如实报"朴素基线已足够" |
| **B4 混合/不可判** | ①两序列不一致或落差跨 δ | 写"n=2 干净 held-out 不足以分辨"；②作方向旁证不替代；列为 open item |

**无论落哪个分支，flow-mask 这一列都进主表**（审稿人已问出，藏了更糟）。

## 八、E0 装置自证（WP-B 起跑前）

1. flow-mask 唯一差异确认：`SemanticMask.source=flow_threshold` 时，config 除 mask 来源外与
   vanilla 逐字节一致（`tests/test_wpb_flowmask_configs.py`）。
2. flow 可用性：6 序列 `flow_raft/` 均非 0（已验：balloon 438 / balloon2 468 / mv_no_box 777 /
   mv_no_box2 930 / pt1 579 / pt2 566）。
3. mask 活动：`flow-mask` run 的 console/log 必须有 mask 生效证据（mask_mapping/mask_insertion 触发）；
   `vanilla` run 必须无。无活动证据 = 作废重跑（G3）。
4. 阈值分位在 dev 选、在 held-out 确认，**不事后调**（M1）。

## 九、与优化方向的关系

WP-B 是**论文需要的 baseline 证据**，不是"优化方法"。与 WP-F（融合算子）无关、不互相替代。
WP-B 结果是"MRCS vs 朴素 flow 处理"的归因对照；WP-F 是 MRCS 内部的算子优化（success 只进 Supplementary）。

---
**§v3 预注册（WP-B）定稿：2026-08-14。判据冻结（首个 run 前 commit）。**

## E0 装置自证（2026-08-14）— 撤回（exp19，2026-08-15 修正）

> ⚠ **此 E0=PASS 作废。根因：远程 3090 repo 的 WP-B 代码未经 git 同步（HEAD 停在 7a46595，
> 远落后 origin/ours-v3=5f3cdaa2），前端 `utils/slam_frontend.py` **不含** `flow_threshold` 分支。
> 因此 flowmask config 运行时 `semantic_mask_enabled()=true` 落入 `else → compute_semantic_dynamic_mask`
> = **Mask R-CNN 学习分割**，朴素 flow 阈值 mask **从未执行**。
> 证据：运行时 config.yml `{model:maskrcnn, source:flow_threshold}`（source 无读取代码）、
> `semantic_timing/hard_calls=439/439`（Mask-RCNN 调用数）、`flow_mask_baseline.py` 只在
> `_compute_flow_threshold_mask` 可达而该函数远程不存在。E0"3.13"与整个 E0% 是**学习分割结果**，非朴素基线。
> 处置：2026-08-15 重发 FULL 6-run pilot（含 balloon-p90 作为 E0 重发），阈值选择重新开始。
> commit `5c2c3ae6`（E0 PASS 文案）、`306e95e1`/`0ec4e65b`（pilot）基于错误前提已不可信。


---

## 附：事实更正（2026-08-15, exp22）—— **判据未改，仅更正一处事实描述**

本预注册 §（flow 预算）写有"flow-mask 与 MRCS 用**同一套离线双向 RAFT flow**（未来帧可见、非因果、
预计算）"。经三重核实（生成器循环、磁盘 manifest、`reliability_signal.py` 消费端），
**该描述错误**：冻结 flow 一直是 backward `f_{t→t-1}`，每帧只用该帧与其前一帧，**信息上严格因果**。

- **预注册判据（δ、held-out 划分、分母、判决分支）一字未动**，B1 判决不受影响。
- 依此写下的自我限制"不支持任何在线可部署最简基线结论 / causal 变体 = 后续工作第一项"予以**撤回**。
- 完整核实链与更正后表述：`results/evidence/flow_causality_correction.md`。
