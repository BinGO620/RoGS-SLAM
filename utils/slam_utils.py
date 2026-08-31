import torch

from utils.mapping_weight import (
    dynamic_weight_map,
    mapping_scale_match_floor,
    mapping_soft_floor,
    scale_match_factor,
)
from utils.reliable_tracking import (
    build_reliable_tracking_terms,
    reliable_tracking_enabled,
)
from utils.reliability import compute_pixel_reliability, reliability_loss_enabled
from utils.tri_reliability import (
    compute_tri_reliability,
    tri_reliability_policy_enabled,
)


def image_gradient(image):
    # Compute image gradient using Scharr Filter
    c = image.shape[0]
    conv_y = torch.tensor(
        [[3, 0, -3], [10, 0, -10], [3, 0, -3]], dtype=torch.float32, device="cuda"
    )
    conv_x = torch.tensor(
        [[3, 10, 3], [0, 0, 0], [-3, -10, -3]], dtype=torch.float32, device="cuda"
    )
    normalizer = 1.0 / torch.abs(conv_y).sum()
    p_img = torch.nn.functional.pad(image, (1, 1, 1, 1), mode="reflect")[None]
    img_grad_v = normalizer * torch.nn.functional.conv2d(
        p_img, conv_x.view(1, 1, 3, 3).repeat(c, 1, 1, 1), groups=c
    )
    img_grad_h = normalizer * torch.nn.functional.conv2d(
        p_img, conv_y.view(1, 1, 3, 3).repeat(c, 1, 1, 1), groups=c
    )
    return img_grad_v[0], img_grad_h[0]


def image_gradient_mask(image, eps=0.01):
    # Compute image gradient mask
    c = image.shape[0]
    conv_y = torch.ones((1, 1, 3, 3), dtype=torch.float32, device="cuda")
    conv_x = torch.ones((1, 1, 3, 3), dtype=torch.float32, device="cuda")
    p_img = torch.nn.functional.pad(image, (1, 1, 1, 1), mode="reflect")[None]
    p_img = torch.abs(p_img) > eps
    img_grad_v = torch.nn.functional.conv2d(
        p_img.float(), conv_x.repeat(c, 1, 1, 1), groups=c
    )
    img_grad_h = torch.nn.functional.conv2d(
        p_img.float(), conv_y.repeat(c, 1, 1, 1), groups=c
    )

    return img_grad_v[0] == torch.sum(conv_x), img_grad_h[0] == torch.sum(conv_y)


def depth_reg(depth, gt_image, huber_eps=0.1, mask=None):
    mask_v, mask_h = image_gradient_mask(depth)
    gray_grad_v, gray_grad_h = image_gradient(gt_image.mean(dim=0, keepdim=True))
    depth_grad_v, depth_grad_h = image_gradient(depth)
    gray_grad_v, gray_grad_h = gray_grad_v[mask_v], gray_grad_h[mask_h]
    depth_grad_v, depth_grad_h = depth_grad_v[mask_v], depth_grad_h[mask_h]

    w_h = torch.exp(-10 * gray_grad_h**2)
    w_v = torch.exp(-10 * gray_grad_v**2)
    err = (w_h * torch.abs(depth_grad_h)).mean() + (
        w_v * torch.abs(depth_grad_v)
    ).mean()
    return err


def get_loss_tracking(
    config,
    image,
    depth,
    opacity,
    viewpoint,
    initialization=False,
    tracking_dynamic_mask=None,
    tracking_dynamic_soft=None,
    tracking_view_weight=None,
):
    image_ab = (torch.exp(viewpoint.exposure_a)) * image + viewpoint.exposure_b
    if config["Training"]["monocular"]:
        return get_loss_tracking_rgb(config, image_ab, depth, opacity, viewpoint)
    return get_loss_tracking_rgbd(
        config,
        image_ab,
        depth,
        opacity,
        viewpoint,
        tracking_dynamic_mask=tracking_dynamic_mask,
        tracking_dynamic_soft=tracking_dynamic_soft,
        tracking_view_weight=tracking_view_weight,
    )


def get_loss_tracking_rgb(config, image, depth, opacity, viewpoint):
    gt_image = viewpoint.original_image.cuda()
    _, h, w = gt_image.shape
    mask_shape = (1, h, w)
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]
    rgb_pixel_mask = (gt_image.sum(dim=0) > rgb_boundary_threshold).view(*mask_shape)
    rgb_pixel_mask = rgb_pixel_mask * viewpoint.grad_mask
    l1 = opacity * torch.abs(image * rgb_pixel_mask - gt_image * rgb_pixel_mask)
    return l1.mean()


