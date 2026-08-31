# exp39 Step C 尺度对齐三臂 —— 预注册（发批前写死，commit 早于 run）

> 目的：拆开原 E 臂里纠缠的**三件事**——admission / 权重形状 / 5.7×10⁴ 倍尺度膨胀。
> 本预注册在派发之前 commit，判读阈值不事后拟合。

## 0. 为什么需要这批（撤回说明）

原 EMA 分支 `return ema_c_mass * (alpha*l1_rgb.mean() + ...)`，其中
`ema_c_mass = sum(w)/count(valid)` = **平均**权重。于是光度项 ∝ `err̄ · w̄²`。
实测 `w̄` = 238.8(E) / 537.8(S) ⇒ 相对硬臂膨胀 **5.7e4 / 2.9e5 倍**，
而固定的 `10 * isotropic_loss.mean()` 未变 ⇒ **两臂事实上跑在几乎无 isotropic 正则的状态**。

后果（已在 `exp39c_ema_decomposition_verdict.md` 更正）：
- 判决 `ADMISSION-NOT-SHAPE` **撤回**——E 与 S 共享该混杂，"S≈E"最可能由共同混杂造成；
  且 S 的膨胀是 E 的 5 倍，与 S 的 ATE 更差（5.36 vs 4.81）**单调对应**。
- 附带发现：原 D-3 置换在全图上做，把无效区（μ̂,q̂≈0 ⇒ w≈1e4）的权重搬进 valid，
  `w̄` 239→538，**总质量未守恒** ⇒ 它并非声称的"等质量、等边际、只改形状"介入。已修为 valid 内置换。

**仍然成立**（不依赖 loss 尺度）：`bias_suppression` 四轮为负（权重图自身属性）；
μ̂²/σ̂² 分量分解与判据 #24（残差统计的直接测量）。

## 1. 装置：三臂链，每对相邻臂只差一个变量

| 臂 | 权重形状 | 支撑集 | 总质量 | 状态 |
|---|---|---|---|---|
| **H** | 均匀 1 | valid ∩ static | count(valid∩static) | 已有，ATE 2.99 |
| **E-sm-zeromask** | EMA | valid ∩ static | 锁定 = H 的 | 本批 |
| **E-sm** | EMA | valid（含 dynamic） | 锁定 = H 的 | 本批 |

- `H → E-sm-zeromask`：单变量 = **static 内部的权重形状**
- `E-sm-zeromask → E-sm`：单变量 = **admission**（动态像素是否带权重）

**代码分支混杂已解析排除，不烧 run**：`tests/test_exp39c_scale_match.py::
TestMathematicalEquivalenceToHard::test_uniform_weight_reproduces_hard_loss_exactly`
证明均匀权重经 EMA 分支算出的 loss 与硬 mask 分支**逐位相等**（rtol 1e-6）。
⇒ 分母、有效像素数、梯度稀疏性等分支差异不构成解释（codex 对抗第 2 点关闭）。

规模：balloon × seed0 × 2 臂 = **2 run**，两卡并行 + 30s 错开，约 15 min。
Phase 0 纪律：ATE 只记录不作最终判决；本批的作用是**归因**，不是给 EMA 平反。

## 2. 判读（阈值发批前写死）

地板取项目 ATE 噪声地板 **6%**，基线 H = 2.99 cm ⇒ 可读门槛 |Δ| > 0.18 cm。
**但 E 臂已知自身 spread 3.44 cm**（5.31/8.25/4.81）⇒ 单 seed 下任何涉及 EMA 形状的
差值都必须与该 spread 比，不与 6% 地板比。故本批判读**只认方向与量级档位**，不认精确效应量。

### 分支 A：`ADMISSION-CONFIRMED`
`E-sm-zeromask ≈ H`（|Δ| 与 H 自身 spread 0.47 cm 同档）**且** `E-sm` 明显差于 `E-sm-zeromask`
（差值 > E 臂 spread 3.44 cm，或方向一致且 > 1 cm）
⇒ 伤害确来自 admission，原判决方向恢复（但作用域仍限 balloon 单 seed）。

### 分支 B：`SHAPE-HARMFUL`
`E-sm-zeromask` 明显差于 `H`（> 1 cm）
⇒ 伤害来自**权重形状本身**（哪怕只作用在静态像素上），与 admission 无关。
这会把判据 #24 的适用面**扩大**：残差倒数型权重连在静态像素上都有害。

### 分支 C：`SCALE-WAS-THE-STORY`
`E-sm` 与 `E-sm-zeromask` **都** ≈ H
⇒ 原 E/S 的全部伤害来自尺度膨胀（isotropic 正则被删），
**连续加权本身在 balloon 上未被证否** ⇒ Step C 需重开，且 Phase 1 的
SOFT-WORSE 也须复查是否同源（floor 臂走的是另一分支，`l1.mean()` 分母恒为全图，
不含 w̄² 膨胀，故预期不同源——但需明说）。

### 分支 D：`NO VERDICT`
两臂任一崩溃（ATE > 20 cm）或落在上述档位之间不可归类 ⇒ 不贴标签，报 range，
按需补 seed。

## 3. 装置门（发批前必过，写在判读之前）

- **G-1**：两 config 解析后与 `exp39c_ema_balloon.yaml` 的差异**只能**是
  `mapping_ema_mass_match` / `mapping_ema_zero_dynamic` 两键。
- **G-2**（负对照）：`E-sm-zeromask` 的 probe 读数 `ema_mean_weight_dynamic`
  必须恒为 **0**（动态像素零权重）；非 0 ⇒ 臂标错，判决作废。
- **G-3**（正对照）：`E-sm` 的 `ema_mean_weight_dynamic` 必须 > 0
  （否则两臂无法区分 admission）。
- **B-0/B-1**（沿用）：发批前 0 个 slam 进程 + 两卡残留显存 < 1 GB。

## 4. 自限（发批前声明）

- 单序列（balloon）、单 seed。mv_no_box 上 `applied_frac = 0`，本批不外推。
- 本批**不能**给 EMA 平反：预注册主判据 `bias_suppression > 0` 已四轮全败，
  那是权重图自身的性质，与尺度无关。本批只回答"ATE 的伤害由什么造成"。
- `pose_to_map_ratio` 仍只是 DBAphoto 失效模式的代理，未做 Hessian 条件数。
- 质量对齐只对 RGB 项做（`hard_support` 由 `rgb_pixel_mask & static` 定义），
  depth 项复用同一权重图 ⇒ depth 侧的等效质量未单独对齐，属已知残留不对称。
