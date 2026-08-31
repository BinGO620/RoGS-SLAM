"""R2-P02 Fork B: alpha-driven EXIT + FILL lifecycle (mapping side).

`alpha` == per-Gaussian static-world trust in [0,1]. It REUSES the existing,
fully-plumbed `GaussianModel.static_prob` tensor (and `static_obs_count` as the
persistence counter) -- no new per-Gaussian field is introduced. This module is
the *exit* and *fill* half of the entry-exit-fill loop; the hard deferred ENTRY
(candidate isolation, `Mapping.lifecycle_mode: deferred`) is unchanged. That
split is the whole point of Fork B: deferred lost the vacated-region ghost 0/5
because it only gates entry; alpha here drives the missing exit + fill.

Everything that decides WHICH Gaussians to reset/carve and WHERE to fill is a
pure tensor function taking plain (u, v, z, depth, alpha, ...) arrays, so the
geometry is unit-testable on CPU with no rasterizer. The backend wiring
(`slam_backend`) extracts those arrays from a viewpoint + a fresh render and
calls into here; it owns nothing but plumbing.

Mechanisms (each with a literature anchor, see the pre-registration):
  - select_reset_mask   : mechanism A, targeted opacity-reset of low-alpha
                          occluders that hide the observed background (LPM).
  - select_carve_mask   : mechanism B, free-space carving of PERSISTENT low-alpha
                          floaters in front of the observed surface (MAGS). The
                          persistence gate (static_obs_count >= min_obs) is what
                          makes exit robust to the single-frame MAD-collapse that
                          blew up the raw reliability signal (mv_no_box2 +435%).
  - plan_fill_points    : mechanism C, KD-tree background recovery in vacated
                          pixels (GGD).

alpha protects static structure: reset/carve fire ONLY on low alpha, so a static
Gaussian that is momentarily occluded is never deleted -- the failure mode plain
`prune` has.
"""

from dataclasses import dataclass

import numpy as np
import torch

# ---- lifecycle modes (arms) -------------------------------------------------
# off        -> arm B (passive deferred; this module is a no-op, byte-identical)
# observe    -> arm C (accumulate alpha from evidence, take NO action; placebo)
# exit       -> arm D (alpha update + opacity-reset + free-space carve)
# exit_fill  -> arm E (arm D + KD-tree background fill; the full method)
MODE_OFF = "off"
MODE_OBSERVE = "observe"
MODE_EXIT = "exit"
MODE_EXIT_FILL = "exit_fill"
_MODES = (MODE_OFF, MODE_OBSERVE, MODE_EXIT, MODE_EXIT_FILL)


@dataclass(frozen=True)
class AlphaLifecycleParams:
    """Thresholds for the exit/fill passes, read from the AlphaLifecycle block."""

    mode: str = MODE_OFF
    ema_beta: float = 0.9
    # per-pixel dynamic-evidence depth band (robust; NOT reliability s(x))
    evidence_band_abs_m: float = 0.05
    evidence_band_rel: float = 0.02
    # mechanism A: opacity-reset
    tau_reset: float = 0.35
    delta_occlude_m: float = 0.05
    reset_value: float = 0.01
    # mechanism B: free-space carve
    tau_carve: float = 0.20
    delta_free_m: float = 0.10
    min_obs_count: float = 3.0
    # T3: semantic alpha override (None => off, byte-identical to R2-P02 arm D)
    semantic_alpha_override: float = None
    semantic_override_delta_m: float = 0.10
    # mechanism C: fill
    fill_k: int = 8
    fill_band_abs_m: float = 0.10
    fill_band_rel: float = 0.03
    fill_min_opacity: float = 0.5
    fill_max_points: int = 2000

    @property
    def updates_alpha(self):
        return self.mode in (MODE_OBSERVE, MODE_EXIT, MODE_EXIT_FILL)

    @property
    def does_exit(self):
        return self.mode in (MODE_EXIT, MODE_EXIT_FILL)

    @property
    def does_fill(self):
        return self.mode == MODE_EXIT_FILL

    @property
    def does_semantic_override(self):
        """T3 fires only inside an EXIT arm: the override is a shortcut through the
        ledger toward reset/carve, so in `observe` (the placebo arm) it would change
        alpha without any pass able to act on it -- a silent confound, not an ablation.
        """
        return self.does_exit and self.semantic_alpha_override is not None


