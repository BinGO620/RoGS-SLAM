# P9 静态崩溃机制消融（f3_st_hf, async, n=2 筛选）

我们的 mask-free 臂相对 vanilla 只多开四样机制。w≡1 判据（`exp26_w1_causal_prereg.md`）
已排除 `ReliabilitySignal` 的**跟踪路径**（去掉下权重照样 35.99 崩），其余三个 + RS 的
地图路径**从未在静态序列上测过**。本批一次全测，不再一个一个试。

| 臂 | config | 关掉什么 |
|---|---|---|
| V  | `p9_vanilla_f3_st_hf` | 四个全关 = 我们自己的 vanilla 锚点 |
| A1 | `p9_nodynkf_f3_st_hf` | `DynamicKeyframe`（gap_cap=5 强制每 5 帧插 KF） |
| A2 | `p9_norobust_f3_st_hf` | `RobustTracking`（huber IRLS，w≡1 判据的盲区） |
| A3 | `p9_nodeferred_f3_st_hf` | `DeferredCommit`（prune / 延迟提交） |
| A4 | `p9_norelsig_f3_st_hf` | `ReliabilitySignal` 整个（含地图路径） |

全部 async（与主表同模式），f3_st_hf，n=2 筛选。n=3 只留正式数。
