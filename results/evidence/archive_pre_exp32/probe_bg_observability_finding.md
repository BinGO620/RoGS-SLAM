# Direction B 可行性 probe — occluded 背景时域补洞（2060 离线, 零训练, 2026-08-09）

> exp-v3-12。脚本 = `scripts/probe_bg_observability.py`（mv_no_box 可观测性）+ `scripts/probe_background_self_fill.py`（mv_no_box 地图自补）
> + `scripts/probe_bg_observability_balloon.py`（balloon 版）。
> 序列 = mv_no_box（moving non-obstructing box, P-B 的 mask-free 干净语境）+ balloon（人+气球, 混合 mover）。
> 目的：判断「动态物移开后, 背景洞是否**可恢复**而非必须 inpainting 幻觉」——这决定
> temporal background completion（"背景后来被确认 → 补/回填"）是否 well-posed。

## ⚠ 一句话摘要（balloon 版结果直接改判路线）

**mv_no_box 上 bundle 已自补洞（不是 needed fix）；balloon 上被挡背景可恢复性高（W=20 73% 露出），
但地图自补是否成立仍需看 render 深度。方向 B 的剩值域在 balloon（busy 背景）而非 mv_no_box。**
（完整 mv_no_box 读法见下；balloon 分节见末尾追加。）

## Part 1：被遮挡背景在序列其他帧的可观测性（probe_bg_observability.py）

对每个"盒在场"帧（GTMC cov>0.03，n=94 锚点取前 80），在其遮罩区内，检查滑窗内**其他帧**
同一像素深度 > box_depth*1.3（露出背后远墙）的比例：

| 窗 ±W | 平均暴露 | 中位 | p25 | p75 | max |
|---|---|---|---|---|---|
| W=5 | 0.295 | 0.239 | 0.107 | 0.485 | 0.862 |
| W=10 | 0.386 | 0.344 | 0.159 | 0.615 | 0.925 |
| W=20 | 0.473 | 0.435 | 0.247 | 0.776 | 0.937 |

**读数**：被遮挡的背景在 ±10 帧内平均有 ~39% 会露出、±20 帧 ~47%。即**相当一部分 occluded
背景在邻近帧就重新可见 → 不是必须 inpainting，是可从真实观测 recover**。这支持 temporal
completion 的可行性方向。

**caveat（必须自报）**：这是**像素级 2D 代理**（深度超过 box_depth 即"露出"），没做 3D
unprojection / 世界坐标对应 / 遮挡一致性检验——"同 2D 像素露出"不完全等于"同 3D 背景点被
重建出来"。严格的可恢复性需要：box 移走后，把该 3D 背景点重新投影并验证它就是同一背景。
这是下一步要补强的部分，当前是**方向性**证据。

## Part 2：地图当前是否已自补洞（probe_background_self_fill.py）

对 maskoff run（mv_no_box seed1，mask-free bundle）final PLY，在其 85 个"盒在场"帧渲染，
看盒遮罩区的渲染：

| 量 | 值 | 读法 |
|---|---|---|
| render_op @ mask | **0.989**（frac>0.5 = 1.000） | **不是洞**（op≈1，不是空洞/雾） |
| render_dep @ mask med | **2.43 m** | ≈ 墙 |
| full-render 深度 med | **2.52 m** | 周围墙参照 |
| mask-render 深度 ~ 墙？ | **YES**（差 0.1m） | **背景已被重建/露出** |

**读数**：mv_no_box 的 mask-free bundle 在动态区**不是留洞**——盒被干净移除、背后墙已被
重建（render 深度 ≈ 墙 2.4-2.5m，"空洞"在 op 和深度上都不存在）。这与
`probe_hole_ghost_finding.md` 的修正一致（combined/maskoff 干净露出墙，非 foggy hole），
现在在**纯 mask-free（maskoff）臂**上也得到复现。

⇒ **地图自己已经把被遮挡的墙补上了**（因为盒反复移动、墙在不同帧被观察到，bundle 时域
一致性 + prune lifecycle 在下一次出现时把墙重建出来）。

## 判决（方向 B 可行性，诚实）

1. **可行性与价值需各自表述**：
   - **可恢复性成立（无分割依赖）**：被挡背景 ±10-20 帧内 39-47% 露出，可 recover 非幻觉。
   - **但"地图自补洞"已由 mask-free bundle 在 mv_no_box 上做到了**（op 0.99、深度=墙）。
     ⇒ **在这一场景，temporal background-completion 不是 needed fix，是 already-solved**。
2. **方向 B 的真正剩值域** = 地图**补不了**的洞。上文 `probe_hole_ghost` 显示 balloon（人+气球,
   busy 背景、远动态）即使 combined 也在远区留 foggy 洞；mv_no_box 干净。⇒ 方向 B 的
   "补洞"动机在**混合 mover / 远动态 / busy 背景**（balloon 类），不在 mv_no_box。
