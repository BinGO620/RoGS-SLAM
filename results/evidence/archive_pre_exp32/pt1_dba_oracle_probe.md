# pt1 KF-BA 重启前提探针 — DBALite GT-oracle + conditioning（exp-v3-14）

> 2026-08-11。只读探针（`DBALite.oracle: true`，零核心改动，纯 config toggle）。
> 回答：在 **mask-ON + edge3** 的 person 序列（pt1）上，masked geometry 是否偏好 GT？
> 这是 KF-BA 重启的前提判定 —— 之前 `run_dba_v0` 是在「无多视图 mask 参与 / edge3 未落地」的状态判负的。
> 数据 = P6-DBA-ORACLE 批（pt1 × 3 seed，3090 双卡只读跑）。

## 装置
- config：`configs/rgbd/experiments/p6_mason/pt1_dba/p6_mason_pt1_dba_oracle.yaml`
  （inherit pt1_edge3 → 叠 `DBALite: {diagnostic: true, oracle: true}`）。
- `slam.py` 在 `final_pose_refinement()` 之后、`save_final_tracking_raw()` 之前调 `run_dba_oracle`（只读，
  不写位姿）；`run_dba_diagnostic` 在 backend 的 `color_refinement` 阶段（`eval_rendering` 门内）。
- 8 个 GT-direced t 插值步（t=0 online → t=1 GT），主指标 = masked geo-resid + photo-resid + ate-proxy。

## 结果（pt1 × 3 seed，3/3 已出）

| seed | online geo-resid (t=0) | GT geo-resid (t=1) | per-edge GT-fits-better | GEO verdict | photo verdict |
|---|---|---|---|---|---|
| 0 | 0.01127 m | 0.03632 m | 2/245 | **BIASED** | PHOTO-BIASED |
| 1 | 0.01105 m | 0.03620 m | 3/245 | **BIASED** | PHOTO-BIASED |
| 2 | 0.01131 m | 0.03622 m | 4/245 | **BIASED** | PHOTO-BIASED |

（oracle 探测跑出 3 个 seed 的 ATE = **8.66 / 7.75 / ~9** cm，RPE ≈ 1.6，即探针跑本身是正常稳定的 edge3 行为——BIASED 判定不是异常 run。）

- **PHOTO 同向 BIASED**：photo-resid 在 GT 处 0.05846 ≥ online 0.03010，光一致性也不偏好 GT。
- **per-edge 压倒性**：online-fits-better **99%**（239-243/245）——GT 位姿几乎在所有 masked 几何边上
  都比当前在线估计更差，3 seed 全同。
- **ate-proxy 失真**：t=0 158cm → t=1 爆表（几十 m 到 km 级），GT 位姿在 KF0-gauge 下被抛走。
  （这正是 `dba-photo-weighted-ba-plan` memory 里记录的已知口径陷阱：KF0-gauge 带 ~96% 全局对齐量，
  **不能用它判位姿优劣**；真正的判定 = geo-resid 方向 + headline SE(3)-Umeyama 口径，本表以 geo-resid 为准。）

## 裁决（3/3 同向，定稿）
- **masked geometry 和 photometric 在 mask-ON + edge3 下仍不偏好 GT**（3/3）——与 `run_dba_v0` 时代
  （`e94158d` / `687af1b`）判负的机制完全一致。**不是"没多视图/没 edge3"造成的，是这套 masked-container 的
  几何目标本身方向不对。**
- ⇒ **KF-BA 重启前提未改变**：`DBALite.enabled` 保持 default-off，run_dba_v0 不会改善 pt1。
- ⇒ **pt1 person-ATE 差距（9.16 vs RGD 7.2）无法靠 masked-geometry/photo KF-BA 关闭**。

## 与 03-results 已录音的回旋（就地收口）
- `03-results.md` §90-94 曾记「换更强基座 / 加特征锚 / 改 masked-edge 构造后可重启」。
  **本探针证明：即使换到 mask-ON + edge3（更强基座 + 更强约束的 person 序列），GT 仍不偏好。
  ⇒ 那条"可重启"的乐观尾巴在本 person 序列上反而不成立，就地收口：在这套 masked-container 下的
  几何 KF-BA 是死路，不再重启。**

## 下一步（long-horizon 位姿正则的换道）
- codex round2 的「long-horizon 位姿正则」需要换一条**不是「最小化 masked 几何/光度」的约束**。
  候选（待设计假设 + 离线探针）：
  - **轨迹形状先验 / 平滑正则**：直接对估计轨迹施加运动平滑（不经过 masked 观测目标）。
  - **航位推算残差**：用已冻结的可靠性 flow / 相邻帧相对位姿做低成本死区一致约束。
  - 均需按最高准则先预注册假设 + 离线验证再批量。

## 与 03-results 已录音的回旋
- `03-results.md` §90-94 早就记了「DBA GT-oracle 是当前基座+当前边界的负结论；换更强基座/特征锚/改
  masked-edge 构造后可重启」。**本探针证明：即使换到 mask-ON + edge3（更强基座+更强约束），仍然负。**
  ⇒ 那条"可重启"的乐观尾巴在本 person 序列上反而不成立，应就地收口：**在这套 masked-container 下的
  几何 KF-BA 是死路**。

## 数据源
- `results/runs/P6/P6-DBA-ORACLE/pt1_edge3_dba_seed{s}/tables/tracking_raw.csv`
- 控制台：`*.consolelog` 的 `DBA-lite GT-ORACLE FALSIFIER` 段。
