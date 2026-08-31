# 远程代码同步事故 —— 历史批量可信度审计（2026-08-15，exp19）

> **触发**：WP-B E0/pilot 因远程装置未同步而全部作废（见 `wpb_flowmask_pilot_verdict.md §0`）。
> 同一故障类可能悄悄废掉更早的批量，故对**已落判决的历史 campaign 逐一取证**。
> 结论先行：**WP-A（120 run）与 P7（48 run）均通过审计，判决维持有效**；作废的只有 WP-B v1。

## §1 故障类的精确边界

远程 `cron/monogs-ours` 长期处于「HEAD 停在旧 commit + 装置文件手工拷成 untracked」的半同步态。
在这种状态下，一个 campaign 是否被废，**取决于它依赖的代码是新增的还是既有的**：

| 依赖类型 | 后果 | 实例 |
|---|---|---|
| **新增代码**（本次才写、只在未同步的 commit 里） | 配置写了但**无代码消费** → 静默走 fallback，结果无效 | WP-B `flow_threshold`（`slam_frontend.py` 分支整个缺失）→ 实跑 Mask R-CNN |
| **既有代码**（远程旧 HEAD 或工作树已含） | 配置正常被消费 → 结果有效 | WP-A 的 K/R/L；P7 的 `mode`（经 stash 证实当时在工作树） |

**判据**：不能只看"配置对不对"，必须验证**消费该配置的代码当时是否在实跑的工作树里**，
并佐以运行时落盘（config dump + 机制活性 + 臂间效应 vs 种子噪声）。

## §2 WP-A 审计（120 run，全因子 K/R/L）—— **PASS，判决维持**

| 证据 | 结果 |
|---|---|
| **消费代码在场** | `RobustTracking.enabled` → `slam_utils.py:152`（`get_loss_tracking_rgbd_robust`）+ `:197`（huber IRLS 加权）；`DynamicKeyframe` → `slam_frontend.py:212`；`ReliabilitySignal` → `reliability_signal.py`。三者在实跑工作树中**均存在** |
| **配置零漂移** | BROKEN（实跑库）与 origin 提交版比对 `configs/rgbd/experiments/wpa_factorial/` 全部 **48/48 逐字节一致，0 不一致** |
| **运行时 config dump** | 8 臂落盘的 K/R/L 布尔**完全按全因子设计变化**（K0R0L0→false/false/false … K1R1L1→true/true/true） |
| **K 轴机制活性（直接观测）** | 关键帧数 **K=0 → 31 / 24；K=1 → 88 / 88**。dense-KF 按设计生效 |
| **臂间效应 >> 种子噪声** | balloon 3-seed：K0R0L0 `40.7/38.9/35.5`、K1R0L0 `49.3/49.1/47.8`、K0R1L1 `10.7/10.4/12.5`、K1R1L1 `11.8/14.5/14.0`。臂间 3-4×、臂内簇紧 |
| **反向可证伪信号** | K1R0L0（~48.7）**系统性劣于** K0R0L0（~38.4）——"dense-KF 在 balloon 有害"。**惰性机制无法产生跨 3 seed 一致的系统性劣化**，这是机制活着的强证据 |

> 对照 WP-B 失效签名：那里改 `flow_quantile` 全臂跑的是同一个 Mask R-CNN mask，差异纯属非确定性；
> 此处 R 轴单开即把 balloon 从 ~38 拉到 ~19.5，且 3 seed 同向。两者签名截然不同。

## §3 P7 审计（48 run，cue-split）—— **PASS，判决维持**

| 证据 | 结果 |
|---|---|
| **消费代码在场** | `fuse_static_evidence(..., mode)` 含 `both`/`flow-only`/`geometry-only` 三分支（`reliability_signal.py:235-263`），未知 mode **抛异常**（fail-loud，不静默降级） |
| **传参在场（关键）** | 前端 `mode=str(rel_cfg.get("mode","both"))` 当时确在工作树 —— 经 `git stash show -p stash@{0}` 证实（该 overlay 是 exp19 追平远程时才被 stash 收走，**P7 实跑时在场**） |
| **运行时 config dump** | balloon-flow → `mode=flow-only`；balloon-geo → `mode=geometry-only`；balloon-off → `ReliabilitySignal.enabled=false`。配置确实抵达运行时 |

> ⚠ 注意取证顺序陷阱：exp19 在追平远程时对旧库执行过 `git stash`，**旧库工作树已不等于 P7 实跑时的代码**。
> 复核此类历史必须查 stash / reflog，不能直接 grep 当前工作树。

## §4 未受影响项

- **本地 2060 产出**（P2-T 等）：本地库始终 tracked 且 clean，不涉及该故障类。
- **WP-C/WP-D0/WP-F**：零 GPU 或纯离线分析，不依赖远程代码。

## §5 制度性后果（已固化）

1. **发批量前铁律**：`ssh ... 'git fetch origin ours-v3 && git rev-parse HEAD origin/ours-v3'` 两值必须相等，
   否则先 `git merge --ff-only`。**禁止手工 scp/cp 装置文件**——它制造"本地已 commit、远程仍旧码"的假同步。
2. **G3 活性闸升级**：新机制的自证不能只看"配置里写了"，必须给**随参数系统性变化的行为证据**
   （如 WP-B v2：mask coverage 0.248@p80 vs 0.077@p95）。
3. **远程旧库留证**：`cron/monogs-ours-BROKEN` 保留不删，供后续复核。
