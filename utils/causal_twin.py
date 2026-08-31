"""Causal-twin infrastructure: lineage IDs + counter-based RNG (method #7).

The make-or-break ablation (``03-knowledges/11-make_or_break_ablation_spec.md``)
compares three Gaussian-lifecycle arms -- ``immediate`` / ``prune`` / ``deferred`` --
that must differ ONLY by ``Mapping.lifecycle_mode``. For that comparison to be a
valid *causal twin* (same seed, same everything-else), two pieces of infrastructure
are needed and are provided here as pure, CPU-testable units (no GaussianModel, no
CUDA, no dataset):

1. LineageAllocator + ``lineage_prune_mask`` -- a monotonic per-birth id so the
   ``prune`` arm can delete a rejected candidate's ENTIRE lineage (the candidate
   Gaussian PLUS every clone/split descendant it spawned PLUS optimizer state),
   not just the seed point. Without full-lineage deletion the ``prune`` control is
   not a faithful "insert-then-remove" twin of ``deferred`` (codex hardening, doc-11).

2. CounterRNG -- a counter-based (key -> seed -> Generator) RNG so every stochastic
   site (InitGaussian point subsample, densify-and-split jitter) draws from a stream
   keyed by ``(seq, seed, frame, event, call_index)`` and NOT by ``lifecycle_mode``.
   Same logical event across arms => identical draw (paired); different ``seed`` =>
   different draw (real multi-seed variance). This removes gratuitous RNG desync so
   any measured arm difference is the lifecycle mechanism, not a lucky ``torch.normal``.

CONTRACT for CounterRNG keys (caller's responsibility):
  * base_key = ``(seq_name, seed)``  -- fixed for a run, varies the stream per seed.
  * event_key = ``(frame_idx, event_name, call_index)`` -- identifies a logical draw;
    it MUST NOT contain ``lifecycle_mode`` or any arm-dependent quantity, or the arms
    desync. ``call_index`` MUST be a logical SITE-LOCAL counter (e.g. the k-th split
    at this frame), NOT a global draw counter -- a global counter is itself
    arm-dependent (arms draw a different number of times) and would desync the key.
  * PAIRING IS SAME-DEVICE ONLY: a CPU and a CUDA ``torch.Generator`` seeded
    identically do NOT produce the same samples, and bitwise replay is not
    guaranteed across PyTorch/CUDA versions. Pair arms on the same device + build;
    seed the generator on the SAME device as the tensor being sampled.
Determinism is process-independent (hashlib, not Python's salted ``hash``), so a run
replays bit-for-bit and E1-M mechanism-replay can re-key the exact same streams.
"""

from __future__ import annotations

import hashlib
from typing import Iterable

import torch

UNTRACKED = -1  # lineage id for normal map growth (never lineage-pruned)


def key_to_seed(*parts) -> int:
    """Deterministic, process-independent 63-bit seed from an arbitrary key tuple.

    Uses blake2b over a canonical ``repr``-joined encoding (Python's built-in
    ``hash`` is salted per-process for str/bytes and would break run replay). The
    result is non-negative and fits ``torch.Generator.manual_seed``.
    """
    canonical = "|".join(repr(p) for p in parts).encode("utf-8")
    digest = hashlib.blake2b(canonical, digest_size=8).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


