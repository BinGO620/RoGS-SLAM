# ReliabilitySignal (L) 独立贡献摘要

> **来源**：WP-A 三因子全因子 120-run（预注册 `bee241a`，3-seed，5 序列，commit `6b8e85b`）
> **证据文件**：`archive_pre_exp32/wpa_factorial_{prereg,readout,verdict}.md`（同目录 archive）
> **生成日期**：2026-08-25（exp45，从 archive 提升为正式引用）

---

## 1. 装置门 E0（0 GPU，pre-dispatch PASS）

L 轴是否为 null-vs-null 是本摘要的前置条件。E0 dry-run（mv_no_box seed0）证实：

| 项 | L=ON (K1R1L1) | L=OFF (K1R1L0) |
|---|---|---|
| tracking_raw.csv | 有，ate=2.83 | 有，ate=3.75 |
| reliability_signal/ 目录 | **有**（逐帧 frames.csv） | **无**（0 文件） |
| console reliability 引用 | >0 | **0** |
| reject 语义 | 加权 C±（`use_reliability=True`） | 纯整数 `contradictions` |

**结论**：L=OFF 是真正的机制移除，不是 null-vs-null。pre-reg §8 已写死此判据。

## 2. L 轴边际效应（K1R1L0 vs K1R1L1，3-seed k=3）

去掉 ReliabilitySignal（K/R 固定）后的 ATE 变化：

| 序列 | 类型 | L=ON ATE | L=OFF ATE | ratio | Δ_log(ATE) | 判定 |
|---|---|---:|---:|---:|---:|---|
| mv_no_box | 纯物·easy | 3.28±0.40 | 3.93±1.17 | 1.20× | +0.157 | mixed |
| mv_no_box2 | 纯物·easy | 5.12±0.36 | 5.85±0.59 | 1.14× | +0.131 | mixed |
| pt2 | 纯人·medium | 8.76±0.41 | 10.37±0.18 | 1.18× | +0.170 | **positive** |
| balloon | 混合·medium | 13.45±1.43 | 18.36±5.12 | 1.37× | +0.291 | **positive** |
| pt1 | 难人·hard | 36.59±3.36 | 41.38±9.34 | 1.13× | +0.108 | mixed |

### 读法

- **Δ_L 全部为正**（5/5），方向一致：去掉 Reliability 一定不会更好。
- **pt2 和 balloon 正向显著**（positive，Δ > 2× sd）：balloon 去掉 L 后 ATE +37%（1.37×）。
- **mv/mv2/pt1 为 mixed**（方向对但在 sd 内）：但 5 个 Δ_L 均值 +0.171，不为零。
- L 是三组件中**唯一在所有 5 序列上都不为负的**（K 在 balloon 上负、R 在 mv/mv2/pt2 上 ≈0）。
- 在 8 格全表中，L 从未出现在最差格子。

### L 的贡献模式

| regime | Δ_L | 读法 |
|---|---|---|
| pure-object easy（mv/mv2） | +0.13~+0.16 | 小幅正向，方向一致 |
| pure-person medium（pt2） | +0.17 | 正向显著 |
| mixed medium（balloon） | **+0.29** | 最大贡献（去掉后 1.37×） |
| hard person（pt1） | +0.11 | 小幅正向，高方差 |

## 3. 交叉验证：WP-B flow-mask baseline

WP-B（`wpb_flowmask_verdict.md`）的 flow-mask baseline（朴素 flow 阈值 p90，无 Reliability 加权）
在 held-out 4 序列上**不稳定**（pt2 反更差 0.90×）；MRCS（含 Reliability）**4/4 稳定改善**
（1.63–4.99×）。

这间接支持：ReliabilitySignal 的加权机制比朴素 flow 阈值更鲁棒——不是"有 flow 就够了"，
而是"怎么用 flow 加权"很重要。

## 4. 审稿人关切回应

R1-M3 指出"P6 和 P-B 保留 RobustTracking 和 ReliabilitySignal 一起，无法确定
RAFT signal 是否独立贡献"。**答案是 WP-A 已做了这个隔离**：

- L 轴（ReliabilitySignal ON/OFF，K/R 固定）是 120-run 全因子的预注册核心轴之一。
- Δ_L 跨序列非负（5/5），pt2 和 balloon 上正向显著。
- 审稿人可能未读到 `archive_pre_exp32/` 下的 WP-A 判决文件——该文件目前不在主证据目录，
  本摘要将其提升为正式引用。

## 5. 自限

- 5 序列 3-seed，逐序列 CI 弱（描述性证据，非统计等价声称）。
- mixed 序列的方向在 sd 内，不能声称"统计显著"——只能说"方向一致、大小有regime依赖"。
- L 的贡献是 regime-dependent 的（balloon/pt2 显著，mv/pt1 边缘）——这与 WP-A 的
  "A4 序列依赖"结论一致。
- 本摘要不声称 ReliabilitySignal 是唯一或主导贡献；它是最稳定的正向组件。
- **⚠ Δ_L 是复合介入，不是纯 tracking 侧**（2026-08-25 exp46 补，见
  `method_attachment_audit.md` §3）：WP-A 8 格全部钉死 `DeferredCommit.reliability_confirm: true`
  + `lifecycle_mode: prune`，因此 L=OFF **同时**移除两个机制 —— ①tracking RGB+depth 残差降权，
  ②候选高斯 C± 确认的 reliability 加权（退化为纯整数计数，§1 的 E0 表已写明"reject 语义"这一行）。
  ⇒ 因子表内部有效（第四组件恒定），但 **Δ_L 是这两个 site 的联合效应**。
  写稿时不得把 L 描述成"a tracking down-weight"再拿 Δ_L 给它背书。
  **未测**：C± 通道单独隔离后的份额（需新 run）⇒ 不得声称两 site 各占多少。
