# P3-DENSIFY-TAIL + terminal-compression MECHANISM AUTOPSY (2026-08-07)

> 产出：2026-08-07。**机制层面推翻**——`papers/mmm/mechanism.md` 的「ADC 稳态尾巴」主张，对
> 本项目所有带 `final`/`final_after_opt` 双 PLY 的运行（P2-T 36 run + P3-DENSIFY-TAIL 10 run）
> 被 PLY 直接比对证伪。terminal compression 的**经验事实**依然成立，但**机制故事需要重写**。
> 结论由我（本会话）+ codex（MCP 两轮复申）共同确认；这是**审判前的诚实收口**，不是事后辩护。

---

## 0. 一句话结论

**op<0.01 尾巴不是在线 ADC（densify/prune/reset）的稳态产物，而是 26000 迭代 color-refinement
（纯光度后优化）阶段被优化出来的软抑制（soft-suppression）产物。** 在线地图（`final` PLY）几乎
没有 <0.01 尾巴（P2-T 36 run 均值 0.69%，中位 0.10%），color-refinement 后（`final_after_opt` PLY）
才出现 6-22% 的尾巴（P2-T 36 run 均值 10.4%，36/36 都增长，平均 +9.7pp）。

---

## 1. 直接证据：P2-T 全 36 run（论文 terminal compression 的 12/12 母体）

对每个 run 的 `final`（在线地图结束）与 `final_after_opt`（color-refinement 后）PLY 算
`sigmoid(op)<0.01` 占比：

| 口径 | op<0.01 online (final) | op<0.01 after (final_after_opt) |
|---|---|---|
| mean | **0.69%** | **10.39%** |
| median | 0.10% | 10.20% |
| range | [0.00, 4.90] | [6.00, 18.40] |
| 增长运行 | — | **36/36**（平均 +9.69pp） |

**在线地图几乎没有极端低 opacity 尾巴。** 在线 prune 每 150 迭代 `op<0.7 → 删`，一个 op<0.01 的
高斯在线不可能存活（这正是 codex 第一轮的怀疑，现在被 PLY 证实）。尾巴是在**最后一次在线 prune 之后**、
color-refinement（无成百上千次 prune/densify/reset）里长出来的。

### 子表（部分 P2-T 行，最终 PLY 对）

| seq | arm | seed | N在线 | <0.01在线% | <0.01之后% | <0.7在线% | <0.7之后% |
|---|---|---|---|---:|---:|---:|---:|
| balloon | prune | 0 | 32653 | 1.8 | 12.8 | 35.1 | 54.8 |
| balloon | prune | 1 | 46074 | 4.9 | 18.4 | 53.9 | 61.9 |
| balloon2 | prune | 0 | 31528 | 0.0 | 11.4 | 13.5 | 42.6 |
| mv_no_box | prune | 0 | 38598 | 1.5 | 9.9 | 18.5 | 42.2 |
| pt1 | prune | 0 | 49838 | 0.0 | 9.9 | 2.2 | 39.9 |
| pt2 | prune | 0 | 87537 | 2.2 | 18.4 | 48.2 | 53.8 |

（注意：mv_no_box 若干 run 的 `final_after_opt` 比 `final` 多 ~5000 高斯——那是在 before_opt 评估
teardown 期间的一个插入竞态，不是纯 opacity 变化；同一代群体的干净 before/after 以 balloon/balloon2
为准。）

## 2. 代码路径确认（为什么尾巴长在 refinement）

- `color_refinement()`（`utils/slam_backend.py:826`）：26000 迭代，**纯光度 L1+SSIM**（`l1_loss(image,gt_image)` + dssim），
  对**存好的 viewpoints** 优化。循环内**没有** densify_and_prune、没有 reset_opacity、没有密度控制。
- opacity 是一个活的 Adam 参数（`opacity_lr=0.05`，`base_config.yaml:322`），通过全部 refinement。
- 解析后的 `config.yml`（每个 run 的 `TriReliability.enabled: false` ⇒ `_freeze_color_refinement_geometry_lrs`
  的 `freeze_geometry = static_guard and ...` = **False** ⇒ **refinement 期间什么都不冻结**。opacity 完全自由。
  （静态看 `apply_color_refinement_static_guard: false` + `enabled: false`，双保险确认不冻结。）
