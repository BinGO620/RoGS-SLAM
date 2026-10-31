"""mope_layer — MoPe 有界 log-odds 持久动态后验（移植件；纯逻辑层，便于两态单测）。

来源：MoPe（arXiv:2606.29237，`resources/lit_dyn_mapping/papers/mope.md:40-42` Algorithm 1）。
本文件是**像素空间后验**的纯数学核，**不含**任何 per-primitive（α/opacity）操作
—— 这是刻意的（prereg_mope_layer.md §1：绕开墙 A，D2-017）。

算法（逐字移植，不改数学）：
    m_t(u) = max(1 − w_t(u), sem_t(u))                    # 逐帧证据（w=本仓可靠性权重）
    L̃_t    = Warp(L_{t−1}; T_{t−1→t}, D_t)                # 跨帧传播（由调用方做，见下）
    L_t    = clip(L̃_t + γ·logit(m_t), −c, c)              # 有界 log-odds 融合
    p_t    = σ(L_t)                                        # 持久动态后验 ∈ (0,1)

设计约束（`results/mope_layer/evidence/prereg_mope_layer.md`）：
- **默认关闭**：`MopeLayer.enabled: false`（缺省）⇒ 本模块所有入口"无操作"，主会话逐位不变。
- **纯像素空间**：后验是 (H,W) 场；**不做** per-primitive α/opacity 修改（§1/§2）。
- **R0 对照**：`propagate: false` ⇒ 不做 `L̃` 跨帧传播（= 同信号无记忆门），用于 M2/A2 对照。
- **阴性对照**：`null_posterior: true` ⇒ 后验恒常数（A3）。

本模块只做"证据→有界融合→后验"的纯逻辑；warp 与落盘由调用方（前端）完成。
"""
from __future__ import annotations

import numpy as np

# 缺省 = 关闭时的行为（`enabled=False` ⇒ 除 enabled 外键被忽略）
DEFAULTS = {
    "enabled": False,
    # gamma 为 MoPe 超参；其**取值须标定**（prereg §4.1 M1：不得先验拍数）。
    # 结构保证（与 gamma 无关）：更新是**加性**的 L_t = clip(L̃ + γ·logit(m), −c, c)
    # ——单帧只按 γ·|logit| 增减，**不重写**为"仅由当前帧决定"的值；clip 保证有界。
    "gamma": 1.0,        # log-odds 融合速率（待标定；全序列固定）
    "c": 4.0,            # log-odds 有界上界（clip 保证长期静止区可恢复）
    "propagate": True,   # False = R0 臂（同信号、无跨帧传播）
    "null_posterior": False,  # True = C− 臂（后验置常数）
    "tau_ins": 0.5,      # 插入门阈（fail-closed：p ≥ τ_ins ⇒ 不插入）
    "eta_sem": 1.0,      # 语义软地板系数（s_t = max(p_t, η·sem_t)）
    # 尺度标定（2026-10-02 冒烟实证）：本仓 w 域窄（1−w≈0.32），须按帧内分位拉伸到 [0,1]，
    # 否则 logit 恒负、p 越不过 τ_ins ⇒ 空转。见 evidence()/normalize_evidence() 的尺度纪律。
    "normalize": True,   # True = 逐帧分位归一（推荐）；False = 原样（MoPe 原始语义）
    "norm_lo_q": 0.10,
    "norm_hi_q": 0.90,
    # 仪器开关（default-off；只影响**落盘**，不改机制、不碰 per-primitive）：
    #   region ⇒ 按 GT 动态掩码分区的 p 落盘（M1 分离性 / M2 持久性 的前置件）
    #   timing ⇒ 逐帧墙钟落盘（M3 成本门斜率的前置件）
    # 二者都是 prereg §4.1 明文的"须先实装"件；缺则对应门 unjudgeable。
    "instrument": False,
    "instrument_region": True,   # 仅当 instrument=True 时生效
    "instrument_timing": True,   # 仅当 instrument=True 时生效
    # 用途接线（prereg §2 三条像素空间用途；**各自 default-off、互相独立**）：
    #   ① tracking  ⇒ ω̃=(1−p_t)·ω：把 p_t 合进 tracking 的逐像素软权（动态像素降权）
    #   ② mapping   ⇒ β̃：把 (1−p_t) 作为建图损失的逐像素权重（动态像素少拟合）
    #   （③ 插入门 = 既有 `apply_mope_insertion_gate`，非本开关）
    # 语义与既有软权一致：本仓所有软权通道都是 **dynamic_soft**（0=静态/1=动态），
    # 消费端做 `static_conf = clamp(1 − strength·dynamic_soft, floor, 1)` 或 `max` 合成。
    # ⇒ 本层贡献 dynamic_soft = p_t（**高后验 = 更动态 ⇒ 更强降权**），与用途①公式一致。
    "use_tracking": False,
    "use_mapping": False,
    # 与既有软权通道的合成方式（'max' = 任一通道认为动态就降权，本仓 default 语义）。
    "soft_combine": "max",
}


