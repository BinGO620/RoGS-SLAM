"""obsdebt.py — 观测债补偿（prereg_L1f_obsdebt，D2-011 ②；default-off）。

机制（信息/资源分配级，无新门/阈值/状态机——判据层冻结承诺）
--------------------------------------------------------------
腾空区在"被动态掩码占据期"被挡出渲染监督（观测债）。本模块维护一张
**世界空间体素债账本**：掩码每覆盖一个 voxel 一帧，其债务计数 +1（``observe``）；
计数不衰减、不淘汰（债不因时间流逝而消失——这是与 L1c OccupancyMemory 的
本质区别：那边是"最近 K 帧占据过"的窗口语义，这边是**累计欠账**）。

分配律（纯资源分配）：腾空区像素脱离掩码后（fill 管线的 vacated 像素 / 高债区
基元），按其 voxel 债务 D(x) 获得加权分配——
  * fill 插入配额：高债 vacated 像素在 ``fill_max_points`` 预算内优先保留
    （排序键 = 债务降序，替代原均匀 linspace 下采样）；
  * 额外局部迭代配额：``debt_iter_boost``——高债区新插入基元的优化步数放大
    （以 fill 插入后的自然优化步为基准，乘 (1+boost·D̂)，D̂ = 归一化债务）。

安全性（与 L1b/L1c 同款护栏形状，测试照 tests/lifecycle_paper2/test_evidence_gate.py）：
* **default-off**：``obsdebt: false`` 时整条路径不进入，与主线逐位一致；
* 纯函数：账本只读不写在查询侧；分配只重排/加权既有预算，**不新增任何删除门**；
* 债账本体量有界：只有被掩码击中的 voxel 才入账（与 L1c 同款单 KF 上界）；
* ATE 保护：不触碰任何 α / 位姿 / 频率结构（只动 fill 预算分配与插入后迭代配额）。

体素键约定抄 ``utils/occupancy_memory.py``（W2C→C2W，键 = x·4194304+y·2048+z）。
"""
from __future__ import annotations

import torch

VOX_KEY_X = 4194304   # 与 occupancy_memory.py 一致的空间哈希基数
VOX_KEY_Y = 2048


