"""exp39 A2: continuous (soft) dynamic weighting for the mapping/BA loss.

Background (why this module exists at all):
  exp34 measured that the gain carrier of the semantic-mask backbone is the *BA
  observation aggregation* (share_BA 0.44-0.80), and exp36/37 narrowed the decisive
  channel to `mask_mapping` -- the dynamic mask consumed by `get_loss_mapping_rgbd`.
  That consumer is **binary**: a dynamic pixel contributes exactly zero. exp37/38 then
  measured a variance-bias trade-off on the pose side (dropping more pixels raises
  per-frame variance but lowers the coherent/drift component, and ATE follows the
  bias). This module parameterises the binary endpoint into a continuous one so the
  trade-off can be tested *in the aggregator itself*.

Two default-off arms:
  - `soft_mapping`  (treatment): dynamic pixels keep weight `mapping_floor` instead of 0.
                    floor=0.0 is numerically identical to today's hard mask;
                    floor=1.0 is identical to no mask at all.
  - `mapping_scale_match` (control): keeps the HARD mask but rescales the photometric
                    terms by the weight mass the soft arm would have had. Required
                    because `get_loss_mapping_rgbd` normalises by the full H*W pixel
                    count while `slam_backend` adds a fixed-scale isotropic regulariser
                    -- so changing the floor changes the photometric-to-regulariser
                    ratio as well as the weight shape. Without this arm a Phase-1 win
                    cannot be attributed to the weight shape (codex adversarial review,
                    2026-08-22, results/evidence/consult_codex_exp39_direction.md).
"""

import torch

from utils.semantic_mask import get_semantic_mask_config, mask_mapping_enabled


def _floor_value(sc):
    floor = float(sc.get("mapping_floor", 0.0))
    if not 0.0 <= floor <= 1.0:
        raise ValueError(
            f"SemanticMask.mapping_floor must be in [0, 1], got {floor}"
        )
    return floor


def mapping_soft_floor(config):
    """Floor for the soft (treatment) arm, or None when the arm is off.

    Returns None unless `mask_mapping` is on -- with no dynamic mask reaching the
    mapping loss there is nothing to soften, and silently reporting a floor would
    make an inert arm look live.
    """
    sc = get_semantic_mask_config(config)
    if not bool(sc.get("soft_mapping", False)):
        return None
    if bool(sc.get("mapping_scale_match", False)):
        raise ValueError(
            "SemanticMask.soft_mapping and .mapping_scale_match are the treatment and "
            "its control; enabling both in one run makes the arm unidentifiable"
        )
    if not mask_mapping_enabled(config):
        return None
    return _floor_value(sc)


def mapping_ema_enabled(config):
    """Exp39 Step C hook (default-off).

    Returns True when the per-pixel lagged-residual EMA mechanism is active. The
    actual stateful recorder lives in ``utils/mapping_probe.MappingEMARecorder``
    and is only instantiated by the backend when this returns True -- so the
    return value here is the sole gate between a byte-identical main path and the
    EMA treatment path.
    """
    sc = get_semantic_mask_config(config)
    return bool(sc.get("mapping_ema", False))


def mapping_ema_config(config):
    """Return the EMA hyperparameters (beta, lambda, sigma_min, scramble) if enabled, else None."""
    if not mapping_ema_enabled(config):
        return None
    sc = get_semantic_mask_config(config)
    return {
        "beta": float(sc.get("mapping_ema_beta", 0.95)),
        "lam": float(sc.get("mapping_ema_lambda", 1.0)),
        "sigma_min": float(sc.get("mapping_ema_sigma_min", 0.01)),
        "scramble": bool(sc.get("mapping_ema_scramble", False)),
    }


def mapping_scale_match_floor(config):
    """Floor whose weight mass the hard (control) arm should match, or None when off."""
    sc = get_semantic_mask_config(config)
    if not bool(sc.get("mapping_scale_match", False)):
        return None
    if not mask_mapping_enabled(config):
        return None
    return _floor_value(sc)


