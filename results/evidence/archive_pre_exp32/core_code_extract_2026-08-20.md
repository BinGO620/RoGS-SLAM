# 核心代码片段提取 — 底层逻辑深度分析

> 提取时间：2026-08-20 | 分支：ours-v3 | HEAD: 1ddb38ff
> 用途：方法论打磨（MRCS 内核评估 / 自适应策略设计 / 专家评审反馈应对）

---

## 1. 关键帧插入逻辑

**文件**: `utils/slam_frontend.py`

> 注：项目中不存在名为 `should_create_new_keyframe` 的函数。关键帧决策拆分为三个部分：
> `is_keyframe()`（协方差+平移检查）、`_dynamic_crisis_keyframe()`（动态危机自适应覆盖）、
> 以及 `run()` 中的主决策块。无注释掉的 photometric-error 自适应插帧废弃代码。

### 1.1 `is_keyframe()` — 协方差 + 平移阈值（行 1347-1374）

```python
    def is_keyframe(
        self,
        cur_frame_idx,
        last_keyframe_idx,
        cur_frame_visibility_filter,
        occ_aware_visibility,
    ):
        kf_translation = self.config["Training"]["kf_translation"]
        kf_min_translation = self.config["Training"]["kf_min_translation"]
        kf_overlap = self.config["Training"]["kf_overlap"]

        curr_frame = self.cameras[cur_frame_idx]
        last_kf = self.cameras[last_keyframe_idx]
        pose_CW = getWorld2View2(curr_frame.R, curr_frame.T)
        last_kf_CW = getWorld2View2(last_kf.R, last_kf.T)
        last_kf_WC = torch.linalg.inv(last_kf_CW)
        dist = torch.norm((pose_CW @ last_kf_WC)[0:3, 3])
        dist_check = dist > kf_translation * self.median_depth
        dist_check2 = dist > kf_min_translation * self.median_depth

        union = torch.logical_or(
            cur_frame_visibility_filter, occ_aware_visibility[last_keyframe_idx]
        ).count_nonzero()
        intersection = torch.logical_and(
            cur_frame_visibility_filter, occ_aware_visibility[last_keyframe_idx]
        ).count_nonzero()
        point_ratio_2 = intersection / union
        return (point_ratio_2 < kf_overlap and dist_check2) or dist_check
```

**决策逻辑**：两个条件取 OR —— (1) 观测点重叠率 < kf_overlap **且** 平移 > kf_min_translation；或 (2) 平移 > kf_translation（更松的纯平移阈值）。

### 1.2 `_dynamic_crisis_keyframe()` — 动态危机覆盖（行 1543-1591）

```python
    def _dynamic_crisis_keyframe(self, cur_frame_idx, last_keyframe_idx):
        """Promote a non-keyframe to a keyframe when it risks accumulating drift, so it
        enters backend BA. All triggers config-gated and tightened under high dynamic
        occlusion (the map is least reliable there). Supports the three joint-plan
        configs from one helper:
          - legacy coverage: crisis_interval + person_mask_ratio_thresh
          - gap cap ("no pose stays > N frames from a KF" -- a local-BA-support
            invariant): gap_cap, tightened to gap_cap_tight when occluded
          - motion (same primitive as is_keyframe's kf_translation*median_depth, but as
            a hard cap independent of covisibility): motion_tau_depth / motion_tau_tight
        A pure fixed-interval control = gap_cap only, occ_tighten_thresh disabled."""
        cfg = self.dyn_kf_cfg
        # Identical-count control (off by default): cap total keyframes so adaptive-vs-
        # uniform can be compared at MATCHED count (mgap@N vs fixed@N) -- isolates
        # placement from the +count confound. Only caps crisis promotions; default
        # covisibility keyframing is untouched.
        kf_budget = cfg.get("kf_budget")
        if kf_budget is not None and len(self.kf_indices) >= int(kf_budget):
            return False
        gap = cur_frame_idx - last_keyframe_idx
        high_occ = self.last_dyn_coverage >= float(cfg.get("occ_tighten_thresh", 2.0))

        # Legacy coverage trigger (round-1 design).
        ci = cfg.get("crisis_interval")
        cov_th = cfg.get("person_mask_ratio_thresh")
        if ci is not None and cov_th is not None:
            if gap >= int(ci) and self.last_dyn_coverage >= float(cov_th):
                return True

        # Hard gap cap (systems invariant), tightened under occlusion.
        gap_cap = (
            cfg.get("gap_cap_tight")
            if (high_occ and cfg.get("gap_cap_tight"))
            else cfg.get("gap_cap")
        )
        if gap_cap and gap >= int(gap_cap):
            return True

        # Motion cap (distinct from is_keyframe: a hard bound ignoring covisibility).
        tau = (
            cfg.get("motion_tau_tight")
            if (high_occ and cfg.get("motion_tau_tight"))
            else cfg.get("motion_tau_depth")
        )
        if tau and gap >= 1 and getattr(self, "median_depth", None):
            dist = self._kf_translation_since(cur_frame_idx, last_keyframe_idx)
            if dist is not None and dist > float(tau) * self.median_depth:
                return True
        return False
```

**三种触发机制**：
- **Coverage trigger**：gap >= crisis_interval 且 person 覆盖率 >= 阈值
- **Gap cap**：距上一关键帧帧数 >= gap_cap（高遮挡时收紧到 gap_cap_tight）
- **Motion cap**：平移距离 > tau * median_depth（忽略协方差的硬约束）

### 1.3 `run()` 中的关键帧决策块（行 2026-2064）

```python
                last_keyframe_idx = self.current_window[0]
                check_time = (cur_frame_idx - last_keyframe_idx) >= self.kf_interval
                curr_visibility = (render_pkg["n_touched"] > 0).long()
                create_kf = self.is_keyframe(
                    cur_frame_idx,
                    last_keyframe_idx,
                    curr_visibility,
                    self.occ_aware_visibility,
                )
                if len(self.current_window) < self.window_size:
                    union = torch.logical_or(
                        curr_visibility, self.occ_aware_visibility[last_keyframe_idx]
                    ).count_nonzero()
                    intersection = torch.logical_and(
                        curr_visibility, self.occ_aware_visibility[last_keyframe_idx]
                    ).count_nonzero()
                    point_ratio = intersection / union
                    create_kf = (
                        check_time
                        and point_ratio < self.config["Training"]["kf_overlap"]
                    )
                if self.single_thread:
                    create_kf = check_time and create_kf
                kf_reason = "covis" if create_kf else "none"
                if self.dyn_kf_enabled and not create_kf:
                    create_kf = self._dynamic_crisis_keyframe(
                        cur_frame_idx, last_keyframe_idx
                    )
                    if create_kf:
                        kf_reason = "crisis"
```

**主循环决策流程**：先用 `is_keyframe()`（协方差+平移），窗口未满时退化为纯时间+重叠率检查；若仍未触发且动态关键帧开启，调用 `_dynamic_crisis_keyframe()` 覆盖。

---

## 2. 权重映射与 Tau 计算

**文件**: `utils/reliability_signal.py`

### 2.1 `compute_reliability_tracking_weight()` — 完整接口（行 603-670）