def get_alpha_lifecycle_config(config):
    return (config or {}).get("AlphaLifecycle", {}) or {}


def alpha_lifecycle_mode(config):
    """Validated lifecycle mode string. Absent block -> off (arm B parity)."""
    mode = str(get_alpha_lifecycle_config(config).get("mode", MODE_OFF)).lower()
    if mode not in _MODES:
        raise ValueError(
            f"AlphaLifecycle.mode must be one of {_MODES}, got {mode!r}"
        )
    return mode


def alpha_lifecycle_active(config):
    """True when the exit/fill lifecycle should run at all (mode != off)."""
    return alpha_lifecycle_mode(config) != MODE_OFF


def read_alpha_lifecycle_params(config):
    cfg = get_alpha_lifecycle_config(config)
    d = AlphaLifecycleParams()  # defaults
    delta_free_m = float(cfg.get("delta_free_m", d.delta_free_m))
    override = cfg.get("semantic_alpha_override", d.semantic_alpha_override)
    return AlphaLifecycleParams(
        mode=alpha_lifecycle_mode(config),
        ema_beta=float(cfg.get("ema_beta", d.ema_beta)),
        evidence_band_abs_m=float(cfg.get("evidence_band_abs_m", d.evidence_band_abs_m)),
        evidence_band_rel=float(cfg.get("evidence_band_rel", d.evidence_band_rel)),
        tau_reset=float(cfg.get("tau_reset", d.tau_reset)),
        delta_occlude_m=float(cfg.get("delta_occlude_m", d.delta_occlude_m)),
        reset_value=float(cfg.get("reset_value", d.reset_value)),
        tau_carve=float(cfg.get("tau_carve", d.tau_carve)),
        delta_free_m=delta_free_m,
        min_obs_count=float(cfg.get("min_obs_count", d.min_obs_count)),
        semantic_alpha_override=(None if override is None else float(override)),
        # defaults to delta_free_m (the CARVE band, 0.10 m) rather than
        # delta_occlude_m (0.05 m): the override must be at least as conservative
        # as the strictest geometry gate it can trigger.
        semantic_override_delta_m=float(
            cfg.get("semantic_override_delta_m", delta_free_m)
        ),
        fill_k=int(cfg.get("fill_k", d.fill_k)),
        fill_band_abs_m=float(cfg.get("fill_band_abs_m", d.fill_band_abs_m)),
        fill_band_rel=float(cfg.get("fill_band_rel", d.fill_band_rel)),
        fill_min_opacity=float(cfg.get("fill_min_opacity", d.fill_min_opacity)),
        fill_max_points=int(cfg.get("fill_max_points", d.fill_max_points)),
    )


# ---- projection / sampling --------------------------------------------------


def project_gaussians_to_view(xyz, world_view_transform, fx, fy, cx, cy, height, width):
    """Project world Gaussian centers to pixel (u, v) + camera-frame depth z.

    Mirrors EXACTLY the convention already used by
    ``utils.static_prob.update_static_prob_from_evidence`` (row-vector:
    ``cam = [x, y, z, 1] @ world_view_transform``), so visibility here agrees
    with the tracking-side static_prob splat. Returns ``(u, v, z, valid)`` with
    ``valid`` = positive depth AND inside the image.
    """
    xyz = xyz if torch.is_tensor(xyz) else torch.as_tensor(xyz, dtype=torch.float32)
    device, dtype = xyz.device, xyz.dtype
    wvt = torch.as_tensor(world_view_transform, device=device, dtype=dtype)
    ones = torch.ones((xyz.shape[0], 1), dtype=dtype, device=device)
    cam = torch.cat((xyz, ones), dim=1) @ wvt
    z = cam[:, 2]
    zc = torch.clamp(z, min=1e-6)
    u = fx * (cam[:, 0] / zc) + cx
    v = fy * (cam[:, 1] / zc) + cy
    valid = (z > 0.01) & (u >= 0) & (u < width) & (v >= 0) & (v < height)
    return u, v, z, valid


