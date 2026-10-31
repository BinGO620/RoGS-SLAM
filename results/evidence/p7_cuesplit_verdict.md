# P7 Cue-Split 3-Seed Verdict（2026-08-13）

## 结论摘要

**P7 完成 48/48 run，全部 tracking_raw.csv 存在，远程 launcher `missing=0`。**

P7 在 mask-free MRCS 骨干上拆解 ReliabilitySignal 的四个 tracking 臂：off、默认 both、flow-only、geometry-only；覆盖 balloon、mv_no_box、mv_no_box2、pt2，每序列每臂 3 seed。ATE 统一取完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`，均值与标准差使用 3 seed、样本标准差（ddof=1）。

**H1：单 seed 的 cue 主导性只部分复现。** 单 seed 方向在 balloon 上没有复现（原 screen 的 flow-only 最好；3-seed geometry-only 最好），mv_no_box 的 single-seed geometry 偏好也被 3-seed 默认 both 反超；但 mv_no_box2 / pt2 的 geometry 优势在 3 seed 上稳定复现。

**H2：geometry-only 在 4 个序列中有 3 个取得最低 mean ATE（balloon、mv_no_box2、pt2），达到预注册的 ≥3 序列门槛。** 因此固定 both 不应继续作为方法的普适内核解释；P7 支持将内核叙述升级为 **regime-aware cue selection / conservative cue fusion**。但不能把 geometry-only 写成所有序列的默认最优：mv_no_box 上默认 both 最优（2.86±0.27 cm），balloon 上 geometry-only 最优但方差仍较大。

## 完整数值（cm，mean±std，3 seed）

| 序列 | OFF | BOTH（默认） | FLOW-ONLY | GEOMETRY-ONLY | 最低 mean |
|---|---:|---:|---:|---:|---|
| balloon | 13.78±5.97 | 13.85±0.58 | 13.96±0.88 | **12.25±1.51** | geo |
| mv_no_box | 6.56±4.50 | **2.86±0.27** | 4.12±0.60 | 3.70±0.68 | both |
| mv_no_box2 | 6.08±0.35 | 5.67±0.33 | 5.58±0.36 | **4.88±0.05** | geo |
| pt2 | 10.91±0.52 | 9.18±1.12 | 10.04±0.87 | **8.78±0.43** | geo |

原始 seed 数值：

| 序列 | 臂 | seed 0 | seed 1 | seed 2 |
|---|---|---:|---:|---:|
| balloon | off | 9.55 | 11.19 | 20.61 |
| balloon | both | 13.25 | 13.91 | 14.40 |
| balloon | flow | 13.03 | 14.05 | 14.79 |
| balloon | geo | 10.63 | 12.51 | 13.62 |
| mv_no_box | off | 3.92 | 4.01 | 11.76 |
| mv_no_box | both | 2.61 | 2.83 | 3.15 |
| mv_no_box | flow | 3.74 | 3.81 | 4.81 |
| mv_no_box | geo | 3.20 | 3.43 | 4.47 |
| mv_no_box2 | off | 5.72 | 6.09 | 6.42 |
| mv_no_box2 | both | 5.30 | 5.76 | 5.95 |
| mv_no_box2 | flow | 5.27 | 5.50 | 5.98 |
| mv_no_box2 | geo | 4.84 | 4.86 | 4.94 |
| pt2 | off | 10.32 | 11.16 | 11.25 |
| pt2 | both | 7.90 | 9.67 | 9.98 |
| pt2 | flow | 9.26 | 9.89 | 10.97 |
| pt2 | geo | 8.31 | 8.86 | 9.16 |

## 逐序列解释

### balloon（混合 mover）

Geometry-only 最低（12.25 cm），比 both 低 11.5%，比 flow-only 低 12.2%。但是 off 的 seed-2=20.61 cm 造成较大 std，不能只看一个 seed；both 与 flow-only 在三个 seed 内均较稳定，却没有超过 geometry-only 的均值。

这推翻了 ours-method 单 seed 中“balloon 偏 flow”的 screening 结论，但不推翻“balloon 是不同 regime”的判断。更准确的当前说法是：balloon 上双线索 both 没有收益，geometry-only 在本 P7 设置下均值最好；需要避免把早期 flow-only 的单 seed 最优继续写成确定机制。

### mv_no_box（纯物）

默认 both 最低（2.86 cm），geo 次之（3.70 cm），flow-only 为 4.12 cm，off 为 6.56 cm。off 的 seed-2=11.76 cm 是高方差异常，但 reliability 开启的三种臂都明显优于 off。

这说明在 mv_no_box 上 both 不是有害的固定融合，反而是最好的 P7 臂；因此不能把 P7 总结成“geometry-only 全局替代 both”。

### mv_no_box2（纯物，独立复现）

Geometry-only 稳定最优（4.88±0.05 cm），三个 seed 只在 4.84–4.94 cm；both 为 5.67±0.33 cm，仍优于 off，但比 geo 高 16.2%。早期 single-seed 的 both 退化 5.68→12.72 没有按同样幅度复现，说明那次退化受 seed/运行方差影响；不过 3-seed 仍支持 both 非最优、geo 更稳。

这条结果应写成“固定 both 在 mv_no_box2 上存在可重复的次优/退化趋势”，不能继续写成“+124% 的确定性退化”作为 P7 结论。

### pt2（纯人）

Geometry-only 最优（8.78±0.43 cm），比 both 低 4.4%，比 flow-only 低 12.5%，比 off 低 19.5%。geo 三个 seed 单调落在 8.31–9.16 cm，稳定性最好；both 方差较大（7.90–9.98）。

这复现了 geometry 主导的方向，但提升幅度需要按 run-to-run 方差谨慎表达，不应直接宣称大幅改善。

## 预注册判决映射

- **每臂 3 seed：完成。**
- **ATE 口径：满足。** 读取 `tracking_raw.csv` 的 `ate_rmse_cm`，不是 console 的 keyframe RMSE。
- **cue 主导性：geometry-only 在 3/4 序列最低 mean。** H2 的 ≥3 序列门槛满足。
- **both 比 off 差 ≥20%：未形成普遍事实。** mv_no_box、mv_no_box2、pt2 上 both 优于 off；balloon 上 both 与 off 基本相当（+0.5%），但 off 受 seed-2 高值影响。
- **单一固定融合是否足够：不支持普适性。** 最优臂跨序列为 geo / both / geo / geo，说明“默认 geometry 更稳”比“固定 both 普适”更有支持，但仍存在 mv_no_box 的 both 反例。

## 方法与命名后果

1. MRCS 名称仍然合适：P7 没有推翻 Reliability + Coverage 的方法结构，只是表明 Reliability 内部不能被固定 both 公式概括。
2. 02-method 的内核表述应从“固定双线索融合”改成：**Reliability-guided cue selection/fusion；默认 both 是历史 control，不是普适最优定理。**
3. 不把 geometry-only 直接升级为新的全局默认配置。当前最稳妥的方法假设是：**不同 mover regime 对 flow/geometry cue 的可信度不同，需要保守的 cue selection；P7 只验证了需要选择，尚未验证一个新的 regime detector 或自适应融合器。**
4. P7 是方法期证据，不是写作充分条件。下一步若要把 cue selection 变成方法贡献，需要单独预注册 cue regime 判别规则，并在未参与选择的数据/序列上验证，避免用测试序列结果事后选最优臂。

## 可复核来源

- 预注册与判据：`results/evidence/p7_cuesplit_prereg.md`
- 原始结果：`results/runs/P7/P7-CUESPLIT/cuesplit_{seq}_{mode}_seed{0,1,2}/tables/tracking_raw.csv`
- 远程完成标记：`results/runs/P7/P7-CUESPLIT/cuesplit.done`，`ALL_DONE ... missing=0`
- 代码开关：`utils/reliability_signal.py`、`utils/slam_frontend.py`
- 配置合同：`tests/test_p7_cuesplit_configs.py`
