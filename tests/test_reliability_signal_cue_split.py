"""ReliabilitySignal cue-split (flow-only / geometry-only) behavior tests.

These verify the ABLATION-only switch in `fuse_static_evidence` / the caller path
is correct and that the default (`both`) is byte-identical to the historic formula.
"""

import torch
import pytest

from utils.reliability_signal import (
    cauchy_tracking_weight,
    fuse_static_evidence,
)
from utils.reliability_signal import compute_reliability_tracking_weight  # noqa: F401


def _sample(h=8, w=9, mover_ratio=0.2):
    """Deterministic synthetic frames with a contiguous mover block."""
    torch.manual_seed(7)
    mover = torch.zeros(h, w, dtype=torch.bool)
    mover[4:, 6:] = True
    e_flow = torch.zeros(h, w)
    g = torch.zeros_like(e_flow)
    v = torch.ones_like(e_flow)
    e_flow[mover] = 0.8   # mover has high flow-consensus anomaly
    g[mover] = 0.7        # mover has high geometric anomaly
    return e_flow, g, v, mover


def test_default_both_formula():
    """Default mode reproduces the historic identity (1-e)*(1-v*g)."""
    e, g, v, m = _sample()
    s = fuse_static_evidence(g, e, v, mode="both")
    expected = (1.0 - e) * (1.0 - v * g)
    assert torch.allclose(s, expected, atol=1e-7)
    # omitting mode must give the same result as mode="both"
    s_default = fuse_static_evidence(g, e, v)
    assert torch.allclose(s, s_default, atol=1e-7)


def test_flow_only_ignores_geometry():
    e, g, v, m = _sample()
    s = fuse_static_evidence(g, e, v, mode="flow-only")
    assert torch.allclose(s, 1.0 - e, atol=1e-7)
    g2 = g + 1e6
    s2 = fuse_static_evidence(g2, e, v, mode="flow-only")
    assert torch.allclose(s, s2, atol=1e-7)


def test_geometry_only_ignores_flow():
    e, g, v, m = _sample()
    s = fuse_static_evidence(g, e, v, mode="geometry-only")
    assert torch.allclose(s, 1.0 - v * g, atol=1e-7)
    e2 = e + 1e6
    s2 = fuse_static_evidence(g, e2, v, mode="geometry-only")
    assert torch.allclose(s, s2, atol=1e-7)


def test_invalid_mode_raises():
    e, g, v, m = _sample()
    with pytest.raises(ValueError):
        fuse_static_evidence(g, e, v, mode="nonsense")


def test_both_no_less_downweight_than_either_single_cue():
    """Motion pixels under 'both' are at least as down-weighted as under either
    single-cue signal, whenever both cues flag motion."""
    e, g, v, m = _sample()
    w_both = cauchy_tracking_weight(fuse_static_evidence(g, e, v, mode="both"))
    w_flow = cauchy_tracking_weight(fuse_static_evidence(g, e, v, mode="flow-only"))
    w_geo = cauchy_tracking_weight(fuse_static_evidence(g, e, v, mode="geometry-only"))
    assert bool(((w_both[m] <= w_flow[m] + 1e-6).all()))
    assert bool(((w_both[m] <= w_geo[m] + 1e-6).all()))