def ema_mass_matched(config):
    """True when the EMA weight map must be renormalised to the hard mask's weight mass.

    Why this exists (exp39 Step C, 2026-08-23 audit): the original EMA branch returned
    ``c_rgb = sum(w)/count(valid)`` -- the MEAN weight -- and then *multiplied* the loss
    by it, so the photometric term scaled as ``mean(err*w) * mean(w) ~ err * w_bar**2``.
    With the measured ``w_bar ~ 239`` (E) and ``~538`` (E-scrambled) that inflates the
    photometric term by 5.7e4 and 2.9e5 respectively against the hard arm, which
    effectively deletes the fixed ``10 * isotropic_loss.mean()`` regulariser in those
    arms. Any E-vs-H ATE difference is then confounded by a five-order-of-magnitude
    scale change, exactly the failure mode Phase 1 invented the S arm to avoid.

    With this flag on, the weight map is rescaled so its total mass over contributing
    pixels equals the hard arm's (``count(valid & static)``) and the multiplier is 1,
    making E and H differ only in how a *fixed* amount of weight is distributed.
    """
    sc = get_semantic_mask_config(config)
    return bool(sc.get("mapping_ema_mass_match", False))


def ema_zero_dynamic(config):
    """True when the EMA weight map must be zeroed on dynamic pixels.

    This is the ``admission`` variable in isolation: an arm with EMA-shaped weights
    over the static population only. Against H it isolates the weight *shape* within
    the static pixels; against the admitting EMA arm it isolates *admission* itself.
    """
    sc = get_semantic_mask_config(config)
    return bool(sc.get("mapping_ema_zero_dynamic", False))


def apply_ema_mass_match(weight_map, contributing, target_mass, eps=1e-12):
    """Rescale ``weight_map`` so its mass over ``contributing`` equals ``target_mass``.

    Returns the rescaled map. ``target_mass`` is the hard arm's effective pixel count,
    so a uniform weight map is returned unchanged up to float error -- which is what
    makes the mathematical-equivalence test against H possible.
    """
    current = (weight_map * contributing.to(dtype=weight_map.dtype)).sum()
    if float(current) <= eps:
        return weight_map
    return weight_map * (target_mass / current)


def dynamic_weight_map(static_mask, floor, dtype):
    """(1,H,W) weight: 1 on static pixels, `floor` on dynamic ones."""
    static = static_mask.to(dtype=dtype)
    return static + (1.0 - static) * floor


def scale_match_factor(valid_mask, static_mask, floor, eps=1e-8):
    """Σw(soft) / Σw(hard) over the pixels this term actually sums.

    Detached by construction (built from masks only, no autograd history) -- it must
    not open a second gradient path into the loss.
    """
    valid = valid_mask.to(dtype=torch.float32)
    static = static_mask.to(dtype=torch.float32)
    soft_mass = (valid * (static + (1.0 - static) * floor)).sum()
    hard_mass = (valid * static).sum()
    return (soft_mass / torch.clamp(hard_mass, min=eps)).item()


def ema_dynamic_cap(config):
    """Target ``mean_w(dynamic) / mean_w(static)`` for the admission-dose scan, or None.

    exp39 Step C measured two ends of the dose axis on balloon: a 31.8% admission share
    doubles ATE (6.53 vs 3.27, 7.6x the per-arm floor) while a 0% share is
    indistinguishable from the hard mask (0.1x floor). This flag parameterises the
    share itself so the open question -- is there a share small enough to be harmless?
    -- becomes a single-variable scan.

    The cap rescales dynamic weights so their MEAN hits ``cap x mean_w(static)``, rather
    than clamping each pixel. Two reasons: the controlled quantity is then exactly the
    quantity the diagnostics report (so gate G-4 can verify the dose was delivered), and
    a mean-preserving rescale keeps the EMA's relative shape *within* the dynamic
    population instead of flattening its top end. The subsequent
    ``mapping_ema_mass_match`` rescales all pixels uniformly, which leaves this ratio
    invariant -- so dose and total mass are independent knobs.
    """
    sc = get_semantic_mask_config(config)
    cap = sc.get("mapping_ema_dynamic_cap", None)
    if cap is None:
        return None
    cap = float(cap)
    if not 0.0 <= cap <= 1.0:
        raise ValueError(
            f"SemanticMask.mapping_ema_dynamic_cap must be in [0, 1], got {cap}"
        )
    return cap


