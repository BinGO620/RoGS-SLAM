# WP-A FACTORIAL — 预注册（2026-08-14，CCF-C 整改执行卡 v3）

> **本文件在第一个 run 发出之前 commit。commit 之后，判据、数值界、序列集合与分母一律
> 冻结，不得再改（护栏 6 / 17 / 18）。** 装置实现与排期可现场变通，判据不可。

## 一、靶

审稿意见 R1（后半）：三组件（dense-KF `K` + RobustTracking `R` + Reliability `L`）都是现成
技术，P-B 2×2「逐个关掉都不崩」被解读为**组件冗余而非协同设计**。RT 与 Reliability 从未在
mask-free 骨架上被单独消融过（历史 RT-off 全 flat 是因为语义 mask 在场、把效应吞掉，
P6 已给机制解释）。本实验用全因子回答：三组件在完整配置处是否**联合必要**（局部不可约）。

## 二、因子与恒定量

- 8 格全因子：`K`=`DynamicKeyframe.enabled` / `R`=`RobustTracking.enabled` /
  `L`=`ReliabilitySignal.enabled`；mask-free 全 campaign（`SemanticMask.enabled:false`）。
- 恒定量（8 格全同，`tests/test_wpa_factorial_configs.py` 钉死）：
  `Mapping.lifecycle_mode: prune`、`TriReliability.enabled:false`、window/pose_window、
  densify/prune 全旋钮、`ReliabilitySignal` 非 mode 旋钮、`DeferredCommit` 全部。
- **DeferredCommit 取同一值**：`{enabled:true, reliability_confirm:true}`（8 格同）。
  由于 `reliability_confirm` 的确认路径消费 `reliability_s`（只在 `L=1` 时被 stash），
  `L=0` 时确认自然退化为纯整数 support/contradiction 计数（同一 make-or-break 决策器，
  只是没有 reliability 加权证据）。
  **E0 断言（经 codex 对抗核验，2026-08-14）**：
  - **L=1 确实走加权 C± 路径** —— 逐 KF `reliability_s` 被 stash，`_update_batch` 走
    `use_reliability=True` 分支（`reject = c_minus>=rejecting & c_minus>c_plus`）；
  - **L=0 绝无加权路径** —— `reliability_active` 需 `ReliabilitySignal.enabled`，L=0 永不
    进入 compute 块，`reliability_s` 不 stash，`_reliability_maps` 返回 None →
    `use_reliability=False`，reject 用纯整数 `contradictions`。
  - **因此 L 轴不是 null-vs-null**：prune 模式下 reject 分支确实随 L 改变（加权 C⁻ vs
    整数计数），L=0 是真正的"reliability off"，不是机械失效。
  - **不可写成"L=0/1 行为一致"**：两者 reject 语义不同（这是 L 的机制效应，是本实验要测的，
    不是混杂）。E0 断言的是"L=1 有加权路径 activity / L=0 无"，不是"判定一致"。
  - **8 格全部保留 `reliability_confirm:true`**（不因 L=0 清零）：L 轴完全由
    `ReliabilitySignal.enabled` 驱动，确认配置保持统一。
- 主力配置 = `method_combined_maskoff_prune.yaml` 继承链（P6/P7 同 backbone）。

## 三、序列（5 个，easy→hard；覆盖"基于既有结果挑选"诚实声明的边界）

| 序列 | 类型 | 已知 (P7/P6) | 角色 |
|---|---|---|---|
| `mv_no_box` | 纯物·easy | both 最优 2.86 | 主判据 ① |
| `mv_no_box2` | 纯物复现·easy | geo 最优 4.88 | 主判据 ① |
| `pt2` | 易 person·medium | geo 最优 8.78 | 主判据 ① |
| `balloon` | 混合·medium | geo 最优 12.25 | 主判据 ① |
| `pt1` | 难 person·hard | 边界失效（mask-free 32） | 主判据 ①（C3 新增） |

- **不含 walking/crowd**（写进 limitation）：mask-free 下它们 26–66 cm，8 格多数会
  catastrophic，无法稳定估计组件效应。因此本实验结论**显式限定为"非 catastrophic regime"**
  且**不得外推**；且因序列是基于已知非 catastrophic 结果挑选的，作用域只能写成
  "本研究的这 5 个序列上"，不得包装成原则性判据。

## 四、规模与排期

- 8 格 × 5 序列 × 3 seed = **120 run**，全部同 campaign 重跑，不借 P6/P7 的行。
- 基准吞吐 ~25-30 min/run，双卡各 1 并发 ≈ 4 run/h ⇒ 120 run ≈ 30h 双 3090。
- seed0 tranche = 40 run ≈ 10h（screening，**不下判决**）→ G1–G5 全绿 → seeds1/2。

## 五、闸门（每 run 必过）

