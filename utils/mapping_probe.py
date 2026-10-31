"""exp39 Phase-0 probe: where does the mapping/BA gradient actually go?

Why this exists (and why `applied_frac` alone is not a Phase-0 gate):
  The treatment re-admits dynamic pixels at weight `floor`. Counting how many pixels
  carry a weight below 1 only proves the *weight field* changed -- it says nothing about
  whether that change reached the optimiser. What has to move is the **gradient's
  composition over the two parameter blocks the mapping loss jointly drives**: the
  Gaussian parameters and the window keyframe poses. That distinction is not cosmetic:
  the closed DBAphoto verdict (2026-08-03) died precisely because a reliability-weighted
  objective moved the *minimiser* rather than merely re-weighting observations, and the
  codex review (2026-08-22) flagged that the same failure mode can recur here through
  map-pose co-adaptation. So Phase 0 measures the pose block separately from the map
  block, and reports how much of each the dynamic pixels command.

The probe re-renders one keyframe on its own graph rather than hooking the accumulated
mapping loss, so it cannot perturb the run it is observing: gradients are read with
`torch.autograd.grad`, never `.backward()`, and nothing is stepped.
"""

import json
import os

import torch

from gaussian_splatting.gaussian_renderer import render
from utils.mapping_weight import dynamic_weight_map


def mapping_probe_config(config):
    return config.get("MappingProbe", {})


def mapping_probe_enabled(config):
    return bool(mapping_probe_config(config).get("enabled", False))


def mapping_probe_interval(config):
    return int(mapping_probe_config(config).get("interval", 50))


def _split_losses(config, image, depth, viewpoint, dynamic_mask, floor,
                   weight_map=None, c_mass=None):
    """(L_dynamic, L_static): the mapping loss restricted to each pixel population.

    Weights are the treatment's own weights, so the two terms sum to the treatment loss
    (up to the shared 1/(H*W) normaliser) and their gradients are directly comparable.
    """
    alpha = config["Training"]["alpha"] if "alpha" in config["Training"] else 0.95
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]

    gt_image = viewpoint.original_image.cuda()
    gt_depth = torch.from_numpy(viewpoint.depth).to(
        dtype=torch.float32, device=image.device
    )[None]
    rgb_valid = (gt_image.sum(dim=0) > rgb_boundary_threshold).view(*depth.shape)
    depth_valid = (gt_depth > 0.01).view(*depth.shape)

    static = (~dynamic_mask.to(device=depth.device, dtype=torch.bool)).view(*depth.shape)
    w = dynamic_weight_map(static, floor if floor is not None else 0.0, image.dtype)

    rgb_err = torch.abs(image - gt_image)
    depth_err = torch.abs(depth - gt_depth)

    # When an external weight map (e.g. the EMA treatment) is supplied, the two splits
    # must still reconstruct the *same* objective the backend will optimise -- but that
    # objective includes the scale-matching constant `c_mass` that converts the
    # per-pixel weight map into the same photometric-to-regulariser ratio as the hard
    # baseline.  Without threading `c_mass` through the split the probe would read a
    # different loss surface and its gradient attribution would be non-actionable.
    # NOTE: when no external weight map is supplied the existing floor-based weights `w`
    # are used so that the Phase-0 path stays byte-identical.
    effective_weight_map = weight_map if weight_map is not None else w
    effective_c = c_mass if c_mass is not None else 1.0
    out = []
    for population in (~static, static):
        sel = population.to(dtype=image.dtype)
        w_rgb = rgb_valid.to(dtype=image.dtype) * effective_weight_map * sel
        w_depth = depth_valid.to(dtype=depth.dtype) * effective_weight_map.to(depth.dtype) * sel.to(depth.dtype)
        out.append(
            effective_c * (alpha * (rgb_err * w_rgb).mean() + (1 - alpha) * (depth_err * w_depth).mean())
        )
    return out[0], out[1], effective_weight_map, effective_c