def apply_ema_dynamic_cap(weight_map, valid, dynamic, cap, eps=1e-12):
    """Rescale dynamic-pixel weights so mean_w(dynamic) == cap * mean_w(static)."""
    dyn_sel = dynamic & valid
    stat_sel = (~dynamic) & valid
    if not bool(dyn_sel.any()) or not bool(stat_sel.any()):
        return weight_map
    mean_dyn = weight_map[dyn_sel].mean()
    mean_stat = weight_map[stat_sel].mean()
    if float(mean_dyn) <= eps:
        return weight_map
    factor = (cap * mean_stat) / mean_dyn
    return torch.where(dyn_sel, weight_map * factor, weight_map)


def ema_weight_diagnostics(weight_map, valid_mask, dynamic_mask):
    """Quantify how much the EMA weight map treats dynamic pixels differently.

    A successful EMA must have ``mean_w(dynamic) < mean_w(static)`` -- it down-weights
    the pixels the binary mask deletes rather than treating all pixels uniformly.

    **2026-08-23 bug fix — this function inverted its own primary readout.** The third
    parameter used to be named ``static_mask`` and was consumed as
    ``static = static_mask & valid``, but both call sites passed the DYNAMIC mask. So
    ``ema_mean_weight_static`` reported the mean over dynamic pixels and vice versa, and
    ``ema_dynamic_over_static`` was the reciprocal of its own name. Every Step C round
    (R1 -3.21 / R2 -3.51 / R3 -3.91 / Step B -2.15) was read through that inversion, and
    the pre-registered gate was judged on the flipped sign. Proof of the swap: in the
    ``zero_dynamic`` arm the dynamic weight is 0 by construction, and the field named
    ``ema_mean_weight_static`` read exactly 0.0 over all 668 probe frames while
    ``ema_mean_weight_dynamic`` read exactly 1.0 (the mass-matched static mean).
    The parameter is now named for what callers actually pass.
    """
    w = weight_map.detach().to(dtype=torch.float32)
    valid = valid_mask.to(dtype=torch.bool)
    dynamic = dynamic_mask.to(dtype=torch.bool) & valid
    static = (~dynamic_mask.to(dtype=torch.bool)) & valid

    static_mean = float(w[static].mean().item()) if static.any() else None
    dynamic_mean = float(w[dynamic].mean().item()) if dynamic.any() else None
    ratio = (dynamic_mean / static_mean) if (static_mean is not None and dynamic_mean is not None and static_mean > 0) else None
    return {
        "ema_mean_weight_static": static_mean,
        "ema_mean_weight_dynamic": dynamic_mean,
        # mean_w(dynamic) / mean_w(static): < 1 means dynamic pixels are suppressed.
        "ema_dynamic_over_static": ratio,
        # Pre-registered primary readout: > 0 means the EMA suppresses dynamic pixels.
        "ema_bias_suppression": (1.0 - ratio) if ratio is not None else None,
    }