def get_loss_tracking_rgbd(
    config,
    image,
    depth,
    opacity,
    viewpoint,
    initialization=False,
    tracking_dynamic_mask=None,
    tracking_dynamic_soft=None,
    tracking_view_weight=None,
):
    if reliable_tracking_enabled(config):
        return get_loss_tracking_rgbd_reliable(
            config,
            image,
            depth,
            opacity,
            viewpoint,
            tracking_dynamic_mask,
            tracking_dynamic_soft,
            tracking_view_weight,
        )

    if tracking_dynamic_soft is not None:
        # H-e: if configured, composition the hard dynamic mask INTO the soft path so the
        # moving person is truly excluded from tracking (not just down-weighted). The soft
        # strength then only applies to non-hard-masked pixels. Without this, when both
        # soft (reliability/static) and hard (semantic) are present the hard mask is
        # bypassed entirely and the large low-texture person interior still drags pose.
        he = config.get("SemanticMask", {}).get(
            "hard_tracking_mask",
            config.get("HardTrackingMask", {}).get("enabled", False),
        )
        if he and tracking_dynamic_mask is not None:
            return get_loss_tracking_rgbd_hardsoft(
                config,
                image,
                depth,
                opacity,
                viewpoint,
                tracking_dynamic_mask,
                tracking_dynamic_soft,
            )
        return get_loss_tracking_rgbd_soft(
            config, image, depth, opacity, viewpoint, tracking_dynamic_soft
        )

    if tracking_dynamic_mask is not None:
        return get_loss_tracking_rgbd_flow_mask(
            config, image, depth, opacity, viewpoint, tracking_dynamic_mask
        )

    if reliability_loss_enabled(config, "tracking"):
        weighted_loss = get_loss_tracking_rgbd_reliability(
            config, image, depth, opacity, viewpoint
        )
        if weighted_loss is not None:
            return weighted_loss

    if tri_reliability_policy_enabled(
        config, "tracking", "apply_tracking_dynamic_mask"
    ):
        masked_loss = get_loss_tracking_rgbd_tri_mask(
            config, image, depth, opacity, viewpoint
        )
        if masked_loss is not None:
            return masked_loss

    if config.get("RobustTracking", {}).get("enabled", False):
        robust_loss = get_loss_tracking_rgbd_robust(
            config, image, depth, opacity, viewpoint
        )
        if robust_loss is not None:
            return robust_loss

    alpha = config["Training"]["alpha"] if "alpha" in config["Training"] else 0.95

    gt_depth = torch.from_numpy(viewpoint.depth).to(
        dtype=torch.float32, device=image.device
    )[None]
    depth_pixel_mask = (gt_depth > 0.01).view(*depth.shape)
    opacity_mask = (opacity > 0.95).view(*depth.shape)

    l1_rgb = get_loss_tracking_rgb(config, image, depth, opacity, viewpoint)
    depth_mask = depth_pixel_mask * opacity_mask
    l1_depth = torch.abs(depth * depth_mask - gt_depth * depth_mask)
    return alpha * l1_rgb + (1 - alpha) * l1_depth.mean()


def get_loss_tracking_rgbd_reliable(
    config,
    image,
    depth,
    opacity,
    viewpoint,
    dynamic_mask=None,
    dynamic_soft=None,
    view_weight=None,
):
    """RGD-inspired reliability weighting with fixed-support normalization."""
    alpha = config["Training"].get("alpha", 0.95)
    terms = build_reliable_tracking_terms(
        config,
        image,
        depth,
        opacity,
        viewpoint,
        dynamic_mask=dynamic_mask,
        dynamic_soft=dynamic_soft,
        view_weight=view_weight,
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
        terms["rgb_residual"],
        rgb_weight,
        terms["rgb_mask"],
        terms["rgb_valid_count"],
    )
    depth_loss = _weighted_by_valid_count(
        terms["depth_residual"],
        depth_weight,
        terms["depth_mask"],
        terms["depth_valid_count"],
    )
    return alpha * rgb_loss + (1 - alpha) * depth_loss