def mope_cfg(config: dict) -> dict:
    """合并缺省；非法值直接抛错（配置是实验的唯一定义，不允许静默回退）。"""
    raw = dict(config.get("MopeLayer") or {})
    cfg = dict(DEFAULTS)
    cfg.update(raw)
    for k in ("gamma", "c", "tau_ins", "eta_sem"):
        if not isinstance(cfg[k], (int, float)) or isinstance(cfg[k], bool):
            raise ValueError(f"MopeLayer.{k} 必须是数值，实为 {cfg[k]!r}")
    if cfg["gamma"] <= 0:
        raise ValueError("MopeLayer.gamma 必须 > 0")
    if cfg["c"] <= 0:
        raise ValueError("MopeLayer.c 必须 > 0（有界 log-odds 的上界）")
    if not (0.0 < cfg["tau_ins"] < 1.0):
        raise ValueError("MopeLayer.tau_ins 必须在 (0,1)")
    if cfg["eta_sem"] < 0:
        raise ValueError("MopeLayer.eta_sem 必须 ≥ 0")
    if not (0.0 <= cfg["norm_lo_q"] < cfg["norm_hi_q"] <= 1.0):
        raise ValueError("MopeLayer.norm_lo_q/norm_hi_q 必须 0≤lo<hi≤1")
    for k in ("propagate", "null_posterior", "normalize",
              "instrument", "instrument_region", "instrument_timing",
              "use_tracking", "use_mapping"):
        if not isinstance(cfg[k], bool):
            raise ValueError(f"MopeLayer.{k} 必须是 bool，实为 {cfg[k]!r}")
    if cfg["soft_combine"] not in ("max", "replace"):
        raise ValueError(f"MopeLayer.soft_combine 必须是 'max' 或 'replace'，实为 {cfg['soft_combine']!r}")
    return cfg


def posterity_dynamic_soft(p):
    """本层对既有 soft 通道的**增量**：`dynamic_soft = p_t`（高后验 ⇒ 更动态 ⇒ 更强降权）。

    纯读：不改 p。用途①（跟踪权重 `ω̃=(1−p)ω`）与②（建图损失 `β̃`）共用同一映射——
    本仓软权约定 dynamic_soft=1 ⇒ 完全降权、0 ⇒ 不降权，故直接取 p（消费端再 clamp）。
    返回 (H,W) float32 numpy（调用方负责转 torch/搬设备）。
    """
    return np.asarray(p, dtype=np.float32)


def region_stats(p, dynamic_mask) -> dict:
    """按 GT 动态掩码分区统计后验：动态区 / 静态区的 median(p)（M1 分离性的读数源）。

    `dynamic_mask` = (H,W) bool（True = 动态）。返回 dict；退化（某区为空）时该键为 None。
    **纯读数**：不修改 p，不碰任何基元标量。
    """
    p = np.asarray(p, dtype=np.float32)
    dm = np.asarray(dynamic_mask, dtype=bool)
    if dm.shape != p.shape:
        return {"n_dyn": None, "n_static": None,
                "p_median_dynamic": None, "p_median_static": None,
                "separation": None, "shape_mismatch": [list(dm.shape), list(p.shape)]}
    dyn = p[dm]
    sta = p[~dm]
    out = {
        "n_dyn": int(dyn.size),
        "n_static": int(sta.size),
        "p_median_dynamic": float(np.median(dyn)) if dyn.size else None,
        "p_median_static": float(np.median(sta)) if sta.size else None,
        "separation": None,
    }
    if dyn.size and sta.size:
        out["separation"] = out["p_median_dynamic"] - out["p_median_static"]
    return out


def mope_enabled(config: dict) -> bool:
    """唯一开关入口。缺省（无 MopeLayer 段或 enabled 缺省）⇒ False。"""
    return bool(mope_cfg(config)["enabled"])


