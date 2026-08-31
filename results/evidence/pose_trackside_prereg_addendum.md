# 预注册附录 —— exp37 的 tracking 侧正控制（发批前注册）

> 主预注册 = `pose_trackside_prereg.md`（commit `364da26c`）；判决 = `pose_trackside_verdict.md`
> （commit `e9ec3738`）。本附录**在第一个 run 之前 commit**，此后不改。
> 这一次是**真正的发批前注册**（主文件那次是读数前注册，因为 E 臂的 run 已存在）。

## 1. 它补的是哪个洞

exp37 判 `TRACKSIDE-INERT`：`P(E) = +0.3996` 落在 H-inert 预言 `+0.3911` 的 **0.0085** 内
（= 地板 0.0831 的 10%），离 H-material 预言 3.0 个地板。装置门 5/5 全过。

**缺口（判决文档 §4.1 自己写下的）**：动态惩罚 P 的正控制是 **mapping 侧**的
（`mask_mapping`，间距 3.1× 地板、逐 run 完全分离、失效对照 3/3）。
**没有任何正控制证明 P 对 tracking 侧介入敏感。**
⇒ 严格地说，`INERT` 只能读成「**没有本估计量能看见的效应**」。
若 P 对 tracking 侧本来就盲，那 exp37 的判决就只是在复述装置的盲区，不是关于机制的陈述。

这是 exp33 判据 #9 的正面用法：**门要写在主判据之前、且真的执行**。本轮是补一条**事后**发现
缺失的门 —— 照记，不掩饰：主判决先发了，门后补，所以判决的最终效力取决于本批。

## 2. 装置（单变量，走已有代码路径）

新臂 `pba_trackside_hard_balloon.yaml`，相对 E 臂 `pba_trackside_only_balloon.yaml`
**唯一差异 = `SemanticMask.hard_tracking_mask: true`**。

机制（`utils/slam_utils.py:126-153`，代码已读，非推测）：

```
tracking_dynamic_soft is None      (迭代 0..9,   reliability soft 尚未就位)
    -> get_loss_tracking_rgbd_flow_mask      硬 mask 生效        <- 通道①的现状
tracking_dynamic_soft is not None  (迭代 10..99)
    -> hard_tracking_mask 为假: get_loss_tracking_rgbd_soft      硬 mask 被整条旁路
    -> hard_tracking_mask 为真: get_loss_tracking_rgbd_hardsoft  硬 mask 合成进 soft
```

⇒ 本 flag 把通道①的作用域从 **10/100** 次跟踪迭代扩到 **100/100**。
该路径由 `configs/rgbd/experiments/p6_mason/*` 在用，default-off，**主干一行不动**。

规模：balloon × 3 seed = **3 run**（Phase 0 纪律：只看机制诊断，**不看 ATE**）。

## 3. 装置门（收批后逐 run 验，任一不过 ⇒ 该 run 不进读数）

| 门 | 判据 | 为什么可测（发批前已确认） |
|---|---|---|
| **H-0** | config 解析后 `enabled=T, mask_mapping=F, mask_insertion=F, hard_tracking_mask=T`，且与 E 臂**唯一差异**是最后一项 | 由 `tests/test_pba_ba_coupling.py::TestPBATracksideHardConfig` 钉住 |
| **H-1** | 硬 mask 真的进了跟踪损失：本臂必须走 `hardsoft` 分支 | 该分支存在且被 p6_mason 臂用过；由 H-0 的 flag + 代码路径唯一性保证 |
| **H-2** | 插入门仍**不响**（0 次）、`mad_excl_semantic` frac ≥ 0.95 | exp36 在 E 臂上已 6/6 拿到（G1/G3 同一装置） |
| **H-3** | 忠实性锚 G-A：重算 ATE/RPE 与出厂 CSV 差 ≤ 5e-3 cm | exp37 已 22/22，max\|Δ\| 0.00005 cm |

## 4. 判读规则（**跑前写死**，地板与口径全部由 exp37 import，不重新拟合）

口径 = 运动匹配分层（exp37 的 PRIMARY），地板 = **0.0831**（exp37 从 4 对同 config 同 seed
复跑量出，本轮不重量），`P(E) = +0.3996`（exp37 实测）。

| 落点 | 结论 |
|---|---|
| `|P(E-hard) − P(E)| > 0.0831` | **APPARATUS-TRACKING-SENSITIVE** ⇒ exp37 的 `TRACKSIDE-INERT` **站住**，含义收窄为「通道①**在其当前 10/100 的作用域内**买不到动态特异的逐帧跟踪改善」 |
| `|P(E-hard) − P(E)| ≤ 0.0831` | **APPARATUS-TRACKING-BLIND** ⇒ exp37 的判决**降级为描述性**，不得再写成关于 tracking 侧机制的结论；下一步改换终点而非加 seed |

**不预言方向。** 放大通道①既可能降低 P（硬 mask 有用）也可能升高 P（全程剔除大片像素
⇒ 位姿约束变弱，P1b 已测到「剔除 ⇒ H 变小 ⇒ 放大 nuisance」这个杠杆效应）。
**门问的只是「P 会不会动」，方向留给读数** —— 这正是 exp36 那条设计对了的 G3 的做法。

**停跑规则**：若 `range(P(E-hard))` 逐 seed 极差 > 0.1200（exp37 注册的停跑阈值）
⇒ 本门 **NO VERDICT**，不贴 SENSITIVE/BLIND 任一标签。

## 5. 本附录不做什么

- 不看 ATE（Phase 0）；不因本批结果改 exp36 的 trackside ATE 判决（仍 INDETERMINATE）；
- 不改 exp37 已 commit 的任何数字、阈值或标签 —— 本批只决定那个标签的**效力等级**；
- 不扩序列（balloon 是唯一有协变量且地板可测的序列，见主预注册 §7）。
