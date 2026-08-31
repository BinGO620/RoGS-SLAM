# DBAphoto step2 — GN 指标修复（headline 口径 ATE）预注册

> 2026-08-03 | branch `dba-photo-weighted` | 起跑前 commit，§1–§3 = 跑前预声明，§4 = 结果
> 前情：`p2_dba_geo_oracle_outcome.md`（oracle INCONCLUSIVE + GN step test 指标不可比）
> 性质：**non-preregistered 探索的收尾测量**。不改 H-D / P2-T 任何已定记录。

## §0 封顶条件（用户 2026-08-03 拍板，先于任何数字）

**无论本次出什么数，路线①都不进 MMM 2027。** 理由是装置事实不是判断：
主表 P2-T 36 run 已冻结，换 tracker ⇒ 全表重跑（~15–17h）+ 渲染/效率/P2-SF 下游全部重生成，
而 08-06 是写作硬起点、08-16 AOE 是 DDL。

因此本测量的**最大可能产出 = 下一篇的 lead + 干净存档**，不是本篇的改进。
任何分支都不得触发：主表重跑、H-D 记录修改、P2-T 判决修改、叙事分支变更。

## §1 门控问题

GN step test 报的 85–98cm 是 **KF0-gauge-shared camera-center RMSE**，
与 headline 的 2.6–3.0cm 不同口径（codex 019fc7e1 判为 fatal）。
问题：**把 GN 每步位姿放进 headline 的同一个 ATE 协议里，改善还在不在？**

## §2 协议（by import，不重写）

readout = `scripts/r2_p2_dba_gn_umeyama.py`，ATE 由
`utils.eval_utils._evaluate_trajectories` **导入**（与 `tracking_raw.csv` 的
`ate_rmse_cm` 同一函数），不复制实现。

**协议修正（跑前决定）**：`p2_dba_geo_oracle_outcome.md` §未完成 写的是 "Sim(3)-Umeyama"，
本次改用 **SE(3)-Umeyama（无尺度）**，即 `monocular=False`。理由：这些是 RGB-D run，
headline 本身就是 `correct_scale=monocular=False`；放开尺度自由度会让全局 scale 吸收误差，
得到一个既偏乐观、又与 headline **不可比**的数 —— 而不可比正是本次要修的病。

三个读数（每个 GN 迭代都算）：

| 读数 | 定义 | 地位 |
|---|---|---|
| `full_sub` | 全轨迹，KF 帧换成 GN 位姿，非 KF 帧留在 online 位姿 | **PRIMARY** |
| `kf_ate` | 只取 KF 子集，在 KF 子集上对齐 | 诊断 |
| `full_prop` | 全轨迹，非 KF 帧按 T_rel 被各自 ref KF 刚性带走 | 诊断（乐观上界） |

**为什么 PRIMARY 是 `full_sub`**：`run_dba_v0`（`dba_lite.py:931`）**只写回 KF 位姿**，
且在 `slam.py` 里跑在 `final_pose_refinement()` **之后**（非 KF 位姿那时已定），
而 headline `ate_rmse_cm` 是全轨迹口径 ⇒ `full_sub` 就是路线①真上线后
`tracking_raw.csv` 里会出现的那个数。`full_prop` 是"如果非 KF 也重组"的上界，
**ref-KF 归属是重建的**（取最近的前一个 KF；在线 `ref_kf_id` 未落盘）⇒ 只作诊断。

## §3 硬门 + 判据（跑前钉死，事后不得改）

**硬门（不过 = readout 作废，不进入"解读"）**
- **G0**：用 online 位姿离线重算的全轨迹 ATE == `tracking_raw.csv` 的 `ate_rmse_cm`，
  容差 1e-3 cm。证明本脚本复现的就是 headline 那个数。
- **G1**：GN iter-0 的 KF 位姿 == 该 run 的 online KF 位姿，容差 1e-6。
  证明 GN 轨迹起点确实是 online 位姿。

