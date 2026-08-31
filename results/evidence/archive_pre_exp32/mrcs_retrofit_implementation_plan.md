# M2 / T2 / T3 实装执行计划与实装记录（exp31 存档，2026-08-20）

> **状态**：架构组拍板①②③ 与追加约束已全部并入。**M0 探针已执行完毕**，结果见文末 §五。
> 本次仍**未改动任何在线源码 / config**；唯一新增文件是探针脚本 `scripts/probe_mad_exclusion.py`（只读）。
> 日期：2026-08-20 | 分支 `ours-v3` @ `e2cebd5b` | 环境 `conda run -n monogs-ours`
>
> **前序文档**：
> - 《可行性尽调报告》→ `results/evidence/mrcs_retrofit_feasibility.md`
> - 逐行代码底稿 → `results/evidence/core_code_extract_2026-08-20.md`
> - M0 原始数据 → `results/evidence/m0_mad_exclusion/m0_*.json`

---

## 0. 拍板落地对照表

| 拍板 | 内容 | 本文落地位置 |
|---|---|---|
| ① `tau_floor` 由 M0 决定 | ≥95% 不加地板 / 50–95% 地板转正 / <50% 排除方案作废 | §0.1 门控 + §五 判决 |
| ② Override 持久化 | `persist=true` 为**默认且唯一实现**，删除 false 分支 | §三 T3（config 键已删 `semantic_override_persist`） |
| ③ AlphaLifecycle 范围 | 只建独立 arm，绝不并进 combined 主干；判据 arm 内闭环 | §三 T3「消融与判决」 |
| 追加约束 | 任务二是 **combined 专属增益机制**；E-flow 与 control 不显著、E-both 显著 ⇒ 符合预期，不构成判负 | §三 T2「arm 说明」（已显式写入） |
| 顺手修 | P7 空断言单独一个 commit，不与三项任务混淆 | §四 |

---

## 0.1 执行顺序与门控（★ 本次新增，按拍板① 固化）

```
┌── M0 探针（零源码改动）────────────────────────────── ✅ 已执行，见 §五
│      判决量 = both 模式下 mad_zero_frac_after < 0.5 的帧占比
│      ├─ ≥95%  → 任务二：纯 exclusion，guard 兜底
│      ├─ 50–95% → 任务二：exclusion + tau_floor（地板转正为必带主路径）
│      └─ <50%  → 任务二作废，改独立立项测纯 tau_floor
│
├── 任务一 M2（锚点只读探针）  ← 不依赖 M0，可立即开工
│      │  gate: frame 371 附近锚点量有无拐点
│      ├─ 有拐点 → M3（锚点触发，48 run）
│      └─ 无拐点 → B 判负，M3 不跑
│
├── 任务二 T2（MAD 统计域隔离） ← **进入条件 = M0 判决落在前两档**
│      │  M0 实测落在【第三档】⇒ 见 §五 判决与建议
│
└── 任务三 T3（语义 Alpha 覆盖） ← 与 M0/T2 无依赖，可与任务一并行开发
       │  独立 arm 内闭环，绝不进主干
       │  gate: carved > 0 的机制自证
```

**并行度**：任务一与任务三改动文件不重叠（`slam_frontend.py` 前端 vs `slam_backend.py`+`alpha_lifecycle.py` 后端），
可并行开发；但**不能在同一个 run 里同时评估**（任务三会改高斯数 ⇒ 改地图 ⇒ 改位姿 ⇒ 改锚点量）。

---

# 一、探索与思考总结

## 1.1 透传难点 —— 架构师点名的两个，一个不存在，一个是三层

### （a）`e_flow` 怎么拿到？—— **不需要透传**

`e_flow` 与 `flow_valid` 在 `compute_reliability_tracking_weight` 内部**已经是局部变量**，
与 `cauchy_tracking_weight` 的调用点只隔 5 行：

```
utils/reliability_signal.py
  :650   e_flow, flow_valid = assemble_flow_consensus([f_obs], [f_static], [valid], ...)
  :654   s = fuse_static_evidence(g, e_flow, opacity, mode=mode)
  :655   w = cauchy_tracking_weight(s)            # ← exclusion_mask 在这里就地构造即可
```

⇒ **最省的接法**：`exclusion_mask` 在 `:654–655` 之间用现成的 `e_flow` / `flow_valid` / `semantic_mask`
组装成一张 `(H,W)` bool，`cauchy_tracking_weight` 只接受一个**成品 mask**，不感知它怎么来的。
纯数学核保持纯粹、可单测，也不需要把 `e_flow` 塞进它的签名。

### （b）`semantic_mask` 怎么透传？—— **三层，但每层只加一个默认 None 的参数**

```
utils/slam_frontend.py :798-816   semantic_mask  (1,H,W) bool, cuda      ← 唯一的源头
        │  （与 freeze 块 :1092 同在 tracking() 作用域内，天然可见）
        ▼
utils/slam_frontend.py :1119      compute_reliability_tracking_weight(..., semantic_mask=…)
        ▼
utils/reliability_signal.py :603  新增形参 semantic_mask=None
        ▼
        :654-655 就地组装 exclusion_mask → cauchy_tracking_weight(s, exclusion_mask=…)
```

三处必须做的适配：`squeeze(0)`（`(1,H,W)`→`(H,W)`）；显式 `.to(d.device)`；
mask-free 臂 `semantic_mask` 恒 `None` ⇒ exclusion 自动退化为纯 `e_flow`，**无需额外分支**。

### （c）任务一**不需要改** `reliability_signal.py`

`frames.csv` 的列是**从 rows 派生**的，不是硬编码白名单：

```
utils/slam_frontend.py:142-146
def reliability_frames_fields(rows):
    base = list(RELIABILITY_FRAMES_BASE_FIELDS)
    return base + sorted({k for r in rows for k in r if k not in seen})
```

⇒ 只要在 `slam_frontend.py:1158–1171` 往 `rstats` 加键，**writer 零改动、列自动出现**。
（该设计是 P8 事故后专门改的，注释 `:125-135` 有记载 —— 硬编码白名单曾静默删掉整个 P8 战役的 `ego_*` 列。）

---

## 1.2 ★★ 任务二的塌缩陷阱（M0 已把估计变成测量）

**机理**：`robust_anomaly` 对 ≤ 帧中位数的残差返回 0，且无效像素也返回 0
（`utils/reliability_signal.py:119-121`）⇒ `d` 有一大团**恰好为 0** 的质量。
`tau = median(d) + 1.4826·MAD(d)`：一旦 `d==0` 占比 ≥ 50%，`median=MAD=0` ⇒ **`tau = eps`**
⇒ `w` 退化成硬二值掩码。exclusion 剔除的**全是 `d > 0.5` 的像素**（`e_flow>0.5 ⇒ d ≥ e_flow`），
只剔非零质量 ⇒ 零质量占比必然上升：

