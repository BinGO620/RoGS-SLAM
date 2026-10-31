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

## 冒烟 A/B 补记

（执行时填写：RoGS-Densify 同款流程，裁剪仓 vs monogs-ours@31b0f0367 纯净参照，
config `configs/experiments/combined_prune/balloon.yaml`，--max-frames 40 --seed 0。）
