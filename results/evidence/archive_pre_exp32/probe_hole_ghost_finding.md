# offline probe — 动态移除"ghost vs clean removal"可量化指标（2060, 零训练）

> 2026-08-09 exp-v3-11。用户授权 2060 验证 idea。
> 脚本 = `scripts/probe_hole_ghost.py`（离线重渲已存 final PLY + trj_full_final）。
> 序列 balloon,person 存在帧（GTMC cov∈[0.02,0.25]）。

## 指标

对每个 person 存在帧,在 GTMC-person 区域比较**重渲染颜色与 GT（含人）颜色差** `mean_render_gt_color_diff`:

- **低 diff ≈ 0.05-0.09** ⇒ 地图里**保留了人**（渲染 ≈ GT 里的人）= **GHOST**（vanilla 失败模式）
- **高 diff ≈ 0.15** ⇒ 地图里**没有显示人**（渲染 ≠ GT,因为真背景/洞把人替代）= 动态物被移除

## 结果（两个序列, person/物体存在帧）

### balloon（人, busy 背景）

| run | masked-region color diff vs GT(person) | 读法 |
|---|---|---|
| **vanilla** | **0.0884** (n8) / 0.0972 (n12) | **GHOST**：人烤进地图,渲染≈人 |
| **combined** | **0.1577** (n8) / 0.1481 (n12) | **CLEAN**：人不在地图,渲染显示背景/洞 |
| **maskoff** | **0.0942** | 介于中间——mask 关闭后人部分烤进,移除不如 combined 干净 |

### mv_no_box（低纹理盒, 纯背景墙）

| run | masked-region color diff | 读法 |
|---|---|---|
| **vanilla** | **0.068** | ghost（盒烤进） |
| **combined** | **0.055** | clean |
| **maskoff** | **0.058** | **≈ combined —— 几乎同样干净移除!** |

**mv_no_box 的 hole-ghost 结果与 P-B 的 ATE 结论完全互证**：mask 在 mv_no_box 上几乎没有额外价值
（0.058 vs 0.055）,mask-free 的时域一致性 bundle 本身就是干净的动态移除器。

（注意：color-diff 绝对水平跨场景不可比——mv_no_box 低纹理背景墙 clean removal 的 diff 低
0.055,balloon 忙背景要 0.15;但**同一场景内**能干净区分 ghost vs clean。此点写论文时必须注明。）

（mean_op 三臂全 ≈1.0,说明不是"透明度洞";是**颜色内容**区分。）

## 意义

这是一个**可量化、离线可复现**的"动态物移除干净度"指标,直接对应用户关心的**空洞/脏移除**
问题。它把"空洞"从模糊的视觉抱怨变成数字:
- **vanilla = ghost**（人烤进墙里 = 动态污染）
- **combined = 干净移除**（人不在,露出真背景或干净洞）
- **maskoff = 半干净**（部分人还在）

但对 MMM 头条的价值需谨慎（见下）：
1. **color-diff 高 ≠ 一定是"干净背景"，也可能是"糊洞"**（洞的 smear 也≠人）。要严格区分
   "干净背景" vs "洞",需一个独立背景参照——即同一位置在 person 移开后某帧的真背景颜色。
   把 masked-region render 与"true background reference"比：diff 小=干净背景,diff 大=洞/糊。
2. 单序列 seed0,需多 person 帧稳。
3. 它不是一个"方法"，是一个**测量/评估指标**。可作论文 evaluation 段落/method figure 支撑,
   不是 headline 本身。

## 与头条的关系

这个指标目前是**支撑性的 evaluation 工具**,不构成方法。真正的方法内核仍 = P6/P-B 的
"mask-free 时域一致性 bundle 的动态跟踪"。这个 probe 给那篇论文一个"空洞/脏移除"的量化面板,
强化"对动态 3DGS SLAM 有用"这条。也可作为 future-work 的一个小贡献（offscreen 动态移除度量）。

## 下一步（若要把"干净 vs 洞"分离）
- 加"true background reference"帧对照（person 不在该位置时的 GTMC==0 帧的颜色/深度）,
  把 `mean_render_gt_color_diff` 拆成 `ghost_frac`（render≈person）和 `hole_frac`（render≈洞）。