```
zero_frac_after = zero_frac_before / (1 − excl_frac)
Task 2 生效条件：zero_frac_after < 0.5
```

**flow 通道离线实测（GT pose，五序列）**：exclusion 效果**精确为零**（tau 前后同为 1.00e-06，
mean_w 前后四位小数全同）—— 因为单线索模式 tau 本来就已塌缩。这也意味着
**P7 的 flow-only / geometry-only 臂对任务二完全免疫**，做消融时不要指望它们有反应。

**`both` 模式**：需要 `v·g` ⇒ 需要 render ⇒ 由 **M0** 回答。**结果见 §五。**

---

## 1.3 任务二的前提需要修正：数据里 MAD 不"膨胀"，而是"塌缩"

架构师给的动机是"全屏动态时 MAD 膨胀导致惩罚失效"。**数据不支持这个失效模式**：

- M0 实测 `tau_before`：crowd2（全屏动态）**0.184** < f3_st_hf（静态）**0.192** < balloon **0.488**
  ⇒ 最动态的序列 tau **最低**，不存在"动态多了 tau 膨胀"。
- 尺度等变性（exp26 已证）：`d → c·d ⇒ tau → c·tau ⇒ w 不变`。tau **永远不会相对 d 膨胀**。
  实测 `mean_w` 在 8 条静/动序列上恒 0.57–0.66，**动静无差别**。

**但这不否定任务二的机制方向** —— 真正的缺陷是 `w` 看不见 `d` 的**绝对水平**，
而"把 tau 的估计限制在静态子群上"正是打破这个等变性的正确杠杆。
⚠ 但 M0 揭示了一个**上一版计划说错的地方**，见 §五-3：**exclusion 与 tau_floor 在静态帧上方向相反，
不是互补而是对抗**，两者的组合方式必须按量级重新定义。

**自洽性提醒**：`e_flow > 0.5` 本身来自 `robust_anomaly`，也按本帧中位数归一化。
在 >50% 像素是 mover 的极端帧里，中位数落在 mover 上 ⇒ 静态背景反而 `e_flow=0`，
被排除的是"最极端的那半 mover"。这不是 bug，但意味着**排除判据继承了它想修的多数支配问题**
—— 正是架构师追加约束里认可的那条效能上界。

---

## 1.4 任务一：锚点定义在 `s` 上是对的；但阈值不应预先写死

1. **不要预先定死 θ**：`s` 的分布是双峰的。M0 顺带测到 `both` 模式的
   `zero_frac(d)`（= `s==1` 的占比）为 0.376–0.511，逐序列差 1.4×
   ⇒ 一个固定 θ 在不同序列上圈出的锚点比例会差很多。
   **一次探针同时输出 θ∈{0.80, 0.90, 0.95} 三档**，事后离线选。
2. **残差就地可得，不需要额外 render**：freeze 块里已有 `image`（`:1052`）、
   `viewpoint.original_image`、`depth`（`:1053`）、`obs_depth`（`:1115`）。
3. **必须带"背景对照"统计量**：只报锚点残差无法区分"锚点特异性恶化"（B 要抓的）
   与"全局恶化"（曝光变化）。同时报补集残差中位数，**两者之比才是判据**。
4. **EMA / ring buffer 的选择留到离线**：逐帧原始值落 `frames.csv`，
   平滑方式在离线分析里试，不要在没看到信号形状前就焊进在线代码。

---

## 1.5 任务三：拍板已定的两点 + 一处"门的角色互换"

### （a）插入点被 `obs_at` 的计算位置卡死

```
utils/slam_backend.py::_alpha_lifecycle_step
  :604-620   ledger: ev_at → ema_alpha_update → 写回 static_prob(:619)/static_obs_count(:620)
  :622-623   if not params.does_exit: return
  :626-628   obs_at = sample_map_at_gaussians(obs, u, v, proj_valid, H, W)   ← override 需要它
  :629-632   reset_mask = select_reset_mask(z, obs_at, alpha, ...)           ← override 必须在它之前
  :633-643   carve_mask = select_carve_mask(z, obs_at, alpha, obs_count, ...)
```

⇒ **override 只能放在 `:628` 与 `:629` 之间**。

### （b）【拍板② 已定】持久化写回 `static_prob`，删除 false 分支

写回后 alpha 从 0 按 `alpha ← 0.9·alpha + 0.1·(1−ev)` 自愈，`ev=0` 时 `alpha_k = 1 − 0.9^k`：

| KF 数 k | 1 | 2 | 3 | 4 | 5 |
|---|---:|---:|---:|---:|---:|
| alpha | 0.100 | 0.190 | 0.271 | 0.344 | 0.410 |
| < `tau_carve`=0.20？ | ✅ | ✅ | ❌ | ❌ | ❌ |
| < `tau_reset`=0.35？ | ✅ | ✅ | ✅ | ✅ | ❌ |

⇒ **误杀自限**：一次语义假阳性最多让该高斯在 carve 门内多待 2 个 KF、reset 门内多待 4 个 KF。
实装时**不提供 `semantic_override_persist` 开关**，写回是唯一路径（拍板②）。

### （c）★ 门的角色互换："瞬杀"实为"立刻软杀 + 3 KF 后硬杀"

- `select_reset_mask`（`:211-221`）**没有 `obs_count` 门** ⇒ alpha 置 0 后**当帧立刻 opacity reset**。
- `select_carve_mask`（`:224-237`）含 `persistent = obs_count ≥ 3` ⇒ **硬 prune 仍需 3 次观测**。

上一轮说"`obs_count≥3` 不是绑定约束"（实测 `obs_ge_min=13795` 已过门）是对**存量**高斯说的；
**新生成在人身上的高斯** `obs_count` 从 0 起，仍要 3 个 KF。
⇒ **文案与判据都不要写"瞬杀"**，否则回来看到前几个 KF `carved=0` 会被误读成机制失效。

### （d）【拍板③ 已定】只建独立 arm

resolved config 实测：主干 `method_combined_maskoff_prune.yaml` 的 `AlphaLifecycle` = `None`
⇒ `mode=off` ⇒ `slam_backend.py:1209` 的门不通过，`_alpha_lifecycle_step` **一次都不执行**。
任务三新建 `configs/rgbd/experiments/t3_semantic_alpha/` 下的独立 arm，**主干一行不动**。

### （e）`in_front` 用 `delta_free_m` 是保守且正确的

`z < obs_at − delta_free_m`（0.10 m）比 `select_reset_mask` 的 `delta_occlude_m`（0.05 m）更严
⇒ override 集合 ⊂ reset 的几何集合。坐着不动的人 `z ≈ obs_at` ⇒ `in_front=False` ⇒ **保护自动成立**。

