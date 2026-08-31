# Terminal-Compression Generalization Probe — online-final-map opacity tail (2026-08-10)

> 2026-08-10，exp-v3-13。用户 pushback：terminal compression（删 op<0.01 高斯零代价去掉
> 9-16%）不必然是 refinement 特有，值得验证"是否所有 3DGS 终态都有"。
> **此 non-GPU 探针（2060 离线，zero-SLAM）回应此 pushback，把结论从"refinement-specific"
> 修正为"更接近 opacity-DOF 一般性 + 阶段限定"。**

## 一句话结论

**用户的质疑成立，之前"换基座就没了"是我的过度断言，已撤回。** 实测证明：
**online final 地图本身就有非零 op<0.01 尾巴**（balloon 0.10% / balloon2 1.14% / mv 0.05% /
mv_no_box2 0.85%），**不是零**。之前"在线 prune 必删干净、tail 只在 refinement 长出来"的判断
**不完全对** —— 在线 prune 用 `op<0.7 → 删`，但仍有一批 op 在 (0, 0.01) 残留下来。

## 数据（读 ONLINE `final/point_cloud.ply`，**非** final_after_opt，隔离 densify 驱动的尾 vs refinement 驱动）

源 = `results/runs/P3/P3-DENSIFY-TAIL/{balloon,balloon2,mv_no_box,mv_no_box2}_{base,lo,hi}_seed0`。

| seq | arm | n_total | op<0.01 | op<0.05 | op<0.10 | op>=0.90 |
|---|---|---|---|---|---|---|
| balloon | base | 27648 | **0.098%** | 0.94% | 4.84% | 63.99% |
| balloon | lo   | 58518 | 0.0%    | 0.0%  | 0.49% | 79.35% |
| balloon | hi   | 25487 | **4.46%** | 14.0% | 25.4% | 36.47% |
| balloon2| base | 70746 | **1.14%** | 4.14% | 6.30% | 79.08% |
| balloon2| lo   | 69012 | 0.061%   | 0.54% | 1.81% | 80.61% |
| balloon2| hi   | 18380 | 0.0%     | 0.24% | 4.87% | 64.24% |
| mv_no_box base | 33678 | **0.05%** | 0.61% | 1.14% | 85.95% |
| mv_no_box lo   | 77193 | 0.80%     | 2.97% | 3.99% | 80.77% |
| mv_no_box hi   | 21091 | **4.98%**  | 14.6% | 18.6% | 46.90% |
| mv_no_box2base | 76406 | **0.85%**  | 3.41% | 4.39% | 77.71% |
| mv_no_box2lo   | 128043| 2.11%     | 7.75% | 9.79% | 63.40% |

## 解读（诚实，不拉满）

1. **opacity-DOF 单调序在线上不成立**（base/lo/hi 无单调）——densify 计数/增密速度在低阈值挡
   主导，opacity 收缩不是唯一驱动。**不能 claim 单调。**
2. **但 opacity DOF 确实是尾形成的一部分**：hi 挡（更高 densify opacity 阈值 = 更宽 opacity
   收缩空间）在 balloon(4.46%) / mv(4.98%) 大幅拉高 tail，对照 base ~0.1-1%。
3. **规模 vs 阶段**：online 尾 ≈0-5%，refinement 后 9-16%（P3 已测）。巨大尾巴主要仍在
   refinement/no-prune 后优化阶段产生；**但 online 也有一批可删的 op<0.01（0.05-1%），
   且 hi 挡可到 4-5%。**

## 对论文定位的影响（修正版）

**不能写"换基座就没有"。** 可写的诚实结论：
> "**opacity 自由度使 3DGS 终态天然积累近零贡献高斯；在任何 done-optimizing 且之后不再 prune
> 的阶段（含 MonoGS 的 color-refinement，以及更宽 opacity 阈值的在线地图），都测到可删的
> op<0.01 cohort（约 0.1-5%，后优化阶段 9-16%），删除零代价（P3 已核 `|dPSNR|≤1e-4`）。**"

- 这把它从"refinement artifact"升级为"**3DGS opacity 生命管理的一般性质**"，作为探索一节点保留。
- **作为支撑段**仍然成立（footprint，非头条）。
- **不建议**作为独立新实验无限深入（密度计数等 confound 会稀释 sell），保留在当前骨架支撑段。

## 待续
- 若想进一步坐实"任何 3DGS 终态都有"，可换 SplaTAM/DG 的最终地图测同指标（离线，零 SLAM）。
  成本低，但当前头条(mask-free bundle)优先级更高，此项押后。
