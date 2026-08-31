# 预注册 —— mask 增益的第三条通道：tracking 侧隔离（exp36, 2026-08-21）

> **发批前注册。** 本文件在第一个 run 之前 commit，此后不改（判据①：零假设与阈值一起提前注册）。
> exp34 把分支标签写反过一次、exp35 的 G3 押在了已知不敏感的量上 —— 本文件 §2 先把
> 装置门与标签映射写死，§4 先把**判据可达域**算完，再谈读数。

## 1. 为什么值得 GPU：两种读法对同一段 cm 给出相反归因

exp34/35 已把两条通道钉死（两次都是干净的单变量翻转）：

| 对比 | 翻的开关 | 结论 |
|---|---|---|
| eboth vs PBA | `mask_mapping` | share_BA = **0.672 / 0.438 / 0.798**（balloon / f3_wk_xyz / pt1） |
| eboth vs insertion-off | `mask_insertion` | share_ins = **0.017 / −0.005 / 0.004**（全在可读地板下） |

两者之和不足 1，残差 **R = 0.311 / 0.567 / 0.199**（= 2.72 / 13.66 / 4.70 cm）。
这个残差有**两种互相矛盾的读法，而且都写在了上一轮的产物里**：

- `results/evidence/insertion_verdict.md` §更正：「残差是**两条通道的重叠**，不是别处的贡献」；
- `scripts/insertion_verdict.py::_decide` 判决文本：「the 20-56% gap is NOT in insertion;
  **it can only be in the tracking side**. Next target = tracking-side isolation.」

**两种读法对 balloon 上同一段 2.72 cm 给出相反归因**，而现有四个臂无法分辨，因为
所谓「第四格 maskfree」并不是 (`map=F, ins=F`) —— 它是 `SemanticMask.enabled: false`，
**同时关掉了第三条仍然活着的通道**（tracking 光度损失的前 10 次迭代）和 T2 的候选集。
逐通道代码证据 = `results/evidence/semantic_mask_channel_inventory.md`。

**本轮补的那一格**：`enabled=true, mask_mapping=false, mask_insertion=false`
（`configs/rgbd/experiments/pba_ba_coupling/pba_trackside_only_*.yaml`）。

```
                       ins=T                ins=F
   map=T   A eboth      3.07     B insertion-off   3.20      ← exp35
   map=F   C mapping-off 8.64     E trackside-only  ???       ← 本轮
   （enabled=false: D maskfree 11.36 —— 不是 E，它连 tracking 侧和 T2 一起关了）
```

**设计上的强性质：这一格把残差 R 做成恰好的二分**（代数恒等式，非近似）：

```
(D − E)/(D − A)  +  (E − C)/(D − A)  =  (D − C)/(D − A)  =  1 − share_BA − share_ins ≈ R
 └ trackside 单独买到的 ┘   └ insertion 在 map-OFF 域买到的 ┘
```

⇒ **一个 E 的读数同时给出两个份额**，不是两个独立量的比较；两种读法各自预言 E 落在
区间的一端（§4 有预言表）。

## 2. 装置门（写在主判据之前，且必须真的执行 —— 判据⑨；正负两个方向都验 —— G5 教训）

**发批前已验（零 GPU，已执行）**：

- **G0**：三个 config 解析后 `enabled=True, mask_mapping=False, mask_insertion=False`；
  与 `pba_mapping_off_*` 的**唯一差异 = `mask_insertion`**；`mad_exclusion` 与 eboth 一致。
  由 `tests/test_pba_ba_coupling.py::TestPBATracksideOnlyConfigs` 钉住（15 passed）。
- **G0b（通道存活的代码路径）**：`TestTrackingChannelIsLive` 钉住
  「soft 分支先于 hard 分支、且本臂族不设 `hard_tracking_mask`」⇒ tracking 硬 mask 只在
  `tracking_itr < warmup_iters=10`（共 `tracking_itr_num=100`）时进损失。
  **这条不是推理，是把推理钉进测试**：将来若有人把硬 mask 接进 soft 分支，先红的是这个测试。

**收批后必须逐 run 验，任一不过 ⇒ 该 run 作废，不进判决**：