### （f）`sample_map_at_gaussians` 直接吃 bool，已验证

`sample_map_at_gaussians(bool_mask, u, v, valid, H, W) → tensor([1., 0.])`（内部 `.to(float32)`）
⇒ 语义 mask 采样到高斯用现成原语，`u,v,z,proj_valid` 在 `:586-595` 已算好并共享。

---

## 1.6 契约与不变式复核

### ★ P7 契约测试有一条**空断言**

`tests/test_p7_cuesplit_configs.py:138` 的 `assertNotIn("mode", filter_overlay(cfg))`：
`filter_overlay`（`:74-85`）返回的是**带前缀**的路径集合，实测

```
screen_balloon_on → {'ReliabilitySignal.enabled', 'ReliabilitySignal.flow_scale_floor', ...}
裸 "mode" 是否在集合里 → False        # 恒 False，与配置内容无关
```

⇒ 这条断言恒真（当前 5 tests 全绿，但它没在工作）。新增 config 键不会被它挡住，
但也**不能靠它保证 P7 arm 的纯净**。按拍板，单独一个 commit 修（§四）。

### 三条 byte-identical 回退路径

| 任务 | 开关 | 关闭时 |
|---|---|---|
| 一 | `DynamicKeyframe.anchor_probe: false`（默认） | 统计块被 `if` 跳过；`rstats` 不增键 ⇒ 列集合与历史一致 |
| 二 | `ReliabilitySignal.mad_exclusion: false`（默认） | `exclusion_mask=None` ⇒ `scale_mask` 表达式与现状逐字符相同 |
| 三 | `AlphaLifecycle.semantic_alpha_override: null`（默认） | override 块被跳过；且主干 `AlphaLifecycle` 本就 off |

> ⚠ **byte-identical 只能靠代码审查 + 单测确立，不能靠"重跑对比 ATE"。**
> exp26 实测：**同机、同 config、同 seed 两次跑出 2.99 与 33.70**（异步后端时序）。

### 其他模块（无冲突）

- **causal_twin RNG**：三项任务都不新增随机抽样；任务一/二不改 KF 数与高斯数 ⇒ 事件键集合不变。
- **`compress_deletion` / `reset_opacity_nonvisible` 顺序**：任务三仍在两次 `map()` 之后
  （`:1207-1225`），`prune_points` 后已有 `_occ_visibility_drop(~remove)`（`:650`）镜像 ⇒ 无需改。
- **`Camera.clean()`**（`camera_utils.py:156-160`）只对非关键帧调用（`:2022`），
  且后端持有队列深拷贝 ⇒ 不影响 `viewpoint.dynamic_mask`。

---

# 二、任务一：M2 锚点持久化 + 只读探针

> **无前置门控，可立即开工。**

### 改动文件与函数

| 文件 | 位置 | 改动 |
|---|---|---|
| `utils/slam_frontend.py` | `FrontEnd.__init__` 附近 `:256` | +2 行：`self.anchor_probe_enabled`、`self._anchor_last`（供 M3 读取） |
| `utils/slam_frontend.py` | freeze 块 `:1157` 之后、`:1171` `append(rstats)` 之前 | +~25 行：调新私有方法，返回 dict `update` 进 `rstats` |
| `utils/slam_frontend.py` | 新私有方法 `_anchor_stats(...)`（放 `_keyframe_diag` `:1628` 附近） | +~40 行：纯统计，`torch.no_grad()`，无副作用 |

**不改** `utils/reliability_signal.py`、**不改** frames.csv writer。

### 新增 config 键

```yaml
DynamicKeyframe:
  anchor_probe: false                     # 默认 false ⇒ byte-identical
  anchor_thresholds: [0.80, 0.90, 0.95]
  anchor_require_grad_mask: true          # 锚点是否只取强边缘像素（有约束力的那些）
```

### 实现思路

1. `A_θ = (s_map ≥ θ) & support`，`support = gt_image.sum(0) > rgb_boundary_threshold`，
   若 `anchor_require_grad_mask` 再 `& viewpoint.grad_mask`（`camera_utils.py:125-159` 现成）。
2. `rgb_res = |image − gt|.mean(0)`、`depth_res = |depth.squeeze() − obs_depth|`
   （深度侧再 `& (obs_depth > 0.01)`）。
3. 每档 θ 落 6 个键（共 18 列 + 2 全局列）：

| 键 | 含义 |
|---|---|
| `anchor_frac_s{80,90,95}` | **存活率** = \|A_θ\| / \|support\| |
| `anchor_n_s{...}` | 原始像素数（分母会漂，绝对数同样要看） |
| `anchor_rgb_med_s{...}` / `anchor_dep_med_s{...}` | A_θ 内残差中位数 |
| `anchor_rgb_med_bg_s{...}` | **补集对照**：`~A_θ & support` 内 rgb 残差中位数 |
| `anchor_ratio_s{...}` | `anchor_rgb_med / anchor_rgb_med_bg` ← **真正的判据量** |
| `anchor_support_frac` / `anchor_probe` | 全局分母漂移监控 / provenance(0-1) |

4. **只读硬保证**：整块 `torch.no_grad()`，只读不写，不进 `combined_soft`，
   不参与 `_dynamic_crisis_keyframe` 的返回值。
5. **EMA / ring buffer 不在此实现**，逐帧原始值落盘。

### 单元测试（新增 `tests/test_anchor_probe.py`）

1. `anchor_probe=false` ⇒ `rstats` 键集合与历史一致（byte-identical 守卫）。
2. 合成 `s_map` 一半 1.0 一半 0.0 ⇒ `anchor_frac_s90 == 0.5`。
3. 合成"锚点残差高、背景残差低" ⇒ `anchor_ratio > 1`；反之 `< 1`。
4. `s_map` 全 1 ⇒ 补集为空 ⇒ `anchor_rgb_med_bg` 为 nan 而非崩。
5. 探针不改变 `viewpoint.R/T`、不改变 `reliability_soft`（无副作用断言）。

### 判决（M2 生死门）

在 `f3_st_hf` 的 **frame 371**（P9 实测固定崩点；前 350 帧四臂一致 ~1.6 cm，371 一步翻倍到 3.32）
附近，`anchor_frac` 或 `anchor_ratio` **是否有可见拐点**。
参照量：`flow_valid_frac` 在 f368–380 从 0.54 掉到 0.43（−20%）—— 锚点量至少要同级才算有信号。

- **有拐点** → 进 M3（锚点触发，48 run）
- **无拐点** → B 判负，M3 不跑

---

# 三、任务二 / 任务三

## 任务二 T2：MAD 统计域的多模态隔离

