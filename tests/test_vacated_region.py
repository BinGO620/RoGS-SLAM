"""Unit tests for the vacated-region (ghost-contamination) metric.

Pure CPU tensor tests mirroring tests/test_static_eval.py: the support is
``(∪ earlier dynamic) ∧ ¬(dynamic now) ∧ (valid GT)``, ghosts left where the
mover used to be are scored, holes are charged d_max, and the mover's CURRENT
footprint never leaks into the score.
"""

import math
import os
import sys
import unittest

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.static_eval import (  # noqa: E402
    vacated_region_mask,
    vacated_region_metrics,
)


def _scene(h=8, w=8):
    gt_img = torch.rand(3, h, w)
    gt_depth = torch.ones(h, w) * 2.0
    past = torch.zeros(h, w, dtype=torch.bool)
    past[2:5, 2:5] = True  # mover WAS here (frames < t)
    cur = torch.zeros(h, w, dtype=torch.bool)
    cur[2:5, 6:8] = True  # mover IS here now (disjoint)
    return gt_img, gt_depth, past, cur


class VacatedRegionMaskTests(unittest.TestCase):
    def test_support_is_past_minus_current_and_valid(self):
        _, gt_depth, past, cur = _scene()
        m = vacated_region_mask(gt_depth, cur, past)
        self.assertEqual(int(m.sum()), 9)  # the full 3x3 vacated square
        self.assertTrue(bool(m[3, 3]))
        self.assertFalse(bool(m[3, 6]))  # current footprint excluded

    def test_current_dynamic_overlap_excluded(self):
        _, gt_depth, past, cur = _scene()
        cur = cur.clone()
        cur[2:5, 4] = True  # mover still covers one past column
        m = vacated_region_mask(gt_depth, cur, past)
        self.assertEqual(int(m.sum()), 6)  # 3x3 minus the still-covered column

    def test_invalid_gt_excluded(self):
        _, gt_depth, past, cur = _scene()
        gt_depth = gt_depth.clone()
        gt_depth[2, :] = float("nan")
        gt_depth[3, :] = 0.0
        m = vacated_region_mask(gt_depth, cur, past)
        self.assertEqual(int(m.sum()), 3)  # only row 4 of the square survives


class VacatedRegionMetricsTests(unittest.TestCase):
    def test_perfect_render_scores_clean(self):
        gt_img, gt_depth, past, cur = _scene()
        out = vacated_region_metrics(
            gt_img, gt_img, gt_depth, gt_depth, cur, past, d_max_cm=50.0
        )
        self.assertEqual(out["vacated_support_px"], 9)
        self.assertTrue(math.isinf(out["vacated_psnr"]))
        self.assertAlmostEqual(out["vacated_depth_l1_pen_cm"], 0.0, places=6)

    def test_ghost_is_penalized(self):
        gt_img, gt_depth, past, cur = _scene()
        pred_img = gt_img.clone()
        pred_depth = gt_depth.clone()
        pred_img[:, 2:5, 2:5] = 0.0  # ghost colour where the mover was
        pred_depth[2:5, 2:5] = 1.7  # ghost surface 30cm in front of background
        out = vacated_region_metrics(
            pred_img, gt_img, pred_depth, gt_depth, cur, past, d_max_cm=50.0
        )
        self.assertTrue(math.isfinite(out["vacated_psnr"]))
        self.assertLess(out["vacated_psnr"], 30.0)
        self.assertAlmostEqual(out["vacated_depth_l1_pen_cm"], 30.0, places=4)

    def test_ghost_outside_support_ignored(self):
        gt_img, gt_depth, past, cur = _scene()
        pred_img = gt_img.clone()
        pred_depth = gt_depth.clone()
        pred_img[:, 2:5, 6:8] = 0.0  # error only inside the CURRENT footprint
        pred_depth[2:5, 6:8] = 0.5
        out = vacated_region_metrics(
            pred_img, gt_img, pred_depth, gt_depth, cur, past, d_max_cm=50.0
        )
        self.assertTrue(math.isinf(out["vacated_psnr"]))
        self.assertAlmostEqual(out["vacated_depth_l1_pen_cm"], 0.0, places=6)

    def test_hole_charged_d_max(self):
        gt_img, gt_depth, past, cur = _scene()
        pred_depth = gt_depth.clone()
        pred_depth[2:5, 2:5] = float("nan")  # no render where the mover was
        out = vacated_region_metrics(
            gt_img, gt_img, pred_depth, gt_depth, cur, past, d_max_cm=50.0
        )
        self.assertAlmostEqual(out["vacated_depth_l1_pen_cm"], 50.0, places=4)

    def test_empty_union_gives_no_support(self):
        gt_img, gt_depth, _, cur = _scene()
        empty = torch.zeros_like(cur)
        out = vacated_region_metrics(
            gt_img, gt_img, gt_depth, gt_depth, cur, empty, d_max_cm=50.0
        )
        self.assertEqual(out["vacated_support_px"], 0)
        self.assertTrue(math.isnan(out["vacated_psnr"]))
        self.assertTrue(math.isnan(out["vacated_depth_l1_pen_cm"]))


if __name__ == "__main__":
    unittest.main()