class CounterRNG:
    """Counter-based RNG: a key deterministically selects an independent stream.

    ``base_key`` fixes the run (e.g. ``("walking_xyz", 0)``); each ``generator`` /
    sampling call mixes in an ``event_key`` to seed a fresh ``torch.Generator``.
    Because the seed is a pure function of the key (never of wall-clock, call
    ordering across arms, or ``lifecycle_mode``), two arms that reach the same
    logical event draw identical samples. See the module docstring for the key
    contract.
    """

    def __init__(self, *base_key):
        self.base_key = tuple(base_key)

    def generator(self, *event_key, device="cpu") -> torch.Generator:
        """A ``torch.Generator`` on ``device`` seeded by ``base_key + event_key``.

        The generator's device MUST match the device of the tensors it will
        sample (a CUDA ``torch.normal`` needs a CUDA generator).
        """
        g = torch.Generator(device=device)
        g.manual_seed(key_to_seed(*self.base_key, *event_key))
        return g

    def randn(self, size, *event_key, device="cpu", dtype=torch.float32) -> torch.Tensor:
        """Standard-normal tensor of shape ``size`` from the ``event_key`` stream."""
        g = self.generator(*event_key, device=device)
        return torch.randn(size, generator=g, device=device, dtype=dtype)

    def normal_like(self, std, *event_key) -> torch.Tensor:
        """Zero-mean normal with per-element ``std`` (matches ``densify_and_split``).

        Samples on ``std``'s own device/dtype so it is a drop-in for
        ``torch.normal(mean=zeros, std=std)`` at the split site.
        """
        g = self.generator(*event_key, device=std.device)
        return torch.normal(torch.zeros_like(std), std, generator=g)

    def randperm(self, n: int, *event_key, device="cpu") -> torch.Tensor:
        """Deterministic permutation of ``range(n)`` from the ``event_key`` stream."""
        g = self.generator(*event_key, device=device)
        return torch.randperm(n, generator=g, device=device)

    def subsample_indices(self, n: int, k: int, *event_key, device="cpu") -> torch.Tensor:
        """Sorted indices of a deterministic size-``min(k, n)`` subset of ``range(n)``.

        Drop-in for a random point-cloud downsample at InitGaussian: same key =>
        same kept points across arms, different ``seed`` => different subset.
        Sorted so the surviving order is reproducible.
        """
        k = max(0, min(int(k), int(n)))
        if n <= 0 or k == 0:
            return torch.empty(0, dtype=torch.long, device=device)
        if k == n:
            return torch.arange(n, dtype=torch.long, device=device)
        perm = self.randperm(n, *event_key, device=device)
        return perm[:k].sort().values


class LineageAllocator:
    """Monotonic allocator of fresh per-birth lineage ids (int32, never reused).

    Each candidate birth gets a contiguous block of fresh ids; clone/split
    descendants INHERIT the parent id (handled in GaussianModel), so an id names
    the whole sub-tree descended from one candidate. ``allocate`` is the single
    source of ids, keeping them collision-free and replay-stable.
    """

    def __init__(self, start: int = 0):
        self._next = int(start)

    def allocate(self, k: int, device="cpu") -> torch.Tensor:
        """Return ``k`` fresh contiguous int32 ids and advance the counter."""
        k = int(k)
        if k < 0:
            raise ValueError(f"cannot allocate a negative count: {k}")
        ids = torch.arange(self._next, self._next + k, dtype=torch.int32, device=device)
        self._next += k
        return ids

    @property
    def count(self) -> int:
        """Total ids allocated so far (also the next id to be handed out)."""
        return self._next

    def reset(self, start: int = 0) -> None:
        self._next = int(start)


def base_rng_key(config) -> tuple:
    """The ``(sequence, seed)`` base key for a run's CounterRNG, from ``config``.

    Load-bearing property (the causal-twin contract): the key varies with
    ``seed`` (so multi-seed runs draw genuinely different streams) and with the
    sequence, but NEVER with ``Mapping.lifecycle_mode`` -- so the three lifecycle
    arms (immediate / prune / deferred) reach identical logical events with
    identical draws. ``config`` may be ``None`` or missing keys (non-SLAM callers
    such as the mesh renderer or unit tests) -> falls back to a stable empty tag;
    determinism is preserved, only the per-seed/per-sequence spread is dropped.
    """
    dataset = config.get("Dataset", {}) if isinstance(config, dict) else {}
    seq = dataset.get("sequence") or dataset.get("dataset_path") or ""
    seed = config.get("seed", 0) if isinstance(config, dict) else 0
    return (str(seq), int(seed))


def lineage_prune_mask(lineage_id: torch.Tensor, targets: Iterable[int]) -> torch.Tensor:
    """Boolean mask (``True`` = prune) selecting every Gaussian whose lineage id is
    in ``targets``.

    Feeds ``GaussianModel.prune_points`` so a rejected/expired candidate and its
    full densification lineage are removed together with their optimizer state.
    ``targets`` empty => all-``False`` (prune nothing). ``UNTRACKED`` ids are only
    matched if explicitly requested.
    """
    li = lineage_id.reshape(-1)
    tlist = [int(t) for t in targets]
    if len(tlist) == 0:
        return torch.zeros_like(li, dtype=torch.bool)
    t = torch.as_tensor(tlist, dtype=li.dtype, device=li.device)
    return torch.isin(li, t)