> **⛔ 进入条件 = M0 判决落在前两档。M0 实测落在【第三档】——** 见 §五。
> 以下实装规格**冻结保留**，供架构师在 §五-4 的三个选项中若选择"修正后继续"时直接取用。

### 改动文件与函数

| 文件 | 位置 | 改动 |
|---|---|---|
| `utils/reliability_signal.py` | `cauchy_tracking_weight` `:448-467` | 签名 +`exclusion_mask=None`, `min_keep_frac=0.20`, `tau_floor=0.0`, `stats_out=None`；`:459-461` 的 `scale_mask` 加一项；+ guard 与回退 |
| `utils/reliability_signal.py` | `compute_reliability_tracking_weight` `:603-670` | 签名 +`semantic_mask=None`, `mad_exclusion=False`, `mad_excl_e_thresh=0.5`；`:654-655` 之间组装 mask；`stats` 追加 provenance 列 |
| `utils/slam_frontend.py` | `:1119-1139` | +3 行透传 |

### 新增 config 键

```yaml
ReliabilitySignal:
  mad_exclusion: false          # 默认 false ⇒ byte-identical
  mad_excl_e_thresh: 0.5
  mad_excl_min_keep_frac: 0.20  # guard: 保留域过小则回退
  mad_excl_tau_floor: 0.0       # 抗塌缩地板（量级见 §五-3，≠ no-harm 修复地板）
```

### 实现思路

**（a）exclusion_mask 组装**（`compute_reliability_tracking_weight` 的 `:654-655` 之间）

```
excl_flow = flow_valid & (e_flow > mad_excl_e_thresh)
excl_sem  = semantic_mask.squeeze(0).to(device, bool)  if semantic_mask is not None else False
exclusion_mask = excl_sem | excl_flow          # mask-free 时自动退化为 excl_flow
```

**（b）`cauchy_tracking_weight` 的统计域**

```
scale_mask = finite (& valid)
if exclusion_mask is not None:
    keep = scale_mask & ~exclusion_mask
    # G1 min_keep   : keep.sum() < min_keep_frac * scale_mask.sum()  → reject "too_few_kept"
    # G2 degenerate : median(d[keep])==0 且 MAD==0                    → reject "tau_collapsed"
    scale_mask = keep 或回退
sel = d[scale_mask]; tau = med + 1.4826*mad + eps
if tau_floor > 0: tau = clamp(tau, min=tau_floor)
w = 1/(1+(d/tau)**2)          # ← 对【全部像素】计算，含被排除的
```

> **语义钉死**：exclusion 只作用于 **tau 的估计域**，**不**把被排除像素的 `w` 置零、
> 也不把它们排除出 tracking loss。它们照常拿 `w = 1/(1+(d/tau)²)`，只是 tau 由静态子群决定。

**（c）provenance 列（必须落盘）**

`mad_exclusion`(声明) / `mad_excl_applied`(实际生效) / `mad_excl_reject`(none/too_few_kept/tau_collapsed) /
`mad_excl_frac` / `mad_zero_frac_before` / `mad_zero_frac_after` / `mad_tau_before` / `mad_tau_after`
—— 照抄 `ego_reject` + `reliability_frames_summary:149-187` 的 `ego_reject_counts` 聚合模式。

### 单元测试（新增 `tests/test_mad_exclusion.py`）

1. `exclusion_mask=None` 与不传参逐值相等（byte-identical 守卫）。
2. **正向机制**：30% 面积 `d≈0.9` mover + 70% 背景 `d~U(0,0.1)` ⇒ 排除后 tau 显著下降、
   `w(mover)` 显著下降、`w(background)` 基本不变。
3. **★ 塌缩 guard**：`zero_frac_before=0.45`、`excl_frac=0.25` ⇒ 排除后 0.60 > 0.5
   ⇒ 必须触发 `tau_collapsed` 回退，`mad_excl_applied==0`。
4. **min_keep guard**：exclusion 覆盖 90% ⇒ 触发 `too_few_kept` 回退。
5. **单线索无效性**（把 §1.2 的数学钉进测试）：flow-only 输入下排除前后 `tau`/`w` 逐值相等。
6. `semantic_mask=None` ⇒ 退化为纯 `e_flow` 路径。

### 消融与判决序列（**arm 说明含追加约束的显式声明**）

| 臂 | 配置 | 说明 |
|---|---|---|
| control | `mad_exclusion: false` | 当前主干 |
| **E-flow** | `true`，mask-free | ⚠ **效能上界声明**：`e_flow>0.5` 的判据本身按帧内中位数归一化，在 mover 占多数的帧里会反过来把静态背景判为异常（§1.3 自洽性提醒）。**本臂与 control 差异不显著属于预期，不构成任务二判负。** |
| **E-both** | `true`，combined（semantic ∪ e_flow） | **任务二的目标形态**。语义不依赖帧内中位数，是唯一能突破上述上界的成分 ⇒ 判据以本臂为准。 |

序列 = `{balloon, mv_no_box, crowd2, f3_st_hf, f2_xyz}` × 3 seed。

**判据**（不含"修静态崩溃"，理由见尽调报告 C1-4）：
- **机制自证（首要）**：`mad_excl_applied` 帧占比 ≥ 95%，否则读数无意义；
- **主判据**：E-both 相对 control 的动态 ATE 改善；
- **护栏**：静态 `{f3_st_hf, f2_xyz}` ATE 不劣化 > 5%，且 `mean_w` 不得进一步下降（见 §五-3 的风险）；
- E-flow ≈ control 而 E-both 显著 ⇒ **符合预期**（追加约束）。

---

## 任务三 T3：带严格几何门控的语义 Alpha 覆盖

> **无前置门控，可与任务一并行开发。** 拍板③：**只建独立 arm，主干一行不动。**

### 改动文件与函数

| 文件 | 位置 | 改动 |
|---|---|---|
| `utils/alpha_lifecycle.py` | 新增纯函数 `select_semantic_override_mask(...)`（`select_carve_mask` `:237` 之后） | +~20 行：`valid & obs_ok & in_front(delta_free_m) & semantic_hit` |
| `utils/alpha_lifecycle.py` | `AlphaLifecycleParams` `:50-84` + `read_alpha_lifecycle_params` `:106-125` | +2 字段：`semantic_alpha_override`(Optional[float])、`semantic_override_delta_m`（默认复用 `delta_free_m`） |
| `utils/slam_backend.py` | `_alpha_lifecycle_step` `:628`–`:629` 之间 | +~15 行：取 mask → 采样到高斯 → 选择 → 覆盖 alpha → **写回 `static_prob`** → 日志 |

### 新增 config 键

