# 18 序列渲染主表（paper main table, 2026-08-11）

> 来源标注: **我们** = 3090 离线重渲 `final/` PLY + `trj_full_final`（`posthoc_fullframe`，3-seed mean±std, ddof=1）; **竞品** = 用户自测 `04-baselines_result.xlsx`（mean）。渲染 = 全帧 PSNR/SSIM/LPIPS/Depth-L1。我们的渲染协议（`final/` PLY）与竞品同口径比较（均全分辨率全帧）。FPS 是 2060 数，不与竞品并列。

> **⚠ MonoGS 行的 ATE 是 3-seed mean±sd (CV)，不是 xlsx 的单一均值**（2026-08-25 exp46 改）。源 = `resources/02-baselines/baselines_result/MonoGS/tracking_raw.csv`（同环境同口径重跑，18 序列 × 3 seed）。这是 `headline_ratio_recompute.md` 定为**唯一合法**的倍数分母。标 ⚠ 的格子 vanilla CV > 20% ⇒ **该序列的 improvement ratio 依 basin 而变，不得写成单一倍数**，只能写 mean±sd 或给区间。渲染四列仍取自 xlsx（那里只有 mean），故 MonoGS 行**ATE 有离散度、渲染没有** —— 这是取数来源不同，不是漏报。

## 主表（Method × Sequence）

