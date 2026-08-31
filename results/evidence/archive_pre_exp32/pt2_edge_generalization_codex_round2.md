# pt2 edge 通用性 + codex 第二轮对抗裁决（2026-08-10）

> exp-v3-13。pt2 edge=3.0 通用性确认；codex 第二轮对抗审查给了精确机制定位 + 唯一判别实验。

## pt2 edge=3.0（person 序列通用性）

| | seed0/1/2 | mean | RPE |
|---|---|---|---|
| pt2 baseline mask-ON | — | 10.44 | ~1.6 |
| pt2 edge=3.0 | 9.04/9.22/8.92 | **9.06** | **1.46** |

**edge 增益跨 person 序列成立**（pt1 9.16 / pt2 9.06），低纹理抑制是一般增益，非 pt1 特异。

## codex 第二轮对抗审查要点（kmtwnhcm6）

1. **H-e 实测 = 纯语义硬挡**（combined 配置 `FlowResidualTracking.enabled:false`，`dyn_mask=semantic_mask`，
   reliability flow 只进 soft 不进 hard mask）。**flow-mask confound 不存在，不需重测 semantic-only。**
2. **H-e 失败在迭代 10 后的 pose-refinement 阶段**（基线 0-9 也硬挡、10 后切 soft；H-e 全程硬挡）。
3. **"欠约束"是 plausible 未严格证**（需 pose-Hessian 条件数；库里有 `dba_lite.py:577` 的条件数机制）。
   **"人体边界是有效约束"站不住**——edge=3 赢可能只因选的是背景结构，7px 膨胀带连背景也一起挡。
4. **不追"每帧像素加权"够 RGD 7.2**：RGD pt1 ATE 7.21 但 RPE 2.52 + 路径比 145-150%，
   **我们 edge=3 的 RPE 1.60 已优于 RGD**。靠局部像素加权关闭 ATE 差距不是良定义目标。
5. **裁决**：(a) 不重测 semantic-only；(b) 只跑一个 interior-vs-boundary 判别实验（带 Hessian 诊断）；
   (c) 无改善则接受 edge=3（9.16）为当前 tracking 公式经验上限（**非**数据集 floor——DG 4.25/WildGS 3.63 证明）。

## 下一步：唯一判别实验（E factorial，带条件数诊断）
- A: edge=3（已有 9.16）
- B: edge=3 + 全语义硬挡（只留强背景边缘）
- C: edge=3 + 只抑制人体内部（erode mask，留边界带+背景）
- 判据：≥0.5cm 提升 + RPE/路径不退化 + 种子稳；否则接受 9.16 floor，转向 long-horizon 位姿正则 / KF-BA。