- **G1 自跟踪**：`Oracle.pose_file` 空、`gt_pose` off、cam lr > 0。
- **G2 旋钮 live**：从 run 自 dump 的 `config.yml` 读回三布尔，与臂名一致。
- **G3 activity 闸**（最重要）：开的机制必须有 console 证据（dense-KF `gap_cap` 触发计数 /
  huber 生效 / Reliability 逐 KF 权重统计）；关的必须没有。无证据 = 作废重跑。
- **G4 ATE 口径**：只读 `tables/tracking_raw.csv` 的 `ate_rmse_cm`；不 grep console。
- **G5 provenance**：每个 run 落 commit hash + config checksum（见 §六.6）。

## 六、读出：三层指标（C4 修正 —— 失败是证据，不是缺失数据）

**禁止**：ATE 截断上限、因基线崩溃删序列、事后改 `≥N/M` 规则的分母。每个 (臂, 序列)
报告三层，缺一不可：

| 层 | 指标 | 定义（跑前钉死） |
|---|---|---|
| **L1 完成率** | `completion = 完成的 seed 数 / 3` | 「完成」= `tracking_raw.csv` 存在 **且** `trj_full_final` 帧数 ≥ **数据集总帧数×95%**（`trj_full_final` = run 输出目录 `plot/trj_full_final.json`，帧数 = `len(trj_gt)`；数据集总帧 = 该序 `depth/*.png` 数，与 loader 的 `len(self.depth_paths)` 一致） |
| **L2 条件 ATE** | `mean ± sd`，仅在完成的 seed 上 | 必须与 L1 并列呈现；单独引用 L2 视为违规 |
| **L3 轨迹覆盖** | `evaluated_frames / total_frames` | 防"截断轨迹换低 ATE" |

**配对规则**：任何两格对比只在双方共同完成的 seed 上配对，令 `k = |completed(A)∩completed(B)|`：

| k | 处置 |
|---|---|
| **3** | 正常判决 |
| **2** | descriptive only —— 可报数，**不得**用于 A1 的"通过"计数 |
| **≤1** | 该对比标记 **UNRESOLVED** |

**UNRESOLVED 与分母**：分母固定为 **5 个序列**，UNRESOLVED 一律计为"未通过"（保守）。
任何情况下不得把序列移出分母。基线 `K0R0L0` 若在某序列 `completion < 2/3`，该序列保留
并单独成段报告（"最弱骨架在此序列不可用"本身是结果）。

## 七、判定：局部不可约性（C1 修正 + round-2 收紧）

弃用 `S = G(111) − [G(100)+G(010)+G(001)]`（混杂二/三阶交互）。Δ 直接定义（不经 G、
不出现 `000` 分母）：

```
Δ_K(s) = log( ATE(K0R1L1, s) / ATE(K1R1L1, s) )    # R、L 在场时，去掉 K 的代价
Δ_R(s) = log( ATE(K1R0L1, s) / ATE(K1R1L1, s) )    # K、L 在场时，去掉 R 的代价
Δ_L(s) = log( ATE(K1R1L0, s) / ATE(K1R1L1, s) )    # K、R 在场时，去掉 L 的代价
```

- **Δ 度量的是"在完整配置处逐个剔除的条件效应"= 局部不可约性（local irreducibility
  at K1R1L1）**，不是三阶协同，也不能推出"三组件构成不可分整体"。
- **实际效应界 `ε=0.10`**（log 尺度 ≈10.5% ATE 比值）。依据 = 项目历史 3-seed 相对 sd 跨度
  1–12%（P7：mv_no_box2 geo 1%、balloon both 4%、pt2 both 12%），取上端附近。
  **`ε` 是实践相关性阈值，不是统计等价界** —— 论文如此标注。
- Δ 判"正 / 负 / ≈0 / mixed"：见 readout 实现（k=3 同号 + mean 超界）。

**A1 逐序列联合通过**：同一序列上 Δ_K、Δ_R、Δ_L 三者同时判"正" ⇒ 计数；这样的序列
**≥ 4/5**（分母固定 5，UNRESOLVED 计未通过）。

| 分支 | 条件 | 后果 |
|---|---|---|
| **A1 局部不可约** | 同一序列三 Δ 全正 ≥ 4/5 | 组件冗余指控被驳回；按 C2 只支持 **integration/system-design 贡献** |
| **A2 部分冗余** | 某 Δ 在 ≥3/5 序列判 ≈0 | 贡献收窄到 necessary subset |
| **A3 单因子主导/加性** | 某单因子在 ≥3/5 拿到 ≥70% `G(K1R1L1)`，或三 Δ 全 ≈0 | "内核"叙事死 → empirical-study |
| **A4 序列相关** | 分支跨序列不一致 | 逐序列报，叙事 = regime-dependent |
| **A5 负交互** | 某 Δ 在 ≥2/5 判负 | 该组件在 regime 有害 → 从 necessary subset 剔除 |

