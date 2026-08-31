# exp44 Replica 锚点结果 —— 全部完成（2026-08-24 07:51）

## 结果总表

| 臂 | 序列 | ATE (cm) | KF-ATE | PSNR | SSIM | LPIPS | DepthL1 (cm) |
|---|---|---:|---:|---:|---:|---:|---:|
| **vanilla** | office0 | **0.382** | 0.359 | 43.00 | 0.983 | 0.044 | 4.51 |
| **combined** | office0 | **0.917** | 0.673 | 40.32 | 0.970 | 0.095 | 8.60 |
| **vanilla** | room0 | **0.499** | 0.531 | 35.00 | 0.952 | 0.082 | 6.06 |
| **combined** | room0 | **0.328** | 0.319 | 35.60 | 0.951 | 0.103 | 5.93 |

## published 参照（MonoGS 论文 Table 2, Ours sp）

| | office0 | room0 |
|---|---:|---:|
| published ATE | 0.36 | 0.33 |
| 我们 vanilla | 0.382 (+6%) | 0.499 (+51%) |

## 判读

### vanilla 锚点
- office0: 0.382 vs published 0.36 → **差 0.02 cm（+6%）**，接近可复现。
- room0: 0.499 vs published 0.33 → **差 0.17 cm（+51%）**，超出 published 自身浮动范围。
  **ANCHOR-MARGINAL**：需查 fork 差异（edge_threshold / single_thread / 末段 refinement 参数）。
  **后续补充（seed-0 回溯）**：seed0 实际跑了两次，两次 room0 为 0.263 / 0.499——**双稳态**，非连续偏移。

### combined vs vanilla（Replica 全静态）
- **office0: combined 0.917 比 vanilla 0.382 差 2.4×**——我们的内核在静态场景上退化，与 FULLKERN "静态 6/6 变差"记录一致。
- **room0: combined 0.328 比 vanilla 0.499 优 33%**——方向相反，可能 room0 的纹理/几何更简单，mask 反而帮了忙。
- **结论矛盾**：两场景方向不一致，n=1 不可判，需补 seed。

### 渲染
- PSNR: vanilla office0 43.0 > combined 40.3（−2.7 dB）；room0 35.0 ≈ 35.6（持平）
- DepthL1: vanilla office0 4.51 << combined 8.60（1.9×）；room0 6.06 ≈ 5.93（持平）
- office0 的几何退化（DepthL1 1.9×）与 ATE 退化同向；room0 没有。

## 自限与下一步

- 单 seed = screening，不进判决。需 seed1/2 确认方向是否稳。
- room0 的 vanilla 51% 偏离需先查根因（可能 `single_thread` 改了异步映射行为，见 exp26 的教训）。
- combined 在静态场景上的退化已预注册为"第三种结局"（§5），如实报 limitation。
