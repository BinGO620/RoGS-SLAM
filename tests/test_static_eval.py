"""Unit tests for hole-safe static-background metrics (utils/static_eval.py, P-A).

Pure CPU tensor tests: no dataset, no GPU render, no network. Verifies the
hole-safe protocol from
``workspace/dynamic-3dgs-slam/03-knowledges/11-make_or_break_ablation_spec.md`` §0:
the support set excludes dynamic + invalid-GT pixels, holes are charged (not
skipped), and dynamic-region content never affects a static score.
"""

import math
import unittest

import torch

from utils.static_eval import (
    dynamic_adjacent_band_mask,
    dynamic_band_metrics,
    masked_lpips,
    masked_psnr,
    masked_ssim,
    penalized_depth_l1_cm,
    static_background_metrics,
    static_coverage,
    static_support_mask,
)


def _l1_lpips(a, b):
    # Stand-in for a real LPIPS network: order-0 perceptual proxy for tests only.
    return torch.mean(torch.abs(a - b))


class StaticSupportMaskTests(unittest.TestCase):
    def test_excludes_invalid_gt_and_dynamic(self):
        gt_depth = torch.ones(8, 8)
        gt_depth[0, :] = 0.0  # invalid depth row
        gt_depth[1, :] = float("nan")  # non-finite row
        dynamic = torch.zeros(8, 8, dtype=torch.bool)
        dynamic[:, 0] = True  # dynamic column
        m = static_support_mask(gt_depth, dynamic)
        self.assertFalse(bool(m[0, 3]))  # zero depth excluded
        self.assertFalse(bool(m[1, 3]))  # nan excluded
        self.assertFalse(bool(m[4, 0]))  # dynamic excluded
        self.assertTrue(bool(m[4, 4]))  # valid static kept

    def test_no_dynamic_mask_defaults_to_valid_depth(self):
        gt_depth = torch.ones(8, 8)
        m = static_support_mask(gt_depth, None)
        self.assertEqual(int(m.sum()), 64)


class MetricValueTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(0)
        self.h = self.w = 16
        self.gt_img = torch.rand(3, self.h, self.w)
        self.gt_depth = torch.ones(self.h, self.w) * 2.0
        self.dynamic = torch.zeros(self.h, self.w, dtype=torch.bool)
        self.dynamic[:, :4] = True  # left 4 columns dynamic

    def test_perfect_reconstruction(self):
        mask = static_support_mask(self.gt_depth, self.dynamic)
        self.assertTrue(torch.isinf(torch.tensor(masked_psnr(self.gt_img, self.gt_img, mask))))
        self.assertAlmostEqual(masked_ssim(self.gt_img, self.gt_img, mask), 1.0, places=4)
        self.assertAlmostEqual(
            penalized_depth_l1_cm(self.gt_depth, self.gt_depth, mask, d_max_cm=50.0),
            0.0,
            places=5,
        )
        self.assertAlmostEqual(static_coverage(self.gt_depth, mask), 1.0, places=5)

    def test_noisy_reconstruction_is_finite_and_high(self):
        pred = (self.gt_img + 0.01 * torch.randn_like(self.gt_img)).clamp(0, 1)
        mask = static_support_mask(self.gt_depth, self.dynamic)
        psnr = masked_psnr(pred, self.gt_img, mask)
        self.assertTrue(torch.isfinite(torch.tensor(psnr)))
        self.assertGreater(psnr, 20.0)


