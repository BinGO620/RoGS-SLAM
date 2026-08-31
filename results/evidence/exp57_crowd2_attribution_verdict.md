# EXP57 判决 — P11+mask_insertion 单变量臂（crowd2）

> 执行读数与判决，判据冻结见 `exp57_crowd2_attribution_prereg.md`。
> 3/3 run rc=0；E0 门全过（resolved mask_insertion=true，DynKF/Reliability off）。
> 运行于 jiangwenheng 双 RTX 3090（seed0/1 双卡并行 03:23，seed2 串行 03:45，
> 全部完成 04:00:19，墙钟约 37 分钟）。

## 1. 正式读数

| 臂 | seed0 | seed1 | seed2 | mean (cm) | sd |
|---|---:|---:|---:|---:|---:|
| P11+mask_insertion | 8.7348 | 5.1602 | 3.0927 | **5.6626** | 2.8544 |

## 2. 判决（按预注册 §5 三分支）

地板 = max(0.43, 0.06 × max(5.6626, 2.1086)) = **0.43 cm**。
本臂均值 5.66 < P11 6.89 − 0.43 = 6.46 → 且 ≥ Combined + 0.43。

**分支落点：INSERTION-CONTRIBUTES——mask_insertion 有实质贡献（−1.23 cm vs P11）
但不充分（距 Combined 还有 3.55 cm）。**

## 3. crowd2 组件阶梯（六臂全览，EXP53/54/56/57）

| 臂 | 新增开关 | mean (cm) | sd | 距 Combined |
|---|---|---:|---:|---:|
| P11 | —（R+D+M_map） | 6.89 | 1.64 | +4.78 |
| +DynKF | K | 5.16 | 2.25 | +3.05 |
| +Reliability | L | 6.00 | 2.11 | +3.89 |
| +DynKF+Reliability | K+L | 4.55 | 1.38 | +2.45 |
| +mask_insertion | M_ins | 5.66 | 2.85 | +3.55 |
| **Combined** | K+L+M_ins | **2.11** | 0.08 | — |

**读法**：
1. 没有任何单变量臂低于 5.16——三个开关单独的贡献都有限且互相纠缠；
2. 双变量 K+L（4.55）是最佳部分组合，但 Combined（2.11）仍只有它的一半——
   **K+L+M_ins 三者存在强交互**：M_ins 单独 +3.55、K+L 双变量 +2.45，但三者合计 +0.
   （2.11−6.89=−4.78 的改善远超各分量之和的线性叠加预期）；
3. sd 模式同样一致：单/双变量臂 sd 1.4–2.9，Combined sd 0.08——完整 bundle
   同时解决了均值与稳定性。

## 4. 对 Limitations §9 的影响

§9 当前声明（EXP56 后版本）"no subset suffices; the insertion gate is necessary
there"仍然准确，且现在有完整阶梯支撑。可选进一步加强（写成"…and no single or
pairwise subset approaches it; the three switches interact strongly on this regime"），
但当前措辞已够，无需改动。

## 5. Caveats

1. 单序列（crowd2）；3 seed 描述性；
2. 本臂 sd=2.85 为全阶梯最大，逐 seed 读数 8.73/5.16/3.09 分化剧烈——
   mask_insertion 单独开启时 map 动态残余与 insertion gating 的耦合不稳定；
3. 组件阶梯跨 EXP53/54/56/57 四个 campaign，跨 campaign 漂移纪律（~30%）适用；
   但 Combined 与 P11 锚同 campaign（EXP53），阶梯两端锚定可靠。
