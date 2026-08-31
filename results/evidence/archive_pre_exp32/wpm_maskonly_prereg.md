# WP-M 预注册：mask-only baseline（vanilla + Mask R-CNN）— 冻结于 2026-08-15，exp22

> **本文件在任何 WP-M run 启动之前提交。判据不得事后修改。**
> 装置合同：`tests/test_wpm_maskonly_configs.py`（3 passed / 36 subtests）。
> 配置：`configs/rgbd/experiments/wpm_maskonly/`（method overlay + 18 个逐序列 run config）。

## 1. 问题

论文的**绝对竞争力数字全部来自 combined(mask-ON)**（crowd 2.33 vs RGD 2.61、f3_wk_hf 3.03 vs 3.25、
balloon 3.06 vs 2.45）。审稿人的第一枪必然是：

> "这些数字里有多少只是把现成的 Mask R-CNN 接到 MonoGS 上？"

现有证据**回答不了**：P-B 的 mask-ON 格里 RobustTracking + ReliabilitySignal 仍然开着；
WP-A 全在 mask-free 下做；WP-B 的"vanilla+mask"臂用的是 flow 阈值而非语义 mask。
`vanilla + Mask R-CNN` 这一格**从未跑过**（已扫全部实验配置确认）。

## 2. 设计

**补齐顶层 2×2**（这是本 campaign 的真正价值，不只是补一个基线）：

| | mask OFF | mask ON |
|---|---|---|
| **kernel OFF** | vanilla（MonoGS 行 / WP-A K0R0L0） | **mask-only ← 本 campaign** |
| **kernel ON** | Ours-mask-free（主表） | Ours-combined（主表） |

- **范围：全 18 主表序列 × 3 seed = 54 run，分母固定 18，不允许事后挑序列。**
  （初稿只打算跑 5 个"combined 有竞争力"的序列；codex 对抗审指出这是结论导向的后验挑选，
  采纳其质疑，扩到全表——同时顺带把 2×2 补完整，收益大于成本。）
- **臂 = combined 主表 overlay（`method_combined_maskboth_prune.yaml`，即 `p6_mason_combined_*` 所用）
  仅翻转 K/R/L 三个开关**；Mask R-CNN 块、DeferredCommit、Training window、prune lifecycle、
  Results 块与 combined 逐字段相同（合同测试逐序列断言 diff 恰为三个 flag）。
- **协议**：与 WP-A / P7 同款完整协议（**无 `--fast`**），ATE 只认 `tracking_raw.csv` 的
  `ate_rmse_cm`（全轨迹），不 grep console 的 keyframe RMSE。
- **硬件**：远程 3090 ×2（每卡 2 槽）。**不混用 2060 跑本 campaign**，避免协议/硬件混杂；
  2060 分给机制探针（WP-N）。

## 3. 主判据

逐序列 3-seed 配对：`Δ = log(ATE_maskonly / ATE_combined)`，**正 = combined 更好**。
δ = **0.15**（≈16% 相对差）。**δ 是工程等效界，不是统计阈值**——同时报告逐序列 3-seed
标准差与配对区间，不把 δ 说成显著性。

## 4. 预注册分支（互斥，按 M0 → M3 → M1 → M2 → M4 顺序判定）

- **M0 UNRESOLVED（逐序列）**：completion 闸（`trj_full_final` 帧数 ≥ 数据集总帧数 ×95%）
  下共同完成 seed < 2 的序列，退出配对，单列报告，不进任何计数。
- **M3 kernel 在 mask 下有害**：≥2/18 序列 mask-only 优于 combined 达 δ 且该序列 3/3 seed 同号
  ⇒ **必须显著位置报告**，Layer-2 主张重写，并检查是否与 WP-A 的 balloon Δ_K<0 同源。
- **M1 kernel 在 mask 之上仍有增益**：combined 优于 mask-only 达 δ 的序列 ≥6/18，
  且 mask-only 优于 combined 达 δ 的 ≤1/18 ⇒ Layer-2 维持"mask + kernel > mask alone"，
  但必须按序列分层陈述（不写全局最优）。
- **M2 mask 主导、kernel 在 mask 下冗余**：|Δ| < δ 的序列 ≥12/18 ⇒ **诚实改写 Layer-2**：
  "combined 的绝对竞争力主要来自借来的语义分割；我们的贡献是 mask-free 内核（Layer-1）
  与受控证据链（WP-A/WP-B）"。**这是完全可接受的结果，不是失败**。
- **M4 异质/分层**（codex 对抗审补入）：以上阈值均不满足，或方向按 regime 反转
  （例：纯物序列 combined 更好、crowd 反向）⇒ 结论就是这个分层本身，不做全局主张。
- **逐序列 INDETERMINATE**：该序列 3-seed 的 Δ 标准差 > δ ⇒ 不计入"达 δ"也不计入"<δ"，
  单独计数并在结果表标注（避免把噪声读成冗余）。

## 5. 次判据与必须同报的量

- `log(ATE_maskonly / ATE_vanilla)`：**单靠 mask 相对 MonoGS 买到多少**（Layer-2 归因的另一半）。
- **预算混淆必须报告，不得隐藏**（codex 对抗审指出，采纳）：关掉 K 同时改变关键帧预算，
  因而改变插入/prune 机会与计算量。因此每臂必须并报
  `efficiency_raw.csv` 的 KF 数 / `num_gaussians` / `online_fps` / `peak_gpu_memory_gb`。
  同一混淆也存在于 WP-A 的 Δ_K，写作时一并声明。定预算对照 = future work，不在本 campaign。

## 6. 起跑铁律（exp19 教训）

1. 发批量前验证 **远程 HEAD == origin/ours-v3**，再 ff-merge；**禁止手工 scp 装置文件**。
2. launcher 的 `pgrep` 必须**锚定 argv 起始**（`^${PY} slam\.py`），非锚定会匹配监控命令自身。
3. 收尾以产物为准：`tracking_raw.csv` 存在 + completion ≥95%。

---

**冻结时间：2026-08-15（exp22），提交于任何 run 之前。结果写入 `results/evidence/wpm_maskonly_verdict.md`。**
