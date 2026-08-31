# EXP56 判决 — crowd2 归因补全：P11+DynKF+Reliability 双变量臂

> 执行读数与判决，判据冻结见 `exp56_crowd2_attribution_prereg.md`。
> 6/12→6/6 run：seed0/1 首轮完成（ATE 2.9982/5.6079），E0 门因 YAML bool 大小写
> 误报（"False" vs "false"）终止；修 gate 后 seed2 补跑完成（03:00:46 rc=0），
> seed0/1 数据有效保留（SKIP 机制）。全部 3 seed 的 resolved config.yml 确认
> DynKF=true, Reliability=true, mask_insertion=false。
> 运行于 jiangwenheng 双 RTX 3090。

## 1. 正式读数

| 臂 | seed0 | seed1 | seed2 | mean (cm) | sd |
|---|---:|---:|---:|---:|---:|
| P11+DynKF+Reliability | 2.9982 | 5.6079 | 5.0548 | **4.5536** | 1.3751 |

## 2. 判决（按预注册 §5 三分支）

地板 = max(0.43, 0.06 × max(4.5536, 2.1086)) = **0.43 cm**。
Δ = 4.5536 − 2.1086 = **+2.4450**，远超地板。

**分支落点：INSERTION-NEEDED——`mask_insertion` 是 crowd2 上 Combined 优势的必要成分。**
DynKF+Reliability 的双变量组合仍不足以恢复 Combined（4.55 vs 2.11），bundle 归因保留。

## 3. crowd2 全臂阶梯（EXP53/54/56 汇总）

| 臂 | 组件 | mean (cm) | sd | 距 Combined |
|---|---|---:|---:|---:|
| P11（simpler） | R+D+M_map | 6.89 | 1.64 | +4.78 |
| P11+DynKF | K+R+D+M_map | 5.16 | 2.25 | +3.05 |
| P11+Reliability | R+L+D+M_map | 6.00 | 2.11 | +3.89 |
| **P11+DynKF+Rel（本实验）** | K+R+L+D+M_map | **4.55** | 1.38 | **+2.45** |
| Combined（full） | K+R+L+D+M_map+M_ins | **2.11** | 0.08 | — |

读法：加 DynKF 略好（5.16→4.55 加 L 后），加 Reliability 反而更差（5.16→6.00），
双变量 4.55 介于其间但仍远不达标——**组件阶梯单调性不成立**（crowd2 上组件组合
非简单叠加），mask_insertion 是不可替代的最后一块。

## 4. 论文写法建议

Limitations §9 从"crowd-regime 增益归因于 bundle，不归因于组件"升级为：

> "…the remaining switch — masking the keyframe-insertion gate — was tested in
> EXP56 and proved necessary: the double-variable arm (coverage + reliability)
> still trails the full configuration by 2.45 cm on `crowd2`. The crowd-regime
> advantage is therefore attributable to the full bundle including insertion
> gating, not to any subset of components."

§5.3 Table 3 可扩展加一行双变量臂（可选，若加则crowd2 行变5列）。

## 5. Caveats

1. 单序列（crowd2）；不外推其他 crowd 系序列（crowd 未测）；
2. 3 seed 描述性；双变量臂 sd=1.38 大，但全部 seed 最低值 3.00 仍超地板（3.00−2.11=0.89>0.43），
   方向不依赖均值；
3. mask_insertion 的单独贡献未测（需 P11+mask_insertion 臂，优先级低于本判决）。
