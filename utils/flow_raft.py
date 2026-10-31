"""Frozen RAFT optical-flow artifact (method #8, signal ``s`` observed-flow half).

The reliability signal ``s=(1-e_flow)(1-v*g)`` (``utils/reliability_signal.py``,
doc-10 §1) needs an *observed* dense flow field ``f_obs``. Per the locked positioning
(``frozen-RAFT-consensus reliability``) and the frozen-provenance discipline used for
the P-A dynamic mask (``dynamic_mask_gtmc/``), ``f_obs`` is PRECOMPUTED OFFLINE into a
frozen, hashed artifact rather than run online:

  * it keeps RAFT entirely out of the online (6 GB) VRAM/latency budget -- the online
    path only computes the ego-motion ``f_static`` (``reliability_signal.rigid_flow``)
    and the disagreement ``q=A(||f_obs-f_static||)``;
  * it guarantees BIT-IDENTICAL ``f_obs`` across every lifecycle arm and seed, which is
    exactly what the make-or-break causal-twin requirement (doc-11 §2) needs -- the arms
    must differ ONLY in ``Mapping.lifecycle_mode``;
  * it is method-INDEPENDENT: ``f_obs`` depends only on the RGB stream, never on any
    arm's pose/map output.

The stored flow is BACKWARD ``f_{t->t-1}`` (current frame ``t`` to its predecessor) in
PIXELS, in the SAME undistorted pinhole pixel space the loader tracks in
(``utils/dataset.py::MonocularDataset.__getitem__`` undistorts RGB when
``distorted``) -- the builder (``scripts/build_flow_raft.py``) undistorts identically
before RAFT so ``f_obs`` and ``f_static`` share one pixel space. The direction is
BACKWARD (not forward) so the disagreement ``||f_obs - f_static||`` is CURRENT-FRAME
anchored: a mover's anomaly lands on frame ``t``'s grid directly (no warp for the newest
pair; a forward field would misplace it by the flow magnitude), matching the proven P2b
``flow_mask.py`` convention. One ``<later-frame-stem>.npy`` (float16, ``(H, W, 2)``) per
frame ``t`` keyed by its timestamp stem (frame 0 has no predecessor), plus a
``manifest.json`` (weights sha, variant, iters, direction, calib, content hash).

The online-incremental RAFT variant (doc-10 §Cost: one inference/frame, FP16, CPU
buffers) remains available for the deployable-system (E1-S) claim; this frozen artifact
is the reproducible eval path.

Model helpers (``load_raft_model`` / ``compute_forward_flow``) import torchvision lazily
and run only on the GPU builder; the artifact IO + hashing below are pure and unit-tested
on CPU with synthetic ``.npy`` (``tests/test_flow_raft.py``).
"""

from __future__ import annotations

import hashlib
import os
from glob import glob

import numpy as np

PROTOCOL_VERSION = "flow-raft-v1"


def get_flow_raft_config(config):
    return config.get("FlowRaft", {})


def flow_raft_enabled(config):
    return bool(get_flow_raft_config(config).get("enabled", False))


# --------------------------------------------------------------------------- #
# Frozen-artifact IO (pure; no torch/torchvision import needed).
# --------------------------------------------------------------------------- #
def flow_sha256(flows) -> str:
    """Deterministic hash of a forward-flow stack (frozen provenance, doc-11).

    Hashes the exact bytes that are written to disk (float16), so the manifest sha
    matches a re-read of the artifact.
    """
    h = hashlib.sha256()
    for f in flows:
        h.update(np.ascontiguousarray(np.asarray(f, dtype=np.float16)).tobytes())
    return h.hexdigest()


def save_frozen_flow(path, flow) -> None:
    """Persist one ``(H, W, 2)`` forward flow (px) as float16 ``.npy``.

    float16 quantisation (~5e-3 px at a 5 px flow) sits far below the flow noise floor
    the MAD-robust ``flow_anomaly`` normaliser rides, so it never perturbs the anomaly
    decision, while halving disk vs float32 over a full sequence.
    """
    arr = np.asarray(flow, dtype=np.float16)
    if arr.ndim != 3 or arr.shape[2] != 2:
        raise ValueError(f"flow must be (H, W, 2), got {arr.shape}")
    np.save(path, arr, allow_pickle=False)