```python
def compute_reliability_tracking_weight(
    obs_depth,
    render_depth,
    opacity,
    f_obs,
    R_tgt_from_src,
    t_tgt_from_src,
    fx,
    fy,
    cx,
    cy,
    geo_scale_floor: float = 0.0,
    flow_scale_floor: float = 0.0,
    mode: str = "both",
    ego_projection: bool = False,
    ego_kwargs=None,
):
    """One-frame (K=1) reliability weight ``w`` for the tracking down-weight (doc-10 §1).

    Assembles the current-frame reliability signal ``s=(1-e_flow)(1-v*g)`` and its Cauchy
    tracking weight ``w`` from the online render + the frozen backward flow, with NO new
    pose estimator (down-weight only). All ``(H, W)`` on one device:
      * ``obs_depth`` observed depth (m), ``render_depth`` rendered depth, ``opacity`` v;
      * ``f_obs`` ``(H, W, 2)`` frozen BACKWARD flow ``f_{t->t-1}`` (px), current-anchored;
      * ``R_tgt_from_src`` / ``t_tgt_from_src`` the ``T_{t-1<-t}`` rotation/translation
        (build with ``relative_pose_target_from_source``) for the ego ``f_static``.
    ``geo_scale_floor`` (m) / ``flow_scale_floor`` (px) are the noise-floor priors that
    protect the static no-harm gate. ``mode`` = fusion ablation switch, forwarded to
    ``fuse_static_evidence`` ("both" | "flow-only" | "geometry-only", default "both").
    Returns ``(s, w, flow_valid, stats)``; ``w -> 1``
    (no-harm) on a static frame. Missing/invalid flow is neutral for TRACKING (``e_flow``
    nan -> 0 in the fusion), but ``flow_valid`` (the K-frame consensus support map) is
    returned UNREDUCED so candidate CONFIRMATION can apply the missing-cue policy (a view
    with no valid flow is gated OUT of ``C±`` -- doc-10 §6 -- NOT treated as static).
    """
    g = geometric_anomaly(obs_depth, render_depth, scale_floor=geo_scale_floor)
    f_static, fs_valid = rigid_flow(
        obs_depth, fx, fy, cx, cy, R_tgt_from_src, t_tgt_from_src
    )
    valid = fs_valid & torch.isfinite(f_obs).all(dim=-1)
    ego_stats = {}
    ego_jac_list = None
    if ego_projection:
        J, _ = flow_jacobian_se3(
            obs_depth, fx, fy, cx, cy, R_tgt_from_src, t_tgt_from_src
        )
        ego_jac_list = [J]
    e_flow, flow_valid = assemble_flow_consensus(
        [f_obs], [f_static], [valid], scale_floor=flow_scale_floor,
        ego_jac_list=ego_jac_list, ego_kwargs=ego_kwargs, ego_stats_out=ego_stats,
    )
    s = fuse_static_evidence(g, e_flow, opacity, mode=mode)
    w = cauchy_tracking_weight(s)
    fv = flow_valid
    stats = {
        "mean_s": float(s.mean()),
        "min_s": float(s.min()),
        "mean_w": float(w.mean()),
        "min_w": float(w.min()),
        "flow_valid_frac": float(fv.float().mean()),
        "e_flow_mean_valid": float(e_flow[fv].mean()) if bool(fv.any()) else 0.0,
        "g_mean": float(g.mean()),
        "ego_projection": int(bool(ego_projection)),
    }
    stats.update(ego_stats)
    return s, w, fv, stats
```

**数据流**：`obs_depth/render_depth/opacity` → `geometric_anomaly(g)` → `rigid_flow(f_static)` → `assemble_flow_consensus(e_flow)` → `fuse_static_evidence(s)` → `cauchy_tracking_weight(w)`

### 2.2 `fuse_static_evidence()` — s 的融合公式（行 416-445）

```python
def fuse_static_evidence(geom_anom, flow_consensus, opacity, mode="both"):
    """``s = (1 - e_flow) * (1 - v*g)`` (doc-10 §1.6), for TRACKING.

    Opacity ``v`` gates the geometric cue ``g`` so newly-revealed (unmapped, low-v)
    geometry is not mislabelled as motion. Missing flow (nan) -> neutral
    (``e_flow=0``), i.e. tracking leaves ``s`` unreduced. Candidate CONFIRMATION must
    NOT use this path (it needs ``flow_valid`` to gate the observation out of ``C±``).
    All ``(H, W)`` in ``[0, 1]``.

    ``mode`` is an ABLATION-only switch (default ``"both"``, byte-identical to the
    historic behavior). It isolates the independent tracking contribution of each cue,
    so a reviewer-facing flow-only / geometry-only split is reproducible:
      * ``"both"``          : s = (1 - e_flow) * (1 - v*g)   (default, unchanged);
      * ``"flow-only"``     : s = (1 - e_flow)               (geometry cue zeroed);
      * ``"geometry-only"`` : s = (1 - v*g)                  (flow cue zeroed).
    Any other value raises. The caller (tracking) keeps the same missing-cue policy;
    confirmation must NOT route through this path regardless of mode.
    """
    g = geom_anom.detach().float().clamp(0.0, 1.0)
    e = torch.nan_to_num(flow_consensus.detach().float(), nan=0.0).clamp(0.0, 1.0)
    v = opacity.detach().float().clamp(0.0, 1.0)
    if mode == "both":
        return (1.0 - e) * (1.0 - v * g)
    if mode == "flow-only":
        return 1.0 - e
    if mode == "geometry-only":
        return 1.0 - v * g
    raise ValueError(
        f"fuse_static_evidence: unknown mode {mode!r}; expected 'both'|'flow-only'|'geometry-only'"
    )
```

**关键设计**：
- `v * g`：opacity 门控几何异常 —— 新揭示的（低 opacity）几何不被误判为运动
- nan flow → neutral（e_flow=0），tracking 不降权；但 candidate CONFIRMATION 不走这条路径
- mode 是消融开关，非运行时自适应

### 2.3 `cauchy_tracking_weight()` — Tau 计算（行 448-467）

```python
def cauchy_tracking_weight(s, valid=None, eps: float = 1e-6):
    """Frame-adaptive Cauchy down-weight ``w = 1/(1+(d/tau)^2)``, ``d = 1-s`` (doc-10 §1.7).

    ``tau`` from ``d``'s own median+MAD (no fixed temperature). ``s -> 1 => w -> 1``
    (no-harm). Non-finite ``s`` is treated as static (``w=1``) and excluded from the
    scale estimate; ``s`` is clamped to ``[0, 1]``. Returns ``(H, W)`` in ``(0, 1]``.
    """
    s_f = s.detach().float()
    finite = torch.isfinite(s_f)
    s_c = torch.nan_to_num(s_f, nan=1.0).clamp(0.0, 1.0)
    d = 1.0 - s_c
    scale_mask = finite if valid is None else (valid.to(d.device, torch.bool) & finite)
    sel = d[scale_mask]
    if sel.numel() == 0:
        return torch.ones_like(d)
    med = sel.median()
    mad = (sel - med).abs().median()
    tau = med + _MAD_CONST * mad + eps
    w = 1.0 / (1.0 + (d / tau) ** 2)
    return torch.where(finite, w, torch.ones_like(w))
```

**核心细节**：
- `_MAD_CONST = 1.4826`（MAD → 标准差的一致估计，假设正态分布）
- `tau = median(d) + 1.4826 × MAD(d) + ε`：帧自适应尺度，从当前帧 d 的分布本身推导
- `d = 1 - s`：异常度（s=1 → d=0 → w=1，no-harm）
- 非有限 s → w=1（当作静态），从尺度估计中排除
- **已知缺陷（2026-08-19 exp25）**：tau=median(d)+MAD 对 s 的绝对水平**严格不变** —— s∈[.97,1]（静态帧）与 s∈[.1,1]（动态帧）的 mean_w 同为 0.7438。tau 该不该改是独立问题

### 2.4 `robust_anomaly()` — 几何异常度（行 86-121）

```python
def robust_anomaly(values, valid=None, eps: float = 1e-6, scale_floor: float = 0.0):
    """``A(a) = 1 - exp(-[a - median]_+ / scale)`` over valid pixels.

    Threshold-free (no hand-set residual cutoff): 0 for residuals <= the frame
    median, approaching 1 for robust outliers. Returns ``(H, W)`` in ``[0, 1]``;
    out-of-``valid`` and non-finite pixels are 0.

    ``scale = max(1.4826*MAD, scale_floor) + eps``. With the default
    ``scale_floor=0`` this is the pure per-frame MAD normaliser: when MAD=0 (>50%
    identical residuals, e.g. a near-static frame) the scale collapses to ``eps``
    and any nonzero deviation saturates to ~1 -- mathematically faithful to doc-10
    but a sensor/flow-noise footgun on static scenes. A positive ``scale_floor``
    (in the SAME physical units as ``values`` -- px for flow, m for depth) is a
    NOISE-FLOOR SCALE PRIOR: it holds the normaliser at the known noise level so
    noise-magnitude residuals stay well below saturation (protecting the static
    no-harm gate) while genuine outliers >> floor still flag. This is the
    "calibrated scale floor" ablation doc-10 reserves; it regularises the ANOMALY
    SCALE, it is NOT a residual threshold on the decision (fusion stays
    threshold-free). Calibrate ``scale_floor`` from a noise-floor probe, not by
    hand; leave it 0 to reproduce the pure-MAD arm.
    """
    v = values.detach().float()
    valid = torch.ones_like(v, dtype=torch.bool) if valid is None else valid.to(v.device, torch.bool)
    valid = valid & torch.isfinite(v)
    sel = v[valid]
    if sel.numel() == 0:
        return torch.zeros_like(v)
    med = sel.median()
    mad = (sel - med).abs().median()
    scale = _MAD_CONST * mad
    if scale_floor > 0.0:
        scale = torch.clamp(scale, min=float(scale_floor))
    scale = scale + eps
    a = torch.clamp(v - med, min=0.0) / scale
    out = 1.0 - torch.exp(-a)
    return torch.where(valid, out, torch.zeros_like(out))
```

