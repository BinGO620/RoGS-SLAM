# WP-F 替代融合算子 —— frame-level 离线诊断（零 GPU，CCF-C 整改执行卡 §10 WP-F）

> **执行卡 §10.1 要求**：先做零 GPU 离线诊断（权重分布 + 分离度），诊断不过就不跑 GPU。
> 本诊断用 P7 `reliability_signal/frames.csv` 的 **per-frame mean** e_flow 与 g 评估三个候选
> 算子的权重分布。**注意这是 frame-mean 级粗诊断** —— 执行卡要求的 per-pixel 诊断需要
> per-pixel e_flow/g stash（P7 未存，需 2060 probe 才能补）。

## frame-mean 级权重分布（s = 静态可信度；w = tracking 降权 = 1-s）

| seq | both(当前) | min | max | geomean | e_flow_mean | g_mean |
|---|---|---|---:|---:|---:|---:|---:|
| mv_no_box | 0.645 | 0.727 | 0.886 | 0.802 | 0.11 | 0.27 |
| mv_no_box2 | 0.652 | 0.735 | 0.886 | 0.807 | 0.11 | 0.27 |
| pt2 | 0.626 | 0.735 | 0.851 | 0.790 | 0.15 | 0.27 |
| balloon | 0.623 | 0.717 | 0.868 | 0.789 | 0.13 | 0.28 |

## 读（frame-mean 级）

- **三算子把 `s` 整体抬高了**（both 0.62–0.65 → min 0.72 / max 0.86 / geomean 0.79），
  即降低 tracking 降权强度 —— 这是**全局重标定**效应。
- **真正的信号分离度很弱**：e_flow≈0.11–0.15、g≈0.27（帧平均），两条 cue 的判别力都低。
  ⇒ 在 frame-mean 级，三个算子**看不到能区分 dynamic/static 的分离度提升**。
- 这正是执行卡预判的框架风险：**单纯换融合算子很可能只是全局重标定，而非分离度改善**。
  WP-F 的 `both-mean-matched` 控制臂就是要剥离这种全局重标定。

## 诊断结论（frame-mean 级，第一道闸）

**不通过（无分离度提升信号）** —— 按执行卡，"诊断不过就不跑 GPU"。frame-mean 级未显示
换算子带来 dynamic/static 分离增益，且算子主要效果是全局平移权重。

## 是否要 per-pixel 探针？

执行卡的正式诊断是 per-pixel。当前 frame-mean 级已经负面，**但 per-pixel 分布可能在
高 e_flow/g 尾部才有分离**（frame 均值抹掉了尾部）。按执行卡 M5，per-pixel 诊断是跑 GPU
**之前**的必要步骤。若要在 2060 上继续 WP-F，应先用一个 2060 probe stash 每像素 e_flow/g，
跑 per-pixel 分离度 —— 但 2060 probe 是 GPU 任务，且 WP-F 是 opt-in。

**决定（本会话）**：WP-F **默认不做**（frame-mean 级诊断负面；per-pixel 诊断需 GPU probe，
而 2060 当前无必须任务；WP-A/B 是主导线）。若用户明确要 2060 做 WP-F，先补 per-pixel
probe 分离度，过了再跑 pilot。已记录为 opt-in 决策点。