def _weighted_by_valid_count(error, weight, mask, valid_count):
    mask = mask.to(device=error.device, dtype=error.dtype)
    weight = weight.to(device=error.device, dtype=error.dtype)
    denominator = torch.as_tensor(
        valid_count, device=error.device, dtype=error.dtype
    ).clamp_min(1.0)
    return (error * weight * mask).sum() / denominator


def get_loss_tracking_rgbd_reliability(config, image, depth, opacity, viewpoint):
    alpha = config["Training"]["alpha"] if "alpha" in config["Training"] else 0.95
    reliability_config = config.get("Reliability", {})
    min_mean_reliability = float(reliability_config.get("min_mean_reliability", 0.20))
    loss_eps = float(reliability_config.get("loss_eps", 1e-6))
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]

    metrics = compute_pixel_reliability(
        config,
        image,
        depth,
        opacity,
        viewpoint,
        use_exposure=False,
    )
    if metrics["mean_reliability"] < min_mean_reliability:
        return None

    reliability = metrics["reliability"].detach()
    gt_image = viewpoint.original_image.to(device=image.device, dtype=image.dtype)
    gt_depth = torch.from_numpy(viewpoint.depth).to(
        dtype=torch.float32, device=image.device
    )[None]

    rgb_pixel_mask = gt_image.sum(dim=0, keepdim=True) > rgb_boundary_threshold
    rgb_pixel_mask = rgb_pixel_mask & viewpoint.grad_mask.to(
        device=image.device, dtype=torch.bool
    )
    rgb_error = opacity * torch.abs(image - gt_image).mean(dim=0, keepdim=True)
    l1_rgb = _weighted_mean(rgb_error, reliability, rgb_pixel_mask, loss_eps)

    depth_pixel_mask = (gt_depth > 0.01).view(*depth.shape)
    opacity_mask = (opacity.detach() > 0.95).view(*depth.shape)
    depth_mask = depth_pixel_mask & opacity_mask
    l1_depth = _weighted_mean(
        torch.abs(depth - gt_depth), reliability, depth_mask, loss_eps
    )

    return alpha * l1_rgb + (1 - alpha) * l1_depth


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
    # This isolates whether the boundary band (or adjacent static-side pixels) is the useful
    # constraint, vs full hard-exclusion under-constraining.
    erode_px = int(sc.get("track_erode_px", 0))
    dm = dynamic_mask.to(device=image.device, dtype=torch.bool)
    if erode_px > 0:
        # erode = shrink the dynamic region by erode_px on each side (via max-pool on the
        # inverted mask). We erode the dynamic mask with a box: a pixel stays dynamic only
        # if it AND its erode_px-neighborhood are all dynamic. Implemented by min-pooling
        # the dynamic mask (min over a box = interior stays 1, boundary 7px band becomes 0).
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

def get_loss_tracking_rgbd_tri_mask(config, image, depth, opacity, viewpoint):
    """P1a / TR-T (H1): hard-exclude high dynamic-evidence pixels from the RGB-D
    tracking loss. `image` is already exposure-corrected (image_ab), so
    compute_tri_reliability is called with use_exposure=False, matching the
    Reliability hook. Returns None to fall back to vanilla tracking when the
    masked ratio exceeds max_tracking_mask_ratio (an all-dynamic frame would
    otherwise starve pose optimization).
    """
    alpha = config["Training"]["alpha"] if "alpha" in config["Training"] else 0.95
    tri_config = config.get("TriReliability", {})
    dynamic_threshold = float(tri_config.get("tracking_dynamic_threshold", 0.45))
    max_mask_ratio = float(tri_config.get("max_tracking_mask_ratio", 0.60))
    loss_eps = float(tri_config.get("tracking_loss_eps", 1e-6))
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]

    metrics = compute_tri_reliability(
        config, image, depth, opacity, viewpoint, use_exposure=False
    )
    valid_mask = metrics["valid_mask"]
    dynamic_mask = (metrics["dynamic_evidence"] > dynamic_threshold) & valid_mask
    valid_pixels = max(int(valid_mask.count_nonzero().item()), 1)
    mask_ratio = dynamic_mask.count_nonzero().item() / valid_pixels
    if mask_ratio > max_mask_ratio:
        return None

    # keep only confidently-static pixels (dynamic_evidence is already boundary-
    # and unmapped-protected inside compute_tri_reliability)
    static_mask = valid_mask & (~dynamic_mask)

    gt_image = viewpoint.original_image.to(device=image.device, dtype=image.dtype)
    gt_depth = torch.from_numpy(viewpoint.depth).to(
        dtype=torch.float32, device=image.device
    )[None]

    rgb_pixel_mask = gt_image.sum(dim=0, keepdim=True) > rgb_boundary_threshold
    rgb_pixel_mask = rgb_pixel_mask & viewpoint.grad_mask.to(
        device=image.device, dtype=torch.bool
    )
    rgb_error = opacity * torch.abs(image - gt_image).mean(dim=0, keepdim=True)
    l1_rgb = _weighted_mean(
        rgb_error, torch.ones_like(rgb_error), static_mask & rgb_pixel_mask, loss_eps
    )

    depth_pixel_mask = (gt_depth > 0.01).view(*depth.shape)
    opacity_mask = (opacity.detach() > 0.95).view(*depth.shape)
    depth_mask = static_mask & depth_pixel_mask & opacity_mask
    l1_depth = _weighted_mean(
        torch.abs(depth - gt_depth), torch.ones_like(depth), depth_mask, loss_eps
    )

    return alpha * l1_rgb + (1 - alpha) * l1_depth


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