**核心公式**：`A(a) = 1 - exp(-[a - median]_+ / scale)`，其中 `scale = max(1.4826 × MAD, scale_floor) + ε`
- 残差 ≤ median → A=0（无异常）
- 残差 >> scale → A→1（强异常）
- `geometric_anomaly()` 和 `assemble_flow_consensus()` 都基于此原语

---

## 3. 鲁棒核与 Loss 注入点

**文件**: `utils/slam_utils.py`

### 3.1 `_robust_irls_weight()` — 鲁棒核权重（行 433-446）

```python
def _robust_irls_weight(residual, delta, kernel):
    """IRLS weight w(r) that down-weights large residuals (detached -> a
    per-iteration reweighting, not a gradient path). Recomputed every tracking
    iteration as the pose (and thus residual) updates, so weights co-adapt with
    the pose -- unlike a fixed per-frame reliability map."""
    r = residual.detach().abs()
    scale = max(float(delta), 1e-6)
    if kernel == "huber":
        return torch.clamp(scale / r.clamp(min=1e-6), max=1.0)
    if kernel == "cauchy":
        return 1.0 / (1.0 + (r / scale) ** 2)
    if kernel == "gm":  # Geman-McClure
        return 1.0 / (1.0 + (r / scale) ** 2) ** 2
    return torch.ones_like(r)
```

**三种核**：Huber（clamp）、Cauchy（soft）、Geman-McClure（更激进的降权）。

### 3.2 `get_loss_tracking_rgbd_flow_mask()` — 主 Tracking Loss（行 484-532）

```python
def get_loss_tracking_rgbd_flow_mask(
    config, image, depth, opacity, viewpoint, dynamic_mask
):
    """Masked RGB-D tracking loss: exclude a precomputed dynamic-pixel mask
    (flow-residual P2b and/or semantic P2d, combined in the frontend) from the loss.
    If RobustTracking is also enabled, the surviving static pixels are additionally
    robust-kernel reweighted (the P2a+P2d/P2b hybrid). dynamic_mask is (1,H,W) bool;
    the frontend already applied the max-ratio guardrail."""
    alpha = config["Training"]["alpha"] if "alpha" in config["Training"] else 0.95
    loss_eps = float(config.get("FlowResidualTracking", {}).get("loss_eps", 1e-6))
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]

    gt_image = viewpoint.original_image.to(device=image.device, dtype=image.dtype)
    gt_depth = torch.from_numpy(viewpoint.depth).to(
        dtype=torch.float32, device=image.device
    )[None]

    valid = gt_image.sum(dim=0, keepdim=True) > rgb_boundary_threshold
    dyn = dynamic_mask.to(device=image.device, dtype=torch.bool)
    static_mask = valid & (~dyn)

    rgb_pixel_mask = valid & viewpoint.grad_mask.to(
        device=image.device, dtype=torch.bool
    )
    rgb_residual = torch.abs(image - gt_image).mean(dim=0, keepdim=True)
    rgb_error = opacity * rgb_residual
    depth_residual = torch.abs(depth - gt_depth)

    rc = config.get("RobustTracking", {})
    if bool(rc.get("enabled", False)):  # hybrid: robust-weight surviving static pixels
        kernel = rc.get("kernel", "huber")
        w_rgb = _robust_irls_weight(
            rgb_residual, float(rc.get("rgb_delta", 0.10)), kernel
        )
        w_depth = _robust_irls_weight(
            depth_residual, float(rc.get("depth_delta", 0.10)), kernel
        )
    else:
        w_rgb = torch.ones_like(rgb_error)
        w_depth = torch.ones_like(depth_residual)

    l1_rgb = _weighted_mean(rgb_error, w_rgb, static_mask & rgb_pixel_mask, loss_eps)

    depth_pixel_mask = (gt_depth > 0.01).view(*depth.shape)
    opacity_mask = (opacity.detach() > 0.95).view(*depth.shape)
    depth_mask = static_mask & depth_pixel_mask & opacity_mask
    l1_depth = _weighted_mean(depth_residual, w_depth, depth_mask, loss_eps)

    return alpha * l1_rgb + (1 - alpha) * l1_depth
```

**Loss 注入架构**：
- `static_mask = valid & (~dynamic_mask)` —— 硬排除动态像素
- `rgb_error = opacity × |image - gt_image|` —— opacity 加权光度残差
- `w_rgb / w_depth` —— IRLS 鲁棒核权重（Huber δ=0.10）
- `l1_rgb = weighted_mean(rgb_error, w_rgb, static_mask & rgb_pixel_mask)`
- `l1_depth = weighted_mean(depth_residual, w_depth, static_mask & depth_pixel_mask & opacity_mask)`
- **最终**：`alpha × l1_rgb + (1-alpha) × l1_depth`（默认 alpha=0.95）

### 3.3 `get_loss_tracking_rgbd_soft()` — 软混合路径（行 535-588）

```python
def get_loss_tracking_rgbd_soft(config, image, depth, opacity, viewpoint, dynamic_soft):
    """P3a soft hybrid tracking loss: per-pixel weight = robust-kernel weight
    (if RobustTracking on) x static confidence (1 - strength*person_prob).
    Soft down-weighting of likely-dynamic pixels -- keeps info (unlike a hard mask)."""
    alpha = config["Training"]["alpha"] if "alpha" in config["Training"] else 0.95
    sc = config.get("SemanticMask", {})
    if config.get("StaticProb", {}).get("enabled", False):
        sc = config.get("StaticProb", {})
    strength = float(sc.get("soft_strength", 1.0))
    floor = float(sc.get("soft_floor", 0.10))
    loss_eps = float(sc.get("loss_eps", 1e-6))
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]

    gt_image = viewpoint.original_image.to(device=image.device, dtype=image.dtype)
    gt_depth = torch.from_numpy(viewpoint.depth).to(
        dtype=torch.float32, device=image.device
    )[None]

    valid = gt_image.sum(dim=0, keepdim=True) > rgb_boundary_threshold
    d_soft = dynamic_soft.to(device=image.device, dtype=image.dtype)
    static_conf = torch.clamp(
        1.0 - strength * d_soft, floor, 1.0
    )  # (1,H,W) soft weight

    rgb_pixel_mask = valid & viewpoint.grad_mask.to(
        device=image.device, dtype=torch.bool
    )
    rgb_residual = torch.abs(image - gt_image).mean(dim=0, keepdim=True)
    rgb_error = opacity * rgb_residual
    depth_residual = torch.abs(depth - gt_depth)

    rc = config.get("RobustTracking", {})
    if bool(rc.get("enabled", False)):
        kernel = rc.get("kernel", "huber")
        w_rgb = _robust_irls_weight(
            rgb_residual, float(rc.get("rgb_delta", 0.10)), kernel
        )
        w_depth = _robust_irls_weight(
            depth_residual, float(rc.get("depth_delta", 0.10)), kernel
        )
    else:
        w_rgb = torch.ones_like(rgb_error)
        w_depth = torch.ones_like(depth_residual)

    l1_rgb = _weighted_mean(rgb_error, w_rgb * static_conf, rgb_pixel_mask, loss_eps)

    depth_pixel_mask = (gt_depth > 0.01).view(*depth.shape)
    opacity_mask = (opacity.detach() > 0.95).view(*depth.shape)
    depth_mask = valid & depth_pixel_mask & opacity_mask
    l1_depth = _weighted_mean(
        depth_residual, w_depth * static_conf, depth_mask, loss_eps
    )

    return alpha * l1_rgb + (1 - alpha) * l1_depth
```

**软路径**：不硬排除，而是用 `static_conf = clamp(1 - strength × person_prob, floor, 1)` 逐像素降权。鲁棒核权重 × static_conf 乘积应用到残差上。

### 3.4 `get_loss_tracking_rgbd_hardsoft()` — 硬排除+软权重（行 291-378）

