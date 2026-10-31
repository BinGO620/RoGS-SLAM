"""P4a coarse pose initialization (Lever A).

Classical, semantic-free, cheap robust coarse pose *initialization* run BEFORE the
MonoGS Adam photometric refinement, to escape local minima on dynamic frames.
Two modes (config-gated, default-off):

  - ``const_vel``: ORB-SLAM3 constant-velocity motion model. Predicts the current
    world->camera pose from the previous two poses:
        V          = Tcw_prev @ inv(Tcw_prevprev)
        Tcw_pred   = V @ Tcw_prev
    (see ORB-SLAM3 Tracking.cc mVelocity / TrackWithMotionModel).

  - ``icp``: const_vel seed + robust frame-to-frame projective point-to-plane
    RGB-D ICP (current gt depth vs previous gt depth). Robust trimming (depth-diff
    gate, normal-angle gate, MAD + best-fraction trim, inlier-ratio fallback) keeps
    the moving person from dominating the normal equations. ICP only produces an
    *initializer*; the Gaussian photometric tracker still runs afterwards.

  - ``masked_icp``: like ``icp`` but the dynamic (person) mask is removed from BOTH
    the current source pixels AND the previous target pixels (sampled at the warp),
    so the mover supplies no correspondences on either endpoint -- the earlier
    UNMASKED icp locked onto the person (~50cm); masking both sides is the fix.
    A total-delta guard rejects an ICP result that drifts too far from the const_vel
    seed (mover lock) and falls back to const_vel. Requires masks (else falls back).
    SPEC-1, doc 14 (04-ours/14-backend_precision_plan.md).

Convention: MonoGS ``Camera.R``/``Camera.T`` are world->camera
(``P_cam = R @ P_world + T``), i.e. ``Tcw = getWorld2View2(R, T)`` in this fork
(the transpose line is commented out). We optimize the relative transform
``T_prev_curr`` (current cam -> previous cam) and convert back to absolute Tcw.

Everything here runs under no_grad -- it is a pose *guess*, not a differentiable
term. Enabling nothing leaves vanilla MonoGS tracking untouched.
"""

import torch
import torch.nn.functional as F

from gaussian_splatting.utils.graphics_utils import getWorld2View2
from utils.logging_utils import Log

# Per-pyramid-level default thresholds (from the adversarial-debate recipe, doc 13).
_DEFAULT_PYRAMID = [(4, 10), (2, 5), (1, 4)]  # (stride, gauss-newton iters)
_DEFAULT_DEPTH_GATE = {4: 0.10, 2: 0.07, 1: 0.05}  # |z_prev - z_curr| max, meters
_DEFAULT_NORMAL_DEG = {4: 35.0, 2: 30.0, 1: 25.0}  # max normal-angle disagreement
_DEFAULT_TRIM_ABS = {4: 0.05, 2: 0.04, 1: 0.03}  # MAD-trim absolute cap, meters


def get_coarse_pose_config(config):
    return config.get("CoarsePoseInit", {})


def coarse_pose_enabled(config):
    return bool(config.get("CoarsePoseInit", {}).get("enabled", False))


def _skew(w):
    z = torch.zeros((), device=w.device, dtype=w.dtype)
    return torch.stack(
        [
            torch.stack([z, -w[2], w[1]]),
            torch.stack([w[2], z, -w[0]]),
            torch.stack([-w[1], w[0], z]),
        ]
    )


def _se3_exp(xi):
    """xi = [omega(3), v(3)] -> 4x4 SE(3). Left-perturbation twist."""
    omega, v = xi[:3], xi[3:]
    theta = torch.norm(omega)
    Omega = _skew(omega)
    eye = torch.eye(3, device=xi.device, dtype=xi.dtype)
    if theta < 1e-8:
        R = eye + Omega
        V = eye
    else:
        Omega2 = Omega @ Omega
        A = torch.sin(theta) / theta
        B = (1.0 - torch.cos(theta)) / (theta**2)
        C = (1.0 - A) / (theta**2)
        R = eye + A * Omega + B * Omega2
        V = eye + B * Omega + C * Omega2
    T = torch.eye(4, device=xi.device, dtype=xi.dtype)
    T[:3, :3] = R
    T[:3, 3] = V @ v
    return T


def _backproject(depth, fx, fy, cx, cy):
    """depth (H,W) -> vertex map (H,W,3) in camera frame (P_cam)."""
    h, w = depth.shape
    vv, uu = torch.meshgrid(
        torch.arange(h, device=depth.device, dtype=depth.dtype),
        torch.arange(w, device=depth.device, dtype=depth.dtype),
        indexing="ij",
    )
    x = (uu - cx) / fx * depth
    y = (vv - cy) / fy * depth
    return torch.stack([x, y, depth], dim=-1)


