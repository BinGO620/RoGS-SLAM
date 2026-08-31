# `SemanticMask.enabled` 到底打开了几条通道 —— 逐通道代码清单（exp36, 2026-08-21）

> **零 GPU。** 本文件是 exp34/35 那两个判决的**分母审计**：它们把「mask 的增益」
> 定义成 `ATE(maskfree) − ATE(eboth)`，而 `maskfree` 是 `SemanticMask.enabled: false`。
> 那一个开关到底关掉了几样东西？下面逐条用 file:line 点出来，并把**由 config 算术
> 就已经死掉的**通道与**真的活着的**通道分开。
>
> 适用域 = exp34/35/36 这一族臂（`method_combined_maskboth_prune` + T2 overlay）。
> 换 overlay 结论可能变，判据是「解析后的 config + 代码路径」，不是「代码里存在这个分支」。

## 1. 活着的通道（4 条）

| # | 通道 | 门 | 代码位置 | 盘上自证 |
|---|---|---|---|---|
| 1 | **tracking 光度损失的硬 mask** | 只要 `enabled` | mask 算出：`slam_frontend.py:841-853`；并入 `dyn_mask`：`:1125-1129`；喂进损失：`:1309`；分支阶梯：`slam_utils.py:126-153` | 见 §2（只在前 10 次迭代活着） |
| 2 | **mapping/BA 损失的 mask** | `enabled` ∧ `mask_mapping` | `slam_backend.py:371, 422`（**`mask_mapping_enabled` 全仓只有这两个消费点**） | exp34 判决：share_BA 0.44–0.80 |
| 3 | **插入门**（把关键帧深度上的 person 像素置零） | `enabled` ∧ `mask_insertion` | `slam_frontend.py:488-525` | console `Semantic insertion gate` 行数：控制臂 67–151 次、处理臂 0 次 |
| 4 | **T2 的 MAD 排除候选集**（`semantic ∪ e_flow`） | `enabled` ∧ `mad_exclusion` | 传入：`slam_frontend.py:1188`；使用：`reliability_signal.py:806-810` | frames.csv `mad_excl_semantic` = 1（eboth balloon 438/438）；maskfree 里**无该列**、`mad_exclusion` 恒 0（827/827） |

**⇒ `maskfree` 这一格同时关掉了 1、2、3、4 四条，不是只关了 2 和 3。**

## 2. 通道 1 的活性窗口：前 10 次迭代，不是全程

`slam_utils.py:126-153` 的分支阶梯（顺序就是判据）：

```
if 有 soft 权重:                      # reliability 的 (1−w)
    if hard_tracking_mask: hardsoft   # ← 本臂族没设这个开关
    else:                  soft_only  # ← 硬 mask 在这里被完全旁路
elif 有 hard mask:         flow_mask  # ← 硬 mask 唯一真正生效的分支
```

- `reliability_soft` 初值 None（`slam_frontend.py:1040`），在 `tracking_itr >= warmup_iters`
  时才赋值（`:1137-1141`、`:1213`），`warmup_iters: 10`（`configs/rgbd/tum/base_config.yaml:143`）。
- ⇒ **迭代 0–9 走硬 mask 分支，迭代 10 起硬 mask 被旁路**。
- `Training.tracking_itr_num: 100`（同文件 `:295`），但 `slam_frontend.py:1338-1339` 有
  `if converged: break` ⇒ **实际每帧跑了多少次迭代没有落盘**，所以「10/100」只是上界口径，
  真实占比未测。若 exp36 判 TRACKSIDE-MATERIAL，这个占比就变成必须补测的量。
- 盘上自证：frames.csv 的 `tracking_itr` 在 438/438 帧上都等于 10 ⇒ 每帧都跑够了 10 次
  （否则 reliability 不会被计算、该帧不会有行）。
- 边角情形：某帧没有 frozen flow ⇒ `reliability_active=False`（`:1064`）⇒ 该帧**全程**走硬 mask。
  balloon 上 `flow_valid_frac` 均值 0.86、438 帧全有行 ⇒ 这类帧在本批里不是主体。

## 3. 由 config 算术已经死掉的通道（4 条，别再当解释）

| 通道 | 为什么死 | 证据 |
|---|---|---|
| `DynamicKeyframe` 用 `dyn_coverage` 收紧关键帧 | `high_occ = dyn_coverage >= occ_tighten_thresh(2.0)`，而 coverage 是 0–1 的比例 ⇒ **永不可达**；`gap_cap_tight` / `crisis_interval` / `person_mask_ratio_thresh` / `motion_tau_*` 全缺 ⇒ 只剩 mask 无关的 `gap_cap: 5` | `slam_frontend.py:1647-1662`；解析后 `DynamicKeyframe = {enabled, gap_cap: 5, occ_tighten_thresh: 2.0}` |
| BootstrapVO 的 mask | `BootstrapVO.enabled: False` | `slam_frontend.py:644-660`；解析后 config |
| MaskQA（补检测空洞） | `MaskQA.enabled: False` | `slam_frontend.py:855-860` |
| `final_pose_refinement`（离线用 masked loss 重优化非 KF 位姿） | `FinalPoseRefine` 段不存在 ⇒ 默认 off | `slam_frontend.py:1928-1936, 1992` |
| DBA-lite oracle 里的 mask | 只在离线脚本路径 | `dba_lite.py:723` |

（`Results.static_bg_mask_subdir` 的 GTMC mask 不算方法通道：它是 eval 侧的、方法无关的
冻结 mask，四个臂共用同一套支持集。）

## 4. 分母审计：`eboth ↔ maskfree` 还差了一个 T2 机制，量已测出来