```python
def get_loss_tracking_rgbd_hardsoft(
    config, image, depth, opacity, viewpoint, dynamic_mask, dynamic_soft
):
    """H-e: hard-exclude the semantic dynamic mask from RGB-D tracking, THEN apply the
    robust kernel + soft static confidence on the surviving static pixels.

    Rationale (pt1/person-tracking): the moving person is ~65% of frame and its interior
    is large + low-texture, so leaving it down-weighted (soft) still lets its photometric
    residual (and strong edges) drag the pose. Hard-removing the mask region confines pose
    optimization to the static background (walls/floor/room lines), which our background
    probe shows retains ~25% strong-edge pixels, i.e. enough constraint. This matches how
    RGD/DG get lower person-ATE (explicit dynamic exclusion during tracking).

    Soft strength still applies to the remaining static pixels (robust kernel x
    static_conf); the hard mask only zeroes the dynamic region. Config switch:
    SemanticMask.hard_tracking_mask=true.
    """
    alpha = config["Training"]["alpha"] if "alpha" in config["Training"] else 0.95
    sc = config.get("SemanticMask", {})
    strength = float(sc.get("soft_strength", 1.0))
    floor = float(sc.get("soft_floor", 0.10))
    loss_eps = float(sc.get("loss_eps", 1e-6))
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]

    gt_image = viewpoint.original_image.to(device=image.device, dtype=image.dtype)
    gt_depth = torch.from_numpy(viewpoint.depth).to(
        dtype=torch.float32, device=image.device
    )[None]

    valid = gt_image.sum(dim=0, keepdim=True) > rgb_boundary_threshold
    # hard: keep only pixels NOT in the dynamic mask
    # E-C arm: optionally ERODE the dynamic mask (SemanticMask.track_erode_px>0) so only the
    # person INTERIOR is hard-excluded, leaving a boundary band + background as constraints.
    erode_px = int(sc.get("track_erode_px", 0))
    dm = dynamic_mask.to(device=image.device, dtype=torch.bool)
    if erode_px > 0:
        import torch.nn.functional as Fn
        dm = (Fn.avg_pool2d(dm.float(), kernel_size=2 * erode_px + 1, stride=1,
                            padding=erode_px) > 0.999).bool()
    hard_static = (~dm).byte()
    hard_static = (hard_static.view(-1) > 0).view(*hard_static.shape)
    # soft static confidence on the surviving pixels only
    d_soft = dynamic_soft.to(device=image.device, dtype=image.dtype)
    static_conf = torch.clamp(
        1.0 - strength * d_soft, floor, 1.0
    )  # (1,H,W) weight; only multiplied into surviving pixels

    rgb_pixel_mask = valid & viewpoint.grad_mask.to(
        device=image.device, dtype=torch.bool
    )
    rgb_pixel_mask = rgb_pixel_mask & hard_static
    rgb_residual = torch.abs(image - gt_image).mean(dim=0, keepdim=True)
    rgb_error = opacity * rgb_residual

    rc = config.get("RobustTracking", {})
    if bool(rc.get("enabled", False)):
        kernel = rc.get("kernel", "huber")
        w_rgb = _robust_irls_weight(
            rgb_residual, float(rc.get("rgb_delta", 0.10)), kernel
        )
    else:
        w_rgb = torch.ones_like(rgb_error)

    l1_rgb = _weighted_mean(
        rgb_error, w_rgb * static_conf, rgb_pixel_mask, loss_eps
    )

    depth_pixel_mask = (gt_depth > 0.01).view(*depth.shape)
    opacity_mask = (opacity.detach() > 0.95).view(*depth.shape)
    depth_mask = valid & depth_pixel_mask & opacity_mask & hard_static
    depth_residual = torch.abs(depth - gt_depth)
    if bool(rc.get("enabled", False)):
        w_depth = _robust_irls_weight(
            depth_residual, float(rc.get("depth_delta", 0.10)), kernel
        )
    else:
        w_depth = torch.ones_like(depth_residual)
    l1_depth = _weighted_mean(
        depth_residual, w_depth * static_conf, depth_mask, loss_eps
    )

    return alpha * l1_rgb + (1 - alpha) * l1_depth
```

**硬+软混合**：先硬排除 dynamic_mask 区域（person interior），再对存活静态像素应用 `w_rgb × static_conf`。可选 erode（`track_erode_px`）只保留 person interior 被排除，边界带保留约束。

### 3.5 `_weighted_mean()` — 加权均值辅助（行 591-597）

```python
def _weighted_mean(error, reliability, valid_mask, eps):
    valid_mask = valid_mask.to(device=error.device, dtype=torch.bool)
    weights = reliability.to(device=error.device, dtype=error.dtype) * valid_mask.to(
        dtype=error.dtype
    )
    denom = torch.clamp(weights.sum(), min=eps)
    return (error * weights).sum() / denom
```

### 3.6 `get_loss_tracking_rgbd_reliable()` — RGD 启发式可靠性加权（行 192-238）

```python
def get_loss_tracking_rgbd_reliable(
    config, image, depth, opacity, viewpoint,
    dynamic_mask=None, dynamic_soft=None, view_weight=None,
):
    """RGD-inspired reliability weighting with fixed-support normalization."""
    alpha = config["Training"].get("alpha", 0.95)
    terms = build_reliable_tracking_terms(
        config, image, depth, opacity, viewpoint,
        dynamic_mask=dynamic_mask, dynamic_soft=dynamic_soft, view_weight=view_weight,
    )
    rgb_weight = terms["rgb_weight"]
    depth_weight = terms["depth_weight"]
    robust = config.get("RobustTracking", {})
    if bool(robust.get("enabled", False)):
        kernel = robust.get("kernel", "huber")
        rgb_weight = rgb_weight * _robust_irls_weight(
            terms["rgb_residual"], robust.get("rgb_delta", 0.10), kernel
        )
        depth_weight = depth_weight * _robust_irls_weight(
            terms["depth_residual"], robust.get("depth_delta", 0.10), kernel
        )

    rgb_loss = _weighted_by_valid_count(
        terms["rgb_residual"], rgb_weight, terms["rgb_mask"], terms["rgb_valid_count"],
    )
    depth_loss = _weighted_by_valid_count(
        terms["depth_residual"], depth_weight, terms["depth_mask"], terms["depth_valid_count"],
    )
    return alpha * rgb_loss + (1 - alpha) * depth_loss
```

### 3.7 `get_loss_tracking()` — 入口路由（行 66-89）

```python
def get_loss_tracking(
    config, image, depth, opacity, viewpoint,
    initialization=False,
    tracking_dynamic_mask=None, tracking_dynamic_soft=None, tracking_view_weight=None,
):
    image_ab = (torch.exp(viewpoint.exposure_a)) * image + viewpoint.exposure_b
    if config["Training"]["monocular"]:
        return get_loss_tracking_rgb(config, image_ab, depth, opacity, viewpoint)
    return get_loss_tracking_rgbd(
        config, image_ab, depth, opacity, viewpoint,
        tracking_dynamic_mask=tracking_dynamic_mask,
        tracking_dynamic_soft=tracking_dynamic_soft,
        tracking_view_weight=tracking_view_weight,
    )
```

### 3.8 Tracking Loop 中 Reliability Weight 冻结（slam_frontend.py 行 1087-1157）

```python
            # Reliability weight (method #8): compute ONCE at the warm-up iteration from
            # the detached warmed-up pose + render, then freeze (recomputing per-iter lets
            # a bad pose suppress its own contradictions). w is stored as a dynamic-soft
            # (=1-w) and composed with any semantic/static soft by max (either cue may
            # down-weight). No-harm: on a static frame w->1 => dynamic-soft->0.
            if (
                reliability_active
                and not reliability_frozen
                and (tracking_itr >= rel_warmup or oracle_skip)
            ):
                reliability_frozen = True
                with torch.no_grad():
                    if bool(rel_cfg.get("ego_pose_oracle", False)):
                        pose_prev = self._pose_w2c_gt(prev)
                        pose_cur = self._pose_w2c_gt(viewpoint)
                    else:
                        pose_prev = self._pose_w2c(prev)
                        pose_cur = self._pose_w2c(viewpoint)
                    R_ts, t_ts = relative_pose_target_from_source(pose_prev, pose_cur)
                    obs_depth = torch.from_numpy(viewpoint.depth).to(self.device).float()
                    f_obs = torch.from_numpy(load_frozen_flow(rel_flow_path)).to(self.device)
                    s_map, w_map, fv_map, rstats = compute_reliability_tracking_weight(
                        obs_depth, depth.squeeze(), opacity.squeeze(), f_obs,
                        R_ts, t_ts,
                        viewpoint.fx, viewpoint.fy, viewpoint.cx, viewpoint.cy,
                        geo_scale_floor=float(rel_cfg.get("geo_scale_floor", 0.0)),
                        flow_scale_floor=float(rel_cfg.get("flow_scale_floor", 0.0)),
                        mode=str(rel_cfg.get("mode", "both")),
                        ego_projection=bool(rel_cfg.get("ego_projection", False)),
                        ego_kwargs=dict(rel_cfg.get("ego_projection_kwargs", {}) or {}),
                    )
                    reliability_soft = (1.0 - w_map).clamp(0.0, 1.0)
                    # DIAGNOSTIC: force w == 1 in TRACKING loss only
                    downweight_off = bool(rel_cfg.get("tracking_downweight_off", False))
                    if downweight_off:
                        reliability_soft = torch.zeros_like(reliability_soft)
```

