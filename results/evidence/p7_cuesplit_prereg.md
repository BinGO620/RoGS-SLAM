# P7 CUE-SPLIT — 预注册与判决（2026-08-13 方法期立项）

> 移交来源：`carryover_to_ours-v3.md`（ours-method @ c57299b）。本轮把 "ReliabilitySignal 固定
> 双线索乘法非普适内核" 的 cue 拆解提升为 ours-v3 的正式方法期实验。先并 18-seq 渲染主表
> （`papers/maskfree_bundle/skeleton.md` §3.3），再立项本 cue-split。

## 一、问题（Why）

现行头条把 ReliabilitySignal 的 `s=(1-e_flow)(1-v*g)` 当作 bundle 内核之一，但 ours-method
的单 seed cue 拆解（seed-0 / mask-free / prune / RTX2060 --fast）显示**固定 both 不是普适正确**：

| 序列 | OFF | both(默认) | flow-only | geometry-only |
|---|---:|---:|---:|---:|
| balloon | 18.506 | 14.877 | **12.840** | 14.714 |
| mv_no_box | 3.737 | 3.583 | 4.293 | **3.568** |
| mv_no_box2 | **5.681** | **12.725** ⚠️ | OOM(未完成) | **4.812** |
| pt2 | 13.525 | 9.494 | 15.288 | **9.309** |

- balloon 偏 flow（flow-only 12.84 最优）；mv_no_box / mv_no_box2 / pt2 偏 geometry；
- **mv_no_box2 上固定 both 真实退化（5.68→12.72 cm，+124%）** —— 固定乘法不是无害默认。

⇒ 结论：不是 "flow 是内核" 也不 "both 一定好"，而是 regime 依赖。真正值得的方向 = **regime-aware
/ cue 选择** 或 **保守融合**，而不是沿用固定 both。

## 二、假设（待证）

**H1（单 seed 是否 3090 稳定）**：4 序列 × 4 臂（off / on-both / flow-only / geometry-only）
在 3090 + 3-seed 上，ours-method 单 seed 的 cue 主导性（balloon→flow，其余→geometry，
mv_no_box2 上 both 退化）是否复现。

**H2（regime-aware 是否值得）**：若 geometry 普遍最稳（≥3 序列最优），则把默认融合改为
geometry 优先/保守融合（只取更保守的 cue）是一个可写的方法改进；若 cue 主导性序列之间矛盾
（balloon→flow 而其余→geo），则证明单一固定融合无解，必须序列级 cue 选择。

## 三、Control / 口径

- **base**：`method_combined_maskoff_prune.yaml`（mask-free，SemanticMask off —— 纯内核，不掺借来的 mask）。
- **4 臂**：ReliabilitySignal 仅 mode 差 —— `on`(默认 both) / `off`(disabled) / `flow-only` / `geometry-only`。
- **config 合同**：`tests/test_p7_cuesplit_configs.py` 钉住"四臂与 base 唯一差异 = ReliabilitySignal"。
- **序列**：balloon（混合 mover=flow 偏好）+ mv_no_box / mv_no_box2（纯物）+ pt2（纯人）——ours-method 已证区分度最高的 4 个。
- **机器**：3090 双卡（`--fast` 口径 ATE 与完整 eval 一致，工程护栏见 memory）；3-seed。
- **ATE 口径**：`tracking_raw.csv` 的 `ate_rmse_cm`（full-traj），不 grep 关键帧 console。

## 四、判决规则（跑前固定）

- **每臂 = 3-seed**。主导 cue 判定 = 该序列下某单 cue arm 的 3-seed mean 最优，且与次优间隔 ≥ 方法内抖动（参考同序列 base 的多 seed std）。
- **`both` 有退化臂**：若某序列 `both` 的 3-seed mean 比 `off` 差 ≥20%（如 mv_no_box2），则在结果表必标注 ⚠️，并证明固定 both 在该 regime 是负贡献。
- **H2 判定**：≥3 序列同 cue 主导 ⇒ 该 cue 作为 bundle 内核升级可行；跨序列矛盾（balloon→flow，其余→geo）⇒ 写进方法为 "**regime-aware cue 选择**" 非"统一融合内核"。
- 单 seed 是 screening（项目纪律⑤）；**本判决只在 3-seed 齐后下**。

## 五、停止条件

- 若 3090 的 3-seed 与 ours-method 单 seed 结论大幅冲突（如 balloon 不再偏 flow），先复核
  probe 是否 2060 特有，不再直接收成方法改进。
- 若 geometry 在全部 4 序列都劣于 flow 或反之（无 regime 反例），则 cue-split 无信息量，收窄
  回固定 both（但 mv_no_box2 退化需解释，不可当不存在）。

## 六、如何跑（远程 3090）

```bash
# 在 3090 上：同步本 commit 后
bash scripts/run_cuesplit_3090.sh
# 输出 results/runs/P7/P7-CUESPLIT/cuesplit_{seq}_{mode}_seed{seed}/tables/tracking_raw.csv
# 约 12h 双卡（48 run × ~30min ÷ 2 卡）。
```

## 七、产出

- 结果表：`results/evidence/p7_cuesplit_verdict.md`（3-seed 裁决 + H1/H2 + "写方法要怎么改"）。
- 若 H2=regime-aware：进入 `our_method/02-method.md` 现行头条的方法内核重写（从"固定融合"替为"cue 选择"）。
