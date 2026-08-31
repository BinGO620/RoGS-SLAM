"""Class-agnostic reliability signal s(x) and Cauchy tracking down-weight (method core).

Pure-math core of the reliability signal from
``workspace/dynamic-3dgs-slam/03-knowledges/10-method_math_formalization.md`` §1:

    s(x) = (1 - e_flow(x)) * (1 - v(x) * g(x))    in [0, 1]   (1 = reliable static)

where ``g`` = normalized geometric-residual anomaly (opacity-gated by ``v``),
``e_flow`` = K-frame frozen-flow motion-consensus, ``v`` = rendered opacity. The
FROZEN RAFT flow field ``f_obs`` itself is NOT here (that is the integration step);
everything below is threshold-free (per-frame MAD) and unit-testable with synthetic
inputs.

Tracking is DOWN-WEIGHT ONLY (no new pose estimator; FullFramePose stays killed):

    d = 1 - s ;  tau = median(d) + 1.4826*MAD(d) + eps ;  w = 1 / (1 + (d/tau)^2)

so ``s -> 1  =>  w -> 1`` (no-harm on static).

INTEGRATION CONTRACT (caller's job; enforced by the wrapper, not these pure helpers):
  1. run a bounded vanilla-MonoGS warm-up, then snapshot the warmed-up pose;
  2. these functions already ``.detach()`` inputs, but still call them under
     ``torch.no_grad()`` and FREEZE ``s``/``w`` for the remaining tracking iterations
     (recomputing per-iteration lets a bad pose suppress its own contradictions);
  3. TRACKING uses missing flow as neutral (``s`` unreduced); candidate CONFIRMATION
     must instead gate a missing observation OUT of ``C±`` -- use ``flow_valid`` from
     ``kframe_consensus``, do NOT route confirmation through ``fuse_static_evidence``;
  4. feed ``kframe_consensus`` a TRAJECTORY-ALIGNED anomaly stack (anomalies sampled
     along RAFT flow), not a fixed-pixel frame stack; uniform weights are the frozen
     method choice.

All tensors are torch, CPU or CUDA; image maps are ``(H, W)`` and flow is ``(H, W, 2)``.
"""

from __future__ import annotations

import os

import numpy as np
import torch

_MAD_CONST = 1.4826  # MAD -> std consistency factor for a Gaussian


def stash_dba_weights_enabled(config):
    """P2-DBAphoto: persist the exact-online w_map (+ warmup render context) to disk.

    Default-off (ReliabilitySignal.stash_dba_weights). When on, the frontend stashes
    per frozen-frame: w_map, s_map (float16), the render_depth/opacity the signal was
    computed from, and the prev/cur W2C poses — so DBA-lite can re-run a
    reliability-weighted geometric oracle on the SAME weights the online tracker froze,
    NOT a post-hoc recompute from the final (co-adapted) PLY. See
    results/evidence/consult_codex_dbaphoto_design.md (the codex review that made
    exact-online a hard requirement)."""
    return bool(get_reliability_signal_config(config).get("stash_dba_weights", False))


def _dba_weight_stem(depth_path):
    """Frame stem shared with frozen flow (e.g. ``1548266469.88217``) for indexing."""
    return os.path.splitext(os.path.basename(depth_path))[0]


def save_dba_weight_snapshot(directory, stem, w_map, s_map, render_depth, opacity,
                             w2c_cur, w2c_prev, frame_idx, warmup_itr):
    """Write one frame's exact-online reliability snapshot for DBA-lite consumption.

    All image maps are saved float16 to bound cost (w/s in [0,1], depth in m, opacity in
    [0,1]). Poses are float32 4x4 W2C. Frame-level metadata (idx, warmup_itr, stem) goes
    into a sidecar JSON so DBA-lite can rebuild the edge set + prev-frame lookup without
    parsing filenames."""
    os.makedirs(directory, exist_ok=True)
    np.save(os.path.join(directory, f"{stem}_w.npy"),
            w_map.detach().cpu().numpy().astype(np.float16))
    np.save(os.path.join(directory, f"{stem}_s.npy"),
            s_map.detach().cpu().numpy().astype(np.float16))
    np.save(os.path.join(directory, f"{stem}_rdepth.npy"),
            render_depth.detach().cpu().numpy().astype(np.float16))
    np.save(os.path.join(directory, f"{stem}_opacity.npy"),
            opacity.detach().cpu().numpy().astype(np.float16))
    np.savez(os.path.join(directory, f"{stem}_pose.npz"),
             w2c_cur=w2c_cur.detach().cpu().numpy().astype(np.float32),
             w2c_prev=w2c_prev.detach().cpu().numpy().astype(np.float32),
             frame_idx=int(frame_idx), warmup_itr=int(warmup_itr), stem=stem)


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
    no-harm gate) while genuine outliers ``>> floor`` still flag. This is the
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


