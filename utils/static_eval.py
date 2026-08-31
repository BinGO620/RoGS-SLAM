"""Hole-safe static-background rendering metrics (make-or-break P-A).

Method-INDEPENDENT static-background evaluation for anti-dynamic 3DGS SLAM. The
support set is

    M_static = (gt depth valid) AND (NOT dynamic)

and is *never* intersected with an arm's rendered opacity, rendered-depth
validity, or co-visibility. That is deliberate: a conservative arm that leaves a
hole (no Gaussian) in a static-background region must be *scored on that hole*
(as a rendering/geometry error), not have the hole silently excluded from the
denominator. Otherwise "emit fewer Gaussians" would win by shrinking the metric
support. See
``workspace/dynamic-3dgs-slam/03-knowledges/11-make_or_break_ablation_spec.md`` §0.

All image tensors are ``(C, H, W)`` float in ``[0, 1]``; depths are ``(H, W)`` in
metres; masks are ``(H, W)`` bool. Everything runs on CPU or CUDA and is pure
(no dataset / GPU-render dependency) so it is unit-testable in isolation.
"""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F

__all__ = [
    "static_support_mask",
    "masked_psnr",
    "masked_ssim",
    "masked_lpips",
    "static_coverage",
    "penalized_depth_l1_cm",
    "static_background_metrics",
    "dynamic_adjacent_band_mask",
    "dynamic_band_metrics",
    "vacated_region_mask",
    "vacated_region_metrics",
    "vacated_contrast_metrics",
]


def _as_hw_bool(x, shape, device) -> torch.Tensor:
    if x is None:
        return torch.zeros(shape, dtype=torch.bool, device=device)
    t = x if torch.is_tensor(x) else torch.as_tensor(np.asarray(x))
    return t.to(device=device, dtype=torch.bool).reshape(shape)


def _as_hw_float(x, device) -> torch.Tensor:
    t = x if torch.is_tensor(x) else torch.as_tensor(np.asarray(x))
    return t.to(device=device, dtype=torch.float32).squeeze()


def static_support_mask(gt_depth, dynamic_mask=None) -> torch.Tensor:
    """``M_static = (gt depth finite & > 0) AND (NOT dynamic)`` as a ``(H, W)`` bool.

    ``dynamic_mask`` is the method-INDEPENDENT dynamic region (Bonn GT / frozen
    shared mask), ``True`` where dynamic. It must NOT come from the arm under test.
    """
    gt = _as_hw_float(gt_depth, gt_depth.device if torch.is_tensor(gt_depth) else "cpu")
    device = gt.device
    valid = torch.isfinite(gt) & (gt > 0.0)
    dyn = _as_hw_bool(dynamic_mask, gt.shape, device)
    return valid & (~dyn)


def masked_psnr(pred, gt, mask) -> float:
    """PSNR over ``mask`` pixels only (per-channel MSE, standard -10 log10)."""
    device = pred.device
    m = _as_hw_bool(mask, pred.shape[-2:], device)
    if not bool(m.any()):
        return float("nan")
    # (C, H, W) -> select masked pixels across channels
    pred_m = pred[:, m]
    gt_m = gt.to(device)[:, m]
    mse = torch.mean((pred_m - gt_m) ** 2)
    if mse.item() <= 0.0:
        return float("inf")
    return float((-10.0 * torch.log10(mse)).item())


def _gaussian_window(window_size: int, sigma: float, channels: int, device, dtype) -> torch.Tensor:
    coords = torch.arange(window_size, dtype=dtype, device=device) - window_size // 2
    g = torch.exp(-(coords**2) / (2 * sigma**2))
    g = (g / g.sum()).unsqueeze(1)
    win2d = (g @ g.t()).unsqueeze(0).unsqueeze(0)  # (1,1,W,W)
    return win2d.expand(channels, 1, window_size, window_size).contiguous()