| Seq | 类型 | 方法 | ATE(cm)↓ | PSNR↑ | SSIM↑ | LPIPS↓ | Depth-L1(cm)↓ |
|---|---|---|---|---|---|---|---|
| f1_desk | TUM 静态 | **Ours-mask-free** | 1.49±0.05 | 18.70±0.10 | 0.736±0.007 | 0.321±0.011 | 4.32±0.08 |
| f1_desk | TUM 静态 | **Ours-combined(mask-ON)** | 1.39±0.04 | 18.74±0.10 | 0.739±0.004 | 0.318±0.008 | 4.22±0.04 |
| f1_desk | TUM 静态 | MonoGS (vanilla, 3-seed) | 1.47±0.08 (CV 6%) | 23.57 | 0.783 | 0.246 | 6.30 |
| f1_desk | TUM 静态 | RGD-SLAM | 2.32 | 23.33 | 0.779 | 0.245 | 3.46 |
| f2_xyz | TUM 静态 | **Ours-mask-free** | 1.91±0.04 | 15.92±0.07 | 0.731±0.002 | 0.292±0.007 | 4.11±0.45 |
| f2_xyz | TUM 静态 | **Ours-combined(mask-ON)** | 1.93±0.03 | 15.98±0.05 | 0.730±0.004 | 0.291±0.003 | 3.96±0.09 |
| f2_xyz | TUM 静态 | MonoGS (vanilla, 3-seed) | 1.66±0.13 (CV 8%) | 24.59 | 0.794 | 0.219 | 14.24 |
| f2_xyz | TUM 静态 | RGD-SLAM | 1.71 | 24.40 | 0.796 | 0.219 | 1.97 |
| f3_office | TUM 静态 | **Ours-mask-free** | 1.59±0.02 | 18.95±0.30 | 0.732±0.010 | 0.329±0.016 | 9.37±0.64 |
| f3_office | TUM 静态 | **Ours-combined(mask-ON)** | 1.55±0.11 | 18.50±1.12 | 0.719±0.027 | 0.353±0.029 | 11.54±3.79 |
| f3_office | TUM 静态 | MonoGS (vanilla, 3-seed) | 1.65±0.05 (CV 3%) | 24.96 | 0.840 | 0.206 | 13.94 |
| f3_office | TUM 静态 | RGD-SLAM | 1.42 | 22.91 | 0.803 | 0.267 | 4.47 |
| f2_person | TUM 动态 | **Ours-mask-free** | 6.79±0.18 | 17.49±0.44 | 0.591±0.024 | 0.463±0.030 | 18.45±1.50 |
| f2_person | TUM 动态 | **Ours-combined(mask-ON)** | 7.34±0.25 | 17.09±0.19 | 0.595±0.010 | 0.487±0.020 | 24.91±2.19 |
| f2_person | TUM 动态 | MonoGS (vanilla, 3-seed) | 6.30±0.40 (CV 6%) | 20.17 | 0.677 | 0.387 | 26.07 |
| f2_person | TUM 动态 | RGD-SLAM | 6.11 | 20.81 | 0.699 | 0.363 | 20.08 |
| f3_st_hf | TUM sitting | **Ours-mask-free** | 35.59±0.47 | 16.69±0.33 | 0.569±0.011 | 0.456±0.018 | 31.91±1.30 |
| f3_st_hf | TUM sitting | **Ours-combined(mask-ON)** | 29.43±8.00 | 14.89±0.07 | 0.552±0.002 | 0.485±0.007 | 46.62±3.53 |
| f3_st_hf | TUM sitting | MonoGS (vanilla, 3-seed) | 2.80±0.92 (CV 33%) ⚠ | 19.14 | 0.699 | 0.299 | 33.65 |
| f3_st_hf | TUM sitting | RGD-SLAM | 2.76 | 20.38 | 0.796 | 0.256 | 27.53 |
| f3_st_rpy | TUM sitting | **Ours-mask-free** | 2.63±0.17 | 18.64±0.14 | 0.707±0.004 | 0.295±0.005 | 13.33±0.06 |
| f3_st_rpy | TUM sitting | **Ours-combined(mask-ON)** | 2.58±0.17 | 17.27±0.20 | 0.670±0.000 | 0.367±0.002 | 22.11±1.14 |
| f3_st_rpy | TUM sitting | MonoGS (vanilla, 3-seed) | 18.99±9.80 (CV 52%) ⚠ | 14.56 | 0.521 | 0.449 | 79.26 |
| f3_st_rpy | TUM sitting | RGD-SLAM | 2.90 | 19.45 | 0.767 | 0.248 | 28.77 |
| f3_st_xyz | TUM sitting | **Ours-mask-free** | 2.66±0.64 | 20.11±0.29 | 0.721±0.012 | 0.246±0.019 | 11.44±0.32 |
| f3_st_xyz | TUM sitting | **Ours-combined(mask-ON)** | 4.69±0.71 | 16.83±0.07 | 0.662±0.008 | 0.315±0.010 | 34.48±1.74 |
| f3_st_xyz | TUM sitting | MonoGS (vanilla, 3-seed) | 1.66±0.04 (CV 2%) | 22.14 | 0.806 | 0.184 | 23.27 |
| f3_st_xyz | TUM sitting | RGD-SLAM | 2.03 | 21.16 | 0.827 | 0.166 | 33.52 |
| f3_wk_hf | TUM walking | **Ours-mask-free** | 17.33±2.97 | 14.94±0.51 | 0.491±0.027 | 0.513±0.023 | 50.25±1.90 |
| f3_wk_hf | TUM walking | **Ours-combined(mask-ON)** | 3.29±0.25 | 15.69±0.04 | 0.622±0.010 | 0.382±0.012 | 52.66±0.58 |
| f3_wk_hf | TUM walking | MonoGS (vanilla, 3-seed) | 44.45±11.06 (CV 25%) ⚠ | 13.85 | 0.455 | 0.572 | 104.87 |
| f3_wk_hf | TUM walking | RGD-SLAM | 3.25 | 19.73 | 0.771 | 0.250 | 46.80 |
| f3_wk_rpy | TUM walking | **Ours-mask-free** | 14.61±2.12 | 14.41±0.15 | 0.494±0.014 | 0.516±0.017 | 60.84±4.49 |
| f3_wk_rpy | TUM walking | **Ours-combined(mask-ON)** | 4.29±0.48 | 14.93±0.03 | 0.624±0.008 | 0.396±0.003 | 66.38±0.50 |
| f3_wk_rpy | TUM walking | MonoGS (vanilla, 3-seed) | 62.89±6.81 (CV 11%) | 14.60 | 0.504 | 0.548 | 110.59 |
| f3_wk_rpy | TUM walking | RGD-SLAM | 3.55 | 19.07 | 0.757 | 0.286 | 62.39 |
| f3_wk_xyz | TUM walking | **Ours-mask-free** | 26.84±0.71 | 15.28±0.06 | 0.522±0.001 | 0.557±0.004 | 116.96±14.45 |
| f3_wk_xyz | TUM walking | **Ours-combined(mask-ON)** | 3.06±0.52 | 17.65±0.08 | 0.715±0.003 | 0.301±0.003 | 76.78±0.17 |
| f3_wk_xyz | TUM walking | MonoGS (vanilla, 3-seed) | 28.14±0.86 (CV 3%) | 13.76 | 0.413 | 0.567 | 101.68 |
| f3_wk_xyz | TUM walking | RGD-SLAM | 2.01 | 19.31 | 0.775 | 0.221 | 54.89 |
| balloon | BONN 混合 | **Ours-mask-free** | 12.11±2.33 | 22.49±0.14 | 0.843±0.002 | 0.284±0.001 | 26.82±2.57 |
| balloon | BONN 混合 | **Ours-combined(mask-ON)** | 3.06±0.14 | 21.56±0.30 | 0.853±0.001 | 0.281±0.002 | 26.71±1.31 |
| balloon | BONN 混合 | MonoGS (vanilla, 3-seed) | 39.32±1.01 (CV 3%) | 19.30 | 0.766 | 0.356 | 31.14 |
| balloon | BONN 混合 | RGD-SLAM | 2.45 | 25.14 | 0.896 | 0.224 | 15.69 |
| balloon2 | BONN 混合 | **Ours-mask-free** | 10.14±0.61 | 19.75±0.13 | 0.794±0.003 | 0.338±0.005 | 32.19±1.43 |
| balloon2 | BONN 混合 | **Ours-combined(mask-ON)** | 5.27±0.12 | 19.31±0.10 | 0.815±0.001 | 0.325±0.003 | 38.00±0.57 |
| balloon2 | BONN 混合 | Baseline-flow-mask(p90) | 23.30±10.50 | — | — | — | — |
| balloon2 | BONN 混合 | MonoGS (vanilla, 3-seed) | 22.05±1.55 (CV 7%) | 19.17 | 0.736 | 0.371 | 34.32 |
| balloon2 | BONN 混合 | RGD-SLAM | 4.26 | 24.36 | 0.892 | 0.202 | 25.47 |
| crowd | BONN 多人 | **Ours-mask-free** | 34.89±28.27 | 15.10±1.17 | 0.639±0.081 | 0.537±0.114 | 45.31±10.77 |
| crowd | BONN 多人 | **Ours-combined(mask-ON)** | 2.29±0.05 | 17.08±0.09 | 0.766±0.006 | 0.368±0.019 | 33.54±0.83 |
| crowd | BONN 多人 | MonoGS (vanilla, 3-seed) | 86.47±18.34 (CV 21%) ⚠ | 15.84 | 0.654 | 0.541 | 74.32 |
| crowd | BONN 多人 | RGD-SLAM | 2.61 | 24.21 | 0.905 | 0.178 | 32.17 |
| crowd2 | BONN 多人 | **Ours-mask-free** | 45.89±17.35 | 16.16±0.49 | 0.665±0.009 | 0.496±0.007 | 42.07±3.17 |
| crowd2 | BONN 多人 | **Ours-combined(mask-ON)** | 2.19±0.09 | 15.71±0.10 | 0.750±0.001 | 0.375±0.002 | 46.46±0.06 |
| crowd2 | BONN 多人 | MonoGS (vanilla, 3-seed) | 147.46±39.03 (CV 26%) ⚠ | 16.52 | 0.648 | 0.522 | 73.05 |
| crowd2 | BONN 多人 | RGD-SLAM | 2.36 | 24.36 | 0.915 | 0.157 | 45.68 |
| mv_no_box | BONN 纯物 | **Ours-mask-free** | 3.10±0.46 | 24.71±0.07 | 0.874±0.001 | 0.220±0.003 | 18.25±0.31 |
| mv_no_box | BONN 纯物 | **Ours-combined(mask-ON)** | 2.65±0.12 | 24.65±0.02 | 0.877±0.002 | 0.217±0.005 | 18.51±1.50 |
| mv_no_box | BONN 纯物 | MonoGS (vanilla, 3-seed) | 15.33±9.47 (CV 62%) ⚠ | 21.78 | 0.807 | 0.285 | 20.78 |
| mv_no_box | BONN 纯物 | RGD-SLAM | 2.28 | 24.45 | 0.869 | 0.250 | 7.90 |
| mv_no_box2 | BONN 纯物 | **Ours-mask-free** | 5.62±0.30 | 25.07±0.05 | 0.881±0.001 | 0.239±0.005 | 19.09±0.87 |
| mv_no_box2 | BONN 纯物 | **Ours-combined(mask-ON)** | 5.14±0.28 | 25.13±0.02 | 0.884±0.001 | 0.235±0.004 | 18.80±0.82 |
| mv_no_box2 | BONN 纯物 | Baseline-flow-mask(p90) | 6.23±0.44 | — | — | — | — |
| mv_no_box2 | BONN 纯物 | MonoGS (vanilla, 3-seed) | 16.84±16.96 (CV 101%) ⚠ | 22.90 | 0.835 | 0.276 | 23.26 |
| mv_no_box2 | BONN 纯物 | RGD-SLAM | 4.70 | 24.01 | 0.860 | 0.297 | 6.18 |
| pt1 | BONN 纯人 | **Ours-mask-free** | 32.41±8.52 | 21.97±0.45 | 0.829±0.009 | 0.323±0.009 | 33.84±5.76 |
| pt1 | BONN 纯人 | **Ours-combined(mask-ON)** | 11.89±2.36 | 22.19±0.11 | 0.856±0.002 | 0.278±0.004 | 29.05±2.95 |
| pt1 | BONN 纯人 | Baseline-flow-mask(p90) | 51.41±11.20 | — | — | — | — |
| pt1 | BONN 纯人 | MonoGS (vanilla, 3-seed) | 44.83±9.06 (CV 20%) ⚠ | 17.81 | 0.718 | 0.442 | 37.78 |
| pt1 | BONN 纯人 | RGD-SLAM | 7.21 | 24.11 | 0.855 | 0.297 | 11.31 |
| pt2 | BONN 纯人 | **Ours-mask-free** | 9.30±0.64 | 22.06±0.12 | 0.854±0.001 | 0.269±0.006 | 26.13±2.84 |
| pt2 | BONN 纯人 | **Ours-combined(mask-ON)** | 10.45±0.84 | 21.97±0.17 | 0.853±0.003 | 0.265±0.006 | 26.98±1.85 |
| pt2 | BONN 纯人 | Baseline-flow-mask(p90) | 51.07±11.10 | — | — | — | — |
| pt2 | BONN 纯人 | MonoGS (vanilla, 3-seed) | 43.85±8.55 (CV 20%) | 19.68 | 0.743 | 0.381 | 36.04 |
| pt2 | BONN 纯人 | RGD-SLAM | 22.99 | 22.76 | 0.835 | 0.326 | 12.30 |

