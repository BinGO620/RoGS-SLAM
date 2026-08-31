# 可行性尽调报告

> 对象：外部方法论架构师提出的三项改造设想（A 连续态线索路由 / B 锚点自适应关键帧 / C MAD 先验锚定 + 语义强杀）
> 执行：2026-08-20，分支 `ours-v3` @ `e2cebd5b`。零 GPU 批量；所有统计从盘上已有 run 产物与在线函数离线重算得出。
> 约束遵守：**未写任何实装代码**；未改动任何 config / 源文件。

---

## 0. 一句话结论

| 设想 | 判定 | 根因 |
|---|---|---|
| **A** 连续态线索路由 | **不建议实施（按当前描述）** | 要解决的"阈值震荡"在代码里不存在（`mode` 是 run 级常量，非运行时开关）；且 α_flow 的判别基底已被本项目两个独立测量层证否 |
| **B** 锚点纯化自适应关键帧 | **有条件可行（三项中唯一有正面证据基底）** | 靶子（`gap_cap=5` ⇒ 215 KF/1074 帧）是 P9 的头号假设且有部分正面读数；时序无问题，缺的只是 `w` 的持久化 |
| **C1** `tau_floor` | **可行（最干净的一项），但预期效应必须下调** | 方向与架构师担心的相反：当前 tau 才是破坏 no-harm 的那一方，floor 是修复它；但 exp26 已证它**不修**静态崩溃 |
| **C2** 语义强杀 evidence=1.0 | **不建议实施（打错了 conjunct）** | 绑定约束不是 `obs_count≥3`（实测 13795 个高斯已过该门），是 `alpha<tau_carve` 的 EMA 速率（需 n≥12，实测 obs_max=11） |

**本次尽调产出的两个新事实**（此前项目内未记录，直接改变 A 与 C1 的设计前提）：

1. **单线索模式下 `w` 根本不是软权重，是硬二值掩码。** `robust_anomaly` 对 ≤ 帧中位数的残差返回 0，无效像素也返回 0 ⇒ flow-only / geometry-only 下 `median(d)=0` 且 `MAD(d)=0` ⇒ `tau = eps = 1e-6` ⇒ `w ∈ {≈0, 1}`。实测坐实：P7 全部 22 个单线索 arm 的 `min_w` **每一帧恰好 = 0.000000**；`both` 臂 `min_w = 0.143–0.181`。
2. **闭式恒等式** `mean_w(flow-only) = 1 − 0.5·flow_valid_frac`，4 序列吻合到小数点后 5 位（残差 `+0.00000`）。⇒ 单线索下 `w` 携带的信息量正好 1 bit：「本像素残差是否 ≤ 本帧中位数」，与场景内容无关。

---

## 1. 每个设想的可行性判定

### 设想 A：Regime-Aware 连续态线索路由 —— **不建议实施**

**A-1（前提事实错误）：不存在"阈值处震荡"。**
`mode` 每帧从同一个 config 字符串读出，全 run 恒定：

- `utils/slam_frontend.py:1132` — `mode=str(rel_cfg.get("mode", "both"))`，`rel_cfg` 在 `:998` 一次读出，循环内不变。
- `utils/reliability_signal.py:425` — docstring 明写 `mode` is an **ABLATION-only switch**。

没有运行时切换，因而没有可震荡的阈值。A 的动机在当前代码库上不成立。**若架构师的真实意图是"P7 证明了需要按 regime 选线索，但没有选择器"，那是另一个问题**，见 A-3。

**A-2（判别基底不存在，实测）：`flow_valid.mean()` 与 `g.mean()` 在帧级不可分。**
从 181 个 `reliability_signal/frames.csv`（主臂 `maskoff_prune` + `mason_combined`，共 104 694 帧）计算 dynamic-vs-static 的帧级 AUC：

| 线索 | DYN-TUM vs STATIC-TUM | ALL-DYN vs STATIC-TUM |
|---|---:|---:|
| `flow_valid_frac` | **0.463**（低于随机） | 0.586 |
| `g_mean` | 0.586 | 0.640 |
| `e_flow_mean_valid` | 0.538 | 0.580 |

同数据集内部（TUM，排除传感器混杂）三个量全部接近随机。跨数据集那一列的抬升是**数据集身份**的混杂：`flow_valid` 在 Bonn 恒为 0.838–0.865、在 TUM 为 0.626–0.833，而 TUM 的 walking（动）0.666 与 sitting（静）0.669 **几乎相同**。

**A-3（更强的反证）：即使给一个 oracle 级的线索质量标量，也不能用来路由。**
`results/evidence/reliability_separability_verdict.md` 结论 3（exp22，已入档）：像素级可分性 AUC 排序是 flow-only 3/4 最优，而 P7 的 ATE 排序是 geometry-only 3/4 最优，**两个排序不一致**。原文判据："『检测得更准 ⇒ SLAM 更好』这条直觉在我们的系统里不成立……future work 的 selector 必须直接以**位姿误差**为目标，而不是以线索可分性为代理。"
A 的 α_flow 恰恰是从"线索质量"代理构造的 ⇒ 落在已被证否的那一族里。

**A-4（同类改造已跑过诊断并判负）：** `results/evidence/wpf_fusion_operator_diag_framelevel.md` 对 min / max / geomean 三个替代融合算子做过帧级诊断，判决"**不通过（无分离度提升信号）**，算子主要效果是全局重标定"。A 的几何均值形式正是其中之一。

**A-5（本次新增的机制层反证）：Cauchy 归一化会吃掉 α 的大部分作用。**
线性混合 `s = α(1−e) + (1−α)(1−v·g)` ⇒ `d = α·e + (1−α)·v·g`。对任意 α∈(0,1)，`d=0` 当且仅当 `e=0 ∧ v·g=0` —— **零集与 `both` 完全相同**。而 `tau = median(d)+1.4826·MAD(d)` 与 `d` 同尺度（`utils/reliability_signal.py:465`），所以 `w` 对 `d` 的整体缩放**严格不变**（exp26 数值证：`s∈[0.97,1]` 与 `s∈[0.10,1]` 的 `mean_w` 同为 0.7438）。α 只能通过改变两条线索的**相对形状**影响 `w`，改变量级的那部分被完全归一化掉。这在机制上解释了 A-4 为什么测出"只有全局重标定"。