def geometric_anomaly(obs_depth, render_depth, valid=None, scale_floor: float = 0.0):
    """``g(x) = A(|obs_depth - render_depth|)`` (axial residual, doc-10 §1.3).

    Intrinsic finite/positive-depth validity is ALWAYS enforced (a caller mask can
    only further restrict it, never admit NaN/zero/negative depth). ``scale_floor``
    (metres) is the depth noise-floor prior forwarded to ``robust_anomaly``.
    """
    obs = obs_depth.detach().float()
    ren = render_depth.detach().float()
    r = (obs - ren).abs()
    safe = torch.isfinite(obs) & torch.isfinite(ren) & (obs > 0) & (ren > 0)
    valid = safe if valid is None else (valid.to(obs.device, torch.bool) & safe)
    return robust_anomaly(r, valid, scale_floor=scale_floor)


def relative_pose_target_from_source(T_w2c_target, T_w2c_source):
    """``T_{tgt<-src} = T_w2c_target @ inv(T_w2c_source)`` for world-to-camera 4x4 poses.

    Centralizes the pose convention so callers cannot silently pass camera motion,
    camera-to-world, or reversed frame order into ``rigid_flow``. Returns ``(R (3,3),
    t (3,))``.
    """
    tt = T_w2c_target.detach().float()
    ts = T_w2c_source.detach().float()
    t_rel = tt @ torch.inverse(ts)
    return t_rel[:3, :3], t_rel[:3, 3]


def rigid_flow(depth, fx, fy, cx, cy, R, t):
    """Static-scene expected optical flow from ego-motion + depth (doc-10 §1.4).

    ``depth`` ``(H, W)`` metres; ``R`` ``(3, 3)``, ``t`` ``(3,)`` are the
    target-from-source transform ``T_{j+1<-j}`` (use ``relative_pose_target_from_source``
    to build it correctly). Returns ``flow (H, W, 2)`` = ``target_pixel -
    source_pixel`` and ``valid (H, W)``. A pixel is valid only with finite positive
    source and target depth AND an in-bounds finite target projection.
    """
    device = depth.device
    h, w = depth.shape
    z = depth.detach().float()
    us = torch.arange(w, device=device, dtype=torch.float32).view(1, w).expand(h, w)
    vs = torch.arange(h, device=device, dtype=torch.float32).view(h, 1).expand(h, w)
    x = (us - cx) / fx * z
    y = (vs - cy) / fy * z
    r = R.detach().to(device, torch.float32)
    tt = t.detach().to(device, torch.float32).reshape(3)
    xc = r[0, 0] * x + r[0, 1] * y + r[0, 2] * z + tt[0]
    yc = r[1, 0] * x + r[1, 1] * y + r[1, 2] * z + tt[1]
    zc = r[2, 0] * x + r[2, 1] * y + r[2, 2] * z + tt[2]
    base = torch.isfinite(z) & (z > 0) & torch.isfinite(zc) & (zc > 1e-6)
    zc_safe = torch.where(base, zc, torch.ones_like(zc))
    u2 = fx * xc / zc_safe + cx
    v2 = fy * yc / zc_safe + cy
    valid = (
        base
        & torch.isfinite(u2)
        & torch.isfinite(v2)
        & (u2 >= 0)
        & (u2 <= w - 1)
        & (v2 >= 0)
        & (v2 <= h - 1)
    )
    flow = torch.stack([u2 - us, v2 - vs], dim=-1)
    flow = torch.where(valid.unsqueeze(-1), flow, torch.zeros_like(flow))
    return flow, valid


def flow_jacobian_se3(depth, fx, fy, cx, cy, R, t):
    """``J(x) = d(rigid_flow)/d(xi)`` -- how the ego prediction moves under a pose error.

    ``xi = (nu, omega)`` is a LEFT perturbation of the same target-from-source transform
    ``rigid_flow`` consumes: ``T' = exp(xi^) T``, so ``p_c' ~= p_c + omega x p_c + nu``
    (``p_c = R p + t`` the point in the TARGET camera frame). Differentiating the target
    projection ``u2 = fx*Xc/Zc + cx``, ``v2 = fy*Yc/Zc + cy`` gives, with
    ``a = fx/Zc``, ``b = -fx*Xc/Zc^2``, ``c = fy/Zc``, ``d = -fy*Yc/Zc^2``::

        du2 = a*dXc + b*dZc ,  dv2 = c*dYc + d*dZc
        dXc = nu_x + (om_y*Zc - om_z*Yc)
        dYc = nu_y + (om_z*Xc - om_x*Zc)
        dZc = nu_z + (om_x*Yc - om_y*Xc)

    The source pixel does not depend on ``xi``, so ``d(flow)/d(xi) = d(u2,v2)/d(xi)``.
    Returns ``(J (H, W, 2, 6), valid (H, W))`` with the SAME validity rule as
    ``rigid_flow`` (finite positive source and target depth).
    """
    device = depth.device
    h, w = depth.shape
    z = depth.detach().float()
    us, vs = _pixel_grid(h, w, device)
    x = (us - cx) / fx * z
    y = (vs - cy) / fy * z
    r = R.detach().to(device, torch.float32)
    tt = t.detach().to(device, torch.float32).reshape(3)
    xc = r[0, 0] * x + r[0, 1] * y + r[0, 2] * z + tt[0]
    yc = r[1, 0] * x + r[1, 1] * y + r[1, 2] * z + tt[1]
    zc = r[2, 0] * x + r[2, 1] * y + r[2, 2] * z + tt[2]
    valid = torch.isfinite(z) & (z > 0) & torch.isfinite(zc) & (zc > 1e-6)
    zc_safe = torch.where(valid, zc, torch.ones_like(zc))
    a = fx / zc_safe
    b = -fx * xc / (zc_safe * zc_safe)
    c = fy / zc_safe
    d = -fy * yc / (zc_safe * zc_safe)
    zero = torch.zeros_like(a)
    # translation columns (nu_x, nu_y, nu_z)
    ju = [a, zero, b]
    jv = [zero, c, d]
    # rotation columns (om_x, om_y, om_z)
    ju += [b * yc, a * zc - b * xc, -a * yc]
    jv += [d * yc - c * zc, -d * xc, c * xc]
    J = torch.stack([torch.stack(ju, dim=-1), torch.stack(jv, dim=-1)], dim=-2)
    J = torch.where(valid[..., None, None], J, torch.zeros_like(J))
    return J, valid


