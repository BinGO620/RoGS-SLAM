# T2-scale 对照臂：预注册（exp32, 2026-08-20，**在看到常数值之前写下**）

## 为什么要这个臂

REVIEW §7.1 的自我质疑：配额隔离只能让 `tau` 变小（它剔掉的全是最大的 `d`），
而 `tau` 变小本身就锐化同一个 Cauchy 核 —— `w = 1/(1+(d/tau)²)`。
所以"隔离静态子群估计 tau"与"把 tau 乘一个常数 c<1"在 ATE 上**先验地不可区分**。
不设这个臂，E-both 赢了也说不出赢在哪；输了更说不出输在哪。

**声称的差别**：配额的等效 `c = f(帧)` 是帧自适应的（帧内 mover 占比越大剔得越多），
常数缩放不是。这个差别要么在 ATE 上体现出来，要么"隔离"这个叙事就得撤回，
机制改名为"自适应鲁棒核锐度"，理论依据整体重写。

## 常数 c 的定义（先于取值）

> **c = E-both 臂逐 run 的 `median(mad_tau_after / mad_tau_before)`（只取配额真正触发的帧），
> 再对 5 条序列的 seed-0 run 取中位数。**

REVIEW §7.1 原文写的是"取 E-both 实测 tau_after/tau_before 的中位数，约 0.45"。
这里把"实测"钉成可复算的口径：哪些帧（`mad_excl_applied == 1`）、哪一层先取中位数
（run 内先，再跨序列）、用哪些 run（seed 0 × 5 序列，因为它们最早齐）。
**取值由 `scripts/t2_quota_verdict.py` 打印，不手工挑。**

## 臂的构造

- 底座 = `method_combined_maskboth_prune.yaml`（与 E-both 同底座，与 control_maskon 同底座）；
- `ReliabilitySignal.mad_exclusion: false`（**不排除任何像素**）；
- `ReliabilitySignal.tau_scale: c`；
- 与 `method_t2_control_maskon.yaml` 的差异必须**只有** `tau_scale` 这一个键
  （由 `tests/test_retrofit_configs.py` 钉住）。

## 判读规则（先于数据）

| 结果 | 结论 |
|---|---|
| T2-scale ≈ E-both（|Δ| 小于 control 的 seed 间极差） | "隔离"叙事**撤回**。机制真名 = 自适应鲁棒核锐度；理论依据重写 |
| E-both 明显优于 T2-scale | 帧自适应性是真的贡献，"隔离"站得住 |
| 两者都不优于 control | 任务二整体判负，两种叙事都不用写 |

## 规模

15 run（5 序列 × 3 seed），与其它臂同矩阵。

**追加规则**：mask-free 一侧的同类对照（scale 常数按 Q-free 的 tau 比值取、
底座换 maskoff）**只在 Q-free 相对 control_maskfree 真有增益时才买**。
没有增益的机制不需要解释它为什么赢。
