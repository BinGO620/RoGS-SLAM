# Codex 咨询：exp27 架构审视与技术路径（2026-08-19）

## 咨询背景

exp27 交叉验证暴露根本问题：
- async50 在 3090 稳定(5/5)、2060 不稳定(2/3)
- balloon 动态序列 async50 vs async10 仅 16% 改善，非之前的 14×
- 证实 14× 来自 MRCS vs vanilla，不是 iter_per_kf 调参
- 项目处于"不知道怎么办"的决策点

**咨询模型**：gpt-5.6-sol（本地 codex 配置）
**咨询时间**：2026-08-19
**参与角色**：codex（独立技术评审）、claude（本项目）、user（最终决策）

## 核心问题

向 codex 提出 4 个技术问题：

1. **根因诊断**：dense KF (215 vs 20) 导致静态序列失败，是 3DGS 架构根本问题还是工程调参问题？
2. **简化假设**：mask-guided static-only mapping（不 map 动态，只过滤）是否技术可行？
3. **Reliability 必要性**：在有 semantic mask + Huber loss 的情况下，reliability weighting 何时必要？
4. **路径推荐**：1-2 周发表时间线下，哪条技术路线成功概率最高？

## Codex 判断（原文精华）

### 1. 根因诊断

**结论**：不是 3DGS 根本限制，是工程/算法耦合失败，但有三层叠加：

```
① vanilla MonoGS 本身在 f3_st_hf 就脆弱（~1/5 失败率）
   ↓
② dense KF (gap_cap=5 → 215KF) 饿死后端
   - 队列永不为空 → 自由跑优化不触发
   - 每帧固定 iter_per_kf=10 → 地图持续变化但从未充分优化
   ↓
③ reliability signal 闭环缺陷
   - pose error → 被误判为 dynamic flow
   - → 下权重静态像素
   - → pose 更差（正反馈循环）
   ↓
结果：把 vanilla 的"偶尔失败"变成"必然失败"
```

**关键洞察**：
- f3_st_hf 对 vanilla 本身就是临界序列（exp26 已测得 vanilla 4/5 失败）
- 你们的方法把它推过了悬崖
- async50 修复的是 ② 但没解决 ①③，所以硬件依赖

### 2. Mask-only 简化方案

**结论**：技术可行，是最高成功概率路线

> "Mask-guided static-only mapping is technically sound and is the highest-probability fallback."

**理由**：
- 对 camera tracking + 静态背景建图，过滤动态像素是正确策略
- 3DGS 不需要 dense temporal KF 或复杂 reliability model
- 需要足够的、分布良好的静态观测来优化 pose 和 Gaussian map

**限制**（明确的）：
- Semantic mask 必须高召回率（漏检 → 地图污染）
- 假阳性 → 孔洞、tracking 约束减少
- 新暴露背景插入慢
- 不处理深度孔洞、motion blur、反射、非语义 outlier
- **这是 static-background SLAM，不重建动态物体**

**发表性判断**（冷水）：
> "mask-only is a valid dynamic 3DGS SLAM method, but probably not a strong novelty claim by itself. Its publishability would come from a careful 3DGS-specific evaluation and lifecycle design, not from the mask operation alone."

**需要证明**：为什么 3DGS 比 feature SLAM 更需要专门的 mask-guided design？

### 3. Reliability 必要性

**结论**：不是"必要"或"冗余"，是"有条件的增强"

**有用场景**：
- 未知或未识别的动态物体
- 部分 mask 失败
- Motion blur 和 rolling shutter
- 无效或噪声深度
- 镜面/非朗伯区域
- 只是部分不可靠的 flow/geometry outlier

**失效场景**：
- 近静态序列上，ego-motion residual 被误判为 dynamic
- 循环失败：`pose error → bad flow → downweight static → worse pose`

**当前状态判断**：
> "it is not safe as a mandatory component because its cues depend on the estimated pose"

**正确定位**：
- reliability 是可选增强，用于 semantic mask 覆盖不到的 bad observations
- 必须 fail-safe 且 observability-gated
- 应在 ego-motion residual 不可靠时禁用，或用 ego-residual projection 修正
- **不应作为 minimum stable method 的一部分**，直到修正验证通过

**与 Huber loss 的区别**：
- Huber 作用于投影后的 residual magnitude
- Reliability 试图在 residual 主导优化之前改变贡献权重
- 不等价，但在静态场景上可能冗余

### 4. 推荐路径（1-2 周时间线）

**优先级排序**：

```
1. 立刻跑 Option A: sparse KF + mask-only
   - 最快可证伪（12 runs, 3h）
   - 给你稳定、可解释的 baseline
   - 测量：ATE, 失败率, KF 数量, Gaussian 数量, FPS, 静态区域渲染质量

2. 无论最终方法是什么，都做 Option B: queue-aware budget
   - 工程稳定化
   - 防止实现 artifact 污染对比
   - iter_per_kf = f(queue_depth) + 允许 idle optimization
   - 限制 Gaussian 增长率

3. Reliability 作为可选增强
   - 验证 ego-residual projection 或保守闸门
   - 验收标准：保持动态增益 + 不退化静态序列
   - 在此之前，报告 mask-only 为核心，reliability 为 ablation

4. 不做 Option C (adaptive config) 作为主要贡献
   - 除非证明 principled regime detector + 固定决策规则
   - 否则看起来像 post hoc tuning

5. 不做 Option D (explicit dynamic object tracking)
   - 改变问题范围
   - 引入大量新失败模式
   - 超出时间线
```