**可分辨带**：0.14 cm（P2-T 的 seed-to-seed sd，见 HANDOFF P2-RT spike 条目）。
低于此 = 不可分辨，**不是**"小改善"。

**三分支处置**
- **(R-NOGO)** `full_sub` 改善 < 0.14cm，或 4 run 符号分裂 ⇒
  **路线① 干净 NO-GO**。存档关门，跟踪维持 P2-T，不留 lead。
- **(R-LEAD)** 4/4 run `full_sub` 改善 ≥ 0.14cm **且** 最优迭代 = 末次迭代
  （不许挑中间迭代 —— codex 019fc7e1 反对意见 #2 就是 ATE 非单调）⇒
  记为**下一篇 lead**，本篇零改动（§0）。
- **(R-AMBIG)** 其余（含改善达标但非单调、或 gate 过而三读数互相打架）⇒
  **INCONCLUSIVE-CLOSED**：按现状存档，本轮不再投 GPU。

**刻意不做**：不扫 `lm_prior`；不跑端到端 `DBALite.enabled` 的 4-run 确认
（那是 ~2h GPU，只有落 R-LEAD 且用户另行批准才排期，且属下一篇）；
不动 `run_dba_v0` 的 live code。

## §4 结果（2026-08-03，GN 复跑 1.0min + 离线重算，零额外 GPU）

装置：GN 复跑 `d0ce2b2`，**逐位复现**上一次的 KF0-gauge 数
（85.86→84.00 / 85.85→83.80 / 98.37→98.46 / 98.09→97.75，cost_ratio 0.538–0.542，
accepted 5/5）⇒ 存位姿的改动没有扰动被测对象。

### §4.1 硬门

| run | G0 recorded vs offline | G0 | G1 max dev | G1 |
|---|---|---|---|---|
| balloon s0 | 3.0317 vs 3.0317 | **PASS** | 6.50e-07 | **PASS** |
| balloon s1 | 3.1011 vs 3.1011 | **PASS** | 5.85e-07 | **PASS** |
| mv_no_box s0 | 2.5716 vs 2.5716 | **PASS** | 1.01e-06 | **FAIL** |
| mv_no_box s1 | 2.6862 vs 2.6862 | **PASS** | 8.24e-07 | **PASS** |

- **G0 4/4 PASS，且是逐位相等**（Δ < 1e-6 cm）⇒ 本脚本算的确实就是 headline 那个数。
- **G1 3/4 PASS**。`mv_no_box s0` 偏差 1.01e-06 越界（阈 1e-06）。
  成因可核：GN 在 **float32** 下跑并按 float32 落盘，1e-06 是 float32 有效位边缘 ⇒
  **这是我把 G1 容差定得比数值精度还紧的装置缺陷，不是该 run 有问题**。
  按 §3 处置：**该 run 出主读数**（容差事后不得放松）。它的方向另作
  **labeled sensitivity** 报（见 §4.4），**不参与分支判定**。

### §4.2 PRIMARY：`full_sub`（run_dba_v0 上线后会写进 `ate_rmse_cm` 的那个数）

| run | online (iter0) | iter5 | Δ | 最优迭代 | 单调下降 |
|---|---|---|---|---|---|
| balloon s0 | **3.0317** | **12.6300** | **+9.5983** | **iter 0** | 否 |
| balloon s1 | **3.1011** | **12.7781** | **+9.6770** | **iter 0** | 否 |
| mv_no_box s1 | **2.6862** | **6.0681** | **+3.3819** | **iter 0** | 否 |

三个诊断读数**全部同向**（balloon s0：`kf_ate` 3.0034→24.5464，
`full_prop` 3.0317→24.4510）；**三个 run × 三个读数 = 9/9 的最优迭代都是 iter 0**，
即 **online 位姿本身**。每一步 GN 都比上一步更差，逐步单调**变坏**。

⇒ **落 (R-NOGO)**：不但没到 0.14cm 可分辨带，而且是**反方向的大幅劣化**
（+3.4 ~ +9.7cm，是可分辨带的 24–69 倍），4/4 run 同号（含 sensitivity 那格）。

