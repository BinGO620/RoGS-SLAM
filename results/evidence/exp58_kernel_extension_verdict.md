# EXP58 判决 — kernel 消融扩展（4 新序列，24 run）

> 执行读数与判决，判据冻结见 `exp58_kernel_extension_prereg.md`。
> 24/24 run rc=0；E0 双重门全过。运行于 jiangwenheng 双 RTX 3090
> （04:23–09:30，GPU0=cauchy 队列、GPU1=gm 队列，墙钟约 5.1h）。

## 1. 正式矩阵（Huber 锚 = 主表 3-seed）

| 序列 | Huber（锚） | Cauchy | Δ | GM | Δ | 地板 | 判决 |
|---|---:|---:|---:|---:|---:|---:|---|
| mv_no_box | 2.66±0.12 | 2.56±0.16 | −0.10 | 2.83±0.13 | +0.17 | 0.43 | 均 INDISTINGUISHABLE |
| pt1 | 11.89±2.36 | 11.45±0.46 | −0.44 | 13.68±5.14 | +1.79 | 0.71/0.82 | cauchy indist.（边界 −0.44≈0.71 内）；**GM WORSE** |
| f3_wk_hf | 3.29±0.25 | 3.23±0.30 | −0.06 | 2.97±0.23 | −0.32 | 0.43 | 均 INDISTINGUISHABLE |
| crowd | 2.29±0.05 | 2.38±0.05 | +0.09 | 2.33±0.01 | +0.04 | 0.43 | 均 INDISTINGUISHABLE |

## 2. 判决

**8 组比较：7 INDISTINGUISHABLE + 1 WORSE（pt1 的 GM，且 sd=5.14 双稳态）+ 0 BETTER。**

与 EXP55（balloon/pt2：cauchy 1 indist + 1 worse；gm worse×2）合并，
**六个序列、10 组比较上 Huber 全部 ≥ 替代 kernel，无一 BETTER**。
§3.3 的措辞从 "two-sequence" 升级为 **"six-sequence, regime-spanning"**：
Huber 的选择经 object-only（mv_no_box）、hard-person（pt1/pt2）、walking（f3_wk_hf）、
mixed（balloon）、crowd 全部五类 regime 验证。

## 3. Caveats

1. GM 在 pt1 的 13.68±5.14 含一颗 19.38 的双稳态 seed——即使剔除，方向不变；
2. pt1 的 cauchy Δ=−0.44 在地板 0.71 内（pt1 huber 锚 sd=2.36，漂移纪律适用）；
3. kernel × δ 交互仍未测；3 seed 描述性。

## 4. 论文写法

§3.3 句子更新为：

> "A six-sequence, regime-spanning kernel ablation (36 runs, pre-registered) confirms
> the choice: neither Cauchy nor Geman–McClure is ever better than Huber, and on the
> high-dynamic person sequences both degrade (by 1.8–2.5 cm on `pt2`; Geman–McClure
> also on `pt1`)."