def evidence(w, sem=None) -> np.ndarray:
    """逐帧动态证据 `m = max(1 − w, sem)` ∈ [0,1]（`w` = 可靠性权重；高 w = 可信静态）。

    `sem` 为 None 时只用 `1 − w`（无语义掩码的降级路径）。

    **⚠ 尺度纪律（2026-10-02 冒烟实证）**：本仓 `w` 的取值域**窄**（实测 mean_w≈0.68、
    1−w≈0.32），与 MoPe 的 DINOv2 不确定性（近 0/1）**不同量纲**。若把 `1−w` 直接当 `m`
    送进 `logit`，稳态 `L≈logit(0.32)≈−0.76 ⇒ p≈0.32`，**永远越不过插入门阈值** ⇒ 空转。
    故提供 `normalize=True`（**推荐**）：按帧内**分位数**把 `1−w` 拉伸到 [0,1]，
    使"本帧最动态的像素 ⇒ m≈1、最静态的 ⇒ m≈0"，从而与 MoPe 的 m 语义对齐。
    """
    w = np.asarray(w, dtype=np.float32)
    m = 1.0 - np.clip(w, 0.0, 1.0)
    if sem is not None:
        m = np.maximum(m, np.clip(np.asarray(sem, dtype=np.float32), 0.0, 1.0))
    return np.clip(m, 0.0, 1.0).astype(np.float32)


def normalize_evidence(m, lo_q: float = 0.10, hi_q: float = 0.90) -> np.ndarray:
    """把逐帧证据按**帧内分位数**拉伸到 [0,1]（尺度标定；见 `evidence` 的尺度纪律）。

    `lo_q`/`hi_q` 分位分别映到 0/1，中间线性夹逼。退化（分位重合）⇒ 返回原值。
    """
    m = np.asarray(m, dtype=np.float32)
    lo = float(np.quantile(m, lo_q))
    hi = float(np.quantile(m, hi_q))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-6:
        return np.clip(m, 0.0, 1.0)
    return np.clip((m - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)


def logit(m, eps: float = 1e-4) -> np.ndarray:
    """`logit(m)`，带 eps 夹逼防 ±inf。"""
    m = np.clip(np.asarray(m, dtype=np.float32), eps, 1.0 - eps)
    return np.log(m / (1.0 - m)).astype(np.float32)


def sigmoid(L) -> np.ndarray:
    """数值稳定 sigmoid。"""
    L = np.asarray(L, dtype=np.float32)
    out = np.empty_like(L)
    pos = L >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-L[pos]))
    e = np.exp(L[~pos])
    out[~pos] = e / (1.0 + e)
    return out


def fuse(L_prev_warped, m, gamma: float, c: float) -> np.ndarray:
    """有界 log-odds 融合：`L_t = clip(L̃ + γ·logit(m), −c, c)`（MoPe 式 5-6 逐字）。"""
    L = np.asarray(L_prev_warped, dtype=np.float32) + float(gamma) * logit(m)
    return np.clip(L, -float(c), float(c)).astype(np.float32)


