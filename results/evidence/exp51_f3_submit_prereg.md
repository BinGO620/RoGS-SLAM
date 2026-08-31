# EXP51 预注册 — f3_st_hf 静态 ATE 优化：映射预算公平对照（Phase 1）

> **判据与实验矩阵在本文件写死后才可启动 GPU。** 本文件早于任何 EXP51 run 存在。
> 正式数据只使用 3090（远程 jiangwenheng 双卡）；本地 cb(2060) 不做任何判决，
> 只用于代码/配置审计。HEAD 基线 = `bc73eb1a`（三方一致：cb / origin/ours-v3 / 远程）。
> 配置链全部继承自现有已审阅配置（`method_combined_maskoff_prune` / `p9_vanilla`），
> 未改动任何共享 base_config，未改 `gap_cap=5`。

## 0. 动机与背景（不改变判据）

f3_st_hf（freiburg3_sitting_halfsphere）在完整 MRCS 内核下 full-trajectory ATE
从旧主表的 ~2–3 cm 崩到 **35.6–35.9 cm（mask-free）/ 29.4（combined）**，且 0/5 逃逸。

已查明的根因（exp27 定稿，三层叠加）：
1. f3_st_hf 对 vanilla MonoGS 本身即临界序列（exp26：vanilla 自身 4/5，~20% 失败）；
2. `DynamicKeyframe gap_cap=5` 强插 215 KF × 异步映射预算 `async_iter_per_kf=10` 硬编码
   ⇒ 后端队列塞满、地图长期欠优化；
3. ReliabilitySignal 闭环把"偶尔失败"(1/5) 放大成"必然失败"(5/5)，崩点固定 frame 371。

已有 3090 证据（exp27/p10，`exp27_verdict.md` / `exp27_crossvalidation_update.md`）：
- MRCS + `async_iter_per_kf=50`：**5/5 逃逸，mean≈2.87–2.9 cm**（3090, n=5）
- MRCS + `async_iter_per_kf=150`：1/5，mean≈6.1 cm（过头退化，不作为候选）
- MRCS + `async_iter_per_kf=10`：0/5，mean≈35.9 cm

EXP51 的目标是把"预算修复"从**已有局部验证**升级为**完整、公平、可审计的对照**，
并钉死它究竟是不是 MRCS 独有的增益（用 vanilla+async50 排除预算混杂）。

## 1. 实验矩阵（4 臂 × 3 seed，共 12 run，全部 3090）

| 臂 | 方法内核 | async_iter_per_kf | 目的 |
|---|---|---|---|
| A1 | MRCS（mask-free） | 10 | 失败锚点，确认 35 cm 级退化可复现 |
| A2 | MRCS（mask-free） | 50 | 第一候选修复 |
| B1 | vanilla（四机制全关） | 10 | 原始 baseline |
| B2 | vanilla（四机制全关） | 50 | 排除预算混杂 |

- MRCS = `method_combined_maskoff_prune.yaml`（RobustTracking + DynamicKeyframe gap_cap=5 +
  ReliabilitySignal + DeferredCommit + prune lifecycle，SemanticMask off）。
- vanilla = 与 `p9_vanilla_f3_st_hf.yaml` 一致（四机制全关）。
- 每臂 **3 个 seed（0/1/2）**，至少满足项目"n≥3 才下判决"纪律。
- A2 若在审计后确认与已完成的 P10 3090 结果同代码/同 HEAD，可按"同 seed 复跑"规则复用；
  否则补跑 3 seed，**禁止混合不同代码版本的均值**。

## 2. 主指标与逃逸定义

- **主指标**：full-trajectory ATE，取自 `tables/tracking_raw.csv` 的 `ate_rmse_cm`
  （evo `-a` Horn 口径）。**不用控制台 "RMSE ATE"（那是关键帧口径）。**
- **逃逸** ≡ `ate_rmse_cm < 5.0`（与 P9/exp27 一致）。
- 同时记录：RPE、frame 371 附近误差曲线、实际 KF 数量、每 KF mapping 迭代、在线 FPS、总时长。

## 3. 预注册判据（写死后不改）

### 3.1 A2（MRCS+async50）晋级判据
- **必须**：3 个 seed 全部逃逸（<5 cm），即逃逸率 3/3。
- **目标值**：3-seed mean 落在约 2.9 cm 量级（复现 exp27，不作逐 seed 调参）。
- 否决：任一正式 seed ≥5 cm 或 mean ≥10 cm。

