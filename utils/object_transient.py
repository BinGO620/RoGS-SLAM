"""object_transient.py — E2 对象级瞬态层的**纯逻辑核**（在线实装，prereg_E2_online.md §2）。

设计原则（与预注册一致）：

1. **纯逻辑、零 torch**：本模块只做"从逐帧观测到该插/该删什么"的决策，产出**载荷**
   （像素 + 深度 + 颜色 + lineage + 用哪台相机），由前端转成既有消息
   `insert_candidates_cam` / `request_prune`（`utils/slam_frontend.py:1522/:1679`）。
   ⇒ 可离线单测，且**不碰核心三处**（例外流程②③）。
2. **默认关闭 = 逐位一致**：`enabled=False` ⇒ `step()` 立即返回空结果、零状态改动
   （与 `TransientMap` 的两态做法同源，`utils/transient_map.py:26`）。
3. **对象级有界**：每 tracklet 一个簇、**逐帧替换不累积**、`n_absent` 帧无命中 ⇒ 整对象退役。
4. **占用证据回填**：对象让出的体素用**该 tracklet 到来之前最近 ≤K 帧**的**传感器**深度/RGB 回填，
   源帧像素**不得落在该帧掩码内**（否则会采到物体自身），并以"静态图该处无支撑"为**占用门**。
5. **禁用 GT**：只接受调用方传入的 `pose_c2w` 与 `depth`/`rgb`/`mask`；本模块**不读**任何
   `groundtruth` / 数据集文件（§5⑩ 的运行时断言与此配套）。

术语：voxel key = `tuple(floor(world_xyz / voxel_m))`（与探针 `_voxel_keys` 同口径）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# 缺省值 = 关闭时的行为（`enabled=False` ⇒ 其余键被忽略）
DEFAULTS = {
    "enabled": False,
    "voxel_m": 0.02,
    "stride": 3,
    "topk": 3,
    "min_area_px": 200,
    "min_area_frac": 0.05,
    "assoc_gate_m": 0.5,
    "n_absent": 3,
    "max_points_per_object": 4000,
    "max_objects_per_frame": 3,
    "fill_enabled": True,
    "fill_gate_m": 0.05,
    "fill_source_frames": 3,
    "ring_frames": 32,
    "fill_max_per_frame": 8000,
    "fill_max_total": 0,      # 累计回填预算（0 = 不限）；§9-ter H-B 在线的落地（探针用 fill_max_frac=0.03）
    "fill_scan_per_frame": 20000,   # 每帧最多扫多少待回填体素（成本上界）
    "fit_iters": 0,          # 0 = 不拟合（与主线逐位一致）；>0 才发观测载荷
    "fit_fill": False,       # fit-fill（R2 修正案件②）：fill 批用**源帧**观测拟合（默认关 = 逐位一致）
    "fit_fill_iters": 20,    # fit-fill 的拟合步数（fit_fill 开时生效）
    "lineage_base": 1 << 28,  # 避开 LineageAllocator 的 0..N 段（int32 内）
    "control_shift_m": 0.0,   # C− 阴性对照臂（A2）：插入载荷相机系横移
}

_INT_KEYS = ("stride", "topk", "min_area_px", "n_absent", "max_points_per_object",
             "max_objects_per_frame", "fill_source_frames", "ring_frames",
             "fill_max_per_frame", "fill_max_total", "fill_scan_per_frame", "fit_iters", "fit_fill_iters",
             "lineage_base")
_NUM_KEYS = ("voxel_m", "assoc_gate_m", "fill_gate_m", "control_shift_m")


def object_transient_cfg(config: dict) -> dict:
    """合并缺省；非法值直接抛错（config 是实验的唯一定义，不允许静默回退）。"""
    cfg = dict(DEFAULTS)
    cfg.update(dict(config.get("E2ObjectLayer") or {}))
    for k in _INT_KEYS:
        if not isinstance(cfg[k], int) or isinstance(cfg[k], bool):
            raise ValueError(f"E2ObjectLayer.{k} 必须是 int，实为 {cfg[k]!r}")
    for k in _NUM_KEYS:
        if not isinstance(cfg[k], (int, float)) or isinstance(cfg[k], bool):
            raise ValueError(f"E2ObjectLayer.{k} 必须是数，实为 {cfg[k]!r}")
    if not isinstance(cfg["enabled"], bool) or not isinstance(cfg["fill_enabled"], bool) \
            or not isinstance(cfg["fit_fill"], bool):
        raise ValueError("E2ObjectLayer.{enabled,fill_enabled,fit_fill} 必须是 bool")
    for k, lo in (("stride", 1), ("topk", 1), ("n_absent", 1), ("ring_frames", 1),
                  ("fill_source_frames", 1), ("max_objects_per_frame", 1),
                  ("fill_scan_per_frame", 1)):
        if cfg[k] < lo:
            raise ValueError(f"E2ObjectLayer.{k} 必须 ≥{lo}，实为 {cfg[k]}")
    for k in ("voxel_m",):
        if cfg[k] <= 0:
            raise ValueError(f"E2ObjectLayer.{k} 必须 >0，实为 {cfg[k]}")
    for k in ("min_area_px", "max_points_per_object", "fill_max_per_frame", "fill_max_total", "fit_iters",
              "fit_fill_iters", "lineage_base", "control_shift_m", "assoc_gate_m", "fill_gate_m"):
        if cfg[k] < 0:
            raise ValueError(f"E2ObjectLayer.{k} 必须 ≥0，实为 {cfg[k]}")
    return cfg


def object_transient_enabled(config: dict) -> bool:
    """唯一开关入口。缺省（无 E2ObjectLayer 段或 enabled 缺省）⇒ False。"""
    return bool(object_transient_cfg(config)["enabled"])


# ────────────────────────── 纯函数 ──────────────────────────

def voxel_keys(points, voxel_m: float) -> np.ndarray:
    """(N,3) 世界点 → (N,3) int64 体素键。"""
    return np.floor(np.asarray(points, dtype=np.float64) / float(voxel_m)).astype(np.int64)


def component_masks(mask, min_area_px: int, min_area_frac: float, topk: int):
    """连通域（8 邻接）→ 面积降序 top-k、达阈的域布尔掩码列表。

    阈 = `max(min_area_px, min_area_frac · 最大域面积)`（与探针 `_components` 同口径）。
    """
    from scipy import ndimage

    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return []
    lab, n = ndimage.label(m, structure=np.ones((3, 3), dtype=int))
    if n == 0:
        return []
    sizes = ndimage.sum(m, lab, index=np.arange(1, n + 1))
    thr = max(float(min_area_px), float(min_area_frac) * float(sizes.max()))
    order = [i + 1 for i in np.argsort(sizes)[::-1] if sizes[i] >= thr][: int(topk)]
    return [(lab == l) for l in order]


def sample_pixels(mask, depth, rgb, stride: int, dmin: float = 0.2, dmax: float = 8.0):
    """掩码 ∧ 有效深度 ⇒ 下采样像素 (px, py, d, color)；`rgb` 支持 (3,H,W) 或 (H,W,3)。"""
    depth = np.asarray(depth, dtype=np.float32)
    m = np.asarray(mask, dtype=bool) & np.isfinite(depth) & (depth > dmin) & (depth < dmax)
    vs, us = np.nonzero(m)
    if vs.size:
        keep = ((vs % stride) == 0) & ((us % stride) == 0)
        vs, us = vs[keep], us[keep]
    if vs.size == 0:
        z = np.empty(0, np.int64)
        return z, z, np.empty(0, np.float32), np.empty((0, 3), np.float32)
    d = depth[vs, us]
    img = np.asarray(rgb, dtype=np.float32)
    cols = img[:, vs, us].T if (img.ndim == 3 and img.shape[0] == 3) else img[vs, us]
    return us.astype(np.int64), vs.astype(np.int64), d, cols.astype(np.float32)


def centroid_world(px, py, d, pose_c2w, fx, fy, cx, cy) -> np.ndarray:
    """像素+深度 → 世界系点云（`pose_c2w` 4×4）。"""
    d = np.asarray(d, dtype=np.float64)
    x = (np.asarray(px, dtype=np.float64) - cx) * d / fx
    y = (np.asarray(py, dtype=np.float64) - cy) * d / fy
    c2w = np.asarray(pose_c2w, dtype=np.float64)
    return (c2w[:3, :3] @ np.stack([x, y, d], 1).T).T + c2w[:3, 3]


def control_shift_px(px, d, fx, shift_m: float) -> np.ndarray:
    """C− 阴性对照（A2）：相机系横向错位 → 像素偏移（与 `transient_map` 同式）。"""
    px = np.asarray(px, dtype=np.float64)
    if shift_m == 0.0:
        return px
    return px + float(fx) * float(shift_m) / np.maximum(np.asarray(d, dtype=np.float64), 1e-3)


def occupancy_gate(centers, static_xyz, gate_m: float) -> np.ndarray:
    """占用门：返回"静态图无支撑"（KNN 距离 > gate_m）的布尔掩码。

    依据（E2 L2 失败模式诊断）：无条件回填使 fill/n_static 达 1.2–2.3 ⇒ 静态区被错误背景覆盖（J3 破）。
    """
    if static_xyz is None or len(static_xyz) == 0 or len(centers) == 0:
        return np.ones(len(centers), dtype=bool)
    from scipy.spatial import cKDTree

    dmin, _ = cKDTree(np.asarray(static_xyz, dtype=np.float64)).query(
        np.asarray(centers, dtype=np.float64), k=1)
    return dmin > float(gate_m)


def project_to_camera(world_pt, cam: dict):
    """世界点 → 相机像素 (u,v)；不可见/背向/出界 ⇒ None。"""
    c2w = np.asarray(cam["c2w"], dtype=np.float64)
    p_c = c2w[:3, :3].T @ (np.asarray(world_pt, dtype=np.float64) - c2w[:3, 3])
    if p_c[2] <= 1e-6:
        return None
    u = int(round(cam["fx"] * p_c[0] / p_c[2] + cam["cx"]))
    v = int(round(cam["fy"] * p_c[1] / p_c[2] + cam["cy"]))
    if not (0 <= u < int(cam["W"]) and 0 <= v < int(cam["H"])):
        return None
    return u, v


class ObservationRing:
    """过去帧观测环形缓冲（深度/RGB/语义掩码/相机）——回填的**唯一**来源；只存传感器数据。"""

    def __init__(self, capacity: int):
        if int(capacity) < 1:
            raise ValueError("ObservationRing capacity 必须 ≥1")
        self.capacity = int(capacity)
        self._items: dict[int, dict] = {}
        self._order: list[int] = []

    def add(self, frame_idx: int, depth, rgb, mask, cam: dict) -> None:
        k = int(frame_idx)
        if k in self._items:
            return
        self._items[k] = {"frame": k,
                          "depth": np.asarray(depth, dtype=np.float32),
                          "rgb": np.asarray(rgb, dtype=np.float32),
                          "mask": np.asarray(mask, dtype=bool) if mask is not None else None,
                          "cam": dict(cam)}
        self._order.append(k)
        while len(self._order) > self.capacity:
            self._items.pop(self._order.pop(0), None)

    def frames_before(self, frame_idx: int, k: int) -> list:
        """该帧**之前**最近的 ≤k 个已缓存帧（升序）。"""
        prior = sorted(f for f in self._order if f < int(frame_idx))
        return prior[-int(k):]

    def get(self, frame_idx: int):
        return self._items.get(int(frame_idx))

    def __len__(self) -> int:
        return len(self._order)


@dataclass
class InsertBatch:
    """一批插入基元（载荷 = 既有 `insert_candidates_cam` 消息的字段）。"""

    kind: str            # "object" | "fill"
    lineage_id: int
    cam: dict            # {fx,fy,cx,cy,R,T}（回填批 = **源帧**相机）
    px: np.ndarray
    py: np.ndarray
    depth: np.ndarray
    color: np.ndarray
    src_frame: int | None = None

    @property
    def n(self) -> int:
        return int(np.asarray(self.px).shape[0])


@dataclass
class ObjectLedger:
    """对象层记账（lineage 寿命 + 逐帧计数；DISCIPLINE #9 落盘证据）。"""

    lineage_base: int
    issued: dict = field(default_factory=dict)
    counters: list = field(default_factory=list)
    _next: int = 0

    def issue(self, object_id: int, kind: str, frame_idx: int) -> int:
        lid = int(self.lineage_base) + self._next
        self._next += 1
        self.issued[lid] = {"object": int(object_id), "kind": str(kind), "frame": int(frame_idx)}
        return lid

    def retire(self, lineage_ids) -> None:
        for lid in lineage_ids:
            self.issued.pop(int(lid), None)

    def active_lineages(self) -> list:
        return sorted(self.issued)

    def log(self, frame_idx: int, stats: dict) -> None:
        self.counters.append({"frame": int(frame_idx), **stats})

    def write_csv(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = ("frame", "n_tracklets", "n_object_points", "n_fill_points",
                "n_retired", "n_inserted_total", "n_track_points", "ring_frames",
                "vacated", "gate_blocked", "no_source", "filled", "capped", "budget_hit", "obj_capped",
                "pending", "n_static_pts")
        with open(path, "w", encoding="utf-8") as f:
            f.write(",".join(cols) + "\n")
            for row in self.counters:
                f.write(",".join(str(row.get(c, 0)) for c in cols) + "\n")


def to_np(x):
    """torch tensor（含 CUDA）/numpy → numpy。

    为何需要它：快筛崩过两次——CUDA tensor 不能 `np.asarray`（须 `.detach().cpu().numpy()`）。
    """
    if x is None:
        return None
    if hasattr(x, "detach"):
        return x.detach().cpu().numpy()
    return np.asarray(x)


def rt44(R, T) -> np.ndarray:
    """(R, T) → 4×4 世界←相机 变换。"""
    m = np.eye(4)
    m[:3, :3] = np.asarray(R, dtype=np.float64)
    m[:3, 3] = np.asarray(T, dtype=np.float64)
    return m


def build_insert_message(batch, min_scale, max_scale, fit_iters, obs=None) -> list:
    """一批对象层基元 → 后端 `insert_candidates_cam` 消息（与既有契约逐字段对齐）。

    契约（`utils/slam_backend.py` 的 handler）：`[tag, fx, fy, cx, cy, R, T, px, py, depth,
    color, lineage_id, min_scale, max_scale, fit_iters[, image, depth_map, mask]]`；
    `fit_iters>0` 时尾部必须带观测三元组（image (3,H,W) float32 / depth (H,W) / mask (H,W) bool）。
    """
    cam = batch.cam
    msg = [
        "insert_candidates_cam",
        float(cam["fx"]), float(cam["fy"]), float(cam["cx"]), float(cam["cy"]),
        np.asarray(cam["R"], dtype=np.float32), np.asarray(cam["T"], dtype=np.float32),
        np.asarray(batch.px, dtype=np.float32), np.asarray(batch.py, dtype=np.float32),
        np.asarray(batch.depth, dtype=np.float32), np.asarray(batch.color, dtype=np.float32),
        int(batch.lineage_id), float(min_scale), float(max_scale), int(fit_iters),
    ]
    if int(fit_iters) > 0:
        if obs is None:
            raise ValueError("fit_iters>0 但未携带观测（观测必须与所用相机同源）")
        msg += [np.ascontiguousarray(obs["image"], dtype=np.float32),
                np.ascontiguousarray(obs["depth"], dtype=np.float32),
                np.ascontiguousarray(obs["mask"], dtype=bool)]
    return msg


class ObjectLayer:
    """对象级瞬态层的逐帧决策核（纯逻辑；前端按返回值发消息）。

    `step(...)` 返回 `(inserts, retire_lineage_ids, stats)`：
      * `inserts`：本帧插入批（object 批用**当前帧**相机；fill 批用**源帧**相机）；
      * `retire_lineage_ids`：本帧要 `request_prune` 的 lineage（整对象退役）；
      * `stats`：逐帧计数（含 `n_track_points` = 对象层簇规模，供 V4③ 非累积判据）。
    """

    def __init__(self, cfg: dict, ring: ObservationRing | None = None):
        self.cfg = cfg
        self.ring = ring if ring is not None else ObservationRing(cfg["ring_frames"])
        self.ledger = ObjectLedger(cfg["lineage_base"])
        self.tracks: list[dict] = []
        self.blocked: dict[int, dict] = {}   # object_id -> {"keys": set, "birth": int}
        self._next_obj = 0
        self._inserted_total = 0
        self._last_disp = 0.0
        self._pending_pts = np.empty((0, 3), np.float32)
        self._pending_cols = np.empty((0, 3), np.float32)
        # 回填诊断（DISCIPLINE #9：静默组件必须有落盘证据）——把"为什么没填"变成可量化读数
        self._fill_total = 0
        self.fill_diag = {"vacated": 0, "gate_blocked": 0, "no_source": 0, "filled": 0, "budget_hit": 0,
                          "capped": 0, "obj_capped": 0}

    # ── 主入口 ──
    def step(self, frame_idx: int, mask, depth, rgb, pose_c2w, cam: dict,
             static_xyz=None):
        if not self.cfg["enabled"]:
            return [], [], {"n_tracklets": 0, "n_object_points": 0, "n_fill_points": 0,
                            "n_retired": 0, "n_inserted_total": self._inserted_total,
                            "n_track_points": 0, "ring_frames": len(self.ring),
                            "n_static_pts": -1, **self.fill_diag}
        f = int(frame_idx)
        self.ring.add(f, depth, rgb, mask, cam)
        inserts: list[InsertBatch] = []
        n_obj = 0
        comps = component_masks(mask, self.cfg["min_area_px"], self.cfg["min_area_frac"],
                               self.cfg["topk"])
        for cm in comps:
            if len([b for b in inserts if b.kind == "object"]) >= self.cfg["max_objects_per_frame"]:
                break
            px, py, d, cols = sample_pixels(cm, depth, rgb, self.cfg["stride"])
            if px.size == 0:
                continue
            world = centroid_world(px, py, d, pose_c2w, cam["fx"], cam["fy"], cam["cx"], cam["cy"])
            self._pending_pts, self._pending_cols = world, cols
            t = self._associate(np.median(world, axis=0), f)
            t["centroid"], t["last_seen"] = np.median(world, axis=0), f
            keys = set(map(tuple, voxel_keys(world, self.cfg["voxel_m"])))
            vacated = t["covered"] - keys
            t["covered"] |= keys
            if vacated:
                self.fill_diag["vacated"] += len(vacated)
                self.blocked.setdefault(t["id"], {"keys": set(), "birth": t["birth"], "pre_obs": t.get("pre_obs")})["keys"].update(vacated)
            if px.size > self.cfg["max_points_per_object"]:
                self.fill_diag["obj_capped"] += 1
                sel = np.round(np.linspace(0, px.size - 1,
                                           self.cfg["max_points_per_object"])).astype(int)
                px, py, d, cols = px[sel], py[sel], d[sel], cols[sel]
            px = control_shift_px(px, d, cam["fx"], self.cfg["control_shift_m"])
            lid = self.ledger.issue(t["id"], "object", f)
            t["lid"] = lid
            inserts.append(InsertBatch("object", lid, dict(cam), np.asarray(px, np.float32),
                                       np.asarray(py, np.float32), np.asarray(d, np.float32),
                                       np.asarray(cols, np.float32), src_frame=f))
            n_obj += int(px.size)
        # 整对象退役（时间确认）
        retire: list[int] = []
        for t in list(self.tracks):
            if f - t["last_seen"] >= self.cfg["n_absent"]:
                self.tracks.remove(t)
                if t.get("lid") is not None:
                    retire.append(t["lid"])
                if self.cfg["fill_enabled"]:
                    self.blocked.setdefault(t["id"], {"keys": set(), "birth": t["birth"], "pre_obs": t.get("pre_obs")})["keys"].update(t["covered"])
        # 回填（占用门 + 源帧早于对象到来 + 源像素不在该帧掩码内）
        n_fill = 0
        if self.cfg["fill_enabled"]:
            for obj_id, rec in list(self.blocked.items()):
                batch, done = self._fill_batch(obj_id, rec, f, static_xyz)
                if batch is not None:
                    inserts.append(batch)
                    n_fill += batch.n
                for k in done:
                    rec["keys"].discard(k)
                if not rec["keys"]:
                    self.blocked.pop(obj_id, None)
        for lid in retire:
            self.ledger.retire([lid])
        self._inserted_total += n_obj + n_fill
        stats = {"n_tracklets": len(self.tracks), "n_object_points": n_obj,
                 "n_fill_points": n_fill, "n_retired": len(retire),
                 "n_inserted_total": self._inserted_total,
                 "n_track_points": int(sum(len(t["covered"]) for t in self.tracks)),
                 "ring_frames": len(self.ring),
                 "pending": int(sum(len(v["keys"]) for v in self.blocked.values())),
                 # 占用门的输入规模（每帧值）：-1 = static_xyz 未传入（此时 gate 恒放行 ⇒ gate_blocked=0
                 # 无法区分"图无支撑"与"没传图"——2026-09-27 冒烟待核项①的处置）
                 "n_static_pts": (int(len(static_xyz)) if static_xyz is not None else -1),
                 **self.fill_diag}
        self.ledger.log(f, stats)
        return inserts, retire, stats

    def object_points(self):
        """当前对象层的 (xyz (N,3) float32, cols (N,3) float32)——快照记录器用。

        返回各 tracklet 的"最后一次观测重建"组成（= t 时刻对象层的样子；逐帧替换 ⇒ 有界）。
        """
        import numpy as _np
        pts, cols = [], []
        for t in self.tracks:
            p, c = t.get("last_pts"), t.get("last_cols")
            if p is None or len(p) == 0:
                continue
            pts.append(p); cols.append(c)
        if not pts:
            return _np.empty((0, 3), _np.float32), _np.empty((0, 3), _np.float32)
        return _np.concatenate(pts, 0).astype(_np.float32), _np.concatenate(cols, 0).astype(_np.float32)

    # ── 内部 ──
    def _associate(self, centroid, frame_idx: int):
        best, bd = None, None
        for t in self.tracks:
            dd = float(np.linalg.norm(np.asarray(centroid) - np.asarray(t["centroid"])))
            if bd is None or dd < bd:
                best, bd = t, dd
        gate = max(self.cfg["assoc_gate_m"], 2.0 * self._last_disp)
        if best is not None and bd is not None and bd <= gate:
            self._last_disp = bd if self._last_disp == 0.0 else 0.5 * (self._last_disp + bd)
            best["last_pts"], best["last_cols"] = self._pending_pts, self._pending_cols
            return best
        t = {"id": self._next_obj, "centroid": np.asarray(centroid, dtype=np.float64),
             "last_seen": int(frame_idx), "birth": int(frame_idx), "covered": set(), "lid": None,
             "last_pts": self._pending_pts, "last_cols": self._pending_cols,
             # **出生时快照**"到来之前"的观测：环形缓冲只有 ring_frames 帧，tracklet 出生帧
             # 早晚会被逐出 ⇒ 若在需要回填时再查 ring，源帧已不在（端到端冒烟实测 no_source 巨大）。
             # 持有引用（不拷贝数组）：该 dict 因引用而不被回收，随 tracklet 生命周期释放。
             "pre_obs": self._snapshot_pre(frame_idx)}
        self._next_obj += 1
        self.tracks.append(t)
        return t

    def _snapshot_pre(self, frame_idx: int) -> list:
        """该帧**之前**最近 ≤K 帧的观测（引用列表）——作为新 tracklet 的回填源。"""
        out = []
        for f in self.ring.frames_before(int(frame_idx), self.cfg["fill_source_frames"]):
            obs = self.ring.get(f)
            if obs is not None:
                out.append(obs)
        return out

    def _fill_batch(self, obj_id: int, rec: dict, frame_idx: int, static_xyz):
        """让出体素 → 一次回填批（源帧相机）。返回 (batch|None, 已完成键)。"""
        keys_all = sorted(rec["keys"])
        cap = int(self.cfg["fill_scan_per_frame"])
        keys = keys_all[:cap]                      # 本帧**扫描**的切片（上界控成本）
        centers = (np.asarray(keys, dtype=np.float64) + 0.5) * self.cfg["voxel_m"]
        keep = occupancy_gate(centers, static_xyz, self.cfg["fill_gate_m"])
        self.fill_diag["gate_blocked"] += int((~keep).sum())
        keys = [keys[i] for i in np.nonzero(keep)[0]]
        centers = centers[keep]
        # `done` = 从待办集合里**移除**的键：① 被占用门拦下的（无需再试）；② 已填的（下方追加）。
        # **超出扫描上界的键必须留待下一帧**（不进程 ⇒ 不进 done）——2026-09-28 端到端崩于此处：
        # 原式枚举**未截断**的键表，而 keep 只有切片长度 ⇒ IndexError（单测此前未覆盖"待办 > 上界"）。
        done = [k for i, k in enumerate(keys_all) if i < cap and not bool(keep[i])]
        if not keys:
            return None, done
        # 源集合**语义**（2026-09-27 端到端冒烟修正）：不是"对象出生之前"，而是
        # "该体素**最近一次作为背景被看到**"——由近及远搜环形缓冲里未遮挡的观测（见到即停）。
        # 依据：pt2 里对象自始在场 ⇒ "出生之前"根本没有可用源（实测 no_source 巨大、fill=0）。
        pre = list(reversed([self.ring.get(f) for f in sorted(self.ring._order)
                             if f < int(frame_idx) and self.ring.get(f) is not None]))
        pre += [o for o in (rec.get("pre_obs") or []) if o not in pre]
        if not pre:
            self.fill_diag["no_source"] += len(keys)
            return None, done
        xs, ys, ds, cs, src = [], [], [], [], pre[-1]
        for k, ctr in zip(keys, centers):
            for si, obs in enumerate(pre):
                uv = project_to_camera(ctr, obs["cam"])
                if uv is None:
                    continue
                u, v = uv
                if obs["mask"] is not None and bool(obs["mask"][v, u]):
                    continue                     # 源帧该像素在掩码内 ⇒ 拍到的是物体本身，不用
                dd = float(obs["depth"][v, u])
                if not np.isfinite(dd) or dd <= 0.2 or dd >= 8.0:
                    continue
                img = obs["rgb"]
                col = img[:, v, u] if (img.ndim == 3 and img.shape[0] == 3) else img[v, u]
                xs.append(u); ys.append(v); ds.append(np.float32(dd)); cs.append(np.asarray(col, np.float32))
                src = obs
                done.append(k)
                break
        if not xs:
            self.fill_diag["no_source"] += len(keys)
            return None, done
        # per-frame 上限截断（先于预算）
        if len(xs) > self.cfg["fill_max_per_frame"]:
            self.fill_diag["capped"] += 1
            sel = np.round(np.linspace(0, len(xs) - 1, self.cfg["fill_max_per_frame"])).astype(int)
            xs, ys = [xs[i] for i in sel], [ys[i] for i in sel]
            ds, cs = [ds[i] for i in sel], [cs[i] for i in sel]
        # 累计预算（§9-ter H-B 在线落地）：全 run 回填总量上限；触顶即停止本帧及以后回填
        budget = int(self.cfg.get("fill_max_total") or 0)
        if budget > 0:
            room = budget - int(self._fill_total)
            if room <= 0:
                # 预算触顶：本帧不再回填；**filled 只在真正发出时计数**（见下方），故此处不动它
                self.fill_diag["budget_hit"] += 1
                self.fill_diag["capped"] += len(xs)
                return None, done
            if len(xs) > room:
                self.fill_diag["budget_hit"] += 1
                sel = np.round(np.linspace(0, len(xs) - 1, room)).astype(int)
                xs, ys = [xs[i] for i in sel], [ys[i] for i in sel]
                ds, cs = [ds[i] for i in sel], [cs[i] for i in sel]
        # filled == 真正发出的回填量（截断后）⇒ 与"不污染"语义一致、且可作预算有效性的核对量
        self.fill_diag["filled"] += len(xs)
        self._fill_total += len(xs)
        lid = self.ledger.issue(obj_id, "fill", frame_idx)
        return InsertBatch("fill", lid, dict(src["cam"]), np.asarray(xs, np.float32),
                           np.asarray(ys, np.float32), np.asarray(ds, np.float32),
                           np.asarray(cs, np.float32), src_frame=int(src["frame"])), done


def fill_fit_obs(src: dict | None, px, py, r: int = 3) -> dict | None:
    """fit-fill 的源帧观测构造（R2 修正案②）：ROI 掩码 = fill 像素膨胀 r ∧（源帧动态掩码取反）
    ——fill 像素本就在源帧掩码外（源选择时已跳过掩码内像素）。
    返回 {image (3,H,W) f32, depth (H,W) f32, mask (H,W) bool}；源帧缺数据或 ROI 空 ⇒ None（回退不拟合）。"""
    if not isinstance(src, dict) or src.get("rgb") is None or src.get("depth") is None:
        return None
    dep = np.asarray(src["depth"], dtype=np.float32)
    if dep.ndim == 3:
        dep = dep[0]
    h, w = int(dep.shape[-2]), int(dep.shape[-1])
    m = np.zeros((h, w), dtype=bool)
    pxc = np.clip(np.asarray(px, dtype=np.int64), 0, w - 1)
    pyc = np.clip(np.asarray(py, dtype=np.int64), 0, h - 1)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            m[np.clip(pyc + dy, 0, h - 1), np.clip(pxc + dx, 0, w - 1)] = True
    smask = src.get("mask")
    if smask is not None:
        sm = np.asarray(smask, dtype=bool)
        sm = sm[0] if sm.ndim == 3 else sm
        if sm.shape == (h, w):
            m &= ~sm
    if not bool(m.any()):
        return None
    img = np.asarray(src["rgb"], dtype=np.float32)
    if img.ndim == 3 and img.shape[0] != 3 and img.shape[-1] == 3:
        img = np.transpose(img, (2, 0, 1))  # (H,W,3) → (3,H,W)
    return {"image": img, "depth": dep, "mask": m}
