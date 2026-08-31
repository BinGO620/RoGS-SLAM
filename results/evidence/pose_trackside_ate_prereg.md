# 预注册 —— F 臂的 **ATE 终点**：通道① 扩大作用域后，累积漂移往哪走？（exp37, 2026-08-22）

> **读数前注册。** 12 个 run 已全部落盘（E×3 + F×3 首批，各 +3 复跑），ATE 就在
> `tracking_raw.csv` 里 ⇒ **本轮零 GPU**。本文件在 `scripts/pose_trackside_ate_gate.py`
> 存在之前 commit，此后不改。
>
> 前序链：`pose_trackside_prereg.md`(`364da26c`) → `pose_trackside_verdict.md`(`e9ec3738`)
> → `pose_trackside_prereg_addendum.md`(`2985dd07`) → `pose_trackside_hard_gate.md`(`c02b374e`)
> → `pose_trackside_paired_prereg.md`(`07a14ff3`) → `pose_trackside_paired_gate.md`(`c065ccd9`)

## 0. ⚠ 效力声明（与配对预注册同一格式，先说清）

**已看过的**：F 首批三个 ATE = **7.4447 / 6.9805 / 7.8344**（`pose_trackside_hard_gate.py` 的
provenance 列打印过），E 首批三个 = **8.18 / 9.72 / 9.40**。所以「F 的 ATE 均值 7.42 比 E 的 9.10 低」
这件事我**已经知道**，它正是本轮立项的原因（上两轮都作为 flagged-未判决记录在案）。

**未看过的**：
1. **6 个复跑的 ATE**（E×3 + F×3）—— 主统计量用**复跑平均后的格均值**，由 12 个 run 算出，
   我只看过其中 6 个；
2. **整个分母** —— ATE 的 within-config 地板，本轮第一次量。

⇒ 准确标签同上一轮：**「分子部分已知、分母未知的预先指定分析」**，**不是盲注册**。
**照此，本轮不注册任何依赖「我已知道 F<E」的规则**（例如"单侧"检验、或方向性的点预言）；
判据对符号**对称**，方向由读数给出。

## 1. 为什么这是一个**新问题**（而不是上一轮的延续）

上一轮判的是**逐帧动态惩罚**这个终点：`shift_P = +0.0806 > floor_P = 0.0662`
⇒ 把通道① 从 10/100 扩到 100/100 让**逐帧跟踪在动态帧上变差**。

本轮换的是**终点**：从「逐帧跟踪质量」换成「整条轨迹的累积漂移」（ATE）。
按 exp33 判据 #10，**换 estimand/终点 = 新问题 ⇒ 必须重新注册**。

**为什么值得**：exp37 已实测两终点**解耦且跨序列不单调**（null 复跑 ATE 差 10% 而逐帧 RPE 中位差
在地板上；f3_wk_xyz ATE ~10× 而 RPE 仅 2.7× 地板）。若本轮测到 **F 的 ATE 显著更好**，
那就是这条解耦最锋利的一例 —— **同一个单变量介入同时让逐帧跟踪变差、让累积漂移变好**。
这不是锦上添花：它直接约束「位姿侧到底在哪一层被 mask 影响」这个方法问题。

**为什么现在才能做**：exp36 判过 balloon ATE 在该口径下**不可分辨**（臂内极差 1.3–1.5 vs 效应 2.3）。
但那时**没有复跑** ⇒ 无法把「run-to-run 非确定性」与「seed 间真实变动」分开。
现在 E/F 每格有 2 个 run ⇒ **ATE 的 within-config 地板第一次可测**。

## 2. 装置与主统计量（与配对门**同形**，以便两终点可直接并列）

无新 run、无新 config。口径 = `tracking_raw.csv` 的 `ate_rmse_cm`（全轨迹，项目硬规则）。
臂对 = **F vs E**，因为这是**唯一的单变量对**（只差 `hard_tracking_mask`；F vs C/D 不是单变量，
只作描述性上下文）。

```
格均值      Ā(arm, s) = mean over that cell's runs of ate_rmse_cm      (r = 2)
配对位移    Δ_s       = Ā(F, s) − Ā(E, s)                              单位 cm
主统计量    shift_ATE = mean over s in {0,1,2} of Δ_s
```

**地板与主统计量同形**（逐字沿用配对门的构造，连 √2 保守性一起继承）：
对每臂、每个符号向量 `ε ∈ {−1,+1}³`

```
null_shift(arm, ε) = (1/3) · Σ_s  ε_s · [ ATE(cell_s 的 run_a) − ATE(cell_s 的 run_b) ]
floor_ATE = max |null_shift|            两臂共 8 个不同幅度，取 max（保守）
```

两侧都是**同 config 同 seed** ⇒ 期望为 0，run-to-run 非确定性对它做的事和对主统计量一样。

> **⚠ 继承自上一轮的已知构造缺陷（照记，不掩饰）**：这个 null 与主统计量**结构同形但方差不同** ——
> 主统计量是两个**格均值**（各 r=2）之差（方差 σ²），null 项是两个**单 run** 之差（方差 2σ²）
> ⇒ 地板宽 **√2**，对"声称有差异"是保守的，但对**可达域**是偏向关闭的方向。
> 处置与上轮一致：注册规则照原样执行，**方差匹配地板 `floor_ATE/√2` 并列报出**；
> 两者标签不同 ⇒ 报 **CONSTRUCTION-LIMITED**，不挑好看的那个。