def _normals_from_vertex(vertex):
    """Vertex map (H,W,3) -> per-pixel normals (H,W,3), oriented toward camera."""
    normals = torch.zeros_like(vertex)
    dvx = vertex[1:-1, 2:, :] - vertex[1:-1, :-2, :]  # d/du  (h-2,w-2,3)
    dvy = vertex[2:, 1:-1, :] - vertex[:-2, 1:-1, :]  # d/dv
    n = torch.cross(dvx, dvy, dim=-1)
    n = F.normalize(n, dim=-1, eps=1e-6)
    # Orient toward the camera: "toward" is n·P < 0 (P = camera-frame vertex),
    # not simply n.z < 0 (that fails on oblique surfaces).
    center = vertex[1:-1, 1:-1, :]
    flip = ((n * center).sum(dim=-1) > 0).unsqueeze(-1)
    n = torch.where(flip, -n, n)
    normals[1:-1, 1:-1, :] = n
    return normals


def _robust_projective_icp(
    depth_curr,
    depth_prev,
    fx,
    fy,
    cx,
    cy,
    T_pc,
    cfg,
    mask_curr=None,
    mask_prev=None,
    stats=None,
):
    """Refine relative pose T_pc (curr-cam -> prev-cam) by robust point-to-plane ICP.

    mask_curr / mask_prev: (H,W) bool person masks (True = dynamic) at full depth
    resolution, or None. When given, current person pixels are dropped from the ICP
    source set and matches that warp onto previous person geometry are rejected.
    """
    device = depth_curr.device
    min_d = float(cfg.get("min_depth", 0.05))
    max_d = float(cfg.get("max_depth", 5.0))
    pyramid = cfg.get("pyramid", _DEFAULT_PYRAMID)
    min_inlier_ratio = float(cfg.get("min_inlier_ratio", 0.30))
    min_points = int(cfg.get("min_points", 2000))
    best_fraction = float(cfg.get("best_fraction", 0.70))
    max_rot = float(cfg.get("max_update_rot_deg", 8.0)) * torch.pi / 180.0
    max_trans = float(cfg.get("max_update_trans", 0.15))
    eye6 = torch.eye(6, device=device, dtype=depth_curr.dtype)

    for stride, iters in pyramid:
        s = int(stride)
        dc = depth_curr[::s, ::s].contiguous()
        dp = depth_prev[::s, ::s].contiguous()
        hl, wl = dc.shape
        fxl, fyl, cxl, cyl = fx / s, fy / s, cx / s, cy / s
        depth_gate = float(cfg.get("depth_gate", {}).get(s, _DEFAULT_DEPTH_GATE[s]))
        normal_cos = torch.cos(
            torch.tensor(
                float(cfg.get("normal_deg", {}).get(s, _DEFAULT_NORMAL_DEG[s]))
                * torch.pi
                / 180.0,
                device=device,
            )
        )
        trim_abs = float(cfg.get("trim_abs", {}).get(s, _DEFAULT_TRIM_ABS[s]))

        vert_c = _backproject(dc, fxl, fyl, cxl, cyl)
        norm_c = _normals_from_vertex(vert_c)
        vert_p = _backproject(dp, fxl, fyl, cxl, cyl)
        norm_p = _normals_from_vertex(vert_p)

        valid_c = (dc > min_d) & (dc < max_d) & (norm_c.norm(dim=-1) > 0.5)
        # masked_icp: drop CURRENT-frame person pixels from the ICP source set so the
        # moving person cannot supply correspondences (mask both endpoints).
        if mask_curr is not None:
            mc = mask_curr[::s, ::s]
            if mc.shape == valid_c.shape:
                valid_c = valid_c & (~mc.bool())
        # prev-frame person mask, sampled at the warped target inside the loop below.
        mask_prev_grid = None
        if mask_prev is not None:
            mp_l = mask_prev[::s, ::s]
            if mp_l.shape == dc.shape:
                mask_prev_grid = mp_l.float()[None, None]  # (1,1,hl,wl)
        Pc = vert_c[valid_c]  # (Nc,3)
        Nc = norm_c[valid_c]  # (Nc,3)
        if Pc.shape[0] < min_points:
            continue
        if stats is not None:
            stats["source_pts"] = int(Pc.shape[0])

        dp_grid = dp[None, None]  # (1,1,hl,wl)
        norm_p_grid = norm_p.permute(2, 0, 1)[None]  # (1,3,hl,wl)

        for _ in range(int(iters)):
            R_pc, t_pc = T_pc[:3, :3], T_pc[:3, 3]
            Pp = Pc @ R_pc.T + t_pc  # curr points in prev-cam frame
            Np_c = Nc @ R_pc.T  # curr normals rotated into prev-cam frame
            z = Pp[:, 2]
            u = fxl * Pp[:, 0] / z + cxl
            v = fyl * Pp[:, 1] / z + cyl

            gx = (u / (wl - 1)) * 2 - 1
            gy = (v / (hl - 1)) * 2 - 1
            grid = torch.stack([gx, gy], dim=-1)[None, None]  # (1,1,Nc,2)
            dp_s = F.grid_sample(
                dp_grid, grid, align_corners=True, padding_mode="zeros"
            )[0, 0, 0]
            np_s = F.grid_sample(
                norm_p_grid, grid, align_corners=True, padding_mode="zeros"
            )[0, :, 0].T  # (Nc,3)
            np_s = F.normalize(np_s, dim=-1, eps=1e-6)

            mp_s = None
            if mask_prev_grid is not None:
                mp_s = F.grid_sample(
                    mask_prev_grid, grid, align_corners=True, padding_mode="zeros"
                )[0, 0, 0]

            qx = (u - cxl) / fxl * dp_s
            qy = (v - cyl) / fyl * dp_s
            Qp = torch.stack([qx, qy, dp_s], dim=-1)

            inside = (u >= 0) & (u <= wl - 1) & (v >= 0) & (v <= hl - 1)
            valid_dp = (dp_s > min_d) & (dp_s < max_d)
            depth_ok = (Qp[:, 2] - Pp[:, 2]).abs() < depth_gate
            normal_ok = (np_s * Np_c).sum(-1) > normal_cos
            finite = torch.isfinite(u) & torch.isfinite(v) & torch.isfinite(dp_s)
            m = inside & (z > min_d) & valid_dp & depth_ok & normal_ok & finite
            if mp_s is not None:
                m = m & (mp_s <= 0.5)  # reject matches landing on prev person geometry
            if int(m.sum()) < min_points:
                break

            Pp_m, np_m = Pp[m], np_s[m]
            r = (np_m * (Pp_m - Qp[m])).sum(-1)  # point-to-plane residual

            # Robust trim: MAD + best-fraction of |r|.
            med = r.median()
            mad = 1.4826 * (r - med).abs().median() + 1e-6
            keep = (r - med).abs() < min(2.5 * mad, trim_abs)
            if best_fraction < 1.0 and int(keep.sum()) > 0:
                thr = torch.quantile(r[keep].abs(), best_fraction)
                keep = keep & (r.abs() <= thr)
            n_keep = int(keep.sum())
            if n_keep < min_points or n_keep / max(int(m.sum()), 1) < min_inlier_ratio:
                break

            Pp_k, n_k, r_k = Pp_m[keep], np_m[keep], r[keep]
            hd_fixed = float(cfg.get("huber_delta", 0.0))
            huber_delta = hd_fixed if hd_fixed > 0 else 1.5 * mad
            if stats is not None:
                stats["valid"] = int(m.sum())
                stats["inliers"] = int(n_keep)
                stats["resid_med"] = float(r_k.abs().median())
            w = torch.clamp(huber_delta / r_k.abs().clamp(min=1e-6), max=1.0)
            J = torch.cat([torch.cross(Pp_k, n_k, dim=-1), n_k], dim=-1)  # (K,6)
            Jw = J * w[:, None]
            A = Jw.T @ J
            b = Jw.T @ r_k
            try:
                dx = -torch.linalg.solve(A + 1e-6 * eye6, b)
            except Exception:
                break
            if torch.norm(dx[:3]) > max_rot or torch.norm(dx[3:]) > max_trans:
                break  # reject an implausible jump; keep current T_pc
            T_pc = _se3_exp(dx) @ T_pc
            if torch.norm(dx[:3]) < 3e-4 and torch.norm(dx[3:]) < 1e-4:
                break

    return T_pc


