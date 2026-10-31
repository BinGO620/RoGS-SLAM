"""occupancy_memory.py — L1c 时序先验：区域占据记忆（D2-006，default-off）。

机制（prereg_L1c_occupancy.md 锁定；2026-09-22）
------------------------------------------------
逐帧运行的语义掩码是瞬时的。把"这块 3D 区域最近 K 个 KF 内被运行期人物掩码占据过"
积成一张世界空间 voxel 时间戳表，并对**温暖区**（窗口内被占据过）内的**低 α** 基元
按每 KF γ 做乘法衰减。三条 α 通路里唯一不受几何合取门约束的一条：

* reset/carve 都要求 ``in_front``（z < obs_at − δ）——pt 续命场景 z ≈ obs_at ⇒ 结构性
  不可达（postmortem：a_min 钉死 0.2199 > tau_carve 0.20）；
* L1b evidence gate 只封顶不下降 ⇒ α 停在 0.22；
* **occupancy decay 无几何门**：直接把温暖区低 α 推向 0。

安全性（证明照 L1b 形状，测试照 tests/lifecycle_paper2/test_evidence_gate.py）：
* 净静态结构 α≈1 > occupancy_alpha_guard（=tau_reset=0.35）⇒ **永不被触碰**；
  掩码/体素 FP 的天花板伤害 = 0；
* 伤害只落在"本就低 α（<guard）"的群体——按定义已是不确定内容（T3 的区别：即时
  硬覆写 vs 乘法衰减 + 护栏 + 有界次数）；
* 单帧 FP 的累计效应有界：γ^K 上界（K = warm 窗口长度）。

体素键与反投影约定抄 ``utils/mask_stability.py``（W2C→C2W，键 = x·4194304+y·2048+z）；
表活在 GaussianModel 之外（per-region，不碰 densification/prune 同步点）。
"""
from __future__ import annotations

import torch

VOX_KEY_X = 4194304   # 与 mask_stability.py 一致的空间哈希基数
VOX_KEY_Y = 2048


def unproject_mask_to_voxels(mask_flat_idx, depth, viewpoint, voxel_size: float) -> torch.Tensor:
    """掩码像素 + 传感器深度 + 当前位姿 → 整数 voxel 键（int64, 去重后）。

    ``mask_flat_idx``: (M,) long —— 掩码像素在 H×W 展平后的索引。
    ``depth``: (H, W) —— 传感器深度（米）；无效/零深度像素被丢弃。
    """
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
    pts_cam = torch.stack([x_cam, y_cam, z, torch.ones_like(z)], dim=-1)  # (N, 4)
    W2C = torch.eye(4, dtype=torch.float32, device=z.device)
    W2C[:3, :3] = R
    W2C[:3, 3] = T
    C2W = torch.linalg.inv(W2C)
    pts_w = (C2W @ pts_cam.T).T[:, :3]
    # floor(x/vs) 而非 div(rounding_mode='floor')：torch 2.1 CPU 的 floor 模式
    # 对边界值直接截断（5.0/0.05=100.0 被 floor 成 99），普通除法+floor 才对
    vox = torch.floor(pts_w.double() / voxel_size).to(torch.int64)
    return torch.unique(vox[:, 0] * VOX_KEY_X + vox[:, 1] * VOX_KEY_Y + vox[:, 2])


class OccupancyMemory:
    """世界空间 voxel 的"最近被占据 KF 时间戳"表。

    每个被运行期掩码击中的 voxel 记录最后被占据的 KF 序号；查询 =
    "now − last ≤ warm_kfs" 的键集合。窗口外条目在更新时惰性清理（体量上界 =
    单 KF 掩码像素数 × warm_kfs 量级）。
    """

    def __init__(self, voxel_size: float, warm_kfs: int):
        self.voxel_size = float(voxel_size)
        self.warm_kfs = int(warm_kfs)
        self._keys = torch.zeros(0, dtype=torch.int64)      # 排序
        self._last = torch.zeros(0, dtype=torch.int64)      # 最后占据 KF uid
        self._dev: torch.device | None = None
        self.n_updates = 0
        self.n_evictions = 0

    # ---------------------------------------------------------------- update
    def observe(self, vox_keys: torch.Tensor, kf_uid: int) -> None:
        """合并一个 KF 的占据观测：last[key] = kf_uid（max）。"""
        if vox_keys is None or vox_keys.numel() == 0:
            return
        if self._dev is None:
            self._dev = vox_keys.device
            self._keys = self._keys.to(self._dev)
            self._last = self._last.to(self._dev)
        vox_keys = vox_keys.to(self._dev)
        n0 = self._keys.numel()
        # merge：先筛掉已存在的（原地更新 last=max），再追加新键
        pos = torch.searchsorted(self._keys, vox_keys) if n0 else torch.zeros_like(vox_keys)
        pos_c = pos.clamp(max=n0 - 1) if n0 else pos
        hit = (self._keys[pos_c] == vox_keys) if n0 else torch.zeros_like(vox_keys, dtype=torch.bool)
        self._last[pos_c[hit]] = torch.maximum(self._last[pos_c[hit]],
                                               torch.full_like(vox_keys[hit], kf_uid))
        new_keys = vox_keys[~hit]
        if new_keys.numel():
            self._keys = torch.cat([self._keys, new_keys])
            self._last = torch.cat([self._last,
                                    torch.full((new_keys.numel(),), kf_uid,
                                               dtype=torch.int64, device=self._dev)])
            order = torch.argsort(self._keys)
            self._keys = self._keys[order]
            self._last = self._last[order]
        self._evict(kf_uid)
        self.n_updates += 1

    def _evict(self, kf_uid: int) -> None:
        """窗口外条目惰性清理（体量上界纪律）。"""
        if self._keys.numel() == 0:
            return
        keep = self._last >= kf_uid - self.warm_kfs
        self.n_evictions += int((~keep).sum())
        if not bool(keep.all()):
            self._keys = self._keys[keep]
            self._last = self._last[keep]

    # ----------------------------------------------------------------- query
    def warm_mask(self, xyz: torch.Tensor, kf_uid: int) -> torch.Tensor:
        """基元坐标 → bool (N,)：落在温暖区（now − last ≤ warm_kfs）。"""
        n = xyz.shape[0]
        if self._keys.numel() == 0:
            return torch.zeros(n, dtype=torch.bool, device=xyz.device)
        # floor(x/vs) 而非 div(rounding_mode='floor')：同 unproject——torch 2.1
        # CPU 的 floor 模式对边界值（5.0/0.05=100.0）直接截断成 99 ⇒ 静默漏检
        vox = torch.floor(xyz.double() / self.voxel_size).to(torch.int64)
        keys = vox[:, 0] * VOX_KEY_X + vox[:, 1] * VOX_KEY_Y + vox[:, 2]
        pos = torch.searchsorted(self._keys, keys)
        pos_c = pos.clamp(max=self._keys.numel() - 1)
        hit = self._keys[pos_c] == keys
        warm = hit & ((kf_uid - self._last[pos_c]) <= self.warm_kfs)
        return warm


def apply_occupancy_decay(alpha: torch.Tensor, warm: torch.Tensor,
                          guard: float, decay: float):
    """温暖区内低 α 基元乘法衰减（纯函数）。

    返回 ``(alpha_new, decayed_mask)``。安全性核心：``alpha ≥ guard`` 的基元
    **永不触碰**（净静态结构 α≈1 的天花板伤害 = 0）；``warm`` 之外的基元不动。
    """
    hit = warm & (alpha < guard)
    out = alpha.clone()
    out[hit] = out[hit] * decay
    return out, hit