def ego_residual_projection(
    residual,
    jac,
    valid=None,
    iters: int = 4,
    max_corr_px: float = 20.0,
    min_explained_frac: float = 0.25,
    min_valid: int = 512,
    cond_max: float = 1e8,
    eps: float = 1e-6,
):
    """Remove the part of the flow residual that ANY camera-pose error could explain.

    WHY (results/evidence/eflow_pose_error_defect.md). ``rigid_flow`` predicts the static
    -scene flow from the pose that tracking is still optimising, so the residual
    ``r = f_obs - f_static`` carries the tracker's OWN pose error. On a near-static frame
    nothing genuinely moves, the MAD normaliser in ``robust_anomaly`` collapses to its
    noise floor, and that pose-error residual (``~ fx*dt/z`` px -- 3.3 px at 5 mm and
    0.8 m, vs a 2 px floor) is read as "dynamic" evidence. It lands hardest on NEAR
    pixels, which carry the most parallax, so the tracker down-weights exactly what it
    most needs and the error compounds across frames.

    THE SEPARATION. To first order a pose error ``dxi`` moves the prediction by
    ``J(x) dxi`` -- a 6-DoF subspace of flow fields. Independent object motion does NOT
    live in that subspace (it is not explainable by any single camera motion), except in
    degenerate cases. So: robustly fit ``dxi`` to ``r``, subtract ``J dxi``, and let
    ``robust_anomaly`` see only what no camera motion can account for.

    ``dxi`` IS a local pose estimate. It is used ONLY to normalise the anomaly and is
    NEVER written back to the camera -- the signal stays down-weight-only. Callers must
    not plumb the returned ``dxi`` into a pose update.

    ROBUSTNESS. IRLS with a Cauchy weight whose scale is the residual's own MAD, so a
    minority of genuine movers cannot drag the fit. Four guards, any of which returns
    the residual UNTOUCHED (fail-safe = current behaviour, never a silent half-fix):
      * ``min_valid``       too few valid pixels to identify 6 DoF;
      * ``cond_max``        ill-conditioned normal matrix (e.g. a narrow depth range
                            makes translation and rotation nearly indistinguishable);
      * ``min_explained_frac`` the fit must actually EXPLAIN the residual: the median
                            residual magnitude has to drop by at least this fraction.
                            A residual made of many independent motions (or noise) is
                            not ego-explainable, and subtracting a 6-DoF fit to it would
                            inject error rather than remove it;
      * ``max_corr_px``     backstop against an absurd fit: a per-frame pose error that
                            induces more than this much flow means tracking has already
                            diverged, and repairing that is not this signal's job.

    CALIBRATION (do not hand-tune; re-measure with the probe). ``max_corr_px=20`` comes
    from ``scripts/probe_eflow_pose_sensitivity.py`` on f3_st_hf: the median ego-flow
    magnitude there is 4.95 px and the fitted correction at a REALISTIC 1-5 cm pose
    error is 2.8-10.5 px. An earlier hand-picked 4.0 would have rejected exactly the
    frames the fix exists for -- which is why this default is measured, not chosen.
    An earlier ``min_inlier_frac`` guard (inlier = Cauchy weight > 0.5) was DROPPED: it
    compared a residual MAGNITUDE against a SPREAD, so on real data ~no pixel qualified
    and the guard rejected every frame. Explained-fraction is the scale-free replacement.

    HONEST LIMIT. A mover that BOTH fills most of the frame AND moves rigidly is not
    separable from a camera-pose error by any method working on one frame pair: its flow
    genuinely lies in the ego subspace. The guards bound the damage (fall back to the
    unprojected residual); they do not resolve the ambiguity, and nothing here claims to.

    ``residual`` ``(H, W, 2)``, ``jac`` ``(H, W, 2, 6)``. Returns
    ``(residual_corrected (H, W, 2), stats dict)``.
    """
    res = residual.detach().float()
    J = jac.detach().float()
    finite = torch.isfinite(res).all(dim=-1) & torch.isfinite(J).all(dim=-1).all(dim=-1)
    m = finite if valid is None else (valid.to(res.device, torch.bool) & finite)
    stats = {"ego_fit_applied": 0, "ego_corr_px": 0.0, "ego_dxi_norm": 0.0,
             "ego_explained_frac": 0.0, "ego_reject": "none"}
    n = int(m.sum())
    if n < int(min_valid):
        stats["ego_reject"] = "min_valid"
        return res, stats

    r_sel = res[m]                      # (N, 2)
    j_sel = J[m]                        # (N, 2, 6)
    A = j_sel.reshape(-1, 6)            # (2N, 6)
    b = r_sel.reshape(-1)               # (2N,)
    dxi = torch.zeros(6, device=res.device, dtype=torch.float32)
    e0 = r_sel.norm(dim=-1).median()     # 拟合前的残差尺度（dxi=0）
    for _ in range(max(1, int(iters))):
        pred = (j_sel @ dxi)            # (N, 2)
        e = (r_sel - pred).norm(dim=-1)  # (N,)
        med = e.median()
        mad = (e - med).abs().median()
        tau = (_MAD_CONST * mad).clamp_min(eps) + eps
        wt = 1.0 / (1.0 + (e / tau) ** 2)          # Cauchy IRLS weight, per pixel
        w2 = wt.repeat_interleave(2).unsqueeze(-1)  # both flow components share it
        Aw = A * w2
        H = Aw.transpose(0, 1) @ A
        g = Aw.transpose(0, 1) @ b
        # condition check on the weighted normal matrix (symmetric PSD -> eigvalsh)
        ev = torch.linalg.eigvalsh(H.double())
        lo, hi = float(ev[0]), float(ev[-1])
        if not (hi > 0) or lo <= 0 or (hi / max(lo, 1e-30)) > float(cond_max):
            stats["ego_reject"] = "ill_conditioned"
            return res, stats
        dxi = torch.linalg.solve(H.double(), g.double()).float()

    corr = J @ dxi                       # (H, W, 2), zero where J is zero
    e1 = (r_sel - (j_sel @ dxi)).norm(dim=-1).median()
    explained = float(1.0 - (e1 / e0.clamp_min(eps))) if float(e0) > eps else 0.0
    stats["ego_explained_frac"] = explained
    corr_px = float(corr[m].norm(dim=-1).median())
    stats["ego_corr_px"] = corr_px
    stats["ego_dxi_norm"] = float(dxi.norm())
    if not np.isfinite(explained) or explained < float(min_explained_frac):
        # 6-DoF 解释不掉这个残差 -> 减掉它只会注入误差
        stats["ego_reject"] = "not_ego_explainable"
        return res, stats
    if not np.isfinite(corr_px) or corr_px > float(max_corr_px):
        stats["ego_reject"] = "corr_too_large"
        return res, stats
    stats["ego_fit_applied"] = 1
    return res - corr, stats


