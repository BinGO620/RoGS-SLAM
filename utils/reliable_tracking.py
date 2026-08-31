import csv
import json
import math
import os
import time

import torch

from gaussian_splatting.utils.graphics_utils import getWorld2View2


def reliable_tracking_enabled(config):
    return bool(config.get("ReliableTracking", {}).get("enabled", False))


def _median_inlier_mask(residual, valid_mask, scale):
    valid_values = residual.detach()[valid_mask]
    if valid_values.numel() == 0:
        return valid_mask
    median = valid_values.median().clamp_min(1e-6)
    return valid_mask & (residual.detach() <= float(scale) * median)


def _minimum_opacity_support(inlier_mask, valid_mask, opacity, minimum_ratio):
    valid_count = int(valid_mask.count_nonzero().item())
    if valid_count == 0:
        return valid_mask, False
    minimum_count = max(1, math.ceil(float(minimum_ratio) * valid_count))
    if int(inlier_mask.count_nonzero().item()) >= minimum_count:
        return inlier_mask, False

    valid_indices = valid_mask.flatten().nonzero(as_tuple=False).flatten()
    valid_opacity = opacity.detach().flatten()[valid_indices]
    selected = torch.topk(
        valid_opacity,
        k=min(minimum_count, valid_opacity.numel()),
        largest=True,
        sorted=False,
    ).indices
    fallback = torch.zeros_like(valid_mask, dtype=torch.bool).flatten()
    fallback[valid_indices[selected]] = True
    return fallback.view_as(valid_mask), True


def _safe_ratio(mask, valid_count):
    denominator = max(int(valid_count), 1)
    return float(mask.count_nonzero().item() / denominator)


def _record_tracking_diagnostics(viewpoint, diagnostics, elapsed_ms):
    stats = getattr(viewpoint, "_reliable_tracking_stats", None)
    if stats is None:
        stats = {
            "calls": 0,
            "time_ms": 0.0,
            "rgb_fallback_calls": 0,
            "depth_fallback_calls": 0,
            "opacity_support_ratio_sum": 0.0,
            "rgb_support_ratio_sum": 0.0,
            "depth_support_ratio_sum": 0.0,
            "opacity_support_ratio_min": 1.0,
            "rgb_support_ratio_min": 1.0,
            "depth_support_ratio_min": 1.0,
        }
        viewpoint._reliable_tracking_stats = stats
    stats["calls"] += 1
    stats["time_ms"] += elapsed_ms
    stats["rgb_fallback_calls"] += int(diagnostics["rgb_fallback"])
    stats["depth_fallback_calls"] += int(diagnostics["depth_fallback"])
    for name in (
        "opacity_support_ratio",
        "rgb_support_ratio",
        "depth_support_ratio",
    ):
        stats[f"{name}_sum"] += diagnostics[name]
        stats[f"{name}_min"] = min(stats[f"{name}_min"], diagnostics[name])