```yaml
AlphaLifecycle:
  mode: "exit"                    # 只在独立 arm 的 config 里打开
  semantic_alpha_override: null   # 默认 null ⇒ 不执行；设 0.0 即强制覆盖
# 注：按拍板②，不提供 semantic_override_persist 开关，写回是唯一实现
```

### 实现思路

1. **取 mask —— 只用缓存，绝不触发推理**：用 `getattr(viewpoint, "dynamic_mask", None)` 直接读，
   **不调** `get_or_compute_dynamic_mask`。`_alpha_lifecycle_step` 跑在**后端进程**，
   缓存未命中会在后端加载 Mask R-CNN（`semantic_mask.py:102-125`）—— 2060 6 GB 上是真实显存风险。
   `None` 则整块跳过并记一行日志。
2. **采样到高斯**：复用 `:586-595` 的 `u, v, z, proj_valid`：
   `sem_at = sample_map_at_gaussians(mask.squeeze(0), u, v, proj_valid, H, W) > 0.5`。
3. **几何门（架构师规定，严格保留）**：
   `override_mask = proj_valid & obs_ok & (z < obs_at − delta_free_m) & sem_at`。
4. **覆盖 + 写回**：`alpha[override_mask] = 0.0`，随后 `gaussians.static_prob = alpha.unsqueeze(1)`
   （覆盖 `:619` 那次写入）。
5. **逐 conjunct 日志**：新增 `sem_hit` / `sem_in_front` / `sem_override` 三个计数
   —— 缺了它们，"override 0 个"无法区分"没有人"/"人不在前方"/"mask 没传进来"。

### 单元测试（扩 `tests/test_alpha_lifecycle.py`）

1. `semantic_alpha_override=None` ⇒ `alpha` 与现状逐值相等（byte-identical 守卫）。
2. **静止的人不被杀**：`z == obs_at` + 语义命中 ⇒ `override_mask` 全 False。
3. **前方浮渣被杀**：`z = obs_at − 0.5` + 语义命中 ⇒ True，`alpha` 变 0。
4. **几何门优先于语义**：语义命中但 `z > obs_at` ⇒ 不覆盖。
5. **自愈速率**：override 后连喂 k 次 `evidence=0` 的 `ema_alpha_update`，
   断言 `alpha_k == 1 − 0.9^k`（把 §1.5b 的表钉进测试）。
6. `dynamic_mask=None`（mask-free 臂）⇒ 跳过，不抛异常。

### 消融与判决（【拍板③】arm 内闭环）

新建 `configs/rgbd/experiments/t3_semantic_alpha/`：

| 臂 | 配置 |
|---|---|
| A-off | `AlphaLifecycle.mode: exit`，`semantic_alpha_override: null`（复现 R2-P02 arm D 基线） |
| A-sem | 同上 + `semantic_alpha_override: 0.0` |

序列 = `{balloon, mv_no_box, pt2}`（必须 combined/mask-ON；mask-free 下恒为 no-op）× 3 seed。

**判据（机制先于指标，全部在 arm 内闭环，不与主干比）**：
1. **机制自证（首要）**：`carved > 0` 是否出现。当前实测 `carved` **恒 0**、`a_min=0.2592`
   卡在 `tau_carve=0.20` 之上、`obs_max=11` 差一步到 12（`r2_p02_e2.md`）。
   若仍 `carved==0`，先查 `sem_hit`/`sem_in_front`/`sem_override` 三计数定位哪一环空，**不看 ATE**。
2. **误杀护栏**：用 `dynamic_mask_gtmc/`（冻结 GT 运动一致性掩码，方法从未见过）held-out 核对，
   被 override 的高斯投影落在 GT 静态区的比例 ≤ 5%。
3. **渲染护栏**：band-PSNR 相对 A-off 不劣化。
4. ATE 只作观察项，不作判据。

---

# 四、顺手修：P7 空断言（独立 commit）

- 文件：`tests/test_p7_cuesplit_configs.py:138`
- 改法：`assertNotIn("mode", filter_overlay(cfg))` → `assertNotIn("ReliabilitySignal.mode", filter_overlay(cfg))`
- 同时给 `filter_overlay` 补一条自测（断言它返回带前缀的键），防止同类回归。
- **单独一个 commit，不与三项任务混淆**（拍板）。

---

# 五、M0 执行记录（2026-08-20 实测）

## 5.0 执行方式（零在线源码改动）

原计划推荐"在线诊断键"，那需要动 `slam_frontend.py`，与"零源码改动"不符。
**改为新建只读探针** `scripts/probe_mad_exclusion.py`（新文件，未修改任何既有源码）：
复用 `probe_hole_ghost.load_run/render_frame` 重渲 run 的终态地图，
用**在线函数本身**（`geometric_anomaly` / `assemble_flow_consensus` / `fuse_static_evidence`）
重建 `both` 模式的 `s`，测排除前后的统计域。

**诚实近似（与 `reliability_separability_verdict.md` 同一条）**：`render_depth`/`opacity` 来自
**终态地图**在该 run **自身估计位姿**下的重渲，不是帧 t 当时的在线地图。
公式与 `f_obs`/`obs_depth` 都是在线的，地图不是。
⚠ 注意：两条线索各自的零质量占比由中位数规则**结构性钉在 ~1/2**，与地图好坏几乎无关；
本近似影响的是两个零集的**重叠程度**（即 joint zero-frac），而被测量恰是这个 joint ⇒ 按估计读。

**位姿约定**：`trj_est` 是 c2w（`eval_utils.py:325` 存的是 `inv(w2c)`）。
探针按在线路径 `relative_pose_target_from_source(w2c_prev, w2c_cur)` = `T_{t-1<-t}`
（`slam_frontend.py:1111-1113`）复现。

## 5.1 实际跑的 run

| 序列 | arm | run 路径 | 帧数 | stride |
|---|---|---|---|---|
| balloon | mask-free（RS=both） | `results/runs/P6/P6-MASKOFF/balloon_maskoff_seed0/.../p6_maskoff_prune_balloon/seed_0/2026-08-09-16-44-52` | 40 | 10 |
| crowd2 | combined（mask ON, RS=both） | `results/runs/P6/P6-MASON/crowd2_combined_seed0/.../p6_mason_combined_crowd2/seed_0/2026-08-10-16-54-37` | 40 | 20 |
| f3_st_hf | combined（mask ON, RS=both） | `results/runs/P6/P6-MASON-8SEQ/f3_st_hf_combined_seed0/.../p6_mason_combined_f3_st_hf/seed_0/2026-08-12-20-31-36` | 40 | 25 |