### §4.3 KF0-gauge 那个 −1.85cm 是什么

同一批位姿，两个口径：

```
                      KF0-gauge (旧)        headline SE(3)-Umeyama (新)
balloon s0  iter0        85.86 cm                   3.03 cm
balloon s0  iter5        84.00 cm  (−1.86)         12.63 cm  (+9.60)
```

online 位姿在 KF0-gauge 下是 85.86cm、在 Umeyama 下是 3.03cm ⇒
**那个基线里约 96% 是全局对齐量，不是轨迹误差**。GN 做的事是：
消掉约 1.9cm 的全局错位，同时把轨迹形状**扭坏约 9.6cm**。
Umeyama 把全局刚体自由度整个吸收掉，所以只剩下形变，劣化就露出来了。

**这同时回答了 codex 019fc7e1 的反对意见 #4（"可能是 gauge-like 运动"）——
答案是反的：如果它是 gauge-like 的，Umeyama 会把它吸收掉、ATE 应当基本不动；
实测 ATE 大幅变坏 ⇒ GN 步是真形变，不是规范自由度上的滑动。**

连带影响 oracle 的解读（**不撤销 oracle 的 cost 类数据**，那些是 cost 不是 ATE）：
oracle 的 `dir_deriv` 是朝"KF0 处刚体对齐后的 GT"求的方向导数，而那个目标本身
带着 85cm 量级的 gauge 残差 ⇒ **`dir_deriv<0`（"GN 局部方向指向 GT"）里含 gauge 成分**，
端到端测出来的是：沿该方向走，对齐不变量意义下的精度**变差**。
`p2_dba_geo_oracle_outcome.md` 里"浅盆信号"的乐观读法就此作废（该文件已就地加注）。

### §4.4 labeled sensitivity（不参与分支）

`mv_no_box s0`（G1 越界 1.01e-06，装置缺陷见 §4.1），把 G1 容差 override 到 1e-5 后
（`--g1-tol 1e-5`，脚本会打印 LABELLED SENSITIVITY 抬头）：
`full_sub` **2.5716 → 6.1827（Δ +3.6111）**，`kf_ate` 2.6010→10.9517、
`full_prop` 2.5716→10.9786，最优迭代 = **iter 0**，三读数同向。
**与三个 gate-PASS run 同号同量级**（Δ +3.61 vs +3.38 / +9.60 / +9.68）
⇒ 不改变 §4.2 的分支，只是把 4/4 补全。

### §5 判决

**路线①（给 DBA-lite 几何项加 reliability 权重）= 干净 NO-GO，关门。**

比 step2 收尾时的 INCONCLUSIVE 更强：不是"测不出改善"，而是
**最小化这个加权几何目标会主动把轨迹推离 GT**（cost 降 46% 的同时 ATE 涨 3.4–9.7cm）。
换句话说，该目标的极小值不在真位姿附近 —— 这与 oracle 的 `R_dyn=3–7`
（GT 不在同一有用盆）一致，而且现在是在**能下判决的口径**上测到的。

**处置（按 §0 封顶，无一例外）**：
- 跟踪维持 **P2-T 现状**（balloon 3.07 / mv_no_box 2.58 / pt1 10.97），不动主表。
- **不留 lead**（(R-NOGO) 分支明确不留）：这不是"没调好"，是目标函数方向就不对；
  下一篇若再碰 BA 方向，**不得**从本结果继承"加 reliability 权重值得再试"。
- `DBALite.enabled` 保持 default-off；`run_dba_v0` live code 未改。
- H-D / P2-T / P2-SF 所有已定记录**未动**。

**方法论留档（这条比结论本身更可复用）**：位姿类改进的判据必须在
**对齐不变量**口径上下（headline 用的 evo SE(3)-Umeyama）。
KF0-gauge / 单锚点 camera-center RMSE 会把全局对齐量混进"精度"里，
本例中它把一次 +9.6cm 的劣化显示成 −1.86cm 的改善 —— **符号都是反的**。