def ema_component_decomposition(ema_recorder, valid_mask, dynamic_mask):
    """Decompose the EMA weight into its mu^2 (bias^2) and sigma^2 (variance) parts.

    Per-pixel: ``w = 1 / (sigma^2 + lambda * mu^2 + eps)``, so whichever population has
    the SMALLER components receives the LARGER weight. Reporting both parts separately
    says which term drives the weight split.

    **2026-08-23 bug fix**: the third parameter used to be named ``static_mask`` while
    both call sites passed the dynamic mask, so ``ema_mu2_dynamic`` reported mu^2 over
    the STATIC population and vice versa (same defect as
    :func:`ema_weight_diagnostics`). Read through that swap, balloon looked like
    ``mu2_dyn/mu2_stat = 0.311`` (dynamic residuals *smaller*), which is what the
    withdrawn "absorption meter" criterion was built on. Corrected, the ratio is ~3.0:
    dynamic pixels carry the LARGER residual, as a moving object under a static map
    should.

    Must be called after ``compute_weights()``/``update()`` so mu/q are populated.
    """
    if ema_recorder is None or not ema_recorder.is_enabled():
        return {}
    if ema_recorder.mu_rgb is None or ema_recorder.q_rgb is None:
        return {}

    valid = valid_mask.to(dtype=torch.bool)
    dynamic = dynamic_mask.to(dtype=torch.bool) & valid
    static = (~dynamic_mask.to(dtype=torch.bool)) & valid

    # Compute per-pixel components on the recorder's device
    # mu_rgb shape: [1, H, W] → squeeze to [H, W]
    mu2 = (ema_recorder.mu_rgb ** 2).squeeze(0)  # [H, W]
    sigma2 = torch.clamp(
        ema_recorder.q_rgb - ema_recorder.mu_rgb ** 2,
        min=ema_recorder.sigma_min ** 2
    ).squeeze(0)  # [H, W]

    # Ensure masks are [H, W] to match
    if static.dim() > 2:
        static = static.squeeze(0)
        dynamic = dynamic.squeeze(0)

    def safe_mean(tensor, mask):
        if not mask.any():
            return None
        return float(tensor[mask].mean().item())

    mu2_dyn = safe_mean(mu2, dynamic)
    mu2_stat = safe_mean(mu2, static)
    sig2_dyn = safe_mean(sigma2, dynamic)
    sig2_stat = safe_mean(sigma2, static)

    return {
        "ema_mu2_dynamic": mu2_dyn,
        "ema_mu2_static": mu2_stat,
        "ema_mu2_ratio": (mu2_dyn / mu2_stat) if (mu2_dyn is not None and mu2_stat is not None and mu2_stat > 0) else None,
        "ema_sigma2_dynamic": sig2_dyn,
        "ema_sigma2_static": sig2_stat,
        "ema_sigma2_ratio": (sig2_dyn / sig2_stat) if (sig2_dyn is not None and sig2_stat is not None and sig2_stat > 0) else None,
    }


def weight_stats(valid_mask, static_mask, floor):
    """Phase-0 mechanism diagnostics for one keyframe evaluation.

    Cheap counters only (masks + floor). The expensive Phase-0 probes -- gradient
    attribution over the pose vs Gaussian blocks and BA observability -- are separate;
    per the pre-registration these counters alone are NOT a sufficient gate.
    """
    valid = valid_mask.to(dtype=torch.float32)
    static = valid * static_mask.to(dtype=torch.float32)
    dynamic = valid - static
    w = valid * dynamic_weight_map(static_mask, floor, torch.float32).view_as(valid)

    n_valid = float(valid.sum().item())
    n_dyn = float(dynamic.sum().item())
    w_sum = float(w.sum().item())
    w_sq_sum = float((w * w).sum().item())
    return {
        "valid_pixels": n_valid,
        "dynamic_frac": (n_dyn / n_valid) if n_valid > 0 else 0.0,
        # applied_frac: share of valid pixels carrying a weight strictly below 1.
        # At floor=1.0 nothing is down-weighted even though dynamic pixels exist.
        "applied_frac": (n_dyn / n_valid) if (n_valid > 0 and floor < 1.0) else 0.0,
        "mean_w_static": (
            float((w * static).sum().item()) / float(static.sum().item())
            if float(static.sum().item()) > 0
            else None
        ),
        "mean_w_dynamic": (
            float((w * dynamic).sum().item()) / n_dyn if n_dyn > 0 else None
        ),
        "weight_mass": w_sum,
        # Effective sample size of the weight field: (Σw)^2 / Σw^2. Separates
        # "down-weighted a lot of pixels" from "kept the same effective observations".
        "ess": (w_sum * w_sum / w_sq_sum) if w_sq_sum > 0 else 0.0,
        "ess_frac": (
            (w_sum * w_sum / w_sq_sum) / n_valid if (w_sq_sum > 0 and n_valid > 0) else 0.0
        ),
    }
