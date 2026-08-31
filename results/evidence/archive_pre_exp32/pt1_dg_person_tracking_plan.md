# pt1 person-tracking 补强方案 — 预注册草稿（2026-08-10）

> 2026-08-10 exp-v3-13。pt1 是全 18 序列唯一 mask-ON 下仍明显落后 RGD 的短板
> （mask-ON 11.89 vs RGD 7.21 / DG 4.25 / WildGS 3.63）。用户注意到 **DG 在 person 序列
> 相对最强**，指示深挖 DG 机制能否借鉴。**此文件 = 可拍板方案草稿（不是实施），动核心前呈用户。**

## 1. 问题边界（已定位）

- pt1 mask-ON = 10.36/10.69/14.61（3-seed 大方差），P2-T 也 9.62/9.79/10.70 → **tracking 精度不够，
  不是地图崩**。RPE 2.8（mask-off）vs combined 1.6。
- mask-ON 已把 mask-off 的 32 拉回 11.9，所以语义 mask 有效；剩的是"mask 对了但位姿估得不够准"。

## 2. 为什么 DG 在 pt1/pt2 强（机制假设）

DG-SLAM = 语义mask + **depth warp mask（时空调制动态细化）** + **DROID-VO 粗位姿** + coarse-to-fine
photorealistic alignment。对比我们：

| 组件 | DG-SLAM | 我们 | 判断 |
|---|---|---|---|
| 动态检测 | 语义mask + depth-warp 时空调制 | 语义mask（mask-ON）| 我们 mask-ON 已有效 |
| 粗位姿初始 | DROID-VO（光流/特征VO）| const_vel（**已验证负**）或无 | **关键差异** |
| 精修 | coarse-to-fine 光一致性 | Adam photometric refine | 需加强 |

**const_vel 判负 ≠ 粗位姿判负**：probe1 证明 const_vel 在长序列漂移（正反馈），但那是 const_vel 的具体缺陷
（匀速假设 × 弱光度精修 = 自我强化）。DG 用 DROID（光流驱动）避免了这点。

## 3. 候选方案（从低到高侵入，都先验证 idea 不动 core）

### A. [零侵入，纯旋钮] pt1 mask-ON + RT 更紧 + 更多 tracking itr
- 找 `tracking_itr_num`（现 base 5？）加多、RT huber 更紧（rgb_delta/depth_delta 更小）。
- 直接验证 RPE 是否降。成本 = 1-2 run × 3 seed。**但这只"调紧"，不解决初始化缺陷。**

### B. [低侵入，加 lever] flow 粗位姿（替代 const_vel 的负反馈）
- 我们 tracking 里已有 RAFT flow（reliability 用），DG 用 flow 做 VO 粗位姿。
- 候选：用 flow 估计当前帧相对前一帧的运动，作为 Adam 精修的初始位姿（替代 const_vel 的坏初值）。
- **这是最可能把 pt1 从 11.9 往 RGD 7.2 拉的方向**——因为 pt1 崩在"初始化不佳→photometric refine 陷局部"
  而非"mask 不够"。三个 seed 已拆成"双稳态"（10.3/10.7/14.6），恰是初值敏感的指纹。
- 实现侵入面：`utils/coarse_pose.py`（已有 `const_vel`/`icp`/`masked_icp` 三种 mode，可加 flow 模式）
  + `slam_frontend.tracking()` 的 coarse_pose 块（已在 692 行调用）。

### C. [中侵入] depth-warp mask 补充（学 DG 的时空细化）
- 语义 mask-ON 已排除主体，flow 只需细化边缘。用 reliability flow 的 `fv_map`（flow validity）做
  depth-warp 式边缘微调。但注意 pt1 flow 分离比弱（0.76-0.79），此 lever 可能增益有限 → 排 B 之后。

## 4. 验证方式（零 GPU 先验 idea 也便宜）
- 每候选 = pt1 × 3 seed，ATE + RPE 对比当前 mask-ON 基线（10.36/10.69/14.61）。
- 通过判据：3-seed mean ATE < 10（当前 11.89 的下界），且 RPE 明确下降；不追求一次到 RGD 7.2，
  先看方向。

## 5. 硬停条件提醒
- B/C 改 `utils/coarse_pose.py` / `slam_frontend.py` = **核心逻辑，须先用户拍板**。
- A 纯 config 可不需拍板直接跑。

## 6. 三张卡使用（用户已授权）
- 3090 双卡：pt1 mask-ON 的 A（旋钮）批量，先验证"调紧"是否有效。
- 2060：验证 B 的 flow 粗位姿（单独测，不占 SLAM 显存，可先看 flow 估计的位姿质量）。

---
**待用户拍板点**：是否批准 B（flow 粗位姿）改写 core？或先只跑 A（旋钮）看够不够？
