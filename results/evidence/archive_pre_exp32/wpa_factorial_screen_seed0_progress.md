# WP-A seed-0 screening — 进度与描述性 screen（非判决）

> **单 seed 是 screening [纪律⑤]，不下判决。** 3-seed 齐（seeds1/2 全体完成）才走 A1-A5 判决。
> 所有数字为描述性 screen，不是预注册判决。

## mv_no_box seed-0（8 臂全完成，778/778 帧全过 95% 闸）

| 臂 | K | R | L | ATE (cm) |
|---|---|---|---|---|
| K0R0L0 | 0 | 0 | 0 | 6.09 |
| K1R1L1 | 1 | 1 | 1 | **3.29** |
| K0R1L1 | 0 | 1 | 1 | 4.78 |
| K1R0L1 | 1 | 0 | 1 | 3.84 |
| K1R1L0 | 1 | 1 | 0 | 3.70 |
| K0R1L0 | 0 | 1 | 0 | 4.13 |
| K0R0L1 | 0 | 0 | 1 | 6.15 |
| K1R0L0 | 1 | 0 | 0 | —(in progress at snapshot) |

**边际 Δ（log-ATE，mv_no_box 完全配置处）**：
- Δ_K = log(4.78/3.29) = **+0.37** （去掉 K 成本）
- Δ_R = log(3.84/3.29) = **+0.16** （去掉 R 成本）
- Δ_L = log(3.70/3.29) = **+0.12** （去掉 L 成本）

**单 seed 读出**：三个 Δ 都正 ⇒ 在 K1R1L1 处逐个去掉组件都退化（mv_no_box 上各组件"局部必要"方向）。
**但** 方差大（3090 seed 间可达 10-20%），**必须 3-seed 后判决**；不当预注册结论。

**G1-G5**（已完成 runs 抽验）：
- G1 自跟踪 PASS：Oracle.pose_file 空 / gt_pose false / cam lr>0。
- G2 旋钮 PASS：config.yml 每 run 确认 K/R/L 与臂一致。
- G3 activity PASS：`reliability_signal/` 目录 L=ON 有、L=OFF 无（E0 亦证 L 改变 reject 语义+ATE）。
  R/K 无默认 verbosity console 日志，但 config + 臂间 ATE 差确认 live。
- G4 ATE 口径 PASS：只读 `tables/tracking_raw.csv` ate_rmse_cm。
- G5 provenance PASS：每 run 落 config.yml（含 kwargs/commit）。

## 状态
- 120-run 批量发行中；当前 mv_no_box2 seed-0 在跑。
- 产出：`results/runs/WPA/WPA-FACTORIAL/wpa_{seq}_{arm}_seed{seed}`。
- readout：`scripts/wpa_factorial_readout.py`（3-seed 齐后出 L1/L2/L3 + Δ + A1-A5）。

## 全 5 序列 seed0 边际 Δ（单 seed，非判决，追加于 51-run 时）

| seq | Δ_K | Δ_R | Δ_L | K1R1L1 (cm) | K0R0L0 (cm) |
|---|---|---|---:|---:|---:|
| mv_no_box | **+0.37** | **+0.15** | **+0.12** | 3.29 | 6.09 |
| mv_no_box2 | **+0.87** | −0.02 | **+0.28** | 4.92 | 11.82 |
| pt2 | **+1.07** | −0.13 | **+0.13** | 8.97 | 43.50 |
| balloon | −0.11 | **+0.75** | **+0.25** | 11.83 | 40.67 |
| pt1 | +0.01 | **+0.45** | −0.12 | 35.45**⚠** | 27.71 |

**screen 读出（**单 seed，不下判决**）**：
- K（dense-KF）在 3/5 序列（mv_no_box2 0.87、pt2 1.07、mv_no_box 0.37）强正 —— K 是最显的杠杆；
- R/L 方向跨序列不一致（balloon 极度依赖 R 0.75、pt1 依赖 R 0.45；pt2/mv_no_box2 上 R 反而 ≈0/负）——
  正是需要 3-seed 完整析因才知道 R 是不是"局部必要"；
