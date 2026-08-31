"""P2 DBA-lite — Step 1: DIAGNOSTIC ONLY (doc 14 Execution plan P2a).

Before writing any pose-graph solver, answer codex's REAL failure-mode questions on
REAL masked keyframe windows (not synthetic SE(3) math):

  1. Do masked semi-dense geometric edges have enough inliers?
  2. Are the pose-pose Hessians well-conditioned (full rank, bounded condition
     number) -- or do mask holes / planar-repetitive indoor background make them
     degenerate (the "observability collapse" that would let a solver converge to a
     biased minimum while looking numerically stable)?
  3. On a KNOWN SE(3) perturbation of a real KF edge, does one Gauss-Newton step move
     the pose back toward the unperturbed value?

If conditioning is sick, DO NOT build the dense solver. Reads only -- no Gaussian or
pose is modified. Default-off (``DBALite.diagnostic``). Reuses the masked
point-to-plane machinery from ``coarse_pose.py`` and the KF cameras in
``backend.viewpoints`` (which retain gt depth + RGB + intrinsics + gt pose).
"""

import math

import torch
import torch.nn.functional as F

from gaussian_splatting.utils.graphics_utils import getWorld2View2
from utils.coarse_pose import _backproject, _normals_from_vertex, _se3_exp, _skew
from utils.logging_utils import Log
from utils.semantic_mask import (
    compute_semantic_dynamic_mask,
    get_or_compute_dynamic_mask,
    semantic_mask_enabled,
)


def get_dba_lite_config(config):
    return config.get("DBALite", {})


def dba_lite_diagnostic_enabled(config):
    return bool(get_dba_lite_config(config).get("diagnostic", False))


def dba_lite_enabled(config):
    return bool(get_dba_lite_config(config).get("enabled", False))


