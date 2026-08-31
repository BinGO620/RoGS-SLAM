# Method 章挂载点审计（零 GPU，2026-08-25，exp46）

> **起因**：为画 Fig1 pipeline 需要三个组件的准确挂载点。按 exp45 立的纪律
> （"方法章每个常数必须从解析后配置读回，不能抄散文"，Huber δ 教训）逐条对代码复核，
> **查出 §3 的三处事实错误 + 一个从未披露的第四组件**。
>
> **本文件不产生新实验数据**，只读已落盘 run 的 resolved config 与源码。

## 0. 取数口径（唯一）

| 项 | 源 |
|---|---|
| combined resolved config | `results/runs/P6/P6-FULLKERN/f3_st_xyz_combined_seed2/.../config.yml` |
| mask-free resolved config | `results/runs/P6/P6-FULLKERN-MASKFREE/f3_wk_hf_maskoff_seed1/.../config.yml` |
| WP-A 8 格 config | `configs/rgbd/experiments/wpa_factorial/method_mf_K*.yaml` |
| prune 统计 | 45 份 `results/runs/P6/**/deferred_commit_summary.json` |
| baseline 默认 | `configs/rgbd/tum/base_config.yaml:115`（`DeferredCommit.enabled: false`）|

---

## 1. 【错误 A】§3.1 把 `prune` 说成 MonoGS 原生密度控制

**稿中原文**：
> "The backbone is MonoGS in its RGB-D configuration with **its native insert-then-prune
> density lifecycle** … We change neither the Gaussian representation, the rasteriser,
> **nor the density-control rules**."

**代码事实**（`utils/deferred_commit.py:35-56` `lifecycle_mode` docstring，三臂定义）：

| `Mapping.lifecycle_mode` | 行为 | 归属 |
|---|---|---|
| `immediate` | 不确定像素**立刻入图** | **vanilla MonoGS control** |
| `prune` | 立刻入图但**带 lineage tag**，reject/expire 时**删除整条 lineage** | 本项目的 insert-then-remove 臂 |
| `deferred` | **不入图**，确认后才 promote | 本项目（已退役，V1-DEFERRED REWORK）|

全部上报 run（主表两臂 + WP-A 8 格）都是 `lifecycle_mode: "prune"`，而 base_config 默认
`DeferredCommit.enabled: false`（= vanilla 走 `immediate`）。

**⇒ `prune` 不是 MonoGS 原生，是我们加的第四个机制；密度控制规则确实被改了。**

**它有多承重**（45 份 P6 `deferred_commit_summary.json`，全部 `mode=prune`）：

| 量 | min | median | max |
|---|---:|---:|---:|
| `pruned / prune_immediate_insert` | 0.273 | **0.551** | 0.809 |
| `rejected / prune_immediate_insert` | — | **0.060** | 0.148 |

即**插入的候选高斯里有 27–81%（中位 55%）整条 lineage 被删**；其中约 6%（中位，最高 15%）
走显式 C⁻ 拒绝，其余走 TTL 到期未获足够 C⁺。**不是 inert，是主干**
（对比：§3.6 已披露的 `occ_tighten_thresh` 才是真 inert）。

## 2. 【错误 B】§3.4 的"three sites"抄了 SemanticMask 的通道表

**稿中原文**：
> "The signal is consumed at **three sites**: the tracking RGB and depth residuals,
> **the backend mapping loss**, and **the keyframe-insertion decision**."

**逐条核对**：

| 稿中声称的 site | 代码事实 | 判定 |
|---|---|---|
| tracking RGB + depth 残差 | `reliability_soft`→`combined_soft`→`get_loss_tracking(tracking_dynamic_soft=)`→`get_loss_tracking_rgbd_soft`（`slam_utils.py:541-594`，RGB 与 depth 两路都乘 `static_conf`）| ✅ **对** |
| backend mapping loss | 后端走 `get_loss_mapping(..., dynamic_mask=get_or_compute_dynamic_mask(config, viewpoint))`（`slam_backend.py:429/484`）—— 该函数在 `semantic_mask.py:88`，**只产语义 person mask**，`SemanticMask.enabled=false` 时返回 None。mapping 侧**没有任何 reliability 入口**（`reliability_loss_enabled` 只在 `slam_utils.py:161` 以 scope=`"tracking"` 调用，且 `Reliability.enabled=false`）| ❌ **错** |
| keyframe-insertion decision | 插入门 = `is_keyframe()`（covisibility）∪ `_dynamic_crisis_keyframe()`（gap_cap + motion）。后者只读 `last_dyn_coverage`，而它来自 **semantic_mask/semantic_soft**（`slam_frontend.py:863-870`），与 reliability 无关 | ❌ **错** |