def unproject_flatidx_to_voxels(mask_flat_idx, depth, viewpoint, voxel_size: float) -> torch.Tensor:
    """掩码 flat 索引 + 传感器深度 + 当前位姿 → voxel 键（与 occupancy_memory 同式）。"""
    if mask_flat_idx is None or mask_flat_idx.numel() == 0:
        return torch.zeros(0, dtype=torch.int64, device=depth.device)
    H, W = depth.shape
    ys = (mask_flat_idx // W).float()
    xs = (mask_flat_idx % W).float()
    z = depth.flatten()[mask_flat_idx].float()
    ok = torch.isfinite(z) & (z > 0.01)
    if not bool(ok.any()):
        return torch.zeros(0, dtype=torch.int64, device=depth.device)
    xs, ys, z = xs[ok], ys[ok], z[ok]
    R = viewpoint.R.detach().to(z.device).float()
    T = viewpoint.T.detach().to(z.device).float()
    x_cam = (xs - viewpoint.cx) / viewpoint.fx * z
    y_cam = (ys - viewpoint.cy) / viewpoint.fy * z
    pts_cam = torch.stack([x_cam, y_cam, z, torch.ones_like(z)], dim=-1)
    W2C = torch.eye(4, dtype=torch.float32, device=z.device)
    W2C[:3, :3] = R
    W2C[:3, 3] = T
    C2W = torch.linalg.inv(W2C)
    pts_w = (C2W @ pts_cam.T).T[:, :3]
    vox = torch.floor(pts_w.double() / voxel_size).to(torch.int64)
    return torch.unique(vox[:, 0] * VOX_KEY_X + vox[:, 1] * VOX_KEY_Y + vox[:, 2])


def unproject_pixels_to_voxels(uu, vv, depth_hw, viewpoint, voxel_size: float) -> torch.Tensor:
    """fill 的 vacated 像素 + 传感器深度 + 当前位姿 → 整数 voxel 键（int64，去重前）。

    与 occupancy_memory.unproject_mask_to_voxels 同约定，但输入是显式像素坐标
    （fill 管线给的是 (uu, vv)，不是 flat idx）。
    """
    if uu is None or len(uu) == 0:
        return torch.zeros(0, dtype=torch.int64, device=depth_hw.device)
    xs = torch.as_tensor(uu, dtype=torch.float32, device=depth_hw.device)
    ys = torch.as_tensor(vv, dtype=torch.float32, device=depth_hw.device)
    z = depth_hw[ys.long(), xs.long()].float()
    ok = torch.isfinite(z) & (z > 0.01)
    if not bool(ok.any()):
        return torch.zeros(0, dtype=torch.int64, device=depth_hw.device)
    xs, ys, z = xs[ok], ys[ok], z[ok]
    R = viewpoint.R.detach().to(z.device).float()
    T = viewpoint.T.detach().to(z.device).float()
    x_cam = (xs - viewpoint.cx) / viewpoint.fx * z
    y_cam = (ys - viewpoint.cy) / viewpoint.fy * z
    pts_cam = torch.stack([x_cam, y_cam, z, torch.ones_like(z)], dim=-1)
    W2C = torch.eye(4, dtype=torch.float32, device=z.device)
    W2C[:3, :3] = R
    W2C[:3, 3] = T
    C2W = torch.linalg.inv(W2C)
    pts_w = (C2W @ pts_cam.T).T[:, :3]
    # floor(x/vs)：同 occupancy_memory——torch 2.1 的 div floor 模式对边界值截断
    vox = torch.floor(pts_w.double() / voxel_size).to(torch.int64)
    return vox[:, 0] * VOX_KEY_X + vox[:, 1] * VOX_KEY_Y + vox[:, 2]


class ObsDebtLedger:
    """世界空间 voxel 的累计观测债表：被掩码覆盖一帧 = 该 voxel 债务 +1。

    债务**不衰减不淘汰**（欠账语义）。表体量上界 = 掩码击中过的 voxel 总数
    （单 KF 上界 = 掩码像素数；与 L1c 同款纪律）。
    """

    def __init__(self, voxel_size: float):
        self.voxel_size = float(voxel_size)
        self._keys = torch.zeros(0, dtype=torch.int64)
        self._debt = torch.zeros(0, dtype=torch.int64)
        self._dev: torch.device | None = None
        self.n_updates = 0
        self.n_voxs_total = 0      # 累计（含重复）掩码击中 voxel 数（点火计数诊断）

    # ---------------------------------------------------------------- update
    def observe(self, vox_keys: torch.Tensor) -> None:
        """合并一个 KF 的掩码覆盖：debt[key] += 1（每个 KF 每个 voxel 至多 +1）。"""
        if vox_keys is None or vox_keys.numel() == 0:
            return
        if self._dev is None:
            self._dev = vox_keys.device
            self._keys = self._keys.to(self._dev)
            self._debt = self._debt.to(self._dev)
        vox_keys = vox_keys.to(self._dev)
        uniq, counts = torch.unique(vox_keys, return_counts=True)
        self.n_voxs_total += int(uniq.numel())
        n0 = self._keys.numel()
        pos = torch.searchsorted(self._keys, uniq) if n0 else torch.zeros_like(uniq)
        pos_c = pos.clamp(max=n0 - 1) if n0 else pos
        hit = (self._keys[pos_c] == uniq) if n0 else torch.zeros_like(uniq, dtype=torch.bool)
        self._debt[pos_c[hit]] += counts[hit]
        new_keys = uniq[~hit]
        if new_keys.numel():
            self._keys = torch.cat([self._keys, new_keys])
            self._debt = torch.cat([self._debt, counts[~hit]])
            order = torch.argsort(self._keys)
            self._keys = self._keys[order]
            self._debt = self._debt[order]
        self.n_updates += 1

    # ----------------------------------------------------------------- query
    def debt_at(self, vox_keys: torch.Tensor) -> torch.Tensor:
        """查询 voxel 债务（无记录 = 0）。纯函数：不改表。"""
        n = vox_keys.numel()
        if self._keys.numel() == 0 or n == 0:
            return torch.zeros(n, dtype=torch.int64, device=vox_keys.device)
        keys = vox_keys.to(self._keys.device)
        pos = torch.searchsorted(self._keys, keys)
        pos_c = pos.clamp(max=self._keys.numel() - 1)
        hit = self._keys[pos_c] == keys
        out = torch.zeros(n, dtype=torch.int64, device=self._keys.device)
        out[hit] = self._debt[pos_c[hit]]
        return out.to(vox_keys.device)


def xyz_to_voxels(xyz: torch.Tensor, voxel_size: float) -> torch.Tensor:
    """基元世界坐标 → voxel 键（查询用；与 unproject 同哈希约定）。"""
    if xyz is None or xyz.numel() == 0:
        return torch.zeros(0, dtype=torch.int64, device=xyz.device if xyz is not None else None)
    vox = torch.floor(xyz.detach().double() / voxel_size).to(torch.int64)
    return vox[:, 0] * VOX_KEY_X + vox[:, 1] * VOX_KEY_Y + vox[:, 2]


def fill_budget_by_debt(uu, vv, vox_keys, ledger, max_points: int):
    """fill 插入配额按债分配（纯函数；替代均匀下采样）。

    vacated 像素 ≤ max_points 时原样返回（不重排——保序与旧管线一致）；
    超预算时按债务**降序**保留前 max_points 个（同债内按原顺序稳定）。
    返回 ``(uu_sel, vv_sel, stats_dict)``；stats 含 kept/dropped/debt_max。
    """
    import numpy as np
    uu = np.asarray(uu)
    vv = np.asarray(vv)
    stats = {"kept": int(uu.size), "dropped": 0, "debt_max": 0}
    if uu.size <= max_points:
        return uu, vv, stats
    d = ledger.debt_at(vox_keys).detach().cpu().numpy()
    stats["debt_max"] = int(d.max()) if d.size else 0
    # 稳定排序：债务降序，同债保持原相对顺序（kind='stable'）
    order = np.argsort(-d, kind="stable")[:max_points]
    order.sort()   # 恢复原像素顺序，保 fill 管线下游确定性
    uu_sel, vv_sel = uu[order], vv[order]
    stats["kept"] = int(uu_sel.size)
    stats["dropped"] = int(uu.size - uu_sel.size)
    return uu_sel, vv_sel, stats
