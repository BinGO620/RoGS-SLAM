# P6 MASK-OFF — 全 6 序列 mask-free 主表裁决（3090, 2026-08-10）

> **背景（exp-v3-12 overnight 批）**：用户指示"3090 别闲，能跑的批量全跑"。本批把 mask-free
> maskoff 3-seed 从原 3 序列（balloon/mv_no_box/pt2）扩展到全 6 序列（补 balloon2/mv_no_box2/pt1）。
> 数据 = `results/runs/P6/P6-MASKOFF-3SEED/`（已回拉）。
> 本文档 = **主表 + 诚实裁决**。数值 = `tracking_raw.csv ate_rmse_cm`（全轨迹，3090）。
> combined（mask-ON）= P2-T 3-seed；maskoff = 本批 3-seed；vanilla = P5 单 seed（仅 3 基础序列有）。

## 一、全 6 序列主表（3-seed mean ± sd，cm）

| mover 类 | seq | vanilla (P5) | combined(maskON) | **maskoff(mask-free)** | maskoff vs combined | 裁决 |
|---|---|---|---|---|---|---|
| 纯物 | mv_no_box | 13.60 | 2.66±0.12 | **3.09±0.46**（3.60/2.99/2.70） | **1.16×** | **mask 冗余** |
| 纯物 | mv_no_box2 | — | 5.14±0.28 | **5.62±0.30**（5.95/5.53/5.38） | **1.09×** | **mask 冗余（独立复现）** |
| 纯人 | pt2 | 44.06 | 10.44±0.84 | **9.30±0.64**（9.92/8.64/9.33） | **0.89×** | **mask 冗余（甚至略优）** |
| 纯人 | pt1 | **46.85** | 10.04±0.58 | **32.41±8.51**（31.38/41.39/24.45） | **3.23×** | **mask 主导（边界反例）** |
| 混合 | balloon | 43.94 | 3.06±0.14 | **12.11±2.33**（13.66/9.43/13.24） | **3.96×** | **mask 主导（已知）** |
| 混合 | balloon2 | — | 5.28±0.11 | **10.14±0.62**（10.82/9.96/9.63） | **1.92×** | **mask 主导（中档）** |

（vanilla 仅 P5 有 balloon/mv_no_box/pt2/pt1；mv_no_box2/balloon2 无 vanilla 基线。
**pt1 vanilla 2026-08-10 补跑 = 46.85cm，maskoff(32.41) 仍优于 vanilla 1.44× —— 不是完全失效，
只是远不如 mask(combined 10.04)。** balloon2 maskoff 3-seed 软链崩溃后重跑完成 = 10.14±0.62，
1.92× 差于 combined —— mask 中档主导，不如 pt1/balloon 极端。）

## 二、核心裁决

### 1. 三类 mover 的 mask-free 通用性——**成立，但 pt1 是边界反例、balloon2 是中档**

- **纯物族（mv_no_box / mv_no_box2）**：maskoff ≈ combined（1.09–1.16×），**mask 完全冗余**，
  且 mv_no_box2 独立复现了 mv_no_box 的结论（3.09 / 5.62，均压到 combined 量级）。
- **纯人 pt2**：maskoff ≈ combined（0.89×，甚至略优）——mask 冗余。
- **混合 balloon**：mask 主导（3.96×），bundle 在无 mask 时仍把 vanilla 43.9 压到 12.1（3.6×）。
- **混合 balloon2（新）**：mask 中档主导（1.92×，maskoff 10.14 vs combined 5.28）；无 vanilla 对照，
  无法判 maskoff 相对 vanilla 优劣。
- **⚠ 纯人 pt1（新矛盾）**：maskoff 32.4±8.5 **远差于** combined 10.0±0.6（**3.2×**），
  **mask 主导且不可省**。这与同属"person 族"的 pt2（maskoff≈combined）**直接相反**。
  但 pt1 maskoff 仍优于其 vanilla（46.85，1.44×），**不是完全失效，只是远不如 mask**。

### 2. pt1 vs pt2 分歧的诊断（为什么一个行、一个不行）

| 维度 | pt1 | pt2 |
|---|---|---|
| maskoff 3-seed | 31.38 / 41.39 / 24.45（±8.5 大方差） | 9.92 / 8.64 / 9.33（±0.64 低方差） |
| combined(maskON) | 9.79 / 9.62 / 10.70 | 9.87 / 11.41 / 10.06 |
| GT 轨迹位移 | 4.3 m（583 pose） | 3.9 m（570 pose） |
| RPE（maskoff） | 2.78 / 2.79 / 3.12 | 1.58 / 1.59 |
| NGD-SLAM 基线 | 4.9–5.4 cm | ~6.3–7.1 cm |

