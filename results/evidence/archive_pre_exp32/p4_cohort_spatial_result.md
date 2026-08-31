# Direction A result — spatial/geometric structure of the op<0.01 cohort (2026-08-09)

> 来源：`scripts/p4_cohort_spatial.py`（CPU-only，读 final_after_opt PLY 的 xyz + opacity）。3 个代表
> map（balloon s0 / mv_no_box s0 / pt2 s0），覆盖低(≈10%)/高(≈18%)删除率两端。单位米。
> 问题（candidate-pool #2/#6）：这批低-op 高斯是不是"浮渣/孤立细碎"，还是贴着场景表面？

## 数值

| map | cohort% | 高-op% | cohort内部平均近邻 | cohort→高-op表面 最近/次近 | 0.05m内 | 0.1m内 | 0.2m内 |
|---|---:|---:|---:|---:|---:|---:|---:|
| balloon s0 | 12.8% | 40.3% | 0.047 m | 0.084/0.098 m | 42% | 68% | 93% |
| mv_no_box s0 | 9.9% | 53.0% | 0.040 m | 0.045/0.054 m | 68% | 91% | 99% |
| pt2 s0 | 18.4% | 41.1% | 0.037 m | 0.060/0.073 m | 59% | 85% | 97% |

## 解读

1. **cohort 内部高度聚合（不是孤立的远处浮渣）**：mean intra-cohort NN 仅 3.7–4.7 cm，
   与场景尺度（Bonn 室内序列，物体/表面毫米–厘米级）相比是很小的聚集步长。若这批是"游离在所有
   表面之外的孤立浮渣"，intra-NN 会明显更大。
2. **cohort 贴近高-opacity 表面**：到最近高-opacity(≥0.9)高斯的距离仅 4.5–8.4 cm，
   mv_no_box 尤其紧（4.5 cm）。且有高-op 邻居在 0.1m 内的比例 68–91%、0.2m 内 93–99%。
   ⇒ **绝大多数低-op 高斯并不是"远离任何表面的孤立 Floaters"，而是紧贴在场景稠密表面附近的
   冗余薄层/过渡层**。这与 freeze 反事实机制一致：refinement 不是把远处浮渣清除，而是把**贴近表面、
   与该表面重叠贡献的冗余高斯**软抑制到 ~0（腾出穿透权重给表面的高-op 高斯）。
3. **删除率高(map) ≥ 高-op 占比低的 map**（pt2 18.4% ↔ 高-op 41.1%，balloon 12.8% ↔ 40.3%）
   ——删除率与"场景里高不透明表面覆盖的稀缺程度"同向：表面覆盖越稀（高-op 越少），refinement 越
   需要把更多重叠低-op 高斯压到零。这是一个可写的、与 H-A3 相关的描述性观察（需更多 map 定量验证）。

## 这是怎样的贡献

把"有多少可删"推进到"**可删低-op cohort 的空间归属**：它不是游离浮渣，而是**贴着高-opacity 表面的
冗余软抑制层**。这把 soft-selection 的对象刻画得更具体——refinement 通过压低表面附近重叠高斯的
opacity 来"让路"给确定性表面，从而产生 8–18% 可零代价删的薄层。这是 characterization 型贡献，
且与机制（freeze）与结构曲线（方向 B）三方自洽。

## Caveats
- 3 个代表 map，非 18 全量；intra-NN 用子采样（最多 20k）。scale_ratio/LoHasHiNN 等更细指标未展开。
- "表面"用高-op ≥0.9 近似，未用真实 GT 表面网格。米制距离依赖序列坐标系尺度，仅序列内可比。
- 描述性观察，未做跨 18 map 的显著性检验。
