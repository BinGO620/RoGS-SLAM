# Codex adversarial 审查 — pt1 vs pt2「纯人 mask-free」矛盾（2026-08-10 draft, 待 codex 返回）

**背景问题**：mask-free bundle（dense-KF+RT+Reliability, 无语义 mask）在 pt2「纯人」序列 mask 冗余
（maskoff 9.30 ≈ combined 10.44），但在 pt1「纯人」序列 mask 主导崩（maskoff 32.41±8.51 vs combined
10.04±0.58, 3.23×）。同为 person 族, 一个行一个不行。请 codex 从实验/归因角度对抗审查这组数字:
- pt1 RPE 2.8-3.1 vs pt2 ~1.6（pt1 逐帧位姿噪声大 2x）
- pt1 maskoff seed 大方差 ±8.5（24-41cm), pt2 低方差 ±0.64
- 我的解释: pt1 双稳态/难跟踪, mask-free 失去 mask 加持时跟踪发散；pt2 低遮挡稳定, mask-free 扛得住。
- 也可能 pt1 是"该序列 mask 本来就主导"（同 balloon 混合, 只是 person 遮挡更散）。

请判断:
1. 这个"pt1 是边界反例, 收窄'纯人 mask 冗余'为 pt2 结论"的定性站得住吗？还是应视为"对头条的更强威胁"，需更多实验?
2. 是否需要 pt1 masked-on 的逐帧诊断（哪些帧 maskoff 崩了, mask-ON 是否同一帧区也崩）来定位"是 mask 贡献还是 bundle 崩"?
3. 序列内容层面（pt1 vs pt2 的遮挡/多人/相机运动）是否足以解释 RPE 2x 差异?
