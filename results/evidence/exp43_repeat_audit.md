# exp43 Phase −1 —— 全盘 within-config 重复跑盘点：**崩溃率叙事判死**（零 GPU，2026-08-23）

> **判读（跑前写死在 `scripts/exp43_repeat_audit.py` docstring 里）**：
> median(R) < 1.2 ⇒ 判死。**实测 median(R) = 1.052，n = 12 组 ⇒ 判死。**
>
> 待检验的主张是：「竞品一律报 3-seed 均值、无一报崩溃率；而同 config 同 seed 重复跑
> ATE 能差一倍以上 ⇒ 这是我们独有的贡献轴」。**我们自己的全盘数据不支持它。**

装置 `scripts/exp43_repeat_audit.py`，读数 `exp43_repeat_audit.json`。
扫描 855 个 `tracking_raw.csv` / 872 行。

## 1. 第一遍的结论是污染的（必须连同修正一起读）

第一遍（无 provenance 门）得到 104 个"重复组"，最强 10–19×，看起来信号极强：

```
19.13×  p6_maskoff_prune_f3_st_hf   seed0  [1.89 .. 36.09]
15.78×  p6_maskoff_prune_crowd      seed0  [3.38 .. 53.39]
10.76×  p6_mason_combined_f3_st_hf  seed1  [3.23 .. 34.78]
```

**逐组查 provenance 后判为伪信号**：每一组都是 **2026-08-10/12 的 run 对 2026-08-16/17 的
`*FULLKERN*` run**——即 **exp24 flow-sync 修复前 vs 修复后**。修复前那批的
`ReliabilitySignal` 因冻结 flow 索引为空而**静默退化成 w≡1**（registry 行 EXP24-FLOWSYNC）。
⇒ 同一个 `method` 字符串，**实际配置一个开着内核一个关着内核**。
量到的是 exp25 已经记录过的 kernel-ON/OFF 系统性差异（"动态 4/4 改善、静态 6/6 变差"），
**不是 run-to-run 非确定性**。

**可复用判据（新增）**：跨 campaign 的 `method` 字符串**不是**配置身份。
盘点重复跑必须加 provenance 门（同 campaign = 同代码 + 同冻结资产 + 同硬件），
否则会把"修复前后"读成"同配置抖动"。与 exp24 的静默 no-op、exp39c 的标签互换同族：
**装置身份必须被验证，不能从命名推定。**

## 2. 加 provenance 门后的真实读数

只认**同一 campaign 目录内**的重复：

| | n | median | p75 | p90 | max | >1.5 |
|---|---:|---:|---:|---:|---:|---:|
| **within-config**（同 config 同 seed 复跑） | 12 组 | **1.052** | 1.086 | 1.157 | 1.363 | **0/12** |
| **between-seed**（同 config 跨 seed） | 149 组 | **1.138** | 1.398 | 2.175 | 17.153 | — |

**within / between 中位数比 = 0.92** ⇒ **同 config 复跑的抖动比换 seed 更小。**

最强的 within-config 组（全部 n=2）：

```
1.36×  p6_maskoff_prune_f3_wk_rpy  seed0  [15.72 .. 21.42]  P6/P6-18SEQ
1.16×  wpa_mv_no_box_K1R1L1        seed0  [2.83 ..  3.29]   WPA/WPA-FACTORIAL
1.11×  pba_mapping_off_balloon     seed1  [7.73 ..  8.54]   PBA
1.03×  t2_eboth_balloon            seed0  [3.10 ..  3.17]   PBA
```

## 3. 专门做的崩溃率实验（B-CRASHRATE）拆开看，方向一致

该批 12 run 不在本地盘（只有 `b_crashrate_verdict.json`），拆开两个 block：

| block | 设计 | 范围 (cm) | ratio |
|---|---|---|---:|
| **T** | 同 config **同 seed** × 6 次 | 37.04 – 73.14 | **1.97×** |
| **S** | 同 config **6 个不同 seed** | 28.05 – 77.87 | **2.78×** |

⇒ **即使在 mask-free 高 ATE 的不稳定 regime 里，between-seed 的离散仍大于 within-config。**
与 §2 的全盘比值（0.92）同向，也与 exp37 在 balloon 上测到的
「between-seed 主导 3.6×」一致（那是第三个独立实例）。

## 4. 判读与后果

**判死。** 「同 config 同 seed 不可复现 ⇒ 崩溃率是我们独有的贡献轴」这个主张，
在我们自己的全盘数据上**不成立**：

1. within-config 非确定性在稳定 regime 里是 **~5%**（median 1.05），远低于项目 6% 噪声地板；
2. 在最不稳定的 regime 里也只有 **~2×**（B-CRASHRATE block T）；
3. 而 **between-seed 的离散始终更大** —— 那正是竞品已经在报的东西（3-seed 均值±sd）。

⇒ 竞品"只报 3-seed 均值"并没有隐藏一个更大的复现性问题；他们报的那个轴本来就是更大的那个。
**不立项，不投入 GPU。**

## 5. 自限（这条判死的适用域，必须同报）

- 盘上只有 **12 个**干净的同 campaign 重复组，且**几乎全部在 balloon 这类稳定 regime**
  （mask-ON / mapping-off 臂）。**不稳定 regime（f3_st_hf / crowd2 / mask-free）的干净复跑
  本地几乎没有**，B-CRASHRATE 的 12 run 在远程。⇒ §2 的 median 1.05 主要刻画稳定 regime；
  不稳定 regime 的唯一干净测量是 B-CRASHRATE 的 1.97×。
- 全部 within-config 组都是 **n=2**，ratio 由两点估计，是弱估计量。
- 判死的是「**崩溃率作为独立贡献轴/论文头条**」，**不撤回**任何既有的方法论纪律：
  「mask-free 底座的判决要用崩溃率口径」（exp32/T2）与「噪声分两层」（exp37）仍然成立，
  它们是**内部判据纪律**，本来就不是对外的论文主张。