| 门 | 内容 | 判据 | 为什么它能测（发批前已确认可测 —— 判据②） |
|---|---|---|---|
| **G1** | 插入门必须**不响** | 本臂 console 中 `Semantic insertion gate` 出现 **0 次** | exp35 已用同一装置拿到 9/9 |
| **G2** | 对照臂必须**响** | 同批 `eboth` / `pba_mapping_off` console 中该行 **>0 次** | 盘上已核：`eboth_balloon_seed0` = 67 次、`pba_mapping_off_balloon_seed1` = 67 次（**控制臂不重跑，引用其自身日志**） |
| **G3** | 被测通道必须**活着**（正控制） | 本臂 `reliability_signal/frames.csv` 的 `mad_excl_semantic == 1` 占比 ≥ 0.95 | 盘上已核：`eboth_balloon_seed0` 438/438 = 1 —— 该列非 0 就证明 semantic mask 张量确实算出来且进了 tracking 侧的消费路径 |
| **G4** | 被测通道在 maskfree 里必须**死着**（负控制） | `control_maskfree_*` 的 frames.csv **无** `mad_excl_semantic` 列、`mad_exclusion` 恒 0 | 盘上已核：`control_maskfree_f3_wk_xyz_seed0` = 827/827 为 0，且无该列 |

**G3 与 exp35 失败的 G3 的区别**（吃过一次的教训）：exp35 那个门押在
`n_gaussians` —— 一个 exp34 已经测出对 mask 变化不敏感（±4%）、且被 prune 二次清洗的
代理量。本轮 G3 是**日志级直接量**：它只问「mask 算出来了吗、进了消费路径吗」，
不问「机制往哪个方向动」。方向留给主判据，不塞进装置门。

## 3. 可分解性门（判据⑧，由 exp34 继承，不重新拟合）

| 序列 | 总效应 D−A | 控制臂极差 | 比值 | 可分解 | 控制口径可读地板 |
|---|---:|---:|---:|:-:|---:|
| balloon | 8.30 | 1.52 | 5.46 | ✅ | 0.183 |
| f3_wk_xyz | 24.10 | 0.39 | 61.8 | ✅ | 0.016 |
| pt1（描述性） | 23.64 | 6.49 | 3.65 | ✅ | 0.275 |
| mv_no_box | 0.81 | 1.50 | 0.54 | ❌ 不跑 | — |

**⚠ 本轮新增的一条更正（对 exp34/35 判据本身）**：上表的「极差」只取了两个**控制臂**
（eboth / maskfree）的 seed 极差，而分子里那个**处理臂本身强双稳态**：
`pba_mapping_off` 逐 seed = balloon [9.35, 8.55, 8.03]（极差 1.32）、
f3_wk_xyz [6.56, 9.95, **23.73**]（极差 **17.16** = 总效应的 71%）、
pt1 [16.5, 33.4, 36.5]（极差 **20.0**）。
⇒ **share_BA 在 f3_wk_xyz / pt1 上的均值口径不可读**（CLAUDE.md 已立的硬规则：
mask-free 底座双稳态必须用崩溃率口径，不能用均值差），0.016 那个地板严重低估了噪声。
本轮判据因此使用**双臂感知地板** `floor' = max(ptp_两个被比臂) / (D−A)`，并对
每个序列同时报**逐 seed 配对方向**（causal-twin 的 keyed RNG 让同 seed 可配对）。

## 4. 判据可达域与预言（先算，再跑 —— 判据④）

两种读法各自的**点预言**（写在跑之前，可被数据打脸）：

| 序列 | A eboth | C map-off | D maskfree | H-inert 预言 E≈ | H-material 预言 E≈ | 两预言间距 |
|---|---:|---:|---:|---:|---:|---:|
| balloon | 3.07 | 8.64 | 11.36 | **11.36** | **8.64** | 2.72 |
| f3_wk_xyz | 2.85 | 13.41 | 26.95 | **26.95** | **13.41** | 13.54 |
| pt1 | 9.95 | 28.82 | 33.59 | **33.59** | **28.82** | 4.78 |