def sample_map_at_gaussians(field_hw, u, v, valid, height, width):
    """Nearest-pixel gather of a dense (H,W) field at each Gaussian's (u, v).

    Invalid Gaussians read the clamped corner but are meant to be masked out by
    the caller via ``valid``; the returned value at invalid entries is unused.
    """
    field = field_hw.squeeze()
    uu = torch.clamp(torch.as_tensor(u).round().long(), 0, width - 1)
    vv = torch.clamp(torch.as_tensor(v).round().long(), 0, height - 1)
    return field.to(dtype=torch.float32)[vv, uu]


# ---- per-pixel dynamic evidence (robust; NOT reliability s(x)) ---------------


def depth_inconsistency_evidence(
    rendered_depth, observed_depth, band_abs_m=0.05, band_rel=0.02
):
    """Per-pixel dynamic evidence in [0,1] from a FIXED depth band.

    Deliberately geometric and band-based, not the MAD-normalized reliability
    ``s(x)`` (which collapses to noise-saturation on near-static frames, the
    mv_no_box2 +435% footgun). Evidence is 0 within ``band_abs + band_rel*z`` of
    the observed depth and rises smoothly beyond it; pixels without a valid
    observation return 0 evidence (no news == static, never a delete trigger).

    Returns ``(evidence_hw, valid_hw)`` both (H,W).
    """
    r = rendered_depth.squeeze().to(dtype=torch.float32)
    o = observed_depth.squeeze().to(dtype=torch.float32)
    valid = torch.isfinite(r) & torch.isfinite(o) & (o > 0.01) & (r > 0.01)
    band = torch.clamp(band_abs_m + band_rel * torch.clamp(o, min=0.0), min=1e-6)
    excess = torch.clamp((r - o).abs() / band - 1.0, min=0.0)
    evidence = 1.0 - torch.exp(-excess)
    evidence = torch.where(valid, evidence, torch.zeros_like(evidence))
    return evidence, valid


def ema_alpha_update(alpha, obs_count, evidence_per_gaussian, update_mask, beta):
    """EMA each updated Gaussian's alpha toward ``static_obs = 1 - evidence`` and
    bump its observation counter. Pure; returns ``(alpha_new, obs_count_new)``.

    Static evidence (low dynamic evidence) pulls alpha -> 1; persistent dynamic
    evidence pulls it -> 0. Only ``update_mask`` entries move (visible + valid).
    """
    alpha = alpha.clone()
    obs_count = obs_count.clone()
    m = update_mask
    if m.any():
        static_obs = torch.clamp(1.0 - evidence_per_gaussian[m], 0.0, 1.0)
        alpha[m] = beta * alpha[m] + (1.0 - beta) * static_obs
        obs_count[m] = obs_count[m] + 1.0
    return alpha.clamp(0.0, 1.0), obs_count


# ---- exit selection ---------------------------------------------------------


def select_reset_mask(
    z, obs_at_gauss, alpha, valid, tau_reset, delta_occlude_m
):
    """Mechanism A (LPM opacity-reset): low-alpha Gaussians that sit in FRONT of
    the observed surface by more than ``delta_occlude`` -- i.e. they occlude the
    true background. Resetting their opacity (reversibly) lets the background be
    re-optimized. Static structure is protected by the ``alpha < tau_reset`` gate.
    """
    obs_ok = torch.isfinite(obs_at_gauss) & (obs_at_gauss > 0.01)
    in_front = z < (obs_at_gauss - delta_occlude_m)
    return valid & obs_ok & in_front & (alpha < tau_reset)


def select_carve_mask(
    z, obs_at_gauss, alpha, obs_count, valid, tau_carve, delta_free_m, min_obs_count
):
    """Mechanism B (MAGS free-space carving): PERSISTENT low-alpha floaters
    clearly in front of the observed surface (by > ``delta_free`` >
    ``delta_occlude``) get hard-pruned. The ``obs_count >= min_obs`` persistence
    gate is the robustness lever: a Gaussian must be seen-and-inconsistent across
    several keyframes before deletion, so a single-frame evidence spike (MAD
    collapse) can never carve real geometry.
    """
    obs_ok = torch.isfinite(obs_at_gauss) & (obs_at_gauss > 0.01)
    in_front = z < (obs_at_gauss - delta_free_m)
    persistent = obs_count.squeeze() >= min_obs_count
    return valid & obs_ok & in_front & (alpha < tau_carve) & persistent


