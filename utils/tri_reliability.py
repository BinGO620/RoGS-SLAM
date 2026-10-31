import json
import os
import time

import cv2
import numpy as np
import torch


def get_tri_reliability_config(config):
    return config.get("TriReliability", {})


def tri_reliability_enabled(config, scope):
    tri_config = get_tri_reliability_config(config)
    if not tri_config.get("enabled", False):
        return False
    mode = tri_config.get("mode", "off")
    if mode == "off":
        return False
    if mode == "observe":
        return scope in {"tracking", "mapping"}
    if mode == "both":
        return scope in {"tracking", "mapping"}
    return mode == scope


def tri_reliability_policy_enabled(config, scope, policy_name):
    tri_config = get_tri_reliability_config(config)
    if not tri_config.get("enabled", False):
        return False
    if not tri_config.get(policy_name, False):
        return False
    mode = tri_config.get("mode", "off")
    if mode == "both":
        return scope in {"tracking", "mapping"}
    return mode == scope


def _to_depth_tensor(depth, device, dtype):
    if depth is None:
        return None
    if torch.is_tensor(depth):
        depth_tensor = depth.to(device=device, dtype=dtype)
    else:
        depth_tensor = torch.from_numpy(depth).to(device=device, dtype=dtype)
    if depth_tensor.ndim == 2:
        depth_tensor = depth_tensor[None]
    return depth_tensor


def _gradient_magnitude(tensor):
    data = tensor.detach()
    dx = torch.zeros_like(data)
    dy = torch.zeros_like(data)
    dx[..., :, 1:] = torch.abs(data[..., :, 1:] - data[..., :, :-1])
    dy[..., 1:, :] = torch.abs(data[..., 1:, :] - data[..., :-1, :])
    return torch.sqrt(dx.square() + dy.square())


