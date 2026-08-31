"""Functional pin for the TRACKING-side consumption of the semantic mask (exp36).

WHY THIS FILE EXISTS. exp36's trackside arm (`pba_trackside_only_*`) turns both mask
consumers off and claims the mask is still consumed in ONE place: the tracking photometric
loss, for iterations ``0..warmup_iters-1``, after which the reliability soft weight appears
and the hard mask is bypassed. That claim came from reading
``utils/slam_utils.py::get_loss_tracking_rgbd``'s branch ladder. Reading is not measuring:
these tests EXECUTE the ladder on a stub viewpoint and assert

  1. soft absent  + mask present -> the mask changes the loss   (channel live)
  2. soft present + mask present -> the mask does NOT change it (channel bypassed)
  3. soft present + mask present + ``hard_tracking_mask: true`` -> it changes it again

If a refactor routes the hard mask into the soft branch (or drops it), test 1/2 flip and
the trackside arm would be measuring a different channel than its prereg says. This is the
test that fails first.

CPU-only, no CUDA, no dataset: the loss functions take plain tensors plus a viewpoint with
``original_image`` / ``depth`` / ``grad_mask``.
"""
import os
import sys
import types
import unittest

import numpy as np
import torch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from utils.slam_utils import get_loss_tracking_rgbd  # noqa: E402

H = W = 16


def _config(hard_tracking_mask=False):
    cfg = {
        "Training": {"alpha": 0.95, "rgb_boundary_threshold": 0.01},
        "SemanticMask": {"enabled": True, "soft_strength": 1.0, "soft_floor": 0.10},
        "RobustTracking": {"enabled": False},
        "ReliableTracking": {"enabled": False},
    }
    if hard_tracking_mask:
        cfg["SemanticMask"]["hard_tracking_mask"] = True
    return cfg


def _viewpoint(gen):
    """Stub with only what the tracking losses touch."""
    return types.SimpleNamespace(
        original_image=torch.rand((3, H, W), generator=gen),
        depth=np.abs(np.random.RandomState(0).rand(H, W)).astype(np.float32) + 0.5,
        grad_mask=torch.ones((1, H, W), dtype=torch.bool),
    )


class TestTrackingMaskChannel(unittest.TestCase):
    """Baselines use an ALL-FALSE mask rather than ``mask=None`` on purpose: with no mask
    and no soft weight the ladder falls through to the vanilla RGB-D tail, whose
    ``get_loss_tracking_rgb`` hardcodes ``.cuda()`` (utils/slam_utils.py:96). Comparing
    all-false vs half-true keeps BOTH sides on the same function and isolates the only
    thing under test -- the mask's content."""

    @classmethod
    def setUpClass(cls):
        gen = torch.Generator().manual_seed(7)
        cls.view = _viewpoint(gen)
        cls.image = torch.rand((3, H, W), generator=gen)
        cls.depth = torch.rand((1, H, W), generator=gen) + 0.5
        cls.opacity = torch.ones((1, H, W))
        # a mask over the left half -- big enough that excluding it must move the loss
        cls.mask = torch.zeros((1, H, W), dtype=torch.bool)
        cls.mask[:, :, : W // 2] = True
        cls.none_mask = torch.zeros((1, H, W), dtype=torch.bool)   # excludes nothing
        cls.all_mask = torch.ones((1, H, W), dtype=torch.bool)     # excludes everything
        # a soft weight that is deliberately NOT the mask, so the two paths are separable
        cls.soft = torch.full((1, H, W), 0.30)

    def _loss(self, cfg, mask=None, soft=None):
        return float(
            get_loss_tracking_rgbd(
                cfg, self.image, self.depth, self.opacity, self.view,
                tracking_dynamic_mask=mask, tracking_dynamic_soft=soft,
            ).detach()
        )

    def test_mask_is_live_when_no_soft_weight_exists(self):
        """Iterations 0..warmup-1: reliability_soft is still None (slam_frontend.py:1040)."""
        cfg = _config()
        self.assertNotAlmostEqual(
            self._loss(cfg, mask=self.mask), self._loss(cfg, mask=self.none_mask), places=6,
            msg="hard mask did not change the tracking loss on the no-soft path -- the "
                "trackside arm would then have NO live channel at all",
        )

    def test_mask_is_bypassed_once_the_soft_weight_appears(self):
        """Iterations >= warmup: reliability_soft is set (slam_frontend.py:1213), and this
        arm family does not set hard_tracking_mask, so the mask is dropped."""
        cfg = _config()
        self.assertAlmostEqual(
            self._loss(cfg, mask=self.mask, soft=self.soft),
            self._loss(cfg, mask=self.none_mask, soft=self.soft), places=6,
            msg="the hard mask still affects the loss on the soft path without "
                "hard_tracking_mask -- exp36's '10 of at most 100 iterations' window is wrong",
        )

    def test_hard_tracking_mask_flag_restores_the_mask_on_the_soft_path(self):
        """Negative control for the test above: the bypass is the FLAG's doing, not an
        artifact of the stub (only p6_mason configs set this flag)."""
        cfg = _config(hard_tracking_mask=True)
        self.assertNotAlmostEqual(
            self._loss(cfg, mask=self.mask, soft=self.soft),
            self._loss(cfg, mask=self.none_mask, soft=self.soft), places=6,
            msg="hard_tracking_mask=true did not re-admit the mask -- then the flag is "
                "dead code and the bypass claim rests on nothing",
        )

    def test_mask_enters_as_an_exclusion_not_a_weight(self):
        """Masking every pixel must not silently equal masking none: the mask shrinks the
        loss's support set, it is not a per-pixel weight."""
        cfg = _config()
        self.assertNotAlmostEqual(
            self._loss(cfg, mask=self.all_mask), self._loss(cfg, mask=self.none_mask),
            places=6,
            msg="masking every pixel equals masking none -- the mask is being ignored",
        )


if __name__ == "__main__":
    unittest.main()