### 3.9 Tracking Loop 中 Loss 调用（slam_frontend.py 行 1207-1228）

```python
            if oracle_skip:
                break  # oracle pose final; reliability stashed; skip optimization
            base_soft = static_soft if static_soft is not None else semantic_soft
            if reliability_soft is not None:
                combined_soft = (
                    reliability_soft
                    if base_soft is None
                    else torch.maximum(base_soft, reliability_soft)
                )
            else:
                combined_soft = base_soft
            pose_optimizer.zero_grad()
            loss_tracking = get_loss_tracking(
                self.config, image, depth, opacity, viewpoint,
                tracking_dynamic_mask=dyn_mask,
                tracking_dynamic_soft=combined_soft,
                tracking_view_weight=tracking_view_weight,
            )
```

**关键架构**：reliability soft 与 semantic/static soft 取 **逐像素 max**（任一 cue 想降权就降权），而非加权平均。

---

## 4. 高斯生命周期与密度管理

**文件**: `gaussian_splatting/scene/gaussian_model.py`

### 4.1 `densify_and_prune()` — 主入口（行 1377-1392）

```python
    def densify_and_prune(self, max_grad, min_opacity, extent, max_screen_size):
        grads = self.xyz_gradient_accum / self.denom
        grads[grads.isnan()] = 0.0

        self.densify_and_clone(grads, max_grad, extent)
        self.densify_and_split(grads, max_grad, extent)

        prune_mask = (self.get_opacity < min_opacity).squeeze()
        if max_screen_size:
            big_points_vs = self.max_radii2D > max_screen_size
            big_points_ws = self.get_scaling.max(dim=1).values > 0.1 * extent

            prune_mask = torch.logical_or(
                torch.logical_or(prune_mask, big_points_vs), big_points_ws
            )
        self.prune_points(prune_mask)
```

**Prune 条件**：sigmoid(opacity) < min_opacity **或** max_radii2D > max_screen_size **或** max_scale > 0.1 * scene_extent

### 4.2 `densify_and_clone()` — 低梯度+小高斯克隆（行 1337-1375）

```python
    def densify_and_clone(self, grads, grad_threshold, scene_extent):
        # Extract points that satisfy the gradient condition
        selected_pts_mask = torch.where(
            torch.norm(grads, dim=-1) >= grad_threshold, True, False
        )
        selected_pts_mask = torch.logical_and(
            selected_pts_mask,
            torch.max(self.get_scaling, dim=1).values
            <= self.percent_dense * scene_extent,
        )

        new_xyz = self._xyz[selected_pts_mask]
        new_features_dc = self._features_dc[selected_pts_mask]
        new_features_rest = self._features_rest[selected_pts_mask]
        new_opacities = self._opacity[selected_pts_mask]
        new_scaling = self._scaling[selected_pts_mask]
        new_rotation = self._rotation[selected_pts_mask]

        new_kf_id = self.unique_kfIDs[selected_pts_mask.cpu()]
        new_n_obs = self.n_obs[selected_pts_mask.cpu()]
        self.ensure_static_memory_state()
        new_static_prob = self.static_prob[selected_pts_mask]
        new_static_obs_count = self.static_obs_count[selected_pts_mask]
        new_unmapped_score = self.unmapped_score[selected_pts_mask]
        new_lineage_id = self.lineage_id[selected_pts_mask.cpu()]
        self.densification_postfix(
            new_xyz, new_features_dc, new_features_rest, new_opacities,
            new_scaling, new_rotation,
            new_kf_ids=new_kf_id, new_n_obs=new_n_obs,
            new_static_prob=new_static_prob, new_static_obs_count=new_static_obs_count,
            new_unmapped_score=new_unmapped_score, new_lineage_id=new_lineage_id,
        )
```

**克隆条件**：梯度 >= threshold **且** max_scale <= percent_dense × scene_extent（小高斯在高梯度区域）

### 4.3 `densify_and_split()` — 高梯度+大高斯分裂（行 1274-1335）

```python
    def densify_and_split(self, grads, grad_threshold, scene_extent, N=2):
        n_init_points = self.get_xyz.shape[0]
        padded_grad = torch.zeros((n_init_points), device="cuda")
        padded_grad[: grads.shape[0]] = grads.squeeze()
        selected_pts_mask = torch.where(padded_grad >= grad_threshold, True, False)
        selected_pts_mask = torch.logical_and(
            selected_pts_mask,
            torch.max(self.get_scaling, dim=1).values
            > self.percent_dense * scene_extent,
        )

        stds = self.get_scaling[selected_pts_mask].repeat(N, 1)
        # Counter-based keyed RNG (causal-twin): identical split jitter across
        # lifecycle arms at the same logical densify event, independent of the
        # global torch RNG stream (which desyncs the arms). See utils/causal_twin.
        samples = self._counter_rng().normal_like(
            stds, "densify_split", self._next_rng_event("densify_split")
        )
        rots = build_rotation(self._rotation[selected_pts_mask]).repeat(N, 1, 1)
        new_xyz = torch.bmm(rots, samples.unsqueeze(-1)).squeeze(-1) + self.get_xyz[
            selected_pts_mask
        ].repeat(N, 1)
        new_scaling = self.scaling_inverse_activation(
            self.get_scaling[selected_pts_mask].repeat(N, 1) / (0.8 * N)
        )
        new_rotation = self._rotation[selected_pts_mask].repeat(N, 1)
        new_features_dc = self._features_dc[selected_pts_mask].repeat(N, 1, 1)
        new_features_rest = self._features_rest[selected_pts_mask].repeat(N, 1, 1)
        new_opacity = self._opacity[selected_pts_mask].repeat(N, 1)

        new_kf_id = self.unique_kfIDs[selected_pts_mask.cpu()].repeat(N)
        new_n_obs = self.n_obs[selected_pts_mask.cpu()].repeat(N)
        self.ensure_static_memory_state()
        new_static_prob = self.static_prob[selected_pts_mask].repeat(N, 1)
        new_static_obs_count = self.static_obs_count[selected_pts_mask].repeat(N, 1)
        new_unmapped_score = self.unmapped_score[selected_pts_mask].repeat(N, 1)
        new_lineage_id = self.lineage_id[selected_pts_mask.cpu()].repeat(N)

        self.densification_postfix(
            new_xyz, new_features_dc, new_features_rest, new_opacity,
            new_scaling, new_rotation,
            new_kf_ids=new_kf_id, new_n_obs=new_n_obs,
            new_static_prob=new_static_prob, new_static_obs_count=new_static_obs_count,
            new_unmapped_score=new_unmapped_score, new_lineage_id=new_lineage_id,
        )

        prune_filter = torch.cat(
            (
                selected_pts_mask,
                torch.zeros(N * selected_pts_mask.sum(), device="cuda", dtype=bool),
            )
        )

        self.prune_points(prune_filter)
```

**分裂条件**：梯度 >= threshold **且** max_scale > percent_dense × scene_extent（大高斯在高梯度区域）
**分裂操作**：沿主轴方向偏移 ±0.5σ 生成 N=2 个子高斯，原高斯被 prune

### 4.4 `compress_deletion()` — Map 压缩删除（行 1400-1449）

```python
    def compress_deletion(
        self, op_floor=0.05, op_and_foot_th=0.10, foot_th_m=0.02, log_prefix=""
    ):
        """Map-compression deletion pass (R3-P05, STEP4).

        WHY THIS EXISTS. The paper's compactness axis is currently a false lever:
        deferred's was under-seeding, S6's was a degenerate lifecycle. This adds a
        GENUINE prune-style compression: delete Gaussians that contribute almost
        nothing to the rendered output. The offline gate (results/evidence/
        R3-P05-map-compression-step1.md, 4 seqs x prune seed-0) showed a safe set
        exists: deleting sigmoid opacity < 0.01 costs 0.000 dB at 10-18%; < 0.05
        costs <= 0.016 dB at 12.6-23.6%; the set is dynamics-agnostic (vac_excess=0)
        and surface-embedded (distance-to-TSDF flat), so it is a pure
        output-contribution axis needing no masks/TSDF.

        Deletion rule (recommended default from STEP2/3):
            delete if (sigmoid_op < op_floor)
                 OR (sigmoid_op < op_and_foot_th  AND  max_scale_axis < foot_th_m)
        ``foot_th_m=0`` disables the joint half, leaving pure ``op_floor``.

        Live-loop safety: when a live optimizer owns the parameters (mid-mapping,
        the STEP4 case), it routes through ``prune_points`` -> ``_prune_optimizer``
        so the removed set's Adam state is sliced too (the critical correctness
        requirement -- leaving orphaned optimizer state behind would poison the next
        ``optimizer.step()``). The offline-probe path (no optimizer) uses
        ``_prune_raw``. Both slice every bookkeeping tensor (xyz, scaling, rotation,
        opacity, static_* ledger, lineage). Return the number removed (0 on a
        length mismatch that would desync the ledger)."""
        if op_floor <= 0.0 and foot_th_m <= 0.0:
            return 0
        N = self._xyz.shape[0]
        if N == 0:
            return 0
        sig = self.get_opacity.reshape(-1)  # sigmoid opacity (N,)
        foot = self.get_scaling.max(dim=1).values  # max scale axis in m (N,)
        mask = sig < op_floor
        if foot_th_m > 0.0:
            mask = mask | ((sig < op_and_foot_th) & (foot < foot_th_m))
        remove_mask = mask
        n_remove = int(remove_mask.sum().item())
        if n_remove == 0:
            return 0
        if self.optimizer is not None:
            self.prune_points(remove_mask.to(self._xyz.device))
        else:
            self._prune_raw((~remove_mask).to(self._xyz.device))
        Log(f"{log_prefix}compress_deletion: removed {n_remove}/{N} "
            f"({n_remove / max(N, 1) * 100:.1f}%) -> {self._xyz.shape[0]}")
        return n_remove
```