def _grad_norm(loss, params):
    params = [p for p in params if p is not None and p.requires_grad]
    if not params or not loss.requires_grad:
        return 0.0
    grads = torch.autograd.grad(
        loss, params, retain_graph=True, allow_unused=True, materialize_grads=True
    )
    return float(torch.sqrt(sum((g.detach() ** 2).sum() for g in grads)).item())


_GLOBAL_EMA_RECORDER = None


def set_global_ema_recorder(recorder):
    """Register the backend's MappingEMARecorder so the probe can read its state."""
    global _GLOBAL_EMA_RECORDER
    _GLOBAL_EMA_RECORDER = recorder


def _ema_weight_from_config(config, image, depth, viewpoint):
    """Compute EMA weight map from the probe's own render using the global recorder."""
    from utils.mapping_weight import mapping_ema_enabled
    if not mapping_ema_enabled(config):
        return None, None
    if _GLOBAL_EMA_RECORDER is None or not _GLOBAL_EMA_RECORDER.is_enabled():
        return None, None
    gt_image = viewpoint.original_image.cuda()
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]
    rgb_valid = (gt_image.sum(dim=0) > rgb_boundary_threshold).view_as(depth)
    depth_valid = (torch.from_numpy(viewpoint.depth).to(
        dtype=torch.float32, device=depth.device
    )[None] > 0.01).view_as(depth)
    w, c = _GLOBAL_EMA_RECORDER.weight_map(image, gt_image, depth,
        torch.from_numpy(viewpoint.depth).to(dtype=torch.float32, device=depth.device)[None],
        rgb_valid, depth_valid)
    return w, c


