import json
import os
import time

import cv2
import numpy as np
import torch


def get_reliability_config(config):
    return config.get("Reliability", {})


def reliability_observation_enabled(config, scope):
    reliability_config = get_reliability_config(config)
    if not reliability_config.get("enabled", False):
        return False

    mode = reliability_config.get("mode", "off")
    if mode == "off":
        return False
    if mode == "observe":
        return scope in {"tracking", "mapping"}
    if mode == "both":
        return scope in {"tracking", "mapping"}
    return mode == scope


def reliability_loss_enabled(config, scope):
    reliability_config = get_reliability_config(config)
    if not reliability_config.get("enabled", False):
        return False

    mode = reliability_config.get("mode", "off")
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


def _valid_rgb_mask(gt_image, rgb_boundary_threshold):
    return (
        gt_image.sum(dim=0, keepdim=True) > rgb_boundary_threshold
    ) & torch.isfinite(gt_image).all(dim=0, keepdim=True)


def compute_pixel_reliability(
    config,
    image,
    depth,
    opacity,
    viewpoint,
    use_exposure=True,
):
    reliability_config = get_reliability_config(config)
    tau_depth = float(reliability_config.get("tau_depth", 0.05))
    tau_rgb = float(reliability_config.get("tau_rgb", 0.10))
    r_min = float(reliability_config.get("r_min", 0.05))
    hard_threshold = float(reliability_config.get("hard_threshold", 0.50))
    reliability_type = reliability_config.get("type", "soft")
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
        valid_rgb = _valid_rgb_mask(gt_image, rgb_boundary_threshold)
        rgb_residual = torch.abs(render_image - gt_image).mean(dim=0, keepdim=True)
        r_rgb = torch.exp(-rgb_residual / max(tau_rgb, 1e-6))

        gt_depth = _to_depth_tensor(
            viewpoint.depth, render_image.device, render_image.dtype
        )
        valid_depth = None
        depth_residual = torch.zeros_like(rgb_residual)
        r_depth = torch.ones_like(rgb_residual)
        if gt_depth is not None and depth is not None:
            render_depth = depth.detach().to(
                device=render_image.device, dtype=render_image.dtype
            )
            if render_depth.ndim == 2:
                render_depth = render_depth[None]
            valid_depth = (gt_depth > 0.01) & torch.isfinite(gt_depth)
            valid_depth = valid_depth & torch.isfinite(render_depth)
            depth_residual = torch.abs(render_depth - gt_depth)
            r_depth = torch.where(
                valid_depth,
                torch.exp(-depth_residual / max(tau_depth, 1e-6)),
                torch.ones_like(depth_residual),
            )

        r_soft = torch.clamp(r_rgb * r_depth, min=r_min, max=1.0)
        if reliability_type == "hard":
            reliability = torch.where(
                r_soft >= hard_threshold,
                torch.ones_like(r_soft),
                torch.full_like(r_soft, r_min),
            )
        else:
            reliability = r_soft

        valid_mask = valid_rgb
        valid_pixels = int(valid_mask.count_nonzero().item())
        if valid_pixels > 0:
            valid_reliability = reliability[valid_mask]
            low_reliability_ratio = (
                (valid_reliability < hard_threshold).float().mean().item()
            )
            mean_reliability = valid_reliability.mean().item()
            reliability_sum = valid_reliability.sum().item()
            low_pixels = int(
                (valid_reliability < hard_threshold).count_nonzero().item()
            )
        else:
            mean_reliability = 0.0
            low_reliability_ratio = 0.0
            reliability_sum = 0.0
            low_pixels = 0

        opacity_map = None
        if opacity is not None:
            opacity_map = opacity.detach()

        return {
            "reliability": reliability.detach(),
            "rgb_residual": rgb_residual.detach(),
            "depth_residual": depth_residual.detach(),
            "opacity": opacity_map.detach() if opacity_map is not None else None,
            "valid_mask": valid_mask.detach(),
            "valid_depth": valid_depth.detach() if valid_depth is not None else None,
            "mean_reliability": mean_reliability,
            "low_reliability_ratio": low_reliability_ratio,
            "reliability_sum": reliability_sum,
            "valid_pixels": valid_pixels,
            "low_pixels": low_pixels,
        }


def _normalize_map(tensor, scale=None, valid_mask=None):
    data = tensor.detach().float().squeeze().cpu().numpy()
    if valid_mask is not None:
        valid = valid_mask.detach().bool().squeeze().cpu().numpy()
    else:
        valid = np.isfinite(data)

    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    if scale is None:
        valid_values = data[valid]
        scale = float(np.percentile(valid_values, 95)) if valid_values.size else 1.0
    scale = max(float(scale), 1e-6)
    normalized = np.clip(data / scale, 0.0, 1.0)
    normalized[~valid] = 0.0
    return (normalized * 255.0).astype(np.uint8)


def _save_colormap(path, tensor, scale=None, valid_mask=None, inverse=False):
    gray = _normalize_map(tensor, scale=scale, valid_mask=valid_mask)
    if inverse:
        gray = 255 - gray
    color_map = (
        cv2.COLORMAP_TURBO if hasattr(cv2, "COLORMAP_TURBO") else cv2.COLORMAP_JET
    )
    color = cv2.applyColorMap(gray, color_map)
    cv2.imwrite(path, color)


