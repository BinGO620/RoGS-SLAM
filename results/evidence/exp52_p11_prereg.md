# EXP52 预注册 — P11 sparse-KF + mask-only 3090 当前 HEAD 重验 + MRCS+async50 balloon matched 对照

> 预注册先于任何 run commit 冻结。本文件所在 commit 派发后才允许 GPU。
> 正式 GPU 仅限 jiangwenheng 双 RTX 3090,每卡固定串行 worker。
> 主指标:完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`(evo `-a` Horn)。

## 1. 目的

EXP51 判决 §4.5 指定的方向:评估 **P11(sparse-KF + mask-only)** 是否值得作为下一版方法
结构,与 **MRCS+async50** 做跨静态/动态 matched 对照,直接回答
"dense-KF + ReliabilitySignal 是否值得保留"。

- MRCS = mask-free combined 内核(`method_combined_maskoff_prune.yaml`):
  DynamicKeyframe(gap_cap=5)+ ReliabilitySignal + DeferredCommit + RobustTracking(huber)+ prune,
  SemanticMask OFF。
- P11 = vanilla KF + SemanticMask(mask_mapping=true, mask_insertion=false)+
  RobustTracking(huber);DynamicKeyframe / ReliabilitySignal OFF。
  与 WP-M maskonly(exp22 54-run 旧臂)的规格差异恰为 {RobustTracking ON, mask_insertion OFF}。

## 2. 已有证据与数据复用规则

**exp28(2026-08-19)3090 P11 批(锚,非正式判决):**

- 12-run 判据批(远程 `results/runs/P11/P11-MASKONLY-3090`,本轮已核实 12/12 `status=OK`):
  f3_st_hf 3.4618/3.9370/4.7093(mean **4.04±0.63**)、balloon 3.7115/2.8575/2.9787
  (mean **3.18±0.46**)、f2_xyz 1.66±0.04、mv_no_box 3.64±0.10。
- 42-run 主表批(本地 `P11-MAINTABLE-3090`,其余 14 序列 × 3,ALL_DONE missing=0,
  method 字段 `P11-*-sparsemaskonly`)。
- **不能直接当正式判决的原因**:① 当时冻结判据把判决权放在 2060 判决批,该批 12/12 缺
  tracking_raw.csv → UNRESOLVED(`archive_pre_exp32/p11_maskonly_verdict.md`),3090 批按设计
  只是预读;② 运行 HEAD 为 a1b8e6e2 时代,此后运行时代码 +1527 行(§3)。
- 排除:`P11-REMEDIAL-3090` 的 f3_st_hf ×3 method 字段为 `WPM-f3_st_hf-maskonly`,
  是 WP-M 旧臂(RT off / insertion on),不是 P11,任何统计不得混入。

**EXP51 A2(MRCS+async50 f3_st_hf,seed0/1/2 = 2.9378/2.3943/20.2845;6-seed 5/6 逃逸):**

作为本实验 f3_st_hf 侧 MRCS 臂的正式对照,不重跑。依据:
`bc73eb1a..c544b940` 运行时代码零改动(diff 仅文档 + EXP51 工具),EXP52 新增 commit
同样只含文档/配置/脚本/测试;EXP52 runner 的 provenance SHA256 与
`exp51_provenance.json` 采用同一文件清单,判决时逐文件 diff 留档(等价性证据)。

**排除**:chenfan/V100、本地 2060、一切历史不同 HEAD 结果不进 matched 均值
(交接词选项 2 规则)。

## 3. 代码漂移审计(零 GPU,预注册时完成)

`a1b8e6e2..c544b940` 运行时代码 +1527/-7(7 文件)。逐文件确认新增行为全部 default-off:

| 文件 | 增量 | 门(默认值) |
|---|---:|---|
| `utils/mapping_probe.py`(新) | +422 | `MappingProbe.enabled` 默认 False(`mapping_probe_enabled`) |
| `utils/mapping_weight.py`(新) | +336 | `SemanticMask.mapping_ema` 默认 False;`soft_mapping` 默认 False;`mapping_scale_match` 默认 False |
| `utils/slam_backend.py` | +191 | 全部在上述门后(`mapping_probe_enabled` / `mapping_ema.is_enabled`) |
| `utils/slam_frontend.py` | +160 | `DynamicKeyframe.anchor_probe` 默认 False;其余为诊断行读取 |
| `utils/reliability_signal.py` | +212 | `mad_exclusion` 默认 False;`tau_scale` 默认 1.0(no-op);`tau_floor` 默认 0.0 |
| `utils/slam_utils.py` | +157 | `ema_zero_dynamic` / `ema_dynamic_cap` / `ema_mass_matched` 均在 `mapping_ema` 门后 |
| `utils/alpha_lifecycle.py` | +56 | `semantic_alpha_override` 默认 None |

P11 与 MRCS 配置链(§4)均未设置以上任何键 → 当前 HEAD 对两臂的行为应与 exp28 时代等价。
此等价性是**推断**,不是证明:由 G0 异常中止门(§6)兜底。

## 4. 臂定义

配置合同由 `tests/test_exp52_p11_configs.py` 钉住。

| 臂 | 序列 | 配置 | 内容 |
|---|---|---|---|
| P11F | f3_st_hf | `configs/rgbd/experiments/p11_maskonly/p11_maskonly_f3_st_hf.yaml`(复用,不改) | vanilla KF + mask_mapping + huber;DynKF/ReliabilitySignal/mask_insertion OFF |
| P11B | balloon | `configs/rgbd/experiments/p11_maskonly/p11_maskonly_balloon.yaml`(复用,不改) | 同上 |
| M50B | balloon | `configs/rgbd/experiments/exp52_p11/exp52_mrcs_async50_balloon.yaml`(新) | MRCS + `Training.async_iter_per_kf: 50`;method 侧与已验证的 `p10_async50_balloon.yaml` 及 EXP51 A2 逐字节等价(测试断言) |

- seeds **0/1/2**(与 EXP51 同 seed 集,便于跨序列对照)。
- 每 run 完整 `--eval`;P11 臂 `async_iter_per_kf` 走代码默认 10(两臂 config 不设置该键)。
- 不变量:不改 `DynamicKeyframe.gap_cap=5`;不写共享 `tum/bonn base_config.yaml`;
  不改 vanilla 默认;不改 p11_maskonly 既有配置文件。

## 5. 运行协议

- 远程 jiangwenheng 双 3090,`PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python`。
- GPU0 = P11F×3(f3_st_hf,~25-50 min/run);GPU1 = P11B×3 + M50B×3(balloon,~20-45 min/run)。
  每卡固定串行 worker,墙钟预计 ~2.5-3.5h。
- 派发前检查(runner 内置):远程 HEAD == EXPECTED_HEAD、tracked worktree 干净、
  关键文件存在;flow 预检按 TUMParser frame-stem 口径对 f3_st_hf 与 balloon 各跑一次
  (parser 帧数 == manifest n_frames 且 runtime depth stems[1:] ⊆ flow stems)。
  MRCS 臂另有 `assert_reliability_flow_available` 硬门兜底(exp23 教训)。
- provenance:`results/runs/EXP52/exp52_provenance.json`,sha256 文件清单与
  `exp51_provenance.json` 相同(4 运行时文件)+ EXP52 配置链 + 脚本/测试/预注册。

## 6. 判据(冻结,四分支)

**G0 异常中止门**:P11F/P11B 新 3-seed mean 与 exp28 锚(4.04 / 3.18)的偏移
\> max(3× 历史 sd, 2 cm)(即两序列均为 > 2 cm)→ **停**,先查代码漂移,不续跑、不改判据。

**G1 静态稳定**:P11F 3/3 seed full-traj ATE < 10 cm(exp28 冻结判据)。
逃逸(< 5 cm)计数与 EXP51 A2(2/3,主矩阵)描述性对照。

**G2 动态增益**:P11B 3-seed mean ≤ 19.2 cm(= vanilla 38.35 的一半,exp28 冻结判据)。

**G3 结构对照**:
- 主对照(balloon):P11B vs M50B 3-seed mean。判定地板 = max(0.43 cm(exp39 balloon
  噪声地板), 两臂较大均值的 6%)。P11B 不劣 = P11B mean ≤ M50B mean + 地板。
- 副对照(f3_st_hf,描述性):P11F 逃逸计数 vs A2 主矩阵 2/3(该序列已知运行级双稳态,
  不做均值比较);P11F 逃逸 ≥ 2/3 记"稳定性不劣"。

**分支判决:**

| 分支 | 条件 | 行动 |
|---|---|---|
| BRANCH-1(P11 晋级) | G1 PASS 且 G2 PASS 且 balloon G3 中 P11B 不劣 且 P11F 逃逸 ≥ 2/3 | P11 升级为下一版方法结构候选;Phase 2 扩序列另行预注册(其余 14 序列有 exp28 旧锚) |
| BRANCH-2(MRCS 保持) | balloon G3 中 M50B 显著优于 P11B(差 > 地板),或 G1/G2 FAIL | async50+MRCS 保持主线,P11 归档为消融/替代臂 |
| BRANCH-3(不可分辨) | balloon 两侧差 < 地板 且 G1/G2 PASS | 在位者规则:async50+MRCS 保持主线,P11 记为等价简化替代 |
| BRANCH-4(异常) | G0 触发或 run 大面积失败(rc≠0/OOM > 1) | 停,报告,不判 |

## 7. 效率记录(非门)

每 run 记录:`online_fps`、`num_gaussians`(efficiency_raw.csv)、KF 数
(`plot/trj_final.json` 的 `trj_id` 长度)。P11 预期 KF 数显著低于 M50B
(exp28 锚:balloon P11 ≈ 20,dense gap_cap=5 下更多;f3_st_hf P11 ≈ 60)。

## 8. 预算与纪律

- 9 runs,GPU 墙钟 ~2.5-3.5h;**不追加 seed**;失败 run 原样保留记录,不重跑替换。
- 预注册先于 GPU;原始 9-run 矩阵不替换;V100/2060/旧 HEAD 不进正式均值;
  判决填入 `results/evidence/exp52_p11_verdict.md`(执行读数,不替换本文件的判据)。
