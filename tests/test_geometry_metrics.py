"""Unit tests for compute_geometry_metrics (utils/geometry_metrics.py, P-B).

Pure-numpy point-cloud tests (no GPU, no mesh, no dataset). Verifies the F-score
addition and that neither ghosts nor a sparse map can win a single axis (codex
P-B: "so emitting fewer Gaussians cannot win through accuracy alone").
"""

import unittest

import numpy as np

from utils.geometry_metrics import compute_geometry_metrics


class ComputeGeometryMetricsTests(unittest.TestCase):
    def test_identical_clouds_are_perfect(self):
        pts = np.random.default_rng(0).random((500, 3))
        m = compute_geometry_metrics(pts, pts, threshold_m=0.05, seed=0)
        self.assertAlmostEqual(m["accuracy_cm"], 0.0, places=4)
        self.assertAlmostEqual(m["completion_cm"], 0.0, places=4)
        self.assertAlmostEqual(m["completion_ratio"], 100.0, places=4)
        self.assertAlmostEqual(m["precision_ratio"], 100.0, places=4)
        self.assertAlmostEqual(m["fscore"], 100.0, places=4)

    def test_large_offset_kills_fscore(self):
        # Sparse grid (0.3 m spacing) so each shifted point's nearest neighbour is its
        # own correspondence, not an incidental close point (a dense random cloud
        # breaks that assumption). A 10cm shift >> 5cm threshold -> metrics collapse.
        lin = np.linspace(0.0, 1.2, 5)  # spacing 0.3 m
        gx, gy, gz = np.meshgrid(lin, lin, lin)
        gt = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
        rec = gt + np.array([0.10, 0.0, 0.0])
        m = compute_geometry_metrics(rec, gt, threshold_m=0.05, seed=0)
        self.assertAlmostEqual(m["accuracy_cm"], 10.0, places=1)
        self.assertLess(m["completion_ratio"], 5.0)
        self.assertLess(m["precision_ratio"], 5.0)
        self.assertLess(m["fscore"], 5.0)

    def test_sparse_reconstruction_cannot_win_on_precision(self):
        # rec = a small subset of GT: every rec point sits exactly on GT (precision
        # ~100%), but most GT is uncovered (low recall) -> F-score stays low, so a
        # sparse "fewer Gaussians" map cannot win.
        rng = np.random.default_rng(2)
        gt = rng.random((1000, 3))
        rec = gt[:50]
        m = compute_geometry_metrics(rec, gt, threshold_m=0.05, seed=0)
        self.assertGreater(m["precision_ratio"], 90.0)
        self.assertLess(m["completion_ratio"], 50.0)
        self.assertLess(m["fscore"], 65.0)

    def test_empty_raises(self):
        pts = np.random.default_rng(3).random((10, 3))
        with self.assertRaises(ValueError):
            compute_geometry_metrics(np.empty((0, 3)), pts)


if __name__ == "__main__":
    unittest.main()