class DynamicRegionIsolationTests(unittest.TestCase):
    """Corrupting the dynamic region must NOT change any static score."""

    def setUp(self):
        torch.manual_seed(1)
        self.h = self.w = 16
        self.gt_img = torch.rand(3, self.h, self.w)
        self.pred = (self.gt_img + 0.02 * torch.randn_like(self.gt_img)).clamp(0, 1)
        self.gt_depth = torch.ones(self.h, self.w) * 2.0
        self.pred_depth = self.gt_depth.clone()
        self.dynamic = torch.zeros(self.h, self.w, dtype=torch.bool)
        self.dynamic[:, :6] = True

    def test_static_metrics_invariant_to_dynamic_corruption(self):
        mask = static_support_mask(self.gt_depth, self.dynamic)
        base = {
            "psnr": masked_psnr(self.pred, self.gt_img, mask),
            "ssim": masked_ssim(self.pred, self.gt_img, mask),
            "depth": penalized_depth_l1_cm(self.pred_depth, self.gt_depth, mask, 50.0),
            "lpips": masked_lpips(self.pred, self.gt_img, mask, _l1_lpips),
        }
        corrupt = self.pred.clone()
        corrupt[:, :, :6] = 0.0  # trash the dynamic region only
        corrupt_depth = self.pred_depth.clone()
        corrupt_depth[:, :6] = 0.0
        self.assertAlmostEqual(
            masked_psnr(corrupt, self.gt_img, mask), base["psnr"], places=4
        )
        self.assertAlmostEqual(
            penalized_depth_l1_cm(corrupt_depth, self.gt_depth, mask, 50.0),
            base["depth"],
            places=5,
        )
        # SSIM: mask-normalized moments exclude out-of-mask pixels, so corrupting
        # the dynamic region (even adjacent to the boundary) cannot change it.
        self.assertAlmostEqual(
            masked_ssim(corrupt, self.gt_img, mask), base["ssim"], places=5
        )
        # LPIPS: GT-context compositing makes the dynamic region == gt in both
        # inputs, so corrupting it cannot change the masked LPIPS.
        self.assertAlmostEqual(
            masked_lpips(corrupt, self.gt_img, mask, _l1_lpips), base["lpips"], places=5
        )


class HolePenaltyTests(unittest.TestCase):
    def setUp(self):
        self.h = self.w = 16
        self.gt_depth = torch.ones(self.h, self.w) * 2.0
        self.dynamic = torch.zeros(self.h, self.w, dtype=torch.bool)

    def test_missing_depth_charged_dmax_and_lowers_coverage(self):
        mask = static_support_mask(self.gt_depth, self.dynamic)  # all 256 static
        pred_depth = self.gt_depth.clone()
        pred_depth[:8, :] = 0.0  # half the static region is a hole (invalid render)
        # coverage should be ~0.5
        self.assertAlmostEqual(static_coverage(pred_depth, mask), 0.5, places=5)
        # penalized depth: matched half contributes 0, hole half contributes d_max
        pen = penalized_depth_l1_cm(pred_depth, self.gt_depth, mask, d_max_cm=30.0)
        self.assertAlmostEqual(pen, 0.5 * 30.0, places=3)

    def test_opacity_threshold_reduces_coverage(self):
        mask = static_support_mask(self.gt_depth, self.dynamic)
        pred_depth = self.gt_depth.clone()
        opacity = torch.ones(self.h, self.w)
        opacity[:4, :] = 0.1  # below a_eval -> not covered
        cov = static_coverage(pred_depth, mask, render_opacity=opacity, a_eval=0.5)
        self.assertAlmostEqual(cov, 1.0 - 4.0 / 16.0, places=5)


class BundleTests(unittest.TestCase):
    def test_bundle_keys_and_mask_type(self):
        h = w = 16
        gt_img = torch.rand(3, h, w)
        gt_depth = torch.ones(h, w) * 2.0
        out = static_background_metrics(
            gt_img, gt_img, gt_depth, gt_depth, dynamic_mask=None,
            d_max_cm=50.0, lpips_fn=_l1_lpips,
        )
        self.assertEqual(out["mask_type"], "static")
        for key in (
            "static_psnr", "static_ssim", "static_depth_l1_pen_cm",
            "static_coverage", "static_lpips", "static_support_px",
        ):
            self.assertIn(key, out)
        self.assertEqual(out["static_support_px"], h * w)


class EmptyMaskTests(unittest.TestCase):
    """All-dynamic (or all-invalid-GT) frame -> empty support -> uniform NaN policy."""

    def test_all_dynamic_frame_yields_nan_everywhere(self):
        h = w = 16
        img = torch.rand(3, h, w)
        depth = torch.ones(h, w) * 2.0
        dynamic = torch.ones(h, w, dtype=torch.bool)  # everything dynamic
        mask = static_support_mask(depth, dynamic)
        self.assertEqual(int(mask.sum()), 0)
        self.assertTrue(math.isnan(masked_psnr(img, img, mask)))
        self.assertTrue(math.isnan(masked_ssim(img, img, mask)))
        self.assertTrue(math.isnan(penalized_depth_l1_cm(depth, depth, mask, 50.0)))
        self.assertTrue(math.isnan(static_coverage(depth, mask)))
        self.assertTrue(math.isnan(masked_lpips(img, img, mask, _l1_lpips)))


