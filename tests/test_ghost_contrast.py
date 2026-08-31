"""Unit tests for the paired ghost-contrast metric.

The absolute vacated-region number is dominated by global map/pose quality (on
Bonn balloon: a 21-27 cm base against a 0.1-1.3 cm vacated-minus-static gap and
a measured 1.0-3.3 cm run-to-run noise band), so R2-P02-E2 could not have
resolved its own effect even had the mechanism worked. ``vacated_contrast_metrics``
scores the vacated region against the SAME frame's untouched static background so
that global error cancels.

These tests pin the two properties that make the contrast worth reporting:
  1. a clean map scores ~0 excess (no ghost, no penalty);
  2. a ghost confined to the vacated region shows up as positive excess;
  3. a GLOBAL degradation (drift, worse map everywhere) leaves the excess
     unchanged while moving the absolute vacated number a lot -- exactly the
     confound the contrast is built to remove.
"""

import math
import os
import sys
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.static_eval import (  # noqa: E402
    vacated_contrast_metrics,
    vacated_region_metrics,
)


def _scene(h=16, w=16):
    """Static scene at 2 m; the mover vacated a 4x4 patch and now sits elsewhere."""
    gt_img = torch.zeros(3, h, w)
    gt_depth = torch.full((h, w), 2.0)
    past = torch.zeros(h, w, dtype=torch.bool)
    past[2:6, 2:6] = True
    cur = torch.zeros(h, w, dtype=torch.bool)
    cur[2:6, 10:14] = True
    return gt_img, gt_depth, past, cur


class GhostContrastTests(unittest.TestCase):
    def test_perfect_map_has_zero_excess(self):
        gt_img, gt_depth, past, cur = _scene()
        out = vacated_contrast_metrics(
            gt_img, gt_img, gt_depth, gt_depth, cur, past
        )
        self.assertEqual(out["vacated_support_px"], 16)
        self.assertGreater(out["nonvacated_support_px"], 0)
        self.assertAlmostEqual(out["ghost_excess_depth_l1_cm"], 0.0, places=5)

    def test_ghost_in_vacated_region_is_positive_excess(self):
        gt_img, gt_depth, past, cur = _scene()
        pred_depth = gt_depth.clone()
        pred_depth[2:6, 2:6] = 1.9  # a 10 cm ghost floating in front
        out = vacated_contrast_metrics(
            gt_img, gt_img, pred_depth, gt_depth, cur, past
        )
        self.assertAlmostEqual(out["ghost_excess_depth_l1_cm"], 10.0, places=4)

    def test_global_degradation_cancels_out(self):
        """The whole point: a uniformly worse map must NOT read as more ghost."""
        gt_img, gt_depth, past, cur = _scene()
        clean = gt_depth.clone()
        clean[2:6, 2:6] = 1.9  # same 10 cm ghost as above
        drifted = clean - 0.05  # + a 5 cm global depth bias everywhere

        vac_clean = vacated_region_metrics(
            gt_img, gt_img, clean, gt_depth, cur, past
        )["vacated_depth_l1_pen_cm"]
        vac_drift = vacated_region_metrics(
            gt_img, gt_img, drifted, gt_depth, cur, past
        )["vacated_depth_l1_pen_cm"]
        # The absolute headline moves a lot on a purely global change...
        self.assertGreater(abs(vac_drift - vac_clean), 4.0)

        exc_clean = vacated_contrast_metrics(
            gt_img, gt_img, clean, gt_depth, cur, past
        )["ghost_excess_depth_l1_cm"]
        exc_drift = vacated_contrast_metrics(
            gt_img, gt_img, drifted, gt_depth, cur, past
        )["ghost_excess_depth_l1_cm"]
        # ...while the paired contrast reports the same ghost either way.
        # (15 cm vs 5 cm ghost-vs-background => the excess is preserved at 10 cm.)
        self.assertAlmostEqual(exc_clean, exc_drift, places=4)
        self.assertAlmostEqual(exc_clean, 10.0, places=4)

    def test_complement_excludes_current_mover_and_vacated(self):
        gt_img, gt_depth, past, cur = _scene()
        pred_depth = gt_depth.clone()
        pred_depth[2:6, 10:14] = 0.5  # garbage ON the current mover
        out = vacated_contrast_metrics(
            gt_img, gt_img, pred_depth, gt_depth, cur, past
        )
        # The mover's CURRENT footprint is outside the static support entirely,
        # so neither term of the pair may see it.
        self.assertAlmostEqual(out["nonvacated_depth_l1_pen_cm"], 0.0, places=5)
        self.assertAlmostEqual(out["ghost_excess_depth_l1_cm"], 0.0, places=5)

    def test_no_vacated_pixels_yields_nan_not_a_number(self):
        gt_img, gt_depth, _, cur = _scene()
        empty = torch.zeros_like(cur)
        out = vacated_contrast_metrics(
            gt_img, gt_img, gt_depth, gt_depth, cur, empty
        )
        self.assertEqual(out["vacated_support_px"], 0)
        self.assertTrue(math.isnan(out["ghost_excess_depth_l1_cm"]))


if __name__ == "__main__":
    unittest.main()