def masked_ssim(pred, gt, mask, window_size: int = 11, sigma: float = 1.5) -> float:
    """Mean SSIM over ``mask`` using mask-NORMALIZED local moments.

    Local means/variances are ``conv(x*m)/conv(m)`` so a window straddling the
    static/dynamic boundary averages only static (in-mask) pixels. Dynamic content
    therefore never bleeds into a static SSIM score (verified by a boundary
    corruption test), fixing the naive full-image-convolution leak.
    """
    device = pred.device
    c, h, w = pred.shape
    m = _as_hw_bool(mask, (h, w), device)
    if not bool(m.any()):
        return float("nan")
    dtype = torch.float32
    x = pred.to(dtype).unsqueeze(0)
    y = gt.to(device=device, dtype=dtype).unsqueeze(0)
    mf = m.to(dtype).view(1, 1, h, w).expand(1, c, h, w)
    win = _gaussian_window(window_size, sigma, c, device, dtype)
    pad = window_size // 2

    def _f(a):
        return F.conv2d(a, win, padding=pad, groups=c)

    wm = _f(mf).clamp_min(1e-12)  # per-pixel valid (in-mask) window mass
    mu_x = _f(x * mf) / wm
    mu_y = _f(y * mf) / wm
    var_x = _f(x * x * mf) / wm - mu_x * mu_x
    var_y = _f(y * y * mf) / wm - mu_y * mu_y
    cov = _f(x * y * mf) / wm - mu_x * mu_y
    c1, c2 = 0.01**2, 0.03**2
    ssim_map = ((2 * mu_x * mu_y + c1) * (2 * cov + c2)) / (
        (mu_x * mu_x + mu_y * mu_y + c1) * (var_x + var_y + c2)
    )
    ssim_map = ssim_map.squeeze(0).mean(dim=0)  # (H, W), channel-averaged
    return float(ssim_map[m].mean().item())


def masked_lpips(pred, gt, mask, lpips_fn) -> float:
    """LPIPS with the non-static region replaced by GT in the prediction.

    Composite ``pred' = mask*pred + (~mask)*gt`` and compare to ``gt``: the dynamic
    region is then identical (== gt) in both inputs, contributing ~zero perceptual
    difference with no artificial black boundary. Method-independent (same op per
    arm), still an approximation (the network's receptive field spans the
    boundary). ``lpips_fn`` maps two ``(1, C, H, W)`` tensors in ``[0, 1]`` to a
    scalar tensor. Returns NaN when the static support is empty.
    """
    device = pred.device
    c, h, w = pred.shape
    m = _as_hw_bool(mask, (h, w), device)
    if not bool(m.any()):
        return float("nan")
    mf = m.view(1, h, w).to(pred.dtype)
    gt_d = gt.to(device)
    pred_c = mf * pred + (1.0 - mf) * gt_d
    return float(lpips_fn(pred_c.unsqueeze(0), gt_d.unsqueeze(0)).item())


def static_coverage(render_depth, mask, render_opacity=None, a_eval: float = 0.5) -> float:
    """Fraction of ``M_static`` actually filled by the arm.

    A pixel counts as covered iff rendered depth is finite & > 0 AND (if provided)
    rendered opacity >= ``a_eval``. Low coverage = holes; it is a first-class
    outcome so "fewer Gaussians" cannot win by leaving background empty.
    """
    device = render_depth.device if torch.is_tensor(render_depth) else "cpu"
    d = _as_hw_float(render_depth, device)
    m = _as_hw_bool(mask, d.shape, device)
    n = int(m.sum())
    if n == 0:
        return float("nan")
    filled = torch.isfinite(d) & (d > 0.0)
    if render_opacity is not None:
        if not (math.isfinite(a_eval) and 0.0 <= a_eval <= 1.0):
            raise ValueError("a_eval must be finite and in [0, 1]")
        filled = filled & (_as_hw_float(render_opacity, device) >= a_eval)
    return float((filled & m).sum().item()) / float(n)


def penalized_depth_l1_cm(pred_depth, gt_depth, mask, d_max_cm: float) -> float:
    """Hole-counting depth L1 (cm) over ``M_static``.

    ``|pred - gt|`` clamped to ``d_max``; a pixel with invalid/missing rendered
    depth is charged the full ``d_max`` (a hole is an error, not a skip).
    ``d_max_cm`` is dataset-fixed, NOT an arm-specific statistic.
    """
    device = gt_depth.device if torch.is_tensor(gt_depth) else "cpu"
    gt = _as_hw_float(gt_depth, device)
    m = _as_hw_bool(mask, gt.shape, device)
    n = int(m.sum())
    if n == 0:
        return float("nan")
    if not (math.isfinite(d_max_cm) and d_max_cm > 0):
        raise ValueError("d_max_cm must be finite and > 0")
    d_max_m = d_max_cm / 100.0
    pred = _as_hw_float(pred_depth, device)
    valid_pred = torch.isfinite(pred) & (pred > 0.0)
    err = torch.abs(pred - gt).clamp(max=d_max_m)
    err = torch.where(valid_pred, err, torch.full_like(err, d_max_m))
    return float(err[m].mean().item()) * 100.0


