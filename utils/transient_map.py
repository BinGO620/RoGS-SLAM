"""transient_map — 把动态内容建进地图的最小机制（纯逻辑层，便于两态单测）。

设计（见 `results/transient_map/evidence/prereg_transient_map.md` 与其修正案 1）：

- **默认关闭**：`TransientMap.enabled: false`（缺省）⇒ 本模块的所有入口都返回"无操作"，
  主会话行为**逐位不变**（代码安全判据③）。
- **每帧插入**：以 `insert_stride` 抽帧、`max_points_per_frame` 限幅地对"动态掩码 ∧ 有效深度"
  的像素投候选；插入走既有 `insert_candidate_gaussians(..., lineage_ids=...)`，
  **每个插入批次一个 lineage id**（`t{frame}`）。
- **寿命硬删（修正案 1）**：插入时记 `γ`；`t − γ > beta_frames` 即过期，
  `t − γ > beta_frames + hard_delete_after` 时把该 lineage 交给既有 `prune_lineage` 删除。
  `retire_mode: "none"`（T0 消融）⇒ 永不退役。
- **错位对照**：`control_shift_m > 0` 时，插入点沿**相机系 x** 平移该距离（C− 臂，仪器判别力自检）。

本模块只做"何时插 / 插哪些 / 何时删 / 计数"的纯逻辑，不碰渲染与优化；
几何反投影与建基元由既有代码完成（`insert_candidate_gaussians`）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# 缺省值 = 关闭时的行为（`enabled=False` ⇒ 除 `enabled` 外的键在缺省下被忽略）
DEFAULTS = {
    "enabled": False,
    "retire_mode": "window",      # "window" = 有寿命窗（硬删）；"none" = 不退役（T0 消融）
    "beta_frames": 5,             # 寿命：一个 KF 跨度（该 run KF 间隔实测恒 5）
    "hard_delete_after": 10,      # 过期后再等这么多帧才真删（-1 = 不硬删）
    "insert_stride": 3,           # 每 3 帧插一次（与离线探针 unproj_stride 同量级）
    "max_points_per_frame": 3000,  # 每次插入的点数上限（成本判据 V4）
    "control_shift_m": 0.0,       # C− 臂 = 0.30；其余臂 = 0.0
}


def transient_cfg(config: dict) -> dict:
    """合并缺省；非法值直接抛错（配置是实验的唯一定义，不允许静默回退）。"""
    raw = dict(config.get("TransientMap") or {})
    cfg = dict(DEFAULTS)
    cfg.update(raw)
    if cfg["retire_mode"] not in ("window", "none"):
        raise ValueError(f"TransientMap.retire_mode 非法：{cfg['retire_mode']!r}")
    for k in ("beta_frames", "hard_delete_after", "insert_stride", "max_points_per_frame"):
        if not isinstance(cfg[k], int):
            raise ValueError(f"TransientMap.{k} 必须是 int，实为 {cfg[k]!r}")
    if cfg["insert_stride"] < 1:
        raise ValueError("TransientMap.insert_stride 必须 ≥1")
    if cfg["max_points_per_frame"] < 0:
        raise ValueError("TransientMap.max_points_per_frame 必须 ≥0（0 = 不插入）")
    if cfg["control_shift_m"] < 0:
        raise ValueError("TransientMap.control_shift_m 必须 ≥0")
    if cfg["enabled"] and cfg["beta_frames"] < 1:
        raise ValueError("启用时 beta_frames 必须 ≥1")
    return cfg


def transient_enabled(config: dict) -> bool:
    """唯一开关入口。缺省（无 TransientMap 段或 enabled 缺省）⇒ False。"""
    return bool(transient_cfg(config)["enabled"])


def should_insert(frame_idx: int, cfg: dict) -> bool:
    """抽帧规则：每 insert_stride 帧一次（frame 0 也插，保证冷启动帧有内容）。"""
    if not cfg["enabled"]:
        return False
    return frame_idx % cfg["insert_stride"] == 0


def select_indices(n_valid: int, cfg: dict) -> np.ndarray:
    """在 n_valid 个候选像素里做确定性抽样：先 stride，再按上限均匀截断。

    均匀截断（linspace）而非取前 N 个 —— 避免"只插图像左上角"的位置偏置。
    """
    if n_valid <= 0 or cfg["max_points_per_frame"] == 0:
        return np.zeros(0, dtype=np.int64)
    idx = np.arange(0, n_valid, cfg["insert_stride"], dtype=np.int64)
    cap = cfg["max_points_per_frame"]
    if idx.size > cap:
        take = np.linspace(0, idx.size - 1, cap).round().astype(np.int64)
        idx = idx[np.unique(take)]
    return idx


def gather_candidates(mask, depth, dmin: float = 0.2, dmax: float = 8.0):
    """"动态掩码 ∧ 有效深度"的像素坐标与深度。

    `mask`/`depth` 为 (H,W)；返回一维 `(ys, xs, zs)`（**行优先**顺序，供 `select_indices` 抽样）。
    深度有效区间沿用探针默认（dmin=0.2/dmax=8.0，与离线探针同口径）。
    """
    m = np.asarray(mask).astype(bool)
    z = np.asarray(depth, dtype=np.float32)
    ok = m & np.isfinite(z) & (z > float(dmin)) & (z < float(dmax))
    ys, xs = np.nonzero(ok)
    return ys, xs, z[ys, xs]


def apply_control_shift_px(px, depth, fx: float, shift_m: float):
    """C− 臂：把插入点沿**相机系 x** 平移 `shift_m` —— 在像素平面上等价于
    `Δpx = fx · shift_m / z`（逐点、与深度相关），随后由既有反投影得到相机系 x 的偏移。

    `shift_m <= 0` ⇒ 原样返回（不复制、不就地改）。
    """
    if shift_m <= 0:
        return px
    return px + float(fx) * float(shift_m) / np.maximum(np.asarray(depth, dtype=np.float64), 1e-3)


@dataclass
class TransientLedger:
    """记录每个插入批次的 lineage 与寿命，产出"本帧该删哪些 lineage"。

    纯逻辑（不依赖 torch / 模型），因此可离线单测；前端只负责把结果转成
    `insert_candidate_gaussians(..., lineage_ids=...)` 与 `request_prune(...)`。
    """

    cfg: dict
    inserted: dict = field(default_factory=dict)      # lineage_id -> {"frame": γ, "n": n_points}
    counters: list = field(default_factory=list)      # 逐帧计数（落盘用）

    def lineage_id(self, frame_idx: int) -> int:
        """一帧一个 lineage（frame 直接当 id；既有 lineage 是整数）。"""
        return int(frame_idx)

    def register(self, frame_idx: int, n_points: int) -> int:
        lid = self.lineage_id(frame_idx)
        self.inserted[lid] = {"frame": int(frame_idx), "n": int(n_points)}
        return lid

    def expiry_frame(self, frame_idx: int) -> int | None:
        """该帧插入的批次何时过期；retire_mode="none" ⇒ None（永不）。"""
        if self.cfg["retire_mode"] == "none":
            return None
        return int(frame_idx) + int(self.cfg["beta_frames"])

    def expired(self, frame_idx: int) -> list:
        """本帧应当**删除**的 lineage：已过期 且 超过 hard_delete_after（-1 ⇒ 只过期不删）。"""
        if self.cfg["retire_mode"] == "none" or self.cfg["hard_delete_after"] < 0:
            return []
        out = []
        for lid, rec in self.inserted.items():
            exp = rec["frame"] + int(self.cfg["beta_frames"])
            if frame_idx - exp > int(self.cfg["hard_delete_after"]):
                out.append(lid)
        return sorted(out)

    def forget(self, lineage_ids) -> None:
        for lid in lineage_ids:
            self.inserted.pop(lid, None)

    def active_count(self, frame_idx: int) -> int:
        """仍在寿命窗内的基元数（成本判据 V4 的在线读数）。"""
        if self.cfg["retire_mode"] == "none":
            return sum(r["n"] for r in self.inserted.values())
        return sum(r["n"] for r in self.inserted.values()
                   if frame_idx - r["frame"] <= int(self.cfg["beta_frames"]))

    def log(self, frame_idx: int, n_inserted: int, n_retired: int) -> None:
        self.counters.append({
            "frame": int(frame_idx),
            "transient_inserted_px": int(n_inserted),
            "transient_active": int(self.active_count(frame_idx)),
            "transient_retired": int(n_retired),
        })

    def write_csv(self, path) -> None:
        """逐帧计数落盘（DISCIPLINE #9：静默组件必须有落盘证据）。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = ("frame", "transient_inserted_px", "transient_active", "transient_retired")
        with open(path, "w", encoding="utf-8") as f:
            f.write(",".join(cols) + "\n")
            for row in self.counters:
                f.write(",".join(str(row[c]) for c in cols) + "\n")
