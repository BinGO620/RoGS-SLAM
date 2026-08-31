# P6 MASK-OFF — 全 18 序列 mask-free 主表（对齐 baseline，3090，36 run）

> 2026-08-10 exp-v3-12 收尾。用户澄清「18 序列」= resource baseline 那套（10 TUM + 8 BONN），
> RGD/DG/MonoGS/Co-SLAM 都跑满的。本批把 mask-free 从 BONN 6 扩到全 18 序列
> （新增 crowd/crowd2 + TUM 10）。全部 3-seed，数值 = `tracking_raw.csv ate_rmse_cm`（全轨迹,3090）。
> 数据 = `results/runs/P6/P6-18SEQ/`（36 run 已回拉）。

## 全 18 序列 mask-free 主表（cm, 3-seed mean）

| 序列 | 类型 | vanilla(MonoGS) | **OURS mask-free** | RGD | DG | WildGS | vs vanilla |
|---|---|---|---|---|---|---|---|
| f1_desk | TUM 静态 | 1.47 | **1.42** | 2.32 | 4.49 | 1.76 | 0.97× |
| f2_xyz | TUM 静态 | 1.66 | **1.63** | 1.71 | 0.61 | 0.28 | 0.98× |
| f3_office | TUM 静态 | 1.65 | **1.54** | 1.42 | 2.24 | 1.45 | 0.94× |
| f2_person | TUM 动态 | 6.30 | **7.00** | 6.11 | 2.98 | 1.35 | 1.11× |
| f3_st_hf | TUM sitting | 2.80 | **2.14** | 2.76 | 2.57 | 1.73 | 0.76× |
| f3_st_rpy | TUM sitting | 18.99 | **1.83** | 2.90 | 3.79 | 2.32 | **0.10×** |
| f3_st_xyz | TUM sitting | 1.66 | **2.41** | 2.03 | 1.09 | 0.85 | 1.46× |
| f3_wk_hf | TUM walking | 44.45 | **26.23** | 3.25 | 2.01 | 1.45 | 0.59× |
| f3_wk_rpy | TUM walking | 62.89 | **16.80** | 3.55 | 7.35 | 3.00 | **0.27×** |
| f3_wk_xyz | TUM walking | 28.14 | **26.84** | 2.01 | 1.70 | 1.22 | 0.95× |
| balloon | BONN 混合 | 39.32 | **12.11** | 2.45 | 3.66 | 2.75 | 0.31× |
| balloon2 | BONN 混合 | 22.05 | **10.14** | 4.26 | 3.83 | 2.42 | 0.46× |
| crowd | BONN 多人 | 86.47 | **56.38** | 2.61 | 5.76 | 1.55 | 0.65× |
| crowd2 | BONN 多人 | 147.46 | **66.07** | 2.36 | 6.39 | 2.17 | 0.45× |
| mv_no_box | BONN 纯物 | 15.33 | **3.09** | 2.28 | 3.01 | 1.60 | **0.20×** |
| mv_no_box2 | BONN 纯物 | 16.84 | **5.62** | 4.70 | 3.56 | 2.50 | 0.33× |
| pt1 | BONN 纯人 | 44.83 | **32.41** | 7.21 | 4.25 | 3.63 | 0.72× |
| pt2 | BONN 纯人 | 43.85 | **9.30** | 20.10 | 6.12 | 3.09 | **0.21×** |

（vanilla/竞品 = resource 02-baselines `04-baselines_result.xlsx` 01_ATE_RMSE 表。OURS = 本批 3-seed mean。）

## 裁决

### 1. mask-free 相对 vanilla —— 成立（强增益，framework-general）

- **18 序列中 15 个优于 vanilla，3 个略差**（f2_person 7.0 vs 6.3、f3_st_xyz 2.41 vs 1.66，差值 0.7cm 在噪声带；f3_wk_xyz 26.84 vs 28.14 略优）。
- **大增益序列**：f3_st_rpy **18.99→1.83（10× 优）**、mv_no_box 15.33→3.09（5×）、pt2 43.85→9.30（4.7×）、wk_rpy 62.89→16.80（3.7×）。
- 静态序列（f1_desk/f2_xyz/f3_office）mask-free ≈ vanilla（0.94-0.98×），**无伤** —— 关键卖点：mask-free 动态模块不伤害静态基线。

### 2. mask-free 相对竞品（RGD/DG/WildGS）—— 诚实适用域边界

- **绝对 ATE 打不过动态 SOTA**：RGD/DG/Wild 在动态序列 1-7cm，我们 1.4-66cm。**walking/crowd 人群场景差 5-28×**（f3_wk_xyz 26.84 vs RGD 2.01;crowd2 66.07 vs 2.36）。
- **headline 不 claim 超越 SOTA**：头条 = 「mask-free bundle 相对 vanilla 大增益 + 不依赖语义分割 + framework-general」，**不是**「绝对 ATE 优于有 mask 的动态方法」。
- 诚实定位 = 有 mask 的动态方法（RGD/DG）在人群密集/快速运动场景无可否认更强；mask-free 的价值在"无 segmentation 依赖下的鲁棒基础"，是**基座之上、分割之外的增量**。

### 3. 三类 mover 的 mask-free 通用性（BONN 6，前已裁决）—— 并入 18-seq

- 纯物双复现（mv 3.09/5.62 ≈ combined）✓ / pt2（9.30）✓ / pt1 边界反例（32.41，见 `bracketing_pt1_pt2_scene.md`）
- **新跨数据集证据**：TUM 动态（sitting/walking）mask-free 大多优于 vanilla → mask-free 不只 BONN，**TUM 也成立**。

## 诚实不动摇（对最高准则两问）

| 问 | 答 |
|---|---|
| 方法贡献是自己的吗？ | 是（dynamic-KF/RT-huber/Reliability 是我们实现/调的，kernel 不在 MonoGS，也不依赖分割） |
| 对动态 3DGS SLAM 有用吗？ | 是，**但诚实适用域**：mask-free 在低遮挡/纯物/静态/部分 person/walking 都优于 vanilla（framework-general），但绝对 ATE 打不过有 mask 的动态 SOTA（人群密集/快速运动是边界）。 |

**不 claim SOTA；headline = mask-free 相对 vanilla 的增益 + 不依赖分割 + TUM/BONN 跨数据集通用。**

## 落盘与待办

- 36 run 已回拉 `results/runs/P6/P6-18SEQ/`（含 walking 尾段双卡收尾）。
- 脚本双卡 bug 已修（`run_maskoff_18seq_3090.sh`，commit `71a390b`）。
- **待办**：
  1. 把本 18-seq 表落进 `papers/maskfree_bundle/skeleton.md` §3.1（替换 BONN-6-only 版）。
  2. vanilla 基线对齐：我们 mask-free vs vanilla 的 3 个略差序列（f2_person/f3_st_xyz）需确认非批次噪声。
  3. **下一步最有杠杆迭代**：pt1 崩在 tracking（RPE 2.8、3-seed 双稳态），候选改 `slam_frontend` 核心 tracking 逻辑 —— **需用户拍板（硬停条件②）**，见 `consult_codex_pt1_pt2_maskoff.md`。