class MopePosterior:
    """持久动态后验 `p_t` 的状态机（纯逻辑；warp 由调用方提供 `warp(L)` 回调）。

    - `update(m, warp=None)`：`warp` 给定时做跨帧传播（`propagate=True`）；否则用上帧 `L`
      （等价"无传播"= R0）。首次调用 `L_prev = 0`（p=0.5 中性初值）。
    - `propagate=False`（config）⇒ **无记忆**：每帧从 `L_prev=0` 起融合，
      `L_t = clip(γ·logit(m_t))`（= 逐帧证据的静态映射，**不读上帧 L**）。这是 prereg
      §4.1 M2 / §4.4 定义的 R0 对照臂（"同信号、**无跨帧传播**"；M2 逐字称其"**无记忆**"）。
      **2026-10-02 修正**：早期实现误用 `L_prev = self.L`（保留了跨帧记忆、仅去掉 warp），
      与"无记忆"定义不符 ⇒ M2/A2 的对照被架空（M 与 R0 仅差 warp）。现值 = 真无记忆。
    - `null_posterior=True`（config）⇒ 后验恒 0.5（A3 阴性对照）。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.L = None            # (H,W) float32 或 None
        self.t = -1
        self.n_updates = 0

    def update(self, m, warp=None):
        """推进一帧；返回后验 `p_t`（(H,W) float32 ∈ (0,1)）。"""
        m = np.asarray(m, dtype=np.float32)
        if self.cfg.get("normalize", False):
            m = normalize_evidence(m, self.cfg.get("norm_lo_q", 0.10), self.cfg.get("norm_hi_q", 0.90))
        if self.cfg.get("null_posterior", False):
            self.t += 1
            self.n_updates += 1
            self.L = np.zeros_like(m)              # p 恒 0.5
            return sigmoid(self.L)
        propagate = bool(self.cfg.get("propagate", True))
        if self.L is None or self.L.shape != m.shape:
            L_prev = np.zeros_like(m)
        elif propagate and warp is not None:
            L_prev = np.asarray(warp(self.L), dtype=np.float32)   # 跨帧传播（MoPe W）
        elif propagate:
            L_prev = self.L                        # 有传播但本帧无 warp 支持 ⇒ 沿用上帧
        else:
            L_prev = np.zeros_like(m)              # R0：**无记忆** ⇒ 每帧从 0 起（定义见类 docstring）
        self.L = fuse(L_prev, m, self.cfg["gamma"], self.cfg["c"])
        self.t += 1
        self.n_updates += 1
        return self.posterior()

    def posterior(self) -> np.ndarray:
        """当前 `p_t = σ(L_t)`；未初始化 ⇒ 0.5 场（中性）。"""
        if self.L is None:
            raise RuntimeError("posterior() 在 update() 之前调用")
        return sigmoid(self.L)


def insert_keep(p, sem=None, tau_ins: float = 0.5, eta_sem: float = 1.0) -> np.ndarray:
    """MoPe fail-closed 插入门（式 9-10）：`s = max(p, η·sem)`；`keep = 1[s < τ_ins]`。

    **逐像素 0/1 决策**（非 per-primitive）——本层不修改任何基元标量。"""
    p = np.asarray(p, dtype=np.float32)
    s = p.copy()
    if sem is not None:
        s = np.maximum(s, float(eta_sem) * np.clip(np.asarray(sem, dtype=np.float32), 0.0, 1.0))
    return (s < float(tau_ins))


def warp_field(field, depth_prev_world, w2c_cur, K, shape, depth_valid=None):
    """把上一帧的后验场 `L_{t-1}` warp 到当前帧像素（MoPe 的 `W`，纯几何）。

    做法：把 `L_{t-1}` 的每个像素按**上一帧**世界点（由 `depth_prev_world` 给定，形状 (H,W,3)，
    世界系）投影到**当前帧**相机 → 前向 splat，**按深度做遮挡**（目标像素取最靠前的源）。

    参数：`w2c_cur` (4,4) 世界→当前帧相机；`K` = (fx,fy,cx,cy)；`shape` = (H,W) 目标；
    `depth_valid` (H,W) bool（None ⇒ 全有效）。
    返回：warp 后的 (H,W) float32；**无对应处填 0**（= `L̃=0` ⇒ p=0.5 中性，"无支持"语义）。

    **符号纪律**：`L` 是**带符号** log-odds ⇒ 用**最近邻 splat**（保号），
    不用 max/mean 聚合（那会在正负混合处产生伪值）。
    """
    H, W = int(shape[0]), int(shape[1])
    fx, fy, cx, cy = (float(k) for k in K)
    Pw = np.asarray(depth_prev_world, dtype=np.float32).reshape(-1, 3)
    w2c = np.asarray(w2c_cur, dtype=np.float32)
    R, t = w2c[:3, :3], w2c[:3, 3]
    Pc = Pw @ R.T + t
    z = Pc[:, 2]
    ok = z > 1e-6
    safe_z = np.where(ok, z, 1.0)
    u = fx * Pc[:, 0] / safe_z + cx
    v = fy * Pc[:, 1] / safe_z + cy
    ok &= (u >= 0) & (u <= W - 1) & (v >= 0) & (v <= H - 1)
    if depth_valid is not None:
        ok &= np.asarray(depth_valid, dtype=bool).reshape(-1)
    out = np.zeros((H, W), dtype=np.float32)          # 默认 0 = 中性（无支持）
    if not ok.any():
        return out
    src = np.asarray(field, dtype=np.float32).reshape(-1)
    ti = np.round(v[ok]).astype(np.int64) * W + np.round(u[ok]).astype(np.int64)
    zi = z[ok]
    si = src[ok]
    # 遮挡：同一目标像素被多源命中时取**最小 z**（最靠前）。按 z 降序写入 ⇒ 小 z 最后覆盖。
    order = np.argsort(-zi, kind="stable")
    out.reshape(-1)[ti[order]] = si[order]
    return out