**A-6（序列级选择器整族已关门）：** `results/evidence/wphs_person_area_characterization.md`（WP-HS）判 FAIL，且是"整族失败"：`both` 组唯一成员 mv_no_box（4.54%）夹在两个 geo 组成员 mv_no_box2（3.30%）与 pt2（8.24%）之间 ⇒ **不存在任何单调阈值**；换 dilate / 均值 / 中位数 / 检出率四个变体全部同构失败。

> **结论**：A 按当前描述无法立项。P7 只证了"需要选择"，未证任何选择器成立；A 提出的选择器所依赖的判别量（线索质量）已在**两个独立测量层**（像素 AUC、帧级统计）被证否。
> **可保留的部分**：`mode="both"/"flow-only"/"geometry-only"` 旁路**必须保留**（P7 契约测试依赖，见 §2）。若架构师坚持推进，唯一有意义的下一步是 WP-F 执行卡 §10.1 早已规定但未执行的 **per-pixel 分离度探针**（需 2060 stash 逐像素 `e_flow`/`g`），过了才谈 GPU。

---

### 设想 B：锚点纯化的自适应关键帧 —— **有条件可行**

**B-1（时序无问题，架构师的担心不成立；真正的缺口是持久化）。**
调用链在 `utils/slam_frontend.py::run()` 内是严格顺序的：

- `:2001` `render_pkg = self.tracking(cur_frame_idx, viewpoint)`
- `:2029` `create_kf = self.is_keyframe(...)`
- `:2051` `create_kf = self._dynamic_crisis_keyframe(cur_frame_idx, last_keyframe_idx)`

所以 KF 决策点**一定**在 reliability freeze 之后。问题在于 `reliability_soft` / `w_map` 是 `tracking()` 的**局部变量**（`:1140`），函数返回即丢；只有 `s_map`/`fv_map` 会在 `DeferredCommit.reliability_confirm` 打开时 stash 到 viewpoint（`:1200–1206`），**`w` 从未被 stash 到任何地方**。
⇒ 不需要提前 freeze，不需要移动位置；只需要在 freeze 块内把锚点统计量（或 `w_map` 本身）挂到 `self` / `viewpoint`。这是 B 里成本最低的一步。

**B-2（靶子对，且有量化的正面读数）。**
`results/evidence/p9_static_ablate_prereg.md` 的头号假设 A1 就是本条：`gap_cap=5` ⇒ 实测 **215 KF / 1074 帧**（正好 1/5），而 f3_st_hf 帧间平移中位仅 0.65 cm，vanilla 按 `kf_overlap=0.9`/`kf_translation=0.08m` 只需稀疏 KF ⇒ KF 洪水淹后端。实测逃逸账：

| 臂 | KF | 逃逸 | ATE |
|---|---:|---:|---|
| control（RS 全开） | 215 | **0/9**（合并四个同类臂） | 34–36，全崩在 frame 371 |
| −DynamicKeyframe | **57** | **2/3** | 4.01 / 2.91 / 25.02 |
| A5 bothoff（保留 215 KF） | 215 | 3/5 | 2.19 / 35.36 / 2.38 / 2.45 / 18.95 |
| vanilla | 稀疏 | 4/5 | 2.51 / 2.44 / 2.33 / 2.18 / 20.94 |

**⚠ 必须同时读的反面证据**：P9 最终判决第 5 条明写 —— bothoff **保留了 215 密集 KF 仍恢复到 3/5** ⇒ "`DynamicKeyframe` 并非必须动的那一个"。所以 B 有正面信号，但**不能宣称它是已证的病因**；判据必须写成"逃逸率是否显著优于 control 0/9"，不能写成"修好静态崩溃"。

**B-3（mask-free 下只有一条触发在跑 —— 架构师担心的"三条触发叠加"不存在）。**
`_dynamic_crisis_keyframe`（`:1543–1591`）的三条触发在当前 mask-free 主干上的实际状态：

| 触发 | 依赖 | mask-free 下 |
|---|---|---|
| legacy coverage | `crisis_interval` + `person_mask_ratio_thresh` | **未配置** ⇒ 死路 |
| gap cap | `gap_cap` / `gap_cap_tight` | **唯一活跃**（`gap_cap=5`） |
| motion cap | `motion_tau_depth` / `motion_tau_tight` | **未配置** ⇒ 死路 |
| 收紧开关 | `high_occ = last_dyn_coverage ≥ occ_tighten_thresh` | `last_dyn_coverage` 只在 `semantic_mask`/`semantic_soft` 非 None 时更新（`:820–826`），mask-free 恒 0.0 ⇒ `high_occ` **恒 False** |

resolved config（`method_combined_maskoff_prune.yaml`）：`DynamicKeyframe = {enabled: true, gap_cap: 5, occ_tighten_thresh: 2.0}`。
⇒ **当前 mask-free backbone 的 `_dynamic_crisis_keyframe` 等价于纯固定 5 帧间隔。** `kf_budget` 上限已实现（`:1559–1561`），可直接复用。

**B-4（⚠ 锚点定义必须改：`w>0.8` 在单线索模式下是退化的）。**
架构师的关键假设是"`w>0.8` 的像素代表可信静态背景"。用 shipped 函数实测：

| mode | zero-frac(d==0) | median(d) | tau | mean_w | min_w | **frac(w>0.8)** |
|---|---:|---:|---:|---:|---:|---:|
| flow-only | 0.5000 | 0.00e+00 | **1.000e-06** | 0.5000 | 0.000000 | **0.5000** |
| geometry-only | 0.5000 | 0.00e+00 | **1.000e-06** | 0.5000 | 0.000000 | **0.5000** |
| both | 0.4934 | 1.27e-02 | 3.157e-02 | 0.5116 | 0.000996 | 0.5010 |

