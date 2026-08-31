# exp39 Step C 跨序列验证 f3_wk_xyz —— 预注册（发批前 commit）

> **问题**：balloon 上的结论（admission 有害、安全份额 ≤1%）**能不能迁移到另一条序列**？
> 这是审稿人必问的可迁移性，也是 balloon 单序列判决的最大欠账。
>
> **必须先说明的先验**：exp38 已测到**效应量随序列衰减**——同一介入在 balloon 上
> 4.0× 地板、在 f3_wk_xyz 上 <1× 地板（ATE-INDISTINGUISHABLE）。
> ⇒ **本批很可能读出"不迁移"，而那是一个真结果，不是失败。** 预注册分支 C 为它留位。

## 1. 装置：与 balloon 链条**结构对等**

f3_wk_xyz 根 = `pba_eboth_f3_wk_xyz.yaml`（`f3_wk_xyz` + `method_t2_eboth` overlay），
与 balloon 根 `t2_eboth_balloon.yaml`（`balloon` + **同一** overlay）结构对等
⇒ 除数据集外无第二个差异。

| 臂 | 份额 | balloon 实测 |
|---|---:|---:|
| H（硬 mask） | — | 3.23 |
| zeromask | **0%** | 3.27 |
| cap05 | **5%** | 4.33（2.5× 地板，有害） |
| E-sm | **31.8%** | 6.53（7.6× 地板，有害） |

规模：f3_wk_xyz（814 帧）× seed0 × 4 臂 × **2 run** = **8 run**，两卡并行，约 80–90 min。
**为何每臂 2 run**：f3_wk_xyz 的 within-config 地板**必须在本序列上实测**，
不能 import balloon 的 0.43，也不能用 CLAUDE.md 的"mask-ON 极差 0.1–0.6cm"泛述
（项目铁律：run-to-run 非确定性**逐臂逐序列**，任一个都不可外推）。

## 2. 判读（阈值发批前写死）

地板 = **本批实测**的逐臂 within-config spread 最大值，记 `F3_FLOOR`。
基准 = 本批 zeromask 均值。

### 分支 A：`DOSE-TRANSFERS`
顺序保持（0% ≈ H < 5% < 31.8%）**且** 31.8% 相对 0% 超过 `2 × F3_FLOOR`
⇒ balloon 结论迁移。报两序列的份额-伤害对照表。

### 分支 B：`SEQUENCE-DEPENDENT-THRESHOLD`
31.8% 有害（> 2×F3_FLOOR）但 5% 落在 1×F3_FLOOR 内
⇒ 伤害迁移但**安全份额更大** ⇒ **"安全份额 <1%" 是 balloon 特有的，
必须改写成逐序列陈述**，且拐点与序列的动态特性相关（可用 `applied_frac` 做协变量）。

### 分支 C：`ADMISSION-INERT-HERE`
即使 31.8% 也落在 1×F3_FLOOR 内
⇒ **admission 的伤害不迁移**；balloon 判决降级为序列特有。
与 exp38 的效应量衰减一致。此时必须报 `applied_frac`：
若 f3 的 applied_frac 远低于 balloon 的 16%，则"不迁移"的解释是**剂量的绝对量不同**
（相对份额相同但绝对动态像素少）⇒ 结论应改为"伤害随动态占比缩放"，而非"不迁移"。

### 分支 D：`NO VERDICT`
非单调超出地板、任一臂崩溃（ATE > 20 cm）、或出现双稳态
（同 config 同 seed 两次差 > 3× 其余臂的 spread）⇒ 不贴标签，报 range。

## 3. 装置门（先于判据）

- **G-5（本批最关键）**：f3_wk_xyz 上 `applied_frac` 必须 > 0 且**报出其数值**。
  mv_no_box 就是因 `applied_frac = 0` 而使整个剂量旋钮作用在空集上。
  若 f3 的 applied_frac 远小于 balloon 的 0.16，**分支 C 的解释必须按 §2 改写**。
- **G-4**：每 cap 臂实测 `ema_dynamic_over_static` 中位数 = 配置值（相对误差 < 10%）。
- **G-6（链条锚点）**：`zeromask` 与 `H` 的差必须在 1×F3_FLOOR 内。
  违反 ⇒ 该序列上"static 内权重形状"本身有效应，剂量读数与 balloon 不在同一基线上，
  须先解释再判剂量。
- **G-1**：各臂相对本序列基线 config 的差异只允许预期键。
- **B-0/B-1**：发批前 0 个 slam 进程 + 两卡残留显存 < 1 GB。
- **数据门**：`datasets/tum/rgbd_dataset_freiburg3_walking_xyz/flow_raft` 非空
  （已查 = 814；CLAUDE.md 的 rsync 软链纪律）。

## 4. 自限（发批前声明）

- 单 seed（seed0）× 2 run ⇒ 产出的是 **within-config** 地板，非 between-seed。
  按项目铁律 between-seed 通常主导 ⇒ 方向可判、幅度不定。
- 两序列（balloon + f3_wk_xyz）**不足以支撑"随动态占比缩放"这类连续律**，
  最多支撑"两点一致 / 两点不一致"。
- 只扫 σ̂²/λμ̂² 权重族；外生信号权重不在作用域。
- **本批不能给连续加权平反**：即使分支 C（此序列无害），
  也只说明伤害与序列相关，不构成"放回带来增益"（无害 ≠ 有用，沿用上批自限）。
