# 更正：冻结 RAFT flow 是**因果**的（backward f_{t→t-1}），"双向/未来帧可见"是我们自己写错的

> 2026-08-15（exp22）。触发：codex 对抗审把"非因果 flow ⇒ 在线 SLAM 主张不成立"列为头号盲点
> （置信度 0.95）。核查代码与磁盘产物后，**该质疑对 MRCS 不成立**——但它逼出了一个更糟的问题：
> **我们在 8 处文档/代码注释里自己写错了事实，并据此给论文自加了一条不存在的限制。**

## 1. 事实（三重独立确认）

| 来源 | 证据 |
|---|---|
| 生成器 `scripts/build_flow_raft.py:124` | `for t in range(1, n):` → `compute_flow(model, ..., rgb[t], rgb[t-1])`，保存到 `stems[t].npy`。**只用帧 t 与 t−1** |
| 产物 manifest（磁盘实测） | `rgbd_bonn_balloon/flow_raft/manifest.json` 与 `f3_walking_xyz/flow_raft/manifest.json` 均为 `"direction": "backward (f_{t->t-1})"` |
| 消费端 `utils/reliability_signal.py:341-370, 405` | `f_obs` = "frozen BACKWARD flow f_{t→t-1} (px), current-anchored"；K 窗 consensus 把**过去**帧 (t−i) 向当前 t 做 backward warp。**没有任何前向/未来帧路径** |

⇒ **reliability signal 在信息内容上严格因果：任一时刻只用帧 ≤ t。**
WP-B 的朴素 flow-mask 基线读同一批 `.npy`（`utils/flow_mask_baseline.frozen_flow_magnitude`），**同样因果**。

## 2. 写错的地方（原文 → 更正）

原文（8 处）："两臂共用同一冻结离线**双向** flow（**未来帧可见、非因果**、预计算）⇒
**不支持任何在线可部署最简基线结论**；causal（forward-only）变体 = 后续工作第一项。"

**这句话有三处错**：
1. flow 不是双向，是 backward-only；
2. 不存在"未来帧可见"，因此**不是非因果**；
3. "causal 变体 = 后续工作"是空的——**已经就是 causal 的**，没有这个后续工作。

## 3. 更正后的正确表述（写作时用这一版）

> 冻结 RAFT flow 是 backward `f_{t→t-1}`，任一帧只消费该帧与其前一帧，**信息上是因果的**。
> 之所以离线预计算，是为了 (a) 让所有臂/seed 拿到**逐字节相同**的 `f_obs`（受控对照的前提），
> (b) 把 RAFT 挪出 6 GB 的在线显存/延迟预算。这是**调度与工程选择，不是信息选择**。

**仍然成立的诚实 caveat（不能删，只是换成对的那条）**：
- 我们报告的 online FPS **不含 RAFT 推理开销**（它被预计算了）；端到端在线部署要额外付这笔钱，
  本文未测量该端到端代价。
- `utils/flow_raft.py` 顶部记录的 online-incremental RAFT 变体存在于设计中，但**未做端到端基准**。
- 因此正确的限制是"**在线运行时代价未测量**"，**不是**"用了未来信息"。

## 4. 对已有判决的影响

- **WP-B 的 B1 判决本身不变**（数值、配对、seed 一致性全不受影响）。
- 但 B1 的适用范围**变强**：既然两臂共用的是**因果** flow，B1 就是"同等**因果** flow 信息预算下，
  朴素阈值 vs MRCS"的比较，**可以**支持"最简在线基线不够用"的论述（附带上面的 runtime caveat）。
  先前那句"不支持任何在线可部署最简基线结论"是**过度自我否定**，予以撤回。
- 冻结的预注册文件 `wpb_flowmask_prereg.md` **不改判据**，只在文末追加指向本文件的更正说明
  （判据冻结纪律：预注册的**判据**不可事后改；对**事实描述错误**的更正以追加方式记录）。

## 5. 已修正的文件

`utils/flow_mask_baseline.py`（docstring 公平性段）、`utils/flow_raft.py`（`load_frozen_flow`
误写 "forward-flow"）、`results/evidence/wpb_flowmask_verdict.md`、
`results/evidence/18seq_rendering_main_table.md` + 其生成器 `scripts/build_18seq_main_table.py`、
`our_method/{02-method,03-results,ours-method}.md`、`NEXT_SESSION_PROMPT.md`、
`results/evidence/wpb_flowmask_prereg.md`（追加更正说明，判据未动）。

## 6. 方法论教训

一条**没有人验证过的自我限制**在 4 个会话里被逐份文档转抄，差点写进论文的 limitation。
外部对抗审（codex）的价值不在于它说对了——**它这次的头号质疑是错的**——而在于它逼我们去核代码。
**判据**：凡"我们做不到 X"这类自我否定，与"我们能做到 Y"同样需要证据；转抄不算证据。