def static_background_metrics(
    pred_img,
    gt_img,
    pred_depth,
    gt_depth,
    dynamic_mask=None,
    render_opacity=None,
    *,
    d_max_cm: float = 50.0,
    a_eval: float = 0.5,
    lpips_fn=None,
) -> dict:
    """Bundle the hole-safe static-background metrics into one dict.

    ``dynamic_mask`` is the frozen, method-independent dynamic region. Returns
    ``mask_type='static'`` so callers can tag the mapping-raw row unambiguously.
    """
    mask = static_support_mask(gt_depth, dynamic_mask)
    out = {
        "mask_type": "static",
        "static_support_px": int(mask.sum()),
        "static_psnr": masked_psnr(pred_img, gt_img, mask),
        "static_ssim": masked_ssim(pred_img, gt_img, mask),
        "static_depth_l1_pen_cm": penalized_depth_l1_cm(
            pred_depth, gt_depth, mask, d_max_cm
        ),
        "static_coverage": static_coverage(
            pred_depth, mask, render_opacity=render_opacity, a_eval=a_eval
        ),
        "static_d_max_cm": d_max_cm,
        "static_opacity_a_eval": a_eval,
    }
    if lpips_fn is not None:
        out["static_lpips"] = masked_lpips(pred_img, gt_img, mask, lpips_fn)
    return out


def _dilate_bool(mask: torch.Tensor, radius_px: int) -> torch.Tensor:
    """Morphological dilation of a bool mask by a square kernel of ``radius_px``."""
    if radius_px <= 0:
        return mask
    m = mask.to(torch.float32)[None, None]
    k = 2 * radius_px + 1
    d = F.max_pool2d(m, kernel_size=k, stride=1, padding=radius_px)
    return d[0, 0] > 0.5


def dynamic_adjacent_band_mask(gt_depth, dynamic_mask, radius_px: int) -> torch.Tensor:
    """Static-GT pixels forming a ``radius_px`` ring around the dynamic region.

    ``band = dilate(dyn, r) AND (NOT dyn) AND (gt-depth valid & > 0)``. This is the
    boundary band the dynamic object abuts/sweeps -- exactly where insert-then-delete
    scars (prune) and baked-object colour bleed (immediate) surface, and where a
    hold-out-then-promote lifecycle (deferred) should win if it wins anywhere. ``dyn``
    is the frozen, method-INDEPENDENT GTMC dynamic mask (True where dynamic); the band
    is therefore identical for every arm. Returns ``(H, W)`` bool.
    """
    gt = _as_hw_float(gt_depth, gt_depth.device if torch.is_tensor(gt_depth) else "cpu")
    device = gt.device
    valid = torch.isfinite(gt) & (gt > 0.0)
    dyn = _as_hw_bool(dynamic_mask, gt.shape, device)
    ring = _dilate_bool(dyn, int(radius_px)) & (~dyn)
    return ring & valid


def dynamic_band_metrics(
    pred_img,
    gt_img,
    pred_depth,
    gt_depth,
    dynamic_mask,
    radii,
    *,
    d_max_cm: float = 50.0,
) -> dict:
    """Masked PSNR/SSIM/penalized-depth over the dynamic-adjacent band at each radius.

    Discriminating, hole-safe metric for the lifecycle ablation: the full static
    region washes out the effect, so restrict to the ring where the arms actually
    differ. One sub-dict per radius keyed ``band<r>``; ``support_px`` lets the caller
    weight/aggregate and flag empty bands.
    """
    out = {}
    for r in radii:
        mask = dynamic_adjacent_band_mask(gt_depth, dynamic_mask, r)
        n = int(mask.sum())
        out[f"band{int(r)}"] = {
            "support_px": n,
            "psnr": masked_psnr(pred_img, gt_img, mask) if n > 0 else float("nan"),
            "ssim": masked_ssim(pred_img, gt_img, mask) if n > 0 else float("nan"),
            "depth_l1_pen_cm": (
                penalized_depth_l1_cm(pred_depth, gt_depth, mask, d_max_cm)
                if n > 0
                else float("nan")
            ),
        }
    return out


