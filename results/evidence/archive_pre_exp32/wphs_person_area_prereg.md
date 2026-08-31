# WP-HS Step 1 预注册（person 面积统计）— 冻结于 2026-08-15，exp22

> **本文件在运行 `scripts/wphs_person_area_stats.py` 之前提交，判据不得事后修改。**
> 上位冻结来自 exp21 交接文档 `NEXT_SESSION_PROMPT.md` §3/§4（θ=20% 已在那里定死）；
> 本文件只补上 exp21 没有写死的一件事：**"干净分开"的可操作定义**。

## 1. 被检验的假设（H1，来自 P7 后续）

P7（`results/evidence/p7_cuesplit_verdict.md`，48/48 run，3 seed）证明 Reliability 内部
**需要 regime-aware cue selection**，但没有给出 selector。H1 是候选 selector 中最简单的一个：

> **H1**：序列级 person 面积比 > θ ⇒ 用 geometry-only cue；否则用默认 both。

P7 已知的"正确答案"（各序列 mean ATE 最低臂）：

| 序列 | P7 最优臂 | H1 需要它落在 |
|---|---|---|
| balloon | geo | > θ |
| mv_no_box2 | geo | > θ |
| pt2 | geo | > θ |
| mv_no_box | **both** | ≤ θ |

pt1 / balloon2 未参加 P7 ⇒ 它们的面积比是 H1 的**预测输入**，不是拟合数据。

## 2. 统计量定义（跑前冻结）

- **主统计量**：逐序列**帧平均** person mask 面积比。
- **mask 口径必须与 mask-ON 臂完全一致**（否则"selector 用的是系统已有量"这句话作废）：
  Mask R-CNN ResNet50-FPN，COCO person=1，conf ≥ 0.5，mask ≥ 0.5，**dilate_px = 7**
  （直接调用 `utils/semantic_mask.compute_semantic_dynamic_mask`，不另写实现）。
- **帧集合**：`TUMParser`（frame_rate=32）+ `TUMDataset` 去畸变，与 SLAM 消费的帧逐帧相同。
- 次要量（**不参与判决**，仅稳健性展示）：median、p10/p90、dilate_px=0 的裸面积比、
  检测率（有任何 person 像素的帧比例）。

## 3. 判决规则（PASS 才允许花 GPU 跑 Step 2）

θ = 20%（exp21 冻结）。geo 组 = {balloon, mv_no_box2, pt2}，both 组 = {mv_no_box}。

- **C1**：min(geo 组 mean 面积比) > 20%
- **C2**：mv_no_box 的 mean 面积比 ≤ 20%
- **C3**：margin = min(geo 组) − mv_no_box ≥ **5 个百分点**（不接受发丝级间隔）

**C1 ∧ C2 ∧ C3 = PASS** ⇒ 执行 Step 2（pt1 × {selector, both} × 3 seed，判据见
`NEXT_SESSION_PROMPT.md` §4-P1，同样不得事后改）。
**任一不成立 = FAIL** ⇒ **不跑 pt1 6 runs**，不花 GPU；结论写成
"sequence-level semantic heuristic 在数据统计层面就分不开 regime"，P7 的 future-work 措辞保持不变。

## 4. 跑前就必须承认的方法论弱点（无论 PASS/FAIL 都写进文档）

1. **自由度几乎为零的"验证"**：训练集只有 4 个序列，且是 3-vs-1 划分。任何把 mv_no_box
   排在一端的单调标量都会"干净分开"。因此 **PASS 也只是必要条件，不是 H1 成立的证据**；
   真正的检验只能来自未参与的 held-out 序列（pt1）。
2. **因果链未证**：person 面积比大 ⇒ geometry cue 更可信，这条机制没有独立证据，
   目前只是与 P7 结果相容的描述性关联。
3. **定位**：H1 是 **offline sequence-level configuration selector**，不是 online per-frame
   动态检测；它在配置层而非算法层，因此即使成立也不构成"我们做了自适应 cue 选择"的主张
   （禁词表 §7 仍然生效）。
4. Step 2 若执行，**定位为 exploratory**，不作核心贡献；成败都记录。

---

**结果与判决写入**：`results/evidence/wphs_person_area_characterization.md`（本文件不再改动）。