## 3. 第 0 步 = 可达域（**注册在判决之前**，exp32 判据 #4）

**最小有意义效应**用项目**已有**的常量，不新拟合：CLAUDE.md 的
「噪声地板 ≥6% ⇒ 单 seed |Δ|<6% 不可读」（exp32 自测）。
以 E 已公开的首批均值 **9.10 cm** 为基数 ⇒ 最小有意义效应 = **0.546 cm**，取

```
REACH_FLOOR_ATE = 0.55 cm
判据：floor_ATE ≤ 0.55  ⇒ REACHABLE
```

**这个门真的可能不过**（不是走形式）：exp36 已记过 `pba_mapping_off_balloon` 的复跑 ATE 差
**0.813 / 0.480 cm** —— 同为 map-OFF 域的臂。若 E/F 噪声相当，`floor_ATE` 就落在阈值附近甚至之上。

- **不过 ⇒ `UNREACHABLE`**（合法的预注册结局）：同时**必须报出**按 `1/√r` 需要每格多少复跑
  `r = ceil(2·(floor_ATE/0.55)²)` 及总 run 数，据此宣布这条路线关闭或值得继续。
  **不得就地放松 0.55。**
- **过 ⇒ 进第 1 步。**

## 4. 判决规则（对符号**对称**，方向由读数给出）

| 落点 | 标签 | 含义 |
|---|---|---|
| `\|shift_ATE\| ≤ floor_ATE`（且可达） | **ATE-INDISTINGUISHABLE** | 扩大通道① 不动累积漂移 ⇒ 上一轮的逐帧读数**单独成立**，无解耦可言 |
| `shift_ATE < −floor_ATE` | **ENDPOINT-DECOUPLED** | ATE **更好**而逐帧惩罚**更差**（`shift_P = +0.0806 > floor_P = 0.0662`，上一轮已定）⇒ **同一介入在两个终点上方向相反** |
| `shift_ATE > +floor_ATE` | **BOTH-ENDPOINTS-WORSE** | 两终点同向变差 ⇒ 无解耦；扩大① 就是单纯有害 |

**`ENDPOINT-DECOUPLED` 的附加要求**（否则降级为 `ATE-BETTER-ONLY`）：
上一轮那条 `shift_P` 的三条界必须一并引用（margin 仅 1.22×、门证明的是「P 会动」不是
「逐 seed 一致」、地板薄且被 seed2 主导）。**解耦是两个读数的合取，不能只靠本轮这一半。**

**不注册符号一致性规则**（逐 seed k/3）：理由同 §0 —— 我已经知道首批三个 F 的 ATE 都低于 E 的均值。
逐 seed 符号**作为上下文打印**，不作判据。

## 5. 装置门（读数前逐 run 验，任一不过 ⇒ NO VERDICT）

| 门 | 内容 | 判据 |
|---|---|---|
| **K-1** | 每格 r=2 | 12 个 run 全在，每格 `tracking_raw.csv` 恰有 2 行且 `run_id` 互异 |
| **K-2** | 复跑真的同 config | 每格两次跑的 `SemanticMask` 四开关逐字段相同（配对门已 6/6，此处复验） |
| **K-3** | 单变量 | F 与 E 之间恰好一个 `SemanticMask` 开关不同 |
| **K-4** | 口径一致 | 全部 12 行的 `success_threshold_cm` 与 `dataset` 相同（防跨口径混读） |

## 6. 次级读数（**描述性，不作判据**，但对全项目实践有用）

第一次可以把 balloon ATE 的噪声**分解**成两层：

```
within-config  = 同 config 同 seed 两次跑的 |ΔATE|            （run-to-run 非确定性）
between-seed   = 各格均值在 seed 间的极差                      （seed 真实变动）
```

**为什么值得写下来**：exp36 把 balloon ATE 判为不可分辨时用的是「臂内极差」，那是**两层混在一起**的量。
若实测 **within-config 占主导**，那么「补 seed」从来就不是解法、**「补复跑」才是** ——
这会改变全项目的做法（此前多次开出的都是"补 seed"处方）。
**⚠ 这条不改 exp36 的 INDETERMINATE**（那是按当时预注册规则做出的判决，规则不追溯修改），
它只说明**下一次**该怎么设计。

## 7. 本轮不做什么

- 不跑任何新 run（12 个已落盘）；
- 不改上一轮的 `shift_P = +0.0806` / `floor_P = 0.0662` / `APPARATUS-TRACKING-SENSITIVE`；
- 不改 exp36 的 trackside ATE 判决（仍 INDETERMINATE），也不用本轮数据去翻它
  —— 本轮比的是 **F vs E**，exp36 比的是 **E vs D**，不是同一个对比；
- 不扩序列（balloon 是唯一两臂都有复跑的序列）；
- 不注册符号规则、不注册单侧/方向性预言（§0）；
- 若 `UNREACHABLE`，**不放松 0.55**，只报所需 `r`。