def select_semantic_override_mask(z, obs_at_gauss, semantic_hit, valid, delta_m):
    """T3: Gaussians a SEMANTIC dynamic mask hits AND that sit strictly in FRONT of
    the observed surface by more than ``delta_m``. Their alpha is overwritten
    outright instead of being walked down by the EMA.

    WHY an override at all: ``ema_beta=0.9`` means alpha falls as ``1 - 0.9^k``, so a
    Gaussian born on a walking person needs ~4 keyframes to cross ``tau_reset=0.35``
    and ~7 to cross ``tau_carve=0.20``. During that window it is a live occluder. When
    a semantic mask is present it already knows on frame 1 what the ledger takes 7
    keyframes to infer.

    WHY the geometry conjunct is load-bearing and not belt-and-braces: a person who is
    SITTING STILL is the observed surface -- ``z ~= obs_at`` -- so ``in_front`` is
    False and the override cannot touch them. Semantics alone would delete the static
    structure a stationary person legitimately contributes to the map, which is the
    exact failure that makes naive mask-everything pipelines lose the scene. The gate
    also absorbs mask dilation: an over-grown mask boundary that spills onto the wall
    behind the person lands AT the observed surface, not in front of it.

    ``delta_m`` defaults to ``delta_free_m`` (0.10 m), i.e. stricter than
    ``select_reset_mask``'s ``delta_occlude_m`` (0.05 m), so the override set is a
    subset of the geometry the reset pass already considers occluding.

    A false positive is self-limiting rather than permanent: the next keyframe that
    sees the Gaussian with static evidence feeds ``ema_alpha_update`` again, so alpha
    recovers as ``1 - 0.9^k`` -- above ``tau_carve`` after 3 keyframes and above
    ``tau_reset`` after 5. The unrecoverable case is a hard prune, and that still needs
    ``obs_count >= min_obs_count`` from ``select_carve_mask``.
    """
    obs_ok = torch.isfinite(obs_at_gauss) & (obs_at_gauss > 0.01)
    in_front = z < (obs_at_gauss - delta_m)
    return valid & obs_ok & in_front & semantic_hit.to(dtype=torch.bool)


# ---- fill (background recovery) ---------------------------------------------


def detect_vacated_pixels(
    pre_depth,
    pre_opacity,
    post_opacity,
    observed_depth,
    band_abs_m=0.10,
    band_rel=0.03,
    min_opacity=0.5,
    return_diagnostics=False,
):
    """Boolean (H,W) mask of pixels VACATED BY THE EXIT PASS -- the fill targets.

    Option A (fill coupled to the exit delta): a pixel is vacated iff BEFORE exit
    the map rendered an opaque near surface occluding the observed background
    (``pre_opacity >= min_opacity`` AND ``observed`` sits a band behind the
    pre-exit rendered depth), AND AFTER exit that near occluder is GONE
    (``post_opacity < min_opacity``, i.e. carve/reset opened a hole there).

    Coupling fill to the exit delta is the whole fix: fill fires only where exit
    actually removed coverage, so fill == 0 whenever exit == 0 and no Gaussian is
    ever seeded BEHIND a still-present ghost (the post-carve-only detector's
    per-KF re-fill bloat, the mechanism-C footgun). ``pre_depth`` (the near
    occluder, not the post-exit hole depth) is the surface to test occlusion.

    ``return_diagnostics`` additionally returns per-conjunct pixel counts. An empty
    result here is AMBIGUOUS without them: "fill is broken" and "exit opened no
    hole, so there is correctly nothing to fill" produce the identical zero. That
    ambiguity is what let an inert mechanism reach make-or-break in R2-P02-E2
    (`r2_p02_e2.md` §2a: zero `alpha-fill` lines, cause unattributable), and the
    exit pass got its per-conjunct `alpha-ledger` readout for exactly this reason
    while fill did not. ``now_cleared`` is the discriminating conjunct: >0 with
    ``vacated``==0 means the cleared pixels were not occluding anything, whereas
    ==0 means the re-render still shows an opaque surface everywhere -- reset
    knocked per-Gaussian opacity down but the accumulated alpha stayed above
    ``min_opacity`` (other Gaussians still cover those rays).
    """
    r0 = pre_depth.squeeze().to(dtype=torch.float32)
    op0 = pre_opacity.squeeze().to(dtype=torch.float32)
    op1 = post_opacity.squeeze().to(dtype=torch.float32)
    o = observed_depth.squeeze().to(dtype=torch.float32)
    band = band_abs_m + band_rel * torch.clamp(r0, min=0.0)
    valid = torch.isfinite(r0) & torch.isfinite(o) & (o > 0.01) & (r0 > 0.01)
    pre_occluded = (op0 >= min_opacity) & (o > (r0 + band))
    now_cleared = op1 < min_opacity
    vacated = valid & pre_occluded & now_cleared
    if not return_diagnostics:
        return vacated
    diagnostics = {
        "n_px": int(valid.numel()),
        "n_valid": int(valid.sum()),
        "n_pre_occluded": int((valid & pre_occluded).sum()),
        "n_now_cleared": int((valid & now_cleared).sum()),
        "n_vacated": int(vacated.sum()),
        "op1_min": float(op1.min()) if op1.numel() else float("nan"),
        "op1_mean": float(op1.mean()) if op1.numel() else float("nan"),
    }
    return vacated, diagnostics


