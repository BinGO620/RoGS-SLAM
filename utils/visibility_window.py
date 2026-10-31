import numpy as np


# Lightweight engagement diagnostic (screening only): confirms the open-set complement term
# actually fires (current frame carries reliability_s + non-zero complement) instead of
# silently degrading to pure co-visibility. Printed to the run log; grep "VW-DIAG".
_VW_DIAG = {"calls": 0, "cur_rel_s": 0, "cand": 0, "comp_nz": 0, "comp_sum": 0.0}


def visibility_window_enabled(config):
    return bool(config.get("VisibilityWindow", {}).get("enabled", False))


def _pose_cw(camera):
    pose = np.eye(4, dtype=np.float64)
    pose[:3, :3] = camera.R.detach().cpu().numpy()
    pose[:3, 3] = camera.T.detach().cpu().numpy()
    return pose


def _dynamic_numpy(camera, config=None):
    mask = getattr(camera, "dynamic_mask", None)
    if mask is not None:  # closed-set: semantic person mask (unchanged path)
        if hasattr(mask, "detach"):
            mask = mask.detach().cpu().numpy()
        return np.squeeze(np.asarray(mask)).astype(bool)
    # Open-set fallback: training-free dynamic region from the reliability signal
    # s=(1-e_flow)(1-v*g) (low s = dynamic). Fixed threshold on the RAW per-pixel s
    # (NOT the Cauchy w aggregation) -> avoids the majority-domination knee (PROBE1-X).
    s = getattr(camera, "reliability_s", None)
    if s is None or config is None:
        return None  # graceful: complement -> 0, degrades to pure co-visibility
    tau = float(config.get("VisibilityWindow", {}).get("reliability_dynamic_tau", 0.5))
    return np.squeeze(np.asarray(s)) < tau


def _covisibility(current_visibility, previous_visibility):
    if current_visibility.shape != previous_visibility.shape:
        return 0.0
    intersection = (
        current_visibility.bool() & previous_visibility.bool()
    ).count_nonzero()
    denominator = min(
        current_visibility.count_nonzero(), previous_visibility.count_nonzero()
    )
    if denominator.item() == 0:
        return 0.0
    return float((intersection / denominator).item())


def _dynamic_complementarity(config, current, previous):
    dynamic = _dynamic_numpy(current, config)
    if dynamic is None:
        return 0.0
    y, x = np.nonzero(dynamic)
    if len(x) == 0:
        return 0.0

    maximum = int(config.get("VisibilityWindow", {}).get("sample_rays", 2048))
    if len(x) > maximum:
        selected = np.linspace(0, len(x) - 1, maximum, dtype=np.int64)
        x = x[selected]
        y = y[selected]
    # The current dynamic pixels do not reveal the hidden static surface depth.
    # Probe fixed-depth points along those rays, matching RGD-SLAM's view-selection
    # mechanism, instead of back-projecting the moving object's measured depth.
    ray_depth = float(
        config.get("VisibilityWindow", {}).get("complement_ray_depth_m", 2.0)
    )
    z = np.full(len(x), ray_depth, dtype=np.float32)
    points = np.stack(
        [
            (x - current.cx) * z / current.fx,
            (y - current.cy) * z / current.fy,
            z,
            np.ones_like(z),
        ],
        axis=1,
    )
    world = (np.linalg.inv(_pose_cw(current)) @ points.T).T
    camera = (_pose_cw(previous) @ world.T).T[:, :3]
    camera_z = camera[:, 2]
    safe_z = np.where(np.abs(camera_z) > 1e-8, camera_z, 1.0)
    u = np.rint(previous.fx * camera[:, 0] / safe_z + previous.cx).astype(int)
    v = np.rint(previous.fy * camera[:, 1] / safe_z + previous.cy).astype(int)
    edge = int(config.get("VisibilityWindow", {}).get("image_edge_px", 20))
    inside = (
        np.isfinite(camera).all(axis=1)
        & (camera_z > 0.01)
        & (u >= edge)
        & (u < previous.image_width - edge)
        & (v >= edge)
        & (v < previous.image_height - edge)
    )
    if not inside.any():
        return 0.0
    previous_dynamic = _dynamic_numpy(previous, config)
    if previous_dynamic is None:
        useful = inside
    else:
        useful = inside.copy()
        inside_ids = np.nonzero(inside)[0]
        useful[inside_ids] &= ~previous_dynamic[v[inside_ids], u[inside_ids]]
    return float(useful.sum() / len(useful))


def update_visibility_window(
    config,
    cur_frame_idx,
    current_visibility,
    occ_aware_visibility,
    window,
    cameras,
):
    """Keep keyframes useful for both static overlap and dynamic-region completion."""
    updated = [cur_frame_idx] + list(window)
    maximum = int(config["Training"]["window_size"])
    if len(updated) <= maximum:
        return updated, None

    protected = int(config.get("VisibilityWindow", {}).get("protect_newest", 2))
    candidates = updated[protected:]
    if not candidates:
        return updated[:maximum], updated[-1]

    current = cameras[cur_frame_idx]
    cov_weight = float(config.get("VisibilityWindow", {}).get("covis_weight", 0.5))
    complement_weight = 1.0 - cov_weight
    _VW_DIAG["calls"] += 1
    _VW_DIAG["cur_rel_s"] += int(getattr(current, "reliability_s", None) is not None)
    scored = []
    for keyframe_id in candidates:
        previous_visibility = occ_aware_visibility.get(keyframe_id)
        covis = (
            _covisibility(current_visibility, previous_visibility)
            if previous_visibility is not None
            else 0.0
        )
        complement = _dynamic_complementarity(config, current, cameras[keyframe_id])
        _VW_DIAG["cand"] += 1
        _VW_DIAG["comp_nz"] += int(complement > 0.0)
        _VW_DIAG["comp_sum"] += complement
        scored.append(
            (cov_weight * covis + complement_weight * complement, keyframe_id)
        )
    if _VW_DIAG["calls"] % 20 == 0:
        d = _VW_DIAG
        print(
            f"VW-DIAG calls={d['calls']} cur_reliability_s={d['cur_rel_s']}/{d['calls']} "
            f"cand={d['cand']} complement>0={d['comp_nz']}/{d['cand']} "
            f"mean_complement={d['comp_sum'] / max(d['cand'], 1):.4f}",
            flush=True,
        )

    _, removed = min(scored, key=lambda item: (item[0], item[1]))
    updated.remove(removed)
    return updated, removed