def load_frozen_flow(path) -> np.ndarray:
    """Load one frozen BACKWARD flow ``.npy`` (``f_{t->t-1}``) as ``(H, W, 2)`` float32 (px)."""
    arr = np.load(path, allow_pickle=False)
    if arr.ndim != 3 or arr.shape[2] != 2:
        raise ValueError(f"frozen flow at {path} must be (H, W, 2), got {arr.shape}")
    return arr.astype(np.float32)


def frozen_flow_index(flow_dir) -> dict:
    """Map ``frame stem -> absolute ``.npy`` path`` for a frozen flow directory.

    Keys are the timestamp stems written by ``scripts/build_flow_raft.py`` (one file per
    frame ``t``, holding BACKWARD flow ``f_{t->t-1}``; frame 0 has none). The online
    reliability assembler associates frame ``t`` to its own (and its recent frames')
    backward flow by stem, NOT by frame index, so the lookup survives any drift between a
    run's frame selection and the builder's association. ``manifest.json`` is ignored.
    Returns ``{}`` when ``flow_dir`` is missing or empty.
    """
    out: dict = {}
    if not flow_dir or not os.path.isdir(flow_dir):
        return out
    for p in sorted(glob(os.path.join(flow_dir, "*.npy"))):
        out[os.path.splitext(os.path.basename(p))[0]] = os.path.abspath(p)
    return out


# --------------------------------------------------------------------------- #
# RAFT model (GPU builder only; torchvision imported lazily).
# --------------------------------------------------------------------------- #
_RAFT_VARIANTS = ("small", "large")


def load_raft_model(variant: str = "small", device: str = "cuda"):
    """Load a frozen torchvision RAFT (eval, ``requires_grad=False``) + its transforms.

    Returns ``(model, transforms, weights_meta)`` where ``transforms`` maps a pair of
    ``(N, 3, H, W)`` uint8 batches to the normalised model inputs and ``weights_meta``
    carries the checkpoint url for the manifest. ``variant`` in ``{small, large}``;
    ``small`` (~1M params, ~0.2 GB peak at 640x480) is the frozen default.
    """
    if variant not in _RAFT_VARIANTS:
        raise ValueError(f"RAFT variant must be one of {_RAFT_VARIANTS}, got {variant!r}")
    from torchvision.models.optical_flow import (
        Raft_Large_Weights,
        Raft_Small_Weights,
        raft_large,
        raft_small,
    )

    if variant == "small":
        weights = Raft_Small_Weights.DEFAULT
        model = raft_small(weights=weights, progress=False)
    else:
        weights = Raft_Large_Weights.DEFAULT
        model = raft_large(weights=weights, progress=False)
    model = model.eval().to(device)
    for p in model.parameters():
        p.requires_grad_(False)
    return model, weights.transforms(), {"weights_url": weights.url, "variant": variant}


def compute_flow(model, transforms, img_src_u8, img_dst_u8, device: str = "cuda", iters: int = 12):
    """Dense flow ``f_{src->dst}`` (px) for one undistorted uint8 pair.

    ``img_src_u8``/``img_dst_u8`` are ``(3, H, W)`` uint8 tensors (undistorted, in the
    loader's pixel space). Returns ``(H, W, 2)`` float32 numpy ``(du, dv)`` mapping a src
    pixel to its dst location. For the frozen BACKWARD artifact the builder passes
    ``src = frame t``, ``dst = frame t-1`` so the field is current-frame anchored. Runs
    under ``no_grad``; takes RAFT's final refinement (``num_flow_updates=iters``).
    """
    import torch

    with torch.no_grad():
        b1 = img_src_u8.unsqueeze(0)
        b2 = img_dst_u8.unsqueeze(0)
        b1, b2 = transforms(b1, b2)
        b1, b2 = b1.to(device), b2.to(device)
        preds = model(b1, b2, num_flow_updates=iters)
        flow = preds[-1][0]  # (2, H, W) flow src->dst, px
        return flow.permute(1, 2, 0).contiguous().float().cpu().numpy()


def weights_file_sha256(weights_url: str) -> str:
    """sha256 of the cached RAFT checkpoint (frozen-weights provenance) or ``""``.

    Reads the torch-hub cache file the ``weights_url`` resolves to; returns ``""`` if it
    is not present (so the builder degrades to recording the url only).
    """
    import torch

    ckpt = os.path.join(
        torch.hub.get_dir(), "checkpoints", os.path.basename(weights_url)
    )
    if not os.path.isfile(ckpt):
        return ""
    h = hashlib.sha256()
    with open(ckpt, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