def flow_anomaly(flow_obs, flow_static, valid=None, scale_floor: float = 0.0,
                 ego_jac=None, ego_kwargs=None, ego_stats_out=None):

    """``q(x) = A(||f_obs - f_static||_2)`` over valid pixels (doc-10 §1.4).

    Non-finite RAFT/predicted flow is always excluded (a caller mask can further
    restrict, never admit NaN into the MAD statistics). ``scale_floor`` (pixels) is
    the flow noise-floor prior forwarded to ``robust_anomaly`` -- the lever that
    keeps a near-static frame's MAD collapse from saturating ``e_flow`` on
    occlusion-edge/RAFT-glitch pixels (static no-harm protection, doc-10 §1.4).

    ``ego_jac`` (optional, ``(H, W, 2, 6)`` from ``flow_jacobian_se3``) switches on the
    ego-residual projection: the part of the residual that any camera-pose error could
    explain is fitted and removed BEFORE the anomaly, so the tracker's own pose error is
    no longer read as dynamics (see ``ego_residual_projection``). Passing ``None``
    reproduces the historical arm byte-for-byte. ``ego_stats_out``, when a dict, receives
    the fit diagnostics (whether it applied, why it was rejected, correction magnitude).
    """
    fo = flow_obs.detach().float()
    fs = flow_static.detach().float()
    diff = fo - fs
    finite = torch.isfinite(fo).all(dim=-1) & torch.isfinite(fs).all(dim=-1)
    valid = finite if valid is None else (valid.to(fo.device, torch.bool) & finite)
    if ego_jac is not None:
        diff, ego_stats = ego_residual_projection(
            diff, ego_jac, valid, **(ego_kwargs or {})
        )
        if ego_stats_out is not None:
            ego_stats_out.update(ego_stats)
    delta = (diff ** 2).sum(dim=-1).clamp_min(0.0).sqrt()
    return robust_anomaly(delta, valid, scale_floor=scale_floor)