单线索模式下 `frac(w>0.8)` **恰好等于** `zero-frac`：`w>0.8` 就是「残差 ≤ 本帧中位数」的指示函数，与"静态"无关 —— 它只说明这个像素在**本帧内**比一半像素好，帧间不可比，因而"锚点存活率"会被帧内重标定伪造。
⇒ B 的锚点必须定义在 **`s`（或 `1−e_flow`、`1−v·g`）的绝对水平**上，或在 C1 落地（tau_floor 恢复绝对可比性）之后再用 `w`。**这条把 C1 变成了 B 的前置依赖。**

**B-5（mask-free / RS-off 臂的 fallback 现成）。**
`:1209–1217`：mask-free 下 `base_soft=None` ⇒ `combined_soft == reliability_soft`。若 RS 关闭（vanilla / ablation 臂），`reliability_soft=None` ⇒ 无锚点。架构师提的 `rgb_pixel_mask ∩ opacity>0.95` 在 `utils/slam_utils.py:344–347`（`valid & grad_mask & hard_static`）与 `:365–367`（`opacity.detach()>0.95`）已是现成基元，可直接复用，**无需新写几何**。

---

### 设想 C1：`cauchy_tracking_weight` 的 `tau_floor` —— **可行，但预期效应必须下调**

**C1-1（量纲）：`d = 1−s ∈ [0,1]`，无量纲。`tau_floor` 与 `d` 同域，取值在 `[0,1]`。**
代码路径：`utils/reliability_signal.py:463–466` — `med = sel.median(); mad = (sel−med).abs().median(); tau = med + 1.4826·mad + eps`。加 floor 的位置只有 `:465` 一行（与 `robust_anomaly:116–117` 已有的 `scale_floor` 完全同构，可直接照抄那个 clamp 写法）。

**C1-2（分位实测）。** rstats **不含** per-pixel 分位（`compute_reliability_tracking_weight:657–667` 只落 `mean_s` / `min_s`）。两个层次分别测：

*(a) per-frame `mean_d = 1−mean_s`（181 run，104 694 帧，主臂）*

| 族 | 帧数 | mean_d p10/p50/p90 | max_d 的中位数 | flow_valid p10/p50/p90 | g_mean p50 | e_flow p50 |
|---|---:|---|---:|---|---:|---:|
| STATIC-TUM | 59 015 | 0.201 / **0.280** / 0.340 | **1.000** | 0.528/0.747/0.846 | 0.242 | 0.084 |
| DYN-TUM | 33 561 | 0.215 / **0.284** / 0.333 | **1.000** | 0.532/0.744/0.830 | 0.254 | 0.085 |
| DYN-BONN | 12 118 | 0.279 / **0.324** / 0.394 | **1.000** | 0.833/0.856/0.874 | 0.271 | 0.136 |

`max_d` 中位数 = 1.000 ⇒ 半数以上的帧里**存在 `s=0` 的像素**，尾巴永远打满。

*(b) per-pixel `d`（本次用在线函数离线重算，GT pose + 冻结 RAFT，CPU，flow 通道，stride 8，每序列 60 帧）*

| 序列 | d(flow) p50 | p90 | p99 | tau(floor=0) | mean_w @ floor 0 / .15 / .25 / .35 / .50 |
|---|---:|---:|---:|---:|---|
| f3_st_hf（静） | **0.0000** | 0.708 | 0.928 | **0.0000** | 0.661 / 0.725 / 0.763 / 0.797 / 0.840 |
| f3_wk_hf（动） | **0.0000** | 0.818 | 0.961 | **0.0000** | 0.652 / 0.714 / 0.750 / 0.781 / 0.822 |
| balloon（动） | **0.0000** | 0.722 | 0.908 | **0.0000** | 0.571 / 0.656 / 0.709 / 0.755 / 0.810 |
| crowd2（动） | **0.0000** | 0.867 | 0.957 | **0.0000** | 0.584 / 0.659 / 0.701 / 0.737 / 0.784 |

`d` 是**双峰**的（一半质量在 0，另一半在 0.7–0.96），中间几乎无质量 ⇒ **分布本身读不出一个自然的 floor 拐点**，`mean_w` 对 floor 单调平滑上升。⇒ 必须扫描，不能"从分位算出来"。建议预注册扫 **{0.0(control), 0.15, 0.25, 0.35, 0.50}**。

**C1-3（no-harm 方向与架构师的担心相反 —— 这是本节最重要的一条）。**
架构师问"会不会破坏静态帧 no-harm"。从代码路径确认：**破坏 no-harm 的恰恰是现状，`tau_floor` 是修复它。**

- 当前 `tau` 与 `d` 同尺度 ⇒ 把 `d` 整体乘任意 `c>0`，`med→c·med`、`mad→c·mad`、`tau→c·tau`，`d/tau` 不变 ⇒ **`w` 完全看不见 `d` 的量级**。exp26 数值证：`s∈[0.97,1.00]` 与 `s∈[0.10,1.00]` 的 `mean_w` 同为 **0.7438**、`w<0.5` 像素比例同为 **0.1303**（小数点后四位全同）。
- 真实数据对上：8 序列（4 静 4 动）全 run `mean_w` 恒在 **0.57–0.66**，静态动态无差别 ⇒ 纯静态桌面序列上照样丢 ~38% 光度信号。docstring `s→1 ⇒ w→1 (no-harm)`（`:451–452`）只在 `d` 完全无展度时成立。
- 加 floor 后：`d ≪ tau_floor ⇒ w = 1/(1+(d/tau_floor)²) → 1`，no-harm 恢复。上表 f3_st_hf `mean_w` 0.661→0.840 即此效应。

**C1-4（⚠ 但判据不能写成"修静态崩溃"）。** 两条预注册判据已把这条路堵死：

- `exp26_w1_causal_prereg.md`：把下权重**完全去掉**（`tracking_downweight_off`，自证 1077/1077 帧），ATE 仍 **35.99**，仍在 frame 371 翻倍。
- P9：**vanilla 自己也崩 4/5**（seed4 = 20.94，发散区间 299→409 夹住 371）⇒ f3_st_hf 对 MonoGS 本身即临界序列。

⇒ C1 的判据只能是「**恢复 no-harm 不变式**（静态序列 `mean_w` 显著抬升）+ **不伤动态增益**（动态 ATE 不劣化）」，不能是 ATE 改善。

