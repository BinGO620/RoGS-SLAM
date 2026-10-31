"""causal_render_log.py — E2 在线实装的**因果快照记录器**（prereg_E2_online.md §9，2026-09-29 行先锁）。

目的：修 V 侧不可判。既有 `render_compare`/`eval_final_mapping_raw` 渲染的都是**最终地图**，对**瞬态**层
结构性不利（对象层高斯停在最后一帧的位置，渲染到早期帧 = "把人放到他还没走到的位置"；E2n 三臂实测的
早期帧塌陷/末帧反超即该错位的签名）。本模块在**每个因果帧走完后**落盘"t 时刻地图状态"的最小快照：

  * `frame_idx`（int64）、估计位姿 c2w（float64 4×4）、对象层 `xyz`（float16 (N,3)）与 `cols`（uint8 (N,3)）、
    `n_static`（int64）、config 指纹（str）。

设计要点：
  1. **纯逻辑、零 torch**：只做"给什么存什么"的序列化；渲染由第 2 步的离线评测器（`eval_causal.py`）做。
  2. **默认关**：`E2ObjectLayer.causal_log: false`（缺省）⇒ `log_frame` 直接返回、零文件零状态
     （与 `TransientMap`/对象层本体的两态纪律同源）。
  3. **禁用 GT**：位姿只能来自调用方传入的**估计位姿**；本模块不读任何 groundtruth/数据集文件（AST 守护）。
  4. 成本 ~100 KB/帧（对象层有界：逐帧替换不累积 ⇒ N 为簇规模量级 ~5k–9k）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

# 缺省 = 关（不随 E2ObjectLayer.enabled 联动：记录器有自己的开关，便于只开记录不插层）
DEFAULTS = {
    "enabled": False,
    "out_dir": "",            # 空串 = 关闭时忽略；启用时由前端填 save_dir/causal_snapshots
    "every_n": 1,             # 每 N 帧记一次（1 = 全因果帧）
}


def causal_log_cfg(config: dict) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(dict((config.get("E2ObjectLayer") or {}).get("causal_log") or {})
               if isinstance((config.get("E2ObjectLayer") or {}).get("causal_log"), dict)
               else {})
    if not isinstance(cfg["enabled"], bool):
        raise ValueError(f"E2ObjectLayer.causal_log.enabled 必须是 bool，实为 {cfg['enabled']!r}")
    if not isinstance(cfg["every_n"], int) or isinstance(cfg["every_n"], bool) or cfg["every_n"] < 1:
        raise ValueError(f"E2ObjectLayer.causal_log.every_n 必须是 ≥1 的 int，实为 {cfg['every_n']!r}")
    if not isinstance(cfg["out_dir"], str):
        raise ValueError("E2ObjectLayer.causal_log.out_dir 必须是 str")
    # out_dir 允许为空：前端 `_e2_setup` 会自动填 `<save_dir>/causal_snapshots`
    # （仅离线评测/单测直用时才必须显式给）。
    return cfg


def config_fingerprint(config: dict) -> str:
    """config 的稳定指纹（进每个快照，防"快照与读数 config 不一致"的静默混批）。"""
    blob = json.dumps(config or {}, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


class CausalSnapshotWriter:
    """逐帧快照写盘器（默认关 = 零副作用；enable 时 lazily 建目录）。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.enabled = bool(cfg["enabled"])
        self.every_n = int(cfg["every_n"])
        self.out_dir = Path(cfg["out_dir"]) if cfg.get("out_dir") else None
        self._fp = None
        self._config_json = ""
        self.count = 0

    def set_fingerprint(self, config: dict) -> None:
        self._fp = config_fingerprint(config)
        try:
            self._config_json = json.dumps(config, sort_keys=True, default=str)
        except Exception:
            self._config_json = ""

    def log_frame(self, frame_idx: int, pose_c2w, obj_xyz, obj_cols, n_static: int) -> bool:
        """写一帧快照。返回是否真的写了（关闭/非抽帧帧 ⇒ False，零副作用）。"""
        if not self.enabled:
            return False
        f = int(frame_idx)
        if f % self.every_n != 0:
            return False
        assert self.out_dir is not None
        self.out_dir.mkdir(parents=True, exist_ok=True)
        xyz = np.asarray(obj_xyz, dtype=np.float32)
        cols = np.asarray(obj_cols, dtype=np.float32)
        # 颜色压到 uint8（渲染端除以 255 还原）；xyz float16 在 0.02m 体素尺度足够（量化误差 ≤ 体素/2 量级）
        xyz16 = xyz.astype(np.float16)
        cols8 = np.clip(np.rint(cols * 255.0), 0, 255).astype(np.uint8)
        c2w = np.asarray(pose_c2w, dtype=np.float64)
        assert c2w.shape == (4, 4), f"pose_c2w 必须是 4×4，实为 {c2w.shape}"
        np.savez_compressed(
            self.out_dir / f"frame_{f:06d}.npz",
            frame_idx=np.int64(f),
            c2w=c2w,
            xyz=xyz16,
            cols=cols8,
            n_static=np.int64(int(n_static)),
            # 快照**自带**运行时 config 的 JSON 串（而非只带指纹）：评测端直接读它，
            # 不依赖"评测端复算运行时注入链"——实测注入链无法在评测端重构
            #（fp 复算 = f3bf…，快照内 = 20d0…，逐键对撞失败 ⇒ 运行时态不可复现）。
            fingerprint=np.array(self._fp or ""),
            config_json=np.array(self._config_json or ""),
        )
        self.count += 1
        return True


def load_snapshot(path) -> dict:
    """读一份快照（评测器用）：还原 float32 xyz 与 [0,1] 颜色；config 直接取快照自带 JSON。"""
    with np.load(Path(path), allow_pickle=False) as z:
        return {
            "frame_idx": int(z["frame_idx"]),
            "c2w": np.asarray(z["c2w"], dtype=np.float64),
            "xyz": np.asarray(z["xyz"], dtype=np.float32),
            "cols": np.asarray(z["cols"], dtype=np.float32) / 255.0,
            "n_static": int(z["n_static"]),
            "fingerprint": str(z["fingerprint"]),
            "config_json": (str(z["config_json"]) if "config_json" in z else ""),
        }


def load_snapshots(dir_path, frames=None) -> list:
    """目录内全部快照（按帧号升序）；`frames` 给定时只保留 ≤ max(frames) 的（含抽帧语义由调用方保证）。"""
    d = Path(dir_path)
    out = []
    for p in sorted(d.glob("frame_*.npz")):
        s = load_snapshot(p)
        if frames is None or s["frame_idx"] <= max(frames):
            out.append(s)
    return out


def snapshot_for_frame(snapshots, frame_idx: int):
    """取"该帧时刻"的快照 = frame_idx ≤ f 的最近一份（严格因果：不含 f 之后的状态）。"""
    best = None
    for s in snapshots:
        if s["frame_idx"] <= int(frame_idx):
            if best is None or s["frame_idx"] >= best["frame_idx"]:
                best = s
    return best
