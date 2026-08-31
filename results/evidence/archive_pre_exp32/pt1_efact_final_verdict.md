# E-factorial 判别 + pt1 tracking 探索最终裁决（2026-08-10）

> exp-v3-13。E-factorial（codex 指定的唯一判别实验）完成。三臂全 pt1 3-seed。

## 三臂结果

| 臂 | config | seed0/1/2 | mean | RPE | path |
|---|---|---|---|---|---|
| A | edge3 alone | 9.16/9.31/8.99 | **9.16** | 1.60 | 134 |
| B | edge3 + full hard | 9.12/8.82/9.47 | **9.14** | 1.61 | **129** |
| C | edge3 + erode3(留边界带) | 10.16/10.55/9.73 | **10.15** | 1.65 | 134 |

## codex 判别逻辑核算（`kmtwnhcm6` 定）

- **B ≈ A**（9.14 vs 9.16）：full hard 在 edge3 下与 edge3-alone 同 → 硬挡与否在 edge3 下不再影响。
  ⇒ H-e 原失败（13.67）主因是**没叠 edge3**（弱背景像素劣化 conditioning 此解释不符：B 没比 A 好，
  B 也没更差，说明 edge3 已把信息集中到强边缘，硬挡不再有关系）。
- **C 更差**（10.15）：留边界带 + erode → 反而差 ⇒ **边界带不是关键增益**，或 erode 引入的模棱边界有害。
  （也可能 erode 缩 mask 时把部分真实人体/边界结构漏回为"static"，污染位姿。）

## 最终裁决（遵循 codex 的 stop 判据：需 ≥0.5cm 提升，未达）
- **edge_threshold=3.0（9.14-9.16）是当前 MonoGS dense-tracking 公式在 person-tracking regime 的
  empirical limit**（codex 明确：这是 tracker 经验上限，**不是**数据集 floor——DG 4.25 / WildGS 3.63 证明）。
- **不再深化 local photometric 像素加权**（A/B/C 已证明此维度饱和）。下一步可行 = long-horizon 位姿正则 /
  KF-BA 行为 / 换位姿估计器。
- **codex 战略提醒固化**：RGD pt1 ATE 7.2 靠全局对齐（其 RPE 2.52 > 我们的 1.60），"用局部加权关 ATE 差距"
  目标不成立。

## 方法面收益（已可用）
- **edge_threshold=3.0 是纯 config 正增益**：pt1 11.89→9.16（-23%）、pt2 10.44→9.06（-13%），
  跨 person 序列通用，零核心改动。可作为 combined 骨干的默认旋钮或诚实记录为 robustness 改进。
- **H-e（hard_tracking_mask + track_erode_px）保留为可控旋钮（默认关）**，核心改动已 commit，可回滚。

## 落盘
- 数据：`P6-EFACT/`（B/C）、`P6-MASON-grad/`（A=edge3/5, edge2 在 pt1Hd）。
- 代码：`SemanticMask.hard_tracking_mask`（H-e）+ `track_erode_px`（E-C），默认关。
- 竞品对照：RGD pt1 RPE 2.52 / 我们的 edge3 RPE 1.60（局部更好）。

## 下一步（不做 local weighted 深化）
- pt1/person-tracking 探索收敛：edge3 是最优可落地改进。若要再压 pt1，走 long-horizon 位姿正则 /
  KF-BA / 换估计器（不属本 session local photometric 范畴）。