3. **结论（对路线）**：方向 B 不是"我们的 bundle 有个洞要补"，而是"**bundle 干净移除效果好
   到在低纹理场景已自补**"。真正的 future 洞 = balloon 远动态区。若方向 B 要成方法，须先
   在 balloon（而非 mv_no_box）量化洞的大小 + 验证"该背景是否在序列其他帧可观测"
   （balloon busy 背景可能遮蔽既有背景）。**下一步 = 在 balloon 上做同样的两个 probe**，
   看它是否真的有需要补的洞、且洞可 recover。

## 落盘
- 本文件 = 方向 B 可行性 probe 判决（2060 离线）。
- 脚本 = `scripts/probe_bg_observability.py` + `scripts/probe_background_self_fill.py` + `scripts/probe_bg_observability_balloon.py`。
- run = P6 maskoff mv_no_box seed1 + maskoff balloon seed1（`results/runs/P6/P6-MASKOFF-3SEED/`）。

---

## 🔙 追加（balloon 版 probe——把方向 B 收窄到真正值的域）

> 脚本 `scripts/probe_bg_observability_balloon.py`。maskoff balloon seed1 final PLY + GT depth。

### Part A：balloon 地图自补（mask-free bundle final PLY，盒/人遮罩区）

> **⚠ 尺度修正（2026-08-09 深挖，`probe_bg_3d_recovery.py` / depth-distribution）**：
> **balloon 场景本身是远距室内（GT 深度 8–30m 占 94%），不是 2.4–2.9m 墙**。之前的"render_dep
> ≈ 墙 2.4-2.9m"是参照错标——那 2.4-2.9m 并不是场景背景，是**地图里的近表面**。真实读数：

| 量 | 值 | 读法 |
|---|---|---|
| GT 场景深度分布 | 8–30m 占 0.942 | 背景是**远**室内（8-30m） |
| render_op @ mask | **0.981**（frac>0.5 = 1.000） | **不是透明度暗洞** |
| render_dep @ mask med | **2.65–2.70 m** | 近表面，**非真实背景** |
| non-mask 渲染深度 med | **3.08–3.09 m**，frac<3m=0.43 | 地图整体被重建在近处（≤3m），**< 真实 8-30m** |
| 全图渲染 frac>5m | **0.000** | 地图**完全没重建出真实远背景** |

⇨ **balloon 的真实洞态（比 mv_no_box 严重得多）**：mask-free bundle 的 final PLY**把整个场景压到
~3m 的近表面**，而真正的 8-30m 远背景（含气球背后的区域）**完全没有被重建出来**（渲染>5m = 0）。
这是**整体欠重建/洞**，不是精确的"近墙冒进填气球位"——地图根本没有那条远背景，因为它超出相机
/深度下采样能在有界预算内灌进去的尺度。**recoverability ≠ reconstructability**（见下）。

**为何 mv 无洞而 balloon 有洞**：mv_no_box 是近场景（墙 2.4m 在深度相机工作距离内，被反复观测）；
balloon 是 8-30m 远场景，深度相机在此尺度重构吃力、且 balloon 是混合序列训练更涣散 ⇒ 远背景
根本没进地图。这是**map-capacity/尺度问题 + 动态混淆**的结果，不单是"动态没移除干不干净"。

### Part B：balloon occluded 背景可恢复性（187 个 present 锚点）

| 窗 ±W | 平均暴露 | 中位 | p25 | p75 | max |
|---|---|---|---|---|---|
| W=5 | 0.420 | 0.441 | 0.376 | 0.473 | 0.935 |
| W=10 | 0.567 | 0.597 | 0.520 | 0.629 | 0.972 |
| W=20 | **0.733** | 0.733 | 0.578 | 0.866 | 0.999 |

⇨ **balloon 被挡背景的可恢复性比 mv_no_box 更高**（W=10 57% vs 39%；W=20 73% vs 47%）——
因为气球是**远物**，背后暴露的是大面积静止背景，相邻帧相机一移就露出。即在气球上，被移除
动态背后有**充足的真实观测可用来补洞**。

### balloon 版判决（方向 B 真正的剩值域）

1. **mv_no_box（低纹理、近物、墙清）**：bundle 已自补，无洞可补 → **方向 B 在此场景无值**。
2. **balloon（混合 mover、远动态、busy 背景）**：确实有"气球被移除后 mask 区被近墙替换而非
   精确重建远背景"的**真实洞/内容替换问题**，且该背景 **±10 帧 57%、±20 帧 73% 可 recover**
   —— **这是方向 B 的 well-posed 靶子**：堵在"背景在该处先观测后再出现 → 回填/精修该处
   高斯到真背景"，替代现在的"近墙冒进 + opaque"。
