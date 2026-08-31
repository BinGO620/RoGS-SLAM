# 预注册 —— exp39 Phase 0：mapping/BA 观测聚合的连续加权（机制自检）

> **发批前注册**：本文件在第一个 run 之前 commit，此后不改。
> 装置 = `utils/mapping_weight.py` + `utils/mapping_probe.py`（已 commit `c9c045d7` / 本 commit）；
> 合同 = `tests/test_exp39_mapping_weight.py`（24 tests 绿）；
> 形态审计 = `results/evidence/exp39_weight_audit.md`（装置门 G-A PASS）；
> 方向对抗 = `results/evidence/consult_codex_exp39_direction.md`。

## 1. 问题，以及它为什么不是已死的那个问题

**问题**：`mask_mapping` 是本项目实测的唯一决定通道（ATE 必要性 6/6 + 静态带 PSNR 分组 +
动态惩罚 19run 零重叠），而它的消费方式是**二值**——动态像素对 mapping/BA 损失的贡献恰好为 0。
exp37/38 在位姿侧测到方差-偏置权衡（剔更多像素 ⇒ 逐帧方差↑、相干偏置↓、ATE 净变好）。
**本轮把这个二值端点参数化成连续谱，在聚合器自己身上测这个权衡。**

**与死清单的关系（诚实版，已被 codex 反打修正）**：

| 死判决 | 是否覆盖本落点 | 本轮必须承担的风险 |
|---|---|---|
| DBAphoto NO-GO（离线 DBA-lite 几何项加 reliability 权重） | **不覆盖**（离线 post-hoc + KF-KF point-to-plane vs 在线 photometric+depth） | ⚠ **失效机制仍适用**：mapping loss 是 joint BA（同时驱动高斯参数与窗口位姿），改权重会改**极小值位置**，可能以 map–pose 共适应形式复现"目标极小值不在真位姿附近" |
| reliability-redundant-online（tracking 侧已加权 ⇒ 离线复用重复） | **不覆盖**，且其强版本**已被本项目实测证否**：同一张 mask 在 tracking 消费买到 ≈0（TRACKSIDE-INERT）、在 mapping 消费是决定性的 | — |

> **本轮不主张"旧 NO-GO 已被逻辑排除"**，只主张"这是一个未被测过的落点，且失效机制可被本轮诊断量看见"。

## 2. 装置（单变量）

两臂，**唯一差异 = `SemanticMask.soft_mapping`**（合同测试钉住）：

| 臂 | config | 语义 |
|---|---|---|
| **H（对照）** | `exp39_hard_balloon.yaml` | 现状硬 mask（floor 恒等于 0） |
| **W（治疗）** | `exp39_soft025_balloon.yaml` | 动态像素权重 = **floor 0.25** |

两臂都开 `MappingProbe`（interval 50）。**floor 选 0.25 的理由（跑前，来自 S2 审计）**：
它是远离两个端点的内点；尺度混淆在此处仅 `c_rgb = 1.037`（全程最大 1.148）；`ESS_frac` 0.878→0.932。

**恒等锚（已在合同测试中逐位验证，非断言）**：`floor=0` 与硬 mask **逐位相同**；
`floor=1` 与无 mask **逐位相同** ⇒ W 是 H 的严格推广，不是另一个目标函数。

规模 = balloon × seed0 × 2 臂 = **2 run**（分阶预算的 Phase 0 上限）。

## 3. Phase 0 只判机制，**不看 ATE**（跑前声明）

本轮**不读、不报、不讨论任何 ATE 数**。理由 = 分阶预算硬约束（exp32 教训）：
机制未证明触达优化器之前，ATE 只会诱发对噪声的解释。
> 违反本条的读法一律作废，即便数好看。

## 4. 装置门（任一不过 ⇒ NO VERDICT，不进 Phase 1）

| 门 | 判据 | 为什么可测（发批前已确认） |
|---|---|---|
| **G-0** | 两臂 config 解析后唯一差异 = `soft_mapping`；W 的 `mapping_floor` = 0.25 | `tests/test_exp39_mapping_weight.py` + config 合同测试 |
| **G-1** | 恒等锚：`floor=0` ≡ 硬 mask 逐位、`floor=1` ≡ 无 mask 逐位 | 已绿（合同测试，非运行时断言） |
| **G-2 负对照** | **H 臂**的 `dyn_share_map` 与 `dyn_share_pose` **恰好 = 0**（不是"很小"） | 硬 mask 删除动态像素 ⇒ `_split_losses` 的动态项恒等于 0，已单测 |
| **G-3 探针覆盖** | 两臂各 ≥ 20 条 probe 记录，且 `applied_frac` 落在审计预测的 mask 面积 **0.122 ± 0.04** | S2 逐帧审计给出分布 |