def probe_mapping_attribution(
    config, gaussians, viewpoint, pipeline_params, background, dynamic_mask, floor,
    weight_map=None, c_mass=None, ema_recorder=None,
):
    """Gradient mass the dynamic vs static pixels put on each parameter block.

    Returns None when the probe cannot say anything (no mask ⇒ no populations to split).
    """
    if dynamic_mask is None:
        return None

    render_pkg = render(viewpoint, gaussians, pipeline_params, background)
    image, depth = render_pkg["render"], render_pkg["depth"]

    # When Step C EMA is enabled, compute the per-pixel weight map from the
    # **backend's** EMA state (read-only).  The probe must NOT call weight_map()
    # because that advances the EMA state — the backend already did that with the
    # main render residuals.  Using compute_weights() avoids the double-update bug
    # where the probe's independent render residuals would corrupt the state.
    from utils.mapping_weight import (
        apply_ema_dynamic_cap,
        apply_ema_mass_match,
        ema_dynamic_cap,
        ema_mass_matched,
        ema_weight_diagnostics,
        ema_zero_dynamic,
        mapping_ema_enabled,
    )
    ema_on = mapping_ema_enabled(config)
    if ema_on and weight_map is None and ema_recorder is not None and ema_recorder.is_enabled():
        gt_image = viewpoint.original_image.cuda()
        rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]
        rgb_valid = (gt_image.sum(dim=0) > rgb_boundary_threshold).view_as(depth)
        weight_map, c_mass = ema_recorder.compute_weights(rgb_valid, image.dtype)

        # The probe must report the weight the OBJECTIVE uses, not the raw EMA state.
        # `mapping_ema_zero_dynamic` / `mapping_ema_mass_match` are applied downstream
        # in get_loss_mapping_rgbd, so a probe that skips them measures a weight field
        # the optimiser never sees -- which is exactly how gate G-2 came back FAIL on a
        # correctly-configured zeromask arm (2026-08-23). Mirror the loss here so the
        # diagnostics and the gradient attribution below are about the real objective.
        static_eff = (~dynamic_mask.to(device=weight_map.device, dtype=torch.bool)).view_as(
            weight_map
        )
        zero_dyn = ema_zero_dynamic(config)
        if zero_dyn:
            weight_map = weight_map * static_eff.to(dtype=weight_map.dtype)
        else:
            cap = ema_dynamic_cap(config)
            if cap is not None:
                weight_map = apply_ema_dynamic_cap(
                    weight_map, rgb_valid.view_as(weight_map), ~static_eff, cap
                )
        if ema_mass_matched(config):
            hard_support = rgb_valid.view_as(weight_map) & static_eff
            target_mass = hard_support.to(dtype=weight_map.dtype).sum()
            contributing = rgb_valid.view_as(weight_map) & (
                static_eff if zero_dyn else rgb_valid.view_as(weight_map)
            )
            weight_map = apply_ema_mass_match(weight_map, contributing, target_mass)
            c_mass = 1.0

    l_dyn, l_stat, w_map, c_mass = _split_losses(config, image, depth, viewpoint, dynamic_mask, floor, weight_map=weight_map, c_mass=c_mass)

    # exp39 Phase-0 gap fix: Phase 0 had to substitute the run's `person px zeroed` log
    # for applied_frac, and those two are NOT estimates of the same population (the log
    # only fires at keyframes, and dense keyframing favours high-mask frames). Recording
    # it here, on the same frames the gradients are read from, closes that mismatch.
    rgb_boundary_threshold = config["Training"]["rgb_boundary_threshold"]
    gt_image = viewpoint.original_image.cuda()
    valid = (gt_image.sum(dim=0) > rgb_boundary_threshold).view_as(
        dynamic_mask.view(1, *dynamic_mask.shape[-2:])
    )
    dyn_bool = dynamic_mask.to(device=valid.device, dtype=torch.bool).view_as(valid)
    n_valid = float(valid.sum().item())
    applied_frac = (
        float((valid & dyn_bool).sum().item()) / n_valid if n_valid > 0 else 0.0
    )

    # exp39 Step C diagnostics: how the EMA weight map treats dynamic vs static pixels
    from utils.mapping_weight import ema_component_decomposition
    ema_diag = {}
    if weight_map is not None:
        ema_diag = ema_weight_diagnostics(weight_map, valid, dyn_bool)
    # Decompose into mu^2 / sigma^2 components to diagnose WHY dynamic pixels get higher weights
    if ema_recorder is not None and ema_recorder.is_enabled():
        ema_diag.update(ema_component_decomposition(ema_recorder, valid, dyn_bool))

    map_params = [gaussians._xyz, gaussians._opacity, gaussians._scaling]
    pose_params = [
        getattr(viewpoint, "cam_rot_delta", None),
        getattr(viewpoint, "cam_trans_delta", None),
    ]

    g_map_dyn = _grad_norm(l_dyn, map_params)
    g_map_stat = _grad_norm(l_stat, map_params)
    g_pose_dyn = _grad_norm(l_dyn, pose_params)
    g_pose_stat = _grad_norm(l_stat, pose_params)

    # The probe's contract is that it must not perturb the run it observes. Its own
    # render graph is held alive by the four `retain_graph=True` grad reads above, and
    # the cached blocks behind it are the probe's -- not the run's -- footprint. At
    # frame ~300 of balloon the mapping run already sits near the 24 GB card limit
    # (exp39 Step B OOMed there in both arms), so leaving this graph and its cache
    # around is itself an intervention. Release both now that every gradient is read:
    # the four floats above are all we keep.
    del l_dyn, l_stat, render_pkg, image, depth
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    def share(dyn, stat):
        total = dyn + stat
        return (dyn / total) if total > 0 else None

    return {
        "uid": int(viewpoint.uid),
        "floor": float(floor) if floor is not None else 0.0,
        # Share of valid pixels the mask marks dynamic, on THIS frame -- the gate's
        # own measurement, no longer borrowed from the keyframe-only console log.
        "applied_frac": applied_frac,
        "grad_map_dynamic": g_map_dyn,
        "grad_map_static": g_map_stat,
        "grad_pose_dynamic": g_pose_dyn,
        "grad_pose_static": g_pose_stat,
        # PRIMARY Phase-0 readings: the dynamic pixels' share of each block's gradient.
        # At floor=0 both must be exactly 0 (hard mask deletes those pixels); a non-zero
        # value there means the arm is not the arm it claims to be.
        "dyn_share_map": share(g_map_dyn, g_map_stat),
        "dyn_share_pose": share(g_pose_dyn, g_pose_stat),
        # Stability side-channel for the map-pose co-adaptation risk: if re-admitting
        # dynamic pixels makes the pose block's gradient collapse or explode relative to
        # the map block's, the joint BA is being reshaped, not merely re-weighted.
        "pose_to_map_ratio": (
            (g_pose_dyn + g_pose_stat) / (g_map_dyn + g_map_stat)
            if (g_map_dyn + g_map_stat) > 0
            else None
        ),
        # exp39 Step C diagnostics: how the EMA weight map treats dynamic vs static pixels.
        # A successful EMA must have ema_dynamic_over_static < 1 (dynamic pixels suppressed).
        **ema_diag,
    }