- **pt1：K1R1L1(35.4) > K0R0L0(27.7)** —— 完整配置在难 person 上反而比骨架更差，对应 A5 负交互/
  该序列非本实验适用域（P6 已证 mask-free pt1 边界失效）。此事后段必须单独成段报告，不得强翻。

**纪律**：所有以上为 seed0 描述性 screen；**3-seed 判决（k=3/2/≤1 配对 + ε=0.10 + A1-A5）** 决定分支。
seeds1/2 已在续跑中（mv_no_box2 已至 seed1，mv_no_box seed1 8/8 完成）。

## 2-seed 描述性补充（seed0+seed1，mv_no_box / mv_no_box2；非判决）

| seq | Δ_K 2-seed | Δ_R 2-seed | Δ_L 2-seed |
|---|---|---|---|
| mv_no_box | [**+0.37**, **+0.07**] mean +0.22 | [+0.15, −0.18] mean −0.01 | [+0.12, −0.24] mean −0.06 |
| mv_no_box2 | [**+0.87**, **+0.48**] mean **+0.67** | [−0.02, +0.17] mean +0.07 | [**+0.28**, **+0.15**] mean **+0.21** |

读出：Δ_K 在两序列均同号正（mv_no_box2 尤其稳）；Δ_R/Δ_L 在 mv_no_box 跨 seed 翻号（seed 方差大）→
**3-seed 前的 R/L 必要性不可判**。这正是 ε=0.10 + k=3 配对要处理的高方差。seed2 齐后（k=3）才判决。

## 2-seed 全 5 序列 readout 初跑（descriptive，非判决）— 2026-08-14 12:xx

`scripts/wpa_factorial_readout.py` 已在远程对 2-seed 状态成功跑通（L1/L2/L3 + Δ + branch）。
**机械输出 `A2-partial-redundant`：R≈0 在 3/5（mv/mv2/pt2）、L+ 在 3/5、K 强正/强负混合**。

⚠ **统计警告**：所有 cell 当前 k=2（seed2 未到）→ 按预注册 k=2 是 **descriptive-only**，
**不得用于 A1 计数**；readout 的 branch 标签在 k=2 时是**机制性产出、非判决级**。
→ 真正判决**只能在 120-run（全 k=3）后**。文件 `results/evidence/wpa_factorial_readout_partial.{md,json}`（远程）
**不写进正式 verdict 来源**，只作装置 smoke-test + 早期方向参考。

**早期方向（未证实）**：若 3-seed 保持，必要条件子集可能收敛为 **{K, L}**（R 在 3/5 上 ≈0）；
但 pt1 上 K 负（去掉 K 反而帮助 = 边界失效）且 R 强正 —— 高度 seq 依赖。等 seed2。

## mv_no_box 首个 k=3 cell（3-seed 齐）— 2026-08-14 13:xx

- K1R1L1 ate: seed0 3.29 / seed1 3.67 / seed2 **2.87** → mean **3.28±0.40**, completion 3/3。
- Δ_K = +0.25 (seeds +0.37/+0.07/+0.31, **3/3 同号正** > ε) → **K 在完整配置处局部不可约（mv_no_box）**。
- Δ_R = +0.03 (seeds +0.16/−0.19/+0.12, **跨 seed 翻号**) → 未达"3/3 同号"，**R 在 mv_no_box 上非稳健必要**。
- Δ_L = −0.06 (k=2，K1R1L0 seed2 未到) → descriptive only，等 seed2。

**mv_no_box 上 A1 候选判否**（R 非 3/3 正），与 2-seed 的 {K,L} 必要子集猜测一致 —— 但**只此一序列、非全局判决**。
全 verdict 需 5 序列 k=3 + 跨序列 A1-A5 规则。继续等 seed2（其余序列 0/8）。

## mv_no_box 完整 3-seed marginall（24/24）— 2026-08-14 13:4x

| Δ | ratios (seed0/1/2) | mean | decision |
|---|---|---|---|
| Δ_K | +0.37 / +0.07 / +0.31 | **+0.25** | **positive**（3/3 同号正，K 局部不可约） |
| Δ_R | +0.16 / −0.19 / +0.12 | +0.03 | **zero**（跨 seed 翻号+均值<ε，R 非必要） |
| Δ_L | +0.12 / −0.24 / +0.59 | +0.16 | **mixed**（均值>ε 但非 3/3 同号，一对 seed 互抵） |