**C1-5（⚠ 一个 C1 未预见的副作用：它会重定义 P7 的全部单线索臂）。**
由 §0 的新事实：单线索模式下 `tau=eps`，`w` 是硬二值掩码。加 floor 后 `tau ≥ tau_floor ≫ eps` ⇒ **flow-only / geometry-only 从硬掩码变成软权重**，语义完全改变。P7 那 24 个单线索 run（`p7_cuesplit_verdict.md` 的 flow/geo 两列）都是在硬掩码语义下测的。落地时必须显式决定：单线索臂是冻结在 `floor=0` 还是一并重跑（见 §6 开放问题 2）。

---

### 设想 C2：语义强杀（semantic hit ⇒ evidence = 1.0） —— **不建议实施**

**C2-1（模块当前是关的，且属于已判负的支线）。**
resolved config 实测：`method_combined_maskoff_prune.yaml` 的 `AlphaLifecycle` block = **None** ⇒ `alpha_lifecycle_mode()` 返回 `off` ⇒ `alpha_lifecycle_active()` = **False** ⇒ `slam_backend.py:1209` 的门不通过，`_alpha_lifecycle_step` **在所有 active/candidate 臂上根本不执行**。含 `AlphaLifecycle` 的 config 只存在于 `configs/rgbd/experiments/r2_alpha_lifecycle/`（R2-P02 支线，`03-results.md` 记 **H1 证伪**）。C2 要先复活一个已进死清单的模块。

**C2-2（★ 关键：`obs_count≥3` 从来不是绑定约束，C2 打错了 conjunct）。**
`results/evidence/r2_p02_e2.md` §2(c) 的门算术，与 §附表实测一起读：

- `ema_beta=0.9`、初始 `α=0.7` ⇒ 跨 `tau_reset=0.35` 需 **n≥7** 次满证据更新；跨 `tau_carve=0.20` 需 **n≥12**（`0.7·0.9¹¹=0.2197 > 0.20`，`0.7·0.9¹²=0.1977 < 0.20`）。
- 修好后的实测：`obs_ge_min`（`obs_count ≥ min_obs_count` 的高斯数）= **13 795**，`obs_max` = **11**，`a_min` = **0.2592**，`carved` 恒 **0**。

⇒ **观察期门早就过了**（13 795 个高斯在门内）；卡死的是 `alpha < tau_carve` 这个 alpha 门，且差**正好一步**（11 vs 12）。
而 C2 提出的 `evidence := 1.0` 在 `ema_alpha_update`（`utils/alpha_lifecycle.py:191–205`）里等价于 `static_obs = 1−1 = 0` ⇒ `α ← 0.9·α` —— 这**正是满证据路径本身**。`depth_inconsistency_evidence`（`:168–188`）对一个挡在背景前的人给出 `1−exp(−excess)`，`excess` 很大时已经 ≈1。**⇒ C2 什么也不会改变。**

**构造性替代**（若架构师确要语义强杀）：绕过 EMA 而不是绕过 `obs_count` —— 直接写 `alpha[semantic_hit] = 0.0`，或降 `ema_beta`、抬 `tau_carve`。这三者任一都是一行改动，且判别力远强于改 `evidence`。

**C2-3（`in_front` 必须保留 —— 架构师的直觉正确，且现状已经是对的）。**
`select_carve_mask`（`:224–237`）= `valid & obs_ok & in_front & (alpha<tau_carve) & persistent`，`in_front = z < obs_at − delta_free_m`。
坐着不动的人：语义命中，但人**就是**被观测表面 ⇒ `z ≈ obs_at` ⇒ `in_front` = False ⇒ 不会被 carve。`select_reset_mask`（`:211–221`）同构。**保留 `in_front` 自动保护静止的人，无需新增门控。**

**C2-4（语义 mask 在后端可达，无需新传递路径）。**

- 前端在 `slam_frontend.py:833` 设 `viewpoint.dynamic_mask`；`request_keyframe`（`:1446–1449`）把整个 `viewpoint` 对象经队列送出；后端 `slam_backend.py:1143–1151` 存进 `self.viewpoints[cur_frame_idx]`。
- 后端已在 `:366` / `:417` 调 `get_or_compute_dynamic_mask(self.config, viewpoint)`；该函数（`utils/semantic_mask.py:88–99`）**先查 `viewpoint.dynamic_mask` 缓存**，命中即返回。
- ⚠ 风险：`_alpha_lifecycle_step` 用 `self.viewpoints[cur_frame_idx]`（`:1210`），而 `map()` 的 random-KF 分支（`:389–420`）会对**未缓存**的 viewpoint 触发 `compute_semantic_dynamic_mask` ⇒ 在**后端进程**加载 Mask R-CNN（`_load_model:102–125`）。2060 6 GB 上这是真实的显存风险。

**C2-5（与 `compress_deletion` / `reset_opacity_nonvisible` 的顺序无冲突）。**
`map()` 内：`reset_opacity_nonvisible`（`:511`，用 `visibility_filter_acm`）→ optimizer/pose step → `compress_deletion`（`:536–543`，注释 `:526–535` 说明必须在 visibility 张量消费完之后）。
`_alpha_lifecycle_step` 在两次 `map()` **之后**调用（`:1207–1225`），其 `prune_points` 后立刻 `self._occ_visibility_drop(~remove)`（`:650`）镜像收缩缓存。**顺序正确，无需改动。** 若 C2 大幅提高 carve 数量，与 `compress_deletion` 争夺同一批低 opacity 高斯是**数量级问题**（重复删除、地图容量），不是正确性问题。

---

## 2. 冲突与依赖清单