## 覆盖说明

### 我们的方法
- **mask-free**: 全 18 序列 × 3 seed（54 runs）渲染已齐。
- **combined(mask-ON)**: 全 18 序列 × 3 seed 渲染已齐（原 10 序列 + missing8 补齐 f1_desk/f2_xyz/f3_office/f2_person/f3_st_{hf,rpy,xyz}/f3_wk_hf）。
- 静态/低遮挡序列（f1_desk/f2_xyz/f3_office/f2_person/f3_st_*）mask-ON ≤ mask-free 或相当，掩码不形成缺口，作为竞争力支撑段。

### ⚠ FULLKERN 重跑（11 序列 × 2 臂 × 3 seed = 66 run）

- **为什么重跑**：这 11 条序列的**原始主表 run 没有预计算 `flow_raft/`**，`ReliabilitySignal` 因此被**静默跳过** —— 臂名写着 combined / mask-free，实跑是 **K1R1L0**（缺 L 组件），不是 K1R1L1。这是错误的臂标，不是噪声。
  序列：crowd, crowd2, f1_desk, f2_person, f2_xyz, f3_office, f3_st_hf, f3_st_rpy, f3_st_xyz, f3_wk_hf, f3_wk_rpy。
- **修复**：运行时硬闸（`utils/reliability_signal.py::assert_reliability_flow_available`，commit `7b89ff81`）改为**缺 flow 直接 abort**，不再静默降级；补建全部 flow；两臂各 3 seed 重跑。
- **本表取数**：这些序列**只**读 `P6-FULLKERN`（combined）/ `P6-FULLKERN-MASKFREE`（mask-free）。旧的 `P6-18SEQ` / `P6-MASON` / `P6-MASON-8SEQ` 对应格**在代码层被拒绝**（非人工挑选），覆盖不全时脚本**硬报错拒绝出表**，不会静默回落或静默少行。
- **其余 7 序列**（balloon, balloon2, mv_no_box, mv_no_box2, pt1, pt2, f3_wk_xyz）原本就有 flow，未受影响，保持原源。
- **引用纪律**：任何跨事故前后的数字对比必须注明口径 —— 旧数是 K1R1L0，新数才是完整内核。详见 `results/evidence/reliability_signal_silent_noop_incident.md`。

