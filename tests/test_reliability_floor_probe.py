"""Unit tests for the offline reliability FLOW-FLOOR probe (scripts/probe_reliability_floor.py).

Pure CPU/NumPy/torch: the probe's math is method-independent (GT-pose rigid_flow + a
frozen f_obs), so it is fully synthetic-testable with identity poses (every pixel
reprojects to itself -> f_static = 0, so the residual IS the injected f_obs). The
load-bearing property under test is that ``flow_scale_floor`` actually GATES: an injected
mover block saturates e_flow at floor 0 but is suppressed once the floor exceeds its
magnitude -- exactly the static no-harm lever the probe calibrates.
"""

import unittest

import numpy as np
import torch

from scripts.probe_reliability_floor import (
    flagged_fraction,
    frame_static_flow,
    largest_component_fraction,
)
from utils.reliability_signal import assemble_flow_consensus

H, W = 32, 40
FX = FY = 100.0
CX, CY = W / 2.0, H / 2.0
EYE = np.eye(4, dtype=np.float64)


def _eflow(f_obs, floor):
    """Run the probe's per-frame path with identity GT poses (f_static == 0)."""
    depth = np.ones((H, W), dtype=np.float32)
    fo, f_static, valid, residual = frame_static_flow(
        depth, f_obs, EYE.copy(), EYE.copy(), FX, FY, CX, CY, "cpu"
    )
    e_flow, flow_valid = assemble_flow_consensus([fo], [f_static], [valid], scale_floor=floor)
    return e_flow, flow_valid, valid, residual


class FlaggedFraction(unittest.TestCase):
    def test_counts_only_valid_pixels(self):
        e = torch.tensor([[0.9, 0.1], [0.6, 0.4]])
        fv = torch.tensor([[True, True], [True, False]])  # 3 valid; 0.4 invalid excluded
        frac, n = flagged_fraction(e, fv, 0.5)
        self.assertEqual(n, 2)                    # 0.9 and 0.6
        self.assertAlmostEqual(frac, 2 / 3, places=6)

    def test_nan_when_no_valid_flow(self):
        e = torch.zeros((2, 2))
        fv = torch.zeros((2, 2), dtype=torch.bool)
        frac, n = flagged_fraction(e, fv, 0.5)
        self.assertEqual(n, 0)
        self.assertTrue(np.isnan(frac))


class LargestComponentFraction(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(largest_component_fraction(np.zeros((5, 5), dtype=bool)), 0.0)

    def test_single_blob_is_one(self):
        m = np.zeros((10, 10), dtype=bool)
        m[2:5, 2:5] = True
        self.assertAlmostEqual(largest_component_fraction(m), 1.0, places=6)

    def test_two_blobs_report_larger_share(self):
        m = np.zeros((10, 10), dtype=bool)
        m[0:1, 0:1] = True       # 1 px component
        m[5:8, 5:8] = True       # 9 px component -> 9/10
        self.assertAlmostEqual(largest_component_fraction(m), 9 / 10, places=6)


class FrameStaticFlowAndFloor(unittest.TestCase):
    def test_static_frame_noise_is_suppressed_by_floor(self):
        """f_obs=0 => residual is pure float32 projection noise (~1e-5 px). At floor 0 the
        MAD collapses onto that noise and spuriously flags pixels (THE footgun); a small
        floor holds the scale above the noise and flags nothing -- the no-harm gate."""
        zeros = np.zeros((H, W, 2), dtype=np.float32)
        _, _, valid, residual = _eflow(zeros, floor=0.0)
        self.assertTrue(bool(valid.all()))                    # all pixels valid (in-bounds)
        self.assertLess(float(residual.max()), 1e-2)          # residual really is ~0
        e_fl, fv_fl, _, _ = _eflow(zeros, floor=0.1)
        frac_fl, _ = flagged_fraction(e_fl, fv_fl, 0.5)
        self.assertAlmostEqual(frac_fl, 0.0, places=6)        # floor kills the noise-FP

    def test_floor_gates_mover_block(self):
        """A coherent 10-px flow block: a well-chosen floor keeps it (mover flagged) while
        dropping the noise; a floor above its magnitude suppresses it too (the sweep knee)."""
        f_obs = np.zeros((H, W, 2), dtype=np.float32)
        f_obs[8:16, 10:18, 0] = 10.0                          # 8x8 coherent mover, 10 px
        block_frac = (8 * 8) / (H * W)

        # floor 5 px: noise (~1e-5) suppressed, the 10-px block kept (1-exp(-10/5)=0.86).
        e5, fv5, _, _ = _eflow(f_obs, floor=5.0)
        frac5, _ = flagged_fraction(e5, fv5, 0.5)
        self.assertAlmostEqual(frac5, block_frac, places=6)   # exactly the block, no noise
        flagged5 = ((e5 > 0.5) & fv5.bool()).numpy()
        self.assertTrue(flagged5[8:16, 10:18].all())          # whole block flagged
        self.assertAlmostEqual(largest_component_fraction(flagged5), 1.0, places=6)  # one blob

        # floor 30 px >> 10 px: 1-exp(-10/30)=0.28 < 0.5 -> the block no longer clears.
        e_hi, fv_hi, _, _ = _eflow(f_obs, floor=30.0)
        frac_hi, _ = flagged_fraction(e_hi, fv_hi, 0.5)
        self.assertAlmostEqual(frac_hi, 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