> crowd2 与 f3_st_hf 的 **mask-free** 臂没有存 final PLY（只有 combined 臂存了），
> 故这两条用 combined 臂 —— 恰好也是任务二的目标形态（追加约束：combined 专属增益机制）。
> 两条 combined 臂额外跑了 `--semantic` 变体（真 Mask R-CNN，与在线同一函数），
> 给出 `exclusion = semantic ∪ (e_flow>0.5)` 的读数。

## 5.2 `mad_*` 诊断键分布摘要

| run | zero_bef | tau_bef | w_bef | ‖ excl | zero_aft | tau_aft | w_aft | **LIVE** |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| balloon（mask-free） | 0.3755 | 0.4877 | 0.7044 | ‖ 0.125 | 0.4338 | 0.2199 | 0.5581 | **85.0%** |
| crowd2（combined） | 0.4437 | 0.1835 | 0.5902 | ‖ 0.212 | 0.5827 | 0.0724 | 0.5193 | **35.0%** |
| &nbsp;&nbsp;└ + semantic | | | | ‖ 0.295 | 0.6005 | 0.0761 | 0.5207 | **32.5%** |
| f3_st_hf（combined） | 0.5105 | 0.1923 | 0.6237 | ‖ 0.080 | 0.5573 | 0.1245 | 0.5919 | **37.5%** |
| &nbsp;&nbsp;└ + semantic | | | | ‖ 0.252 | 0.6284 | 0.0395 | 0.5383 | **15.0%** |

`LIVE` = `mad_zero_frac_after < 0.5` 的帧占比 = **拍板① 的判决量**。

**逐帧汇总（120 帧池化）**

| 口径 | LIVE | 帧数 |
|---|---:|---|
| flow 变体（`exclusion = e_flow>0.5`） | **52.5%** | 63/120 |
| semflow 变体（`= semantic ∪ e_flow>0.5`，仅两条 combined 臂） | **23.8%** | 19/80 |

| 分位 | p10 | p50 | p90 |
|---|---:|---:|---:|
| `zero_frac_before` | 0.343 | 0.412 | 0.576 |
| `zero_frac_after`（flow） | 0.367 | **0.491** | 0.716 |

**真塌缩帧**（`tau_after < 1e-3`，即 tau 实际掉到 `eps` 量级）：**57/120 = 47.5%**。

> 旁证：上一版计划里用 `min_w` 反解估计 balloon 的 `zero_frac_before` 落在 0.356–0.464，
> **实测 0.3755，落在区间内** —— 反解方法本身可用。

## 5.3 ★ 三条超出 M0 原定范围、但直接影响设计的实测发现

**（1）semantic 一律使塌缩风险变**坏**，不是变好。**
crowd2 35.0% → 32.5%，f3_st_hf 37.5% → **15.0%**。原因：`sem_frac` 实测 0.218（f3_st_hf）/
0.265（crowd2），语义 mask 是一大块**非零 d** 的质量，剔掉它把零质量占比推得更高。
⚠ 这与追加约束的措辞（任务二是"combined 专属的**增益**机制"）在**塌缩风险**这条轴上方向相反：
combined 的**收益上限**更高（语义不受帧内中位数支配），但**塌缩风险**也更高。两者都真，
且实测风险这一侧目前占优。

**（2）`mean_w` 一律下降，包括静态序列 —— exclusion 与 tau_floor 在静态帧上方向相反。**

| 序列 | mean_w before → after | 方向 |
|---|---|---|
| balloon（动） | 0.7044 → 0.5581（−21%） | 降权变强，动态序列上是**想要**的 |
| crowd2（动） | 0.5902 → 0.5193（−12%） | 同上 |
| **f3_st_hf（静）** | 0.6237 → 0.5919 / **0.5383**（semflow） | **降权变强 —— 静态上是不想要的** |

对照上一轮实测的 `tau_floor`：f3_st_hf `mean_w` 0.661 → **0.840**（floor 0.5），方向**相反**。
⇒ **上一版计划里"exclusion 做主机制 + tau_floor 做地板，两者互补"的说法要更正：
在静态帧上两者是对抗的。** 必须按量级区分 floor 的两个角色：

| floor 角色 | 量级 | 与 exclusion 的关系 |
|---|---|---|
| **抗塌缩地板**（拍板① 指的这个） | ≈ 0.01–0.05（低于全部实测 `tau_after` 0.040–0.220） | ✅ 可组合，只挡 `tau→eps` |
| **no-harm 修复地板**（原 C1 的目标） | ≈ 0.25–0.50（高于静态 `tau_before` 0.192） | ❌ 会把 exclusion 完全吞掉（`max(tau_excl, floor)` 恒取 floor） |

⇒ **任务二不提供 no-harm 修复**。原 C1 的目标（静态 `mean_w` 抬到 0.85）仍然悬空，是独立议题。

**（3）副产品：`scripts/probe_reliability_separability.py` 的位姿约定与在线不一致（需独立核查）。**
该脚本第 125–128 行把 `pose_by_id[fid]`（**c2w**）直接喂给
`relative_pose_target_from_source`（docstring 要求 **w2c**），且顺序是 `(cur, prev)`
= `T_{t<-t-1}`，而在线是 `(w2c_prev, w2c_cur)` = `T_{t-1<-t}`。
`probe_reliability_floor.py:99-103` 用的是正确约定，两者不一致。
**不据此推翻 exp22 的结论**（三个 mode 受同一变换影响，AUC **排序**可能仍成立），
但 `reliability_separability_verdict.md` 的**绝对数值**需要重跑核对。
建议单独立一条待办，不并进本三项任务。

## 5.4 最终判决（对照拍板①）

> **判决：落在【第三档】（< 50%）。**

理由，按证据强度排序：

1. **判据应以 E-both（combined + semantic）为准** —— 追加约束明确任务二是"combined 专属增益机制"，
   而 E-flow 臂被声明为"不显著属预期"。该口径的实测 LIVE = **23.8%**（19/80 帧），远低于 50%。
2. **逐序列 2/3 在第三档**：crowd2 35.0%、f3_st_hf 37.5%（semflow 15.0%）；只有 balloon 的
   mask-free 臂达到 85%。
3. 即便放宽到最宽口径（flow 变体、三序列池化）也只有 **52.5%**，刚踩线，
   且 **47.5% 的帧 `tau_after` 真的掉到 `1e-6` 量级**。
4. 方向性问题（§5.3-2）：即使在 LIVE 的帧上，机制把静态序列的 `mean_w` 推向**更低**，
   与原 C1 的 no-harm 修复目标反向。

**按拍板① 第三档的处置** = **当前排除方案作废，改为独立立项测试纯 `tau_floor` 机制。**

### 5.5 给架构师的三个可选处置（供选择，不代拍）

