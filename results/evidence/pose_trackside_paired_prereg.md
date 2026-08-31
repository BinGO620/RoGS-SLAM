# 预注册（第二版）—— tracking 侧正控制的**配对化装置** + E/F 的 within-config 地板

> 前序：主预注册 `pose_trackside_prereg.md`（`364da26c`）→ 判决 `pose_trackside_verdict.md`（`e9ec3738`）
> → 附录预注册 `pose_trackside_prereg_addendum.md`（`2985dd07`）→ 门 NO VERDICT
> `pose_trackside_hard_gate.md`（`c02b374e`）。
> 本文件**在复跑批的第一个 run 之前 commit**，此后不改。

## 0. ⚠ 效力声明 —— 这不是一次盲注册，必须先说清

**我已经看过配对位移了。** 上一轮门判 NO VERDICT 之后，我在 `pose_trackside_hard_gate.md` §5
事后算了逐 seed 配对位移并写了下来：

```
P(F_s) − P(E_s) = +0.0360 / +0.1486 / −0.0546      (单 run 口径, 均值 +0.0433, 符号 2/3 正)
```

由此产生两条**硬约束**，本文件必须遵守：

1. **不注册任何符号一致性规则。** 符号我已经看过（2/3 分裂），拿它当判据是自欺。
   凡"逐 seed 同号 k/3"形式的门，本轮**一律不用**。
2. **本轮真正未见的是分母** —— E 与 F 各自的 **within-config 配对地板**（同 config 同 seed 跑两次
   的 |ΔP|）。那正是复跑要买的东西，也是唯一能让这个门变得可判或明确不可判的量。

⇒ 本文件的准确标签是 **「分子部分已知、分母未知的预先指定分析」**，
**不是**「盲预注册」。分子还会变（主统计量改用**复跑平均后的格均值**，由 12 个 run 算出，
而我只看过其中 6 个的单 run 值），但我的预期已被上面那三个数锚住 —— 照记，不掩饰。

## 1. 为什么换配对化 —— 以及配对**修的是什么、不修什么**

上一轮门比的是「均值位移 vs **臂内极差**」，而极差随 n 只增不减（exp35 判据 #12）
⇒ 停跑规则**第二次为同一理由响**。配对化要换掉的就是这个比法。

**配对修的**：seed 层面的共同变动（初始化、KF 选择的 seed 依赖部分）。
**配对不修的**：**run-to-run 非确定性** —— 同 config 同 seed 跑两次也不一样
（exp26 记过 2.99 vs 33.70 的极端例；exp37 的 4 对 balloon 复跑 |ΔP| 达 0.0831）。
F 臂的散正是**这一类**（seed1 的 0.5393 与另两个离得远），**所以配对本身很可能救不了它** ——
这就是为什么本轮的第一步是**可达域检查**，不是判决。

## 2. 装置：6 run（而不是 2）

复跑写进**同一个 run 目录**（同 config、同 seed、同 `--results-root`）⇒ 时间戳目录追加、
`tracking_raw.csv` 累积行，与 exp37 那 4 对 null 的落盘形式一致，现有 `_load_runs` 自动认得。
**无新 config**：复跑就是把同一个 config 再跑一次。

| 臂 | config | 现有 | 本批新增 | 合计 |
|---|---|---:|---:|---:|
| **E** trackside（① 10/100） | `pba_trackside_only_balloon.yaml` | 3（seed 0/1/2） | **3** | 6 |
| **F** track-hard（① 100/100） | `pba_trackside_hard_balloon.yaml` | 3（seed 0/1/2） | **3** | 6 |

**为什么 6 而不是"给 F 补一对"**：配对位移 `Δ_s = P̄(F,s) − P̄(E,s)` 的噪声由**两个**臂的
within-config 方差共同决定。本轮的核心怀疑正是**"F 比 E 更散"**（放大通道①⇒剔除更多像素
⇒约束更少⇒对初始化更敏感），若只补 F 而把 E 的地板从 A/C 臂借过来，就是**用假设回答问题**。
并发 3 时 6 run 与 2 run 的 wall-clock 同为 ~30 min（上批 3 run 用了 16 min）⇒ 代价可忽略。
**顺带**：E 与 F 各自地板的比较**直接检验**上一轮那条候选解释（描述性，不作门）。

## 3. 主统计量（形状与地板同形）

```
格均值      P̄(arm, s) = mean over that cell's runs of P(run)        (复跑后 r=2)
配对位移    Δ_s       = P̄(F, s) − P̄(E, s)
主统计量    shift     = mean over s in {0,1,2} of Δ_s
```

