# Orbit D — method-deepening brainstorm (2026-08-09, autonomous per NEXT_SESSION_PROMPT §四-D)

> 用户完全自主授权：发现新东西自己做实验验证，不要回头问选哪个方向。GPU 机时充裕（远程双 3090 + 本地 2060）。
> 核心发现 = terminal soft-selection cohort（op<0.01 软选择高斯，8-18%，可零代价删，纯 post-hoc 后处理观测）。
> 本文档 = 轨道D 的 brainstorm → 选方向 → 预注册 → 跑 → 验证 → 落盘的工作记录。
> 保持禁词表（ADC/compression-algo/online-compaction/general-improvement）；落点仍是"测量一个真实的结构事实"。

---

## 候选池（NEXT_SESSION_PROMPT 6 条 + 自由扩展）
1. **cohort 在线可预测性**：能否从在线 opacity logit 轨迹/渲染权重/几何位置预测 8-18% 软选择队列？→ 可能要改在线代码，风险高，先放后。
2. **cohort 空间/几何性质**：这批低-op 高斯位置分布结构（浮渣边缘 vs 场景内部？固定场景类别倾向？）→ **纯后处理离线分析，零 GPU，最便宜**。
3. **阈值响应的连续刻画**：0.01→0.1 连续扫描 removal%/dPSNR/cohort-weight 曲线 → 已有 `mc_opacity_deletion_curve.py`，可扩展，便宜。
4. **对下游的影响**：删后重优化收敛性 → 注意禁词，风险高。
5. **generalize 到 backbone 本身**：cohort 是否依赖 mask-both 骨干 vs vanilla MonoGS → **3090 机时充裕，补 1-2 序列 vanilla，增强普适性或坐实 limitation 诚实边界**。
6. **cohort 与场景内容/跟踪质量**：cohort 大小随序列的可变性（balloon 16% vs mv_no_box 9%）是否与场景结构有可写关联 → 结合 #2 一起做。

**优先级判断**：#2（空间几何性质，零 GPU 最便宜）+ #3（阈值连续曲线，已有脚本）是最快能落盘的、
且直接增强 characterization contribution 的两个方向。用它们把"soft-selection 的对象是什么"这个
核心问题做深，而不是只停留在"有多少可删"。

---

## 选定方向 A（#2 + #6）：cohort 的空间/几何结构刻画 + 与场景内容的关联

**要测的可证伪假设 / 结构问题**：
- H-A1: op<0.01 cohort 在空间上是否集中在特定区域（场景边缘 / 大目标内部 / 稀疏 floaters）？
  若集中在"边缘/浮渣"⇒ 佐证 freeze 反事实的"软抑制浮渣"机制；若散布在场景表面 ⇒ 削弱机制故事。
- H-A2: cohort 的空间聚合度（每个高斯最近邻低-op 高斯距离 / 与场景主表面距离）是否与删除率相关？
- H-A3: 序列间删除率差异（balloon 16% vs mv_no_box 9%）是否与场景结构统计（mover 面积 / 动态像素占比 /
  追踪质量 ATE）有单调关联？

**需要的数据**：18 张 P2-T prune final_after_opt PLY（已回拉本地）+ 每序列 GT pose / gt pose。全部离线。
**GPU**：0（纯 CPU 读 PLY + 几何计算 + 相关性）。
**若成立能加什么**：把"有多少可删"升级为"可删的高斯是可表征的一群空间结构"。若结果显示 cohort
集中在场景的动态/边缘区域，则与 freeze 机制的"软抑制"故事自洽，增强因果叙事的空间证据；
若显示散布，则至少坐实"软选择对象不是单一成因"的诚实边界（仍是贡献）。

## 选定方向 B（#3）：op 阈值连续扫描

已有 `mc_opacity_deletion_curve.py`（删 op<th，测 dPSNR）。把它做成：对 18 图、阈值
{0.001,0.002,0.005,0.01,0.02,0.05,0.08,0.10}，测 removal%、dPSNR、cohort-weight，画成曲线。
**纯离线重渲染，零训练，本地 2060 ~分钟/图**。
**若成立能加什么**：把"0.01 是最粗安全格"从单点 hack 变成完整结构特征曲线——显示 removal 与
dPSNR 的单调关系、0.01 落在曲线的哪一段（拐点之前？）。这是"结构特征的表征"而非算法。

**先跑方向 A（零 GPU 最便宜立即出数）**，跑完落盘后看是否直接跳到方向 C。

---

## 选定方向 C（#5，3090）：vanilla MonoGS 泛化

如果 A/B 的快结果空挡 + 远程 3090 机时允许，跑 1-2 序列 vanilla（无 mask 无 combined 骨干）的
final_after_opt，检验 op<0.01 cohort 是否 backbone-specific。这直接坐实/否定 skeleton P1 的
"跨前端外推克制" limitation，价值高（审稿人最可能的限制质疑就是"只在你的骨干上成立"）。

---

## 记录
每一步（brainstorm 完成 ✓ → 选方向 ✓ → 设计+预注册 → 跑 → 验证 → 落盘 → manuscript）在本文件
追加，commit 到 git。进程被杀时状态在 git 里。