| 选项 | 内容 | 代价 |
|---|---|---|
| **A（按拍板① 执行）** | 任务二作废；独立立项 `tau_floor`（规格见尽调报告 §6-M1：扫 `{0, .15, .25, .35, .50}` × 4 序列 × 3 seed = 60 run，主判据"静态 `mean_w` ≥ 0.85 + 动态 ATE 不劣化 ≤5%"） | 60 run；机制简单、单调、绝不塌缩 |
| **B（修正后继续）** | 把固定阈值 `e_flow>0.5` 改成**自适应配额**：按 `d` 降序只排除前 k 个像素，k 取满足 `zero_frac_after ≤ 0.45` 的最大值 ⇒ **构造上不可能塌缩**，guard 变成不可达分支 | 多 ~10 行；需重跑 M0 验证配额上限下的 tau 降幅是否还够大 |
| **C（两者并行）** | A 与 B 各自立项，同一批序列上对比 —— 它们对静态 `mean_w` 的作用方向相反，正好是一个干净的二选一实验 | 60 + 60 run |

**我的建议：B → 若 B 的 tau 降幅不足再退 A。** 理由：选项 B 保留了架构师"条件化到静态子群"
这个自适应内核（相对固定地板是更强的想法），而塌缩风险在配额约束下被**构造性消除**，
不再依赖运行时 guard 兜底。M0 的数据已经给出配额的可行区间：
`excl_frac ≤ 1 − zero_frac_before/0.45`，实测三序列分别为 balloon 0.166、crowd2 0.014、f3_st_hf −0.13
（**f3_st_hf 为负 ⇒ 该序列 `zero_frac_before=0.511` 本身已过线，任何排除都不可行**）。
⇒ 选项 B 在静态序列上会自动退化为"不排除"，这**恰好是正确行为**（静态帧本来就不需要隔离多模态）。

---

# 六、M2 探针验证命令（任务一，无前置门控）

## 6.1 需要先建的 config（2 个，各 5 行，照 P9 写法）

```yaml
# configs/rgbd/experiments/m2_anchor_probe/m2_anchor_f3_st_hf.yaml
# M2 锚点只读探针 — 唯一差异 = DynamicKeyframe.anchor_probe。
# 目的：判 frame 371（P9 实测固定崩点）附近锚点量有无拐点，决定 B 是否进 M3。
inherit_from: "configs/rgbd/tum/f3_st_hf.yaml"
method_from: "configs/rgbd/experiments/active/candidate/method_combined_maskoff_prune.yaml"
method: "M2-AnchorProbe-f3_st_hf"
DynamicKeyframe:
  anchor_probe: true
```
（`m2_anchor_balloon.yaml` 同构，`inherit_from: configs/rgbd/bonn/balloon.yaml`）

## 6.2 完整启动命令（本地 2060，2 run，串行，~40 min）

```bash
cd /data/monogs-ours
OUT=results/runs/M2/M2-ANCHOR-2060
mkdir -p "$OUT"
PY="$(conda run -n monogs-ours which python)"

# 发批铁律：先确认 config 真的存在（nohup 会吞 bash 报错并返回 0）
for seq in f3_st_hf balloon; do
  ls -l "configs/rgbd/experiments/m2_anchor_probe/m2_anchor_${seq}.yaml" || exit 1
done

for seq in f3_st_hf balloon; do
  outnm="${seq}_anchor_seed0"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm"; continue; }
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0 \
    "$PY" slam.py \
      --config "configs/rgbd/experiments/m2_anchor_probe/m2_anchor_${seq}.yaml" \
      --seed 0 \
      --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1
  echo "EXIT $outnm rc=$?"
done
```

> `--fast` 可省：memory 已记 `--fast ATE == --eval ATE`，且 M2 判据只读 `frames.csv`。
> 单卡串行（不加 `&`），2060 6 GB 不并发。

## 6.3 跑完的自证与判决命令

```bash
OUT=results/runs/M2/M2-ANCHOR-2060

# (1) 自证：run 完成 + 探针真的落盘
for seq in f3_st_hf balloon; do
  d="$OUT/${seq}_anchor_seed0"; echo "== $seq =="
  test -f "$d/tables/tracking_raw.csv" && echo "  tracking_raw.csv OK" || echo "  ❌ MISSING"
  f=$(find "$d" -name frames.csv | head -1)
  head -1 "$f" | tr ',' '\n' | grep -c '^anchor_' | xargs echo "  anchor_* 列数(应为 20):"
  python3 - "$f" <<'PY'
import csv,sys
r=list(csv.DictReader(open(sys.argv[1])))
on=sum(int(float(x.get("anchor_probe",0) or 0)) for x in r)
print(f"  anchor_probe=1 的帧: {on}/{len(r)}  (必须全中，否则探针有跳帧)")
PY
done

# (2) 判决：f3_st_hf 的 frame 371 附近有没有拐点
python3 - "$OUT/f3_st_hf_anchor_seed0" <<'PY'
import csv,glob,sys
f=glob.glob(sys.argv[1]+"/**/frames.csv",recursive=True)[0]
r={int(float(x["frame"])):x for x in csv.DictReader(open(f))}
cols=["anchor_frac_s90","anchor_ratio_s90","anchor_rgb_med_s90","flow_valid_frac"]
print(f"{'frame':>6}"+"".join(f"{c:>22}" for c in cols))
for fr in [300,340,350,360,368,371,375,380,396,421,500]:
    if fr in r:
        print(f"{fr:>6}"+"".join(f"{float(r[fr][c]):>22.4f}" if r[fr].get(c) else f"{'-':>22}" for c in cols))
PY
```

**读法**：`flow_valid_frac` 是**已知在 f368–380 有 −20% 信号**的参照量（0.54→0.43）。
`anchor_frac_s90` / `anchor_ratio_s90` 若在同一窗口出现同级或更强的变化 ⇒ **B 判活，进 M3**；
若平坦 ⇒ **B 判负，M3 的 48 run 不跑**。

## 6.4 M0 探针的复现命令（已执行，留档）

```bash
env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0 \
  conda run -n monogs-ours python scripts/probe_mad_exclusion.py \
    --run-dir <run> --seq-dir <dataset> --label <name> \
    --stride 10 --max-frames 40 [--semantic]
# 产物: results/evidence/m0_mad_exclusion/m0_<name>.json (summary + 逐帧 rows)
```

---

# 七、架构组指令与实装状态（2026-08-20 已闭环）

| # | 指令 | 状态 |
|---|---|---|
| 一 | M2 锚点持久化 + 只读探针，规格冻结 | ✅ 已实装 + smoke 通过 |
| 二 | 采纳**选项 B（自适应配额）**：按 d 降序排前 k，k 取满足 `zero_frac_after ≤ 0.45` 的最大值 | ✅ 已实装（闭式解，guard 变不可达分支） |
| 三 | T3 语义 Alpha 覆盖（独立 arm + 持久化写回 + 严格几何门） | ✅ 已实装 + 机制自证已达成 |
| 四-1 | P7 空断言修复，独立 commit | ✅ 独立 commit |
| 四-2 | `probe_reliability_separability.py` 位姿约定不一致 | 记为下个 Sprint 技术债，**未混入本次提交**（见 §八.5） |