`P` 的定义、协变量、运动匹配分层**全部 import exp37**（`scripts/pose_rpe_calibration.py`），
不重新拟合、不换口径。

**地板必须与主统计量同形**（这是本轮的关键设计）：用 6 个 within-config 复跑对造一个
**同形状的经验 null** —— 对每个臂、每个符号向量 `ε ∈ {−1,+1}³`：

```
null_shift(arm, ε) = (1/3) · Σ_s  ε_s · [ P(cell_s 的 run_a) − P(cell_s 的 run_b) ]
```

每个臂 8 个符号向量给 4 个不同幅度（全翻符号只是取负），两臂合计 **8 个不同的 |null_shift|**。

```
floor_paired = max |null_shift|          （取 max 而非 mean，保守，与 exp37 一致）
```

这个 null 与主统计量**同形状**（都是"3 个 seed 的配对差之均值"）、且两侧都是**同 config**
⇒ 期望为 0，run-to-run 非确定性与自相关对它做的事和对主统计量一样。

## 4. 第 0 步 = 可达域检查（**注册在判决之前**，exp32 判据 #4）

```
floor_paired ≤ 0.0831 ?
```

`0.0831` = exp37 注册的地板，即**该判决把什么幅度当作"有意义"的下限**。理由：若配对化之后
地板反而不小于原来那个，配对就没有买到任何分辨率，这条路线（候选 (a)）就是死的。

- **不过 ⇒ `UNREACHABLE`**：**这是一个合法的预注册结局**，不是"失败后重新解释"。
  同时**必须报出**：要让 `floor_paired ≤ 0.0831`，按 `1/√r` 缩放需要每格多少个复跑 `r`
  （以及总 run 数），并据此宣布路线 (a) 关闭或值得继续。
- **过 ⇒ 进第 1 步。**

**exp37 的停跑规则不适用于本轮**：那条规则比的是"臂内极差 vs 两点预言间距"，
而本轮是装置门、没有两点预言。**可达域检查取代它**，且它检查的是同一件事的正确版本。

## 5. 第 1 步 = 判决规则

| 落点 | 结论 |
|---|---|
| `\|shift\| > floor_paired` | **APPARATUS-TRACKING-SENSITIVE** ⇒ 动态惩罚**确实**响应 tracking 侧介入 ⇒ exp37 的 `TRACKSIDE-INERT` **站住**，含义收窄为「通道①**在其 10/100 的作用域内**买不到动态特异的逐帧跟踪改善」 |
| `\|shift\| ≤ floor_paired` | **APPARATUS-TRACKING-BLIND** ⇒ 把通道①放大 10 倍作用域仍不动这个估计量 ⇒ exp37 判决**降级为描述性**，不得作为关于 tracking 侧机制的结论 |

**不预言方向**（放大①既可能降 P 也可能升 P —— P1b 的杠杆效应）。门只问「P 会不会动」。
**不注册符号规则**（§0 已说明原因）。

## 6. 装置门（收批后逐 run 验，任一不过 ⇒ 该 run 不进读数）

| 门 | 内容 | 判据 |
|---|---|---|
| **J-1** | 忠实性锚 | 每个 run 重算 `ate_rmse_cm` / `rpe_trans_rmse_cm` 与出厂 CSV 差 ≤ 5e-3 cm（exp37 已 22/22 与 12/12） |
| **J-2** | 复跑真的是复跑 | 每格必须有 **≥2** 个时间戳 run，且两个 run 的 `config.yml` 解析后 `SemanticMask` 四个开关**逐字段相同** |
| **J-3** | 通道存活（正负两侧） | F 与 E 的 `mad_excl_semantic` frac ≥ 0.95；插入门 **0 次**（两臂 `mask_insertion=false`） |
| **J-4** | 臂标未漂 | F 与 E 的唯一差异仍是 `hard_tracking_mask`（由 `TestPBATracksideHardConfig` 钉住） |

## 7. 本轮不做什么

- **不看 ATE**（仍 Phase 0）。上一轮 flagged 的「F 臂 ATE 7.42 最低」**仍不判**，
  它需要自己的预注册（且 balloon ATE 正是 exp36 判为不可分辨的口径）；
- 不改 exp37 已 commit 的任何数字、阈值或标签 —— 本批只决定那个标签的**效力等级**；
- 不改 exp36 的 trackside ATE 判决（仍 INDETERMINATE）；
- 不扩序列（balloon 是唯一有协变量且地板可测的序列）；
- **不注册符号一致性门**（§0）；
- 若判 `UNREACHABLE`，**不就地放松 0.0831**，改走候选 (b)「换不 destabilize 臂的介入」
  或 (c)「within-run 注入」。