**推荐论文结构**：

```
核心：static-only mask-guided 3DGS mapping + sparse budget-controlled KF
工程：queue-aware asynchronous optimization
可选增强：reliability weighting + ego-motion-residual protection
诚实限制：不重建动态物体
```

**成功路径判断**：
> "This path gives you the best chance of obtaining a stable baseline, a clean ablation story, and a publishable contribution without relying on hardware-specific behavior or an unreliable bundled kernel."

## Claude 与 Codex 的对比

### 一致点

1. **技术路线**：都认为 sparse KF + mask-only（Option A）最该先试
2. **根因**：都认为 dense KF 饿死后端 + reliability 循环依赖
3. **时间线**：都认为 1-2 周内 Option D 做不了

### 差异点

**Codex 更谨慎**：
- 明确指出 mask-only "probably not a strong novelty claim by itself"
- 强调需要"3DGS-specific evaluation"才可发表
- 把 reliability 定位为"optional enhancement"，不是核心

**Claude 更激进**：
- 认为"简单但有效"本身可能是贡献（对抗过度工程化）
- 愿意赌"mask-only 在 3DGS 上比 ORB-SLAM2 更需要专门设计"

**Codex 的冷水（关键）**：
即使 Option A 技术上成立，仍需额外论证"为什么 3DGS 特殊"，否则发表困难。

## 决策建议

### 立刻做（今晚 3 小时）

**P11: Sparse KF + Mask-only baseline**

```yaml
method: "P11-SparseMaskOnly"
DynamicKeyframe: false
ReliabilitySignal: false
SemanticMask:
  enabled: true
  mask_mapping: true
  mask_insertion: false
RobustTracking: true
```

**实验**：{f3_st_hf, balloon, f2_xyz, mv_no_box} × 3 seeds = 12 runs

**判据**（codex 建议的指标）：
- ATE
- 失败率（frame 371 崩溃与否）
- Keyframe 数量（应回到 ~20）
- Gaussian 数量
- FPS
- 静态区域渲染质量（PSNR）

### 三种结果对应路径

#### A: mask-only 成立（f3_st_hf 不崩 + balloon 有改善）

**下一步**：
1. 写"3DGS-specific evaluation"：为什么 3DGS 比 feature SLAM 更需要 mask-guided？
   - 答案候选：3DGS 的 densification 会固化瞬态观测为 Gaussian
2. 可选：ego-protected reliability 作为增强
3. 论文定位：简单但针对 3DGS 特性的方法

**发表可行性**：中等（需论证"为什么简单"）

#### B: 静态稳定但动态无增益

**说明**：4-14× 确实来自 reliability / dense KF

**下一步**：
1. 实现 Option B (queue-aware budget)
2. 加回 reliability + ego-residual protection
3. 证明在动态有增益、静态不崩

**论文定位**：reliability-guided sampling for dynamic 3DGS SLAM

**发表可行性**：高（如果验证通过）

#### C: mask-only 仍崩溃（最坏）

**说明**：问题在更底层（MonoGS 本身 / 数据 / tracking）

**下一步**：
1. 接受 f3_st_hf 是超出能力的序列
2. 论文转向"诚实失败分析"或专注真正动态序列

**发表可行性**：低（但诚实）

## Codex 原话摘录

### 关于 mask-only 可行性

> "For camera tracking and a static background map, dynamic pixels are usually harmful observations. Filtering them before mapping is consistent with the basic dynamic-SLAM strategy used by feature-based systems. 3DGS does not inherently require dense temporal keyframes or a sophisticated soft reliability model. It requires enough well-distributed static observations to optimize camera pose and the Gaussian map."

### 关于 reliability 循环依赖

> "On near-static scenes, the self-motion residual becomes the apparent 'dynamic' residual, creating the circular failure: pose error -> bad rigid-flow residual -> downweight static pixels -> worse pose."

### 关于发表性

> "mask-only is a valid dynamic 3DGS SLAM method, but probably not a strong novelty claim by itself."

### 关于推荐路径

> "For a 1–2 week publication timeline, I recommend this order: [Option A immediately]... This is the fastest falsifiable experiment and gives you a stable, interpretable baseline."

> "The most defensible near-term paper structure is therefore: core: static-only mask-guided 3DGS mapping with sparse, budget-controlled keyframes..."

## 结论

Codex 判断：
1. **根因清楚**：vanilla 脆弱 + dense KF 饿死后端 + reliability 循环依赖
2. **mask-only 可行**：技术上 sound，但需论证 3DGS-specific novelty
3. **reliability 非必要**：是可选增强，不应是 minimum stable method
4. **优先 Option A**：最快可证伪，最高成功概率

**与最高准则的对齐**：
- "方法是我们的吗？" → mask-only 本身不是，需要 3DGS-specific evaluation 补强
- "对动态 3DGS SLAM 有用吗？" → 如果 Option A 成立，是的（static-background SLAM）

**下会话任务**：跑 P11 实验，根据结果选路径。
