"""World-space mask-stability ledger (mask_fix_iter, 2026-09-12).

Problem being fixed (DISCIPLINE #11 mechanism failure, f3_st_hf class):
``SemanticMask.mask_mapping``/``mask_insertion`` unconditionally exclude
semantic-person pixels from mapping and insertion. On slow-motion sequences
the person sits still for the whole take, so the masked screen region never
enters the map -- a permanent hole in the middle of the view that degrades
tracking (gate s0 frame-0 APE 50.9cm on f3_st_hf; v1 p9 2.15/2.39 after
removing the related gating).

Mechanism: a coarse WORLD-space voxel ledger. Each keyframe, masked pixels
are unprojected (current refined pose + depth) into voxels; a voxel whose
masked-hit ratio stays high over enough observations is a *world-static
person region* and its pixels are RELEASED back to mapping/insertion for
this keyframe. Voxels that show up masked only sporadically (a person
actually moving through) never cross the threshold and stay excluded.
Image-space stability is unusable here -- the camera orbits the person on
f3_sitting_halfsphere, so image coordinates drift even for a statue.

Design constraints:
- Single integration point: the caller overwrites the cached
  ``viewpoint.dynamic_mask`` with the released mask BEFORE the insertion
  gate and the backend mapping loss read it, so both consumers inherit the
  release without knowing the ledger exists.
- ``enabled=false`` (default) keeps the run byte-identical to HEAD: the
  ledger is never constructed and no code path changes.
- Class-agnostic by construction (DISCIPLINE #8): the ledger never looks at
  semantics -- it only measures where the mask has been stable in the world.

Config (``MaskStability`` block; all thresholds are sequence-independent):
  enabled: bool (default false)
  voxel_size: float, metres (default 0.05)
  ema_gamma: float, per-keyframe count decay in (0,1) (default 0.97)
  score_thresh: float, masked/seen EMA ratio to release a voxel (default 0.6)
  min_seen: int, EMA seen-observations before a voxel is eligible (default 8)
  stride: int, pixel subsampling for the "seen" unprojection (default 4)
  log_interval: int, keyframes between release-stat log lines (default 50)
  release_rule: "ema" (v1, default) | "runlen" (v2, 2026-09-13 preregistered)
  runlen_min: int, consecutive masked observations to release under "runlen"
    (default 50). Rationale (results/mask_fix_iter/evidence/verdict_c4.md
    revised verdict): harm tracks EARLY release bursts at pause onsets
    (balloon kf10-13 37% burst, pauses are 4-10 kf); requiring a long
    unbroken masked run suppresses pause-driven releases entirely while a
    sequence-static person (f3_st_hf) still accumulates the run every kf.
"""

import torch

from utils.logging_utils import Log


