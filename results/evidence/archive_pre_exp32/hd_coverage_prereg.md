# H-D 预注册：mask-覆盖率分层下的 compactness 适用域假设

> **状态**：探索性、前瞻性、可证伪检查（exploratory prospective falsifiable check）。
> **不是**统计验证，**不报 p 值 / 显著性**，**不写"假设成立"**。
> 生成日期：2026-07-31（P2-T 发射**之前**）。第一个 P2-T run 之前 commit。
> GO/KILL + 叙事 = 用户保留（prereg §9、08-04 日期门）。

## 0. 这是什么，以及它刻意不是什么

H-D 由 P2-S-pt2 单 seed screening 触发（deferred 在 pt2 上 compactness 反向 G_def/G_prune=1.069× 且 ATE +43.4% 更差），用户据此提出「取长补短」方向。本文件把它从一句直觉**降格并固定**成一个可在 P2-T 上检查的、预先写下的形状——目的是防止看完 P2-T 之后再编规则（本项目复发病：效果不好就换故事）。

**它刻意不是什么**（每条都是 codex 对抗审查打出的窟窿，本预注册就此封堵）：

1. **不是统计验证。** 检验单位是**序列**（n=6 动态序列 + f1_desk 静态无定义），不是 run；seed 只估计每个序列的 G 比值噪声。balloon/pt2 是**生成假设的已见数据**，独立新检验最多 4 条（balloon2/mv_no_box/mv_no_box2/pt1）。即便 4/4 全中，也不报显著性——只报"方向一致 / 不一致 / 不可判"。
2. **不是可部署 gating 信号的设计。** 覆盖率用的 mover 区域来自**冻结 GTMC 评估 oracle**；上线时系统不知道真实 mover，"person mask 覆盖了多少 mover"**不可在线计算**。本预注册支持的是**适用域假设**（两机制各有域，按 oracle 覆盖率分层），**不是**可实现 hybrid gate。可部署 proxy = 未来工作，不在本论文。
3. **不是 per-KF hybrid 的性能证明。** prune/deferred 是全局 lifecycle，会改候选历史/densify/KF/轨迹（有滞后、非加性）。"某序列全程 deferred 更好"**推不出**"逐 KF 切换能同时取两侧最优"。论文里**不得**把"hybrid 原理上能同时拿到两侧"写成推论；只能写成待检验假设。机制实现（per-KF 分流代码）**从本篇砍掉**，留下一篇。
4. **不是单点判决。** "pt2 反向复现与否 = H-D 存亡"是错的：pt2 复现只确认生成假设的观察稳定，不证明覆盖率解释；pt2 不复现也可能只是 1.069× 落在 rate 噪声带内。见 §4 三分支。

## 1. 假设（一句话）

> compactness 的方向（G_def/G_prune ≷ 1）与 **person-mask 对 mover 的覆盖率**（离线 oracle 测）**同序**：覆盖率低（mask 漏 mover）⇒ deferred 优（<1）；覆盖率高（mask 已挡 mover）⇒ prune 优（>1）。

**机制故事**（screening 级，非判决）：mask 漏 mover 时 deferred 候选生命周期有动态可挡 ⇒ compactness 成立；mask 已挡 mover 时 deferred 候选确认无动态可挡，其 provisional 候选反而扰动 densify 预算 = 净负二阶效应 ⇒ prune 优。

## 2. 检验设计

### 2.1 分层信号（覆盖率，离线、零 GPU）

`scripts/hd_coverage_anchor.py` 对 6 条动态序列算三个口径的 person-mask 覆盖率：
- **(a) 逐帧 GTMC**（headline 分层信号）：Σ covered / Σ mover，像素求和，**全视频帧采样**（与臂无关——不用任一臂自己的 KF，KF 是内生的）。
- **(b) ±15 帧 GTMC 并集**：mover 计入若 ±15 帧内被 GTMC flag（缓解 oracle 漏静止 mover 的 under-flag）。
- **(c) 序列全并集**：漫游 mover 上界（balloon 饱和到 ~91%，附 union coverage，饱和值不当尖锐值读）。

锚点在 P2-T 发射**前**落盘（`results/evidence/hd_coverage_anchor.md`），覆盖率排序**在 G 比值存在前**就冻结。

### 2.2 待检验量（P2-T 的 G_def/G_prune）

P2-T 主表：7 序列（balloon/balloon2/mv_no_box/mv_no_box2/pt1/pt2 + f1_desk 静态）× 2 臂 × 3 seed，自跟踪。判据 **import** 自 SWEEP readout（逐字节同 R2-P03 全程用的那条）：rate=`refined_num_gaussians`；G_def/G_prune = deferred 均值 / prune 均值（同 campaign 同 seed 配对）。

### 2.3 检验 = 秩相关，不是阈值

**不设二元阈值**（看过 balloon/pt2 之后再选阈值 = 二点训练）。检验是：
- 把 6 条序列按覆盖率 (a) 排序（低→高），按 G_def/G_prune 排序；
- 看两个排序是否**同向**（Spearman 秩相关，符号为主）。

预测（在 G 比值未知时写下，见锚点文件秩表）：覆盖率低 ⇒ <1；覆盖率高 ⇒ >1。

## 3. 联合判据 + 带宽（防指标挑选）