**G-2 是这套门的承重条**：一个在对照臂上也报出非零动态梯度的探针，说明它量的不是我们以为的东西。

## 5. 主判据与点预言（跑前写死，可被打脸）

**PRIMARY = 动态像素在两个参数块上的梯度份额**（`dyn_share_map` / `dyn_share_pose`，
probe 记录的中位数）。

**点预言**：W 臂 floor=0.25 时，动态像素的**权重质量份额**是
`0.25×0.122 / (0.878 + 0.25×0.122) = 3.4%`（由 S2 审计的面积算出，非拟合）。

| 假设 | 预言 | 含义 |
|---|---|---|
| **H-live**（机制触达优化器） | `dyn_share_map > 0.034` **且** `dyn_share_pose > 0.034` | 动态像素残差大于平均 ⇒ 梯度份额**超过**质量份额 |
| **H-inert**（权重进了 loss 但没进梯度） | 两者 ≈ 0 | 机制不动 ⇒ **死**，不进 Phase 1 |
| **H-degenerate**（BA 被重塑而非重加权） | `pose_to_map_ratio(W)` 偏离 `H` 超过 **2×** | 触发 dead 判决 A 的失效模式警报 ⇒ 不进 Phase 1，改做机制调查 |

**判决规则**：
- **MECHANISM-LIVE**：G-0..G-3 全过 **且** 两个 share 都 > 3.4% **且** `pose_to_map_ratio` 在 2× 内 ⇒ 进 Phase 1；
- **MECHANISM-INERT**：任一 share ≈ 0（< 质量份额的 1/3，即 1.1%）⇒ **死**；
- **MECHANISM-RESHAPING**：`pose_to_map_ratio` 越 2× ⇒ 不进 Phase 1（这是死判决 A 的失效模式在本落点的实例，必须单独调查）；
- **其余（share 落 1.1%–3.4% 之间）**：**PARTIAL**，报份额并写明"梯度份额未超过质量份额 ⇒
  动态像素并非高残差群体，方差-偏置的外推前提在 mapping 侧不成立"。

## 6. Phase 1 规格（现在注册，防止事后拟合）

**只有 Phase 0 判 MECHANISM-LIVE 才执行。** 三臂（codex 尺度混淆对策）：

| 臂 | 语义 |
|---|---|
| H | 硬 mask（现状） |
| W | soft floor 0.25 |
| **S** | 硬 mask + **尺度匹配**（`mapping_scale_match`，`c = Σw/Σm`，detach） |

序列 = balloon + mv_no_box；judgment = ATE 效应 vs 噪声地板 **≥6%**（项目已有值，非新拟合）。
**三分支读法（跑前钉死）**：
- W 优于 H 但**不**优于 S ⇒ 收益来自 loss 尺度，**权重形状主张塌**；
- W 仍优于 S ⇒ 才支持"连续权重形状"本身有价值；
- 都无差异 ⇒ 软化无可测机制收益。

## 7. 适用域与诚实边界（写在读数之前）

1. **仅 balloon、仅 seed0** ⇒ Phase 0 不产生任何跨序列陈述（exp36 判据 #15：残差成分逐序列不同）。
2. **floor 旋钮的作用面主要是 mask 假阳**：S2 实测硬 mask 删掉的像素 **74.1% 未被 GTMC 判为动态**。
   ⚠ 但 GTMC 量的是"该瞬间运动不一致"，**不是"将来会不会动"** ⇒ **不得**把假阳份额读成
   "这些像素放回来是安全的"，只能读成"旋钮作用面落在这批像素上"。
3. **本轮不证明免分割落点（A1）**：W 用的是语义 mask。A2 通过**不得**被引用为 A1 的证据。
4. **方法内核不在本轮**：`soft floor` 是通道验证与对照，**不是**可写进论文的方法内核
   （codex 判定：`huber × dynamic_prior` 形态 = 把 tracking 老形态搬到 mapping）。
   内核候选（逐像素滞后残差 EMA 的 σ̂²/b̂² 分解 + 状态打乱判别实验）在 Phase 1 之后单独预注册。
5. **BA 可观测性只做了代理**（`pose_to_map_ratio`），未做 Hessian 条件数 ⇒
   `MECHANISM-RESHAPING` 的**不触发不等于 BA 没被重塑**，只等于本代理没看见。
