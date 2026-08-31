# BA 耦合干预 Phase 0 — 实验装置与判据
#
# 问：mask 的增益（"保护背景高斯不被拉偏"）发生在 BA mapping 侧，
# 还是 tracking 观测加权侧？
#
# 装置：在 combined 配置上只改一个开关：mask_mapping = false。
# BA 不再剔除动态区域的高斯，但仍然挡动态高斯的插入。
# 两个独立起点 × balloon（440帧）× seed0 = 2 run。
#
# 控制量：eboth_balloon（完整机制）、control_maskfree_balloon（完全无 mask），
# 都已在 T2 3090 批次中跑完，存于 results/runs/T2/T2-QUOTA-3090/。

## 主判据（零假设 / 阈值，跑前注册）

**M1 机制诊断**（看机制是否真的在动）：
- `mask_mapping` 应该关闭 → tracking_raw 里没有 mask_mapping 相关日志 ≠ 失败
- tracking 完成率 100%（440 帧全跑完）
- 高斯数量应介于 control_maskfree 和 eboth 之间（机制"半开"）

**M2 opacity 下降是否消失**：
- 用 map_profile.py 读 final/point_cloud.ply 的 opacity 均值
- 对照：
  - eboth balloon opacity 均值 = 5.87（完整机制）
  - control_maskfree balloon opacity 均值 = 4.79（无 mask）
  - **本 run 的 opacity 均值应 > 5.5**（接近 eboth，非 maskfree）→ 假说成立
  - 若 < 5.0（接近 maskfree）→ 假说不成立

**M3 ATE 是否保住**：
- eboth balloon 3-seed ATE = 3.09 ± 0.18 cm
- control_maskfree balloon 3-seed ATE = 13.34 ± 0.83 cm
- **本 run ATE 应 < 5 cm**（保住 eboth 水平）→ 支持假说
- 若 > 8 cm（接近 maskfree）→ 反对假说

## 判决规则

- **IF** M2 opacity > 5.5 AND M3 ATE < 5 → **假说支持**：增益在 BA mapping 侧，
  进 Phase 1（加 seed + 第二序列）
- **IF** M2 opacity < 5.0 AND M3 ATE > 8 → **假说反对**：mask 的作用在 tracking 侧，
  回头检查 PLY 分层中的 tracking 具体效应
- **ELSE** → INDETERMINATE，看是否值得补 run

## 技术细节

- config: `configs/rgbd/experiments/pba_ba_coupling/pba_mapping_off_balloon.yaml`
- 继承自 combined 主表 overlay（method_combined_maskboth_prune.yaml），
  唯一改动 SemanticMask.mask_mapping = false
- 2 run：seed 0 本地 2060，seed 1 远程 3090（并行）
- 产物：point_cloud/final/point_cloud.ply（opacity）+ tables/tracking_raw.csv（ATE）