### 3.2 B2（vanilla+async50）的作用（排除预算混杂）
- 若 **B2 逃逸率 ≥ A2 且 B2 mean 不比 A2 差**：async50 是**预算公平/工程修复**，
  **不是 MRCS 算法增益**。此时 A2 只证明 MRCS+async50 恢复了可用性，不得把 async50
  写成 MRCS 的方法贡献；主表仍保留 vanilla 标准臂，补充材料报告预算匹配对照。
- 若 **B2 仍差（如 0/3 或明显差于 A2）**：async50 的收益至少部分是 MRCS 特有，
  视为"修复了 dense-KF 后端饥饿"，A2 可作为一个工作点。

### 3.3 A1 vs B1（锚点有效性）
- 若 A1 未能复现 0/5（即出现逃逸）且 B1 也逃逸：说明 f3_st_hf 双稳态/seed 依赖强，
  记录 3-seed 实际值，不因单轮跳变下结论。

### 3.4 三 seed 一致性门
- 晋级臂 mean 与逐 seed 极差需合理（参考项目方法：同 config 同 seed 地板 ~0.08 cm，
  between-seed 可大）。若 3 seed 极差 > 10 cm（双稳态），该臂标为"不稳定"，
  不据此改方法，需补 seed 或用 exp44 的双稳态处理纪律单列。

## 4. 判定分支（跑完填实测，不改判据）

- **BRANCH-1**：A2 3/3 逃逸 且 B2 差于 A2 ⇒ async50 作为 MRCS 预算修复工作点成立。
  下一步 = Phase 2（固定 async50 下隔离 ReliabilitySignal / DynamicKeyframe）。
- **BRANCH-2**：A2 3/3 逃逸 且 B2 也 3/3 逃逸 ≈ A2 ⇒ async50 是预算公平修复，非 MRCS 贡献。
  下一步 = Phase 2 仍做，但措辞收紧为"恢复 MRCS 到 vanilla 同预算公平性"。
- **BRANCH-3**：A2 未达 3/3 ⇒ async50 在 3090 上不足以保证稳定，需重新审视
  （可能回 Phase 0 审计，或转向 Phase 3 的 cue 问题，不直接改 gap_cap）。
- **BRANCH-4**：A1 与 B1 均大量逃逸 ⇒ f3_st_hf 双稳态强，A1/B1 锚点需补 seed，
  暂不判 BRANCH-1/2。

## 5. 运行与验收

- 正式批次脚本：`scripts/run_exp51_f3_submit_3090.sh`（固定 GPU 0/1 worker；每卡
  同时只允许一个 `slam.py`，避免动态选卡竞态）。
- 运行环境：远程 `/home/jiangwenheng/cron/monogs-ours`，
  `PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python`，
  `MPLBACKEND=Agg`，固定 `CUDA_VISIBLE_DEVICES=0` 或 `1`。
- 正式输出根目录：`results/runs/EXP51/f3_submit_v2/`。
- 每 run 完整 `--eval`（保存 full trajectory + rendering 所需产物）。
- 结果聚合用 `scripts/aggregate_results.py`（每 method/seq/seed 取最新 run）。
- 读数脚本：`scripts/read_exp51_f3_submit.py --root results/runs/EXP51/f3_submit_v2`
  （从 `tracking_raw.csv` 抽取 `ate_rmse_cm` 并核对 3 seed）。

### 首轮调度器异常（不纳入数据）

2026-08-27 首轮 `f3_submit/` 启动时，旧调度器的空匹配计数输出为两个 `0`，导致
A1 seed0/1 短暂同占 GPU 0，随后 A1 seed2/A2 seed1 又被错误并发到同一张卡；所有
这些半成品及其目录均标记为**无效、不纳入 EXP51**。A2 seed0 是唯一先前完整且单独占用
GPU 0 的验证 run（ATE 2.9378 cm），因此只按同配置复用到 `f3_submit_v2/A2_seed0`，
并在 launcher 日志中留痕；其余 11 个正式 run 从 v2 根目录重新串行执行。

## 6. 范围声明

- 本实验**不**改变共享 `tum/base_config.yaml`、不改变 vanilla 默认预算、
  不改变 `DynamicKeyframe gap_cap=5`、不引入任何新算法/selector。
- 只新增实验 overlay + 预注册/证据文档 + 运行脚本，均独立建档，可回滚。
- 论文正文与 18 序列主表在 EXP51 判决前**不改**。

## 7. 配置合同

- `tests/test_exp51_f3_submit_configs.py`（新建）：钉死 4 臂中
  "唯一差异 = 方法开关集 + async_iter_per_kf"，防止继承漂移。