def compute_tri_reliability(
    config,
    image,
    depth,
    opacity,
    viewpoint,
    use_exposure=True,
):
    tri_config = get_tri_reliability_config(config)
    tau_depth = float(tri_config.get("tau_depth", 0.10))
    tau_rgb = float(tri_config.get("tau_rgb", 0.20))
    min_static_weight = float(tri_config.get("min_static_weight", 0.50))
    unmapped_opacity_threshold = float(
        tri_config.get("unmapped_opacity_threshold", 0.35)
    )
    opacity_dynamic_threshold = float(tri_config.get("opacity_dynamic_threshold", 0.60))
    boundary_rgb_threshold = float(tri_config.get("boundary_rgb_threshold", 0.08))
    boundary_depth_threshold = float(tri_config.get("boundary_depth_threshold", 0.08))
    boundary_suppression = float(tri_config.get("boundary_suppression", 0.70))
    boundary_gate_power = float(tri_config.get("boundary_gate_power", 1.0))
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]

    with torch.no_grad():
        render_image = image.detach()
        if use_exposure and getattr(viewpoint, "exposure_a", None) is not None:
            render_image = torch.exp(viewpoint.exposure_a.detach()) * render_image
            render_image = render_image + viewpoint.exposure_b.detach()
        render_image = torch.clamp(render_image, 0.0, 1.0)

        gt_image = viewpoint.original_image.to(
            device=render_image.device, dtype=render_image.dtype
        )
        valid_rgb = (gt_image.sum(dim=0, keepdim=True) > rgb_boundary_threshold) & (
            torch.isfinite(gt_image).all(dim=0, keepdim=True)
        )

        rgb_residual = torch.abs(render_image - gt_image).mean(dim=0, keepdim=True)
        rgb_dynamic = 1.0 - torch.exp(-rgb_residual / max(tau_rgb, 1e-6))

        gt_depth = _to_depth_tensor(
            viewpoint.depth, render_image.device, render_image.dtype
        )
        depth_residual = torch.zeros_like(rgb_residual)
        valid_depth = torch.zeros_like(valid_rgb, dtype=torch.bool)
        depth_dynamic = torch.zeros_like(rgb_residual)
        if gt_depth is not None and depth is not None:
            render_depth = depth.detach().to(
                device=render_image.device, dtype=render_image.dtype
            )
            if render_depth.ndim == 2:
                render_depth = render_depth[None]
            valid_depth = (gt_depth > 0.01) & torch.isfinite(gt_depth)
            valid_depth = valid_depth & torch.isfinite(render_depth)
            depth_residual = torch.abs(render_depth - gt_depth)
            depth_dynamic = torch.where(
                valid_depth,
                1.0 - torch.exp(-depth_residual / max(tau_depth, 1e-6)),
                torch.zeros_like(depth_residual),
            )

        if opacity is None:
            opacity_map = torch.ones_like(rgb_residual)
        else:
            opacity_map = opacity.detach().to(
                device=render_image.device, dtype=render_image.dtype
            )
            if opacity_map.ndim == 2:
                opacity_map = opacity_map[None]

        unmapped_evidence = torch.where(
            valid_rgb & (opacity_map < unmapped_opacity_threshold),
            torch.ones_like(rgb_residual),
            torch.zeros_like(rgb_residual),
        )

        gray = gt_image.mean(dim=0, keepdim=True)
        rgb_boundary = torch.clamp(
            _gradient_magnitude(gray) / max(boundary_rgb_threshold, 1e-6),
            0.0,
            1.0,
        )
        if gt_depth is not None:
            depth_boundary = torch.clamp(
                _gradient_magnitude(gt_depth) / max(boundary_depth_threshold, 1e-6),
                0.0,
                1.0,
            )
        else:
            depth_boundary = torch.zeros_like(rgb_boundary)
        boundary_evidence = torch.maximum(rgb_boundary, depth_boundary)
        boundary_evidence = torch.where(
            valid_rgb, boundary_evidence, torch.zeros_like(boundary_evidence)
        )

        raw_dynamic = torch.maximum(rgb_dynamic, depth_dynamic)
        opacity_supported = opacity_map >= opacity_dynamic_threshold
        boundary_gate = torch.clamp(
            1.0 - boundary_suppression * boundary_evidence, 0.0, 1.0
        )
        dynamic_evidence = raw_dynamic * torch.pow(
            boundary_gate, max(boundary_gate_power, 1e-6)
        )
        dynamic_evidence = torch.where(
            valid_rgb & opacity_supported & (unmapped_evidence < 0.5),
            torch.clamp(dynamic_evidence, 0.0, 1.0),
            torch.zeros_like(dynamic_evidence),
        )
        static_weight = torch.clamp(1.0 - dynamic_evidence, min_static_weight, 1.0)

        valid_pixels = int(valid_rgb.count_nonzero().item())
        if valid_pixels > 0:
            dynamic_sum = dynamic_evidence[valid_rgb].sum().item()
            unmapped_sum = unmapped_evidence[valid_rgb].sum().item()
            boundary_sum = boundary_evidence[valid_rgb].sum().item()
            static_sum = static_weight[valid_rgb].sum().item()
        else:
            dynamic_sum = 0.0
            unmapped_sum = 0.0
            boundary_sum = 0.0
            static_sum = 0.0

        return {
            "dynamic_evidence": dynamic_evidence.detach(),
            "unmapped_evidence": unmapped_evidence.detach(),
            "boundary_evidence": boundary_evidence.detach(),
            "static_weight": static_weight.detach(),
            "rgb_residual": rgb_residual.detach(),
            "depth_residual": depth_residual.detach(),
            "opacity": opacity_map.detach(),
            "valid_mask": valid_rgb.detach(),
            "valid_depth": valid_depth.detach(),
            "valid_pixels": valid_pixels,
            "dynamic_sum": dynamic_sum,
            "unmapped_sum": unmapped_sum,
            "boundary_sum": boundary_sum,
            "static_sum": static_sum,
            "mean_dynamic_evidence": dynamic_sum / valid_pixels
            if valid_pixels
            else 0.0,
            "mean_unmapped_evidence": unmapped_sum / valid_pixels
            if valid_pixels
            else 0.0,
            "mean_boundary_evidence": boundary_sum / valid_pixels
            if valid_pixels
            else 0.0,
            "mean_static_weight": static_sum / valid_pixels if valid_pixels else 0.0,
        }


