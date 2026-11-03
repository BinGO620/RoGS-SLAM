# PROVENANCE — 本仓库与 monogs-ours 的对应关系

- **源**：`/data/monogs-ours` @ `31b0f03670a4366e8c6a5a7012963962a8203663`（分支
  `feat/bpw-densification`）。monogs-ours 不拆分、不修改，作为备份库。
- **构建方式**：按 manifest 复制（代码自 RoGS-Densify 同源裁剪状态起步 = 已含论文2
  机制的减法）→ 论文1 增量减法（删致密化机制）→ 换配置/判据件 → 验证。
- **旧仓库历史**：本仓库原 main（2 commits，2026-09 开源快照）已打 tag
  `legacy-20261031` 并推送远程，未丢失。

## 组织原则

同 RoGS-Densify/PROVENANCE.md（减法不改名、显式清单、主干同源、继承显式化、
判据件同仓）。本仓库的「本论文代码」= 论文1 四组件（K/R/L/D + 语义掩码），全部位于
主干开关集内、`combined_prune/method.yaml` 默认开启，无独立新文件。

## 对主干文件的修改（相对 RoGS-Densify 同源状态，即 monogs-ours@31b0f0367 减论文2 后）

目的：移除论文3（致密化）机制的文件与接线。论文1 配置下所有向量选点分支均不激活，
else 分支返回 (None, None) → 标量路径；手术等价于恒走标量路径，主线行为不变。

### utils/slam_backend.py

| 源行号（RoGS-Densify 状态） | 删除内容 |
|---|---|
| 145–159 | `selective_densification`/`densification_selection` import |
| 356–364 | FDose 事件序数 reset（`_fdose_event_idx`/`_fdose_ordinal_must_be_zero`） |
| 406–445 | init 站点向量 dispatch（bpw/cgb/fdose/else）→ 换纯标量 `densify_and_prune` |
| 798–822 | selective residual-EMA ledger 块（含 `update_static_prob_from_evidence` 调用） |
| 829–873 | map 站点向量 dispatch + `log_sel_dens_state` → 换纯标量 `densify_and_prune` |
| 160–163 | `static_prob` 两函数 import（随 ledger 块删除；模块与 `static_prob` 张量字段保留） |

### 删除的模块（2 个，论文3 专属）

`utils/{densification_selection, selective_densification}.py`
（它们在 RoGS-Densify 仓库中保留。）

## 判据件（results/）

- `results/evidence/`：自 `biyelunwen/01_small_papers/MMM2027/deliverable/evidence/`
  原样复制（table1_18seq_ate、wpa_factorial、p7_cuesplit 等 9 件）+ 本仓库新增
  `verify_table1.py`。
- `results/runs/P6/`：自 `/data/archive/monogs-ours-results-archive-20260901.tar`
  提取（`results/runs/` 与 `results/runs_remote_cache/` 两处，P6 家族 8 子族 111+ run），
  仅判据小件；**丢弃** `plot/trj_final.json`/`trj_full_final.json`（221MB 过程件，
  ATE 数字以 tracking_raw.csv/per_frame_ape.csv 为准，trj 可按 config 重跑再生）。
- 归档中不存在 vanilla/rgd 列的 run 工件（ MonaGS 原版与对照方法非本组代码产出），
  两列数字以 evidence CSV 为准，verify_table1.py 逐格如实标注。

## 验证记录

| 项 | 结果 |
|---|---|
| AST import 闭包 | 64 文件，无缺失 |
| `py_compile` slam.py / slam_frontend.py / slam_backend.py | 通过 |
| `pytest tests/test_config_valid.py` | 9 passed（全 18 序列配置继承链有效） |
| Table 1 重算核对 | **28 格 MATCH（含 combined+maskfree 两列全部可核格）**，44 格 NO-RUN-IN-REPO（如实标注） |
| submodule pin | `diff-gaussian-rasterization@43e21bff`、`simple-knn@44f764299` |
| 2060 冒烟 A/B（40 帧，combined/balloon，seed 0） | 见下方补记 |

## 数字验证矩阵（Table 1，工具 = results/evidence/verify_table1.py）

数据源 = 仓内全部 run 判据件（tar 归档 P6 八族 + git tag mmm2027-submission 的
runs/WPB 与 P6 补件，254 个 tracking_raw.csv）；匹配 = 序列名正则 + mean/std 双窗口，
支持跨族合并（论文批次有跨族补种子历史，如 balloon/maskfree 的 3 seeds 分属
P6-MASKOFF 与 P6-MASKOFF-3SEED）。

| 列 | 逐位重算 | 状态 |
|---|---|---|
| **maskfree** | **18/18** | 全命中（含跨族合并 3 格） |
| **combined** | **13/18** | TUM 10 + crowd/crowd2/pt1 命中；**BONN 5 格缺口**（balloon 3.06 / balloon2 5.28 / mv_no_box 2.66 / mv_no_box2 5.14 / pt2 10.44）——论文那批 run 工件不在 tar 与 tag（最接近候选 = WPB-CONFIRM 因子批 K1R1L1，均值差 0.2–1.4，非同批）→ **待查 3090 /mnt/app 工件或重跑** |
| vanilla（MonoGS） | 1/18 | 外部方法列，本组代码不产出，run 工件预期不在归档；数字以 evidence CSV 为准 |
| rgd | 0/18 | 同上（外部对照方法） |

**合计 32/72 逐位重算命中；其余 40 格中 35 格属外部方法列（结构性无工件）、5 格登记待补。**
配置同源：47 个 yaml 与 monogs-ours@31b0f0367 逐字节一致（parity check 2026-11-01）。

## 冒烟 A/B 补记

- 设置：`configs/experiments/combined_prune/balloon.yaml`，`--max-frames 40 --seed 0`，
  同机同卡（RTX 2060）各跑一次；参照 = monogs-ours@31b0f0367 纯净代码副本。
- 读数：ATE RMSE 0.7163 vs 0.7386 cm（Δ=0.022cm）、KF-ATE 0.8654 vs 0.9064、
  RPE 1.4673 vs 1.4834。Δ 绝对量低于同配置跨批噪声地板（0.18–0.62cm）约一个量级；
  手术等价性另行核证：被删的 else 分支函数（`compute_per_gaussian_knobs`/
  `log_sel_dens_state`）在禁用时零副作用早退、不消耗 RNG，标量路径逐位一致。
  **判定：PASS（Δ 属重管线的 CUDA 非确定性）。**

## 归档原则（2026-11-04 登记；用户指令，适用于每一个仓库）

- **工作区永远只留最新**：过时的版本/草稿/历史快照一律移入本仓 `archive/`（就近归档，
  命名 `{语义}_{YYYY-MM-DD}`），不散落工作区顶层。
- **归档 ≠ 删除**：归档件是证据键，账本指针不追改；每处归档配 `README.md` 并在仓内
  索引登记。
- **本仓独立性**：实验一律回 monogs-ours 做，本仓只收"已判据确认"的成果快照
  （四步同步见 monogs-ours `/data/master-thesis/WORKFLOW.md`）；本仓自持门禁与
  PROVENANCE，不依赖 monogs-ours 工作区即可复验。
- **里程碑触发同步**：只在判决落地/投稿等里程碑做 manifest 重灌 + gate 全跑 +
  PROVENANCE 登记；平时不同步（避免快照漂移）。