| # | 改造 | 冲突对象 | 性质 | 说明 |
|---|---|---|---|---|
| 1 | A | `tests/test_p7_cuesplit_configs.py:49` `ALLOWED_REL_DIFFS={enabled,mode}`；`:138` 断言默认臂**不得**显式 set `mode` | **硬冲突** | 新键若加进 P7 overlay 即 FAIL。加在 backbone 默认里则 base 与 overlay 同值、diff 为空 ⇒ 安全。**`mode` 三值旁路必须保留** |
| 2 | A | `tests/test_reliability_signal_cue_split.py::test_default_both_formula` | **硬冲突** | 钉死 `both == (1−e)(1−v·g)` 且省略 `mode` 与 `mode="both"` 等价。A 不得改默认路径 |
| 3 | A / C1 | **static no-harm 不变式** | ⚠ | A：任意 α∈(0,1) 的零集与 `both` 相同，`s→1 ⇒ d→0 ⇒ w→1` 在**分布无展度**时才成立 —— 与现状同样破缺，A 不改善也不恶化。C1：**修复**该不变式（唯一正向的一项） |
| 4 | C1 | P7 单线索臂 24 个 run 的 ATE 基数 | **硬冲突** | floor 把 flow-only/geometry-only 从硬掩码变软权重（§1 C1-5）。必须显式选择冻结或重跑 |
| 5 | B | `utils/causal_twin.py:24–30` CounterRNG key 契约 | ⚠ **不可修复的配对损失** | key 不含 arm-dependent 量，但 B 改变 KF **数量** ⇒ `map_randperm` 的事件**集合**改变、`random_viewpoint_stack` 尺寸改变 ⇒ B 臂与 baseline **天然不是 causal twin**。判据须走多 seed 分布比较，不能走配对 |
| 6 | B | `occ_aware_visibility` / `is_keyframe` | 无冲突 | `is_keyframe`（`:1367–1374`）的 `logical_or` 依赖尺寸一致；B 不改高斯数量 ⇒ 不触发 `_occ_visibility_drop/_grow` 路径 |
| 7 | B | `SemanticMask` | 已隔离 | mask-free 下 `last_dyn_coverage ≡ 0.0` ⇒ 旧的 coverage 触发与 `high_occ` 全死（§1 B-3），新触发不会与它们叠加 |
| 8 | B | `RobustTracking` | 无冲突 | `RobustTracking` 只进 tracking loss 的 IRLS 权重（`slam_utils.py:352–360`），不参与 KF 决策 |
| 9 | B | `DeferredCommit` | ⚠ 间接 | KF 数变化 ⇒ `deferred_manager.process_keyframe`（`:2086`）调用次数变化 ⇒ candidate 生命周期统计不可与旧批直接比 |
| 10 | C2 | `AlphaLifecycle` 模块状态 | **阻塞** | 全部 active/candidate 臂 `mode=off`；复活它本身就是一个独立决策 |
| 11 | C2 | `compress_deletion` / `reset_opacity_nonvisible` | 无顺序冲突 | §1 C2-5；仅数量级竞争 |
| 12 | C2 | 后端 Mask R-CNN 显存 | ⚠ | random-KF 分支可能在后端进程加载检测器（§1 C2-4）。2060 6 GB 风险 |
| 13 | 全部 | **byte-identical vanilla when disabled** | 可满足 | A：默认 `both` 不变；B：新触发键缺省 ⇒ `_dynamic_crisis_keyframe` 逐字节不变；C1：`tau_floor=0.0` ⇒ 照抄 `robust_anomaly:116–117` 的 `if floor>0` 守卫即跳过；C2：`AlphaLifecycle` 缺省 off |
| 14 | B | `ReliabilitySignal.enabled=false` 的 ablation 臂 | 需设计 | 无 `reliability_soft` ⇒ 必须 fallback（§1 B-5），否则 B 在这些臂上静默失效（`assert_reliability_flow_available:576–600` 那类"静默 no-op"事故的同型风险） |

---

## 3. 数据/日志证据

数据源：`results/runs/**/reliability_signal/frames.csv`（181 个 run）、`p7_cuesplit_verdict.md`、`p9_static_ablate_prereg.md`、`r2_p02_e2.md`、`reliability_separability_verdict.md`、`wphs_person_area_characterization.md`、`wpf_fusion_operator_diag_framelevel.md`。

### 3.1 `flow_valid` 与 `g` 的分布（支持/反驳 A 的假设 1）

**结论：反驳。** 两者都不分离 dynamic/static，主要编码数据集身份。

| 序列（主臂 mean over runs） | flow_valid | g_mean | e_flow | mean_s | mean_w | min_w | flow_valid 帧内 sd |
|---|---:|---:|---:|---:|---:|---:|---:|
| balloon（动·Bonn） | 0.8600 | 0.2819 | 0.1327 | 0.6614 | 0.6758 | 0.1594 | 0.0104 |
| mv_no_box（动·Bonn） | 0.8644 | 0.2730 | 0.1147 | 0.6759 | 0.6754 | 0.1439 | 0.0111 |
| pt2（动·Bonn） | 0.8646 | 0.2671 | 0.1509 | 0.6713 | 0.6958 | 0.1842 | 0.0132 |
| crowd2（动·Bonn） | 0.8375 | 0.2871 | 0.2352 | 0.6295 | 0.6418 | 0.1490 | 0.0220 |
| **f3_wk_hf（动·TUM）** | **0.6657** | 0.2341 | 0.2052 | 0.7052 | 0.6007 | 0.0418 | 0.1208 |
| **f3_st_hf（静·TUM）** | **0.6694** | 0.2253 | 0.1454 | 0.7181 | 0.6263 | 0.0650 | 0.1438 |
| f1_desk（静·TUM） | 0.7379 | **0.2337** | 0.1860 | 0.6860 | 0.6341 | 0.1131 | 0.0450 |
| f3_office（静·TUM） | 0.8325 | 0.2634 | 0.1113 | 0.6817 | 0.6653 | 0.1283 | 0.0248 |
| f2_xyz（静·TUM） | 0.6951 | 0.2195 | 0.0501 | 0.7572 | 0.5956 | 0.0216 | 0.1102 |

三条可直接引用的读数：

1. **f3_wk_hf（动）0.6657 ≈ f3_st_hf（静）0.6694** —— 同数据集内动静完全重合。
2. **f1_desk（静）g_mean 0.2337 == f3_wk_hf（动）g_mean 0.2341** —— 数值上不可分。
3. Bonn 序列的 `flow_valid` 帧内 sd 只有 **0.010–0.022** ⇒ 它在一个 run 内几乎是常数，**没有可用于逐帧路由的动态范围**。