def build_reliable_tracking_terms(
    config,
    image,
    depth,
    opacity,
    viewpoint,
    dynamic_mask=None,
    dynamic_soft=None,
    view_weight=None,
):
    """Build RGD-inspired tracking masks and weights without copying RGD code."""
    started_at = time.perf_counter()
    cfg = config.get("ReliableTracking", {})
    rgb_threshold = config["Training"]["rgb_boundary_threshold"]
    opacity_min = float(cfg.get("opacity_min", 0.95))
    min_support_ratio = float(cfg.get("min_support_ratio", 0.10))

    gt_image = viewpoint.original_image.to(device=image.device, dtype=image.dtype)
    gt_depth = torch.from_numpy(viewpoint.depth).to(
        device=image.device, dtype=depth.dtype
    )[None]
    grad_mask = viewpoint.grad_mask.to(device=image.device, dtype=torch.bool)

    valid_rgb = (gt_image.sum(dim=0, keepdim=True) > rgb_threshold) & grad_mask
    valid_depth = (gt_depth > 0.01).view(*depth.shape)
    opacity_support = (opacity.detach() >= opacity_min).view(*depth.shape)

    if dynamic_mask is not None:
        static = ~dynamic_mask.to(device=image.device, dtype=torch.bool)
        valid_rgb &= static
        valid_depth &= static

    rgb_residual = torch.abs(image - gt_image).mean(dim=0, keepdim=True)
    depth_residual = torch.abs(depth - gt_depth)
    rgb_mask = _median_inlier_mask(
        rgb_residual,
        valid_rgb & opacity_support,
        cfg.get("rgb_median_scale", 8.0),
    )
    depth_mask = _median_inlier_mask(
        depth_residual,
        valid_depth & opacity_support,
        cfg.get("depth_median_scale", 10.0),
    )

    # Keep a bounded nonzero gradient on a young map. Unsupported pixels are never
    # restored wholesale: only the highest-opacity valid pixels reach the support floor.
    rgb_mask, rgb_fallback = _minimum_opacity_support(
        rgb_mask, valid_rgb, opacity, min_support_ratio
    )
    depth_mask, depth_fallback = _minimum_opacity_support(
        depth_mask, valid_depth, opacity, min_support_ratio
    )

    if view_weight is None:
        view_weight = torch.ones_like(depth)
    else:
        view_weight = view_weight.to(device=image.device, dtype=image.dtype)

    static_soft = torch.ones_like(depth)
    if dynamic_soft is not None:
        strength = float(cfg.get("soft_strength", 1.0))
        floor = float(cfg.get("soft_floor", 0.10))
        dynamic_soft = dynamic_soft.to(device=image.device, dtype=image.dtype)
        static_soft = torch.clamp(1.0 - strength * dynamic_soft, floor, 1.0)

    rgb_weight = opacity.detach() * view_weight * static_soft
    depth_opacity_weight = opacity.detach().clamp(0.0, 1.0)
    if not depth_fallback:
        depth_opacity_weight = torch.ones_like(depth_opacity_weight)
    depth_weight = depth_opacity_weight * view_weight * static_soft
    depth_valid_count = int(valid_depth.count_nonzero().item())
    rgb_valid_count = int(valid_rgb.count_nonzero().item())
    opacity_valid = valid_depth & opacity_support
    diagnostics = {
        "rgb_fallback": rgb_fallback,
        "depth_fallback": depth_fallback,
        "opacity_support_ratio": _safe_ratio(opacity_valid, depth_valid_count),
        "rgb_support_ratio": _safe_ratio(rgb_mask, rgb_valid_count),
        "depth_support_ratio": _safe_ratio(depth_mask, depth_valid_count),
    }
    _record_tracking_diagnostics(
        viewpoint,
        diagnostics,
        (time.perf_counter() - started_at) * 1000.0,
    )
    return {
        "gt_image": gt_image,
        "gt_depth": gt_depth,
        "rgb_residual": rgb_residual,
        "depth_residual": depth_residual,
        "rgb_mask": rgb_mask,
        "depth_mask": depth_mask,
        "rgb_weight": rgb_weight,
        "depth_weight": depth_weight,
        "rgb_valid_count": rgb_valid_count,
        "depth_valid_count": depth_valid_count,
        **diagnostics,
    }