def plan_fill_points(
    pixels_uv,
    depth_at_pixels,
    cam_to_world,
    fx,
    fy,
    cx,
    cy,
    neighbor_xyz,
    neighbor_color,
    k=8,
    max_points=2000,
):
    """Mechanism C (GGD KD-tree fill): backproject vacated pixels to world at the
    observed depth, then colour each from its ``k`` nearest STATIC (high-alpha)
    neighbours. Returns ``(world_xyz (M,3), color (M,3))`` ready for the standard
    candidate insertion path (same world frame as ``insert_candidate_gaussians``:
    column convention ``world = cam_to_world @ [xc, yc, zc, 1]``).

    Neighbour search is a deterministic ``torch.cdist`` + ``topk`` (no scipy, no
    RNG). Empty inputs -> empty outputs.
    """
    uv = torch.as_tensor(pixels_uv, dtype=torch.float32).reshape(-1, 2)
    d = torch.as_tensor(depth_at_pixels, dtype=torch.float32).reshape(-1)
    if uv.shape[0] == 0 or neighbor_xyz is None or neighbor_xyz.shape[0] == 0:
        return uv.new_zeros((0, 3)), uv.new_zeros((0, 3))

    if uv.shape[0] > max_points:
        keep = torch.linspace(0, uv.shape[0] - 1, max_points).round().long().unique()
        uv, d = uv[keep], d[keep]

    u, v = uv[:, 0], uv[:, 1]
    xc = (u - cx) / fx * d
    yc = (v - cy) / fy * d
    cam = torch.stack([xc, yc, d, torch.ones_like(d)], dim=0)  # (4, M)
    c2w = torch.as_tensor(cam_to_world, dtype=torch.float32)
    world = (c2w @ cam)[:3].transpose(0, 1).contiguous()  # (M, 3)

    nbr_xyz = torch.as_tensor(neighbor_xyz, dtype=torch.float32)
    nbr_col = torch.as_tensor(neighbor_color, dtype=torch.float32)
    kk = int(min(k, nbr_xyz.shape[0]))
    dist = torch.cdist(world, nbr_xyz)  # (M, Nn)
    nn_idx = torch.topk(dist, kk, dim=1, largest=False).indices  # (M, k)
    color = nbr_col[nn_idx].mean(dim=1)  # (M, 3)

    finite = torch.isfinite(world).all(dim=1) & torch.isfinite(color).all(dim=1)
    return world[finite].contiguous(), color[finite].clamp(0.0, 1.0).contiguous()


def as_numpy_pixels(mask_hw):
    """(H,W) bool mask -> (u_array, v_array) int pixel coords of set entries."""
    m = mask_hw.squeeze()
    vv, uu = torch.nonzero(m, as_tuple=True)
    return uu.detach().cpu().numpy().astype(np.int64), vv.detach().cpu().numpy().astype(
        np.int64
    )