帧级 AUC（§1 A-2）：`flow_valid` 0.463 / `g_mean` 0.586 / `e_flow` 0.538（TUM 内部）。

### 3.2 `mean_s` / `mean_w` 分布与 **`w` 的硬掩码结构**（C1 的核心证据）

P7 全部 arm 的 `min_w`（"max over frames" = 全序列中最大的那一帧的 `min_w`）：

| arm 类型 | 样本 | mean_w | avg min_w | **max over frames of min_w** |
|---|---|---:|---:|---:|
| flow-only | 6 arm（balloon/mv/mv2/pt2） | 0.5674–0.5700 | **0.000000** | **0.000000** |
| geometry-only | 8 arm | 0.5673–0.5698 | **0.000000** | **0.000000** |
| both（默认） | 8 arm | 0.6746–0.6966 | 0.143–0.181 | 0.575–0.606 |

**闭式恒等式验证**（`mean_w = 1 − 0.5·flow_valid_frac`）：

| arm | mean_w | flow_valid | 1−0.5·fv | 残差 |
|---|---:|---:|---:|---:|
| screen_balloon_flow | 0.5700 | 0.8600 | 0.5700 | **+0.00000** |
| screen_mv_no_box_flow | 0.5678 | 0.8644 | 0.5678 | **+0.00000** |
| screen_mv_no_box2_flow | 0.5674 | 0.8651 | 0.5674 | **+0.00000** |
| screen_pt2_flow | 0.5677 | 0.8647 | 0.5677 | **+0.00000** |
| screen_balloon_geo | 0.5698 | 0.8600 | 0.5700 | −0.00017 |
| screen_balloon_on（both） | 0.6781 | 0.8600 | 0.5700 | **+0.10808** |

`both` 是唯一偏离该恒等式的模式，也是唯一 `tau > eps`、`w` 真软的模式。

**exp26 的尺度不变性数值证**（已入档，此处复述作为 C1 的直接依据）：

| 场景 | mean_s | min_s | mean_w | w<0.5 比例 |
|---|---:|---:|---:|---:|
| 纯静态 s∈[0.97,1.00] | 0.9850 | 0.9700 | **0.7438** | **0.1303** |
| 动态 s∈[0.10,1.00] | 0.5502 | 0.1000 | **0.7438** | **0.1303** |

### 3.3 alpha ledger 直方图（C2）

`r2_p02_e2.md` 附表（修好后的诊断 run，150 帧）：

| 量 | 修前 | **修后** |
|---|---|---:|
| `ev_valid_frac` | 0.067 → 0.0002（衰减） | **0.85**（稳定） |
| `updated` | 183 → 1 | **10 010 – 15 841** |
| `obs_max` | 1 | **11** |
| `obs_ge_min`（carve 持久性门） | 0 | **13 795** |
| `a_min` | 0.6300 | **0.2592**（已过 `tau_reset`=0.35，未过 `tau_carve`=0.20） |
| `alpha-exit` | `reset 0, carved 0` 每 KF | `reset 250/179/97/126/96`，**`carved` 恒 0** |

⇒ 直方图直接显示：**持久性门是敞开的（13 795），alpha 门是关闭的（`a_min`=0.2592 > 0.20）**。C2 打的是敞开的那道门。

### 3.4 P7 cue-split ATE（A 的效应上界）

| 序列 | OFF | BOTH | FLOW-ONLY | GEOMETRY-ONLY | 最优 |
|---|---:|---:|---:|---:|---|
| balloon | 13.78±5.97 | 13.85±0.58 | 13.96±0.88 | **12.25±1.51** | geo |
| mv_no_box | 6.56±4.50 | **2.86±0.27** | 4.12±0.60 | 3.70±0.68 | **both** |
| mv_no_box2 | 6.08±0.35 | 5.67±0.33 | 5.58±0.36 | **4.88±0.05** | geo |
| pt2 | 10.91±0.52 | 9.18±1.12 | 10.04±0.87 | **8.78±0.43** | geo |

**A 的效应天花板**：一个完美 oracle 选择器（每序列取最优臂）相对固定 `both` 的收益 = balloon −11.5%、mv_no_box 0%、mv_no_box2 −13.9%、pt2 −4.4%。**平均约 −7.5%，且已含 mv_no_box 的 0**。任何实际选择器都在此之下 —— 这个上界应该在立项前就摆出来。

---

## 4. 修正后的落地计划

> 排序原则：先做能**独立判死/判活**且不污染其他项的。C1 是 B 的前置依赖（§1 B-4）。
> 每个 milestone 都遵守：新键默认关闭 ⇒ 关闭时逐字节回退到当前 `ours-v3`。

### M0 — 前置探针（零 GPU 批量，本地 2060，~1h）

- **改动范围**：新增 `scripts/probe_d_quantiles.py`（~120 行）。复用 `utils/reliability_signal.compute_reliability_tracking_weight` 与 `scripts/probe_reliability_floor.frame_static_flow`，不改在线代码。
- **config 键**：无。
- **产出**：逐像素 `d` 的 p50/p90/p99 **在 `both` 模式下**的真实分位（本次尽调只测到 flow 通道；`v·g` 需要 render，故需要一次 GPU 重渲）。同时补 WP-F 执行卡 §10.1 欠的 per-pixel 分离度。
- **判决**：`both` 模式 `median(d)` 是否 > 0（预期是，由 `min_w`=0.14–0.18 反推）。若 `median(d)` 也是 0，C1 的 floor 语义要重新设计。
- **回滚点**：纯新增脚本，无回滚需求。

### M1 — C1 `tau_floor`（最小、最干净）

