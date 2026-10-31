"""P1 mask quality / propagation-lite (doc 14, Execution plan P1).

Mask R-CNN occasionally MISSES the walking person on a frame (coverage collapses to
~0 for one or a few frames) -> that frame leaks the person into tracking / mapping /
insertion / the coarse-pose ICP / (later) the DBA edges. This is the upstream
contract codex flagged: every dynamic-handling consumer must see clean, gap-free
masks. This module provides a MINIMAL fix (not a fancy tracker):

  - per-frame coverage audit,
  - detection-gap flag = person was present in recent frames but current coverage
    collapsed,
  - previous-mask fallback: on a gap, reuse the last good mask (dilated a little to
    cover motion), bounded to a few consecutive frames so a truly person-free stretch
    is not force-masked forever.

Default-off (``MaskQA.enabled``). Pose-independent. State lives on the FrontEnd
(single owner) -- these are pure helpers over that state.
"""

import torch.nn.functional as F


def get_mask_qa_config(config):
    return config.get("MaskQA", {})


def mask_qa_enabled(config):
    return bool(get_mask_qa_config(config).get("enabled", False))


def mask_coverage(mask):
    """Fraction of pixels flagged dynamic. Accepts (1,H,W)/(H,W) bool/float or None."""
    if mask is None:
        return 0.0
    return float(mask.float().mean().item())


def detect_gap(cov, recent, cfg):
    """A detection gap = person was present recently but current coverage collapsed.

    cov: current-frame coverage. recent: list of recent coverages (excl. current).
    Returns True only when we have enough history, the recent median shows presence,
    and the current frame is (near) empty -- i.e. a likely missed detection, not a
    genuine person-free frame.
    """
    min_hist = int(cfg.get("min_history", 3))
    if len(recent) < min_hist:
        return False
    presence = float(cfg.get("presence_thresh", 0.02))  # recently clearly present
    gap_abs = float(cfg.get("gap_abs_thresh", 0.005))  # now (near) empty
    recent.sort()
    med = recent[len(recent) // 2]
    return med >= presence and cov < gap_abs


def dilate_mask(mask, px):
    """Max-pool dilation of a (1,H,W)/(H,W) bool mask by ``px`` pixels each side."""
    if mask is None or px <= 0:
        return mask
    squeeze = mask.dim() == 2
    m = mask.float().view(1, 1, *mask.shape[-2:])
    k = 2 * int(px) + 1
    m = F.max_pool2d(m, kernel_size=k, stride=1, padding=int(px)) > 0.5
    m = (
        m.view(mask.shape[-2], mask.shape[-1])
        if squeeze
        else m.view(1, *mask.shape[-2:])
    )
    return m