def vacated_region_mask(gt_depth, current_dynamic, past_union_dynamic) -> torch.Tensor:
    """Ghost-contamination support: pixels the mover has VACATED.

    ``vacated = (∪ earlier frozen dynamic) AND (NOT dynamic now) AND (gt-depth
    valid)`` — some earlier frame saw the mover here, but the CURRENT frame sees
    true background (GT shows the revealed static surface). Residual "ghost"
    Gaussians — insert-then-delete scars (prune) or baked movers (immediate) —
    surface exactly here as rendering/depth error. Both masks are frozen
    method-INDEPENDENT GTMC masks (never the arm's own semantic mask), so the
    support is identical for every arm. Returns ``(H, W)`` bool.
    """
    gt = _as_hw_float(gt_depth, gt_depth.device if torch.is_tensor(gt_depth) else "cpu")
    device = gt.device
    valid = torch.isfinite(gt) & (gt > 0.0)
    dyn_now = _as_hw_bool(current_dynamic, gt.shape, device)
    past = _as_hw_bool(past_union_dynamic, gt.shape, device)
    return past & (~dyn_now) & valid


def vacated_region_metrics(
    pred_img,
    gt_img,
    pred_depth,
    gt_depth,
    current_dynamic,
    past_union_dynamic,
    *,
    d_max_cm: float = 50.0,
) -> dict:
    """Masked PSNR/SSIM/penalized-depth over the vacated (ghost) region.

    Hole-safe like the static row: a missing render inside the vacated region is
    charged ``d_max`` (a ghost hole is an error, not a skip). ``support_px``
    lets the caller skip frames where nothing has been vacated yet (e.g. the
    first frames of a sequence, before the mover has moved anywhere).
    """
    mask = vacated_region_mask(gt_depth, current_dynamic, past_union_dynamic)
    n = int(mask.sum())
    return {
        "vacated_support_px": n,
        "vacated_psnr": masked_psnr(pred_img, gt_img, mask) if n else float("nan"),
        "vacated_ssim": masked_ssim(pred_img, gt_img, mask) if n else float("nan"),
        "vacated_depth_l1_pen_cm": (
            penalized_depth_l1_cm(pred_depth, gt_depth, mask, d_max_cm)
            if n
            else float("nan")
        ),
    }


def vacated_contrast_metrics(
    pred_img,
    gt_img,
    pred_depth,
    gt_depth,
    current_dynamic,
    past_union_dynamic,
    *,
    d_max_cm: float = 50.0,
) -> dict:
    """Vacated region scored AGAINST its own frame's untouched static background.

    Why this exists. ``vacated_depth_l1_pen_cm`` alone is ~95% global map/pose
    quality: on Bonn balloon it runs 21–27 cm while the vacated-minus-static gap
    is only 0.1–1.3 cm, and the run-to-run noise band of the absolute number
    (measured on 7 null replicates in R2-P02-E2) is 1.0–3.3 cm. An absolute
    headline therefore cannot resolve an effect whose entire ceiling is smaller
    than its own noise — a method that perfectly erased every ghost could still
    score worse than a control that happened to track better.

    The contrast is the paired, within-frame difference

        ``ghost_excess = L1(vacated) - L1(static ∧ ¬vacated)``

    computed per frame and averaged over frames. Global drift, pose error and
    overall map quality hit both terms of each pair and cancel; what survives is
    "how much worse is the region the mover left than the background around it",
    which is the quantity the ghost claim is actually about. The complement is
    taken inside the SAME frozen-GTMC static support, so it stays
    method-independent and its support is identical across arms.
    """
    static = static_support_mask(gt_depth, current_dynamic)
    vac = vacated_region_mask(gt_depth, current_dynamic, past_union_dynamic)
    # `vacated` is already ¬dynamic-now ∧ valid-GT, i.e. a subset of the static
    # support; the complement is the rest of that support.
    nonvac = static & (~vac)
    n_vac, n_non = int(vac.sum()), int(nonvac.sum())
    out = {
        "vacated_support_px": n_vac,
        "nonvacated_support_px": n_non,
        "nonvacated_psnr": masked_psnr(pred_img, gt_img, nonvac) if n_non else float("nan"),
        "nonvacated_depth_l1_pen_cm": (
            penalized_depth_l1_cm(pred_depth, gt_depth, nonvac, d_max_cm)
            if n_non
            else float("nan")
        ),
    }
    if n_vac and n_non:
        vac_depth = penalized_depth_l1_cm(pred_depth, gt_depth, vac, d_max_cm)
        out["ghost_excess_depth_l1_cm"] = vac_depth - out["nonvacated_depth_l1_pen_cm"]
        # PSNR is already logarithmic, so the paired contrast is a dB difference
        # (negative = the vacated region renders WORSE than its own background).
        out["ghost_excess_psnr_db"] = (
            masked_psnr(pred_img, gt_img, vac) - out["nonvacated_psnr"]
        )
    else:
        out["ghost_excess_depth_l1_cm"] = float("nan")
        out["ghost_excess_psnr_db"] = float("nan")
    return out