- **改动范围**：`utils/reliability_signal.py::cauchy_tracking_weight`（`:448–467`，**+3 行**：签名加 `tau_floor: float = 0.0`，`:465` 后加 `if tau_floor > 0: tau = torch.clamp(tau, min=float(tau_floor))`）；`compute_reliability_tracking_weight`（`:603–670`，+2 行透传）；`utils/slam_frontend.py:1119–1139`（+1 行读 config）。
- **config 键**：`ReliabilitySignal.tau_floor`（默认 **0.0** ⇒ `if tau_floor>0` 跳过 ⇒ 逐字节回退）。写法照抄 `robust_anomaly:116–117`。
- **单元测试**（新增 `tests/test_reliability_tau_floor.py`，复用现有 pytest）：
  1. `tau_floor=0` 与不传参数逐值相等（byte-identical 守卫）；
  2. **no-harm 判据**：`s` 全为 `1−ε`（`ε=1e-3`）时，`floor=0` 给出 `mean_w≈0.74`，`floor=0.25` 给出 `mean_w>0.99`；
  3. **单线索退化判据**：`mode="flow-only"` 时 `floor=0` 的 `min_w==0.0` 而 `floor=0.25` 的 `min_w>0`（钉住 §1 C1-5 的语义变更，防止它被静默引入）；
  4. mover 仍被压制：注入 mover 块后 `mean_w(mover) < mean_w(background)` 在所有 floor 下成立。
- **消融最小集合**：`{0.0(control), 0.15, 0.25, 0.35, 0.50}` × `{f3_st_hf, f2_xyz, balloon, mv_no_box}` × 3 seed = **60 run**。先跑 n=2 筛选（40 run）再补 n=3（沿用 P9 的规矩 —— 该规矩在 P9 里直接接住了 `−DynKF` 的假阳性）。
- **判决序列与阈值**（**不含 ATE 改善**，见 §1 C1-4）：
  - **主判据（不变式修复）**：静态 `{f3_st_hf, f2_xyz}` 的 run 级 `mean_mean_w` ≥ **0.85**（当前 0.596–0.626）；
  - **护栏（不伤动态）**：`{balloon, mv_no_box}` 的 3-seed mean ATE 相对 `floor=0` 劣化 **≤ 5%**；
  - **反向护栏**：静态 ATE 不得劣化 > 5%（预期无变化 —— w≡1 臂已证下权重与静态崩溃无因果）。
  - 选最小的满足主判据且过两条护栏的 floor。
- **风险与回滚**：唯一风险是 §1 C1-5 的 P7 语义变更。回滚 = `tau_floor` 恢复 0.0（单键）。

### M2 — B 的第一步：锚点持久化 + 只读探针（**不改任何决策**）

- **改动范围**：`utils/slam_frontend.py` freeze 块（`:1119–1206`，**+~8 行**）把锚点统计量挂到 `self`（`w_map`/`s_map` 的锚点存活率与残差中位数，**不存整张图**，避免每帧 CUDA 张量驻留）；`reliability_frames_fields`（`utils/slam_frontend.py:142–147`）自动吸收新列，无需改 CSV writer。
- **config 键**：`DynamicKeyframe.anchor_probe`（默认 **false**）。只读，**不参与 `_dynamic_crisis_keyframe` 的返回值**。
- **单元测试**：`tests/test_reliability_frames_provenance.py` 已有的 provenance 模式扩展一条 —— 探针关闭时 `frames.csv` 列集合与旧 run 完全一致。
- **产出**：在**已有的**判决序列上跑 `{f3_st_hf, balloon}` × 1 seed = 2 run，得到"锚点存活率/残差 EMA"的真实时间序列。
- **判决**：锚点量在 f3_st_hf 的 **frame 371** 附近是否有可见拐点。**这是 B 的生死门** —— 若锚点在崩溃点前无信号，B 的触发假设当场判负，省下 M3 的全部 GPU。
- **风险与回滚**：只读，回滚 = 关键。

### M3 — B 的第二步：锚点触发（仅在 M2 判活后执行）

- **改动范围**：`utils/slam_frontend.py::_dynamic_crisis_keyframe`（`:1543–1591`，**+~20 行**新增第四条触发，置于 `gap_cap` 之前）；新增 ring buffer 状态（`FrontEnd.__init__` 附近 `:256` 一带，+3 行）。
- **config 键**（全部默认缺省 ⇒ 触发不存在 ⇒ 逐字节回退）：
  `DynamicKeyframe.anchor_survival_drop`（存活率相对基线的骤降比例）、`anchor_residual_rise`（残差 EMA 相对上升比例）、`anchor_warmup_frames`（冷启动 N 帧内不触发）、`anchor_history`（**ring buffer** 长度）。
  **历史中值用 ring buffer 而非 EMA**：EMA 的时间常数会把"骤降"抹平，且 exp26 的教训是 f3_st_hf 是**离散**失败（frame 371 一步翻倍），需要能分辨阶跃的统计量。
  `kf_budget` 复用现有实现（`:1559–1561`）作为过密插帧的硬上限。
- **消融最小集合**：`{anchor-only, gap_cap-only(control), anchor+gap_cap, DynKF-off}` × `{f3_st_hf, f2_xyz, balloon, mv_no_box}` × 3 seed = **48 run**。
- **判决序列与阈值**：
  - **f3_st_hf（主判据，静态 no-harm）**：逃逸率（ATE < 5 cm）相对 control **0/9** 显著提升，目标向 vanilla 的 **4/5** 靠拢；同时报 KF 数（control 215、−DynKF 57）。
  - **balloon / mv_no_box（护栏）**：3-seed mean ATE 相对 control 劣化 **≤ 5%**（当前 mask-free 基线 balloon 13.85、mv_no_box 2.86）。
  - **f2_xyz（静态 no-harm 第二证）**：ATE 不劣化 > 5%。
  - **报 KF 数与 FPS**：P9 已证 FPS 不预测结果，但 KF 数是本改造的直接自变量，必须入表。
- **风险与回滚**：①§2-#5 的 causal-twin 配对损失 —— 判据必须写成多 seed 分布比较；②静态误触发 —— 由 `anchor_warmup_frames` + `kf_budget` 兜底；③"过密插帧"的反向风险（触发比 `gap_cap=5` 更频繁）—— `kf_budget` 是硬上限。回滚 = 删四个键。

### M4 —（可选，需架构师决策）C2 的构造性替代

**仅当架构师在 §6 开放问题 5 上选择推进时执行。** C2 原案不实施。

