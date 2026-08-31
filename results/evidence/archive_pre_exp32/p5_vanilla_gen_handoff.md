# P5-VANILLA H-GEN 完整执行说明（下会话续接）

> 2026-08-09 exp-v3-09 收口。预注册 `results/evidence/p5_vanilla_gen_prereg.md`。
> 目标：把"cross-front-end extrapolation restraint"补实证——cohort 是否 combined 特有？
> 用户明确选**路 B（真 vanilla 重训）**。**此文件 = 下会话怎么读结果、判定、回填稿子。**

## 已做（本会话 commit 3a031c9 + 远程启动）

- 预注册写定：`evidence/p5_vanilla_gen_prereg.md`（判据：① coales 存在 op<0.01 占比∈(0,20%]；
  ② 删+离线重渲 |dPSNR|≤0.003 dB 等量级）。
- **配置**：`configs/rgbd/experiments/p5_vanilla/method_p5_vanilla_prune.yaml` =
  `method_combined_maskboth_prune.yaml` 逐字节 + 仅把 `{SemanticMask, RobustTracking,
  DynamicKeyframe, DeferredCommit, ReliabilitySignal}.enabled` 全部改 false；
  三序列 run 配置 `p5_vanilla_prune_{balloon,mv_no_box,pt2}.yaml`（inherit 各自 bonn 序列，
  method_from 指向 vanilla method）。**零核码改动**，prune lifecycle + terminal refinement 保留。
- **远程 3090 已启动**：`run_p5_vanilla_3090.sh`，`nohup bash … > p5_vanilla_3090.log`，
  pid=2668089（logout 后靠 log 轮询）。双卡并发 balloon(gpu0)+mv_no_box(gpu1)，随后 pt2。
  每 run ~25-40 min → 3 run 约 ~1.5-2h。
  输出：`results/runs/P5/P5-VANILLA/{seq}_vanilla_seed0/…/final_after_opt/point_cloud.ply`。

## 下会话续接步骤

1. **轮询训练完成**：远程 `find results/runs/P5/P5-VANILLA -name tracking_raw.csv | wc` 应=3
   （每 run 一个 tracking_raw.csv），或 `tail p5_vanilla_3090.log` 见 "ALL P5-VANILLA DONE"。
2. **回拉结果**：
   ```bash
   rsync -a -e "ssh -o BatchMode=yes" jiangwenheng@172.16.227.24:/home/jiangwenheng/cron/monogs-ours/results/runs/P5/ results/runs/P5/
   ```
3. **重渲判据（零 GPU 训练）**：在结果上跑 `mc_terminal_comp_3seed.py <各 run_dir> --thresholds 0.01`
   （与 p4_op001 完全同口径；脚本已在远程与本地）。会额外生成
   `posthoc_terminal_comp/op010/fullframe_summary.json`（删% + dPSNR）。
4. **裁决（预注册不事后改）**：
   - ① 若 3 图 op<0.01 占比都 >0 且 ∈(0,20%]，② 各 |dPSNR|≤0.003 dB → **H-GEN 方向成立**
     （cohort 跨 vanilla 退化复现，终端 refinement 的结构事实，非 combined 特有）；
   - 若某图 cohort≈0 或 |dPSNR| 明显 >0.003 → H-GEN 失败，稿子语言**收窄到 "our backbone only"**。
5. **落证据**：`results/evidence/p5_vanilla_gen.md`（2 表 + 一句话裁决 + 回填指向）。
6. **回填 manuscript（若成立）**：§4.7 或 Limitations 加一句 descriptive——
   "…and we confirm a similar op<0.01 soft-selected cohort (≈X%, |dPSNR|≤0.00Y dB) appears
   when our backbone is reduced to its vanilla insert-then-prune core (3 representative
   sequences: balloon, mv_no_box, pt2)". 禁词仍旧：不写成 "general dynamic-SLAM" 或跨竞品。

## 纪律

- **单 seed screening**：3 代表图 seed0，只给方向读数，不写 verdict（判据①② fixed）。
- 3 序列含开放集(balloon 人+物)/纯动态(mv_no_box)/困难人(pt2)——若三者一致则方向强。
- 不复活已判死机制；不把 vanilla 结果当新 headline。
- 若 8/30 投稿窗口紧，本实验结果**只作支撑性 descriptive**，不阻塞投稿；若判据①失败导致
  manuscript 需收窄外推句，也照做（一处措辞，不动证据）。

## 当前 git（e5b3407 → 3a031c9）

```
3a031c9  P5-VANILLA 预注册 + vanilla 配置 (H-GEN)
e5b3407  codex R7 三处收尾 (DG-SLAM 引文/fig4/§3.2 措辞)
```
工作树干净（本地）。远程 3090 在跑 P5。NEXT_SESSION_PROMPT 由本文件承载续接说明。