def kframe_consensus(anomaly_stack, valid_stack=None):
    """``e_flow(x)`` = per-pixel median of K TRAJECTORY-ALIGNED frame anomalies over
    VALID frames.

    Persistence: a minority of spikes cannot dominate the lower median (even-K ties
    resolve conservatively toward static). ``anomaly_stack`` is ``(K, H, W)`` sampled
    along RAFT flow (NOT a fixed-pixel stack). Returns ``(e_flow (H, W), flow_valid
    (H, W))``; a pixel with no valid finite frame gets ``e_flow=nan, flow_valid=False``
    (do NOT treat missing flow as static -- the caller applies the missing-cue policy).
    """
    stack = anomaly_stack.detach().float()
    valid_stack = (
        torch.ones_like(stack, dtype=torch.bool)
        if valid_stack is None
        else valid_stack.to(stack.device, torch.bool)
    )
    valid_stack = valid_stack & torch.isfinite(stack)
    filled = torch.where(valid_stack, stack, torch.full_like(stack, float("inf")))
    sorted_, _ = filled.sort(dim=0)
    cnt = valid_stack.sum(dim=0)
    idx = ((cnt - 1).clamp(min=0) // 2).long().unsqueeze(0)  # lower median of valid
    med = torch.gather(sorted_, 0, idx).squeeze(0)
    flow_valid = cnt > 0
    med = torch.where(flow_valid, med, torch.full_like(med, float("nan")))
    return med, flow_valid


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


def cauchy_tracking_weight(
    s,
    valid=None,
    eps: float = 1e-6,
    exclusion_mask=None,
    max_zero_frac: float = 0.45,
    min_keep_frac: float = 0.20,
    tau_floor: float = 0.0,
    tau_scale: float = 1.0,
    stats_out=None,
):
    """Frame-adaptive Cauchy down-weight ``w = 1/(1+(d/tau)^2)``, ``d = 1-s`` (doc-10 §1.7).

    ``tau`` from ``d``'s own median+MAD (no fixed temperature). ``s -> 1 => w -> 1``
    (no-harm). Non-finite ``s`` is treated as static (``w=1``) and excluded from the
    scale estimate; ``s`` is clamped to ``[0, 1]``. Returns ``(H, W)`` in ``(0, 1]``.

    T2 -- ADAPTIVE-QUOTA SCALE-DOMAIN ISOLATION (opt-in, ``exclusion_mask`` not None).
    ``tau`` is a MAJORITY statistic: when a large moving object occupies the frame it
    joins the population that sets its own knee, so the mover cannot be down-weighted
    relative to itself. The fix is to estimate ``tau`` on the STATIC subgroup only.

    The obvious way to pick that subgroup -- a fixed cue threshold (``e_flow > 0.5``)
    -- has a hard failure mode this project MEASURED before implementing it (M0,
    ``results/evidence/m0_mad_exclusion/``). ``robust_anomaly`` returns exactly 0 at or
    below the frame median and on every invalid pixel, so ``d`` carries a large
    exactly-zero mass (0.38-0.51 of the frame in the three M0 runs). Every excluded
    pixel has ``d > 0`` by construction, so removal can only RAISE that share:

        zero_frac_after = zero_frac_before / (1 - excl_frac)

    Once it crosses 1/2 both ``median(d)`` and ``MAD(d)`` are 0, ``tau`` collapses to
    ``eps``, and ``w`` degenerates into the hard binary mask this mechanism exists to
    avoid. A fixed threshold crossed that line in 47.5% of the M0 frames.

    So the quota, not the threshold, is the mechanism. ``exclusion_mask`` supplies
    CANDIDATES; this function removes only the ``k`` largest-``d`` candidates, with

        k <= n_total * (1 - zero_frac_before / max_zero_frac)

    which is the closed-form solution of the identity above. The collapse is therefore
    not guarded against, it is UNREACHABLE: ``zero_frac_after <= max_zero_frac < 1/2``
    holds by construction, and on a frame that is already at or past the cap the
    formula yields ``k <= 0`` and the estimate falls back to the full domain, bit for
    bit. Two further caps keep ``k`` sane -- ``min_keep_frac`` of the domain always
    survives, and only candidates with ``d > 0`` are eligible (removing a zero-``d``
    pixel would break the closed form and help nothing).

    SEMANTICS, nailed down: exclusion applies to the ESTIMATION DOMAIN OF ``tau`` and
    to nothing else. Excluded pixels are NOT zero-weighted and are NOT dropped from
    the tracking loss -- they get the ordinary ``w = 1/(1+(d/tau)^2)`` like every other
    pixel, just against a ``tau`` that the static subgroup chose.

    ``tau_floor`` (>0) is an independent, orthogonal knob: it clamps ``tau`` from
    below. Note it pushes ``mean_w`` in the OPPOSITE direction to exclusion (M0: a
    floor raises it, exclusion lowers it), so the two are antagonistic, not
    complementary -- do not enable both without a reason.

    ``tau_scale`` (default 1.0 = exact no-op, a plain float multiply) is the T2-SCALE
    COUNTERFACTUAL, and it exists to be able to LOSE the quota's story. Exclusion can
    only lower ``tau`` (it removes the largest ``d``), and ``tau`` lower by any route
    sharpens the same Cauchy kernel -- so "isolate the static subgroup" and "multiply
    ``tau`` by a constant c<1" are observationally confusable. This knob does the
    latter and nothing else (no exclusion, ``mad_excl_*`` untouched), so the campaign
    can ask whether the quota buys anything a constant does not. The claimed
    difference is that the quota's effective ``c = f(frame)`` is frame-adaptive while
    this one is fixed; if the two arms land on the same ATE, the "isolation" narrative
    is what has to go, not the measurement.

    ``stats_out``, when given a dict, receives the before/after provenance the
    campaign needs to prove which mechanism produced the numbers.
    """
    s_f = s.detach().float()
    finite = torch.isfinite(s_f)
    s_c = torch.nan_to_num(s_f, nan=1.0).clamp(0.0, 1.0)
    d = 1.0 - s_c
    scale_mask = finite if valid is None else (valid.to(d.device, torch.bool) & finite)
    sel = d[scale_mask]
    if sel.numel() == 0:
        return torch.ones_like(d)
    if exclusion_mask is not None:
        sel = _quota_isolated_domain(
            d, sel, scale_mask, exclusion_mask,
            max_zero_frac, min_keep_frac, eps, stats_out,
        )
    med = sel.median()
    mad = (sel - med).abs().median()
    tau = med + _MAD_CONST * mad + eps
    if tau_scale != 1.0:
        # multiply BEFORE the floor: the floor is an absolute lower bound on the tau
        # that is actually used, so it has to see the scaled value.
        tau = tau * float(tau_scale)
    if tau_floor > 0.0:
        tau = torch.clamp(tau, min=float(tau_floor))
    if stats_out is not None:
        stats_out["mad_tau_after"] = float(tau)
    w = 1.0 / (1.0 + (d / tau) ** 2)
    return torch.where(finite, w, torch.ones_like(w))


def _quota_isolated_domain(
    d, sel, scale_mask, exclusion_mask, max_zero_frac, min_keep_frac, eps, stats_out
):
    """T2 helper: the largest-``d`` candidate prefix that keeps ``tau`` non-degenerate.

    Returns the ``d`` values ``cauchy_tracking_weight`` should estimate ``tau`` from.
    Split out of the caller so the closed-form quota is unit-testable on its own and
    so the default (no-exclusion) path above stays a single unbranched statement.
    """
    cand = scale_mask & exclusion_mask.to(d.device, torch.bool)
    n_tot = int(scale_mask.sum())
    z0 = float((sel == 0).float().mean())
    # closed form: keep zero_frac_after = z0 * n_tot / (n_tot - k) <= max_zero_frac
    q = float(max_zero_frac)
    k_quota = int(n_tot * (1.0 - z0 / q)) if q > 0.0 else 0
    k_keep = int(n_tot * (1.0 - float(min_keep_frac)))
    flat = torch.nonzero((cand & (d > 0.0)).reshape(-1), as_tuple=False).squeeze(1)
    k = max(0, min(k_quota, k_keep, int(flat.numel())))
    if stats_out is not None:
        med0 = sel.median()
        mad0 = (sel - med0).abs().median()
        stats_out.update({
            "mad_excl_cand_frac": float(cand.float().sum()) / max(n_tot, 1),
            "mad_zero_frac_before": z0,
            "mad_tau_before": float(med0 + _MAD_CONST * mad0 + eps),
            "mad_excl_k": int(k),
            "mad_excl_frac": k / max(n_tot, 1),
            "mad_excl_applied": int(k > 0),
            # WHICH cap bound k. Without it a small k is unattributable: "the cue
            # found little", "the frame is already near the zero-mass cap", and
            # "min_keep clipped us" are three different stories with one number.
            "mad_excl_bind": (
                "none" if k == 0
                else "quota" if k == k_quota
                else "min_keep" if k == k_keep
                else "candidates"
            ),
        })
    if k <= 0:
        if stats_out is not None:
            stats_out["mad_zero_frac_after"] = z0
        return sel
    chosen = flat[torch.topk(d.reshape(-1)[flat], k, largest=True).indices]
    keep = scale_mask.clone()
    keep.reshape(-1)[chosen] = False
    kept = d[keep]
    if stats_out is not None:
        stats_out["mad_zero_frac_after"] = float((kept == 0).float().mean())
    return kept


def _pixel_grid(h, w, device):
    us = torch.arange(w, device=device, dtype=torch.float32).view(1, w).expand(h, w)
    vs = torch.arange(h, device=device, dtype=torch.float32).view(h, 1).expand(h, w)
    return us, vs


def backward_warp(field, flow_fwd, valid=None):
    """Sample a source-frame map at the CURRENT frame via first-order backward warp.

    ``flow_fwd`` ``(H, W, 2)`` is the source->current FORWARD flow (px); the current
    pixel ``(u, v)`` reads the source at ``(u - flow_fwd_x, v - flow_fwd_y)`` -- the
    standard small-motion approximation ``f_{cur->src} ≈ -f_{src->cur}`` (the warped
    quantity is a robust/normalised anomaly, so first order suffices). ``field`` is
    ``(H, W)`` or ``(H, W, C)``. Returns ``(warped_field, warp_valid)`` where
    ``warp_valid`` is in-bounds sample locations AND, if ``valid`` is given, the warped
    source validity (bilinear, thresholded). Out-of-bounds reads are zeros/invalid.
    """
    device = field.device
    h, w = field.shape[:2]
    us, vs = _pixel_grid(h, w, device)
    ff = flow_fwd.detach().float()
    xs = us - ff[..., 0]
    ys = vs - ff[..., 1]
    inb = (
        torch.isfinite(xs)
        & torch.isfinite(ys)
        & (xs >= 0)
        & (xs <= w - 1)
        & (ys >= 0)
        & (ys <= h - 1)
    )
    gx = torch.where(inb, xs, torch.zeros_like(xs))
    gy = torch.where(inb, ys, torch.zeros_like(ys))
    nx = 2.0 * gx / max(w - 1, 1) - 1.0
    ny = 2.0 * gy / max(h - 1, 1) - 1.0
    grid = torch.stack([nx, ny], dim=-1).unsqueeze(0)  # (1, H, W, 2)
    inp = (field.detach().float().unsqueeze(0).unsqueeze(0) if field.ndim == 2
           else field.detach().float().permute(2, 0, 1).unsqueeze(0))
    sampled = torch.nn.functional.grid_sample(
        inp, grid, mode="bilinear", padding_mode="zeros", align_corners=True
    )
    out = sampled[0, 0] if field.ndim == 2 else sampled[0].permute(1, 2, 0)
    warp_valid = inb
    if valid is not None:
        vf = valid.to(device, torch.float32).unsqueeze(0).unsqueeze(0)
        vs2 = torch.nn.functional.grid_sample(
            vf, grid, mode="bilinear", padding_mode="zeros", align_corners=True
        )[0, 0]
        warp_valid = warp_valid & (vs2 > 0.999)
    return out, warp_valid


def assemble_flow_consensus(f_obs_list, f_static_list, valid_list, scale_floor: float = 0.0,
                            ego_jac_list=None, ego_kwargs=None, ego_stats_out=None):
    """``e_flow`` at the CURRENT frame from K recent frames' BACKWARD flow (doc-10 §3).

    ``f_obs_list[k]`` / ``f_static_list[k]`` are ``(H, W, 2)`` BACKWARD flows for frame
    ``t-k`` (observed RAFT ``f_{(t-k)->(t-k-1)}`` vs ego-motion rigid prediction), on
    frame ``t-k``'s own grid, ordered MOST-RECENT FIRST (``k=0`` is the current frame
    ``t``). ``valid_list[k]`` ``(H, W)`` bool is that frame's support (finite flow +
    valid depth). Each frame's disagreement anomaly ``q_k = A(||f_obs - f_static||)``
    lives on grid ``t-k`` and is backward-warped hop-by-hop UP to the current frame ``t``
    along the frozen backward flow (``k`` hops for frame ``k``; ``k=0`` needs NONE -- it
    is already current-anchored, which is exactly why the artifact is backward: a mover's
    anomaly lands on frame ``t`` without a warp). A per-pixel median over the K warped,
    still-valid frames is ``e_flow`` (persistence: a single-frame flow glitch cannot
    dominate the lower median). Returns ``(e_flow (H, W), flow_valid (H, W))``; a current
    pixel with no valid warped frame gets ``e_flow=nan, flow_valid=False`` (the caller
    applies the missing-cue policy -- tracking treats missing as neutral).

    ``ego_jac_list`` (optional, same K order) enables the ego-residual projection per
    frame; ``ego_stats_out``, when a dict, receives the CURRENT frame's (``k=0``) fit
    diagnostics only -- that is the one the tracking weight is actually built from.
    Leaving it ``None`` reproduces the historical arm byte-for-byte.
    """
    k = len(f_obs_list)
    if k == 0 or len(f_static_list) != k or len(valid_list) != k:
        raise ValueError("assemble_flow_consensus needs K>=1 aligned (obs, static, valid)")
    if ego_jac_list is not None and len(ego_jac_list) != k:
        raise ValueError("ego_jac_list must be aligned with f_obs_list (K entries)")
    anomalies, valids = [], []
    for i in range(k):
        q = flow_anomaly(
            f_obs_list[i], f_static_list[i], valid_list[i], scale_floor=scale_floor,
            ego_jac=None if ego_jac_list is None else ego_jac_list[i],
            ego_kwargs=ego_kwargs,
            ego_stats_out=ego_stats_out if (i == 0 and ego_stats_out is not None) else None,
        )
        vv = valid_list[i].to(q.device, torch.bool)
        # warp grid (t-i) -> current t: hops f_obs[i-1], f_obs[i-2], ..., f_obs[0]
        # (each backward flow is indexed on the newer target grid; i=0 needs no hop).
        for m in range(i - 1, -1, -1):
            q, vv = backward_warp(q, f_obs_list[m], vv)
        anomalies.append(q)
        valids.append(vv)
    return kframe_consensus(torch.stack(anomalies, dim=0), torch.stack(valids, dim=0))


def get_reliability_signal_config(config):
    return config.get("ReliabilitySignal", {})


def reliability_signal_enabled(config):
    return bool(get_reliability_signal_config(config).get("enabled", False))


def assert_reliability_flow_available(config, dataset_path):
    """HARD GATE against the exp23 silent-noop incident.

    ``ReliabilitySignal.enabled=true`` but an empty/missing frozen-flow directory used
    to silently skip the whole module frame-by-frame (ATE still converged, no warning).
    Decide solely from ``enabled && depth_paths`` (no dependence on gaussians/iteration),
    resolve the frozen-flow index, and raise immediately if it is empty so a broken
    config fails in the first frame instead of burning a run. Returns the flow index so
    the caller can reuse it. Separate helper (not inline) so it is unit-testable.
    """
    import os  # local import: keeps this module import-light on CPU
    from utils.flow_raft import frozen_flow_index

    flow_dir = os.path.join(
        dataset_path, get_reliability_signal_config(config).get("flow_subdir", "flow_raft")
    )
    index = frozen_flow_index(flow_dir)
    if not index:
        raise RuntimeError(
            f"ReliabilitySignal.enabled=true but no frozen flow found in {flow_dir}. "
            f"Refusing to run ReliabilitySignal with an empty flow index "
            f"(see reliability_signal_silent_noop_incident.md). Build flow_raft/ for "
            f"this sequence, or set ReliabilitySignal.enabled=false to run without it."
        )
    return index


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
    semantic_mask=None,
    mad_exclusion: bool = False,
    mad_excl_e_thresh: float = 0.5,
    mad_excl_candidates: str = "cue",
    mad_excl_max_zero_frac: float = 0.45,
    mad_excl_min_keep_frac: float = 0.20,
    mad_excl_tau_floor: float = 0.0,
    tau_scale: float = 1.0,
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
    ``mad_exclusion`` (default-off) turns on the T2 adaptive-quota scale-domain
    isolation: ``tau`` is estimated with the most-anomalous CANDIDATE pixels removed,
    under a quota that makes the MAD collapse unreachable (see
    ``cauchy_tracking_weight``). Candidates are ``semantic_mask | (e_flow > thresh)``
    when ``mad_excl_candidates == "cue"`` (the default -- the semantic term is the only
    ingredient that does NOT renormalise by the frame median, so it is what lets the
    mechanism exceed the flow cue's own ceiling), or every valid pixel when ``"all"``
    (cue-free variant: the quota alone trims the anomalous tail, so it also runs in the
    mask-free arms). ``semantic_mask`` is ``(1,H,W)`` or ``(H,W)`` bool and may be None.
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
    # T2 (default-off): candidate set for the adaptive-quota tau isolation. Built
    # HERE rather than inside cauchy_tracking_weight so the pure-math core never has
    # to know about cues -- it takes a finished mask and a quota, nothing else.
    excl_mask = None
    mad_stats = {}
    if mad_exclusion:
        excl_mask, sem_used = _mad_exclusion_candidates(
            e_flow, flow_valid, semantic_mask, mad_excl_e_thresh, mad_excl_candidates
        )
        mad_stats["mad_excl_semantic"] = int(sem_used)
    w = cauchy_tracking_weight(
        s,
        exclusion_mask=excl_mask,
        max_zero_frac=mad_excl_max_zero_frac,
        min_keep_frac=mad_excl_min_keep_frac,
        tau_floor=mad_excl_tau_floor,
        tau_scale=tau_scale,
        stats_out=mad_stats if mad_exclusion else None,
    )
    fv = flow_valid
    stats = {
        "mean_s": float(s.mean()),
        "min_s": float(s.min()),
        "mean_w": float(w.mean()),
        "min_w": float(w.min()),
        "flow_valid_frac": float(fv.float().mean()),
        "e_flow_mean_valid": float(e_flow[fv].mean()) if bool(fv.any()) else 0.0,
        "g_mean": float(g.mean()),
        # provenance: whether the ego projection ran, and if not, why. A run must be
        # able to prove which mechanism produced its numbers (silent-no-op lesson).
        "ego_projection": int(bool(ego_projection)),
        # provenance: same contract for T2. The DECLARATION column is always present
        # (so a control run proves the mechanism was off); the measurement columns
        # appear only when it actually ran, mirroring the ego_* block below.
        "mad_exclusion": int(bool(mad_exclusion)),
        # T2-scale declaration. Always on disk, like `mad_exclusion`: the whole point
        # of this arm is to be confusable with the quota arm from the ATE alone, so
        # which one produced a row must be readable off the row itself.
        "tau_scale": float(tau_scale),
    }
    stats.update(ego_stats)
    stats.update(mad_stats)
    return s, w, fv, stats


def _mad_exclusion_candidates(
    e_flow, flow_valid, semantic_mask, e_thresh, candidates
):
    """T2 candidate set for the quota. Returns ``(mask_hw_bool, semantic_used)``.

    ``"cue"``: ``semantic_mask | (flow_valid & e_flow > e_thresh)``. In a mask-free
    arm ``semantic_mask`` is None and this degrades to the flow term with no extra
    branch -- which is expected to be WEAK: ``e_flow`` is itself normalised by the
    frame median, so on a frame the mover dominates, ``e_flow > thresh`` starts
    selecting the static background instead. The semantic term is the only one that
    escapes that ceiling, which is why T2 is a combined-arm mechanism by design.

    ``"all"``: every valid pixel is a candidate, i.e. the quota alone decides. Cue-free
    and therefore available to the mask-free arms; kept as a separate arm rather than a
    fallback because it is a DIFFERENT mechanism, not a degraded one.
    """
    e_filled = torch.nan_to_num(e_flow.detach().float(), nan=0.0)
    if str(candidates) == "all":
        return torch.ones_like(e_filled, dtype=torch.bool), 0
    if str(candidates) != "cue":
        raise ValueError(
            f"mad_excl_candidates must be 'cue' or 'all', got {candidates!r}"
        )
    mask = flow_valid.to(e_filled.device, torch.bool) & (e_filled > float(e_thresh))
    if semantic_mask is None:
        return mask, 0
    sem = semantic_mask.squeeze()
    if sem.shape != mask.shape:
        # Never silently drop a cue: a shape mismatch means the arm is not running
        # the mechanism it is labelled with, and `mad_excl_semantic=0` on disk is
        # what makes that visible instead of a quiet mask-free result.
        return mask, 0
    return mask | sem.to(mask.device, torch.bool), 1