**删除规则**：`sigmoid(op) < op_floor` **或** (`sigmoid(op) < op_and_foot_th` **且** `max_scale < foot_th_m`)
**安全保证**：删除代价 ≤ 0.016 dB（offline 已验证），dynamics-agnostic

### 4.5 `reset_opacity()` / `reset_opacity_nonvisible()` / `reset_opacity_masked()` — Opacity 重置（行 753-791）

```python
    def reset_opacity(self):
        opacities_new = inverse_sigmoid(torch.ones_like(self.get_opacity) * 0.01)
        optimizable_tensors = self.replace_tensor_to_optimizer(opacities_new, "opacity")
        self._opacity = optimizable_tensors["opacity"]

    def reset_opacity_nonvisible(self, visibility_filters):
        """Reset opacity for only non-visible gaussians"""
        opacities_new = inverse_sigmoid(torch.ones_like(self.get_opacity) * 0.4)

        for filter in visibility_filters:
            opacities_new[filter] = self.get_opacity[filter]
        optimizable_tensors = self.replace_tensor_to_optimizer(opacities_new, "opacity")
        self._opacity = optimizable_tensors["opacity"]

    def reset_opacity_masked(self, mask, reset_value=0.01):
        """Reset opacity of ONLY the masked Gaussians to ``reset_value`` (the
        inverse selection of ``reset_opacity_nonvisible``). Used by the R2-P02
        Fork-B alpha exit pass (mechanism A): low-alpha occluders that hide the
        observed background get their opacity knocked down so the background can
        be re-optimized -- reversible, unlike a hard prune, and it leaves every
        other Gaussian's opacity logit exactly as-is. Returns #reset."""
        if mask is None:
            return 0
        mask = mask.to(device=self._opacity.device, dtype=torch.bool).view(-1)
        n = int(mask.sum())
        if n == 0:
            return 0
        opacities_new = self._opacity.detach().clone()
        opacities_new[mask] = inverse_sigmoid(
            torch.tensor(
                float(reset_value), device=opacities_new.device, dtype=opacities_new.dtype,
            )
        )
        optimizable_tensors = self.replace_tensor_to_optimizer(opacities_new, "opacity")
        self._opacity = optimizable_tensors["opacity"]
        return n
```

**三种重置策略**：
- `reset_opacity()`：全部重置为 0.01（全局压缩）
- `reset_opacity_nonvisible()`：不可见的保持，可见的重置为 0.4（反直觉命名）
- `reset_opacity_masked()`：仅重置 mask 区域为 reset_value（可选性、可逆）

### 4.6 `prune_points()` — 通用 Prune 切片（行 950-980）

```python
    def prune_points(self, mask):
        valid_points_mask = ~mask
        if self.static_prob.shape[0] != valid_points_mask.shape[0]:
            # Ledger desync caught right before the slice. get_xyz is still at
            # the PRE-prune count here, so the shared resizer applies: a grow
            # keeps the accumulated alpha prefix, a shrink rebuilds and counts.
            self.ensure_static_memory_state()
        if self.lineage_id.shape[0] != valid_points_mask.shape[0]:
            self.lineage_id = torch.full(
                (valid_points_mask.shape[0],), UNTRACKED, dtype=torch.int32
            )
        self.static_prob = self.static_prob[valid_points_mask]
        self.static_obs_count = self.static_obs_count[valid_points_mask]
        self.unmapped_score = self.unmapped_score[valid_points_mask]

        optimizable_tensors = self._prune_optimizer(valid_points_mask)

        self._xyz = optimizable_tensors["xyz"]
        self._features_dc = optimizable_tensors["f_dc"]
        self._features_rest = optimizable_tensors["f_rest"]
        self._opacity = optimizable_tensors["opacity"]
        self._scaling = optimizable_tensors["scaling"]
        self._rotation = optimizable_tensors["rotation"]

        self.xyz_gradient_accum = self.xyz_gradient_accum[valid_points_mask]
        self.denom = self.denom[valid_points_mask]
        self.max_radii2D = self.max_radii2D[valid_points_mask]
        self.unique_kfIDs = self.unique_kfIDs[valid_points_mask.cpu()]
        self.n_obs = self.n_obs[valid_points_mask.cpu()]
        self.lineage_id = self.lineage_id[valid_points_mask.cpu()]
```

**关键细节**：prune 不仅切片参数张量，还同步切片 Adam 优化器状态（`_prune_optimizer`），以及 static_prob / static_obs_count / unmapped_score / lineage_id 等账本字段。残留优化器状态会导致下一步 `optimizer.step()` 污染。

### 4.7 `AlphaLifecycleParams` — Alpha 生命周期参数（alpha_lifecycle.py 行 50-84）

```python
@dataclass(frozen=True)
class AlphaLifecycleParams:
    """Thresholds for the exit/fill passes, read from the AlphaLifecycle block."""

    mode: str = MODE_OFF
    ema_beta: float = 0.9
    # per-pixel dynamic-evidence depth band (robust; NOT reliability s(x))
    evidence_band_abs_m: float = 0.05
    evidence_band_rel: float = 0.02
    # mechanism A: opacity-reset
    tau_reset: float = 0.35
    delta_occlude_m: float = 0.05
    reset_value: float = 0.01
    # mechanism B: free-space carve
    tau_carve: float = 0.20
    delta_free_m: float = 0.10
    min_obs_count: float = 3.0
    # mechanism C: fill
    fill_k: int = 8
    fill_band_abs_m: float = 0.10
    fill_band_rel: float = 0.03
    fill_min_opacity: float = 0.5
    fill_max_points: int = 2000

    @property
    def updates_alpha(self):
        return self.mode in (MODE_OBSERVE, MODE_EXIT, MODE_EXIT_FILL)

    @property
    def does_exit(self):
        return self.mode in (MODE_EXIT, MODE_EXIT_FILL)

    @property
    def does_fill(self):
        return self.mode == MODE_EXIT_FILL
```

**三种机制的阈值体系**：
| 机制 | 阈值 | 含义 |
|---|---|---|
| A: opacity-reset | `tau_reset=0.35`, `delta_occlude_m=0.05`, `reset_value=0.01` | 低 alpha 且在观测面前方 >5cm 的高斯 → 可逆 opacity 重置 |
| B: free-space carve | `tau_carve=0.20`, `delta_free_m=0.10`, `min_obs_count=3.0` | 持续低 alpha 且在观测面前方 >10cm 的高斯 → 硬 prune |
| C: fill | `fill_k=8`, `fill_min_opacity=0.5`, `fill_max_points=2000` | exit 后检测空洞区域 → 补种新高斯 |

### 4.8 `select_reset_mask()` — 机制 A 选择（alpha_lifecycle.py 行 211-221）

```python
def select_reset_mask(
    z, obs_at_gauss, alpha, valid, tau_reset, delta_occlude_m
):
    """Mechanism A (LPM opacity-reset): low-alpha Gaussians that sit in FRONT of
    the observed surface by more than ``delta_occlude`` -- i.e. they occlude the
    true background. Resetting their opacity (reversibly) lets the background be
    re-optimized. Static structure is protected by the ``alpha < tau_reset`` gate.
    """
    obs_ok = torch.isfinite(obs_at_gauss) & (obs_at_gauss > 0.01)
    in_front = z < (obs_at_gauss - delta_occlude_m)
    return valid & obs_ok & in_front & (alpha < tau_reset)
```