只看 G 方向不够——更小的地图可能只是少建图，某臂 G 更小但 ATE/保真更差。**预声明联合判据**：
- **primary**：G_def/G_prune（同 campaign 配对比值）。
- **no-harm 约束**：ATE（`tracking_raw.csv` `ate_rmse_cm` 全轨迹）与两项保真（vac_depth ≤ 1.56cm、vac_psnr ≤ 0.28dB，与 R2-P03 同边界）不得越过预声明带宽。
- **ATE no-harm 预声明带宽**：单序列 deferred ATE 劣化 > **50%**（相对 prune）⇒ 该序列标注"deferred ATE 显著更差"，论文放弃该序列的 no-harm 措辞、改为诚实报告（**事后再定 = 移动球门**）。pt2 screening 是 +43.4%，带宽定在 50% 留余地；若 P2-T 多 seed 显示 deferred ATE 在多条序列上 >50% 劣化，则"ATE no-harm"作为**方法级定位主张**失败（叙事 D 仍成立，但不再包装为有 no-harm 保证的方法贡献）。

## 4. 三分支处置（跑前钉死，事后不得改）

对每条序列的 (G 比值, 覆盖率) 配对，按其 G 比值相对 **rate 噪声带**（<~2× own sd 不可分辨，HANDOFF 运维教训 3）判分支：

| 分支 | 条件 | 处置 |
|---|---|---|
| **可判** | \|G_def/G_prune − 1\| > 2× 较大 own sd（两臂 3 seed） | 记方向（<1 / >1），进入秩相关 |
| **不可判** | 带内（最可能，pt2 的 1.069× 即此） | 该序列不进秩相关，标 INDETERMINATE |
| **反向** | 可判且方向与预测**相反** | 记为反例 |

**整体 H-D 三分支**（看完全部 6 条后）：
- **CONFIRMED（方向支持）**：可判序列 ≥2 条 且 全部同向 且 无反例；不可判序列的覆盖率口径 (a) vs (b) 秩不翻转。
- **INDETERMINATE（不可判）**：可判序列 <2 条，或 (a)/(b) 秩翻转，或 ≥1 反例但带内。⇒ 论文写"方向性观察，数据不足以分层"，H-D 节降为一句话 limitation。
- **FALSIFIED（证伪）**：可判序列 ≥2 条 且 ≥1 反例方向稳定（多 seed 同号）。⇒ H-D 节删除，论文只留叙事 D。

**无论哪个分支，都不写"假设成立/验证通过"**；CONFIRMED 也只写"方向与预测一致，n=6 探索性"。

## 5. 高覆盖侧样本（pt1 的角色，本预注册的关键新增）

codex #4：H-D 最关键的"高覆盖 ⇒ prune 优"那半边，加 pt1 **之前**只由生成假设的 pt2 单独承重（n=1 post-hoc）。**pt1（Bonn person_tracking，纯人，未见）是 pt2 的同类未见兄弟**——是高覆盖侧第一个**独立**样本。其 GTMC 评估 mask 已于 2026-07-31 冻结（sha 06f9c475，本预注册之前）。不加 pt1，高覆盖侧 = 单点 post-hoc，H-D 不可声称"双侧边界"。pt1 的 de-risk 由 pt2 de-risk 承担（同类、combined 骨干已在 pt2 存活）。

## 6. 已知局限（必须随结论同引）

1. **覆盖率与类别组成共线**：pt1/pt2 纯人；balloon 人+气球；box 人+物体。H-D 在 n=6 上**无法区分**"mask 充分性"与"纯人 vs 人+物"——这是 stated limitation，不是此处可解的 confound。
2. **GTMC 是冻结 oracle 非 ground truth**：漏静止 mover ⇒ (a) 是真实覆盖率的下界；故报三口径。
3. **像素 ≠ 高斯**：coverage 是 depth-valid mover 像素比；deferred 插入时降采样 ⇒ G 比值不由覆盖率 1:1 预测。覆盖率**排序**预测，不预测**幅度**。
4. **box 家族双稳态**：自跟踪下 mv_no_box/mv_no_box2 跨低/高 basin。覆盖率秩良好定义；其 G 比值可能吵——三分支的 INDETERMINATE 处理。

## 7. catastrophic-run 规则（跑前钉死）

- **爆炸 seed 不得事后删**：每条序列 3 seed 全部逐 seed 展示（ATE + G + KF）。爆炸（ATE > 100cm 或 G 超出 3× 该序列中位）记为 CATASTROPHIC 但保留在表里。
- **不因爆炸补 seed 至无穷**：每序列固定 3 seed；若 3 seed 里 ≥1 爆炸，该序列 G 比值标注"含爆炸 seed，方向参考性降低"，进 INDETERMINATE 而非补跑至干净。
- seed-0 全序列 tranche 优先 + stop/go：seed-0 跑完先读数，若 ≥2 序列骨干崩溃（ATE>50cm 非爆炸义），停下汇报再决定是否继续——不盲目烧完 21h。

## 8. 与叙事的关系

H-D **不取消**叙事 D（诚实负结果 + 方法论贡献），而是给它一个**正向方法论出口**：测出两机制各有适用域，给出可证伪假设 + 离线分层信号。对 MMM（多媒体会议）这是比纯负结果更可投稿的形状。机制本身（per-KF 分流）是下一篇的开头，不是这一篇的补丁。

**08-04 叙事门**：默认落 D + 适用域边界；若 §4 落 CONFIRMED，加 H-D 假设一节；若 INDETERMINATE/FALSIFIED，H-D 降为一句话 limitation。**由用户定，本预注册不预判。**

## 9. 数据谱系披露（诚实）

P2-T 的 6 条 Bonn 序列及其旧骨干结果在本项目中**已被多次看过**——这不是"独立外部验证"，是"combined 骨干的新 run + 前瞻性内部检查"。论文须完整披露：balloon/pt2 是生成假设的已见数据；balloon2/mv_no_box/mv_no_box2/pt1 是未见数据但序列本身非新。H-D 标为 **prospective internal check**，不标 independent validation。
