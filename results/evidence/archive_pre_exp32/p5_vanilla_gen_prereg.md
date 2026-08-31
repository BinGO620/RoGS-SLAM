# Pre-registration — 轨道D 方向B²: vanilla MonoGS 泛化（跨前端外推克制）

> 2026-08-09。exp-v3-09 会话收口前最后追加实验。用户明确选 **路 B（真 vanilla 重训）**。
> 目的：给 skeleton P1 的"跨前端外推克制"一句补实证支点——审稿人最可能的问法
> "cohort 是不是只有你们 combined 骨干特有？"。
> 落点仍是 **measurement**（跨前端结构事实），不滑向"赢了指标"。

## 假设（H-GEN，可证伪）

**H-GEN**：把 combined 骨干的所有附加机制全关（SemanticMask / RobustTracking /
DynamicKeyframe / DeferredCommit / ReliabilitySignal 全部 `enabled: false`，保留
insert-then-prune 生命周期、保留 terminal color refinement），得到的接近 vanilla 的
monoGS-style 骨干，其终图 `final_after_opt` **仍会**软选择出一个 sigmoid(op)<0.01 的
cohort，且该 cohort 可零代价删除（|dPSNR| 与 combined 同量级）。

- **若成立**：cohort 不是 combined 特有伪影，而是 terminal color-refinement 的泛化结构；
  坐实"跨前端外推克制"的诚实边界（我们只说"在我们 backbone 及其 vanilla 退化上都观测到"，
  不声称其他方法）。
- **若失败**（vanilla 上无 cohort 或删除有代价）：cohort 是 combined 骨干特定产物，
  论文语言需再收窄到 "our backbone"，不能外推。

## 受控对照（唯一变量 = 骨干设置）

| 臂 | 骨干 | 机制开 | lifecycle | 终图来源 | 用途 |
|---|---|---|---|---|---|
| combined (已有) | combined maskboth prune | mask+robust+dynkf+reliability | prune | P2-T prune `final_after_opt` | 参照，已在稿 |
| vanilla (本实验) | 全部机制 off | —— | prune | 本实验重训 `final_after_opt` | 对照 |

**唯一允许差异**：`{SemanticMask, RobustTracking, DynamicKeyframe, DeferredCommit,
ReliabilitySignal}.enabled = false`。其余（layer/densify/prune/refinement/optimizer/loss/
窗口/keyframe 策略/seed）**逐字节继承** P2-T 的 `p2s_combined_prune_*.yaml`。lifecycle 保持
prune。不改任何核心代码（零改动门槛）。

## 序列 / seed / 判据

- **序列 × seed**：balloon seed0, mv_no_box seed0, pt2 seed0 —— 3 个代表图（1 开放集人+物 /
  1 纯动态 box / 1 困难 person）。**单 seed screening**（预注册纪律：单 seed 不写 verdict，
  这里只需"cohort 是否存在 + 是否零代价"的**方向读数**，3090 机时有限，先 3 个代表）。
  若方向成立且机时允许，再扩 seed 到 3/图。
- **主机**：远程 3090 双卡，`conda activate monogs-ours-3090`。
- **判据（预注册，不事后改）**：
  1. **cohort 存在**：终图 `final_after_opt` 的 op<0.01 占比 ∈ (0, 20%]（若 ≈0 即失败）；
  2. **删除零代价**：op<0.01 删 + 离线 interval-5 full-frame 重渲，|dPSNR| ≤ 0.003 dB
     （与 combined 的最差 −0.0025 dB 同表准）。
  - 两项都满足 → H-GEN 方向成立（跨前端复现）；cohort% 或 |dPSNR| 明显偏离 → 收窄到
    "our backbone only"。

## 方法（完全复刻 p4_cohort_spatial / p4_op001 的装置）

1. 新建 vanilla 配置：`configs/rgbd/experiments/p5_vanilla/p5_vanilla_prune_{seq}.yaml`
   `inherit_from: configs/rgbd/{seq}.yaml` +
   `method_from: configs/.../p5_vanilla_method.yaml`（所有机制 off）。
2. 3090 上 `slam.py` 全长自跟踪重训 3 序列（每 ~45-90 min/run，共 ~3-4 GPU-h）。
3. 每 run 取 `final_after_opt` 做 op<0.01 删 + 离线重渲（`mc_terminal_comp_3seed.py` 阈值 0.01，
   与 p4_op001 同口径）。
4. 落证据 `results/evidence/p5_vanilla_gen.md`；若成立，回填 manuscript §4.7 或 limitation
   补一句"…and we confirm a similar cohort appears when our backbone is reduced to its
   vanilla insert-then-prune core (3 representative sequences)"（descriptive）。

## 禁词/不回炉

- 不把 vanilla 结果写成 "general dynamic-SLAM improvement" 或 "works on any 3DGS SLAM"。
  只报"our backbone 及其 vanilla 退化"。
- 不复活已判死机制；不把它当新 headline。
- 单 seed 不写 verdict（只方向读数，判据①②是 fixed 的）。

## 纪律

- 跑前 `git commit`（预注册 + 本说明）。
- 3090 机时：约 3-4 GPU-h，双卡可并行 2 序列。
- 同步用 rsync（REMOTE_3090_DEPLOY.md），软链重指回 `/mnt/app/datasets`，`--assume-unchanged`。