def save_reliability_visualization(config, save_dir, scope, label, metrics):
    reliability_config = get_reliability_config(config)
    if not reliability_config.get("save_visualization", True):
        return 0
    if save_dir is None:
        return 0

    output_dir = os.path.join(save_dir, "reliability", scope)
    os.makedirs(output_dir, exist_ok=True)
    tau_depth = float(reliability_config.get("tau_depth", 0.05))
    tau_rgb = float(reliability_config.get("tau_rgb", 0.10))
    valid_mask = metrics["valid_mask"]

    _save_colormap(
        os.path.join(output_dir, f"{label}_reliability.png"),
        metrics["reliability"],
        scale=1.0,
        valid_mask=valid_mask,
    )
    _save_colormap(
        os.path.join(output_dir, f"{label}_rgb_residual.png"),
        metrics["rgb_residual"],
        scale=tau_rgb,
        valid_mask=valid_mask,
    )
    _save_colormap(
        os.path.join(output_dir, f"{label}_depth_residual.png"),
        metrics["depth_residual"],
        scale=tau_depth,
        valid_mask=metrics.get("valid_depth"),
    )
    saved = 3
    if (
        reliability_config.get("save_opacity", True)
        and metrics.get("opacity") is not None
    ):
        _save_colormap(
            os.path.join(output_dir, f"{label}_opacity.png"),
            metrics["opacity"],
            scale=1.0,
        )
        saved += 1
    return saved


class ReliabilityRecorder:
    def __init__(self, config, scope):
        self.config = config
        self.scope = scope
        self.calls = 0
        self.time_ms = 0.0
        self.valid_pixels = 0
        self.reliability_sum = 0.0
        self.low_pixels = 0
        self.saved_visualizations = 0
        self._saved_labels = set()

    def enabled(self):
        return reliability_observation_enabled(self.config, self.scope)

    def observe(
        self,
        image,
        depth,
        opacity,
        viewpoint,
        label,
        use_exposure=True,
        save_visualization=True,
    ):
        if not self.enabled():
            return None

        start = time.perf_counter()
        metrics = compute_pixel_reliability(
            self.config,
            image,
            depth,
            opacity,
            viewpoint,
            use_exposure=use_exposure,
        )
        reliability_config = get_reliability_config(self.config)
        save_interval = int(reliability_config.get("save_interval", 20))
        save_this = save_visualization and label not in self._saved_labels
        frame_id = _label_frame_id(label)
        if save_interval > 0 and frame_id is not None:
            save_this = save_this and frame_id % save_interval == 0
        if save_this:
            self.saved_visualizations += save_reliability_visualization(
                self.config,
                self.config["Results"].get("save_dir"),
                self.scope,
                label,
                metrics,
            )
            self._saved_labels.add(label)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self.calls += 1
        self.time_ms += elapsed_ms
        self.valid_pixels += metrics["valid_pixels"]
        self.reliability_sum += metrics["reliability_sum"]
        self.low_pixels += metrics["low_pixels"]

        return metrics

    def summary(self):
        mean_reliability = (
            self.reliability_sum / self.valid_pixels if self.valid_pixels > 0 else None
        )
        low_reliability_ratio = (
            self.low_pixels / self.valid_pixels if self.valid_pixels > 0 else None
        )
        return {
            "calls": self.calls,
            "time_ms": self.time_ms,
            "valid_pixels": self.valid_pixels,
            "mean_reliability": mean_reliability,
            "low_reliability_ratio": low_reliability_ratio,
            "saved_visualizations": self.saved_visualizations,
        }

    def flush_summary(self):
        save_dir = self.config["Results"].get("save_dir")
        if save_dir is None:
            return
        write_reliability_summary(save_dir, self.scope, self.summary())


def _label_frame_id(label):
    parts = label.rsplit("_", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def write_reliability_summary(save_dir, scope, scope_summary):
    reliability_dir = os.path.join(save_dir, "reliability")
    os.makedirs(reliability_dir, exist_ok=True)
    summary_path = os.path.join(reliability_dir, "summary.json")
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
        "reliability_calls": total_calls,
        "reliability_time_ms": total_time_ms,
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4)


def load_reliability_summary(save_dir):
    if save_dir is None:
        return {}
    summary_path = os.path.join(save_dir, "reliability", "summary.json")
    if not os.path.exists(summary_path):
        return {}
    with open(summary_path, "r", encoding="utf-8") as f:
        return json.load(f)


def reliability_raw_fields(save_dir, scope):
    summary = load_reliability_summary(save_dir)
    scope_data = summary.get(scope, {})
    return {
        "method_raw_mean_reliability": _round_or_missing(
            scope_data.get("mean_reliability")
        ),
        "method_raw_low_reliability_ratio": _round_or_missing(
            scope_data.get("low_reliability_ratio")
        ),
    }


def reliability_efficiency_fields(save_dir):
    summary = load_reliability_summary(save_dir)
    total_data = summary.get("total", {})
    return {
        "reliability_time_ms": _round_or_missing(total_data.get("reliability_time_ms")),
        "reliability_calls": total_data.get("reliability_calls", "N/A"),
    }


def _round_or_missing(value):
    if value is None:
        return "N/A"
    return round(float(value), 4)