def get_loss_tracking_rgbd_robust(config, image, depth, opacity, viewpoint):
    """P2a robust-IRLS tracking: robustly reweight the RGB-D tracking residual
    with a Huber/Cauchy/GM kernel. `image` is already exposure-corrected."""
    alpha = config["Training"]["alpha"] if "alpha" in config["Training"] else 0.95
    rc = config.get("RobustTracking", {})
    kernel = rc.get("kernel", "huber")
    rgb_delta = float(rc.get("rgb_delta", 0.10))
    depth_delta = float(rc.get("depth_delta", 0.10))
    loss_eps = float(rc.get("loss_eps", 1e-6))
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]

    gt_image = viewpoint.original_image.to(device=image.device, dtype=image.dtype)
    gt_depth = torch.from_numpy(viewpoint.depth).to(
        dtype=torch.float32, device=image.device
    )[None]

    rgb_pixel_mask = gt_image.sum(dim=0, keepdim=True) > rgb_boundary_threshold
    rgb_pixel_mask = rgb_pixel_mask & viewpoint.grad_mask.to(
        device=image.device, dtype=torch.bool
    )
    rgb_residual = torch.abs(image - gt_image).mean(dim=0, keepdim=True)
    rgb_error = opacity * rgb_residual
    w_rgb = _robust_irls_weight(rgb_residual, rgb_delta, kernel)
    l1_rgb = _weighted_mean(rgb_error, w_rgb, rgb_pixel_mask, loss_eps)

    depth_pixel_mask = (gt_depth > 0.01).view(*depth.shape)
    opacity_mask = (opacity.detach() > 0.95).view(*depth.shape)
    depth_mask = depth_pixel_mask & opacity_mask
    depth_residual = torch.abs(depth - gt_depth)
    w_depth = _robust_irls_weight(depth_residual, depth_delta, kernel)
    l1_depth = _weighted_mean(depth_residual, w_depth, depth_mask, loss_eps)

    return alpha * l1_rgb + (1 - alpha) * l1_depth


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


def _weighted_mean(error, reliability, valid_mask, eps):
    valid_mask = valid_mask.to(device=error.device, dtype=torch.bool)
    weights = reliability.to(device=error.device, dtype=error.dtype) * valid_mask.to(
        dtype=error.dtype
    )
    denom = torch.clamp(weights.sum(), min=eps)
    return (error * weights).sum() / denom


def get_loss_mapping(
    config, image, depth, viewpoint, opacity, initialization=False, dynamic_mask=None,
    ema_weight_map=None, ema_c_mass=None,
):
    if initialization:
        image_ab = image
    else:
        image_ab = (torch.exp(viewpoint.exposure_a)) * image + viewpoint.exposure_b
    if config["Training"]["monocular"]:
        return get_loss_mapping_rgb(config, image_ab, depth, viewpoint)
    return get_loss_mapping_rgbd(
        config,
        image_ab,
        depth,
        viewpoint,
        dynamic_mask=dynamic_mask,
        soft_floor=mapping_soft_floor(config),
        scale_match_floor=mapping_scale_match_floor(config),
        ema_weight_map=ema_weight_map,
        ema_c_mass=ema_c_mass,
    )