def write_reliable_tracking_summary(save_dir, cameras):
    if not save_dir:
        return None
    rows = []
    for frame_id, camera in sorted(cameras.items()):
        stats = getattr(camera, "_reliable_tracking_stats", None)
        if not stats or not stats["calls"]:
            continue
        calls = stats["calls"]
        rows.append(
            {
                "frame_id": int(frame_id),
                "calls": calls,
                "time_ms": stats["time_ms"],
                "rgb_fallback_calls": stats["rgb_fallback_calls"],
                "depth_fallback_calls": stats["depth_fallback_calls"],
                "opacity_support_ratio_mean": (
                    stats["opacity_support_ratio_sum"] / calls
                ),
                "rgb_support_ratio_mean": stats["rgb_support_ratio_sum"] / calls,
                "depth_support_ratio_mean": stats["depth_support_ratio_sum"] / calls,
                "opacity_support_ratio_min": stats["opacity_support_ratio_min"],
                "rgb_support_ratio_min": stats["rgb_support_ratio_min"],
                "depth_support_ratio_min": stats["depth_support_ratio_min"],
            }
        )

    calls = sum(row["calls"] for row in rows)
    summary = {
        "calls": calls,
        "time_ms": sum(row["time_ms"] for row in rows),
        "frames": len(rows),
        "rgb_fallback_calls": sum(row["rgb_fallback_calls"] for row in rows),
        "depth_fallback_calls": sum(row["depth_fallback_calls"] for row in rows),
    }
    for name in (
        "opacity_support_ratio",
        "rgb_support_ratio",
        "depth_support_ratio",
    ):
        summary[f"{name}_mean"] = (
            sum(row[f"{name}_mean"] * row["calls"] for row in rows) / calls
            if calls
            else None
        )
        summary[f"{name}_min"] = (
            min(row[f"{name}_min"] for row in rows) if rows else None
        )
    summary["rgb_fallback_ratio"] = (
        summary["rgb_fallback_calls"] / calls if calls else None
    )
    summary["depth_fallback_ratio"] = (
        summary["depth_fallback_calls"] / calls if calls else None
    )

    output_dir = os.path.join(save_dir, "reliable_tracking")
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "summary.json"), "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2)
    if rows:
        with open(
            os.path.join(output_dir, "support_by_frame.csv"),
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return summary


def reliable_tracking_efficiency_fields(save_dir):
    path = os.path.join(save_dir, "reliable_tracking", "summary.json")
    if not os.path.exists(path):
        return {
            "reliable_tracking_time_ms": "N/A",
            "reliable_tracking_calls": "N/A",
            "reliable_tracking_depth_fallback_ratio": "N/A",
        }
    with open(path, "r", encoding="utf-8") as file:
        summary = json.load(file)
    fallback_ratio = summary.get("depth_fallback_ratio")
    return {
        "reliable_tracking_time_ms": round(float(summary.get("time_ms", 0.0)), 4),
        "reliable_tracking_calls": int(summary.get("calls", 0)),
        "reliable_tracking_depth_fallback_ratio": round(float(fallback_ratio), 4)
        if fallback_ratio is not None
        else "N/A",
    }


def projected_border_weight(config, gaussians, viewpoint, last_keyframe_id):
    """Downweight image margins not covered by the last keyframe's Gaussians."""
    cfg = config.get("ReliableTracking", {})
    height = viewpoint.image_height
    width = viewpoint.image_width
    device = viewpoint.R.device
    result = torch.ones((1, height, width), device=device, dtype=torch.float32)
    if gaussians is None or gaussians.get_xyz.numel() == 0:
        return result

    ids = gaussians.unique_kfIDs
    if ids.numel() != gaussians.get_xyz.shape[0]:
        return result
    selected = ids == int(last_keyframe_id)
    if selected.count_nonzero().item() < 32:
        return result

    xyz = gaussians.get_xyz[selected.to(gaussians.get_xyz.device)].detach()
    max_points = int(cfg.get("border_projection_max_points", 20000))
    if xyz.shape[0] > max_points:
        step = max(xyz.shape[0] // max_points, 1)
        xyz = xyz[::step][:max_points]

    world_to_camera = getWorld2View2(viewpoint.R, viewpoint.T)
    camera_xyz = xyz @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
    z = camera_xyz[:, 2]
    valid = torch.isfinite(camera_xyz).all(dim=1) & (z > 1e-4)
    if valid.count_nonzero().item() < 32:
        return result
    camera_xyz = camera_xyz[valid]
    z = camera_xyz[:, 2]
    u = viewpoint.fx * camera_xyz[:, 0] / z + viewpoint.cx
    v = viewpoint.fy * camera_xyz[:, 1] / z + viewpoint.cy

    min_x = int(torch.floor(u.min()).clamp(0, width).item())
    max_x = int(torch.ceil(u.max()).clamp(0, width - 1).item())
    min_y = int(torch.floor(v.min()).clamp(0, height).item())
    max_y = int(torch.ceil(v.max()).clamp(0, height - 1).item())

    min_weight = float(cfg.get("border_weight_min", 0.4))
    max_weight = float(cfg.get("border_weight_max", 0.8))
    max_x_border = int(cfg.get("border_max_width", 60))
    max_y_border = int(cfg.get("border_max_height", 40))

    def ramp(length, reverse=False):
        values = torch.linspace(min_weight, max_weight, length, device=device)
        return values.flip(0) if reverse else values

    left = min(min_x, max_x_border)
    right = min(max(width - 1 - max_x, 0), max_x_border)
    top = min(min_y, max_y_border)
    bottom = min(max(height - 1 - max_y, 0), max_y_border)
    if left > 0:
        result[:, :, :left] = torch.minimum(
            result[:, :, :left], ramp(left)[None, None, :]
        )
    if right > 0:
        result[:, :, -right:] = torch.minimum(
            result[:, :, -right:], ramp(right, reverse=True)[None, None, :]
        )
    if top > 0:
        result[:, :top, :] = torch.minimum(result[:, :top, :], ramp(top)[:, None][None])
    if bottom > 0:
        result[:, -bottom:, :] = torch.minimum(
            result[:, -bottom:, :], ramp(bottom, reverse=True)[:, None][None]
        )
    return result