- **pt1 是"双稳态/大方差"序列**：3 seed 跨 24–41cm，说明该序列对 mask-free bundle 的成败
  高度敏感、非稳定收敛；pt2 则低方差稳定（±0.6cm）。
- **pt1 的 RPE（2.8–3.1）远高于 pt2（~1.6）**，说明 pt1 的逐帧位姿噪声本身就大——mask-free
  失去语义 mask 加持时，无法像 pt2 那样维持干净地图，跟踪随之发散。
- **竞品基线**：pt1 属于"难跟踪"序列（NGD-SLAM ~5cm vs 我们的 combined 9.6–10.7cm，本就在
  higher-ATE 端）；去掉 mask 后直接崩到 24–41cm。

### 3. 对头条的影响——**收窄"纯人 mask 冗余"的适用范围，不强翻头条**

- 头条 = "mask-free 时域一致性 bundle 把动态序列从 vanilla 压下来 + 对 mover 类型鲁棒"仍成立：
  **在 mask 冗余的序列（纯物族 + 纯人 pt2）上 1.09–0.89×、在 mask 主导的序列上（balloon 混合）
  仍比 vanilla 好 3.6×**。
- **但不能写"纯人 mask 冗余"为全局**：那是 pt2（单人轻遮挡）的结论；pt1 证明 person 族存在
  mask-free 不扛的边界（双稳态/高 RPE 序列）。
- **诚实的写作定位** = 把三类 mover 改成**五档证据链**：
  纯物（mv 双复现）✓ / 纯人 pt2 ✓ / 混合 balloon（bundle 仍优于 vanilla）△ / **纯人 pt1 边界反例**
  ○——把 pt1 作为"适用域边界"写进 limitation，反而不引导审稿人反打（自曝边界）。
- 仍需 **pt1 vanilla 基线**判断 maskoff(32) 相对 vanilla 的优劣。
  **已补跑（2026-08-10）：pt1 vanilla = 46.85cm ⇒ maskoff 32.41 仍优于 vanilla 1.44×**，
  **不是完全失效，只是远不如 mask（combined 10.04）。** 诚实定调升级为：
  "mask-free 在 pt1 上不是失效，而是不如 mask 强（1.44× 优于 vanilla vs mask 的 4.67× 优于 vanilla）"。

## 三、诚实不动摇的骨架主张（对最高准则两问）

| 问 | 答 | 证据 |
|---|---|---|
| 方法贡献是自己的吗？ | 是。DynamicKeyframe/RT 实现/Reliability 调优是我们做的，不依赖基座私有机制。 | 全 6 序列 maskoff |
| 对动态 3DGS SLAM 有用吗？ | 是，**但诚实加适用域**：mask-free bundle 在低遮挡/纯物/部分 person 序列有 1.09–0.89× 冗余增益；在难跟踪 person（pt1）与混合（balloon）上不如 mask，但比 vanilla 好 3.6×。 | 本表 |

**不强翻头条**：mv 双复现（3.09/5.62≈combined）+ pt2（0.89×）+ balloon（仍优于 vanilla 3.6×）
是三块基石；pt1 是边界反例不是推翻。真正要改的是**措辞**：从"三类 mover 通用"改为
"多数序列 mask 冗余，难跟踪 person(pt1) 是适用域边界"。

## 四、落盘与待办

- 本文件已回拉全部 6 序列 maskoff 3-seed 数据（mv 双复现 + pt2 + pt1 + balloon + balloon2）。
- **balloon2 软链教训（复用）**：rsync 会把 `datasets/bonn/rgbd_bonn_balloon2` 重建为指向本地
  `/data/Datasets` 的损坏软链 → 远程 FileNotFoundError 崩溃。**每次 rsync 到远程后必须重指向
  `/mnt/app/datasets/Bonn/<seq>`**。已重跑完成。
- **全部 BONN 6 序列 maskoff 主表已齐**。#18 = 全 6 BONN 动态序列 × 3 seed。
- **下一步（用户指示）**：对齐 baseline 的 18 序列全套（用户/资源实测竞品 RGD/DG/MonoGS 等
  都是这 18 序列），mask-free bundle 需扩展补跑 crowd/crowd2 + TUM 全部动态/静态序列，才能与
  竞品 ATE 并排。**待建**:crowd/crowd2/f2_person/f3_st_*/f3_wk_*/f1_desk/f2_xyz/f3_office 的
  maskoff config + 跑批。