**真正的第二个 site（稿中缺失）**：`DeferredCommit.reliability_confirm: true`
⇒ `viewpoint.reliability_s` / `reliability_flow_valid` 被 stash（`slam_frontend.py:1284-1290`）
⇒ `deferred_commit.py:427-456` `_reliability_maps` 读出，`use_reliability=True`
⇒ 候选确认从**整数 support/contradiction 计数**切换到**加权 C±**（`deferred_commit.py:141-144`）
⇒ 决定每个候选高斯 confirm / reject / expire ⇒ 在 `prune` 下决定**删不删整条 lineage**。

**⇒ 正确表述：reliability 信号在上报配置下只有两个消费点 ——
①tracking RGB+depth 残差；②候选高斯的 C± 确认（进而决定 prune 删除）。**
"mapping loss / 插入门"是 **SemanticMask 的**通道（exp34→36 四通道分解），被误抄进了
reliability 段。§3.5 讲 SemanticMask 的那段本身是对的。

> 另一个 reliability 消费者 `utils/visibility_window.py:30` 在上报 config 里
> `VisibilityWindow.enabled: false` ⇒ inert，不计入。

## 3. 【范围修正 C】Δ_L 是复合介入，不是纯 tracking 侧

WP-A 8 格**全部**钉死 `DeferredCommit.enabled: true` + `reliability_confirm: true` +
`lifecycle_mode: "prune"`（config 注释原文：*"DeferredCommit pinned TRUE with
reliability_confirm:true on ALL 8 cells … when L=0 the reliability_s maps are never stashed,
so confirm simply degrades to integer counts"*）。

⇒ **因子表内部有效**（8 格只有 K/R/L 三个开关在动，第四组件恒定）。
⇒ 但 **L=OFF 同时移除两个机制**：tracking 降权 **且** C± 的 reliability 加权。
E0 装置门自己的表已经写明这一点（`wpa_reliability_contribution.md` §1）：

| 项 | L=ON | L=OFF |
|---|---|---|
| reject 语义 | 加权 C±（`use_reliability=True`） | 纯整数 `contradictions` |

**⇒ F1 里 "Reliability 是唯一 5/5 不为负的组件" 作为测量成立，但它信用的"机制"跨两个 site。**
写稿时 L 必须定义为"reliability 信号族（tracking 降权 + 候选确认加权）"，
**不能**写成"a tracking down-weight"然后拿 Δ_L 给它背书 —— 那是把复合介入的效应
归给单一 site。`wpa_reliability_contribution.md` §5 自限**未**载此条，已需补。

> 附带好处：这比原叙述**更强**。reliability 不只是跟踪端的技巧，它还决定哪些高斯
> 能留在图里 —— 与"consistent with background protection"（PLY 剖析所见 opacity 全局变暗、
> 高斯数不变）在方向上自洽，且解释了为什么 Δ_L 是唯一跨 regime 不为负的轴。

## 4. 【缺失常数 D】有效 reliability 权重被 **0.10 地板**截断

`get_loss_tracking_rgbd_soft`（`slam_utils.py:545-563`）：

```python
sc = config.get("SemanticMask", {})            # StaticProb.enabled=false ⇒ 就是这一块
strength = float(sc.get("soft_strength", 1.0)) # = 1.0
floor    = float(sc.get("soft_floor", 0.10))   # = 0.1
static_conf = clamp(1.0 - strength * d_soft, floor, 1.0)
```

其中 `d_soft = 1 - w_rel`（`slam_frontend.py:1213`）⇒ `static_conf = clamp(w_rel, 0.10, 1.0)`。

**⇒ 任何像素的权重都不低于 0.10，最大降权比 10×，MRCS 从不真正剔除像素。**
§3.4 只给了 Cauchy 公式 `w=1/(1+(d/τ)²)`，**没提地板**。

