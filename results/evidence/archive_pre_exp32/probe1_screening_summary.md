# PROBE1 Screening Summary (2026-07-21, RTX 2060, seed 0, --fast)

> 固化快照:今日 probe1 探针链全部原始数字。此文件 git-tracked,不随 `results/runs/` 清理丢失。
> 权威登记见 `results/registry.csv`(PROBE1-C / PROBE1-CPRIME / PROBE1-X)。
> 性质:单 seed、2060、fast 模式的 **screening**,不是论文级证据。

## 1. 诊断链 D0-D5 — 定位 C(V1 参照)在 f2_xyz 的漂移元凶

单模块移除法(single-removal attribution),序列 f2_xyz,seed 0:

| 探针 | 配置 | ATE (cm) | 含义 |
|---|---|---|---|
| D0_vanilla | 纯 MonoGS | 1.807 | 基座正常 |
| D1_no_robust | C 去掉 robust | 10.5646 | — |
| D2_no_dynkf | C 去掉 DynamicKeyframe | 9.9039 | — |
| D3_no_mask | C 去掉 mask | 9.8155 | — |
| D4_training_vanilla | C 训练配置 8-3 | 9.0221 | — |
| D5_no_coarseinit | C 去掉 CoarsePoseInit(匀速初始化) | 1.8137 | **漂移消失** |

> 口径注记(2026-07-21 补 D2 行时核实):本表统一用 full-trajectory `ate_rmse_cm`
> (tracking_raw.csv)。D2 的 console 尾部 `RMSE ATE [m] 0.072524` 是 **keyframe 口径**
> (同 run CSV `keyframe_ate_rmse_cm`=7.2524;console 同段 nonKF-RMSE=9.97cm 与 full-traj
> 9.9039 一致)。两种口径下结论相同:D2 ≫ 1.81,dynkf 不是漂移元凶。

结论:C 在 f2_xyz 的漂移(ATE-abort 15.4cm @ frame 1546)唯一元凶 = **CoarsePoseInit 的匀速初始化(const_vel)**。去掉它即恢复到 ~1.81cm。→ C 被证伪,改用 C-prime(C 去掉 CoarsePoseInit)作为参照臂。

> 机理注记(2026-07-22):const_vel 数学上没错,但与 MonoGS 结构不匹配——它喂给的是弱光度 Adam
> refiner(100 iter+early-stop),消不掉累计漂移速度,速度模型再逐帧外推该漂移、关键帧把带偏位姿
> 烤进地图 → 正反馈积分器。慢速长序列(f2_xyz ~2mm/帧 × 3669 帧)主导发作;快速动态序列被真实
> 帧间运动掩蔽(这就是 V1 历史上在动态序列"看着正常"的原因)。设计不匹配而非数值 bug → 处置 =
> 移除,不修补,今后不回收。

## 2. C-prime 参照臂(V1 − CoarsePoseInit)

| 序列 | ATE (cm) | 说明 |
|---|---|---|
| f2_xyz | 1.8257 | 静态,可用 |
| f3_wk_xyz | 3.2879 | 人物动态 |
| person_t | 12.3515 | Bonn 人物动态 |
| person_t2 | 11.3853 | Bonn 人物动态 |

跨 regime 可用作参照臂(screening only,非论文证据)。

## 3. X 臂(C-prime + ReliabilitySignal, flow_scale_floor=2.0)

| 序列 | C-prime (cm) | X (cm) | Δ | Δ% |
|---|---|---|---|---|
| f2_xyz(静态无害门) | 1.8257 | 1.6722 | −0.15 | −8.4% |
| person_t | 12.3515 | 11.9923 | −0.36 | −2.9% |
| person_t2 | 11.3853 | 10.7339 | −0.66 | −5.8% |

### 关键注记

- **f2_xyz 静态无害:覆盖不完整**。该序列预生成光流当初只建了前 499 帧(manifest n_frames=500,开发期 `--max-frames` 截断遗留),reliability 只在前 ~14% 帧真实生效(该段 s≈0.74、w≈0.59、无伤害);其余 ~3170 帧因"缺光流→中性"策略静默跳过、等价 C-prime。→ 覆盖段内无害成立,全长全覆盖验证未做(补全长光流+重跑约 2.5h)。
- **person_t / person_t2:光流全覆盖**(579 / 566 对),是对信号的干净测试。

## 4. 判定(对齐预登记门槛)

预登记门槛:两条 person 都改善 + 至少一条 ≥15% 且 ≥0.5cm + 另一条不退化。

现状:2/2 方向正确(都降),static no-harm 成立,但最大改善仅 5.8%,**未达 ≥15% 门槛**。

**决定:X(当前版 reliability 信号)NOT PROMOTED**。方向对但力度不足;不是崩,也不是有效贡献。真正承重点(deferred vs prune 在 open-set 上的大涨、多 seed)尚未测。

> 根因注记(2026-07-22,代码级复盘):力度不足**不是覆盖问题**(person flow 全覆盖),是 s→w
> 聚合的选择性问题——per-frame `min_s≈0.0001`(逐像素信号确实抓到 mover)但 `min_w≈0.19`
> (聚合把置信度丢了)。两个耦合原因(`utils/reliability_signal.py`):① 帧自适应 Cauchy
> `tau=median(d)+1.4826·MAD` 被静态多数(~94%)主导,~6% 的 mover 永远推不动自己的膝点,信号
> 自平坦化(这也是调 `flow_scale_floor` 无效的原因——Cauchy 会重新归一化掉);② `g` 的 ~0.26
> 宽底噪把静态 s 从 ~0.85 稀释到 ~0.67,抬高 median(d) 反哺 ①。改进杠杆(若将来重启):固定/低
> 分位 tau、抬 `geo_scale_floor`,且瞄准 **map admission 路径(C±,headline)而非 person-ATE**
> (该 regime 有可观测性天花板)。本轮不改冻结合同,只留档。