`t2_control_maskfree` 除了 `enabled: false`，还带 `mad_exclusion: false`
⇒ 分母里混进了整个 T2 配额机制。**这一项可以零 GPU 定量**，因为 `control_maskon`
（mask-ON + `mad_exclusion: false`）已经有 3 seed：

| 序列 | eboth（T2 开） | control_maskon（T2 关） | 差 | 臂内极差 | 占总效应 |
|---|---:|---:|---:|---:|---:|
| balloon | 3.06 | 3.17 | **0.11** | 0.05 / 0.27 | **1.3%** |
| mv_no_box | 2.76 | 2.82 | 0.06 | 0.14 / 0.22 | 7.4%（但总效应 0.81 本就不可分解） |
| crowd2 | 2.11 | 2.29 | 0.18 | 0.07 / 0.60 | 0.3% |

⇒ **T2 在分母里只值 0.1–0.2 cm，全在臂内极差量级**。exp34/35 的 share 数值不因此改写
（这是本轮**加上**的一条 sensitivity 检查，不是更正）。剩下的分母混淆只有通道 1。

## 5. 三处更正（对上一轮交接与判据本身）

### 5.1 `mask_mapping` **不在前端被消费** ⇒「BA 侧 vs 前端光度」这一刀不存在

`NEXT_SESSION_PROMPT.md`（exp35 交接）§3.1 写：「`mask_mapping` 同时喂 BA 损失和前端
光度残差（`mask_mapping_enabled` 在 backend 与 frontend 两侧都被消费）」，并据此把
下一靶子定为「拆 BA 侧 vs 前端光度」。

**这句是错的。** `mask_mapping_enabled` 全仓只出现 4 次：定义
（`semantic_mask.py:83`）、import（`slam_backend.py:21`）、两个消费点
（`slam_backend.py:371, 422`）。前端一次都没调用；前端的硬 mask 走的是**通道 1**，
由 `enabled` 单独控制，与 `mask_mapping` 无关。

**`mask_mapping` 内部真实存在的那一刀是别的**：`slam_backend.py:518-528` 里
同一次 `loss_mapping` 反传同时喂两个优化器 ——
`gaussians.optimizer.step()`（高斯参数）与 `keyframe_optimizers.step()` +
`update_pose()`（关键帧位姿增量 `cam_rot_delta/cam_trans_delta`）。
⇒ 内部拆刀 = **高斯梯度 vs 关键帧位姿梯度**，需要双 backward（改代码，且改后端
wall-clock ⇒ 异步调度下会污染 ATE），不是改配置。

### 5.2 exp35「残差是通道重叠、不是别处的贡献」**尚未成立**

`insertion_verdict.md` 用它更正了 exp34 的「33–56% 在别处等着」。但**两种读法在同一轮
产物里彼此矛盾**：`scripts/insertion_verdict.py::_decide` 的判决文本写的是
「it can only be in the tracking side. Next target = tracking-side isolation.」

现有四个臂**分辨不了**这两种读法，理由就是 §1：第四格 `maskfree` 连通道 1 一起关了。
⇒ 正确的状态是「**未定**：残差要么是 mapping×insertion 的交互（重叠），要么是通道 1
自己的贡献」。exp36 的 trackside 臂把这段残差做成恰好二分（预注册 §1 的恒等式）。
**exp34 那句「在别处等着」和 exp35 那句「是重叠」都是过度确定，前者方向对但成分未证，
后者把未测的通道当成了不存在。**

### 5.3 可分解性门的「臂内极差」漏掉了处理臂，而处理臂强双稳态

`insertion_channel_prereg.md` §3 的极差 = `max(ptp_eboth, ptp_maskfree)` —— 只有两个
**控制**臂。可分子里的处理臂 `pba_mapping_off` 逐 seed：

| 序列 | 逐 seed ATE | 极差 | 占总效应 |
|---|---|---:|---:|
| balloon | 9.35 / 8.55 / 8.03 | 1.32 | 16% |
| f3_wk_xyz | 6.56 / 9.95 / **23.73** | **17.16** | **71%** |
| pt1 | 16.52 / 33.41 / 36.52 | **20.00** | 85% |

⇒ `share_BA = 0.438`（f3_wk_xyz）与 `0.798`（pt1）**的均值口径不可读**，而 §3 报的
可读地板（0.016 / 0.275）严重低估了噪声 —— 它衡量的是控制臂的稳定性，不是这个 share 的。
CLAUDE.md 早已立过这条规则（mask-free 底座双稳态 ⇒ 用崩溃率口径，不用均值差），
这一轮把它落到判据算术里：**双臂感知地板 `max(ptp_两个被比臂)/总效应` + 逐 seed 配对方向**。

**仍然成立的部分**：balloon 上 `share_BA = 0.672` 的处理臂极差 1.32 < 总效应 8.30 的
1/6，`mask_mapping` 的**必要性**（拆掉它 ATE 从 3.06 → 8.64，9/9 run 无一例外）不依赖
均值口径；受影响的只是「44–80%」这个**份额区间的下界精度**。

## 6. 一句话结论

> `SemanticMask.enabled` 打开的是**四条**通道，exp34/35 只单独翻过其中两条
> （`mask_mapping`、`mask_insertion`），第三条（tracking 侧硬 mask，前 10 次迭代）
> 从未被隔离，第四条（T2 候选集）本轮已测出只值 0.1–0.2 cm。
> 「mapping 既必要又充分」的**必要性**站得住（单变量翻转，9/9），
> **充分性**是「在通道 1 与 4 在场的前提下充分」—— 这个前提在 exp35 的写法里丢了。