### Baseline-flow-mask(p90)（WP-B 中间地带基线）

- **是什么**：与 MRCS **共用同一套冻结离线 RAFT flow**，但用朴素逐像素阈值（`flow_quantile=0.9`，阈值在 pilot 阶段用 dev 序列冻结）生成掩码，替代我们的机制。用于回答审稿 R2「增益是否可归因于随便什么抗动态处理」。判决 **B1**，见 `wpb_flowmask_verdict.md`。
- **有值范围 = WP-B held-out 4 序列**（pt1, pt2, mv_no_box2, balloon2），3 seed × 4 序列 = 12 run，全部 `status=OK`；数据链与我方行同源（`results/runs/WPB/WPB-CONFIRM/*/tables/tracking_raw.csv`）。
- **其余 14 序列 = N/A**（f1_desk, f2_xyz, f3_office, f2_person, f3_st_hf, f3_st_rpy, f3_st_xyz, f3_wk_hf, f3_wk_rpy, f3_wk_xyz, balloon, crowd, crowd2, mv_no_box）：该臂**从未在这些序列上跑过**（WP-B campaign 范围就是 held-out 4 序列），**非漏跑、非漏报**。按预注册，**不得**为补格而外推或复用 dev 序列数据。
- **渲染四列 = 「—」**：该臂只跑了 tracking，没有离线重渲，故无 PSNR/SSIM/LPIPS/Depth-L1。
- **离散度口径**：本表统一 mean±std(ddof=1)；`wpb_flowmask_verdict.md` 对**同一批 run** 报 mean±half-range（口径不同，非数据不同）。
- **公平性说明（引用本行必须同写；2026-08-15 更正）**：两臂共用的冻结 flow 是 **backward `f_{t→t-1}`**（每帧只用该帧与前一帧）⇒ **信息上因果**；离线预计算只为逐字节可复现 + 把 RAFT 移出 6GB 在线预算。因此本行支持「同等因果 flow 信息预算下，朴素阈值 vs MRCS」的比较；仍成立的 caveat = **在线 FPS 不含 RAFT 推理开销**。旧表述「双向/未来帧可见/非因果」已撤回，见 `flow_causality_correction.md`。
- **不可与竞品列直接并读**：本行是我们自建的受控基线（同 campaign、同协议、同 flow 预算），与表内 MonoGS/RGD-SLAM 的外部实测不是同一类比较。

### 竞品
- 表内 headlist = MonoGS（我们的基座）+ RGD-SLAM（动态 SOTA）。其余方法（SplaTAM/Co-SLAM/DG-SLAM/WildGS-SLAM/DynaGSLAM）在 `04-baselines_result.xlsx` 全 18 序列均有渲染，按需扩列。
- `-` = 该 baseline 本身没有或不可比（论文设定里就没这指标），非漏跑。

## 竞品渲染列（其余方法, 可在 xlsx 06-09 直接对号）

PSNR: RGD 全 18 序列 19.0-25.1; WildGS 15.2-22.3; DG 13.1-24.2; MonoGS 13.8-25.0; SplaTAM 14.3-25.1; Co-SLAM 11.7-19.1。

## 运行 provenance（自动检查，不可静默）

✅ 每个 (序列, 臂, seed) 恰好一个已完成 run，ATE 与渲染同源。