def _se3_log(T):
    """SE(3) matrix log -> twist [omega(3), v(3)] (inverse of coarse_pose._se3_exp)."""
    R = T[:3, :3]
    t = T[:3, 3]
    cos = ((torch.trace(R) - 1.0) * 0.5).clamp(-1.0, 1.0)
    theta = torch.arccos(cos)
    w_hat = torch.stack([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    eye = torch.eye(3, device=T.device, dtype=T.dtype)
    if float(theta) < 1e-5:
        omega = 0.5 * w_hat
        V_inv = eye
    else:
        omega = (theta / (2.0 * torch.sin(theta))) * w_hat
        W = _skew(omega)
        half = 0.5 * theta
        c2 = (1.0 - half * torch.cos(half) / torch.sin(half)) / (theta**2)
        V_inv = eye - 0.5 * W + c2 * (W @ W)
    return torch.cat([omega, V_inv @ t])


def _precompute_kf_geom(depth, mask, fx, fy, cx, cy, cfg, device, gray=None):
    """Pose-independent per-KF geometry (computed once, reused every solver iter).

    Returns a dict with the masked static SOURCE points/normals (for when this KF is
    the source of an edge) and the TARGET depth/normal/mask grids (for when it is the
    target). depth: (H,W) float tensor; mask: (H,W) bool person mask or None. gray:
    optional (H,W) grayscale in [0,1] -> adds source intensities Is + target graygrid
    for the photometric-proxy oracle."""
    s = int(cfg.get("stride", 4))
    min_d = float(cfg.get("min_depth", 0.05))
    max_d = float(cfg.get("max_depth", 5.0))
    grad_thr = float(cfg.get("grad_thresh", 0.02))
    d = depth[::s, ::s].contiguous()
    hl, wl = d.shape
    fxl, fyl, cxl, cyl = fx / s, fy / s, cx / s, cy / s
    vert = _backproject(d, fxl, fyl, cxl, cyl)
    norm = _normals_from_vertex(vert)
    valid = (d > min_d) & (d < max_d) & (norm.norm(dim=-1) > 0.5)
    gx = torch.zeros_like(d)
    gy = torch.zeros_like(d)
    gx[:, 1:-1] = (d[:, 2:] - d[:, :-2]).abs()
    gy[1:-1, :] = (d[2:, :] - d[:-2, :]).abs()
    valid = valid & ((gx + gy) > grad_thr)
    mgrid = None
    if mask is not None:
        m = mask[::s, ::s]
        if m.shape == d.shape:
            valid = valid & (~m)
            mgrid = m.float()[None, None]
    out = {
        "Ps": vert[valid],  # (Ns,3) source points (cam frame)
        "Ns": norm[valid],  # (Ns,3) source normals
        "_valid": valid,  # (hl,wl) bool mask that packed Ps/Ns (for _attach_weight_to_geom)
        "dgrid": d[None, None],  # (1,1,hl,wl) target depth
        "ngrid": norm.permute(2, 0, 1)[None],  # (1,3,hl,wl) target normals
        "mgrid": mgrid,  # (1,1,hl,wl) target person mask or None
        "fx": fxl,
        "fy": fyl,
        "cx": cxl,
        "cy": cyl,
        "hl": hl,
        "wl": wl,
        "min_d": min_d,
        "max_d": max_d,
        "Is": None,
        "graygrid": None,
    }
    if gray is not None:
        gl = gray[::s, ::s].contiguous()
        if gl.shape == d.shape:
            out["Is"] = gl[valid]  # (Ns,) source intensities
            out["graygrid"] = gl[None, None]  # (1,1,hl,wl) target gray
    return out


def _edge_two_sided(gi, gj, Tcw_i, Tcw_j, cfg, device):
    """Masked point-to-plane residual + TWO-SIDED Jacobians for a KF edge i->j using
    precomputed per-KF geometry gi (source) and gj (target) and absolute poses.

    Left-perturbation convention (twist [omega; v], matching _se3_exp):
        J_j = [P_j x n_j,  n_j]                       (wrt Tcw_j <- Exp(dx_j) Tcw_j)
        J_i = [-(P_i x n_i'), -n_i'], n_i' = R_ij^T n_j (wrt Tcw_i <- Exp(dx_i) Tcw_i)
    Returns (r, J_i, J_j, w) over inliers, or None.
    """
    depth_gate = float(cfg.get("depth_gate", 0.10))
    normal_cos = math.cos(float(cfg.get("normal_deg", 30.0)) * math.pi / 180.0)
    min_pts = int(cfg.get("min_points", 500))
    Pi, Ni = gi["Ps"], gi["Ns"]
    if Pi.shape[0] < min_pts:
        return None
    T_ij = Tcw_j @ torch.linalg.inv(Tcw_i)
    R_ij, t_ij = T_ij[:3, :3], T_ij[:3, 3]
    fx, fy, cx, cy = gj["fx"], gj["fy"], gj["cx"], gj["cy"]
    hl, wl = gj["hl"], gj["wl"]

    Pj = Pi @ R_ij.T + t_ij
    z = Pj[:, 2]
    u = fx * Pj[:, 0] / z + cx
    v = fy * Pj[:, 1] / z + cy
    gxn = (u / (wl - 1)) * 2 - 1
    gyn = (v / (hl - 1)) * 2 - 1
    grid = torch.stack([gxn, gyn], dim=-1)[None, None]
    dj_s = F.grid_sample(gj["dgrid"], grid, align_corners=True, padding_mode="zeros")[
        0, 0, 0
    ]
    nj_s = F.grid_sample(gj["ngrid"], grid, align_corners=True, padding_mode="zeros")[
        0, :, 0
    ].T
    nj_s = F.normalize(nj_s, dim=-1, eps=1e-6)
    qx = (u - cx) / fx * dj_s
    qy = (v - cy) / fy * dj_s
    Qj = torch.stack([qx, qy, dj_s], dim=-1)

    inside = (u >= 0) & (u <= wl - 1) & (v >= 0) & (v <= hl - 1)
    valid_dp = (dj_s > gj["min_d"]) & (dj_s < gj["max_d"])
    depth_ok = (Qj[:, 2] - Pj[:, 2]).abs() < depth_gate
    Nj_i = Ni @ R_ij.T
    normal_ok = (nj_s * Nj_i).sum(-1) > normal_cos
    finite = torch.isfinite(u) & torch.isfinite(v) & torch.isfinite(dj_s)
    m = inside & (z > gj["min_d"]) & valid_dp & depth_ok & normal_ok & finite
    if gj["mgrid"] is not None:
        mj_s = F.grid_sample(
            gj["mgrid"], grid, align_corners=True, padding_mode="zeros"
        )[0, 0, 0]
        m = m & (mj_s <= 0.5)
    if int(m.sum()) < min_pts:
        return None

    Pj_m, nj_m, Pi_m = Pj[m], nj_s[m], Pi[m]
    r = (nj_m * (Pj_m - Qj[m])).sum(-1)
    J_j = torch.cat([torch.cross(Pj_m, nj_m, dim=-1), nj_m], dim=-1)  # (K,6)
    ni_p = nj_m @ R_ij  # = R_ij^T n_j  (rows)
    J_i = -torch.cat([torch.cross(Pi_m, ni_p, dim=-1), ni_p], dim=-1)  # (K,6)
    med = r.median()
    mad = 1.4826 * (r - med).abs().median() + 1e-6
    w = torch.clamp((1.5 * mad) / r.abs().clamp(min=1e-6), max=1.0)
    return r, J_i, J_j, w


def _attach_weight_to_geom(geom, w_full, cfg):
    """Attach a stashed exact-online reliability weight map to a precomputed KF geom.

    ``w_full`` is the full-res ``(H,W)`` Cauchy weight ``w`` in ``(0,1]`` the online tracker
    froze (stash apparatus, ``utils/reliability_signal.save_dba_weight_snapshot``). It is
    strided to the geom grid (``[::s, ::s]``) then packed onto the source pixels parallel to
    ``Ps`` (``w_src = w_strided[valid]``) and stored as a target grid ``wgrid`` for
    ``grid_sample`` of ``w_j`` on the OTHER side of an edge. ``w_full=None`` (KF0 has no
    snapshot) -> all-ones (no-harm; only used in the KF0-edge sensitivity sweep, NOT the
    primary verdict which excludes KF0 edges -- codex 019fc6be NIT-8).
    """
    s = int(cfg.get("stride", 4))
    valid = geom.get("_valid", None)
    if w_full is None:
        hl, wl = geom["hl"], geom["wl"]
        wstr = torch.ones((hl, wl), dtype=torch.float32, device=geom["Ps"].device)
    else:
        if not torch.is_tensor(w_full):
            w_full = torch.as_tensor(w_full, dtype=torch.float32, device=geom["Ps"].device)
        else:
            w_full = w_full.to(device=geom["Ps"].device, dtype=torch.float32)
        wstr = w_full[::s, ::s].contiguous()
        if wstr.shape[0] != geom["hl"] or wstr.shape[1] != geom["wl"]:
            wstr = torch.ones(
                (geom["hl"], geom["wl"]),
                dtype=torch.float32,
                device=geom["Ps"].device,
            )
    geom["wgrid"] = wstr[None, None]  # (1,1,hl,wl)
    if valid is not None and w_full is not None:
        geom["w_src"] = wstr[valid]
    else:
        geom["w_src"] = torch.ones(
            (geom["Ps"].shape[0],), dtype=torch.float32, device=geom["Ps"].device
        )
    return geom


def _project_source(gi, gj, Tcw_i, Tcw_j, cfg, device):
    """Project gi's source points into gj's image; return per-source-pixel projections +
    sampled target depth/normal/mask + the FULL inlier gate (no min_pts cull).

    Shared geometric core of ``_edge_two_sided`` / ``_edge_weighted_resid_fixed`` /
    ``_edge_dynamic_cost``. Returns a dict with ``u,v,z,Pj,nj_s,Qj,m`` (the bool inlier mask
    over ALL source pixels, NOT yet min_pts-culled) and the relative rotation ``R_ij`` for
    Jacobian assembly, or None if source has < min_points to even attempt (early bail).
    """
    depth_gate = float(cfg.get("depth_gate", 0.10))
    normal_cos = math.cos(float(cfg.get("normal_deg", 30.0)) * math.pi / 180.0)
    min_pts = int(cfg.get("min_points", 500))
    Pi, Ni = gi["Ps"], gi["Ns"]
    if Pi.shape[0] < min_pts:
        return None
    T_ij = Tcw_j @ torch.linalg.inv(Tcw_i)
    R_ij, t_ij = T_ij[:3, :3], T_ij[:3, 3]
    fx, fy, cx, cy = gj["fx"], gj["fy"], gj["cx"], gj["cy"]
    hl, wl = gj["hl"], gj["wl"]

    Pj = Pi @ R_ij.T + t_ij
    z = Pj[:, 2]
    u = fx * Pj[:, 0] / z + cx
    v = fy * Pj[:, 1] / z + cy
    gxn = (u / (wl - 1)) * 2 - 1
    gyn = (v / (hl - 1)) * 2 - 1
    grid = torch.stack([gxn, gyn], dim=-1)[None, None]
    dj_s = F.grid_sample(gj["dgrid"], grid, align_corners=True, padding_mode="zeros")[0, 0, 0]
    nj_s = F.grid_sample(gj["ngrid"], grid, align_corners=True, padding_mode="zeros")[0, :, 0].T
    nj_s = F.normalize(nj_s, dim=-1, eps=1e-6)
    qx = (u - cx) / fx * dj_s
    qy = (v - cy) / fy * dj_s
    Qj = torch.stack([qx, qy, dj_s], dim=-1)

    inside = (u >= 0) & (u <= wl - 1) & (v >= 0) & (v <= hl - 1)
    valid_dp = (dj_s > gj["min_d"]) & (dj_s < gj["max_d"])
    depth_ok = (Qj[:, 2] - Pj[:, 2]).abs() < depth_gate
    Nj_i = Ni @ R_ij.T
    normal_ok = (nj_s * Nj_i).sum(-1) > normal_cos
    finite = torch.isfinite(u) & torch.isfinite(v) & torch.isfinite(dj_s)
    m = inside & (z > gj["min_d"]) & valid_dp & depth_ok & normal_ok & finite
    if gj["mgrid"] is not None:
        mj_s = F.grid_sample(gj["mgrid"], grid, align_corners=True, padding_mode="zeros")[0, 0, 0]
        m = m & (mj_s <= 0.5)
    if int(m.sum()) < min_pts:
        return None
    return {
        "Pj": Pj, "nj_s": nj_s, "Qj": Qj, "Pi": Pi, "Ni": Ni,
        "u": u, "v": v, "z": z, "m": m, "R_ij": R_ij, "grid": grid, "gxn": gxn, "gyn": gyn,
    }


def _edge_weighted_resid_fixed(gi, gj, Tcw_i, Tcw_j, cfg, device, freeze=None):
    """Reliability-weighted masked point-to-plane residual on a FIXED t=0 correspondence set.

    codex 019fc6be FATAL-2/FATAL-3: the primary gate metric must (a) hold the correspondence
    set, the MAD robust weight, and the reliability weight FROZEN at t=0 (changing support
    across t makes costs non-comparable and can fake "GO" by rejecting hard pixels), and
    (b) test the GN local linearization (frozen-weight directional derivative), not a
    re-evaluated piecewise objective at t=.02/.05.

    Two modes:
      * ``freeze is None`` (the t=0 call): compute the full inlier gate ``m0``, sample
        ``w_j0 = grid_sample(gj.wgrid)`` at t=0, ``w_i = gi.w_src[m0]``,
        ``w_rel0 = sqrt(w_i * w_j0)``, the t=0 MAD robust weight ``w_robust0``, and the
        residual ``r0`` + Jacobians ``J_i, J_j``. Returns ``state`` (everything needed to
        re-evaluate at another t with the SAME support) plus ``(r0, J_i, J_j, w_total0,
        m0, N_fixed)`` where ``w_total0 = w_robust0 * w_rel0``.
      * ``freeze is not None`` (a t>0 call with a prior ``state``): re-project under the new
        poses but ONLY over the frozen ``m0`` indices, sample target geometry at the NEW
        projected locations, compute ``r(t)`` and the NEW Jacobians (so the GN linearization
        at t is well-posed), but keep ``w_total0``/``N_fixed`` frozen. Returns
        ``(r_t, J_i_t, J_j_t, w_total0, m0, N_fixed)``.

    ``N_fixed = int(m0.sum())`` is the FIXED denominator across all t (FATAL-2).
    """
    proj = _project_source(gi, gj, Tcw_i, Tcw_j, cfg, device)
    if proj is None:
        return None
    m0 = proj["m"]
    Pj = proj["Pj"][m0]
    nj_m = proj["nj_s"][m0]
    Pi_m = proj["Pi"][m0]
    Ni_m = proj["Ni"][m0]
    Qj_m = proj["Qj"][m0]
    R_ij = proj["R_ij"]
    r0 = (nj_m * (Pj - Qj_m)).sum(-1)
    J_j = torch.cat([torch.cross(Pj, nj_m, dim=-1), nj_m], dim=-1)  # (K,6)
    ni_p = nj_m @ R_ij  # R_ij^T n_j
    J_i = -torch.cat([torch.cross(Pi_m, ni_p, dim=-1), ni_p], dim=-1)  # (K,6)
    # reliability weight: two-sided geometric mean (codex: sqrt(w_i*w_j))
    w_src = gi.get("w_src", None)
    if w_src is not None:
        w_i = w_src[m0] if w_src.shape[0] == proj["Pi"].shape[0] else torch.ones_like(r0)
    else:
        w_i = torch.ones_like(r0)
    w_j0 = F.grid_sample(
        gj["wgrid"], proj["grid"], align_corners=True, padding_mode="zeros"
    )[0, 0, 0]
    w_j0 = w_j0[m0]
    w_rel0 = torch.sqrt(w_i.clamp(min=1e-6) * w_j0.clamp(min=1e-6))
    # MAD robust weight at t=0 (frozen across t -- the solver's IRLS endpoint uses the t=0
    # robust scale as the fixed weighting; this isolates the reliability contribution)
    med = r0.median()
    mad = 1.4826 * (r0 - med).abs().median() + 1e-6
    w_robust0 = torch.clamp((1.5 * mad) / r0.abs().clamp(min=1e-6), max=1.0)
    w_total0 = w_robust0 * w_rel0
    N_fixed = int(m0.sum())
    # r0 over ALL source pixels (carry-forward for OOB re-projections at t>0)
    r0_full = (proj["nj_s"] * (proj["Pj"] - proj["Qj"])).sum(-1)
    state = {
        "m0": m0, "Pi_all": proj["Pi"], "Ni_all": proj["Ni"],
        "w_src": w_src, "gj": gj, "gi": gi, "w_total0": w_total0,
        "r0_all": r0_full,
    }
    return (r0, J_i, J_j, w_total0, m0, N_fixed), state


def _reproject_fixed(gi, gj, Tcw_i, Tcw_j, cfg, device):
    """Project gi's source points into gj under new poses WITHOUT re-gating (no min_pts
    cull, no depth/normal/inside gate). Returns the raw per-source-pixel Pj, projected
    (u,v,z), sampled target depth/normal/Qj, and an in-bounds + finite mask. Used by
    _edge_weighted_resid_at_t to evaluate the SAME source pixels (m0) across all t without
    dropping any (codex 019fc738 FATAL-1: the t=0 correspondence set is fixed; OOB / invalid
    re-projections carry their t=0 residual, so the denominator N_fixed is constant)."""
    Pi, Ni = gi["Ps"], gi["Ns"]
    T_ij = Tcw_j @ torch.linalg.inv(Tcw_i)
    R_ij, t_ij = T_ij[:3, :3], T_ij[:3, 3]
    fx, fy, cx, cy = gj["fx"], gj["fy"], gj["cx"], gj["cy"]
    hl, wl = gj["hl"], gj["wl"]
    Pj = Pi @ R_ij.T + t_ij
    z = Pj[:, 2]
    z_safe = torch.where(z.abs() > 1e-6, z, torch.ones_like(z))
    u = fx * Pj[:, 0] / z_safe + cx
    v = fy * Pj[:, 1] / z_safe + cy
    gxn = (u / (wl - 1)) * 2 - 1
    gyn = (v / (hl - 1)) * 2 - 1
    grid = torch.stack([gxn, gyn], dim=-1)[None, None]
    dj_s = F.grid_sample(gj["dgrid"], grid, align_corners=True, padding_mode="zeros")[0, 0, 0]
    nj_s = F.grid_sample(gj["ngrid"], grid, align_corners=True, padding_mode="zeros")[0, :, 0].T
    nj_s = F.normalize(nj_s, dim=-1, eps=1e-6)
    qx = (u - cx) / fx * dj_s
    qy = (v - cy) / fy * dj_s
    Qj = torch.stack([qx, qy, dj_s], dim=-1)
    valid = (
        (u >= 0) & (u <= wl - 1) & (v >= 0) & (v <= hl - 1)
        & torch.isfinite(u) & torch.isfinite(v) & torch.isfinite(dj_s)
        & (z > gj["min_d"]) & (dj_s > gj["min_d"]) & (dj_s < gj["max_d"])
    )
    if gj["mgrid"] is not None:
        mj_s = F.grid_sample(gj["mgrid"], grid, align_corners=True, padding_mode="zeros")[0, 0, 0]
        valid = valid & (mj_s <= 0.5)
    return {"Pj": Pj, "nj_s": nj_s, "Qj": Qj, "Pi": Pi, "Ni": Ni, "u": u, "v": v,
            "z": z, "valid": valid, "R_ij": R_ij, "grid": grid}


def _edge_weighted_resid_at_t(state, gi, gj, Tcw_i, Tcw_j, cfg, device):
    """Re-evaluate the fixed-support weighted residual at a new t using ``state`` (m0).

    codex 019fc6be FATAL-2: the t=0 inlier set ``m0`` is the FIXED support. Re-project the
    SAME source pixels under the new poses and sample target geometry at the NEW projected
    locations, but:
      * do NOT re-apply the depth_gate / normal_ok / min_pts gate (those selected m0; they
        must not un-select pixels at t>0 -- that was the bug, codex 019fc738 FATAL-1).
      * pixels whose re-projection is OOB / invalid (depth went NaN, out of image, behind
        camera, or onto a person) CARRY their t=0 residual (state["r0_all"][m0]), so the
        denominator N_fixed is exactly constant. This is the intended "carry-forward" that
        the prior code's comment promised but did not implement.
    Weights ``w_total0`` are the frozen t=0 values. Returns
    ``(r_t, J_i_t, J_j_t, w_total0, N_fixed)`` (N_fixed == len(m0), constant) or None only
    if gi has no source points at all.
    """
    if gi["Ps"].shape[0] == 0:
        return None
    proj = _reproject_fixed(gi, gj, Tcw_i, Tcw_j, cfg, device)
    m0 = state["m0"]
    r0_full = state["r0_all"]  # (Ns_full,) t=0 residual over ALL source pixels
    Pj_m = proj["Pj"][m0]
    nj_m = proj["nj_s"][m0]
    Pi_m = proj["Pi"][m0]
    Qj_m = proj["Qj"][m0]
    R_ij = proj["R_ij"]
    r_new = (nj_m * (Pj_m - Qj_m)).sum(-1)
    # valid re-projection mask over the m0 subset
    valid_m = proj["valid"][m0]
    r_t = torch.where(valid_m, r_new, r0_full[m0])  # carry t=0 residual if OOB/invalid
    J_j = torch.cat([torch.cross(Pj_m, nj_m, dim=-1), nj_m], dim=-1)  # (K,6)
    ni_p = nj_m @ R_ij  # R_ij^T n_j
    J_i = -torch.cat([torch.cross(Pi_m, ni_p, dim=-1), ni_p], dim=-1)  # (K,6)
    w_total0 = state["w_total0"]
    N_fixed = int(m0.sum())  # constant across t
    return r_t, J_i, J_j, w_total0, N_fixed


def _edge_dynamic_cost(gi, gj, Tcw_i, Tcw_j, cfg, device):
    """Dynamic-support reliability-weighted edge cost (the REAL solver ``opt_cost`` per-edge).

    codex 019fc6be FATAL-2 diagnostic: re-evaluate inlier set + MAD weight + reliability
    weight fresh at each t (what ``run_dba_v0.opt_cost`` actually does). Returns
    ``(cost = sum(w_robust*w_rel*r^2)/N_inliers, n_inliers, median|r|)`` or None. The primary
    gate uses the fixed-support metric; this is reported alongside and must AGREE in
    direction for a GO (selection-bias guard).
    """
    res = _edge_two_sided(gi, gj, Tcw_i, Tcw_j, cfg, device)
    if res is None:
        return None
    r, J_i, J_j, w_robust = res
    # reliability weight (dynamic): re-sample w_j at the dynamic inlier locations
    w_src = gi.get("w_src", None)
    proj = _project_source(gi, gj, Tcw_i, Tcw_j, cfg, device)
    if proj is None:
        w_rel = torch.ones_like(r)
    else:
        m = proj["m"]
        w_j = F.grid_sample(gj["wgrid"], proj["grid"], align_corners=True, padding_mode="zeros")[0, 0, 0]
        # align w_robust's inlier set (res was computed inside _edge_two_sided which culled
        # the same m via min_pts; the shapes match because both use the same gate)
        if w_src is not None and w_src.shape[0] == proj["Pi"].shape[0]:
            w_i_m = w_src[m]
        else:
            w_i_m = torch.ones_like(r)
        w_j_m = w_j[m]
        # r here is already the culled (m) subset from _edge_two_sided; lengths must match
        n = min(w_i_m.shape[0], w_j_m.shape[0], r.shape[0])
        w_i_m = w_i_m[:n]
        w_j_m = w_j_m[:n]
        r_ = r[:n]
        w_rel = torch.sqrt(w_i_m.clamp(min=1e-6) * w_j_m.clamp(min=1e-6))
        w_robust = w_robust[:n]
        r = r_
    w_total = w_robust * w_rel
    n = int(r.shape[0])
    cost = float((w_total * r * r).sum()) / max(n, 1)
    return cost, n, float(r.abs().median())


def _depth_tensor(cam, device):
    d = getattr(cam, "depth", None)
    if d is None:
        return None
    if not torch.is_tensor(d):
        d = torch.from_numpy(d)
    d = d.to(device=device, dtype=torch.float32)
    return d.squeeze(0) if d.dim() == 3 else d


def _person_mask(config, cam, device):
    m = get_or_compute_dynamic_mask(config, cam)
    if m is None:
        return None
    m = m.to(device).bool()
    return m.squeeze(0) if m.dim() == 3 else m


def _edge_residual_jac(cam_i, cam_j, T_ij, config, cfg, device):
    """Masked point-to-plane residual + Jacobian for KF edge i->j.

    T_ij (4x4): maps a point in cam_i frame to cam_j frame (Tcw_j @ inv(Tcw_i)).
    Returns (r, J, w) over inlier correspondences (J is d r / d(left-perturbation of
    the j-frame pose) = [Pj x nj, nj], matching coarse_pose convention), or None.
    """
    min_d = float(cfg.get("min_depth", 0.05))
    max_d = float(cfg.get("max_depth", 5.0))
    s = int(cfg.get("stride", 4))
    grad_thr = float(cfg.get("grad_thresh", 0.02))
    depth_gate = float(cfg.get("depth_gate", 0.10))
    normal_cos = math.cos(float(cfg.get("normal_deg", 30.0)) * math.pi / 180.0)
    min_pts = int(cfg.get("min_points", 500))

    di = _depth_tensor(cam_i, device)
    dj = _depth_tensor(cam_j, device)
    if di is None or dj is None:
        return None
    mask_i = _person_mask(config, cam_i, device)
    mask_j = _person_mask(config, cam_j, device)

    di = di[::s, ::s].contiguous()
    dj = dj[::s, ::s].contiguous()
    hl, wl = di.shape
    fx, fy = cam_i.fx / s, cam_i.fy / s
    cx, cy = cam_i.cx / s, cam_i.cy / s

    vert_i = _backproject(di, fx, fy, cx, cy)
    norm_i = _normals_from_vertex(vert_i)
    valid_i = (di > min_d) & (di < max_d) & (norm_i.norm(dim=-1) > 0.5)
    # semi-dense: keep pixels with depth gradient (geometry/texture) above a floor.
    gx = torch.zeros_like(di)
    gy = torch.zeros_like(di)
    gx[:, 1:-1] = (di[:, 2:] - di[:, :-2]).abs()
    gy[1:-1, :] = (di[2:, :] - di[:-2, :]).abs()
    valid_i = valid_i & ((gx + gy) > grad_thr)
    if mask_i is not None:
        mi = mask_i[::s, ::s]
        if mi.shape == valid_i.shape:
            valid_i = valid_i & (~mi)
    Pi = vert_i[valid_i]
    Ni = norm_i[valid_i]
    if Pi.shape[0] < min_pts:
        return None

    vert_j = _backproject(dj, fx, fy, cx, cy)
    norm_j = _normals_from_vertex(vert_j)
    dj_grid = dj[None, None]
    nj_grid = norm_j.permute(2, 0, 1)[None]
    mj_grid = None
    if mask_j is not None:
        mj = mask_j[::s, ::s]
        if mj.shape == dj.shape:
            mj_grid = mj.float()[None, None]

    R, t = T_ij[:3, :3], T_ij[:3, 3]
    Pj = Pi @ R.T + t
    Nj_i = Ni @ R.T
    z = Pj[:, 2]
    u = fx * Pj[:, 0] / z + cx
    v = fy * Pj[:, 1] / z + cy
    gxn = (u / (wl - 1)) * 2 - 1
    gyn = (v / (hl - 1)) * 2 - 1
    grid = torch.stack([gxn, gyn], dim=-1)[None, None]
    dj_s = F.grid_sample(dj_grid, grid, align_corners=True, padding_mode="zeros")[
        0, 0, 0
    ]
    nj_s = F.grid_sample(nj_grid, grid, align_corners=True, padding_mode="zeros")[
        0, :, 0
    ].T
    nj_s = F.normalize(nj_s, dim=-1, eps=1e-6)
    qx = (u - cx) / fx * dj_s
    qy = (v - cy) / fy * dj_s
    Qj = torch.stack([qx, qy, dj_s], dim=-1)

    inside = (u >= 0) & (u <= wl - 1) & (v >= 0) & (v <= hl - 1)
    valid_dp = (dj_s > min_d) & (dj_s < max_d)
    depth_ok = (Qj[:, 2] - Pj[:, 2]).abs() < depth_gate
    normal_ok = (nj_s * Nj_i).sum(-1) > normal_cos
    finite = torch.isfinite(u) & torch.isfinite(v) & torch.isfinite(dj_s)
    m = inside & (z > min_d) & valid_dp & depth_ok & normal_ok & finite
    if mj_grid is not None:
        mj_s = F.grid_sample(mj_grid, grid, align_corners=True, padding_mode="zeros")[
            0, 0, 0
        ]
        m = m & (mj_s <= 0.5)
    if int(m.sum()) < min_pts:
        return None

    Pj_m, nj_m = Pj[m], nj_s[m]
    r = (nj_m * (Pj_m - Qj[m])).sum(-1)
    J = torch.cat([torch.cross(Pj_m, nj_m, dim=-1), nj_m], dim=-1)  # (K,6)
    med = r.median()
    mad = 1.4826 * (r - med).abs().median() + 1e-6
    w = torch.clamp((1.5 * mad) / r.abs().clamp(min=1e-6), max=1.0)
    return r, J, w


def _hessian_stats(J, w):
    Jw = J * w[:, None]
    H = Jw.T @ J  # 6x6
    eig = torch.linalg.eigvalsh(H).clamp(min=0)
    emax = float(eig.max())
    emin = float(eig.min())
    cond = emax / emin if emin > 1e-12 else float("inf")
    rank = int((eig > 1e-6 * max(emax, 1e-12)).sum())
    return H, cond, rank


def _median_abs_resid(res):
    if res is None:
        return None
    r, _, _ = res
    return float(r.abs().median())


def _gn_reduction(cam_i, cam_j, T_ij, config, cfg, device):
    """From a KNOWN SE(3) perturbation of T_ij, run a few GN steps and report the
    median-|residual| REDUCTION ratio (1.0 = the perturbation is fully annealed away).

    This is valid even when T_ij is NOT the geometric minimum (real SLAM poses are the
    photometric estimate, so a "recover exactly -xi" metric is confounded by the
    base misalignment and can go negative even for a perfectly good solver). Reduction
    of the robust residual from a perturbed state is the correct well-posedness signal.
    """
    dtheta = float(cfg.get("probe_rot_deg", 2.0)) * math.pi / 180.0
    dtrans = float(cfg.get("probe_trans", 0.03))
    xi = torch.tensor(
        [dtheta, 0.0, 0.0, dtrans, 0.0, 0.0], device=device, dtype=torch.float32
    )
    T = _se3_exp(xi) @ T_ij
    m0 = _median_abs_resid(_edge_residual_jac(cam_i, cam_j, T, config, cfg, device))
    if m0 is None or m0 <= 0:
        return None
    max_rot = float(cfg.get("max_update_rot_deg", 5.0)) * math.pi / 180.0
    max_trans = float(cfg.get("max_update_trans", 0.10))
    for _ in range(int(cfg.get("gn_iters", 5))):
        res = _edge_residual_jac(cam_i, cam_j, T, config, cfg, device)
        if res is None:
            break
        r, J, w = res
        Jw = J * w[:, None]
        try:
            dx = -torch.linalg.solve(
                Jw.T @ J + 1e-6 * torch.eye(6, device=device), Jw.T @ r
            )
        except Exception:
            break
        if torch.norm(dx[:3]) > max_rot or torch.norm(dx[3:]) > max_trans:
            break
        T = _se3_exp(dx) @ T
    mf = _median_abs_resid(_edge_residual_jac(cam_i, cam_j, T, config, cfg, device))
    if mf is None:
        return None
    return 1.0 - mf / m0


def _median(xs):
    return sorted(xs)[len(xs) // 2] if xs else float("nan")


def run_dba_diagnostic(viewpoints, config):
    """Aggregate the masked-edge conditioning diagnostic over temporal KF pairs and
    log a HEALTHY / ILL-CONDITIONED verdict. Read-only; safe to call at run end."""
    cfg = get_dba_lite_config(config)
    device = "cuda"
    kf_ids = sorted(viewpoints.keys())
    if len(kf_ids) < 3:
        Log("DBA-lite diagnostic: <3 KFs, skip")
        return None
    offsets = [int(o) for o in cfg.get("edge_offsets", [1, 2])]
    cond_warn = float(cfg.get("cond_warn", 1e4))

    inliers, conds, ranks, reductions = [], [], [], []
    n_edges = n_degen = 0
    for a in range(len(kf_ids)):
        for off in offsets:
            b = a + off
            if b >= len(kf_ids):
                continue
            ci, cj = viewpoints[kf_ids[a]], viewpoints[kf_ids[b]]
            Tcw_i = getWorld2View2(ci.R, ci.T).to(device)
            Tcw_j = getWorld2View2(cj.R, cj.T).to(device)
            T_ij = Tcw_j @ torch.linalg.inv(Tcw_i)
            res = _edge_residual_jac(ci, cj, T_ij, config, cfg, device)
            if res is None:
                continue
            r, J, w = res
            _, cond, rank = _hessian_stats(J, w)
            red = _gn_reduction(ci, cj, T_ij, config, cfg, device)
            n_edges += 1
            inliers.append(int(r.shape[0]))
            conds.append(cond)
            ranks.append(rank)
            if red is not None:
                reductions.append(red)
            if rank < 6 or cond > cond_warn:
                n_degen += 1
    if n_edges == 0:
        Log("DBA-lite diagnostic: no valid edges (check masks/depth availability)")
        return None

    med_inl = _median(inliers)
    med_red = _median(reductions)
    healthy = (
        n_degen < 0.2 * n_edges
        and (med_red == med_red and med_red > 0.5)  # not NaN and > 0.5 residual drop
        and med_inl > float(cfg.get("min_points", 500))
    )
    Log(
        "=== DBA-lite DIAGNOSTIC (P2a) ===\n"
        f"  edges={n_edges} offsets={offsets}\n"
        f"  inliers:  med={med_inl} min={min(inliers)} max={max(inliers)}\n"
        f"  cond#:    med={_median(conds):.1f} max={max(conds):.1f} "
        f"(ill-cond/rank-deficient edges: {n_degen}/{n_edges}, warn>{cond_warn:g})\n"
        f"  rank<6:   {sum(1 for x in ranks if x < 6)}/{n_edges}\n"
        f"  GN residual reduction: med={med_red:.3f} (1.0=perturbation fully annealed) "
        f"over {len(reductions)} edges\n"
        f"  VERDICT: {'HEALTHY -> geometry well-posed, build v0 pose-graph solver' if healthy else 'ILL-CONDITIONED -> do NOT build dense solver as-is (need feature anchors / more edges / degeneracy handling)'}"
    )
    return {
        "n_edges": n_edges,
        "n_degen": n_degen,
        "med_inliers": med_inl,
        "med_cond": _median(conds),
        "med_reduction": med_red,
        "healthy": healthy,
    }


def _reload_kf_geom(dataset, cam, idx, config, cfg, device):
    """Reload a KF's pose-independent geometry in the MAIN process (Path C): gt depth +
    fresh person mask from the dataset (robust vs whether frontend cameras retained
    depth/RGB). Pose comes from `cam` (the estimate to optimize)."""
    try:
        gt_color, gt_depth, _ = dataset[idx]
    except Exception:
        return None
    if gt_depth is None:
        return None
    depth = torch.from_numpy(gt_depth).to(device).float()
    if depth.dim() == 3:
        depth = depth.squeeze(0)
    mask = None
    if semantic_mask_enabled(config):
        mask = compute_semantic_dynamic_mask(config, gt_color)  # (1,H,W) bool or None
        if mask is not None and mask.dim() == 3:
            mask = mask.squeeze(0)
    gray = None
    if torch.is_tensor(gt_color) and gt_color.dim() == 3 and gt_color.shape[0] == 3:
        c = gt_color.to(device).float()
        gray = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]  # (H,W) in [0,1]
    return _precompute_kf_geom(
        depth,
        mask,
        float(cam.fx),
        float(cam.fy),
        float(cam.cx),
        float(cam.cy),
        cfg,
        device,
        gray=gray,
    )


def _build_edges(kfs, offsets):
    e = []
    for a in range(len(kfs)):
        for off in offsets:
            b = a + off
            if b < len(kfs):
                e.append((kfs[a], kfs[b]))
    return e


def _edge_photometric_resid(gi, gj, Tcw_i, Tcw_j, cfg, device):
    """Photometric proxy: warp masked static source pixels of KF i into KF j, sample
    target gray, and return the robust median |r_rgb| AFTER a per-edge affine brightness
    fit (gray_j ~ a*gray_i + b) that absorbs exposure/auto-white-balance (codex's #1
    photometric failure guard). Uses the SAME geometric inlier gating as the geometric
    edge so the two proxies are compared on comparable correspondences. Returns
    median|r| over inliers or None."""
    if gi.get("Is") is None or gj.get("graygrid") is None:
        return None
    min_pts = int(cfg.get("min_points", 500))
    depth_gate = float(cfg.get("depth_gate", 0.10))
    Pi, Ii = gi["Ps"], gi["Is"]
    if Pi.shape[0] < min_pts:
        return None
    T_ij = Tcw_j @ torch.linalg.inv(Tcw_i)
    R_ij, t_ij = T_ij[:3, :3], T_ij[:3, 3]
    fx, fy, cx, cy = gj["fx"], gj["fy"], gj["cx"], gj["cy"]
    hl, wl = gj["hl"], gj["wl"]
    Pj = Pi @ R_ij.T + t_ij
    z = Pj[:, 2]
    u = fx * Pj[:, 0] / z + cx
    v = fy * Pj[:, 1] / z + cy
    gxn = (u / (wl - 1)) * 2 - 1
    gyn = (v / (hl - 1)) * 2 - 1
    grid = torch.stack([gxn, gyn], dim=-1)[None, None]
    gj_s = F.grid_sample(
        gj["graygrid"], grid, align_corners=True, padding_mode="zeros"
    )[0, 0, 0]
    dj_s = F.grid_sample(gj["dgrid"], grid, align_corners=True, padding_mode="zeros")[
        0, 0, 0
    ]
    inside = (u >= 0) & (u <= wl - 1) & (v >= 0) & (v <= hl - 1)
    valid_dp = (dj_s > gj["min_d"]) & (dj_s < gj["max_d"])
    depth_ok = (dj_s - Pj[:, 2]).abs() < depth_gate
    finite = torch.isfinite(u) & torch.isfinite(v) & torch.isfinite(gj_s)
    m = inside & (z > gj["min_d"]) & valid_dp & depth_ok & finite
    if gj["mgrid"] is not None:
        mj_s = F.grid_sample(
            gj["mgrid"], grid, align_corners=True, padding_mode="zeros"
        )[0, 0, 0]
        m = m & (mj_s <= 0.5)
    if int(m.sum()) < min_pts:
        return None
    gi_m, gj_m = Ii[m], gj_s[m]
    # per-edge affine brightness fit gray_j ~= a*gray_i + b (absorb exposure)
    A = torch.stack([gi_m, torch.ones_like(gi_m)], dim=-1)  # (K,2)
    try:
        sol = torch.linalg.lstsq(A, gj_m.unsqueeze(-1)).solution.squeeze(-1)
        a, b = sol[0], sol[1]
    except Exception:
        a, b = torch.tensor(1.0, device=device), torch.tensor(0.0, device=device)
    r = (a * gi_m + b) - gj_m
    return float(r.abs().median())


def dba_lite_oracle_enabled(config):
    return bool(get_dba_lite_config(config).get("oracle", False))


def _cam_center(Tcw):
    """Camera center in world frame = inv(Tcw)[:3,3]."""
    return torch.linalg.inv(Tcw)[:3, 3]


def run_dba_oracle(cameras, kf_indices, dataset, config):
    """GT-oracle falsifier (codex, thread 019f63d8): BEFORE investing in a photometric
    term, prove whether the masked GEOMETRIC objective even prefers GT poses. On the
    identical masked edges/pixels, interpolate KF poses along the SE(3) geodesic from
    the online (photometric) estimate (t=0) to GT (t=1) and report the aggregate edge
    residual + an ATE-proxy (camera-center RMSE vs GT, gauge-shared since KF0 anchors
    GT origin) at each t. If the geometric residual RISES as poses approach GT (t->1)
    while the ATE-proxy FALLS, the objective is biased away from GT -> a learning-free
    geometric pose-graph BA CANNOT close the gap here (report the negative result). If
    GT gives clearly LOWER residual than online, geometry should help -> suspect a
    solver/gauge/prior bug instead. Read-only; default-off (DBALite.oracle)."""
    cfg = get_dba_lite_config(config)
    device = "cuda"
    kfs = sorted(int(k) for k in kf_indices if int(k) in cameras)
    if len(kfs) < 3:
        Log("DBA-lite oracle: <3 KFs, skip")
        return None
    geom = {}
    for k in kfs:
        g = _reload_kf_geom(dataset, cameras[k], k, config, cfg, device)
        if g is not None and g["Ps"].shape[0] >= int(cfg.get("min_points", 500)):
            geom[k] = g
    kfs = [k for k in kfs if k in geom]
    if len(kfs) < 3:
        Log("DBA-lite oracle: <3 KFs with usable geometry, skip")
        return None

    T_on = {k: getWorld2View2(cameras[k].R, cameras[k].T).to(device) for k in kfs}
    T_gt = {k: getWorld2View2(cameras[k].R_gt, cameras[k].T_gt).to(device) for k in kfs}
    xi = {k: _se3_log(T_gt[k] @ torch.linalg.inv(T_on[k])) for k in kfs}
    edges = _build_edges(kfs, [int(o) for o in cfg.get("opt_offsets", [1, 2, 5])])

    def pose_at(t):
        return {k: _se3_exp(t * xi[k]) @ T_on[k] for k in kfs}

    def agg_resid(Tt):
        vals = []
        for i, j in edges:
            res = _edge_two_sided(geom[i], geom[j], Tt[i], Tt[j], cfg, device)
            if res is not None:
                vals.append(float(res[0].abs().median()))
        return _median(vals) if vals else float("nan"), len(vals)

    def agg_photo(Tt):
        vals = []
        for i, j in edges:
            rp = _edge_photometric_resid(geom[i], geom[j], Tt[i], Tt[j], cfg, device)
            if rp is not None:
                vals.append(rp)
        return _median(vals) if vals else float("nan")

    def ate_proxy(Tt):
        d = [float(torch.norm(_cam_center(Tt[k]) - _cam_center(T_gt[k]))) for k in kfs]
        return (sum(x * x for x in d) / len(d)) ** 0.5 * 100.0  # cm RMSE

    rows = []
    for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
        Tt = pose_at(t)
        rmed, nval = agg_resid(Tt)
        rows.append((t, rmed, ate_proxy(Tt), nval, agg_photo(Tt)))

    # per-edge online(t=0) vs GT(t=1): how often does GT fit the masked geometry better?
    Ton, Tgt = pose_at(0.0), pose_at(1.0)
    gt_better = on_better = 0
    for i, j in edges:
        ro = _edge_two_sided(geom[i], geom[j], Ton[i], Ton[j], cfg, device)
        rg = _edge_two_sided(geom[i], geom[j], Tgt[i], Tgt[j], cfg, device)
        if ro is None or rg is None:
            continue
        if float(rg[0].abs().median()) < float(ro[0].abs().median()):
            gt_better += 1
        else:
            on_better += 1

    r_on, r_gt = rows[0][1], rows[-1][1]
    p_on, p_gt = rows[0][4], rows[-1][4]
    biased = r_gt >= r_on  # GT does NOT lower the geometric objective
    photo_biased = p_gt == p_gt and p_on == p_on and p_gt >= p_on
    photo_ok = p_on == p_on and p_gt == p_gt
    table = "\n".join(
        f"    t={t:.2f}  geo-resid={r:.5f} m  photo-resid={p:.5f}  ate-proxy={a:.2f} cm  edges={n}"
        for (t, r, a, n, p) in rows
    )
    if photo_ok:
        photo_line = (
            "PHOTO-BIASED too — brightness-corrected photometric also does NOT prefer GT "
            "(%.5f >= %.5f); learning-free RGB-D BA (geo+photo) cannot close the gap → NEGATIVE result"
            % (p_gt, p_on)
            if photo_biased
            else "PHOTO PREFERS GT (%.5f < %.5f) — a photometric term IS the missing "
            "constraint the masked geometry lacks → implement + test the direct photometric BA"
            % (p_gt, p_on)
        )
    else:
        photo_line = "photometric proxy unavailable (no gray) — geometric verdict only"
    Log(
        "=== DBA-lite GT-ORACLE FALSIFIER ===\n"
        f"  edges={len(edges)} offsets={cfg.get('opt_offsets', [1, 2, 5])}\n"
        f"  online(t=0) ate-proxy={rows[0][2]:.2f}cm  GT(t=1) ate-proxy={rows[-1][2]:.2f}cm\n"
        f"{table}\n"
        f"  per-edge geo: GT-fits-better={gt_better}  online-fits-better={on_better}\n"
        f"  GEO VERDICT: {'BIASED — masked geometry does NOT prefer GT (resid at GT %.5f >= online %.5f); geometric BA cannot close the gap here' % (r_gt, r_on) if biased else 'GT lowers the geometric objective (%.5f < %.5f) → geometry SHOULD help; v0 worsening ATE = a solver/gauge/prior BUG' % (r_gt, r_on)}\n"
        f"  PHOTO VERDICT: {photo_line}"
    )
    return {
        "rows": rows,
        "gt_better": gt_better,
        "on_better": on_better,
        "biased": biased,
        "photo_biased": photo_biased if photo_ok else None,
    }


def run_dba_v0(cameras, kf_indices, dataset, config):
    """v0 offline KF-only geometric pose-graph BA (doc 14 P2b). Reloads gt depth+mask
    per KF from the dataset (Path C, main process), then jointly optimizes KF poses
    (KF0 gauge-FIXED = excluded from the variable set, not zeroed) to minimize masked
    point-to-plane residuals over temporal + a few long-range edges. Held-out
    validation edges guard against overfitting the training edges (no GT used
    internally). Writes optimized poses back with update_RT. Default-off
    (DBALite.enabled)."""
    cfg = get_dba_lite_config(config)
    device = "cuda"
    kfs = sorted(int(k) for k in kf_indices if int(k) in cameras)
    if len(kfs) < 3:
        Log("DBA-lite v0: <3 KFs, skip")
        return
    geom = {}
    for k in kfs:
        g = _reload_kf_geom(dataset, cameras[k], k, config, cfg, device)
        if g is not None and g["Ps"].shape[0] >= int(cfg.get("min_points", 500)):
            geom[k] = g
    kfs = [k for k in kfs if k in geom]
    if len(kfs) < 3:
        Log("DBA-lite v0: <3 KFs with usable geometry, skip")
        return
    N = len(kfs)
    fixed = kfs[0]  # gauge fix: KF0 (GT origin) held fixed, excluded from variables
    free = [k for k in kfs if k != fixed]
    col = {k: i for i, k in enumerate(free)}  # variable-block index for free nodes
    n_free = len(free)
    T = {k: getWorld2View2(cameras[k].R, cameras[k].T).to(device) for k in kfs}
    T_anchor = {
        k: T[k].clone() for k in kfs
    }  # photometric estimate = pose prior anchor
    lam_prior = float(cfg.get("lm_prior", 1.0))
    eye6 = torch.eye(6, device=device)

    opt_edges = _build_edges(kfs, [int(o) for o in cfg.get("opt_offsets", [1, 2, 5])])
    val_edges = _build_edges(kfs, [int(o) for o in cfg.get("val_offsets", [3])])

    def opt_cost(Tcur):
        c = 0.0
        for i, j in opt_edges:
            res = _edge_two_sided(geom[i], geom[j], Tcur[i], Tcur[j], cfg, device)
            if res is not None:
                r, _, _, w = res
                we = w / max(int(r.shape[0]), 1)  # per-inlier-count edge normalization
                c += float((we * r * r).sum())
        if lam_prior > 0:  # anchor to the photometric global trajectory shape
            for k in free:
                rp = _se3_log(Tcur[k] @ torch.linalg.inv(T_anchor[k]))
                c += lam_prior * float((rp * rp).sum())
        return c

    def val_resid(Tcur):
        vals = []
        for i, j in val_edges:
            res = _edge_two_sided(geom[i], geom[j], Tcur[i], Tcur[j], cfg, device)
            if res is not None:
                vals.append(float(res[0].abs().median()))
        return _median(vals) if vals else float("nan")

    val0 = val_resid(T)
    c0 = opt_cost(T)
    lam = float(cfg.get("lm_lambda0", 1e-3))
    eye = torch.eye(6 * n_free, device=device)
    for _ in range(int(cfg.get("v0_iters", 12))):
        H = torch.zeros(6 * n_free, 6 * n_free, device=device)
        g = torch.zeros(6 * n_free, device=device)
        for i, j in opt_edges:
            res = _edge_two_sided(geom[i], geom[j], T[i], T[j], cfg, device)
            if res is None:
                continue
            r, Ji, Jj, w = res
            we = w / max(int(r.shape[0]), 1)  # per-inlier-count edge normalization
            wr = we * r
            blocks = []
            if i != fixed:
                blocks.append((col[i], Ji))
            if j != fixed:
                blocks.append((col[j], Jj))
            for bi, Jb in blocks:
                g[6 * bi : 6 * bi + 6] += Jb.T @ wr
                Jbw = Jb * we[:, None]
                for bj, Jc in blocks:
                    H[6 * bi : 6 * bi + 6, 6 * bj : 6 * bj + 6] += Jbw.T @ Jc
        if lam_prior > 0:  # pose prior: keep KFs near their photometric estimate
            for k in free:
                bi = col[k]
                rp = _se3_log(T[k] @ torch.linalg.inv(T_anchor[k]))
                g[6 * bi : 6 * bi + 6] += lam_prior * rp
                H[6 * bi : 6 * bi + 6, 6 * bi : 6 * bi + 6] += lam_prior * eye6
        try:
            dx = -torch.linalg.solve(H + lam * eye, g)
        except Exception:
            lam = min(lam * 4, 1e3)
            continue
        Tn = dict(T)
        maxstep = 0.0
        for k in free:
            d = dx[6 * col[k] : 6 * col[k] + 6]
            maxstep = max(maxstep, float(d.norm()))
            Tn[k] = _se3_exp(d) @ T[k]
        c_new = opt_cost(Tn)
        if c_new < c0:
            improved = (c0 - c_new) / max(c0, 1e-9)
            T, c0 = Tn, c_new
            lam = max(lam * 0.5, 1e-6)
            if maxstep < 1e-5 or improved < 1e-4:
                break
        else:
            lam = min(lam * 4, 1e3)

    val1 = val_resid(T)
    worsened = (
        val1 == val1 and val0 == val0 and val1 > val0 * float(cfg.get("val_tol", 1.10))
    )
    if worsened:
        Log(
            f"DBA-lite v0: REJECTED — held-out validation residual worsened "
            f"{val0:.4f}->{val1:.4f} m (poses UNCHANGED; guards vs train-edge overfit)"
        )
        return
    dts, drots = [], []
    for k in free:
        xi = _se3_log(T[k] @ torch.linalg.inv(T_anchor[k]))
        drots.append(float(torch.norm(xi[:3])) * 180.0 / math.pi)  # deg
        dts.append(float(torch.norm(xi[3:])))  # m
    for k in free:
        Tk = T[k]
        cameras[k].update_RT(Tk[:3, :3].contiguous(), Tk[:3, 3].contiguous())
    Log(
        f"DBA-lite v0: APPLIED to {n_free}/{N} KF poses "
        f"(opt-cost->{c0:.4g}, val-resid {val0:.4f}->{val1:.4f} m, "
        f"median|Δt|={_median(dts) * 100:.1f}cm max|Δt|={max(dts) * 100:.1f}cm, "
        f"median|Δrot|={_median(drots):.2f}° max|Δrot|={max(drots):.2f}°)"
    )
