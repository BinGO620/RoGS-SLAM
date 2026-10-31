"""P3b: temporal per-Gaussian static_prob soft weighting for tracking.

The one thing robust-IRLS lacks is TIME: it reweights per-frame residual and
cannot remember a Gaussian that is *consistently* dynamic across frames. Here
each Gaussian carries a persistent `static_prob` (on GaussianModel, from the TR
line), EMA-updated from the per-frame rendering RESIDUAL (not semantics -- our
experiments showed semantics hurts dense 3DGS). It is rendered to a dense
per-pixel static-weight map (via the now-fixed `override_color` render path) and
fed into the existing soft tracking loss, so it composes with the robust kernel.

Evidence = residual (Gassidy-style), NOT semantic; soft weighting, NOT hard mask.
"""

import torch


def get_static_prob_config(config):
    return config.get("StaticProb", {})


def static_prob_enabled(config):
    return bool(get_static_prob_config(config).get("enabled", False))


def render_static_prob_map(config, gaussians, viewpoint, pipe, background=None):
    """Render per-Gaussian static_prob into a dense (1,H,W) per-pixel map in [0,1].
    Uncovered pixels -> 1 (static / full weight) via a ones background."""
    from gaussian_splatting.gaussian_renderer import render

    if gaussians is None or gaussians.get_xyz.shape[0] == 0:
        return None
    default = float(get_static_prob_config(config).get("initial_static_prob", 0.7))
    gaussians.ensure_static_memory_state(default)
    with torch.no_grad():
        sp = gaussians.static_prob.detach().clamp(0.0, 1.0)  # (N,1)
        override = sp.repeat(1, 3)  # (N,3) all channels = static_prob
        bg = torch.ones(3, device=sp.device, dtype=sp.dtype)
        pkg = render(viewpoint, gaussians, pipe, bg, override_color=override)
        if pkg is None:
            return None
        return pkg["render"][0:1].detach().clamp(0.0, 1.0)  # (1,H,W)


def compute_residual_evidence(config, image, viewpoint):
    """Per-pixel dynamic evidence in [0,1] from the RGB rendering residual."""
    tau = float(get_static_prob_config(config).get("residual_tau", 0.15))
    with torch.no_grad():
        gt = viewpoint.original_image.to(device=image.device, dtype=image.dtype)
        r = torch.abs(image.detach() - gt).mean(dim=0, keepdim=True)  # (1,H,W)
        return 1.0 - torch.exp(-r / max(tau, 1e-6))  # (1,H,W) [0,1)


def update_static_prob_from_evidence(
    config, gaussians, viewpoint, evidence, visibility_filter=None
):
    """EMA-update each visible Gaussian's static_prob from a per-pixel dynamic
    evidence map (mirrors update_gaussian_static_memory but residual-driven and
    gated by the StaticProb config)."""
    if gaussians is None or gaussians.get_xyz.shape[0] == 0:
        return
    sc = get_static_prob_config(config)
    beta = float(sc.get("memory_beta", 0.90))
    default = float(sc.get("initial_static_prob", 0.7))
    gaussians.ensure_static_memory_state(default)

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
        return

    uu = torch.clamp(u[valid].round().long(), 0, w - 1)
    vv = torch.clamp(v[valid].round().long(), 0, h - 1)
    idx = torch.nonzero(valid, as_tuple=False).squeeze(1)
    dyn = evidence.to(device=device)[0, vv, uu].view(-1, 1).clamp(0.0, 1.0)
    static_obs = torch.clamp(1.0 - dyn, 0.0, 1.0)
    gaussians.static_prob[idx] = (
        beta * gaussians.static_prob[idx] + (1.0 - beta) * static_obs
    )
    gaussians.static_obs_count[idx] += 1.0
