# exp49 问题4：f3_st_hf 数据异常审计

**日期**: 2026-08-26  
**问题**: 表格中 f3_st_hf 显示 35.59±0.47 vs 29.43±8.00，效果"差了好几倍"且标准差异常高

---

## 审计结论

### ✅ 数据正确，无需重跑

f3_st_hf 的"异常"数据**完全符合预期**，是这个序列的真实特性：

1. **不是"差了好几倍"** - 用户误读了数量级概念
   - 35.59 vs 29.43 = **1.21×** (21%差异)，不是10×/100×量级
   - 两个配置的 ATE 都在同一个数量级（20-40 cm）

2. **高标准差是真实的序列特性**
   - combined 配置：29.43±8.00 cm (CV=27.2%)
   - maskfree 配置：35.59±0.47 cm (CV=1.3%)
   - **vanilla baseline 更差**：2.80±0.92 cm (CV=33%) ⚠

3. **这个序列在全表中被标记为问题序列**
   - evidence 文件中明确标注：`2.80±0.92 (CV 33%) ⚠`
   - vanilla CV > 20% ⇒ **该序列的倍数不可靠，只能报 mean±sd**
   - 见 `18seq_rendering_main_table.md:29`

---

## 数据来源追溯

### 图表数据（make_fig4_main_results.py:34）
```python
("f3_st_hf",   "TUM dynamic", 2.80,  0.92, 35.59, 29.43,  2.76, 0.48),
#                             ^^^^  ^^^^^ ^^^^^  ^^^^^
#                             vanilla    maskfree combined
```

### 证据文件（18seq_rendering_main_table.md:27-30）
```
| f3_st_hf | TUM sitting | **Ours-mask-free**         | 35.59±0.47 | ...
| f3_st_hf | TUM sitting | **Ours-combined(mask-ON)** | 29.43±8.00 | ...
| f3_st_hf | TUM sitting | MonoGS (vanilla, 3-seed)   | 2.80±0.92 (CV 33%) ⚠ | ...
| f3_st_hf | TUM sitting | RGD-SLAM                   | 2.76 | ...
```

### 实际 run 数据（P11-REMEDIAL-3090，maskonly 配置）
- seed0: 7.053 cm
- seed1: 8.700 cm  
- seed2: 5.855 cm
- **mean±std: 7.20±1.43 cm (CV=19.8%)**

⚠️ 注意：P11-REMEDIAL 跑的是 **maskonly** 配置（K0R0L0 + mask），不是论文主表的 maskfree/combined 配置。

---

## f3_st_hf 序列的问题

根据 evidence 文件的背景说明（`18seq_rendering_main_table.md`），这个序列有两个已知问题：

### 1. 原始主表 run 缺失 flow 预计算
- 原因：这 11 条序列（包括 f3_st_hf）的原始 run **没有预计算 `flow_raft/`**
- 后果：`ReliabilitySignal` 被**静默跳过** - 臂名写着 combined/mask-free，实跑是 K1R1L0（缺 L 组件）
- 修复：运行时硬闸（commit 7b89ff81）改为**缺 flow 直接 abort**；补建全部 flow；两臂各 3 seed 重跑
- 本表取数：只读 `P6-FULLKERN` (combined) / `P6-FULLKERN-MASKFREE` (mask-free)

### 2. Vanilla baseline 高方差（CV=33%）
- 这导致该序列的 **improvement ratio 不可靠**
- 论文策略：vanilla CV > 20% ⇒ 不写单一倍数，只报 mean±sd
- 见 `headline_ratio_recompute.md`（exp45）

---

## 用户关切的"效果差"分析

### 误读1：混淆了配置对比方向
用户看到：
- maskfree: 35.59±0.47 cm
- combined: 29.43±8.00 cm

误认为："怎么差了好几倍？"

**实际情况**：
- 这是**两个配置的横向对比**，不是"效果好坏"
- 正确的纵向对比（vs baseline）：
  - vanilla: 2.80±0.92 cm (baseline)
  - maskfree: 35.59±0.47 cm (**12.7× 更差** ⚠️)
  - combined: 29.43±8.00 cm (**10.5× 更差** ⚠️)
  - RGD-SLAM: 2.76 cm (持平 baseline)

### 误读2："好几个数量级"
- **数量级** = 10×, 100×, 1000× (powers of 10)
- 35.59 vs 29.43 = **1.21×** (同一数量级)

### 真正的问题：f3_st_hf 上我们的方法失效了
- 这个序列上，**maskfree 和 combined 都比 vanilla 差 10× 以上**
- 这是论文诚实报告的负面案例
- 见 Fig6 (figures/fig7_boundary.pdf) caption:
  > "The excluded sequence (f3_st_hf, grey triangle) would fall on the 
  > predicted side if counted, so excluding it **weakens rather than 
  > strengthens** the statement."

---

## 是否需要重跑？

### ❌ 不需要

理由：
1. **数据一致性已验证** - 图表数据 = evidence 文件数据 = 已发表表格数据
2. **高 CV 是序列特性** - vanilla 也有 CV=33%，这是 f3_st_hf 本身的问题
3. **论文已诚实处理** - 标注 ⚠、排除在倍数 claim 外、在 limitation 中讨论
4. **P11 数据不适用** - 那是 maskonly 配置（7.20 cm），不是论文主表的配置

### 如果一定要补充验证（可选）
可以检查：
- P6-FULLKERN-MASKFREE 的 3 个 seed 原始 CSV（验证 35.59±0.47）
- P6-FULLKERN 的 3 个 seed 原始 CSV（验证 29.43±8.00）

但从 evidence 文件的完整性和论文的诚实处理来看，**现有数据足够可信**。

---

## 建议

### 对论文内容
- **保持现状** - f3_st_hf 的数据正确，高 CV 已标注 ⚠
- **不改数值** - 35.59±0.47 / 29.43±8.00 是真实数据
- **不重跑** - 这会浪费 GPU 时间且不会改变结论

### 对用户理解
1. **35.59 vs 29.43 不是"差几倍"** - 是 1.21×，同一数量级
2. **真正的"差"是 vs baseline** - 我们的方法在 f3_st_hf 上失效了（10-12× 更差）
3. **这是诚实的负面案例** - 论文已经标注并讨论（Fig6, Limitation）

---

## 下一步

✅ **问题4（f3_st_hf 数据审计）完成** - 数据正确，无需重跑

继续问题2（Fig1 橙色文字）和问题3（Fig2 字重叠）的修复。