class ParamValidationTests(unittest.TestCase):
    def test_bad_dmax_and_aeval_raise(self):
        h = w = 8
        depth = torch.ones(h, w)
        mask = static_support_mask(depth, None)
        with self.assertRaises(ValueError):
            penalized_depth_l1_cm(depth, depth, mask, -1.0)
        with self.assertRaises(ValueError):
            penalized_depth_l1_cm(depth, depth, mask, float("inf"))
        with self.assertRaises(ValueError):
            static_coverage(depth, mask, render_opacity=torch.ones(h, w), a_eval=2.0)


class PartialDynamicHoleTests(unittest.TestCase):
    def test_only_static_holes_affect_coverage(self):
        h = w = 16
        depth = torch.ones(h, w) * 2.0
        dynamic = torch.zeros(h, w, dtype=torch.bool)
        dynamic[:, :8] = True  # left half dynamic -> right half (128px) static
        mask = static_support_mask(depth, dynamic)
        self.assertEqual(int(mask.sum()), 128)
        pred_depth = depth.clone()
        pred_depth[:, :8] = 0.0  # holes in dynamic region -> must be ignored
        pred_depth[:4, 8:] = 0.0  # holes in static region: 4 rows x 8 cols = 32
        self.assertAlmostEqual(static_coverage(pred_depth, mask), (128 - 32) / 128, places=5)


class DynamicAdjacentBandTests(unittest.TestCase):
    """Band = dilate(dyn, r) AND NOT dyn AND valid-GT — the discriminating ring."""

    def setUp(self):
        self.h = self.w = 40
        self.gt_depth = torch.ones(self.h, self.w)
        self.dyn = torch.zeros(self.h, self.w, dtype=torch.bool)
        self.dyn[15:25, 15:25] = True  # 10x10 dynamic block

    def test_band_excludes_dynamic_and_grows_with_radius(self):
        prev = 0
        for r in (1, 5, 10):
            band = dynamic_adjacent_band_mask(self.gt_depth, self.dyn, r)
            self.assertFalse(bool((band & self.dyn).any()))  # never overlaps dynamic
            n = int(band.sum())
            self.assertGreater(n, prev)  # monotone in radius
            prev = n

    def test_band_excludes_invalid_gt(self):
        gt = self.gt_depth.clone()
        gt[10:30, 10] = 0.0  # invalid column adjacent to the block
        band = dynamic_adjacent_band_mask(gt, self.dyn, 5)
        self.assertFalse(bool(band[20, 10]))  # invalid-GT pixel dropped from band

    def test_metrics_perfect_and_noisy(self):
        pred = torch.rand(3, self.h, self.w)
        gt = pred.clone()
        m = dynamic_band_metrics(pred, gt, self.gt_depth, self.gt_depth, self.dyn, [5, 10])
        self.assertTrue(math.isinf(m["band5"]["psnr"]))  # identical -> inf PSNR
        self.assertGreater(m["band10"]["support_px"], m["band5"]["support_px"])
        gt2 = (gt + 0.1).clamp(0, 1)
        m2 = dynamic_band_metrics(pred, gt2, self.gt_depth, self.gt_depth, self.dyn, [5])
        self.assertTrue(math.isfinite(m2["band5"]["psnr"]))

    def test_empty_band_is_nan_not_crash(self):
        dyn0 = torch.zeros(self.h, self.w, dtype=torch.bool)  # no dynamic -> empty ring
        m = dynamic_band_metrics(
            torch.rand(3, self.h, self.w), torch.rand(3, self.h, self.w),
            self.gt_depth, self.gt_depth, dyn0, [5],
        )
        self.assertEqual(m["band5"]["support_px"], 0)
        self.assertTrue(math.isnan(m["band5"]["psnr"]))


if __name__ == "__main__":
    unittest.main()
