"""P2b: semantic-free dynamic-pixel mask from optical-flow residual.

measured optical flow (current -> previous, classical Farneback) MINUS the
ego-motion-predicted rigid flow (from current depth + relative camera pose);
pixels whose measured flow disagrees with the rigid-flow prediction are moving
independently of the camera -> dynamic. This signal is pose-robust: it reads
motion *inconsistency*, not absolute rendering residual, so it does not collapse
when the pose is still drifting (unlike the T1 / TR-T residual masks).

Pose convention matches utils/tri_reliability.update_gaussian_static_memory:
`world_view_transform` maps world->view by row-vector right-multiply
(P_view = P_world @ WVT), and view points project as
u = fx * x/z + cx, v = fy * y/z + cy.
"""

import cv2
import numpy as np
import torch


def get_flow_tracking_config(config):
    return config.get("FlowResidualTracking", {})


def flow_tracking_enabled(config):
    return bool(get_flow_tracking_config(config).get("enabled", False))


def _to_gray_uint8(image):
    img = image.detach().clamp(0.0, 1.0).cpu().numpy()
    if img.ndim == 3:  # (3, H, W) -> (H, W, 3)
        img = img.transpose(1, 2, 0)
    img = (img * 255.0).astype(np.uint8)
    if img.ndim == 3 and img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    return np.squeeze(img)


def compute_flow_residual_mask(
    config, prev_image, cur_image, cur_depth, prev_w2v, cur_w2v, fx, fy, cx, cy
):
    """Return (dynamic_mask (1,H,W) bool tensor, ratio) or (None, ratio).

    None signals the caller to fall back to vanilla tracking (either no valid
    pixels, or the masked ratio exceeds max_mask_ratio -> degenerate frame).
    """
    fc = get_flow_tracking_config(config)
    thr = float(fc.get("residual_flow_threshold_px", 2.0))
    max_ratio = float(fc.get("max_mask_ratio", 0.90))
    min_depth = float(fc.get("min_depth", 0.01))

    with torch.no_grad():
        gray_cur = _to_gray_uint8(cur_image)
        gray_prev = _to_gray_uint8(prev_image)
        H, W = gray_cur.shape
        # measured flow: current -> previous, (H, W, 2) as (du, dv)
        flow = cv2.calcOpticalFlowFarneback(
            gray_cur, gray_prev, None, 0.5, 3, 15, 3, 5, 1.2, 0
        )

        device = cur_depth.device
        flow_t = torch.from_numpy(flow).to(device=device, dtype=torch.float32)
        d = cur_depth.to(device=device, dtype=torch.float32).reshape(H, W)
        vv, uu = torch.meshgrid(
            torch.arange(H, device=device, dtype=torch.float32),
            torch.arange(W, device=device, dtype=torch.float32),
            indexing="ij",
        )
        # back-project current pixels to current-view 3D (row-vector homogeneous)
        x = (uu - cx) / fx * d
        y = (vv - cy) / fy * d
        z = d
        p_cur = torch.stack([x, y, z, torch.ones_like(z)], dim=-1).reshape(-1, 4)

        prev_w2v = prev_w2v.to(device=device, dtype=torch.float32)
        cur_w2v = cur_w2v.to(device=device, dtype=torch.float32)
        # cur-view -> world -> prev-view  (row-vector convention)
        transform = torch.linalg.inv(cur_w2v) @ prev_w2v
        p_prev = p_cur @ transform
        zp = p_prev[:, 2].clamp(min=1e-6)
        u_prev = fx * (p_prev[:, 0] / zp) + cx
        v_prev = fy * (p_prev[:, 1] / zp) + cy
        # predicted rigid flow current -> previous
        pred_du = (u_prev - uu.reshape(-1)).reshape(H, W)
        pred_dv = (v_prev - vv.reshape(-1)).reshape(H, W)

        res_u = flow_t[..., 0] - pred_du
        res_v = flow_t[..., 1] - pred_dv
        res_mag = torch.sqrt(res_u * res_u + res_v * res_v)

        valid = (d > min_depth) & torch.isfinite(res_mag)
        dynamic = (res_mag > thr) & valid
        valid_count = int(valid.count_nonzero().item())
        if valid_count == 0:
            return None, 0.0
        ratio = dynamic.count_nonzero().item() / valid_count
        if ratio > max_ratio:
            return None, ratio
        return dynamic.reshape(1, H, W), ratio
