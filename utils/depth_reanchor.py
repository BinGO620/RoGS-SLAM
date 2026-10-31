"""Periodic map-depth re-anchoring (depth_reanchor, D1 — 2026-09-09).

Diagnosis (results/submap_lcd/evidence/scale_drift_diagnosis.md): map depth
oscillates +-20-30% on sequence timescales (bootstrap coupling between the
Gaussians committed at drifted poses and the tracking that aligns to the
drifting map), and the trajectory scale follows. Fix: every N keyframes,
render depth at the CURRENT keyframe pose, take the robust median of
sensor/render over confident static pixels, and rescale the VISIBLE
Gaussians along their viewing rays by a clamped step toward the metric
sensor depth.

Config (DepthReanchor): enabled, period_kf, conf_percentile, max_step.
Defaults off — existing experiments are bit-identical.
"""
import numpy as np
import torch
from gaussian_splatting.gaussian_renderer import render


def depth_reanchor_enabled(config):
    return bool(config.get("DepthReanchor", {}).get("enabled", False))


class DepthReanchorer:
    """Stateful re-anchor step, called from the backend after map() on every
    `period_kf`-th keyframe. Logs (round brackets — rich Console mangles
    square ones) the applied ratio for the mechanism-readout time profile."""

    def __init__(self, config):
        cfg = config.get("DepthReanchor", {})
        self.period_kf = int(cfg.get("period_kf", 5))
        self.conf_percentile = float(cfg.get("conf_percentile", 40))
        self.max_step = float(cfg.get("max_step", 0.05))
        self.kf_count = 0
        self.last_kf = None
        self.history = []  # (kf_idx, ratio) — mechanism readout

    def maybe_reanchor(self, kf_idx, viewpoint, backend):
        """Call after a backend map() pass. Returns True if a step applied.
        Counts KEYFRAMES (kf_idx), not map() calls — one map() may run many
        iterations on the same newest KF."""
        if self.last_kf is not None and kf_idx == self.last_kf:
            return False  # same newest KF as the previous map() call
        self.last_kf = kf_idx
        self.kf_count += 1
        if self.kf_count % self.period_kf != 0:
            return False

        with torch.no_grad():
            render_pkg = render(viewpoint, backend.gaussians,
                                backend.pipeline_params, backend.background)
        rd = render_pkg["depth"].squeeze()  # (H,W) rendered depth
        conf = render_pkg["opacity"].squeeze()
        sd = torch.as_tensor(viewpoint.depth, device=rd.device,
                             dtype=rd.dtype).squeeze()
        if sd.shape != rd.shape:
            import torch.nn.functional as F
            sd = F.interpolate(sd[None, None], size=rd.shape[-2:],
                               mode="nearest").squeeze()
        dyn = getattr(viewpoint, "dynamic_mask", None)
        static = torch.ones_like(sd)
        if dyn is not None:
            m = dyn.detach().to(rd.device).float()
            if m.dim() == 3:
                m = m.squeeze(0)
            if m.shape != sd.shape:
                import torch.nn.functional as F
                m = F.interpolate(m[None, None], size=sd.shape[-2:],
                                  mode="nearest").squeeze()
            static = 1.0 - m

        valid = ((sd > 0.05) & (sd < 6.0) & torch.isfinite(sd)
                 & torch.isfinite(rd) & (rd > 0.05)
                 & (conf > 0.5) & (static > 0.5))
        if valid.sum() < 500:
            return False
        ratio = float((sd[valid] / rd[valid]).median().item())
        if not np.isfinite(ratio) or ratio <= 0:
            return False

        # clamped log-space step: ratio > 1 (map too close) -> push out
        step = float(np.clip(np.log(ratio), -self.max_step, self.max_step))
        scale = float(np.exp(step))

        # Rescale VISIBLE Gaussians along the viewing ray of this keyframe:
        # world_x_new = cam_center + scale * (world_x - cam_center)
        # This moves each Gaussian along its ray from the camera, exactly
        # the degree of freedom the depth ratio observes.
        R = viewpoint.R.detach().to(dtype=torch.float32)  # world->cam
        t = viewpoint.T.detach().to(dtype=torch.float32)
        # camera center in world: C = -R^T t
        C = (-R.T @ t.reshape(3, 1)).reshape(1, 3)
        xyz = backend.gaussians._xyz
        vis = render_pkg["visibility_filter"]
        if vis.sum() == 0:
            return False
        idx = torch.where(vis)[0]
        Cf = C.to(device=xyz.device, dtype=xyz.dtype)
        scale_t = torch.tensor(scale, dtype=xyz.dtype, device=xyz.device)
        log_step_t = torch.tensor(np.log(scale), dtype=backend.gaussians._scaling.dtype,
                                  device=backend.gaussians._scaling.device)
        new_xyz = Cf + scale_t * (xyz[idx] - Cf)
        with torch.no_grad():
            backend.gaussians._xyz[idx] = new_xyz.to(xyz.dtype)
            # scales must follow the same radial factor to keep shapes
            backend.gaussians._scaling[idx] = backend.gaussians._scaling[idx] + log_step_t

        self.history.append((int(kf_idx), ratio, scale))
        from utils.logging_utils import Log
        Log(f"DepthReanchor kf={kf_idx}: ratio={ratio:.3f} step={scale:.4f} "
            f"n_gauss={int(vis.sum())}")
        return True
