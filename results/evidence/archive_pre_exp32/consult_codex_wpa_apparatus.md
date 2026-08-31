# WP-A Apparatus — codex 对抗审查处置（2026-08-14, exp-v3-18 起跑前）

> 处置于 WP-A 第一个 run 前（120-run 尚未启动；E0 dry-run 在 E0_hero/K1R1L1/mv_no_box 上跑）。
> 预注册已 commit（`bee241a`），本处置不改预注册判据。

## codex pass-1（apparatus 攻击）：bloNOCK 判决 + 修正

| codex 项 | 判定 | 我的核验 | 处置 |
|---|---|---|---|
| **BLOCKER**: L=0 时 `reliability_confirm:true` 使确认退回整数计数，非"inert" | **部分采纳** | 手动 trace：L=0 时 reliability_s 不 stash → `_reliability_maps` 返回 None → `use_reliability=False` → reject 用纯整数 contradictions。**这是 L 的机制效应，不是混杂**（L 轴要测的正是这个），但 codex 要求 E0 断言"L=1 有加权路径 / L=0 无"而非"判定一致" | E0 改写为 activity 断言（见 prereg §八.2） |
| **RISK**: stale reliability_s 泄漏进 L=0 | **驳回** | 单 run 单 process、L 常量、frame 新建 Camera 对象、无跨 run 复用；无其它入口写 reliability_s | 写进 prereg（不适用） |
| **RISK**: readout 列表 index 位置配对 | **采纳** | `ate_list[list(completed_seeds).index(s)]` 依赖 dict 插入序；若 ate 非有限则错位 | readout 改 seed-keyed `ate_by_seed` 字典 + finite/positive filter |
| **RISK**: 非有限 ATE（+inf）通过 `>0` → 无穷 log 比 | **采纳** | NaN 被 `>0` 挡，+inf 通过 | 加 `math.isfinite` |
| **RISK**: Δ 方向隐含 | **采纳** | 调用点 cell 顺序决定 log(numerator/full) | marginal() 内固定 numerator/denominator + 注释 |
| **RISK/BLOCKER**: --fast 写不写 trj_full_final | **驳回（实证）** | `save_final_tracking_raw` 硬编码写 `plot/trj_full_final.json`（非 eval_ate），--fast 仍写；P7 geo 实测 778/778 | 干脆 WPA runner 改无 --fast（与 P7 逐协议对齐），消歧 |

## codex pass-2（机制裁决）：L 轴是否 null-vs-null

确认：prune 模式下 L toggle 真实改变 reject 路径（加权 C± vs 整数），**L=0 是真 "reliability off"，
不是机械失效**；reliability_confirm:true 在 L=0 格保持统一（L 轴完全由 ReliabilitySignal.enabled 驱动）。
唯一的限定：L=1 不一定每个观测都加权（首帧/缺 flow 会退回整数），E0 应断言 L=1 **有**加权 activity
而非"全部加权"。

## 已采纳修正（代码已 commit 6b8e85b）

1. readout `completion_and_ate` 改 seed-keyed `ate_by_seed` + `math.isfinite(ate)` 过滤；
2. `paired_ate` 直接读 `ate_by_seed[s]`，k 只算双方都有有限正 ATE 的 seed；
3. WPA runner 去掉 `--fast`（与 P7 完整协议对齐）；
4. prereg §二/§八 改写：E0 断言 L-activity（非 parity），保留 reliability_confirm:true 于 8 格。

## E0 dry-run（进行中）

- hero arm = `wpa_mv_no_box_K1R1L1` seed0（mv_no_box，8 格全对 + DeferredCommit 统一 + mask-free）。
- 待验：① tracking_raw.csv + plot/trj_full_final.json 均写；② trj 帧数 ≥95% total(778)；③ console
  出现 K/dense-KF 与 R/huber 与 L/reliability 加权 activity。通过后 launch 全 batch。

## 结论：可跑（改动已含 codex 修正）；全 batch 等在 E0 dry-run 验证活动性后发。