- **改动范围**：`utils/alpha_lifecycle.py`（新增一个纯函数，直接写 `alpha` 而非 `evidence`，~15 行）；`utils/slam_backend.py::_alpha_lifecycle_step`（`:597–620`，+~6 行取 mask 并 sample 到高斯）。
- **config 键**：`AlphaLifecycle.semantic_alpha_override`（默认 **null** ⇒ 不执行）。
- **前置**：必须先把 `AlphaLifecycle` 从 off 打开，即先复现 R2-P02 的 arm D/E —— 这本身是一次独立立项。
- **判决**：`carved > 0` 是否出现（当前恒 0），且 `in_front` 保护住静止的人（用 `dynamic_mask_gtmc` 做 held-out 核对）。

---

## 5. 建议实施顺序与并行度

```
M0 探针 ──► M1 (C1 tau_floor) ──► M2 (B 只读探针) ──► M3 (B 触发)
   │                                    ▲
   └────────────────────────────────────┘
                (M2 的锚点定义依赖 M1 的结论)

A ──► 不进入实施；若必须，先补 WP-F per-pixel 分离度探针（并入 M0）
C2 ──► 不进入实施；等 §6 开放问题 5 的回复
```

**最快出可读判决的**：**M2**。它是只读的、2 个 run、不占批量，却直接判 B 的生死（锚点在 frame 371 前有没有信号）。**建议第一个做的其实是 M2 的探针部分，与 M1 的开发并行**。

**可以并行开发、互不污染的两对**：

- **M1（C1）与 M2（B 探针）可并行开发**：改动文件不重叠（`reliability_signal.py` vs `slam_frontend.py` 的 freeze 块与 KF 决策点），且 M2 是只读的 ⇒ 不改数值。
- **⚠ 但不能在同一个 run 里同时评估**：C1 改 `w` ⇒ 改位姿 ⇒ 改 KF 决策的输入；B 改 KF 数 ⇒ 改后端优化预算 ⇒ 改 `w` 的输入。**两者在系统层耦合**，必须分批跑，判据分开。
- **RNG 污染**：C1 不改 KF 数与高斯数 ⇒ `CounterRNG` 的事件集合不变 ⇒ **C1 的 floor 各臂之间是 causal twin，可配对比较**。B 改 KF 数 ⇒ **不是 twin**，只能走多 seed 分布（§2-#5）。这是两者判据写法必须不同的原因。
- **机器分配建议**：M1 的 60 run 走远程 3090（沿用 P7/P9 的派发路径，注意 rsync 后重指 `datasets/` 软链）；M2 的 2 run 走本地 2060。

---

## 6. 需要架构师回复的开放问题

1. **C1 的判据要不要改成"修复不变式"而非"改善 ATE"？**
   证据：`w≡1` 预注册臂去掉全部下权重后 ATE 仍 35.99、仍崩 371；P9 又证 vanilla 自己 4/5。⇒ 我建议 M1 的主判据写成"静态 `mean_w` ≥ 0.85 + 动态 ATE 不劣化 ≤5%"。**若架构师坚持要 ATE 判据，M1 大概率会判负 —— 但那是判错了对象。** 请确认。

2. **`tau_floor` 是否作用于单线索臂？**（§1 C1-5）
   floor 会把 flow-only / geometry-only 从**硬二值掩码**变成软权重（`min_w` 从恒 0 变成正数），P7 那 24 个 run 的 ATE 都是在硬掩码语义下测的。三个选项：(a) floor 只作用于 `both`，单线索臂冻结在 0；(b) 全局作用，P7 单线索列标注"语义已变，数值不可与旧表并列"；(c) 全局作用并重跑 P7 的 24 个 run（+24 run 成本）。**我倾向 (a)**，因为 P7 是已发布判决的支撑证据。

3. **B 的锚点定义用 `w>0.8` 还是 `s` 的绝对水平？**
   `w>0.8` 在单线索模式下**恰好等于**"残差 ≤ 本帧中位数"的指示函数（实测 `frac(w>0.8)` == `zero-frac`，两者小数点后四位相同），是帧内相对量、帧间不可比 ⇒ "锚点存活率"会被帧内重标定伪造。**我建议锚点定义在 `s` 上，或等 M1 落地后再用 `w`。** 请架构师确认取哪个。

4. **A 是否还有非"线索质量"的路由变量？**
   本项目已在两个独立测量层证否"线索质量 ⇒ 选线索"：像素级 AUC 排序与 ATE 排序不一致（exp22），序列级 person 面积比整族不可分（WP-HS）。separability verdict 的结论是"selector 必须直接以位姿误差为目标"。**若架构师心里的 α_flow 有第三种来源（不是质量代理、也不是序列先验），请明确说明**；否则 A 建议撤案，把预算并入 M1/M3。

5. **C2：是否接受把靶子从 `evidence` 换成 `alpha`（或 `ema_beta`/`tau_carve`），以及是否要复活 `AlphaLifecycle`？**
   实测门算术：`obs_ge_min = 13795`（观察期门**敞开**）、`obs_max = 11`、`a_min = 0.2592`、跨 `tau_carve=0.20` 需 n≥12 ⇒ **C2 原案改的那一项不是绑定约束**。且 `AlphaLifecycle` 在所有主臂上是 off、R2-P02 记 H1 证伪。请确认：(a) 换靶子推进；(b) 整体撤案；(c) 先做一次独立的 `AlphaLifecycle` 复活立项再谈。

---

## 附：本报告的可复现口径

- 帧级统计：`results/runs/**/reliability_signal/frames.csv`，181 run；主臂过滤 = 路径含 `maskoff_prune` 或 `mason_combined`。
- 逐像素 `d`（flow 通道）：GT pose + 冻结 RAFT + CPU，复用 `scripts/probe_reliability_floor.frame_static_flow` 与 `utils.reliability_signal.assemble_flow_consensus`，stride 8、每序列 60 帧。**`v·g` 通道未测**（需 GPU 重渲，列为 M0）。
- `tau`/`min_w`/`frac(w>0.8)` 的模式对比：直接调用 shipped 的 `robust_anomaly` / `fuse_static_evidence` / `cauchy_tracking_weight`，合成 240×320 残差场 + mover 块。
- ATE 口径：一律 `tables/tracking_raw.csv` 的 `ate_rmse_cm`（全轨迹），**非** console 的 keyframe RMSE。
