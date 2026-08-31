# pt1 / person-tracking 探索 — 低纹理难点（用户洞察）+ 候选假设 H 集合

> 2026-08-10 exp-v3-13。pt1/person-tracking 短板（mask-ON 11.89 vs RGD 7.21）进展到：
> **A（rt-tight 加权）无效；B（flow 粗位姿）离线方向性否决。** 用户给关键洞察：低纹理/特征少/
> 易跟丢正是传统点线 SLAM（ORB-SLAM3 / AIRSLAM / 加点线特征）要解的。据此提出 H 集合。

## 已否决节点（固化，不复活除非有新机制证据）
- **A** rt-tight + mask dilate 更大：pt1 mask-ON 13.46 vs 基线 11.89，RPE 未降。**加权更紧不救 pt1。**
- **B** flow 粗位姿（学 DG-DROID）：离线方向性探针 = cosine(flow,GT) **-0.039**、bearing error 90.6°、
  flow 幅度 3.6cm vs GT 0.75cm。**flow 在 pt1 只反映人体动态，不反映相机运动，作初始化是噪声。**
  （若未来要用 flow 必须非"直接解位姿"，而只做减权——但 reliability 已在做。）

## 已确认事实（来自 bracketing_pt1_pt2_scene.md + flow probe）
- pt1/pt2 场景四维相同（相机运动/动态%/人数/距离），flow 分离比弱（0.76-0.79 不可分）。
- 相机运动极小（0.75cm/帧），人体占~65%，**人体大块低纹理 + 相机慢移 + flow 被人体淹没** = 难点根因。
- pt1/pt2 mask-ON 都 ~10-12cm，非 pt1 独崩，而是"人体占大画面 + 慢移"这个 regime 的整体水平。

## 用户洞察 → H 候选（低纹理是难点，线/结构化先验是解法）
1. **H-a 线/边特征约束**：传统点线 SLAM 用线特征在纹理少时补位姿。人体内部无纹理不提供信息，
   真正的约束在人/背景边界 + 房间强边缘（线）。候选 = tracking 加权/专用线对齐项。
2. **H-b 深度边界/几何一致性**：人体面 + 墙面的 depth 边界跳变，用深度梯度把信息集中到边界/平面。
3. **H-c 曼哈顿/结构化先验**：房间强曼哈顿（墙垂直/地水平），给低纹理帧全局方向锚。
4. **H-d [零侵入，先跑] 提高现有的 edge_threshold（grad_mask）**：我们发现 grad_mask 已是
   "按边缘强度保留像素"的掩码，但 edge_threshold=1.1 太宽松（全局 median 被人体大占比拉低，人体内部
   低纹理像素没被丢）。**提高 threshold（如 2-5）→ 只剩强边缘（人/背景边界+房间线）= 手动复现
   '线/边减信息'，免分割免 flow，纯 config 旋钮。** 直接测"低纹理像素是否拖累 tracking"。

## 第一个实验（零侵入，纯 config）
- **H-d**：pt1 mask-ON + edge_threshold 提高（梯度保留更严，只留强边缘）。
  - 预期：若低纹理像素（人体内部）确实拖累 tracking，则 ATE 下降；若无关，则 confirm 瓶颈在别处。
  - config 只覆盖 edge_threshold，其余 = combined mask-ON pt1 一致。
  - 3-seed，对照当前 mask-ON 基线（10.36/10.69/14.61）。

## 待办
- [ ] H-d edge_threshold 3-seed（3090 双卡）→ 见结果定 H-a/b/c 是否值得。
- [ ] H-a 若 H-d 有效，把"边缘加权"做成显式 lever（改 core 前呈用户）。
- [ ] 上线 codex 对抗审查 H 集合 + 已否决 A/B 的裁决。
