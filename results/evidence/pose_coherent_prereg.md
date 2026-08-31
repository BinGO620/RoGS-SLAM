# 预注册 —— 终点 C = 相干分量（coherent amplitude）：方差-偏置机制的直接测量（exp38, 2026-08-22）

> **读数前注册。** 12 个 run 已全部落盘（同 exp37），全部零 GPU。
> 本文件在 `scripts/pose_coherent_component.py` 存在之前 commit，此后不改。
>
> 前序链：`pose_trackside_prereg.md`(`364da26c`) → `pose_trackside_ate_prereg.md`(`f9fa31ea`)
> → `pose_trackside_paired_prereg.md`(`07a14ff3`) → 本文件

## 0. ⚠ 效力声明

**已看过的**：exp37 的 ENDPOINT-DECOUPLED 结论 —— shift_P = +0.0806 / shift_ATE = −1.42cm。
以及 P1b flag② 的定性判断（`coherent` 7/7 最低，`coherent_amplitude` 0.88–1.18×）。

**未看过的**：E/F 各 12 个 run 在高动态帧上的 `coherent` 和 `coherent_amplitude` 的**逐 run 数值**。
预注册之前只手算了 seed0 run0 一个点做方向确认。

⇒ 标签 = **「机制候选已知、量值未见的预先指定分析」**。
不注册方向性预言——方差-偏置候选是从 exp37 的 ENDPOINT-DECOUPLED 推演来的，
但**推演不等于预知符号**（coherent 可能不变而 amplitude 因 median RPE 上升而变大）。

## 1. 为什么这是一个新问题（exp33 判据 #10）

exp37 的两个终点（P 和 ATE）方向相反。本轮要回答的是**为什么会相反**：

```
候选机制 = 方差 vs 偏置：
  把通道①从 10/100 扩到 100/100
  → 剔除更多动态像素 → 逐帧约束更少 → 方差更大（P 变差）
  → 同时去掉动态像素对位姿的系统性拉扯 → 偏置更小（ATE 变好）
  → 噪声沿轨迹平均掉，偏置累积
```

**需要的测量**：RPE 向量在高动态帧上的**相干分量**。相干分量低 = 误差更像噪声（偏置小）；
相干幅度 = 相干 × median|RPE| = 对 ATE 的漂移贡献。若 F 的相干幅度更小，方差-偏置机制成立。

## 2. 装置与主统计量

### 2.1 δ 向量的选择

P1b 的 δ 是**逐帧位姿更新偏差**（离线 GN 步在真位姿处的 bias）。
exp37 的 E/F 臂我们只有 `trj_full_final.json` 里的全轨迹。

**用 RPE 向量**（相邻帧相对位姿误差），理由：
1. RPE 直接量逐帧跟踪质量，与 P 的定义对口；
2. per-frame |δ|（绝对位姿误差）的相干≈0.93（轨迹系统漂移主导），E/F 不可分；
3. RPE 向量的相干≈0.19–0.25（逐帧 jitter 为主），E/F 可分且机制对口。

### 2.2 定义

对每对帧 (i, i+1)：

```
rpe_i = (T_est_i)^{-1} T_est_{i+1} · [(T_gt_i)^{-1} T_gt_{i+1}]^{-1} 的平移部分    单位 cm
```

高/低动态分层：**运动匹配**（GT 步长四分位分箱、箱内再按动态面积中位数切），
与 P 完全一致（`split_motion_matched`）。

```
coherent      = ‖mean(rpe_{hi})‖ / mean(‖rpe_{hi}‖)          无量纲，[0, 1]
median_rpe    = median(‖rpe_{hi}‖)                            单位 cm
coherent_amp  = coherent × median_rpe                          单位 cm
```

- `coherent_amp` 是对**漂移贡献**的直接量度（P1b flag② 的"更贴近 ATE"版本）；
- `coherent` 单独报出，因为它量的是方向一致性（机制诊断）。

### 2.3 比较

臂对 = **F vs E**（唯一的单变量对），序列 = **balloon**。

```
格均值      Ā(arm, s) = mean over that cell's runs of coherent_amp    (r = 2)
配对位移    Δ_s       = Ā(F, s) − Ā(E, s)
主统计量    shift     = mean over s in {0,1,2} of Δ_s
```

## 3. 第 0 步 = 可达域（注册在判决之前，exp32 判据 #4）

**地板从已有数据量**：E 和 F 各自的 within-config 复跑（同 config 同 seed 跑两次）
对 `coherent_amp` 的 |Δ| 取 max = `floor_CA`。

```
floor_CA ≤ 0.0831 ?   （exp37 的 REACH_FLOOR = 最小有意义 shift）
```

- **不过 ⇒ UNREACHABLE**：报 `floor_CA` 和所需 r，宣布路线关闭或值得继续。
- **过 ⇒ 进第 1 步。**

> 选 0.0831 而非 0.55（ATE 的 floor）：coherent_amp 的单位是 cm，量级与 P（~0.1–0.5）相当，
> 不与 ATE（~8–10）可比。用 P 的 floor 更合理。

## 4. 判决规则

| 落点 | 标签 |
|---|---|
| `\|shift\| ≤ floor_CA`（且可达） | **COHERENT-INDISTINGUISHABLE** → 方差-偏置机制**未被**本终点支持 |
| `shift < −floor_CA` | **COHERENT-BIASED** → F 的相干幅度更低 ⇒ 偏置更小 ⇒ **方差-偏置机制成立** |
| `shift > +floor_CA` | **COHERENT-WORSE** → F 的相干幅度更高 ⇒ 机制候选被本终点**否决** |

**附加描述性（不作门）**：相干分量 `coherent` 本身的 E/F 差异，以及 E/F 各自的
`median_rpe(hi)` 差异（P 变差的量级 = RPE median 上升 vs 方差-偏置 = coherent 下降）。

## 5. 机制-终点三角

本轮完成后，三个位姿终点形成三角：

```
          P (动态惩罚)     → shift +0.0806 (1.22×) 变差
          ↓
     coherent_amp (相干幅度) → shift ???          ？
          ↓
          ATE (累积漂移)     → shift −1.42cm (4.0×) 变好
```

- **若 coherent_amp 同向 ATE（F 更小）**：P → coherent_amp → ATE 形成因果链，
  方差-偏置机制从"候选"升级为"有测量支撑的机制"。
- **若 coherent_amp 同向 P（F 更大或不变）**：P 和 ATE 的解耦不能用方差-偏置解释，
  需要找别的机制（如地图侧的 BA 观测聚合）。

## 6. 装置门

沿用 exp37 的装置门（K-1 到 K-4），本轮无新 run ⇒ 不需重新验装置。
追加一个**机制自检**：

| 门 | 内容 | 判据 |
|---|---|---|
| **M-1** | E 的 median_rpe(hi) 应与 P(E) 同量级 | median_rpe(hi) 在 P(E) 的 2× 以内（量纲一致：cm） |
| **M-2** | 高/低动态的 RPE 差应与 P 同号 | median_rpe(hi) > median_rpe(lo)（与 P 的定义一致） |

## 7. 本轮不做什么

- 不跑新 run（12 个全部落盘）；
- 不改 exp37 已 commit 的任何数字或标签；
- 不改 exp36 的 trackside ATE 判决；
- 不扩序列；
- 不注册方向性规则（§0）；
- 若 UNREACHABLE，**不放松 0.0831**。
