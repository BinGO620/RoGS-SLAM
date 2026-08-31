# EXP53 判决 — P11 Phase 2 扩序列 + Combined 臂对照

> 执行读数与判决，判据冻结见 `exp53_p11phase2_prereg.md`。
> 所有正式运行均在 `jiangwenheng` 双 RTX 3090 上完成；本地 cb(2060) 不纳入判决。
> 27/27 run `status=OK`、`rc=0`，无 OOM、配置错误或缺失结果。远程墙钟约 7h32min
>（02:29:57–10:01:37 CST）。

## 1. 正式矩阵

主指标：完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`（evo `-a` Horn 口径）。
逃逸定义：ATE < 5 cm。

| 序列 | 臂 | seed0 | seed1 | seed2 | mean (cm) | sample sd | 逃逸 |
|---|---|---:|---:|---:|---:|---:|---:|
| balloon | P11（EXP52 复用） | 3.0078 | 3.2647 | 3.0094 | **3.0940** | 0.1444 | 3/3 |
| balloon | Combined | 3.1113 | 3.0404 | 3.0138 | **3.0552** | 0.0504 | 3/3 |
| balloon2 | P11 | 5.6059 | 5.5637 | 5.8266 | **5.6654** | 0.1412 | 0/3 |
| balloon2 | Combined | 5.5108 | 5.4310 | 5.1764 | **5.3727** | 0.1746 | 0/3 |
| crowd2 | P11 | 7.9308 | 7.7350 | 5.0033 | **6.8897** | 1.6366 | 0/3 |
| crowd2 | Combined | 2.0671 | 2.2005 | 2.0583 | **2.1086** | 0.0797 | 3/3 |
| mv_no_box | P11 | 3.4180 | 4.0247 | 3.5150 | **3.6526** | 0.3259 | 3/3 |
| mv_no_box | Combined | 2.5598 | 2.6025 | 2.7384 | **2.6336** | 0.0933 | 3/3 |
| f2_xyz | P11 | 1.6903 | 1.5556 | 1.7014 | **1.6491** | 0.0812 | 3/3 |
| f2_xyz | Combined | 1.8745 | 1.8143 | 1.8966 | **1.8618** | 0.0426 | 3/3 |

> 说明：表中显示值按 `tracking_raw.csv` 读数四舍五入；机器读数见
> `scripts/read_exp53_p11phase2.py` 与各 run 的 `tables/tracking_raw.csv`。

## 2. 判据

### G0 — P11 锚漂移中止门：PASS

| 序列 | 当前 P11 mean | exp28 锚 mean±sd | |Δ| | 门 | 判决 |
|---|---:|---:|---:|---:|---|
| balloon2 | 5.67 | 7.01±0.56 | 1.34 | 2.00 | PASS |
| crowd2 | 6.89 | 7.38±0.60 | 0.49 | 2.00 | PASS |
| mv_no_box | 3.65 | 3.64±0.10 | 0.01 | 2.00 | PASS |
| f2_xyz | 1.65 | 1.66±0.04 | 0.01 | 2.00 | PASS |

P11 当前 HEAD 结果没有触发代码/数据漂移异常门。

### G1 — P11 泛化稳定：PASS

4 个新增序列的 P11 均满足 3/3 seed < 10 cm：

- balloon2：5.61 / 5.56 / 5.83
- crowd2：7.93 / 7.74 / 5.00
- mv_no_box：3.42 / 4.02 / 3.52
- f2_xyz：1.69 / 1.56 / 1.70

因此 P11 的**泛化稳定门通过**，但 crowd2 的 3/3 逃逸门(<5cm)未通过；
该序列表现为健康但偏高的 ATE，而不是崩溃。

### G2 — P11 对 Combined 非劣：逐序列

地板冻结为 `max(0.43 cm, 6% × max(P11 mean, Combined mean))`。

| 序列 | P11 mean | Combined mean | 地板 | P11−C | 读数 |
|---|---:|---:|---:|---:|---|
| balloon | 3.09 | 3.05 | 0.43 | +0.04 | P11 非劣 |
| balloon2 | 5.67 | 5.37 | 0.43 | +0.30 | P11 非劣 |
| crowd2 | 6.89 | 2.11 | 0.43 | +4.78 | **Combined 显著优** |
| mv_no_box | 3.65 | 2.63 | 0.43 | +1.02 | **Combined 显著优** |
| f2_xyz | 1.65 | 1.86 | 0.43 | −0.21 | **P11 更优** |

P11 非劣于 Combined 的序列数为 **3/5**（balloon、balloon2、f2_xyz），
不是预注册 BRANCH-1 所需的 ≥4/5。

### G3 — 结构判决：BRANCH-2

- G1 全部通过；
- Combined 超过判定地板显著优于 P11 的序列为 **2/5**：crowd2、mv_no_box；
- 因此满足预注册 BRANCH-2：**Combined 保持动态主力；P11 作为等价简化变体，
  适用域按序列报告。**

## 3. 效率与结构差异

| 序列 | 臂 | KF 数(seed0/1/2) | online FPS | Gaussians |
|---|---|---|---:|---:|
| balloon | P11（EXP52） | 21/21/20 | 0.87 | 19,861 |
| balloon | Combined | 88/88/88 | 0.77 | 38,766 |
| balloon2 | P11 | 22/23/23 | 0.80 | 29,819 |
| balloon2 | Combined | 94/94/94 | 0.80 | 37,343 |
| crowd2 | P11 | 16/15/15 | 0.93 | 16,630 |
| crowd2 | Combined | 179/179/179 | 0.90 | 52,226 |
| mv_no_box | P11 | 35/34/33 | 1.00 | 30,308 |
| mv_no_box | Combined | 156/156/156 | 1.18 | 33,070 |
| f2_xyz | P11 | 94/96/96 | 1.13 | 31,852 |
| f2_xyz | Combined | 680/680/680 | 0.97 | 48,770 |

P11 在所有序列上显著减少 KF 数：约 3–12× 稀疏化。Combined 的动态收益
并非来自更高 FPS，而来自更密集的关键帧/地图结构；P11 则以更低的结构预算
在 balloon、balloon2、f2_xyz 上达到非劣结果。

## 4. 结论的正确表述

### 4.1 原始方法没有被整体否定

EXP53 否定的是“P11 在所有 regime 都能替代 Combined”的强断言，而不是证明
Combined 完全无用：

- **balloon**：P11 与 Combined 不可分辨（3.09 vs 3.05）；
- **balloon2**：P11 与 Combined 不可分辨（5.67 vs 5.37，均无 <5cm 逃逸）；
- **f2_xyz**：P11 反而更好（1.65 vs 1.86）；
- **crowd2**：Combined 明显更好（2.11 vs 6.89，约 3.3×）；
- **mv_no_box**：Combined 明显更好（2.63 vs 3.65，约 1.4×）。

### 4.2 当前方法定位：regime split

当前最稳妥的方法结构不是单一全局冠军，而是：

> **P11 = 更简单、更稀疏的默认候选，在 balloon/balloon2/f2_xyz 类序列上足够；**
> **Combined = crowd2/mv_no_box 类复杂动态序列的增强主力。**

P11 在 4 个新增序列都通过 <10cm 健康门，说明它不是失败 baseline；
但 crowd2 与 mv_no_box 的 Combined 优势足以阻止 P11 直接替代 Combined。

## 5. 后续方向

1. 不再宣称 P11 全面替代 Combined；论文 headline 改为**分 regime 的结构结论**。
2. 下一步优先做零 GPU 分析，拆解 crowd2/mv_no_box 的 Combined 增益来自
   DynamicKeyframe 还是 ReliabilitySignal：已有 P11/Combined 两端，下一批只需
   最小 2 序列 × 2 个单变量介入 × 3 seed 的定向消融，不重跑 18-seq 全表。
3. 在完成该定向消融前，不启动论文压缩；先确认哪个组件在复杂动态 regime 真正必要。
