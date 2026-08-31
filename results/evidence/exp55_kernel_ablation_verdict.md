# EXP55 判决 — RobustTracking kernel 消融（Huber vs Cauchy vs GM）

> 执行读数与判决，判据冻结见 `exp55_kernel_ablation_prereg.md`。
> 12/12 run `status=OK`、`rc=0`；E0 双重硬门全过（resolved config.yml 中
> cauchy 臂 kernel=cauchy、gm 臂 kernel=gm，各 6/6）。
> 运行于 jiangwenheng 双 RTX 3090（GPU0=cauchy 队列、GPU1=gm 队列）。
> 墙钟 23:29–01:42（约 2.2h，balloon ~20 min/run、pt2 ~25–45 min/run）。

**勘误备注**：初版本文件于 2026-08-29 会话内直接定稿，无转录事故
（EXP54 教训后所有数字经 `scripts/build_paper_tables.py` 通路交叉核对）。

## 1. 正式矩阵

| 序列 | Kernel | seed0 | seed1 | seed2 | mean (cm) | sd | Δ vs Huber | 地板 | 判决 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| balloon | **huber（锚）** | — | — | — | **3.06** | 0.14 | — | — | — |
| balloon | cauchy | 3.5014 | 2.9430 | 3.2278 | **3.22** | 0.28 | +0.16 | 0.43 | INDISTINGUISHABLE |
| balloon | gm | 3.4388 | 3.6361 | 3.4904 | **3.52** | 0.10 | +0.46 | 0.43 | **WORSE**（边界，0.46 ≈ 0.43） |
| pt2 | **huber（锚）** | — | — | — | **10.44** | 0.84 | — | — | — |
| pt2 | cauchy | 12.2097 | 11.9592 | 12.5838 | **12.25** | 0.31 | +1.81 | 0.74 | **WORSE** |
| pt2 | gm | 13.9203 | 12.0985 | 12.8757 | **12.96** | 0.91 | +2.52 | 0.78 | **WORSE** |

## 2. 判决

**分支落点：非 INDISTINGUISHABLE，也非单侧 BETTER——Huber 是三 kernel 中最优或并列最优。**

1. **balloon**：cauchy 与 huber 不可区分（+0.16 < 0.43 地板）；gm 位于边界
   （+0.46 ≈ 0.43），跨过地板但幅度小于该序列的 seed 离散度（huber 锚自身 sd=0.14）。
2. **pt2**：两个替代 kernel 都显著 worse——cauchy +1.81、gm +2.52，远超地板（0.74/0.78）。
   这不是噪声：两 kernel 6/6 seed 的均值方向一致，且 cauchy 的 sd（0.31）远小于
   差值本身。

**结论**：`kernel: huber` 不是任意选择——在 pt2（高动态 person 序列）上 Huber 的
恒定影响函数（大残差线性降权而非平方降权）显著优于 Cauchy/GM 的红降曲线。
§3.3 的回答是：**Huber 是经 2 序列消融验证的最优 kernel；Cauchy 在 balloon 上
不可区分但在 pt2 退化；GM 在两序列上均不优于 Huber。**

## 3. Caveats（引用时同写）

1. 消融仅 2 序列（Δ_R 最大的 balloon 与高动态 pt2），不外推其余 16 序列；
2. δ 固定 0.1（两通道），kernel × δ 交互未测；
3. 3 seed 描述性对比，无显著性检验；Huber 锚跨 campaign（~30% 漂移纪律，
   判读以地板内/外为准）；
4. balloon gm 的 +0.46 在地板边界（0.43），不应写成显著 worse。

## 4. 论文写法建议

§3.3 加一句：

> "A two-sequence kernel ablation (EXP55) confirms the choice: Cauchy is
> indistinguishable from Huber on the object-only sequence but degrades by
> 1.8 cm on the high-dynamic one, and Geman–McClure is never better (Sec. S)."

数据表（Table 5 或并入 kernel 消融小节）：
`results/runs/EXP55/kernel_ablation/` 12-run 矩阵由 `build_paper_tables.py` 扩展导出。
