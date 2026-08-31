# 预注册 —— exp39 Step C：逐像素滞后残差 EMA 的方差-偏置内核

> **发批前注册**。本文件在第一个 run 之前 commit，此后不改。
> 装置基于 Phase 0/1 装置（`utils/mapping_weight.py` + `utils/mapping_probe.py`）的扩展；
> 预注册改写自 Phase 1 教训（`results/evidence/exp39_phase1_gate.json`）。

> **2026-08-22 定稿更新（收到 Phase 1 对冲后）**：
> - `mv_no_box` 已判 SCALE-EXPLAINED（W 优于 H 但不优于 S，且 W 臂 `applied_frac=0.0`），
>   ⇒ 至少部分差异来自光度项尺度而非权重形状，**S 臂的存在是必要的**。
> - 因此 Step C 仍保留 H/F/E 三臂，其中 F = soft floor 0.25（Phase 1 已判死的那条），
>   用来把“同样的 mask 放回量、但不同的权重来源”单独隔离。
> - 预注册不做任何事后改写（Phase 1 结果只改变我们怎么解释四分支走向，不改变阈值）。

## 1. 背景与为什么这仍是值得做的事

Phase 1 把固定 floor 判死了：balloon 上 `applied_frac` 几乎相同（0.157 vs 0.160）
但 ATE 差了 176%，说明**固定 floor 只是同比例放回所有 mask 像素，而这些像素在梯度里的
权重比静止背景高 8.6×**。它们不是被"同等地保留在噪声里"，而是被**超比例放大**。

Step C 的核心主张是：**按残差的偏置分量 b̂² 降权、按方差分量 σ̂² 保留**——
这正是 exp37/38 在整条轨迹上测到的方差-偏置机制的在线逐像素版本。

Phase 1 同时也给了一个非常具体的**成功条件**：
只有当 EMA 估计的 b̂² 能比固定 floor 更好地区分"有害偏置"和"无害波动"时，
Step C 才可能在 balloon 上 ATE 不变差。这正是 D-3（状态打乱实验）要判的事。

## 2. 装置（三臂 × 两序列 × seed 0，Phase 0 同级规模）

| 臂 | 语义 | 落点 |
|---|---|---|
| **H** | 现状硬 mask（动态像素权重 = 0） | 冻结对照 |
| **F** | Phase 1 的固定 floor 0.25（`soft_mapping`） | Phase 1 已判死，留作"不判别方向时会发生什么"的参照 |
| **E** | **Step C：逐像素滞后残差 EMA**（`mapping_ema`，β=0.95，λ=1.0，σ_min=0.01） | 待判 |

序列 = balloon + mv_no_box。规模 = 2 序列 × 3 臂 × seed0 = **6 run**。

**Phase 0 同级的机制自检**（不看 ATE）是门槛：E 臂必须通过 G-2（H 臂 dyn_share=0）
+ **G-NEW（Phase 1 教训）**：E 臂的 ATE **不得**比 H 臂差超过 6%（若超过则判
**MECHANISM-HARMFUL**——机制动了但方向反了，这正是 balloon Phase 1 发生的事）。

## 3. Phase 0 只判机制，Phase 1 才看 ATE

**Phase 0**（2 run，balloon × seed0 × {H, E}）：
- 只看探针读数（applied_frac、dyn_share_map/pose、pose_to_map_ratio）；
- **不看任何 ATE**（分阶预算硬约束）；
- 新增诊断：EMA 逐像素 b̂² 在动/静区域的分布分离度（**替代 Phase 0 的 S2 审计**）。

**Phase 1**（4 run，balloon + mv_no_box × {F, E}）：
- 判 ATE 效应 vs 6% 地板；
- E vs F：**同样的动态像素数量，但权重来源不同**（常数 vs 偏置估计），
  分辨"放回的数量"与"放回的判别质量"。

## 4. 装置门（任一不过 ⇒ NO VERDICT）

| 门 | 判据 | 为什么可测 |
|---|---|---|
| **G-0** | E 臂 `mapping_ema.enabled = true`，H/F 臂关闭 | 合同测试钉住 |
| **G-2** | H 臂 `dyn_share_map = 0.00000000`（精确） | Phase 0 已复现两次 |
| **G-NEW** | Phase 1：E 臂 ATE 与 H 的差 ≤ 6% × H | Phase 1 教训：机制在工作但方向反了 = 有害 |
| **G-3** | E 臂 probe 记录 ≥20 条 | 覆盖率 |

## 5. 判决规则

**Phase 0**：
- **EMA-LIVE**：E 臂的 b̂² 在动态/静态区域**可分**（KS 检验 p<0.05 或 AUC>0.6）；
  且 H/F/E 三臂的 `applied_frac` 不全等（EMA 不是换皮的 floor）；
  且 `pose_to_map_ratio` 在 H 的 2× 内（BA 未被重塑）。
- **EMA-INERT**：b̂² 不可分 ⇒ Step C 失败；
- **EMA-RESHAPING**：`pose_to_map_ratio` 越 2× ⇒ 死判决 A 的失效模式复现。

**Phase 1**（只在 Phase 0 判 EMA-LIVE 后执行）：
- **EMA-MATERIAL**：E 优于 H 且 E 优于 F（在 6% 地板上）——
  **同样的动态像素数量，偏置加权比常数加权更好**；
- **EMA-SCALE**：E 优于 H 但不优于 F 的某个匹配尺度 ⇒ 仍是尺度效应；
- **EMA-WORSE**：E 比 H 差超过 6% ⇒ MECHANISM-HARMFUL（动态污染放大器）；
- **EMA-INDISTINGUISHABLE**：都在地板内。

## 6. 适用域与诚实边界

1. **单 seed、两序列** = screening。不报效应量，只报方向；
2. **EMA 状态的初始化**：第一帧 `μ₁ = e₁`（无滞后）—— 这是已知的不稳定源，
   预注册里标注为**前 5% 帧不进读数**；
3. **Step C 不是"免分割"落点**（E 臂仍依赖语义 mask 来决定"哪些像素进 EMA"）；
   免分割的 EMA（用 `1−s` 替代语义 mask）是后续扩展，不在本轮；
4. **β/λ/σ_min 三个超参**不扫（Phase 0/1 同级预算不允许）—— 0.95/1.0/0.01 是
   标准信号处理惯例值，论文里写"未调优"。