def get_loss_mapping_rgb(config, image, depth, viewpoint):
    gt_image = viewpoint.original_image.cuda()
    _, h, w = gt_image.shape
    mask_shape = (1, h, w)
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]

    rgb_pixel_mask = (gt_image.sum(dim=0) > rgb_boundary_threshold).view(*mask_shape)
    l1_rgb = torch.abs(image * rgb_pixel_mask - gt_image * rgb_pixel_mask)

    return l1_rgb.mean()


def _ema_pixel_weight(image, gt_image, depth, gt_depth, rgb_valid, depth_valid, ema):
    """Step C per-pixel lagged-residual EMA weight map.

    Builds (a) a per-pixel signal-noise weight `w_raw` from the *previous* frame's
    lagged residual statistics, and (b) a constant scale factor c that equalises the
    total weight mass between this EMA map and the hard-mask baseline so that any
    Phase-1 ATE difference is attributable to the *shape* of the weight map, not to
    the photometric term's magnitude against the fixed isotropic regulariser.

    State is held externally (``MappingEMARecorder``) and updated by the backend
    with a stop-gradient + 1-step lag, so it never forms a cycle with the current
    iteration's optimiser.
    """
    beta = ema["beta"]
    lam = ema["lam"]
    sigma_min = ema["sigma_min"]
    loss_eps = 1e-6

    rgb_err = torch.abs(image - gt_image).mean(dim=0, keepdim=True)
    depth_err = torch.abs(depth - gt_depth)

    mu_rgb = ema["mu_rgb"]
    mu_d = ema["mu_depth"]
    q_rgb = ema["q_rgb"]
    q_d = ema["q_depth"]

    if ema["first"]:
        ema["mu_rgb"] = rgb_err.detach().clone()
        ema["mu_depth"] = depth_err.detach().clone()
        ema["q_rgb"] = (rgb_err.detach() ** 2).clone()
        ema["q_depth"] = (depth_err.detach() ** 2).clone()
        ema["first"] = False
    else:
        ema["mu_rgb"] = beta * mu_rgb + (1 - beta) * rgb_err.detach()
        ema["mu_depth"] = beta * mu_d + (1 - beta) * depth_err.detach()
        ema["q_rgb"] = beta * q_rgb + (1 - beta) * (rgb_err.detach() ** 2)
        ema["q_depth"] = beta * q_d + (1 - beta) * (depth_err.detach() ** 2)

    mu = ema["mu_rgb"]  # (1,H,W)
    sigma2 = torch.clamp(ema["q_rgb"] - ema["mu_rgb"] ** 2, min=sigma_min ** 2)
    bias2 = ema["mu_rgb"] ** 2

    w_map = torch.zeros_like(rgb_valid, dtype=image.dtype)
    w_map[rgb_valid] = 1.0 / (sigma2[rgb_valid] + lam * bias2[rgb_valid] + loss_eps)
    w_map[~rgb_valid] = 0.0

    c_mass = rgb_valid.to(dtype=image.dtype).sum().item()
    w_mass = w_map[rgb_valid].sum().item()
    c_rgb = (w_mass / c_mass) if c_mass > 0 else 1.0
    c_depth = c_rgb

    return w_map, c_rgb, c_depth