---

# 八、实装记录（2026-08-20）

## 8.1 改动清单

| 文件 | 改动 | 关闭时 |
|---|---|---|
| `utils/slam_frontend.py` | `__init__` `_anchor_last`；`set_hyperparams` 读 3 个 anchor 键；freeze 块调 `_anchor_stats`；新私有方法 `_anchor_stats`；T2 六个键透传；`reliability_frames_summary` 加 `mad_excl_*` 聚合 | `anchor_probe: false` ⇒ `rstats` 不增键 |
| `utils/reliability_signal.py` | `cauchy_tracking_weight` +4 形参 +`stats_out`；新私有 `_quota_isolated_domain`（闭式配额）；新私有 `_mad_exclusion_candidates`；wrapper +6 形参 | `exclusion_mask=None` + `tau_floor=0.0` ⇒ 语句逐字符同现状 |
| `utils/alpha_lifecycle.py` | `AlphaLifecycleParams` +2 字段 + `does_semantic_override`；`read_alpha_lifecycle_params` 解析；新纯函数 `select_semantic_override_mask` | `semantic_alpha_override: null` ⇒ 属性 False，整块跳过 |
| `utils/slam_backend.py` | `_alpha_lifecycle_step` 在 `obs_at` 与 `select_reset_mask` 之间插入覆盖块；`alpha_sem_override_total` 计数入 `backend_timing.json` | 同上；且主干 `AlphaLifecycle` 缺省 ⇒ 整个 step 不执行 |
| `tests/` | 新增 `test_anchor_probe.py`(14) / `test_mad_exclusion.py`(19) / `test_retrofit_configs.py`(15)；扩 `test_alpha_lifecycle.py`(+9) | — |
| `configs/rgbd/experiments/` | 新增 `m2_anchor_probe/`(4) `t2_mad_quota/`(30) `t3_semantic_alpha/`(8) | — |

**全量回归**：`517 passed, 5 skipped, 224 subtests passed`。

## 8.2 任务二的闭式配额（实装形态）

排除只剔 `d > 0` 的候选 ⇒ 零质量 `n_zero` 在排除下不变 ⇒

```
zero_frac_after = z0·N / (N − k) ≤ q   ⟺   k ≤ N·(1 − z0/q)
```

`k = max(0, min(k_quota, k_minkeep, |候选 ∩ d>0|))`。三条推论：

1. `z0 ≥ q` ⇒ `k_quota ≤ 0` ⇒ **不排除，逐值回退**（M0 算出 f3_st_hf 配额上限为负，正是这一支）；
2. `k > 0` ⇒ `zero_frac_after ≤ q < 1/2` **构造成立** ⇒ tau 塌缩不是被守卫，是**不可达**；
3. 于是原设计里的 `tau_collapsed` 拒绝分支**不存在**，`min_keep_frac` 从"拒绝并回退"降级为"给 k 封顶"。

## 8.3 Smoke 实测（balloon 25 帧，降迭代，**不可作指标**）

| arm | 关键读数 |
|---|---|
| M2 | 21 列全部落盘；`support_frac`≈0.46；`frac80≥frac90≥frac95` 逐帧成立；`anchor_dep_med_s90` 随建图 1.53 m → 0.015 m |
| T2 Q-free | `applied_frac=1.0`，bind 全 `quota`，`max_zero_frac_after` = **0.4500**，tau 0.181→0.066 |
| T2 E-both | `applied_frac=1.0`，`mad_excl_semantic=1`，bind = candidates 11 / quota 13，`max_zero_frac_after` = **0.4500** |
| T3 A-off | `alpha-exit` 逐 KF `reset 0, carved 0`；`alpha_sem_override_total=0` |
| T3 A-sem | `override=50`，`reset 52`，**`carved 38`** |

**`max_zero_frac_after` 恰好停在 0.4500 且从不越界**，是 §8.2-2 在真实数据上的验证。

## 8.4 T3 的两条实测发现

**(a) 几何门确实在挡住东西，不是摆设。** KF5 `hit=130 / geom_front=104 / override=9`：
语义命中的 130 个高斯里只有 9 个同时浮在观测面前方 >0.10 m，**其余 121 个在观测面上、被保护了**。
KF10 `hit=452 / geom_front=127 / override=0` ⇒ 当帧 `reset 0, carved 0`。
没有这三个计数，KF10 会被读成"机制失效"；有了它，读法是"这一帧人身上的高斯都在观测面上"。

**(b) `carved > 0` 首次达成。** R2-P02 整个战役 `carved` **恒 0**；本次 A-off 复现了恒 0，
A-sem（唯一差异 = `semantic_alpha_override: 0.0`）拿到 `carved 38`。
⚠ 这只证明**机制会点火**，不证明点火是好事——误杀护栏（GT-MC held-out ≤5%）与渲染护栏才决定好坏。

## 8.5 两处与计划的偏离（须记录）

1. **T3 底座换了。** 计划写"复现 R2-P02 arm D 基线"，但实测
   `r2_alpha_lifecycle/alpha_exit_balloon.yaml` resolve 出 `SemanticMask.enabled = False`
   —— arm D 是 mask-free 的，在它上面 `dynamic_mask` 恒 None、两臂会逐字节相同。
   故 T3 改建在 **combined/mask-ON prune 主干**（lifecycle `prune` 而非 arm D 的 `deferred`）。
   按拍板③ 判据全在 A-off ↔ A-sem 之间闭环，不与 R2-P02 任何数比，换底座不影响判决有效性。
2. **多了一个 Q-free 臂。** 指令二字面是"按 d 降序排前 k"（无线索），而冻结规格的
   E-flow/E-both 是"线索选候选、配额封顶"。两者是**不同机制**而非同一机制的强弱版，
   故 `mad_excl_candidates: cue|all` 两条路都留，各自成臂。Q-free **不依赖分割**，
   因此是三个臂里唯一能进 mask-free 主线（免分割内核）的那个。

## 8.6 技术债（下个 Sprint，未混入本次提交）

`scripts/probe_reliability_separability.py` 把 c2w 直接喂给要求 w2c 的
`relative_pose_target_from_source`，且传参顺序与在线相反（§5.3-3）。
不据此推翻 exp22 的 mode 排序结论（三个 mode 受同一变换影响），但
`reliability_separability_verdict.md` 的**绝对数值**需重跑核对。
