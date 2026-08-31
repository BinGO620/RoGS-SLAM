# EXP51 判决 — f3_st_hf 映射预算公平对照（3090）

> 这是 `exp51_f3_submit_prereg.md` 的执行读数与补充稳定性记录。
> 所有正式运行均在 `jiangwenheng` 双 RTX 3090 上完成；chenfan/V100 结果不纳入本文。
> 代码基线为远程运行时 `bc73eb1a`。原始 3-seed 主矩阵不被补充 run 替换。

## 1. 正式预注册矩阵：4 臂 × 3 seed

主指标为完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`（evo `-a` Horn 口径）。逃逸定义为 ATE < 5 cm。

| 臂 | seed0 | seed1 | seed2 | mean (cm) | sample std (cm) | 逃逸 |
|---|---:|---:|---:|---:|---:|---:|
| A1 MRCS + async10 | 35.7712 | 2.6165 | 34.9789 | 24.4555 | 18.9173 | 1/3 |
| A2 MRCS + async50 | 2.9378 | 2.3943 | 20.2845 | 8.5389 | 10.2710 | 2/3 |
| B1 vanilla + async10 | 3.9275 | 2.7707 | 21.8024 | 9.5002 | 10.6697 | 2/3 |
| B2 vanilla + async50 | 2.7513 | 7.1067 | 14.8549 | 8.2376 | 6.1305 | 1/3 |

- 12/12 run `status=OK`，无 OOM 或配置错误。
- A2 async50 在正式 3-seed 上为 **2/3 逃逸**，未达到预注册的 3/3 晋级门。
- 因此预注册分支为 **BRANCH-3**：async50 在本轮 3090 三 seed 上不足以保证稳定；不能直接写入最终主方法或宣称静态修复完成。
- B2 vanilla+async50 反而只有 1/3 逃逸，说明这不是“增加迭代后任何方法都同样稳定”的简单结果；但在双稳态下，3 个 seed 不足以做强的算法增益归因。

## 2. A2 补充 seed：保持原始 seed2，不替换

为检查 A2 的稳定性，追加了三个新 seed；它们使用与 A2 完全相同的配置、3090 环境和 `async_iter_per_kf=50`：

| run | ATE (cm) | RPE (cm) | status |
|---|---:|---:|---|
| A2 seed3 | 2.6827 | 1.2054 | OK |
| A2 seed4 | 2.5928 | 1.0022 | OK |
| A2 seed5 | 3.6271 | 1.2193 | OK |

原始 seed0–5（不含复跑）为：

- `[2.9378, 2.3943, 20.2845, 2.6827, 2.5928, 3.6271]`
- **5/6 逃逸**
- mean = **5.7532 cm**
- sample std = **7.1317 cm**
- median = **2.8103 cm**

这里的均值和标准差必须带上 20.2845 cm 的原始失败值；不能把它事后删除。

## 3. 原始 seed2 的同配置复跑

原始失败 run 保留在：

`results/runs/EXP51/f3_submit_v2/A2_seed2/`

独立复跑保留在：

`results/runs/EXP51/f3_submit_v2/A2_seed2_rerun1/`

两次配置均确认：

- `method = EXP51-A2-MRCS-Async50`
- `async_iter_per_kf = 50`
- `DynamicKeyframe.gap_cap = 5`
- 同一数据序列 `f3_st_hf`
- 同一 seed = 2
- 3090 运行环境
- 两次 `status=OK`

| run | run_id | ATE (cm) | RPE (cm) | escape |
|---|---|---:|---:|---|
| 原始 A2 seed2 | `2026-08-27-16-58-19` | **20.2845** | 1.4534 | no |
| A2 seed2 rerun1 | `2026-08-27-20-28-10` | **2.6884** | 1.1367 | yes |

这组同 seed 结果是本轮最重要的诊断：

> async50 已把平均失败风险显著压低，但仍存在运行级双稳态/非确定性；20.2845 cm 不是 seed2 的确定性属性，也不能用 rerun 的 2.6884 cm 覆盖原始失败。

如果把复跑作为额外、非独立观测，仅作描述性汇总，则 7 个观测为：

- 逃逸 **6/7**
- mean = **5.3154 cm**
- sample std = **6.6126 cm**

这个 7-run 数字不应替代正式 3-seed 主判决，也不应当作 7 个独立 seed。

## 4. 收口判断与下一步

1. `async_iter_per_kf=50` 已证明是 3090 上可用的 MRCS 工程工作点：A2 六个独立 seed 中 **5/6 逃逸**，成功运行的 ATE 为 2.3943–3.6271 cm；相对 async10 的 35 cm 级失败，改善已经足够明确。
2. 原始 seed2 的同配置复跑从 20.2845 cm 变为 2.6884 cm，确认这次失败是运行级双稳态，而不是 seed2 固有失败。用户已决定不再为这一单点细节追加 seed 或调度追踪实验。
3. 本结果的正确定位是：**async50 作为 3090 实用运行预算收口**，而不是新的算法组件，也不宣称 100% 稳定保证。原始失败值保留，不从统计中删除。
4. `gap_cap=5` 本轮保持不变；本会话不据此修改 DynamicKeyframe，也不把 async50 写入共享 `tum/base_config.yaml` 或改变 vanilla 默认配置。
5. 下一会话转向方法结构问题，优先评估 P11 `sparse KF + mask-only` 是否值得在 3090 上正式立项，或比较 `async50 + MRCS` 与 `mask-only` 的跨动态/静态表现。单个偶发双稳态不再阻塞该方向。
6. chenfan/V100 曾完成探索性 P11 run，但服务器随后不可用；其结果不进入本项目正式统计、主表或方法判决。

## 5. 文件来源

- 预注册：`results/evidence/exp51_f3_submit_prereg.md`
- 正式结果：`results/runs/EXP51/f3_submit_v2/{A1,A2,B1,B2}_seed{0,1,2}/tables/tracking_raw.csv`
- A2 补充结果：`results/runs/EXP51/f3_submit_v2/A2_seed{3,4,5}/tables/tracking_raw.csv`
- A2 同 seed 复跑：`results/runs/EXP51/f3_submit_v2/A2_seed2_rerun1/tables/tracking_raw.csv`
- 3090 读数脚本：`scripts/read_exp51_f3_submit.py`