- **H-inert（exp35 的重叠读法）**：tracking 侧单独买不到东西 ⇒ E≈D。
  由二分恒等式，残差就归给 **insertion 在 map-OFF 域的贡献**
  ⇒ 「insertion 是冗余备份、只在 mapping 缺席时才是唯一防线」这条机制说法**被介入性证实**。
- **H-material（判决脚本自己写的读法）**：tracking 侧单独买到残差 ⇒ E≈C
  ⇒ insertion 在两个域都可忽略，exp35 §4 的机制说法的后半句**被证伪**，
  且 exp34 的残差是**真的第三条通道**，不是重叠。
- 落在中间 ⇒ 按二分比例读，两条都部分成立（允许分级答案，不强行二选一）。

**可达性检查**：balloon 两预言间距 2.72 cm vs 双臂感知地板分母（D ptp 1.52 / C ptp 1.32）
⇒ 间距 ≈ 1.8× 极差，**n=3 的均值口径处在边缘**；f3_wk_xyz 间距 13.54 cm vs D ptp 0.39
⇒ **≈ 35× 极差，是本轮真正的判别序列**（C 的双稳态只影响次级份额，不影响主估计量 E vs D）。
⇒ 因此 **Phase 1 必须同时包含 f3_wk_xyz**，只跑 balloon 会得到一个注定 INDETERMINATE 的读数。

## 5. 判决规则（先把标签写对，再看数）

**标签映射**（拆掉部件后掉性能 = 该部件承载效应；exp34 曾把这条写反）：
E 比 D **好** ⇒ tracking 侧承载了效应；E 与 D **同** ⇒ tracking 侧不承载。

主估计量（每序列）：

```
recovery_trackside = (mean_D − mean_E) / (mean_D − mean_A)
floor'_trackside   = max(ptp_D, ptp_E) / (mean_D − mean_A)
share_ins_mapoff   = (mean_E − mean_C) / (mean_D − mean_A)     # 二分的另一半
floor'_insmapoff   = max(ptp_E, ptp_C) / (mean_D − mean_A)
```

- **TRACKSIDE-MATERIAL**：≥2 个可判序列上 `recovery_trackside > floor'_trackside`
  **且**逐 seed 方向一致 ≥5/6（E < D）。
- **TRACKSIDE-NEGLIGIBLE**：≥2 个可判序列上 `|recovery_trackside| ≤ floor'_trackside`。
- **INDETERMINATE**：序列间不一致，或 E 自己的极差把间距吃掉（`ptp_E > 0.5×`两预言间距）。
- pt1 = **描述性**（其 maskfree 臂落在 38–63 cm「谁都失败」带附近、控制极差 6.49），
  沿用 exp34/35 的处置，不参与投票。

**逐 seed 配对方向**与均值口径**同时报**，两者不一致时以配对方向为主（双稳态下均值不可信）。

## 6. 分阶预算（CLAUDE.md §1 硬纪律）

- **Phase 0（1 run）**：balloon seed0。**只验 G1/G3，不看 ATE**。门不过 ⇒ 停，不进 Phase 1。
- **Phase 1（5 run）**：balloon seed1/2 + f3_wk_xyz seed0/1/2 ⇒ 两个可判序列齐 3 seed。
- **Phase 2（3 run，可选）**：pt1 ×3，仅作描述性第三条。
- 控制臂（A/C/D）**不重跑**，沿用 exp34/35 的 27+9 run（同机同并发；exp34 已验 eboth
  复跑 3.06→3.18 = +3.9% < 6% 噪声地板）。

## 7. 本轮**不**测什么（避免读过头）

- 不测 `mask_mapping` 内部的 BA-位姿梯度 vs 高斯梯度之分（同一个 `loss_mapping.backward()`
  同时喂 `gaussians.optimizer` 与 `keyframe_optimizers`，`utils/slam_backend.py:518-528`）。
  那需要改代码（双 backward）且会改后端 wall-clock ⇒ 在异步调度下污染 ATE，必须单独设计。
- 不测把 tracking 侧**加强**（`hard_tracking_mask: true`）会怎样 —— 那是增强实验，不是隔离。
- 不重述主表（用户明确：等方法成型）。