def get_loss_mapping_rgbd(
    config,
    image,
    depth,
    viewpoint,
    initialization=False,
    dynamic_mask=None,
    soft_floor=None,
    scale_match_floor=None,
    ema_weight_map=None,
    ema_c_mass=None,
):
    alpha = config["Training"]["alpha"] if "alpha" in config["Training"] else 0.95
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]

    gt_image = viewpoint.original_image.cuda()

    gt_depth = torch.from_numpy(viewpoint.depth).to(
        dtype=torch.float32, device=image.device
    )[None]
    rgb_pixel_mask = (gt_image.sum(dim=0) > rgb_boundary_threshold).view(*depth.shape)
    depth_pixel_mask = (gt_depth > 0.01).view(*depth.shape)

    c_rgb = 1.0
    c_depth = 1.0

    # Exclude dynamic (e.g. person) pixels so moving objects are not baked into the
    # map. Without this the mapping loss + windowed pose BA reward fitting the mover.
    if dynamic_mask is not None:
        static = (~dynamic_mask.to(device=depth.device, dtype=torch.bool)).view(
            *depth.shape
        )
        if soft_floor is not None:
            # exp39 A2 treatment: the binary endpoint parameterised into a continuous
            # one. floor=0.0 reproduces the hard branch below bit-for-bit (both reduce
            # to mask * |x - gt|); floor=1.0 reproduces no mask at all.
            w = dynamic_weight_map(static, soft_floor, image.dtype)
            l1_rgb = torch.abs(image - gt_image) * (
                rgb_pixel_mask.to(dtype=image.dtype) * w
            )
            l1_depth = torch.abs(depth - gt_depth) * (
                depth_pixel_mask.to(dtype=depth.dtype) * w.to(dtype=depth.dtype)
            )
            return alpha * l1_rgb.mean() + (1 - alpha) * l1_depth.mean()
        if ema_weight_map is not None:
            # exp39 Step C: per-pixel lagged-residual EMA weight map.
            #
            # 2026-08-23 audit: the original form below multiplied the loss by
            # ``ema_c_mass`` = mean(w), so the photometric term scaled as w_bar**2 --
            # a 5.7e4x (E) / 2.9e5x (E-scrambled) inflation against the hard arm that
            # effectively deleted the fixed isotropic regulariser and confounded every
            # E-vs-H ATE reading. `mapping_ema_mass_match` fixes the total weight mass
            # to the hard arm's, so the arms differ only in how a fixed amount of
            # weight is distributed. `mapping_ema_zero_dynamic` removes admission while
            # keeping this code path, which isolates admission from the branch itself.
            from utils.mapping_weight import (
                apply_ema_dynamic_cap,
                apply_ema_mass_match,
                ema_dynamic_cap,
                ema_mass_matched,
                ema_zero_dynamic,
            )

            w = ema_weight_map.to(dtype=image.dtype)
            zero_dyn = ema_zero_dynamic(config)
            if zero_dyn:
                w = w * static.to(dtype=image.dtype)
            else:
                # Admission-dose scan: set mean_w(dyn)/mean_w(stat) to the configured
                # share. Applied BEFORE mass matching, which is ratio-invariant, so the
                # dose and the total weight mass stay independent.
                cap = ema_dynamic_cap(config)
                if cap is not None:
                    w = apply_ema_dynamic_cap(
                        w, rgb_pixel_mask, ~static, cap
                    )

            multiplier = ema_c_mass
            if ema_mass_matched(config):
                # The hard arm's effective pixel count is its weight mass: every
                # valid&static pixel carries weight exactly 1.
                hard_support = rgb_pixel_mask & static
                target_mass = hard_support.to(dtype=image.dtype).sum()
                contributing = rgb_pixel_mask & (static if zero_dyn else rgb_pixel_mask)
                w = apply_ema_mass_match(w, contributing, target_mass)
                multiplier = 1.0

            l1_rgb = torch.abs(image - gt_image) * (
                rgb_pixel_mask.to(dtype=image.dtype) * w
            )
            l1_depth = torch.abs(depth - gt_depth) * (
                depth_pixel_mask.to(dtype=depth.dtype) * w.to(dtype=depth.dtype)
            )
            return multiplier * (alpha * l1_rgb.mean() + (1 - alpha) * l1_depth.mean())
        if scale_match_floor is not None:
            # exp39 control: keep the hard mask, match only the weight mass the soft
            # arm would have carried, so a Phase-1 difference cannot be explained by
            # the photometric term's scale against the fixed isotropic regulariser.
            c_rgb = scale_match_factor(rgb_pixel_mask, static, scale_match_floor)
            c_depth = scale_match_factor(depth_pixel_mask, static, scale_match_floor)
        rgb_pixel_mask = rgb_pixel_mask & static
        depth_pixel_mask = depth_pixel_mask & static

    l1_rgb = torch.abs(image * rgb_pixel_mask - gt_image * rgb_pixel_mask)
    l1_depth = torch.abs(depth * depth_pixel_mask - gt_depth * depth_pixel_mask)

    return alpha * c_rgb * l1_rgb.mean() + (1 - alpha) * c_depth * l1_depth.mean()


def get_median_depth(depth, opacity=None, mask=None, return_std=False):
    depth = depth.detach().clone()
    opacity = opacity.detach()
    valid = depth > 0
    if opacity is not None:
        valid = torch.logical_and(valid, opacity > 0.95)
    if mask is not None:
        valid = torch.logical_and(valid, mask)
    valid_depth = depth[valid]
    if return_std:
        return valid_depth.median(), valid_depth.std(), valid
    return valid_depth.median()
