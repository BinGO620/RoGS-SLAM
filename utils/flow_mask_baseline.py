"""WP-B naive flow-threshold dynamic mask (CCF-C 整改执行卡 §4 WP-B).

A "no-learning" baseline: threshold the OBSERVED backward RAFT flow magnitude ``|f_obs|``
(a frozen artifact, the SAME offline flow used by ReliabilitySignal) into a binary
person-agnostic dynamic mask, aligned to the SemanticMask ``dilate_px`` convention and
consumed through the existing ``mask_mapping`` + ``mask_insertion`` path. The ONLY
difference from the mask-free MRCS backbone is WHERE the mask comes from (thresholded
flow vs no mask at all); visually it answers "does ANY anti-dynamic handling explain the
gain, or is it specifically the reliability/robust machinery".

Config (SemanticMask block), all default OFF so WP-A mask-off/on is untouched:
  SemanticMask:
    enabled: true            # must be on to consume via mask_mapping/mask_insertion
    source: "flow_threshold" # "maskrcnn" (default) is the learned detector
    flow_quantile: 0.90      # per-frame threshold = quantile of |f_obs| (p80/p90/p95 in pilot)
    flow_abs_px: 2.0         # absolute floor (px): a static camera's frame has ~0 ego flow,
                             # so |f_obs|>2px flags genuine object motion, not just ego parallax
    dilate_px: 7             # aligns with the semantic mask convention

Fairness note (must write into method + limitation): this baseline uses the SAME frozen
offline flow as MRCS, which is BACKWARD ``f_{t->t-1}`` -- every frame consumes only
itself and its predecessor, so the signal is CAUSAL in information content (verified in
``results/evidence/flow_causality_correction.md``: builder loop, on-disk manifest, and
the consumer in ``reliability_signal.py`` all agree). It is precomputed offline so that
every arm/seed gets a bit-identical ``f_obs`` and so RAFT stays out of the 6 GB online
budget -- a scheduling choice, not an information one. The caveat that DOES remain: the
reported online FPS excludes RAFT inference cost, so an end-to-end online deployment
would pay it and this paper does not measure that cost.
(Superseded caveat, retracted 2026-08-15: earlier revisions of this docstring claimed the
flow was "bidirectional / future-visible / non-causal" and that a causal variant was
future work. That was factually wrong -- it is already causal.)
"""
from __future__ import annotations

import os

import numpy as np


def frozen_flow_magnitude(flow_path: str) -> np.ndarray:
    """Load a frozen backward flow ``.npy`` and return ``|f_obs|`` ``(H, W)`` float32 (px)."""
    arr = np.load(flow_path, allow_pickle=False).astype(np.float32)
    if arr.ndim != 3 or arr.shape[2] != 2:
        return np.zeros((arr.shape[0], arr.shape[1]), dtype=np.float32)
    return np.sqrt(arr[..., 0] ** 2 + arr[..., 1] ** 2)


def compute_flow_threshold_mask(
    flow_mag: np.ndarray,
    quantile: float = 0.90,
    abs_px: float = 2.0,
    dilate_px: int = 7,
    max_mask_ratio: float = 0.95,
) -> np.ndarray:
    """``(H, W)`` bool dynamic mask from a threshold on ``|f_obs|``.

    Threshold = max(quantile, abs_px). Dilate (binary box) by ``dilate_px``, mirroring
    ``semantic_mask.compute_semantic_dynamic_mask``. Returns a boolean mask; ``None`` if
    it exceeds ``max_mask_ratio`` (same safety as the learned detector).
    """
    mag = np.maximum(flow_mag, 0.0)
    thr = max(float(np.quantile(mag, quantile)), abs_px) if mag.size else abs_px
    dyn = mag >= thr
    if dilate_px > 0:
        from scipy.ndimage import binary_dilation  # type: ignore

        dyn = binary_dilation(
            dyn, structure=np.ones((2 * dilate_px + 1, 2 * dilate_px + 1), dtype=bool)
        )
    if dyn.mean() > max_mask_ratio:
        return None
    return dyn


def resolve_flow_mask(
    flow_index: dict | None,
    dataset_path: str,
    depth_stem: str,
    flow_subdir: str = "flow_raft",
    quantile: float = 0.90,
    abs_px: float = 2.0,
    dilate_px: int = 7,
    max_mask_ratio: float = 0.95,
):
    """High-level: given a cached flow index + the current depth stem, return ``(mask, path)``.

    ``mask`` is ``(H, W)`` bool (or None if no flow / mask unsafe); ``path`` is the frozen
    flow file used (for provenance). Reuses the same stem-key + flow_subdir resolution as
    the reliability assembler, so the flow-mask and MRCS see the same frozen flow.
    """
    if not flow_index:
        return None, None
    path = flow_index.get(depth_stem)
    if not path:
        return None, None
    try:
        flow_mag = frozen_flow_magnitude(path)
    except Exception:
        return None, None
    mask = compute_flow_threshold_mask(flow_mag, quantile, abs_px, dilate_px, max_mask_ratio)
    return mask, path
