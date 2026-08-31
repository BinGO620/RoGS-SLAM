# EXP53 预注册 — P11 Phase 2 扩序列泛化 + Combined 臂对照(3090)

> 预注册先于任何 run commit 冻结。本文件所在 commit 派发后才允许 GPU。
> 正式 GPU 仅限 jiangwenheng 双 RTX 3090,每卡固定串行 worker。
> 主指标:完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`(evo `-a` Horn)。

## 1. 目的

EXP52(BRANCH-1)判定 P11(sparse-KF + mask-only)晋级为下一版方法结构候选,
但只测了 2 个序列,且**没有与 Combined 臂(论文主表 mask-ON 全内核)对比**。
本实验回答两个问题:

1. **P11 泛化性**:在更多序列(长静态/全屏动态/动态变体)上是否稳定;
2. **P11 vs Combined**:同 HEAD、同机、同 seed 下,简化的 P11 是否非劣于
   全内核 Combined——直接决定下一版方法结构是"P11 简化主线"还是
   "Combined 保留 + P11 简化变体"。

臂定义(与 EXP52 一致,配置合同由 `tests/test_exp53_configs.py` 钉住):

- **P11** = vanilla KF + SemanticMask(mask_mapping=true, mask_insertion=false)
  + RobustTracking(huber);DynamicKeyframe / ReliabilitySignal OFF。
  复用既有 `configs/rgbd/experiments/p11_maskonly/p11_maskonly_*.yaml`(不改)。
- **C(Combined)** = 主表臂 `method_combined_maskboth_prune.yaml`:
  DynKF(gap_cap=5)+ ReliabilitySignal + DeferredCommit + RT(huber)+ prune
  + SemanticMask(mask_mapping=true, **mask_insertion=true**)。
  新建序列级配置 `configs/rgbd/experiments/exp53_p11phase2/exp53_combined_*.yaml`。
- **预算匹配**:两臂都不设 `Training.async_iter_per_kf` → 同走代码默认 10
  (主表口径;无 starvation 混杂例外见 §7 已知边界)。

## 2. 矩阵(27 run)

| 序列 | 类型 | P11 | C | P11 exp28 锚(旧 HEAD, mean±sd) | 旧主表 C 参考(非同 HEAD) |
|---|---|---|---|---|---|
| balloon | Bonn 动态 | EXP52 复用(3.09±0.14) | ×3 新跑 | 3.18±0.46 | 3.06±0.14 |
| balloon2 | Bonn 动态变体 | ×3 | ×3 | **7.01±0.55** | — |
| crowd2 | Bonn 全屏动态 | ×3 | ×3 | **7.38±0.60** | — |
| mv_no_box | Bonn 动态 | ×3 | ×3 | **3.64±0.10** | 2.66±0.12 |
| f2_xyz | TUM 长静态 3397 帧 | ×3 | ×3 | **1.66±0.04** | 1.93±0.03 |

- seeds **0/1/2**;完整 `--eval`。
- balloon 的 P11 侧复用 EXP52 P11B(同 HEAD 运行时文件 SHA256 经 provenance 链
  等价,EXP52 已建立该复用协议);C 侧 3 run 新跑,凑齐 balloon 头对头。
- 排除:MRCS(mask-free)已由 EXP52 判负,不再进入本矩阵。

## 3. 运行协议

- 远程 jiangwenheng 双 3090,串行 worker(沿用 EXP52 v2 模式):
  - GPU0:f2_xyz P11×3 + f2_xyz C×3(最长序列,~11.5h)
  - GPU1:balloon C×3 + balloon2×6 + crowd2×6 + mv_no_box×6(~11h)
- 派发前检查(runner 内置):远程 tracked HEAD == c544b940、worktree 干净、
  5 序列 flow 预检(parser.n_img == manifest n_frames 且 unique depth stems[1:]
  ⊆ flow stems;f2_xyz 已零 GPU 验证 missing=0,crowd2/balloon2/mv_no_box
  由 runner 现场判)。
- provenance:`results/runs/EXP53/exp53_provenance.json`(运行时文件清单同 EXP52,
  另加 exp53 配置/脚本/预注册)。

## 4. 判据(冻结)

**G0 锚漂移中止门(P11 侧,逐序列)**:
|新 mean − exp28 锚 mean| > max(2 cm, 3×锚 sd) → 该序列停判,先查代码/数据,
不盲目续跑。f2_xyz 锚 sd 0.04 → 门 = 2 cm(取 max);crowd2/balloon2 同理 2 cm。

**G1 P11 泛化稳定**:4 个新序列每个 3/3 seed < 10 cm(exp28 锚最大值 7.93 < 10,
预期可过;过不了即泛化失败)。

**G2 P11 vs C 非劣(逐序列,5 序列含 balloon)**:
- 地板(seq)= max(0.43 cm, 6% × max(P11 mean, C mean))
- 非劣 = P11 mean ≤ C mean + 地板(seq)

**G3 结构判决**:

| 分支 | 条件 | 行动 |
|---|---|---|
| BRANCH-1(P11 主线) | G1 全 PASS 且 P11 非劣于 C 的序列数 ≥ 4/5 | P11 定为下一版方法结构主线;Combined 降级为消融/对照臂 |
| BRANCH-2(Combined 保持) | G1 PASS 且 C 显著优(超地板)的序列 ≥ 2/5 | Combined 保持动态主力;P11 记为等价简化变体,适用域按序列报 |
| BRANCH-3(混合) | 其余组合 | 带数据向用户汇报再定 |
| BRANCH-4(异常) | G0 触发或失败 run > 1 | 停,报告,不判 |

## 5. 效率记录(非门)

每 run:online_fps、num_gaussians(efficiency_raw.csv)、KF 数
(trj_final.json trj_id 长度)。预期:P11 的 KF 数在全部序列上显著低于 C
(sparse vs gap_cap=5 dense)。

## 6. 预算与纪律

- 27 run,~21-22 GPU-h,双卡墙钟 ~11-12h(过夜批);不追加 seed;
  失败 run 原样保留;V100/2060/旧 HEAD 不进正式均值;
  预注册先于 GPU;判决填 `results/evidence/exp53_p11phase2_verdict.md`。

## 7. 已知边界(预注册时声明,不事后补)

1. **Combined@async10 的 starvation 风险**:EXP51 证明 dense-KF 臂在 f3_st_hf 上
   async10 会饿死(35 cm 级),但在本批 5 序列上旧主表数字健康
   (balloon 3.06 / mv_no_box 2.66 / f2_xyz 1.93)。若本批 C 在某序列崩到
   >20 cm 而 P11 正常,判"预算 artifact 嫌疑",单列不进 BRANCH-2 的
   "C 显著优"计数,后续用 async50 单序列小批消歧(非本批)。
2. **crowd2 无 C 侧旧参考**:主表 FULLKERN 重出后有 crowd2 combined 数字,
   但 HEAD/口径与 EXP52 链不可比,只作事后 sanity,不进判据。
3. **exp28 锚为旧 HEAD**:G0 只用它做漂移中止,不做均值比较判据。