- 所以 refinement 驱动的不是「删除」，而是把一批已有的、contributing 的高斯 opacity 压到 <0.01
  （identity-matched：balloon/balloon2 常 N run，在线 >=0.7 的高斯里 402-538/run 在 refinement 里降到 <0.01，
  median logit 下降 +7 到 +9.8）。

> 注：`_freeze_color_refinement_geometry_lrs` 冻结集是 `{"xyz","opacity","scaling","rotation"}`，即它**会**冻
> opacity；但该路径仅在 `static_guard=True` 时触发。落地配置 `enabled:false/static_guard:false`，故本轮全程**未**执行。

## 3. P3-DENSIFY-TAIL 的意义（batch1 的解读被重新定性）

批 1（10 run，单 seed）原本读出「HI 臂 frac<0.01 反常高 + %>=0.7 下移」，我在 `p3_densify_tail_batch1_stopped_mech.md`
里把它解读为「密度影响 opacity 竞争」。现在串起两个事实：

1. **mech.md 的「ADC 再生尾巴」主张是错的。** 尾巴不来自在线密度控制，来自 refinement。batch1 的
   `frac<0.01` 主要量的是 **refinement 后**的状态，被 `N_total` 分母 + refinement 本身的双重噪声污染。
2. **HI 臂 `%>=0.7` 下移是真事**（HI 30-51% vs LO 61-66%），但它更可能是「HI 密度不足 → refinement 里更多
   opacity 被压低去够颜色」，而不是「密度竞争 → loser 贴 winner」。

**结论**：batch1 的 `frac<0.01` 作为「densify 阈值 → tail 宽度」的 predictor 仍然被证伪，
但**机制归属从「在线密度控制」迁到「refinement」**。batch2（36 run，~19h）**建议取消**——它
测的是一个现在已知**错的机制**。

## 4. codex 对抗复申（两轮，结论收敛）

**第一轮**（读完 PLY 与机制）：竞争机制不成立（HI 低 op 高斯与高 op 支撑空间分离，LoHasHiNN 0.04-0.48）。
且「低 op 高斯不可能在 op<0.7 prune 下存活」——提出 cadence/scheduling 疑问。

**第二轮**（喂入 final vs final_after_opt 差）：直接确认：
- ADC 机制死了（在线地图没有 tail，tail 是 post-online 现象）。
- 不急着把「颜色 refinement 注入无用 overfit 块」当机理——先做 frozen-opacity 反事实。
- 唯一有希望的中心贡献 = **refinement-aware 压实**（在线检测 inactive gaussian、从中删除、省时间/内存、保持质量）——是系统级贡献，不是「更小的 PLY」。
- 最小判据实验（1 run，不是 36）：**固定 opacity 重跑一次 refinement**，对比渲染/opacity 分布/runtime/内存/终剪后地图大小。

## 5. 待做（诚实的下一步）

1. **frozen-opacity 反事实（1 个 GPU run）**：任取一个在线 `final` 检查点，refinement 时把
   opacity 的 lr 置 0（其余不变），对比标准结果。三个分支：
   - 质量等 + 无尾巴 ⇒ refinement 配置有缺陷，贡献=更干净的 refine 循环（避免注入无用高斯）；
   - 质量降 ⇒ opacity 抑制在 refinement 里**有用**，terminal prune 是合法后处理，但「删无用浮渣」故事要撤；
   - 几何/scale 补偿 ⇒ 关联合参数，两故事都不够。
2. **batch2（36 run）取消**：测的是现在已知错的机制。
3. **paper 重新定位**：terminal compression 从「机制贡献」降级为「干净后处理观测」；除非 frozen-opacity
   反事实揭示可省的开销，否则不足以撑一篇 CCF-C 的机制类头条。

## 6. 记录规范

- 本文件（evidence）落盘结论，`our_method/03-results.md` 加一行裁决（R3-P05 terminal compression 机制重判）。
- `papers/mmm/mechanism.md` + `theory.md` 的「ADC 稳态」主张需**就地标注撤回**（数据未动）。
- 不删 `p3_densify_tail_batch1_stopped_mech.md`，只在其上加指向本文件的纠正标注。
- 任何 terminal compression / MMM 稿启动前，先跑 frozen-opacity 反事实判据。
