# EXP55 预注册 — RobustTracking kernel 消融（Huber vs Cauchy vs Geman-McClure）

> 版本：2026-08-28；本文件必须在任何 EXP55 GPU run 前冻结并 commit。
> 正式 GPU 仅限 jiangwenheng 双 RTX 3090，每卡固定串行 worker；本地 2060 不进判决。
> 主指标：完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`（evo `-a` Horn 口径）。

## 1. 目的

论文 §3.3 的 RobustTracking 组件写死 `kernel: huber`（δ_rgb = δ_depth = 0.1），
但代码同时实现 Cauchy 与 Geman-McClure（`utils/slam_utils.py:_robust_irls_weight`），
且三者之间从未做过对比。审稿人会问"为什么是 Huber"。

本实验回答一个问题：**kernel 选择是否 load-bearing？**

- 若三者在主指标上不可区分 → 支持论文现有框架（组件是经典原语，贡献在测量不在
  kernel 选择），§3.3 加一句"kernel 间消融不可区分"即可。
- 若某 kernel 显著更好/更差 → 这是新发现，需要单独评估是否进论文（不自动替换
  主表配置；任何主表换 kernel 都需要新一轮全表重跑，成本另议）。

## 2. 冻结臂定义

基准配置 = 主表 combined 臂在 balloon / pt2 上的实际源配置（逐字节继承）：

- balloon: `configs/rgbd/experiments/p2_render/p2s_combined_prune_balloon.yaml`
  （主表数据源 `results/runs/P2/P2-T_3090/balloon_prune_seed{0,1,2}`，3090）
- pt2: `configs/rgbd/experiments/p2_render/p2s_combined_prune_pt2.yaml`
  （主表数据源 `results/runs/P2/P2-T_3090/pt2_prune_seed{0,1,2}`，3090）

两者 resolved 均为 `kernel: huber, rgb_delta: 0.1, depth_delta: 0.1`。

**唯一方法介入 = `RobustTracking.kernel`**（`huber → cauchy` / `huber → gm`）。
δ 保持 0.1（两通道）不变——单旋钮交换，不做 kernel×δ 扫描（预算限制，明示为限制）。

新配置（`inherit_from` 指向上述基准，仅覆盖 kernel 一键）：

- `configs/rgbd/experiments/exp55_kernel_ablation/exp55_cauchy_balloon.yaml`
- `configs/rgbd/experiments/exp55_kernel_ablation/exp55_gm_balloon.yaml`
- `configs/rgbd/experiments/exp55_kernel_ablation/exp55_cauchy_pt2.yaml`
- `configs/rgbd/experiments/exp55_kernel_ablation/exp55_gm_pt2.yaml`

Huber 臂**不重跑**：直接引用主表现有 3-seed 锚（同硬件、同 seed 集、同配置identity）。

## 3. 矩阵

```text
2 kernels × 2 sequences × 3 seeds = 12 runs（全部新增）
```

## 4. 静默降级硬门（E0，run 前置）

`_robust_irls_weight` 对未知 kernel 值**静默返回全 1 权重**（= 鲁棒核失效），
与 exp23 ReliabilitySignal 静默跳过同类事故。因此 runner 必须在每 run 启动后：

1. 读 run 目录 resolved `config.yml`，断言 `kernel` 字段 == 预期值
   （cauchy 臂断言 `cauchy`，gm 臂断言 `gm`），否则**立即 abort 该 run 并标记失败**；
2. 断言 tracking 代码路径确实调用 `_robust_irls_weight`（`RobustTracking.enabled: true`
   在 resolved config 中为 true）。

配置合同由 `tests/test_exp55_kernel_configs.py` 钉住（inherit 链、唯一差异键、
kernel 值、δ 不变、dataset/mask/lifecycle 全同基准）。

## 5. 运行协议

- 远程 jiangwenheng 双 3090，`PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python`。
- GPU0 = balloon 6 run；GPU1 = pt2 6 run；每卡固定串行。
- 派发前检查（沿用 exp54 runner 模式）：远程 HEAD == EXPECTED_HEAD、tracked worktree
  干净、flow 预检（balloon/pt2 的 `flow_raft/` 已存在——主表 runs 均正常消费）。
- 每 run 完整 `--eval`；完成门 = 轨迹帧数 ≥ 95% 数据集帧数。
- 预算：12 run × 25–45 min ≈ 2.5–4.5 h 墙钟。

## 6. 判读（冻结，描述性）

Huber 锚 = 主表现有 3-seed（balloon 3.06±0.14 / pt2 10.44±0.84，源
`results/runs/P2/P2-T_3090/*_prune_seed*`）。地板 = `max(0.43 cm, 6% × max(锚均值, 臂均值))`。

对每个 (序列, kernel) 组合，报告 mean±sd 与 Δ = kernel_mean − huber_mean：

- **INDISTINGUISHABLE**：|Δ| < 地板 → kernel 选择不 load-bearing（预期结果）；
- **BETTER / WORSE**：|Δ| ≥ 地板 → kernel 在该序列 load-bearing（新发现，需用户决策）。

Caveats（引用时必须同写）：
1. Huber 锚来自前一 campaign（跨 campaign 比值漂移 ~30% 纪律，判读以地板内/外为准，
   不读比值小数点）；
2. 3 seed 描述性比较，无显著性检验；
3. 只在 2 序列上测（Δ_R 最大的 balloon 与 pt1 族代表 pt2），不外推全表；
4. δ 固定 0.1，kernel×δ 交互未测。

## 7. 禁止事项

- 不改共享 base、vanilla 默认、p2_render 既有配置；
- 不因结果好坏中途改 kernel/δ 追加 run；
- 2060 / chenfan / V100 数字不进判读；
- 失败 run 原样保留，不重跑替换；
- 判决前不把任何 kernel 值写进论文正文。

## 8. 预期

三个 kernel 都是标准鲁棒核，在残差尾部行为上有差异（Huber 有界影响函数、Cauchy/GM
红降更快），但在 δ=0.1、已有一阶"99% 像素近单位权"的工作点上，预期差异远小于序列间
regime 差异。若确实不可区分，这正是论文需要的"组件是经典原语"的证据。