def update_gaussian_static_memory(
    config,
    gaussians,
    viewpoint,
    metrics,
    visibility_filter=None,
):
    if gaussians is None or gaussians.get_xyz.shape[0] == 0:
        return {}
    tri_config = get_tri_reliability_config(config)
    if not tri_config.get("update_gaussian_memory", True):
        return {}

    beta = float(tri_config.get("memory_beta", 0.90))
    default_static_prob = float(tri_config.get("initial_static_prob", 0.70))
    gaussians.ensure_static_memory_state(default_static_prob)

    xyz = gaussians.get_xyz.detach()
    device = xyz.device
    ones = torch.ones((xyz.shape[0], 1), dtype=xyz.dtype, device=device)
    xyz_h = torch.cat((xyz, ones), dim=1)
    cam_points = xyz_h @ viewpoint.world_view_transform.to(device=device)
    z = cam_points[:, 2]
    valid = z > 0.01
    u = viewpoint.fx * (cam_points[:, 0] / torch.clamp(z, min=1e-6)) + viewpoint.cx
    v = viewpoint.fy * (cam_points[:, 1] / torch.clamp(z, min=1e-6)) + viewpoint.cy
    h = int(viewpoint.image_height)
    w = int(viewpoint.image_width)
    valid = valid & (u >= 0) & (u < w) & (v >= 0) & (v < h)
    if visibility_filter is not None:
        valid = valid & visibility_filter.detach().to(device=device, dtype=torch.bool)
    if not valid.any():
        return {"updated_gaussians": 0}

    uu = torch.clamp(u[valid].round().long(), 0, w - 1)
    vv = torch.clamp(v[valid].round().long(), 0, h - 1)
    idx = torch.nonzero(valid, as_tuple=False).squeeze(1)

    dynamic = metrics["dynamic_evidence"].to(device=device)[0, vv, uu].view(-1, 1)
    unmapped = metrics["unmapped_evidence"].to(device=device)[0, vv, uu].view(-1, 1)
    static_observation = torch.clamp(1.0 - dynamic, 0.0, 1.0)

    gaussians.static_prob[idx] = (
        beta * gaussians.static_prob[idx] + (1.0 - beta) * static_observation
    )
    gaussians.unmapped_score[idx] = (
        beta * gaussians.unmapped_score[idx] + (1.0 - beta) * unmapped
    )
    gaussians.static_obs_count[idx] += 1.0

    return {
        "updated_gaussians": int(idx.shape[0]),
        "mean_static_prob": float(gaussians.static_prob.mean().item()),
        "low_static_ratio": float((gaussians.static_prob < 0.5).float().mean().item()),
        "mean_unmapped_score": float(gaussians.unmapped_score.mean().item()),
    }


def _normalize_map(tensor, scale=1.0, valid_mask=None):
    data = tensor.detach().float().squeeze().cpu().numpy()
    valid = (
        valid_mask.detach().bool().squeeze().cpu().numpy()
        if valid_mask is not None
        else np.isfinite(data)
    )
    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    scale = max(float(scale), 1e-6)
    normalized = np.clip(data / scale, 0.0, 1.0)
    normalized[~valid] = 0.0
    return (normalized * 255.0).astype(np.uint8)


def _save_colormap(path, tensor, scale=1.0, valid_mask=None):
    gray = _normalize_map(tensor, scale=scale, valid_mask=valid_mask)
    color_map = (
        cv2.COLORMAP_TURBO if hasattr(cv2, "COLORMAP_TURBO") else cv2.COLORMAP_JET
    )
    cv2.imwrite(path, cv2.applyColorMap(gray, color_map))


def save_tri_reliability_visualization(config, save_dir, scope, label, metrics):
    tri_config = get_tri_reliability_config(config)
    if not tri_config.get("save_visualization", True) or save_dir is None:
        return 0

    output_dir = os.path.join(save_dir, "tri_reliability", scope)
    os.makedirs(output_dir, exist_ok=True)
    valid_mask = metrics["valid_mask"]
    for key in (
        "dynamic_evidence",
        "unmapped_evidence",
        "boundary_evidence",
        "static_weight",
    ):
        _save_colormap(
            os.path.join(output_dir, f"{label}_{key}.png"),
            metrics[key],
            scale=1.0,
            valid_mask=valid_mask,
        )
    return 4


