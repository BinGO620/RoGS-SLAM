"""instrument_v2_core.py — 仪器 v2 第三对照（深度-距离匹配）的纯函数核心。

prereg：results/lifecycle_paper2/evidence/prereg_instrument_v2.md（判据先锁，3cecccfe）。
可 CPU 单测（合成场景）；instrument_v2_rescore.py 调用本模块（GPU 主循环侧）。
"""
from __future__ import annotations

import numpy as np
import torch


def compute_matched_control_mask(gt_depth, dyn, past, valid_gt,
                                 band=0.15, edge_margin_px=15,
                                 support_min_px=200, sample_cap_px=5000,
                                 rng=None):
    """构造第三对照掩码（prereg §2）。

    参数（CPU torch 张量，gt_depth/valid_gt 同形状；dyn/past bool）：
      band            匹配带宽（相对 vac GT 深度中位数）
      edge_margin_px  距图像边缘排除宽度
      support_min_px  支撑下限（不足 ⇒ None，prereg §2）
      sample_cap_px   超上限时固定种子下采样到该值
      rng             可复现采样器（默认 np.random.RandomState(0)）

    返回：bool 张量（同形状，device 同 gt_depth）或 None（不可判）。
    约束：候选 = 静态（¬dyn ∧ ¬past）∧ 有效 ∧ 非边缘 ∧ GT 深度 ∈ 中心±带。
    深度源 = GT——被评对象不自证（prereg §2）。
    """
    if rng is None:
        rng = np.random.RandomState(0)
    if not isinstance(gt_depth, torch.Tensor):
        gt_depth = torch.as_tensor(gt_depth)
    if not isinstance(valid_gt, torch.Tensor):
        valid_gt = torch.as_tensor(valid_gt)
    dyn = torch.as_tensor(np.asarray(dyn, dtype=bool))
    past = torch.as_tensor(np.asarray(past, dtype=bool))
    vac = past & ~dyn & valid_gt
    n_vac = int(vac.sum())
    if n_vac == 0:
        return None
    z_med = float(gt_depth[vac].median())
    H, W = gt_depth.shape
    yy, xx = torch.meshgrid(torch.arange(H), torch.arange(W), indexing="ij")
    edge = ((xx < edge_margin_px) | (xx >= W - edge_margin_px)
            | (yy < edge_margin_px) | (yy >= H - edge_margin_px))
    cand = (~dyn) & (~past) & valid_gt & ~edge
    lo, hi = z_med * (1 - band), z_med * (1 + band)
    m3 = cand & (gt_depth >= lo) & (gt_depth <= hi)
    n_m3 = int(m3.sum())
    if n_m3 < support_min_px:
        return None
    if n_m3 > sample_cap_px:
        sel = rng.choice(n_m3, size=sample_cap_px, replace=False)
        idxs = torch.nonzero(m3)[torch.from_numpy(sel)]
        out = torch.zeros_like(m3)
        out[idxs[:, 0], idxs[:, 1]] = True
        return out
    return m3