3. **方法形态（尚未设计，只定靶）**：不是 inpainting 幻觉，而是**时间反向对齐的回填**
   —— 当遮挡物移开后，该 3D 位置出现真实背景观测时，更新/重估该处的高斯（当前是 opacity
   满、深度=近墙的状态，即"被污染的静态"）。这正好接住 reliability/kframe 的信号：
   动态像素降权不入图，但当它变成稳态静态观测时（背景后来被确认），允许地图在这里补/生长。
   **与方向 A（anti-ghost/clean-removal）互补，且语义上是"防洞的正确主动机制"。**

### ⚠ 尺度修正后的方向 B 判决（3D recoverability probe，`probe_bg_3d_recovery.py`）

**可恢复性（recoverability）很高（2D 像素 ±20 帧 73% 露出），但可重建性（reconstructability）
= 0**：
- **静态背景 3D 点对照（gauge 1）**：非遮挡远背景点，在后续帧地图有内容 = **600/600 (1.000)**，
  但渲染深度 vs 真实背景深度匹配 = **1/600 (0.002)**。
- **被遮挡背景 3D 点（gauge 2）**：地图有内容 = 900/900 (1.000)，深度匹配 = 4/900 (0.004)。
- **根因**：地图（mask-free bundle final PLY）把**整个场景压到 ~3m 近表面**，真实 8-30m 背景
  从未被重建（渲染>5m 恒 0）。所以"那张 occluded 背景点在后续帧有无内容"的答案是"有近表面冒进填充"，
  **但内容是错的深度**（≈3m 而非 8-30m）。

**⇒ 方向 B 的关键语义转向**：
1. **这不是一个"遮挡 → 背景被误删 → 需要回填到真背景"的干净问题** —— 地图在**所有** 8-30m 远背景
   （遮挡与不遮挡都一样）都欠重建，**动态遮挡只是其中一斑**。
2. **recoverability（±20 帧 73% 有真实观测可看）** 说明**观测是够的**——那张背景确实在其他帧可见，
   是相机 + 深度在此远尺度上没把它灌进地图（map-capacity 瓶颈），**不是"观测缺失"**。
3. **因此方向 B 的纠偏落在"远尺度重建"而非"动态回填"**：当前地图压到 ~3m，责任在 densify/阈值
   （远点没被克隆/没进图），不在"动态像素是否被降权"。把方向 B 写成"occluded 背景补洞"会**误导
   审稿人去查为什么远背景全程没被建**而不是动态。
4. **对 headline 的诚实影响**：mask-free bundle 的 maskoff 在 balloon 上 ATE 12cm、地图压到近表，
   **这不是"补洞"能救的**——是深层重建距/预算问题。方向 B 若要做，靶得是**远背景欠重建的修复
   （超出动态的通用问题）**，recoverability 不构成"动态补洞"的充分性。

**建议**：方向 B 从"occluded 背景时域补洞"**重新定位为"动态 + 远距欠重建的联合修复"**，或
**收窄到 mv_no_box 类近场景**（那里 bundle 已自补、无洞）。balloon 的洞是远尺度重建问题，用
动态补洞叙事会在这个 probe 下被证伪。**这是 2060 离线验证判明的诚实负结果**（比写一个会被
3D-recovery 反打的补洞方法强）。

### 方向 B 下一步（基于尺度修正）

- 若坚持方向 B：改成**远尺度重建修复**（提高 densify 远端密度 / 背景观测加权），那与"动态"解绑，
  更像通用 mapping 增强，框架定位需重审。
- 若收窄：方向 B 冻结为负结果 + 观察（balloon 远背景欠重建是 map-capacity，非补洞），方向 A
  已是干净头条（mask-free bundle 在近/低纹理场景压 ATE），不再为 B 写方法。
- 设计新核码（per-Gaussian background-return）**仍须按硬停条件④先呈用户**，但当前证据表明该
  机制在 balloon 会"回填了个错误的近表面"，不值得落。

## 落盘（补充尺度修正后）
- 3D recoverability probe：`scripts/probe_bg_3d_recovery.py`（静态对照 gauge1 + 遮挡 gauge2）。
- 场景深度分布：`/tmp` 临时脚本（balloon GT 8-30m 占 94%）；可复现于 `scripts/`（未固化）。

### 方向 B 下一步（若继续）

- 把 Part A 的 mask-region render 深度分布按**气球 vs 人**分开（气球在远、人是近）——确认
  洞/内容替换主要在远气球区。
- 做**真正 3D 可恢复性**：用 `trj_full_final.json` 把被挡 3D 背景点 unproject，验证 box/气球
  移走后该点被重建且是对应背景。当前仍是 2D 像素代理。
- 若两者都成立 → 设计最小实验（gate 准入 on "背景后来被确认"）→ 预注册 → 需新增核码逻辑
  （per-Gaussian background-return 状态）——**按硬停条件④，设计图须先呈用户，不自行落代码**。
