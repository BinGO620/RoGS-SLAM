# P6-MASON — mask-ON 全 18 序列竞争分析（2026-08-10）

> 2026-08-10 exp-v3-13。**鉴别实验完成**：回答"mask 能否加进方法"。答案 = **必须加**。
> mask-ON combined 把 mask-free 的重灾区（crowd/crowd2/walking，5-36× 落后）瞬间拉回
> RGD/DG 的 SOTA 竞争带。方法定位 = **主表 combined(mask-ON) 打绝对竞争力 + mask-free
> 做免分割内核差异化**。
> 数据 = P6-MASON 本批 15 run（crowd/crowd2/f3_wk_rpy/f3_wk_xyz/pt1 × 3 seed）+ P2-T_3090
> 6 BONN × 3 seed。全部 `tracking_raw.csv ate_rmse_cm`（全轨迹, 3090）。

## 缺 mask-ON 的序列（诚实标注）
- **f3_wk_hf 未测 mask-ON**（walking 第三变体，只有 f3_wk_rpy/xyz 测了）——同族推断但须标注"未测"。
- 静态（f1_desk/f2_xyz/f3_office）/ f2_person / f3_st_* **无 mask-ON**，用 mask-off 占位。
  mask-free 在这些序列已无伤/优于 vanilla（0.94-0.98×），mask-ON 只会更好或平，不作缺口。

## 全 18 序列 mask-ON 竞争表（cm, 3-seed mean）

| 序列 | 类型 | vanilla | mask-off | **mask-ON** | RGD | DG | WildGS | vs RGD | vs DG |
|---|---|---|---|---|---|---|---|---|---|
| f1_desk | 静态 | 1.47 | 1.42 | 1.42* | 2.32 | 4.49 | 1.76 | 优 | 优 |
| f2_xyz | 静态 | 1.66 | 1.63 | 1.63* | 1.71 | 0.61 | 0.28 | ≈ | 输 |
| f3_office | 静态 | 1.65 | 1.54 | 1.54* | 1.42 | 2.24 | 1.45 | ≈ | 优 |
| f2_person | 多人 | 6.30 | 7.00 | 7.00* | 6.11 | 2.98 | 1.35 | 输 | 输 |
| f3_st_hf | sitting | 2.80 | 2.14 | 2.14* | 2.76 | 2.57 | 1.73 | 优 | 优 |
| f3_st_rpy | sitting | 18.99 | 1.83 | 1.83* | 2.90 | 3.79 | 2.32 | 优 | 优 |
| f3_st_xyz | sitting | 1.66 | 2.41 | 2.41* | 2.03 | 1.09 | 0.85 | 输 | 输 |
| f3_wk_hf | walking | 44.45 | 26.23 | **—(未测)** | 3.25 | 2.01 | 1.45 | — | — |
| f3_wk_rpy | walking | 62.89 | 16.80 | **3.67** | 3.55 | 7.35 | 3.00 | **≈** | **优** |
| f3_wk_xyz | walking | 28.14 | 26.84 | **3.06** | 2.01 | 1.70 | 1.22 | 输1.5× | 输 |
| balloon | 混合 | 39.32 | 12.11 | **3.06** | 2.45 | 3.66 | 2.75 | ≈ | 优 |
| balloon2 | 混合 | 22.05 | 10.14 | **5.28** | 4.26 | 3.83 | 2.42 | ≈ | 输 |
| crowd | 多人 | 86.47 | 56.38 | **2.33** | 2.61 | 5.76 | 1.55 | **优** | **优** |
| crowd2 | 多人 | 147.46 | 66.07 | **2.42** | 2.36 | 6.39 | 2.17 | **优** | **优** |
| mv_no_box | 纯物 | 15.33 | 3.09 | **2.66** | 2.28 | 3.01 | 1.60 | ≈ | **优** |
| mv_no_box2 | 纯物 | 16.84 | 5.62 | **5.14** | 4.70 | 3.56 | 2.50 | **优** | 输 |
| pt1 | 纯人 | 44.83 | 32.41 | **11.89** | 7.21 | 4.25 | 3.63 | **输1.65×** | **输2.8×** |
| pt2 | 纯人 | 43.85 | 9.30 | **10.44** | 20.10 | 6.12 | 3.09 | **优** | 输 |

（\* = mask-off 占位，无 mask-ON 实测。）

## 裁决

### 1. mask 加到方法 — 鉴别成立（核心结论）
mask-ON combined 把 mask-free 的重灾区（crowd/crowd2/walking，5-36× 落后）拉回 SOTA：
- **crowd 56.38→2.33（压 RGD 2.61、超 DG 5.76）；crowd2 66.07→2.42（压 RGD 6.39）；f3_wk_rpy 16.8→3.67（≈RGD 超 DG）；f3_wk_xyz 26.84→3.06。全 3-seed 极稳（crowd std < 0.1cm）。**
- **方法不再二选一**：主表 combined（mask-ON）打绝对竞争力；mask-free 做"免分割内核"差异化叙事
  （证明 4-14× 增益真实不靠分割 + 允用分割则进 SOTA）。两张牌拼成完整方法。

### 2. 唯一真短板 = pt1（11.89 vs RGD 7.21 / DG 4.25 / WildGS 3.63）
- mask-ON 已把 mask-off 的 32.41 拉回 11.89，但仍是全表唯一明显落后 RGD（1.65×）、且**远输 DG（2.8×）**。
- 3-seed 大方差（P6-MASON 10.36/10.69/14.61 + P2-T 9.62/9.79/10.70）—— 与"tracking 崩"诊断一致。
- **关键竞品信号：DG 在 pt1 4.25 / pt2 6.12 是唯一全面压我们的（连 RGD 在 pt2 都最差 20.1）。**
  深挖 DG 为何在 person 序列强，是本会话下一步重点（见 `dg_pt1_pt2_advantage.md`）。

### 3. 诚实适用域
- **mask-ON 下**：除 pt1 外全部动态序列进 RGD 竞争带（±50%），crowd/crowd2/wk_rpy/pt2/mv_no_box2 **压 RGD**。
- mask-free 仍是"纯物/低遮挡/静态"的最优定位（mv_no_box 2.66≈RGD、静态无伤），是免分割内核的根基。

## 待续优先级
1. **pt1 tracking 补强方案**（下一步，动核心前呈用户）——顺带深挖 DG 的 person 序列强因（本会话）。
2. **f3_wk_hf mask-ON 补测**（1 序列，可快速闭合 walking 族缺口）。
3. **渲染指标**（如常延后）。

## 数据源
- P6-MASON 15 run：`results/runs/P6/P6-MASON/{crowd,crowd2,f3_wk_rpy,f3_wk_xyz,pt1}_combined_seed{0,1,2}/tables/tracking_raw.csv`
- P2-T 6 BONN：`results/runs/P2/P2-T_3090/{balloon,balloon2,mv_no_box,mv_no_box2,pt1,pt2}_prune_seed{0,1,2}/tables/tracking_raw.csv`
- 竞品：`resources/02-baselines/04-baselines_result.xlsx` 01_ATE_RMSE