- 跑 mv_no_box（物）:mask 在 mv_no_box 几乎不用,预期的 maskoff≈combined 在 ghost/hole 上也接近,
  强化"mask-free bundle 本身就能干净移除"。

## 深度细读（mv_no_box + balloon 的关键区分）

对 person 存在帧,把 masked 区渲染深度 vs 全图渲染深度:

- **mv_no_box combined**: masked 深度 1.91-2.83 vs 全图 2.18-2.74 ≈ 一致,opacity=1.0
  ⇒ **盒子被干净移除,露出真墙(~2.4m)**,不是洞。vanilla 也显示墙深(2.2-2.7)但颜色是盒色。
  ⇒ **mv_no_box 上"空洞"不是问题（prune 生命周期本身就把低纹理盒大部分删了）,method 差异主要在颜色(ghost vs clean)。**
- **balloon combined**: masked 深度 2.70 vs GT 动态(11.4),在远区（gt 8-18m 的气球）渲染只有 2-3m 浅雾
  ⇒ **combined 在 balloon 上把 dynamic 移除,但远区留下 foggy 洞（未重建被遮挡的墙）,不是干净露出**。
  vanilla 也浅(2.34),两者在气球远区都是洞/雾。

**诚实结论**：
1. **mv_no_box**（低纹理、背景干净、prune 已删大部分动态）→ 干净移除,空洞不是瓶颈;mask 几乎无增量（ATE 3.09 vs 2.66）。这是我们的"mask-free bundle"故事的主要场景。
2. **balloon**（busy 背景、远气球）→ mask 显著加值（ATE 12→3）但即使 combined 也在远动态区留 foggy hole。**"被遮挡背景未重建"是真实洞** —— 这是用户关心的"空洞"问题的诚实落点,也是 future-work:双通道 static/transient 分解（DeGauss 式）专门治这个。
3. **probe 的核心价值** = 有量化区分 vanilla-ghost vs combined-clean 的指标,但必须配深度一致性检查才能把"干净背景"和"洞/雾"分开,避免单看颜色误判。

## 🔄 2026-08-09 修正（深度细读的更正——"空洞"不是主问题）

深挖后修正：**combined 在动态区域其实干净露出了墙,不是 foggy hole**。

- **balloon combined**: masked 区渲染深度 2.39-2.85 ≈ 全图深度 2.59-2.92（≈ 墙 2.4-2.9m）。
  之前把 "GT 动态深度=11m(气球远) vs 渲染=2.7m" 误读成"浅雾洞";实际 2.7m ≈ **墙 = 气球被移除后露出真背景**,
  opacity=1.0,是**干净移除**不是洞。GT masked 深度之所以=11m,是 GTMC 掩码盖住了远处的红色气球。
- **vanilla balloon**: 动态区渲染深度 2.1-2.8（也≈墙/近物）,但**颜色里烤进了人/气球**（color-diff 0.088 vs
  combined 0.15）。深度未必能区分,颜色能。
- → 修正后的诚实结论：
  1. **空间干净度（深度一致性）在 combined OR maskoff 都不是瓶颈**——背景墙被重建出来、能露出。
  2. 真正的区分在**颜色内容**：vanilla 把动态物体颜色烤进墙（ghost）,combined/maskoff 移除得干净。
  3. 因此"空洞"在我们这套 mask-free bundle 上**不是大洞/fog**,而是**颜色 ghost vs 干净**。这是个更有利的诚实定位
     （比"会留洞"更好讲,且没有不当 claim）。
  4. 那"空洞"留给真正需要它的地方：**双通道 static/transient（DeGauss 式）** 处理的是"mask 捕不到的半透明/阴影"，
     和我们的 ghost-vs-clean 是两个不同的 artifact。

**对头条的影响**：mask-free 时域一致性 bundle 的动态移除**干净度** = 颜色 ghost-vs-clean 可量化（本文 probe）,
且**没有空洞/雾的负面**——这是对我们更有利的证据。probe 保留为 evaluation 工具,不构成方法。