**选择逻辑**：`valid & obs_ok & in_front & (alpha < tau_reset)`
- 高斯投影深度 z < 观测深度 - 0.05m（在观测面前方）
- alpha < 0.35（持续被标记为动态）
- 两者同时满足 → 可逆重置 opacity（不删除，让背景重新优化）

### 4.9 `select_carve_mask()` — 机制 B 选择（alpha_lifecycle.py 行 224-237）

```python
def select_carve_mask(
    z, obs_at_gauss, alpha, obs_count, valid, tau_carve, delta_free_m, min_obs_count
):
    """Mechanism B (MAGS free-space carving): PERSISTENT low-alpha floaters
    clearly in front of the observed surface (by > ``delta_free`` >
    ``delta_occlude``) get hard-pruned. The ``obs_count >= min_obs`` persistence
    gate is the robustness lever: a Gaussian must be seen-and-inconsistent across
    several keyframes before deletion, so a single-frame evidence spike (MAD
    collapse) can never carve real geometry.
    """
    obs_ok = torch.isfinite(obs_at_gauss) & (obs_at_gauss > 0.01)
    in_front = z < (obs_at_gauss - delta_free_m)
    persistent = obs_count.squeeze() >= min_obs_count
    return valid & obs_ok & in_front & (alpha < tau_carve) & persistent
```

**选择逻辑**：`valid & obs_ok & in_front & (alpha < tau_carve) & persistent`
- 比机制 A 更严格：delta_free=0.10m > delta_occlude=0.05m
- alpha < 0.20（更极端的动态标记）
- **必须持续观察 ≥ 3 帧**（`min_obs_count=3.0`）—— 防止单帧 MAD 崩溃误删真实几何

### 4.10 `ema_alpha_update()` — Alpha 账本更新（alpha_lifecycle.py 行 191-205）

```python
def ema_alpha_update(alpha, obs_count, evidence_per_gaussian, update_mask, beta):
    """EMA each updated Gaussian's alpha toward ``static_obs = 1 - evidence`` and
    bump its observation counter. Pure; returns ``(alpha_new, obs_count_new)``.

    Static evidence (low dynamic evidence) pulls alpha -> 1; persistent dynamic
    evidence pulls it -> 0. Only ``update_mask`` entries move (visible + valid).
    """
    alpha = alpha.clone()
    obs_count = obs_count.clone()
    m = update_mask
    if m.any():
        static_obs = torch.clamp(1.0 - evidence_per_gaussian[m], 0.0, 1.0)
        alpha[m] = beta * alpha[m] + (1.0 - beta) * static_obs
        obs_count[m] = obs_count[m] + 1.0
    return alpha.clamp(0.0, 1.0), obs_count
```

**EMA 动力学**：`alpha_new = β × alpha_old + (1-β) × (1 - evidence)`，β=0.9
- 静态几何（evidence→0）→ alpha→1
- 持续动态（evidence→1）→ alpha→0
- `obs_count` 递增，为机制 B 的 `min_obs_count` 门控提供持久性度量

### 4.11 `_alpha_lifecycle_step()` — 完整 Alpha Exit+Fill 管线（slam_backend.py 行 549-687）

```python
    def _alpha_lifecycle_step(self, viewpoint, observed_depth):
        """R2-P02 Fork-B alpha-driven EXIT + FILL, run once per keyframe AFTER the
        vanilla map()/prune so vanilla mapping stays byte-identical when the
        AlphaLifecycle block is absent/off (arm B never reaches here). ``alpha`` ==
        the reused ``static_prob`` tensor (no new per-Gaussian field). Wrapped so a
        lifecycle fault degrades to a logged no-op and never crashes the mapping
        loop / the smoke run. Only the uncertain-region ghost is targeted: reset +
        carve fire ONLY on persistently low-alpha Gaussians in front of the
        observed surface, so static structure is protected."""
        try:
            params = alpha_lifecycle.read_alpha_lifecycle_params(self.config)
            gaussians = self.gaussians
            if gaussians is None or gaussians.get_xyz.shape[0] == 0:
                return
            if observed_depth is None:
                return
            self.alpha_lifecycle_steps += 1
            gaussians.ensure_static_memory_state()
            device = gaussians.get_xyz.device
            height = int(viewpoint.image_height)
            width = int(viewpoint.image_width)
            obs = torch.as_tensor(
                np.asarray(observed_depth), dtype=torch.float32, device=device
            ).squeeze()
            if obs.dim() != 2 or obs.shape[0] != height or obs.shape[1] != width:
                return

            with torch.no_grad():
                pkg = render(viewpoint, gaussians, self.pipeline_params, self.background)
                if pkg is None:
                    return
                rendered_depth = pkg["depth"].squeeze()
                rendered_opacity = pkg["opacity"].squeeze()
                visibility = pkg["visibility_filter"].to(device=device, dtype=torch.bool)

                # one projection of every Gaussian into this KF, shared by the
                # alpha ledger and the exit selection
                u, v, z, proj_valid = alpha_lifecycle.project_gaussians_to_view(
                    gaussians.get_xyz,
                    viewpoint.world_view_transform,
                    viewpoint.fx, viewpoint.fy, viewpoint.cx, viewpoint.cy,
                    height, width,
                )

                # --- alpha ledger (observe / exit / exit_fill) ---
                evidence, ev_valid = alpha_lifecycle.depth_inconsistency_evidence(
                    rendered_depth, obs,
                    params.evidence_band_abs_m, params.evidence_band_rel,
                )
                ev_at = alpha_lifecycle.sample_map_at_gaussians(
                    evidence, u, v, proj_valid, height, width
                )
                evvalid_at = (
                    alpha_lifecycle.sample_map_at_gaussians(
                        ev_valid.float(), u, v, proj_valid, height, width
                    ) > 0.5
                )
                update_mask = proj_valid & visibility & evvalid_at
                alpha = gaussians.static_prob.squeeze(1)
                obs_count = gaussians.static_obs_count.squeeze(1)
                alpha, obs_count = alpha_lifecycle.ema_alpha_update(
                    alpha, obs_count, ev_at, update_mask, params.ema_beta
                )
                gaussians.static_prob = alpha.unsqueeze(1)
                gaussians.static_obs_count = obs_count.unsqueeze(1)

                if not params.does_exit:
                    return

                # --- EXIT: opacity-reset (A) + free-space carve (B) ---
                obs_at = alpha_lifecycle.sample_map_at_gaussians(
                    obs, u, v, proj_valid, height, width
                )
                reset_mask = alpha_lifecycle.select_reset_mask(
                    z, obs_at, alpha, proj_valid, params.tau_reset, params.delta_occlude_m
                )
                n_reset = gaussians.reset_opacity_masked(reset_mask, params.reset_value)
                carve_mask = alpha_lifecycle.select_carve_mask(
                    z, obs_at, alpha, obs_count, proj_valid,
                    params.tau_carve, params.delta_free_m, params.min_obs_count,
                )
                n_carve = int(carve_mask.sum())
                if n_carve > 0:
                    remove = carve_mask.to(device=device)
                    gaussians.prune_points(remove)
                    # map() rebuilt occ_aware_visibility at the pre-step count; our
                    # carve happens AFTER it, so mirror the prune onto those masks or
                    # the frontend's is_keyframe logical_or hits stale sizes -> crash.
                    self._occ_visibility_drop(~remove)
                self.alpha_exit_reset_total += int(n_reset)
                self.alpha_carve_total += n_carve
                Log(f"alpha-exit KF {int(viewpoint.uid)}: reset {n_reset}, carved {n_carve}")

                if not params.does_fill:
                    return
                if n_reset == 0 and n_carve == 0:
                    return

                # --- FILL: recover background ONLY where exit opened a hole (C) ---
                self.alpha_fill_steps += 1
                pkg2 = render(viewpoint, gaussians, self.pipeline_params, self.background)
                if pkg2 is None:
                    Log(f"alpha-fill KF {int(viewpoint.uid)}: SKIP -- post-exit re-render returned None")
                    return
                vacated, fill_dbg = alpha_lifecycle.detect_vacated_pixels(
                    rendered_depth, rendered_opacity, pkg2["opacity"].squeeze(), obs,
                    params.fill_band_abs_m, params.fill_band_rel,
                    params.fill_min_opacity, return_diagnostics=True,
                )
                self.alpha_fill_cleared_px_total += int(fill_dbg["n_now_cleared"])
                self.alpha_fill_vacated_px_total += int(fill_dbg["n_vacated"])
                # ... (fill pixel processing and Gaussian insertion continues)

        except Exception as exc:  # lifecycle must never crash the mapping loop
            self.alpha_lifecycle_skips += 1
            Log(f"alpha-lifecycle step skipped (KF {getattr(viewpoint, 'uid', '?')}): {exc}")
```