分支判定顺序 **A5 → A3 → A1 → A2 → A4**。A3 的 `G(K1R1L1)` 依赖 `K0R0L0`；若基线某序列
`completion<2/3`，该序列 A1/A2/A5 可判、A3 不可判 ⇒ A3 计数分母改为"基线可用序列数"并
在表中显式标注（唯一允许的分母差异，构造性的、跑前已声明）。

**不能写的**：不得因 A2/A3 说"方法无效"（`G(K1R1L1)` 相对 vanilla 3.6–4.4× 是独立事实）；
不得声称"超加性协同"或"不可分整体"；作用域只能写"这 5 个序列"。

## 八、E0 装置自证（0 GPU，发第一个 run 前）

1. **完整协议（P7 同款，无 `--fast`）**：本 campaign 用无 `--fast` 的完整 eval 协议，与 P7
   逐协议对齐（P7 无 `--fast`，120-run 已验证路径）。`tracking_raw.csv`（`save_final_tracking_raw`，
   硬编码写 `plot/trj_full_final.json`）与 `plot/trj_full_final.json` 均写；`trj_gt` 帧数 =
   数据集总帧数（已完成 P7 geo 实测 778/778）。因此完成率闸门的轨迹源可用，无需 fast 一致性自证。
2. **L=0/1 activity 闸（非"判定一致"）**：dry-run 实测 —— L=1 run 的 `deferred_commit_summary.json`
   / console 必须出现加权 C± 路径 activity（`use_reliability=True`），L=0 run 必须为
   纯整数（无 reliability 加权）。两者 reject 语义不同是 L 的机制效应（本实验要测的），
   不是混杂；E0 只断言"L=1 有加权路径 / L=0 无"。若不满足 ⇒ 8 格全部
   `DeferredCommit.enabled:false` 重跑，并记录 `K1R1L1` 不再逐位等于 P6 mask-free（需重跑锚）。
3. **pytest** `tests/test_wpa_factorial_configs.py` 全绿（7 tests）。
4. **flow 前置**（护栏 17）：§九 的 flow 检查已通过（已在本文件 commit 前做）。

### E0 dry-run 实测（2026-08-14，mv_no_box，seed0，PASS）

| 项 | L=ON 臂（K1R1L1） | L=OFF 臂（K1R1L0） |
|---|---|---|
| tracking_raw | 有，ate=2.83 | 有，ate=3.75 |
| trj_full_final 帧数 | **778/778（100% ≥95% 闸）** | **778/778（100%）** |
| deferred_commit_summary | 有（promoted=132859, rejected=20688, expired=596964） | 有（promoted=571018, rejected=70763, expired=120902） |
| reliability_signal 目录 | 有（逐帧 frames.csv） | **无（0 文件）** —— L=0 绝不 stash reliability_s |
| console reliability 引用 | 非 0 | **0** |

**裁决**：E0 通过 ——
- **L 轴不是 null-vs-null**：L=ON 走加权 C± reject（有 `reliability_signal` 逐帧输出、promoted/rejected 配置明显不同），L=OFF 走纯整数 reject（无 reliability_signal 目录、无 console reliability 引用）。两者 reject 语义确实不同 = L 的机制效应，正是本实验要测的。
- 完整协议均写 tracking_raw + trj_full_final，完成率闸门的轨迹源可用。
- **可以安全起跑全 batch。**

WP-A 5 序列 `flow_raft/` 均有文件：balloon 438 / balloon2 468 / mv_no_box 777 /
mv_no_box2 930 / pt1 579 / pt2 566。无需重建。

## 十、provenance / 异常策略（护栏 15/16）
- 每个 run 输出目录落 `commit hash` + `config.yml`（由 slam.py 自 dump）；readout 从
  `config.yml` 读回三布尔核验（G2）。
- timeout：单 run > 90 min 视为 hang，kill 重排。OOM 重试 ≤2 次。输出目录冲突：新建
  递增时间戳子目录（MonoGS 默认）。断点续跑：`--resume`。损坏输出（`tracking_raw.csv`
  缺失 / `trj_full_final` 缺失 / config 校验和不符）→ 作废该 (seq,arm,seed) 重跑。
- 跨本地/远程改码期间两端 revision 可能分叉：移动代码前先确认两端 HEAD 同步。

## 十一、文档同步（出判决后立刻）

- [ ] `results/evidence/wpa_factorial_verdict.md`（本读出 + 分支 + 一句经验）
- [ ] `our_method/03-results.md` 加一行裁决
- [ ] `our_method/02-method.md` / `ours-method.md` Active Plan 状态区更新
- [ ] 会话末重写 NEXT_SESSION_PROMPT.md

---
**§v3 预注册定稿：2026-08-14。判据冻结。**