两条附带事实（都要写）：
1. 这个地板**在 mask-free 臂也生效** —— `soft_floor` 读的是 `SemanticMask` 块，
   而该块即使 `enabled: false` 也带 `soft_floor: 0.1` / `soft_strength: 1.0`（已核对 mask-free config）。
   **配置卫生瑕疵**（mask-free 的常数挂在 mask 的命名空间下），但行为明确、逐字节可复现。
2. 这是 **F2 的加强项**，不是减分项：受控对照里朴素 p90 阈值是**硬剔除**，
   MRCS 是**有界降权**（≥0.10）。"bounded down-weight vs hard removal" 是比
   "我们的阈值更好"更结实的机制差异陈述。

## 5. 【已复核为正确，不改】

| 稿中陈述 | 复核结果 |
|---|---|
| `gap_cap = 5`；native 0.045–0.075 → 0.198–0.204 kf/frame | ✅ config 一致 |
| Huber `δ_rgb = δ_depth = 0.1`、detached 残差、每迭代重算 | ✅ `slam_utils.py:439-453` + `_robust_irls_weight` |
| reliability 每帧算一次、warmup_iters=10 后冻结 | ✅ `slam_frontend.py:1136-1141` |
| `occ_tighten_thresh = 2.0` inert | ✅ **双重** inert：`dyn_cov` 是 [0,1] 分数、阈值 2.0 不可达；且 `gap_cap_tight` 未配置 ⇒ 合取项恒假（`slam_frontend.py:1647,1657-1661`）|
| combined 的硬 mask 仅活在 warmup_iters 之前 | ✅ dispatch 实证：`he=SemanticMask.hard_tracking_mask` 未配置 ⇒ 有 soft 时走 `_soft` 分支、硬 mask 被完全绕过（`slam_utils.py:132-154`，代码注释亦明说）|
| `s → 1` 恢复原估计器（no-harm） | ✅ 但**受 §4 地板限制**：`w_rel→1 ⇒ static_conf→1`，no-harm 成立；反向饱和被 0.10 截断 |

## 6. 写作后果（逐条可执行）

| # | 位置 | 动作 |
|---|---|---|
| A | §3.1 | 删掉"native insert-then-prune"与"change no density-control rules"；把 `prune` 作为**第四个组件**披露，给 27–81%/中位 55% 的删除份额；点明 vanilla = `immediate` |
| B | §3.4 末句 | 改为两个 site（tracking 残差 / 候选 C± 确认）；"mapping loss + 插入门"移到 §3.5 的 SemanticMask 名下 |
| C | §3.4 + §5 | L 定义为"reliability 信号族（两 site）"；Δ_L 明写为复合介入的联合效应 |
| D | §3.4 | 补 0.10 地板 + "bounded down-weight, never removal"；§3.6 常数表加 `soft_floor=0.1`、`soft_strength=1.0` |
| E | §3.6 | 常数表加 `lifecycle_mode=prune` 的语义（已有该字段，但读者会当成 MonoGS 原生）+ `DeferredCommit.{enabled,reliability_confirm,ttl_keyframes=5,confirming_views=2}` |
| F | Fig1 | 必须画**四个**挂载点，且 reliability 画**两条**出边（tracking 残差 / 候选确认），不能画成三组件 |
| G | `wpa_reliability_contribution.md` §5 | 补一条自限：Δ_L 是两 site 的联合效应 |

## 7. 自限

- 本审计只覆盖**上报配置**（主表两臂 + WP-A 8 格）。别的 campaign（P7/P11/exp39…）
  的 config 未逐一复核，本文件的结论**不外推**到它们。
- prune 份额取自 45 份 P6 summary；主表 run 的合并目录只留 `tables/`，
  故份额是**同 campaign 同 lifecycle 的实测范围**，不是主表逐格的精确值。
- §3 的 `rejected` vs `expired` 拆分说明 reliability 加权影响 C±，
  但**未测**"关掉 reliability 加权后删除份额变多少"—— 那需要新 run（L 轴已含此变化，
  但未单独隔离 C± 通道）。⇒ 不得声称"reliability 使删除份额下降 X%"。