**执行顺序**：`vanilla map() + prune()` → `_alpha_lifecycle_step()`（先 EMA 更新 alpha → 机制 A reset → 机制 B carve → 机制 C fill）
**安全保证**：整个 lifecycle 被 try/except 包裹，故障降级为 no-op，不崩溃 mapping loop

### 4.12 `map()` 中的密度管理调用点（slam_backend.py 行 497-522）

```python
                if update_gaussian:
                    self.gaussians.densify_and_prune(
                        self.opt_params.densify_grad_threshold,
                        self.gaussian_th,           # min_opacity for prune
                        self.gaussian_extent,
                        self.size_threshold,         # max_screen_size for prune
                    )
                    gaussian_split = True

                ## Opacity reset
                if (self.iteration_count % self.gaussian_reset) == 0 and (
                    not update_gaussian
                ):
                    Log("Resetting the opacity of non-visible Gaussians")
                    self.gaussians.reset_opacity_nonvisible(visibility_filter_acm)
                    gaussian_split = True

                ## R3-P05 STEP4: harmless-deletion map compression
                if self.compress_enabled:
                    self.gaussians.compress_deletion(
                        op_floor=self.compress_op_floor,
                        op_and_foot_th=self.compress_op_and_foot_th,
                        foot_th_m=self.compress_foot_th_m,
                        log_prefix="[compress]",
                    )
                    gaussian_split = True
```

**四种密度管理触发**（按执行顺序）：
1. `densify_and_prune()` — 每次 mapping iteration
2. `reset_opacity_nonvisible()` — 每 `gaussian_reset` 次迭代（非 mapping 时）
3. `compress_deletion()` — 由 `CompressionDeletion.enabled` 门控
4. `_alpha_lifecycle_step()` — 每个关键帧后（在 map+prune 之后）

---

## 5. 线索切换尝试（Regime-aware）

### 5.1 结论：**不存在运行时自适应切换**

> **关键发现**：项目中**没有**在运行时根据场景 regime 动态切换 geometry/flow 线索的
> 代码。P7 CUE-SPLIT 实验是**静态、配置时**的消融开关，通过 YAML config 在实验前固定，
> 非运行时决策。

### 5.2 模式分发路径

**文件**: `utils/slam_frontend.py`（行 1119-1140）

```python
                    s_map, w_map, fv_map, rstats = compute_reliability_tracking_weight(
                        obs_depth,
                        depth.squeeze(),
                        opacity.squeeze(),
                        f_obs,
                        R_ts,
                        t_ts,
                        viewpoint.fx,
                        viewpoint.fy,
                        viewpoint.cx,
                        viewpoint.cy,
                        geo_scale_floor=float(rel_cfg.get("geo_scale_floor", 0.0)),
                        flow_scale_floor=float(rel_cfg.get("flow_scale_floor", 0.0)),
                        mode=str(rel_cfg.get("mode", "both")),
                        ego_projection=bool(rel_cfg.get("ego_projection", False)),
                        ego_kwargs=dict(rel_cfg.get("ego_projection_kwargs", {}) or {}),
                    )
```

`mode` 从 config 读取一次，传入 `compute_reliability_tracking_weight()` → `fuse_static_evidence()`。

### 5.3 P7 CUE-SPLIT 配置文件

**Flow-only** (`configs/rgbd/experiments/p7_cuesplit/reliability_flow_only.yaml`):
```yaml
# P7 CUE-SPLIT method: mask-free + ReliabilitySignal, FLOW-ONLY cue.
inherit_from: "configs/rgbd/experiments/active/candidate/method_combined_maskoff_prune.yaml"

ReliabilitySignal:
  enabled: true
  mode: "flow-only"
```

**Geometry-only** (`configs/rgbd/experiments/p7_cuesplit/reliability_geo_only.yaml`):
```yaml
# P7 CUE-SPLIT method: mask-free + ReliabilitySignal, GEOMETRY-ONLY cue.
inherit_from: "configs/rgbd/experiments/p7_cuesplit/reliability_flow_only.yaml"

ReliabilitySignal:
  enabled: true
  mode: "geometry-only"
```

**Control-off** (`configs/rgbd/experiments/p7_cuesplit/reliability_screen_off_body.yaml`):
```yaml
# P7 CUE-SPLIT method: mask-free, ReliabilitySignal DISABLED (control-off).
inherit_from: "configs/rgbd/experiments/active/candidate/method_combined_maskoff_prune.yaml"
ReliabilitySignal:
  enabled: false
```

### 5.4 `fuse_static_evidence()` 的 mode 分发（行 416-445，与 §2.2 重复以保持独立可读）

```python
    if mode == "both":
        return (1.0 - e) * (1.0 - v * g)
    if mode == "flow-only":
        return 1.0 - e
    if mode == "geometry-only":
        return 1.0 - v * g
    raise ValueError(
        f"fuse_static_evidence: unknown mode {mode!r}; expected 'both'|'flow-only'|'geometry-only'"
    )
```

### 5.5 设计含义

- P7 实验 = 每序列 × 每臂的 config override（一个 yaml 对应一个消融条件），**非运行时决策模块**
- `tests/test_p7_cuesplit_configs.py` 确认：这是**配置契约测试**，非运行时逻辑
- 如需真正的 in-run 自适应（如根据当前帧 e_flow/g 的统计量动态选择 mode），需要**新建模块**
- `reliability_signal.py` 中的 `geometric_anomaly()`、`assemble_flow_consensus()` 是独立可调用的原语，为设计自适应选择器提供了基础接口

---

## 附：完整数据流架构图

```
Frame t 到达
  │
  ├─ Tracking Loop (slam_frontend.py run())
  │   ├─ is_keyframe()                    ← 协方差 + 平移阈值
  │   ├─ _dynamic_crisis_keyframe()        ← 动态危机覆盖（可选）
  │   │
  │   ├─ Reliability Signal (reliability_signal.py)
  │   │   ├─ robust_anomaly(g)             ← A(a) = 1-exp(-[a-median]_+/scale), scale=1.4826×MAD
  │   │   ├─ rigid_flow(f_static)          ← 刚体投影流
  │   │   ├─ assemble_flow_consensus(e_flow) ← 流一致性
  │   │   ├─ fuse_static_evidence(s)       ← s = (1-e)(1-v*g), mode 分发
  │   │   └─ cauchy_tracking_weight(w)     ← w = 1/(1+(d/tau)²), tau=median+MAD
  │   │
  │   └─ Loss (slam_utils.py)
  │       ├─ get_loss_tracking_rgbd_flow_mask()   ← 硬 mask 路径
  │       ├─ get_loss_tracking_rgbd_soft()        ← 软混合路径
  │       ├─ get_loss_tracking_rgbd_hardsoft()    ← 硬+软混合路径
  │       ├─ get_loss_tracking_rgbd_reliable()    ← RGD 启发式可靠性加权
  │       │   ├─ static_mask = valid & (~dyn)
  │       │   ├─ _robust_irls_weight(w_rgb, w_depth) ← Huber/Cauchy/GM
  │       │   ├─ rgb_error = opacity × |img - gt|
  │       │   └─ loss = α × l1_rgb + (1-α) × l1_depth
  │       └─ combined_soft = max(reliability_soft, base_soft) ← 逐像素 max 融合
  │
  ├─ Mapping (gaussian_model.py)
  │   ├─ densify_and_clone()     ← 梯度高 + scale 小 → 克隆
  │   ├─ densify_and_split()     ← 梯度高 + scale 大 → 分裂
  │   ├─ densify_and_prune()     ← op < min_opacity → 删除
  │   ├─ compress_deletion()     ← 压缩删除（op < 0.05 + scale < 0.02m）
  │   └─ reset_opacity_*()       ← 全局/非可见/掩码 重置
  │
  └─ Alpha Lifecycle (slam_backend.py + alpha_lifecycle.py)
      │   每个关键帧后执行（vanilla map+prune 之后）
      │
      ├─ EMA alpha 更新           ← alpha = β×alpha + (1-β)×(1-evidence), β=0.9
      │   └─ evidence = depth_inconsistency_evidence(rendered_depth, obs_depth)
      │
      ├─ 机制 A: opacity-reset    ← alpha < 0.35 & z < obs-0.05m → 可逆重置 (reset_value=0.01)
      │
      ├─ 机制 B: free-space carve ← alpha < 0.20 & z < obs-0.10m & obs_count ≥ 3 → 硬 prune
      │
      └─ 机制 C: fill             ← 检测 exit 后空洞 → 补种新高斯 (fill_k=8, max_points=2000)
```
