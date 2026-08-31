# codex Round 5 复审 — 修复清单（verified，逐条落地）

来源：codex R5（gpt-5.6-sol）全文复审，裁决 = **NOT-READY but short repair cycle**。
三审共识：18-map 删除结果已支撑窄实证 MMM 论文；无 auto-reject。阻塞 = draft-state 污染 +
数值不一致 + 实验来源混淆 + 机制残留 overclaim。修复以审计/改写/引用/绘图为主，**不需新 GPU 实验**。

## 已对证据逐条核实（本会话）

- **R1-M2 cohort max 计数错** ✅ 复算：<5% = **11/18**（非 14），<7% = **12/18**（非 16）；
  23.74% 在 **mv_no_box2 seed2**（非 seed1）。p99 全 18 图 <2%（max 1.81% pt2-s0）成立。
- **R2-M2 matched-rate 上界错** ✅ `p3_matched_rate_extended.md` 聚合 max|.|=**0.00210** ⇒
  "≤0.002 dB" 应为 **≤0.0021 dB**。
- **R2-M1 数据集来源未披露** ✅ `p4_op001_full18.md` 明写输入 = **2060 P2-T prune final_after_opt**
  （bak 源）；而 ATE/G 数 = **3090 官方重跑**（`p2t_verdict_3090.md`）。"same lifecycle" 可守，
  "same run set" 不实 ⇒ 须显式披露两 cohort。"dual RTX 3090" 硬件行只对 ATE 成立，对删除证据不成立。
- **R3-M1 online cohort "absent/appears only"** ✅ `p3_terminal_mech_autopsy.md` 逐 run online
  有 0–4.9% ⇒ 支持的陈述是 "increases 36/36"，非 "appears only after"。
- **R3-M2 0.01 "coarsest safe" overclaim** ✅ `p4_threshold_curve_result.md` 显示 op=0.02 时最差
  −0.0026 dB（≈0.01 的 −0.0025）⇒ 0.01 不是唯一边界点，"coarsest zero-cost threshold" 过强。
  spatial "redundant layer/freeing transmittance" 超出 3 图可证 ⇒ 标 descriptive signature。
- **R3-M3 theory 内部矛盾** ✅ theory.md §4.1 标题仍"= 裸 sigmoid"（与修正的不等式矛盾）；缺省
  深度顺序的 pro-sec 透射率说明。
- **R5-MonoGS DOI 错** ✅ CrossRef 确认 MonoGS "Gaussian Splatting SLAM" 真 DOI =
  `10.1109/CVPR52733.2024.01708`（现写 01723 解析到 Video ReCap）。MGS-SLAM 标题/作者与 DOI 元数据不符。

## 修复落地（git commits）

tbd（每个修复一个 commit，本条为母记录）。
