# WP-B 中间地带 baseline —— confirm 判决（2026-08-15，exp19）

> **判决 = B1（MRCS 优于同等 flow 信息下的朴素阈值基线），held-out① 2/2，4/4 序列一致。**
> 判据取自 `wpb_flowmask_prereg.md §七`（**首个 confirm run 前冻结，未改**）。
> 阈值 p90 由 pilot 选定并冻结（`wpb_flowmask_pilot_verdict.md`）。

## §1 装置与完整性

| 项 | 状态 |
|---|---|
| 规模 | 3 臂 × 4 held-out 序列 × 3 seed = **36/36 完成，全部 `status=OK`** |
| L1 completion 闸 | **36/36 均 ≥95% 帧**（无一被淘汰，分母固定 4 未变） |
| G3 活性 | flow-mask 臂运行时 config 落盘 `enabled:true / source:flow_threshold / flow_quantile:0.9`；MRCS 臂 `SemanticMask.enabled:false`（mask-free）。三臂差异符合设计 |
| 代码 provenance | 远程 HEAD == `origin/ours-v3`（`c1ad6f1`），起跑前已 ff-merge 校验（事故后铁律） |
| 锚点纪律 | vanilla / MRCS **在本 campaign 自跑**，未借 WP-A 的行 |

## §2 主结果（ATE cm，mean ± half-range，3 seed）

| 序列 | vanilla | flow-mask (p90) | MRCS | 角色 |
|---|---|---|---|---|
| pt1 | 63.22 ± 10.65 | 51.41 ± 11.17 | **38.51 ± 2.51** | held-out① 主判据 |
| pt2 | 45.37 ± 2.02 | 51.07 ± 11.09 | **9.09 ± 0.31** | held-out① 主判据 |
| mv_no_box2 | 15.64 ± 14.14 | 6.23 ± 0.43 | **4.97 ± 0.29** | held-out② 同族次级 |
| balloon2 | 24.10 ± 0.56 | 23.30 ± 9.87 | **11.90 ± 1.85** | held-out② 同族次级 |

## §3 判定：配对 log(ATE_flowmask / ATE_MRCS)，δ=0.20

| 序列 | seed0 | seed1 | seed2 | mean | ATE 比 | 3/3 同号 | 分支 |
|---|---|---|---|---|---|---|---|
| **pt1** ① | +0.402 | +0.059 | +0.361 | **+0.274** | 1.32× | ✅ | **B1** |
| **pt2** ① | +1.883 | +1.509 | +1.738 | **+1.710** | 5.53× | ✅ | **B1** |
| mv_no_box2 ② | +0.299 | +0.198 | +0.182 | **+0.226** | 1.25× | ✅ | B1 |
| balloon2 ② | +0.782 | +0.040 | +0.957 | **+0.593** | 1.81× | ✅ | B1 |

**held-out①（主判据）= pt1 B1 + pt2 B1 ⇒ 2/2 一致 ⇒ 判决 B1。**
held-out②（同族次级，单独成行、不与①合并）同向 2/2，作方向旁证。

### 诚实边界（必须随结论同写）
- **pt1 的效应不均匀**：seed1 仅 +0.059，**远低于 δ**；三 seed 同号但幅度分散（+0.40/+0.06/+0.36）。
  按冻结判据（mean>δ 且 3/3 同号）成立，但**不得宣称 pt1 上差距稳健**。
- **mv_no_box2 勉强过线**：mean +0.226 仅略高于 δ=0.20，属"刚过实践相关界"。
- **绝对性能仍差**：pt1 上三臂全在 38–63 cm，MRCS 只是相对最好，**该 regime 对所有方法都是失败区**，
  不得写成"解决了 pt1"。
- **vanilla 有高方差格**：mv_no_box2 seed2 = 34.16（另两 seed 6.88/5.88）。**保留不截断**（失败即证据）。
- 3 seed/序列 ⇒ 逐序列 CI 很弱；全部结论表述为**可复现的描述性证据**，不作统计等价/显著性声称。