⇒ **mv_no_box 上 A1 判否**（R 需要正但=zero，L=mixed）。唯一稳健不可约 = **K**。
单序列，非全判决。若 Δ_R≈zero 在 ≥3/5 序列复现 ⇒ A2 partial-redundant（必要子集收窄）。

## mv_no_box2 完整 3-seed marginal（24/24）— 2026-08-14 15:1x

| Δ | ratios | mean | decision |
|---|---|---|---|
| Δ_K | +0.87 / +0.48 / +0.41 | **+0.59** | **positive**（K 强不可约） |
| Δ_R | −0.02 / +0.17 / −0.19 | −0.01 | **zero**（跨 seed 翻号+均值≈0，R 冗余） |
| Δ_L | +0.28 / +0.15 / −0.04 | +0.13 | **mixed** |

## 两序列（mv_no_box + mv_no_box2，纯物双复现）一致结构

**K 局部不可约（+0.25/+0.59），R≈zero（两 seq 都！），L=mixed。**
→ 若 Δ_R=zero 在 ≥3/5 复现（pt2/balloon/pt1 待），⇒ **A2 partial-redundant**，R 从必要子集剔除。
**pt1 是 R 可能的反例**（seed0 上 Δ_R 强正 +0.45）—— 高方差难跟踪 regime 可能依赖 R。
3/5 序列待 seed2（pt2 进行中，balloon/pt1 未开始）。

## pt2 完整 3-seed marginal（24/24）— 2026-08-14 16:1x

| Δ | ratios | mean | decision |
|---|---|---|---|
| Δ_K | +1.08 / +0.52 / +0.56 | **+0.72** | **positive**（person 上 K 也强不可约） |
| Δ_R | −0.13 / −0.06 / +0.16 | −0.01 | **zero**（第三个序列 R 冗余） |
| Δ_L | +0.13 / +0.16 / +0.22 | **+0.17** | **positive**（pt2 上 L 必要 3/3 同号） |

## 3/5 序列一致结构（mv/mv2/pt2: 纯物+纯人 easy/medium）

**K 不可约（+0.25/+0.59/+0.72），R≈zero（3/3！），L mixed/positive。**
→ 若 balloon/pt1 上 R 仍≈zero ⇒ 5/5 R 冗余 → **A2 partial-redundant 强证据**（必要子集={K, L?}）。
但 balloon（seed0 Δ_R +0.75）与 pt1（+0.45）seed0 显示 R 在 medium/hard 上可能必要 —— 观望。

## balloon 完整 3-seed marginal（24/24）— 2026-08-14 17:1x

| Δ | ratios | mean | decision |
|---|---|---|---|
| Δ_K | −0.11 / −0.33 / −0.11 | **−0.18** | **negative**（3/3 同号：balloon 上去掉 K 反而帮助，K 有害） |
| Δ_R | +0.75 / +0.82 / +0.77 | **+0.78** | **positive**（3/3：R 在 balloon 上强不可约！rescues R） |
| Δ_L | +0.25 / +0.51 / +0.12 | **+0.29** | **positive**（L 也可谓重要） |

## 4/5 序列完整 —— 非普适模式浮现

| seq | Δ_K | Δ_R | Δ_L |
|---|---|---|---|
| mv_no_box | +0.25 | 0.03(zero) | mixed |
| mv_no_box2 | +0.59 | −0.01(zero) | mixed |
| pt2 | +0.72 | −0.01(zero) | +0.17 |
| balloon | **−0.18(neg)** | **+0.78(pos)** | +0.29 |

**K 在纯物/纯人 easy 上不可约、但在 balloon（混合 mover）上有害；R 在 easy 上冗余、在 balloon 上关键。**
⇒ 高度 regime 依赖，非 A1（无序列三者全正）。**A5 候选**：Δ_K 负仅在 balloon（1/5）；若 pt1 上某 Δ 负
⇒ A5；否则 A4 seq-dependent 或 A2 partial-redundant。等 pt1（6/8 中）。