class TriReliabilityRecorder:
    def __init__(self, config, scope):
        self.config = config
        self.scope = scope
        self.calls = 0
        self.time_ms = 0.0
        self.valid_pixels = 0
        self.dynamic_sum = 0.0
        self.unmapped_sum = 0.0
        self.boundary_sum = 0.0
        self.static_sum = 0.0
        self.saved_visualizations = 0
        self.updated_gaussians = 0
        self.last_gaussian_summary = {}
        self._saved_labels = set()

    def enabled(self):
        return tri_reliability_enabled(self.config, self.scope)

    def observe(
        self,
        image,
        depth,
        opacity,
        viewpoint,
        label,
        gaussians=None,
        visibility_filter=None,
        use_exposure=True,
        save_visualization=True,
    ):
        if not self.enabled():
            return None

        start = time.perf_counter()
        metrics = compute_tri_reliability(
            self.config,
            image,
            depth,
            opacity,
            viewpoint,
            use_exposure=use_exposure,
        )

        tri_config = get_tri_reliability_config(self.config)
        save_interval = int(tri_config.get("save_interval", 20))
        save_this = save_visualization and label not in self._saved_labels
        frame_id = _label_frame_id(label)
        if save_interval > 0 and frame_id is not None:
            save_this = save_this and frame_id % save_interval == 0
        if save_this:
            self.saved_visualizations += save_tri_reliability_visualization(
                self.config,
                self.config["Results"].get("save_dir"),
                self.scope,
                label,
                metrics,
            )
            self._saved_labels.add(label)

        gaussian_summary = update_gaussian_static_memory(
            self.config,
            gaussians,
            viewpoint,
            metrics,
            visibility_filter=visibility_filter,
        )
        self.last_gaussian_summary = gaussian_summary or self.last_gaussian_summary
        self.updated_gaussians += int(gaussian_summary.get("updated_gaussians") or 0)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self.calls += 1
        self.time_ms += elapsed_ms
        self.valid_pixels += metrics["valid_pixels"]
        self.dynamic_sum += metrics["dynamic_sum"]
        self.unmapped_sum += metrics["unmapped_sum"]
        self.boundary_sum += metrics["boundary_sum"]
        self.static_sum += metrics["static_sum"]
        return metrics

    def summary(self):
        denom = self.valid_pixels if self.valid_pixels > 0 else None
        return {
            "calls": self.calls,
            "time_ms": self.time_ms,
            "valid_pixels": self.valid_pixels,
            "mean_dynamic_evidence": self.dynamic_sum / denom if denom else None,
            "mean_unmapped_evidence": self.unmapped_sum / denom if denom else None,
            "mean_boundary_evidence": self.boundary_sum / denom if denom else None,
            "mean_static_weight": self.static_sum / denom if denom else None,
            "saved_visualizations": self.saved_visualizations,
            "updated_gaussians": self.updated_gaussians,
            "gaussian_memory": self.last_gaussian_summary,
        }

    def flush_summary(self):
        save_dir = self.config["Results"].get("save_dir")
        if save_dir is None:
            return
        write_tri_reliability_summary(save_dir, self.scope, self.summary())


def _label_frame_id(label):
    parts = label.rsplit("_", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def write_tri_reliability_summary(save_dir, scope, scope_summary):
    tri_dir = os.path.join(save_dir, "tri_reliability")
    os.makedirs(tri_dir, exist_ok=True)
    summary_path = os.path.join(tri_dir, "summary.json")
    summary = {}
    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except json.JSONDecodeError:
            summary = {}

    summary[scope] = scope_summary
    total_calls = 0
    total_time_ms = 0.0
    for key in ("tracking", "mapping"):
        scope_data = summary.get(key, {})
        total_calls += int(scope_data.get("calls") or 0)
        total_time_ms += float(scope_data.get("time_ms") or 0.0)
    summary["total"] = {
        "tri_reliability_calls": total_calls,
        "tri_reliability_time_ms": total_time_ms,
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4)


def load_tri_reliability_summary(save_dir):
    if save_dir is None:
        return {}
    summary_path = os.path.join(save_dir, "tri_reliability", "summary.json")
    if not os.path.exists(summary_path):
        return {}
    with open(summary_path, "r", encoding="utf-8") as f:
        return json.load(f)


def tri_reliability_raw_fields(save_dir, scope):
    summary = load_tri_reliability_summary(save_dir)
    scope_data = summary.get(scope, {})
    gaussian_data = scope_data.get("gaussian_memory", {}) or {}
    return {
        "method_raw_tri_dynamic_evidence": _round_or_missing(
            scope_data.get("mean_dynamic_evidence")
        ),
        "method_raw_tri_unmapped_evidence": _round_or_missing(
            scope_data.get("mean_unmapped_evidence")
        ),
        "method_raw_tri_boundary_evidence": _round_or_missing(
            scope_data.get("mean_boundary_evidence")
        ),
        "method_raw_tri_static_weight": _round_or_missing(
            scope_data.get("mean_static_weight")
        ),
        "method_raw_gaussian_static_prob": _round_or_missing(
            gaussian_data.get("mean_static_prob")
        ),
        "method_raw_gaussian_low_static_ratio": _round_or_missing(
            gaussian_data.get("low_static_ratio")
        ),
    }


def tri_reliability_efficiency_fields(save_dir):
    summary = load_tri_reliability_summary(save_dir)
    total_data = summary.get("total", {})
    return {
        "tri_reliability_time_ms": _round_or_missing(
            total_data.get("tri_reliability_time_ms")
        ),
        "tri_reliability_calls": total_data.get("tri_reliability_calls", "N/A"),
    }


def _round_or_missing(value):
    if value is None:
        return "N/A"
    return round(float(value), 4)