## §4 旁证一：朴素 flow-mask vs vanilla —— **不可靠**

| 序列 | mean log(van/flow) | ATE 比 | 3/3 同号 |
|---|---|---|---|
| pt1 | +0.212 | 1.24× | ✅ |
| **pt2** | **−0.103** | **0.90×（更差）** | ❌ |
| mv_no_box2 | +0.582 | 1.79× | ✅ |
| balloon2 | +0.122 | 1.13× | ❌ |

朴素 flow 阈值 mask **在 4 序列中仅 2 个稳定优于 vanilla，pt2 上反而更差**。
⇒ "随便加个抗动态处理就能拿到增益"**不成立**。

## §5 旁证二：MRCS vs vanilla —— 稳定且大

| 序列 | mean log(van/MRCS) | ATE 比 | 3/3 同号 |
|---|---|---|---|
| pt1 | +0.486 | 1.63× | ✅ |
| pt2 | +1.607 | **4.99×** | ✅ |
| mv_no_box2 | +0.808 | 2.24× | ✅ |
| balloon2 | +0.715 | 2.04× | ✅ |

**4/4 序列、3/3 seed 同号，1.63–4.99×。**

## §6 结论与叙事后果

**回答审稿 R2（"增益来自你们的方法还是随便什么抗动态处理？"）：**

> 在**同等 flow 信息预算**下（flow-mask 与 MRCS 共用同一套冻结离线 RAFT flow），
> 朴素 flow 阈值 mask 相对 vanilla **时好时坏**（4 序列仅 2 个稳定改善，pt2 上更差），
> 而 MRCS 在 **4/4 序列、3/3 seed** 上稳定优于 vanilla（1.63–4.99×），并在 **4/4 序列**上
> 优于朴素阈值基线（1.25–5.53×，held-out① 2/2）。
> ⇒ 增益**不可**归因于"任意抗动态处理"，MRCS 的机制内核是必要的。

**处置**：
1. **flow-mask 列进主表**（prereg §七：无论落哪个分支都进表，审稿人已问出，藏了更糟）。
2. 与 WP-A 判决（A2-partial-redundant，难度分层适用域）**不冲突且互补**：
   WP-A 说"三组件非联合必要、按难度分层"；WP-B 说"整个 MRCS bundle 相对朴素基线是必要的"。
   合并叙事 = **有内核，但内核的组成随 regime 变化**。
3. **仍禁写** "competitive"（R5/M8 已定）、禁写超加性/不可分整体、禁写"解决 pt1"。

## §7 公平性 caveat（写进 method + limitation，不可省）

flow-mask 与 MRCS 使用**同一套冻结 backward RAFT flow `f_{t→t-1}`**（每帧只用该帧与前一帧，
**信息上因果**；离线预计算是为逐字节可复现 + 把 RAFT 移出 6GB 在线预算）。
本结果衡量的是"**同等因果 flow 信息下**，朴素阈值 vs MRCS"。
仍成立的 caveat = **在线 FPS 不含 RAFT 推理开销**（端到端在线代价本文未测）。

> **2026-08-15 更正（exp22）**：原文写作"同一套离线**双向** RAFT flow（未来帧可见、非因果）⇒
> 不支持任何'在线可部署最简基线'结论；causal 变体 = 后续工作第一项"。经代码 + 磁盘 manifest +
> 消费端三重核实，**该描述事实错误**：flow 一直是 backward-only、严格因果，不存在"causal 变体"
> 这项后续工作。判决 B1 的数值与配对结论不受影响，但先前的自我否定予以撤回。
> 完整核实链：`results/evidence/flow_causality_correction.md`。

---
**判决定稿 2026-08-15（exp19）。数据 `results/runs/WPB/WPB-CONFIRM/`（36 run），
判读脚本 `scripts/wpb_confirm_readout.py`。判据冻结于 prereg §七，未事后修改。**