class MappingProbeRecorder:
    def __init__(self, config):
        self.config = config
        self.rows = []

    def observe(self, **kwargs):
        row = probe_mapping_attribution(self.config, **kwargs)
        if row is not None:
            self.rows.append(row)
        return row

    def flush(self, save_dir):
        if not save_dir or not self.rows:
            return None
        path = os.path.join(save_dir, "mapping_probe.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"rows": self.rows}, file, indent=2)
        return path


class MappingEMARecorder:
    """Stateful recorder for the Step C per-pixel lagged-residual EMA.

    The recorder holds the actual mu/q state and only advances it with
    ``update()`` *after* the current iteration's loss has been evaluated --
    so the current iteration sees the *previous* iteration's statistics and
    there is no self-referential cycle in the computational graph.

    State is kept on CPU to avoid GPU memory overhead; the conversion happens
    inside ``compute_weights()`` / ``update()`` which are called once per
    backend iteration.

    **API contract** (exp39 residual-source bug fix):
      - ``compute_weights()`` is **read-only**: it derives the weight map from
        the *current* mu/q state without modifying it.  Safe for the probe to
        call as often as needed.
      - ``update()`` advances mu/q with the supplied residuals.  Must be called
        **exactly once** per iteration, with the **main render's** residuals --
        never with the probe's independent render residuals.
    """

    def __init__(self, config):
        from utils.mapping_weight import mapping_ema_config
        self.config = config
        cfg = mapping_ema_config(config) or {}
        self.beta = float(cfg.get("beta", 0.95))
        self.lam = float(cfg.get("lam", 1.0))
        self.sigma_min = float(cfg.get("sigma_min", 0.01))
        self.scramble = bool(cfg.get("scramble", False))
        self._is_enabled = bool(cfg)
        self.mu_rgb = None
        self.mu_depth = None
        self.q_rgb = None
        self.q_depth = None
        self.first = True

    def is_enabled(self):
        return self._is_enabled

    def compute_weights(self, rgb_valid, image_dtype):
        """Read-only: derive (w_map, c_mass) from the current EMA state.

        Uses ``self.mu_rgb`` / ``self.q_rgb`` which were set by the most recent
        ``update()`` call (or left at their initial values on the first
        iteration).  Does NOT modify any state -- safe for the probe.
        """
        if self.mu_rgb is None or self.q_rgb is None:
            # First iteration: no state yet → uniform weights (no EMA effect).
            w_map = torch.zeros_like(rgb_valid, dtype=image_dtype)
            w_map[rgb_valid] = 1.0
            w_map[~rgb_valid] = 0.0
            c_mass = rgb_valid.to(dtype=image_dtype).sum().item()
            return w_map, (c_mass / max(c_mass, 1.0))

        lam = self.lam
        sigma_min = self.sigma_min
        loss_eps = 1e-6

        # Ensure EMA state is on the same device as rgb_valid
        device = rgb_valid.device
        mu_rgb = self.mu_rgb.to(device=device) if self.mu_rgb.device != device else self.mu_rgb
        q_rgb = self.q_rgb.to(device=device) if self.q_rgb.device != device else self.q_rgb

        # D-3: spatial scramble — shuffle the EMA state to break the weight<->pixel
        # correspondence while leaving the weight distribution intact.
        #
        # 2026-08-23 fix: the first version permuted over the WHOLE grid, but the loss
        # only consumes `rgb_valid` pixels. Invalid pixels (near-black gt) carry
        # mu,q ~ 0, so their sigma2 clamps to sigma_min**2 = 1e-4 and their weight is
        # ~1e4; permuting globally injected those into valid positions and raised the
        # valid-restricted mean weight from 239 to 538 (2.25x). That broke the very
        # property the arm claims -- an equal-mass, equal-marginal, shape-only
        # intervention. Permuting WITHIN the valid set preserves both exactly.
        if self.scramble:
            idx = rgb_valid.reshape(-1).nonzero(as_tuple=True)[0]
            if idx.numel() > 1:
                perm = idx[torch.randperm(idx.numel(), device=device)]
                for state in (mu_rgb, q_rgb):
                    flat = state.reshape(-1).clone()
                    flat[idx] = flat[perm]
                    state_shuffled = flat.reshape(state.shape)
                    if state is mu_rgb:
                        mu_rgb = state_shuffled
                    else:
                        q_rgb = state_shuffled

        sigma2 = torch.clamp(q_rgb - mu_rgb ** 2, min=sigma_min ** 2)
        bias2 = mu_rgb ** 2

        w_map = torch.zeros_like(rgb_valid, dtype=image_dtype)
        w_map[rgb_valid] = 1.0 / (sigma2[rgb_valid] + lam * bias2[rgb_valid] + loss_eps)
        w_map[~rgb_valid] = 0.0

        c_mass = rgb_valid.to(dtype=image_dtype).sum().item()
        w_mass = w_map[rgb_valid].sum().item()
        c_rgb = (w_mass / c_mass) if c_mass > 0 else 1.0
        return w_map, c_rgb

    def update(self, rgb_err, depth_err):
        """Advance the EMA state with the main render's residuals.

        Call exactly once per backend iteration, AFTER ``compute_weights()``
        has read the previous state.  ``rgb_err`` and ``depth_err`` must come
        from the **main render** (the one feeding the mapping loss), NOT from
        the probe's independent render.
        """
        beta = self.beta

        if self.first:
            self.mu_rgb = rgb_err.clone()
            self.mu_depth = depth_err.clone()
            self.q_rgb = (rgb_err ** 2).clone()
            self.q_depth = (depth_err ** 2).clone()
            self.first = False
        else:
            self.mu_rgb = beta * self.mu_rgb + (1 - beta) * rgb_err
            self.mu_depth = beta * self.mu_depth + (1 - beta) * depth_err
            self.q_rgb = beta * self.q_rgb + (1 - beta) * (rgb_err ** 2)
            self.q_depth = beta * self.q_depth + (1 - beta) * (depth_err ** 2)

    def weight_map(self, image, gt_image, depth, gt_depth, rgb_valid, depth_valid):
        """Legacy single-call API: compute weights AND update state.

        Kept for backward compatibility with callers that only call this once
        per iteration (e.g. the backend's ``_compute_ema_weight``).  The probe
        MUST NOT use this method -- use ``compute_weights()`` instead.
        """
        rgb_err = torch.abs(image - gt_image).mean(dim=0, keepdim=True).detach()
        depth_err = torch.abs(depth - gt_depth).detach()

        # Compute weights from current state (before update).
        w_map, c_mass = self.compute_weights(rgb_valid, image.dtype)

        # Advance state.
        self.update(rgb_err, depth_err)

        return w_map, c_mass
