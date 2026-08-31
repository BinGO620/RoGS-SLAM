"""CPU unit tests for the pure helpers of scripts/eval_vacated_posthoc.py.

The GPU pass has its own built-in validation (the band-metrics faithfulness anchor
against the run's stored band_metrics.json); here we pin the two pure functions the
Phase-0 verdict rides on: C2W->W2C inversion and the band comparison logic.
"""

import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.eval_vacated_posthoc import compare_band_metrics, w2c_from_c2w  # noqa: E402


def _band(psnr, depth=None, support=1000, frames=10):
    return {
        "radius_px": 50,
        "psnr": psnr,
        "ssim": 0.9,
        "depth_l1_pen_cm": depth,
        "support_px_mean": support,
        "frames_with_support": frames,
    }


class W2CFromC2WTests(unittest.TestCase):
    def test_roundtrip_random_se3(self):
        rng = np.random.default_rng(3)
        for _ in range(10):
            angle_axis = rng.normal(size=3)
            theta = np.linalg.norm(angle_axis)
            k = angle_axis / (theta + 1e-12)
            K = np.array(
                [[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]]
            )
            R = np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * K @ K
            t = rng.normal(size=3)
            c2w = np.eye(4)
            c2w[:3, :3] = R
            c2w[:3, 3] = t
            Rw, tw = w2c_from_c2w(c2w.tolist())
            np.testing.assert_allclose(Rw, R.T, atol=1e-12)
            np.testing.assert_allclose(tw, -R.T @ t, atol=1e-12)

    def test_identity(self):
        R, t = w2c_from_c2w(np.eye(4))
        np.testing.assert_allclose(R, np.eye(3), atol=1e-15)
        np.testing.assert_allclose(t, np.zeros(3), atol=1e-15)


class CompareBandMetricsTests(unittest.TestCase):
    def test_pass_within_tolerance(self):
        stored = {"frames_scored": 80, "bands": {"band50": _band(21.5, depth=3.1)}}
        fresh = {"frames_scored": 80, "bands": {"band50": _band(21.53, depth=3.05)}}
        out = compare_band_metrics(stored, fresh, tol_db=0.05)
        self.assertTrue(out["pass"])
        self.assertAlmostEqual(out["max_abs_dpsnr_db"], 0.03, places=6)
        self.assertAlmostEqual(out["per_band"]["band50"]["abs_ddepth_cm"], 0.05)

    def test_fail_beyond_tolerance(self):
        stored = {"frames_scored": 80, "bands": {"band50": _band(21.5)}}
        fresh = {"frames_scored": 80, "bands": {"band50": _band(21.6)}}
        out = compare_band_metrics(stored, fresh, tol_db=0.05)
        self.assertFalse(out["pass"])
        self.assertFalse(out["per_band"]["band50"]["pass"])

    def test_fail_on_frames_scored_mismatch(self):
        stored = {"frames_scored": 80, "bands": {"band50": _band(21.5)}}
        fresh = {"frames_scored": 79, "bands": {"band50": _band(21.5)}}
        self.assertFalse(compare_band_metrics(stored, fresh)["pass"])

    def test_fail_on_missing_band(self):
        stored = {"frames_scored": 80, "bands": {"band50": _band(21.5)}}
        fresh = {"frames_scored": 80, "bands": {}}
        out = compare_band_metrics(stored, fresh)
        self.assertFalse(out["pass"])
        self.assertEqual(out["per_band"]["band50"], "missing-in-fresh")

    def test_null_psnr_matching_is_ok(self):
        stored = {"frames_scored": 80, "bands": {"band10": _band(None)}}
        fresh = {"frames_scored": 80, "bands": {"band10": _band(None)}}
        self.assertTrue(compare_band_metrics(stored, fresh)["pass"])

    def test_null_psnr_one_sided_fails(self):
        stored = {"frames_scored": 80, "bands": {"band10": _band(None)}}
        fresh = {"frames_scored": 80, "bands": {"band10": _band(20.0)}}
        self.assertFalse(compare_band_metrics(stored, fresh)["pass"])

    def test_multi_band_max_delta(self):
        stored = {
            "frames_scored": 80,
            "bands": {"band10": _band(19.0), "band50": _band(21.5)},
        }
        fresh = {
            "frames_scored": 80,
            "bands": {"band10": _band(19.02), "band50": _band(21.46)},
        }
        out = compare_band_metrics(stored, fresh, tol_db=0.05)
        self.assertTrue(out["pass"])
        self.assertAlmostEqual(out["max_abs_dpsnr_db"], 0.04, places=6)


if __name__ == "__main__":
    unittest.main()