def compute_coarse_pose_init(
    config,
    viewpoint,
    prev_cam,
    prevprev_cam,
    prev_depth,
    curr_dynamic_mask=None,
    prev_dynamic_mask=None,
    frame_idx=None,
):
    """Return (R, T) world->camera for the coarse init, or None to fall back.

    prev_cam / prevprev_cam: Camera objects (poses persist through clean()).
    prev_depth: previous frame gt depth tensor (H,W) on cuda, or None.
    curr_dynamic_mask / prev_dynamic_mask: (H,W) bool person masks for masked_icp
        (current and previous frame); ignored by const_vel/icp modes.
    """
    cfg = get_coarse_pose_config(config)
    mode = str(cfg.get("mode", "const_vel"))
    device = viewpoint.T.device

    Tcw_prev = getWorld2View2(prev_cam.R, prev_cam.T).to(device)
    if prevprev_cam is not None:
        Tcw_pp = getWorld2View2(prevprev_cam.R, prevprev_cam.T).to(device)
        V = Tcw_prev @ torch.linalg.inv(Tcw_pp)
        Tcw_pred = V @ Tcw_prev
    else:
        Tcw_pred = Tcw_prev  # no velocity yet -> copy previous pose

    def _const_vel():
        return Tcw_pred[:3, :3].contiguous(), Tcw_pred[:3, 3].contiguous()

    if mode == "const_vel" or prev_depth is None:
        return _const_vel()

    # ICP modes. masked_icp additionally masks the person on both endpoints.
    mask_curr = mask_prev = None
    if mode == "masked_icp":
        require_masks = bool(cfg.get("require_masks", True))
        if curr_dynamic_mask is None or prev_dynamic_mask is None:
            if require_masks:
                if frame_idx is not None:
                    Log(f"masked_icp f{frame_idx}: masks missing -> const_vel")
                return _const_vel()
        else:
            mask_curr = curr_dynamic_mask.to(device).bool()
            if mask_curr.dim() == 3:
                mask_curr = mask_curr.squeeze(0)
            mask_prev = prev_dynamic_mask.to(device).bool()
            if mask_prev.dim() == 3:
                mask_prev = mask_prev.squeeze(0)

    depth_curr = torch.from_numpy(viewpoint.depth).to(
        device=device, dtype=torch.float32
    )
    depth_prev = prev_depth.to(device=device, dtype=torch.float32)
    if depth_curr.dim() == 3:
        depth_curr = depth_curr.squeeze(0)
    if depth_prev.dim() == 3:
        depth_prev = depth_prev.squeeze(0)

    T_pc_seed = Tcw_prev @ torch.linalg.inv(Tcw_pred)  # curr-cam -> prev-cam seed
    stats = {}
    T_pc = _robust_projective_icp(
        depth_curr,
        depth_prev,
        float(viewpoint.fx),
        float(viewpoint.fy),
        float(viewpoint.cx),
        float(viewpoint.cy),
        T_pc_seed.clone(),
        cfg,
        mask_curr=mask_curr,
        mask_prev=mask_prev,
        stats=stats,
    )

    # Total-delta guard (masked_icp): reject an ICP result that drifted too far from
    # the const_vel seed -- a symptom of locking onto the mover -- and fall back.
    reason = "accept"
    if mode == "masked_icp":
        max_total_rot = float(cfg.get("max_total_rot_deg", 12.0)) * torch.pi / 180.0
        max_total_trans = float(cfg.get("max_total_trans", 0.20))
        dT = torch.linalg.inv(T_pc_seed) @ T_pc
        cos_ang = ((torch.trace(dT[:3, :3]) - 1.0) * 0.5).clamp(-1.0, 1.0)
        rot_ang = float(torch.arccos(cos_ang))
        trans_norm = float(torch.norm(dT[:3, 3]))
        finite = torch.isfinite(T_pc).all()
        if (not finite) or rot_ang > max_total_rot or trans_norm > max_total_trans:
            reason = (
                f"reject(dR={rot_ang * 180.0 / torch.pi:.1f}deg "
                f"dt={trans_norm * 100.0:.1f}cm finite={bool(finite)})"
            )
            T_pc = T_pc_seed  # fall back to const_vel
        if frame_idx is not None:
            if reason != "accept":
                Log(f"masked_icp f{frame_idx}: {reason} -> const_vel")
            elif frame_idx % 50 == 0:
                Log(
                    f"masked_icp f{frame_idx}: accept src={stats.get('source_pts', '?')} "
                    f"inl={stats.get('inliers', '?')} "
                    f"resid={stats.get('resid_med', 0.0) * 100.0:.2f}cm "
                    f"dt={trans_norm * 100.0:.1f}cm"
                )

    Tcw_curr = torch.linalg.inv(T_pc) @ Tcw_prev
    return Tcw_curr[:3, :3].contiguous(), Tcw_curr[:3, 3].contiguous()