class MaskStabilityLedger:
    def __init__(self, config):
        ms = config.get("MaskStability", {}) or {}
        self.enabled = bool(ms.get("enabled", False))
        self.voxel_size = float(ms.get("voxel_size", 0.05))
        self.gamma = float(ms.get("ema_gamma", 0.97))
        self.score_thresh = float(ms.get("score_thresh", 0.6))
        self.min_seen = float(ms.get("min_seen", 8.0))
        self.stride = int(ms.get("stride", 4))
        self.log_interval = int(ms.get("log_interval", 50))
        self.release_rule = str(ms.get("release_rule", "ema"))
        assert self.release_rule in ("ema", "runlen"), self.release_rule
        self.runlen_min = int(ms.get("runlen_min", 50))
        # Vectorised voxel table (2026-09-13): the original python-dict loop
        # cost 155-600ms PER KEYFRAME at crowd scale and measurably perturbs
        # the async frontend/backend cadence (crowd +16-50% with ZERO
        # releases; see verdict_c4.md rpx section). Same state machine,
        # tensor ops: sorted key index + (masked_ema, seen_ema, run) table.
        # ``run`` = current unbroken run of masked observations (runlen only).
        self._keys = torch.zeros(0, dtype=torch.int64)
        self._state = torch.zeros(0, 3, dtype=torch.float32)
        self._dev = None          # set on first update (ledger lives on the
        self._mesh = None         # observation device; no host round-trips)
        self.n_updates = 0
        self.n_released_px = 0

    # ------------------------------------------------------------------ api
    def release_mask(self, viewpoint, dynamic_mask):
        """Update the ledger with this keyframe and return a boolean mask of
        the SAME shape as ``dynamic_mask``: True where the currently-masked
        pixel belongs to a world-stable voxel and should be given back to
        mapping/insertion. Caller does ``effective = dynamic_mask & ~release``.

        ``dynamic_mask``: (H, W) bool tensor on any device.
        """
        if not self.enabled:
            return torch.zeros_like(dynamic_mask)
        H, W = dynamic_mask.shape[-2:]
        device = dynamic_mask.device
        depth = viewpoint.depth
        if depth is None:
            return torch.zeros_like(dynamic_mask)
        if not isinstance(depth, torch.Tensor):
            import numpy as np
            depth = torch.from_numpy(np.ascontiguousarray(depth)).float()
        depth = depth.detach().to(dynamic_mask.device).float().reshape(-1)
        # The ledger runs entirely on CPU (per-keyframe, small arrays); the
        # caller may hand us CUDA tensors, so normalise everything here.
        fx, fy = float(viewpoint.fx), float(viewpoint.fy)
        cx, cy = float(viewpoint.cx), float(viewpoint.cy)

        dev = dynamic_mask.device
        if self._mesh is None or self._mesh[0] != (H, W, dev):
            yy, xx = torch.meshgrid(
                torch.arange(H, device=dev, dtype=torch.float32),
                torch.arange(W, device=dev, dtype=torch.float32),
                indexing="ij",
            )
            self._mesh = ((H, W, dev), xx.reshape(-1), yy.reshape(-1))
        xs, ys = self._mesh[1], self._mesh[2]
        R = viewpoint.R.detach().to(dev).float()
        T = viewpoint.T.detach().to(dev).float()

        # Unproject every strided valid-depth pixel (the "seen" evidence set).
        valid = depth > 0
        v_idx = torch.nonzero(valid, as_tuple=False).reshape(-1)
        if self.stride > 1:
            v_idx = v_idx[:: self.stride]
        seen_vox = None
        if v_idx.numel() > 0:
            seen_vox = self._unproject_to_voxel(
                xs[v_idx], ys[v_idx], depth[v_idx], viewpoint
            )

        # Masked pixels (full resolution -- these are the decision pixels).
        mask_flat = dynamic_mask.detach().reshape(-1)
        m_idx = torch.nonzero(mask_flat, as_tuple=False).reshape(-1)
        mask_vox = None
        if m_idx.numel() > 0:
            mask_vox = self._unproject_to_voxel(
                xs[m_idx], ys[m_idx], depth[m_idx], viewpoint
            )

        self._update_counts(seen_vox, mask_vox)
        self.n_updates += 1

        release = torch.zeros_like(dynamic_mask)
        if mask_vox is None or mask_vox.numel() == 0:
            return release

        uniq, inv = torch.unique(mask_vox, return_inverse=True)
        pos = torch.searchsorted(self._keys, uniq)
        pos = pos.clamp(max=self._keys.numel() - 1)
        found = self._keys[pos] == uniq
        if self.release_rule == "runlen":
            runs = torch.where(found, self._state[pos, 2], torch.zeros_like(pos, dtype=torch.float32))
            hits = runs >= self.runlen_min
        else:
            e0 = torch.where(found, self._state[pos, 0], torch.full_like(pos, -1.0, dtype=torch.float32))
            e1 = torch.where(found, self._state[pos, 1], torch.zeros_like(pos, dtype=torch.float32))
            eligible = found & (e1 >= self.min_seen)
            hits = eligible & (e0 / e1.clamp(min=1e-12) >= self.score_thresh)
        rel_flat = torch.zeros(H * W, dtype=torch.bool, device=dev)
        rel_flat[m_idx] = hits[inv]
        release_flat = rel_flat.reshape(H, W)
        n_rel = int(release_flat.sum().item())
        self.n_released_px += n_rel
        if self.log_interval and self.n_updates % self.log_interval == 0:
            Log(
                f"MaskStability kf-update {self.n_updates}: masked {m_idx.numel()} px, "
                f"released {n_rel} px, ledger voxels {self._keys.numel()}"
            )
        return release_flat.to(device)

    # ------------------------------------------------------------- internals
    def _unproject_to_voxel(self, xs, ys, z, viewpoint):
        """Pixels + depth + current estimated pose -> integer voxel keys.

        Convention note: Camera (R, T) stores the WORLD-TO-CAMERA pose (the
        repo's insertion path wraps it with getWorld2View2 then inverts to
        C2W before unprojecting) -- mirror that here, or the person's voxels
        scatter as the camera orbits and nothing ever stabilises.
        """
        R = viewpoint.R.detach().to(z.device).float()
        T = viewpoint.T.detach().to(z.device).float()
        x_cam = (xs - viewpoint.cx) / viewpoint.fx * z
        y_cam = (ys - viewpoint.cy) / viewpoint.fy * z
        pts_cam = torch.stack([x_cam, y_cam, z, torch.ones_like(z)], dim=-1)  # (N, 4)
        W2C = torch.eye(4, dtype=torch.float32, device=z.device)
        W2C[:3, :3] = R
        W2C[:3, 3] = T
        C2W = torch.linalg.inv(W2C)
        pts_w = (C2W @ pts_cam.T).T[:, :3]
        vox = torch.div(pts_w, self.voxel_size, rounding_mode="floor").to(torch.int64)
        return vox[:, 0] * 4194304 + vox[:, 1] * 2048 + vox[:, 2]

    def _update_counts(self, seen_vox, mask_vox):
        """Vectorised merge of one keyframe's observations into the table.

        Replicates the original dict state machine exactly:
          new via seen      -> [e0=0, e1=1, run=0]
          new via mask only -> [e0=1, e1=g, run=1]
          existing + seen   -> e1 = e1*g + 1; run = 0 if seen-unmasked
          existing + masked -> e0 = e0*g + 1; run += 1
        EMA updates apply ONLY to pre-existing entries (first observation
        counts undecayed), matching the original two-pass dict order.
        """
        ref = seen_vox if seen_vox is not None and seen_vox.numel() else mask_vox
        if ref is None or ref.numel() == 0:
            return
        dev0 = ref.device
        seen_u = (torch.unique(seen_vox).to(dev0)
                  if seen_vox is not None and seen_vox.numel()
                  else torch.zeros(0, dtype=torch.int64, device=dev0))
        mask_u = (torch.unique(mask_vox).to(dev0)
                  if mask_vox is not None and mask_vox.numel()
                  else torch.zeros(0, dtype=torch.int64, device=dev0))
        if not seen_u.numel() and not mask_u.numel():
            return
        g = self.gamma
        if self._dev is None:
            self._dev = dev0
            self._keys = self._keys.to(self._dev)
            self._state = self._state.to(self._dev)
        seen_u = seen_u.to(self._dev)
        mask_u = mask_u.to(self._dev)
        n0 = self._keys.numel()

        def _find(keys_q):
            if not n0 or not keys_q.numel():
                return (torch.full(keys_q.shape, -1, dtype=torch.int64, device=self._dev),
                        torch.zeros(keys_q.shape, dtype=torch.bool, device=self._dev))
            pos = torch.searchsorted(self._keys, keys_q)
            pos_c = pos.clamp(max=n0 - 1)
            ok = self._keys[pos_c] == keys_q
            return torch.where(ok, pos_c, torch.full_like(pos_c, -1)), ok

        # ---- seen pass: update existing, collect new
        pos_seen, ok_seen = _find(seen_u)
        if ok_seen.any():
            idx = pos_seen[ok_seen]
            self._state[idx, 1] = self._state[idx, 1] * g + 1.0
            in_mask = torch.isin(seen_u[ok_seen], mask_u)
            self._state[idx, 2] = torch.where(
                in_mask, self._state[idx, 2], torch.zeros_like(self._state[idx, 2]))
        new_seen = seen_u[~ok_seen]
        if new_seen.numel():
            st = torch.zeros(new_seen.numel(), 3, device=self._dev)
            st[:, 1] = 1.0
            self._keys = torch.cat([self._keys, new_seen])
            self._state = torch.cat([self._state, st])
            order = torch.argsort(self._keys, stable=True)
            self._keys = self._keys[order]
            self._state = self._state[order]

        # ---- mask pass: update existing, collect new (against grown table)
        pos_mask, ok_mask = _find(mask_u) if n0 else \
            (torch.full(mask_u.shape, -1, dtype=torch.int64, device=self._dev),
             torch.zeros(mask_u.shape, dtype=torch.bool, device=self._dev))
        # keys added in the seen pass exist now: re-find for those
        if new_seen.numel():
            pos2, ok2 = (lambda p: (p,
                self._keys[p.clamp(max=self._keys.numel()-1)] == mask_u))(
                torch.searchsorted(self._keys, mask_u))
            pos_mask = torch.where(ok_mask, pos_mask, torch.where(ok2, pos2, pos_mask))
            ok_mask = ok_mask | ok2
        if ok_mask.any():
            idx = pos_mask[ok_mask]
            self._state[idx, 0] = self._state[idx, 0] * g + 1.0
            self._state[idx, 2] += 1.0
        new_mask = mask_u[~ok_mask].to(self._dev)
        if new_mask.numel():
            st = torch.zeros(new_mask.numel(), 3, device=self._dev)
            st[:, 0] = 1.0
            st[:, 1] = g
            st[:, 2] = 1.0
            self._keys = torch.cat([self._keys, new_mask])
            self._state = torch.cat([self._state, st])
        # restore sorted key order (append-only growth breaks it)
        order = torch.argsort(self._keys, stable=True)
        self._keys = self._keys[order]
        self._state = self._state[order]

def get_mask_stability_ledger(frontend, config):
    """Lazily construct the ledger on the frontend (default-off => None)."""
    ledger = getattr(frontend, "_mask_stability_ledger", "__unset__")
    if ledger == "__unset__":
        ms = (config.get("MaskStability", {}) or {}).get("enabled", False)
        if ms:
            ledger = MaskStabilityLedger(config)
            Log(f"MaskStability ledger ENABLED (rule={ledger.release_rule}"
                + (f", runlen_min={ledger.runlen_min}"
                   if ledger.release_rule == "runlen" else "")
                + ")")
        else:
            ledger = None
        frontend._mask_stability_ledger = ledger
    return ledger
