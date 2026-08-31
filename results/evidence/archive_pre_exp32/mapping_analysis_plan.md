# Mapping 分析计划（exp34 Phase A）——定位 4–14× 增益的发生环节

> **假说**：3DGS SLAM 在动态场景下的瓶颈不是前端对动态像素的感知，
> 而是后端对异常观测的鲁棒聚合。
>
> **核心问题**：reliability 权重改变了 per-frame pose（P1c 说"几乎不"），
> 还是改变了 map（Gaussians 的存活/分布/opacity/obs count）？
>
> **已有证据**：效率表中的 `online_num_gaussians`、`mapping_iterations`、
> `mapping_calls`、`mapping_time_ms` 在不同臂之间已有差异；
> PLY 文件中每个 Gaussian 带有 `static_prob`、`static_obs_count`、`opacity`
> 等属性。

---

## Phase A：零 GPU 地图剖析

### A1. 同配置 reliability ON vs OFF（map 是否被改变）

| 运行 | 配置 | 路径 | ATE |
|---|---|---|---|
| balloon on | `reliability_screen/balloon_on` | `results/runs/reliability_screen/balloon_on/...` | ~? |
| balloon off | `reliability_screen/balloon_off` | `results/runs/reliability_screen/balloon_off/...` | ~? |

比较：
- n_gaussians（差异 = 被压制的高斯数量）
- opacity 分布（尾部低 opacity 高斯的存活率）
- static_prob 分布（ON 有多少低置信度高斯被保留）
- static_obs_count 分布（被多少帧可靠观测）
- 体积与各向异性比

### A2. mask-ON combined vs mask-free（是否改了地图的动态区域）

已有 226 个 PLY 可用，其中 `Combined` 24 个、`Combined-MaskOff` 11 个、
`Combined-Prune` 18 个。

### A3. 从效率表读取 mapping 预算

已有 `efficiency_raw.csv` 中的：
- `mapping_iterations` / `mapping_calls` = 后端被触发的频率与深度
- `online_num_gaussians` = 追踪结束后高斯数量
- `mapping_time_ms` = mapping 总耗时

不需要重跑任何实验。

### A4. 关键帧数量分析

从已有的 run 目录中计数 KF 数量（与 sparse KF baseline P11 比较）。

---

## Phase B：mapping 特定的新 run（需要 GPU，可能要发远程）

取决于 Phase A 的结果：

- 如果 Phase A 发现 **reliability 改变了 Gaussians 的存活/分布**，那么
  需要一个 mapping-only 消融：**tracking 用 GT pose + 只测 map 质量**
- 如果 Phase A 发现 **mapping_iterations 差异大**，需要一个 KF 选择消融

Phase B 必须遵守分阶预算（CLAUDE.md §1）：Phase 0 2 run → Phase 1 6 run。

---

## Phase C：渲染质量（终版图）

现有渲染主表显示 PSNR/SSIM/LPIPS 已基本持平，但需要补充：
- 动态区域的局部渲染质量（DynaPSNR 口径）
- 修复鬼影的视觉对比（定性但必要）
- 关键帧选择对最终渲染的影响
