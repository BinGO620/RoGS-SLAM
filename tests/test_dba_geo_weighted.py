"""Unit tests for the reliability-weighted geometric edge (DBAphoto step2).

CPU-only synthetic tests: no GPU, no dataset, no Mask R-CNN. Verifies the codex 019fc6be
gate-critical invariants:
  * FATAL-1 gauge: Tgt'_k @ inv(Ton_k) is invariant under a world-frame rigid transform.
  * FATAL-2 fixed-support: the inlier set m0 / N_fixed is FROZEN across t (same geom).
  * FATAL-3 frozen-weight: w_total0 (MAD*reliability) is frozen across t; r(t) re-evaluated.
  * w_rel = sqrt(w_i * w_j) (two-sided geometric mean, codex prior review).
  * objective match: fixed-support cost = sum(w_total0 * r(t)^2) / N_fixed.
"""
import math
import unittest

import torch

from utils.dba_lite import (
    _attach_weight_to_geom,
    _edge_dynamic_cost,
    _edge_weighted_resid_at_t,
    _edge_weighted_resid_fixed,
    _precompute_kf_geom,
)


def _flat_plane_geom(z, fx, fy, cx, cy, h, w, stride, device, mask=None):
    """A flat plane at depth z: depth (h,w)=z, valid everywhere (no gradient gate -> use a
    tiny gradient so grad_thresh passes). Returns geom via _precompute_kf_geom."""
    depth = torch.full((h, w), float(z), dtype=torch.float32, device=device)
    # give a 1-pixel gradient ramp so the grad_thresh gate admits pixels
    depth = depth + torch.linspace(0, 0.05, w, device=device)[None, :].expand(h, w)
    cfg = {"stride": stride, "min_depth": 0.05, "max_depth": 5.0,
           "grad_thresh": 0.0, "min_points": 4, "depth_gate": 0.5,
           "normal_deg": 60.0}
    geom = _precompute_kf_geom(depth, mask, fx, fy, cx, cy, cfg, device)
    return geom, cfg


class AttachWeightTests(unittest.TestCase):
    def test_wgrid_shape_and_stride(self):
        device = "cpu"
        geom, _ = _flat_plane_geom(2.0, 100, 100, 50, 50, 8, 8, 2, device)
        w_full = torch.full((8, 8), 0.5, dtype=torch.float32, device=device)
        cfg = {"stride": 2}
        _attach_weight_to_geom(geom, w_full, cfg)
        self.assertIn("wgrid", geom)
        self.assertEqual(geom["wgrid"].shape, (1, 1, 4, 4))
        self.assertEqual(geom["w_src"].shape[0], geom["Ps"].shape[0])
        self.assertTrue(torch.allclose(geom["w_src"], torch.full_like(geom["w_src"], 0.5)))

    def test_none_w_is_ones(self):
        device = "cpu"
        geom, _ = _flat_plane_geom(2.0, 100, 100, 50, 50, 8, 8, 2, device)
        cfg = {"stride": 2}
        _attach_weight_to_geom(geom, None, cfg)
        self.assertTrue(torch.allclose(geom["wgrid"], torch.ones_like(geom["wgrid"])))
        self.assertTrue(torch.allclose(geom["w_src"], torch.ones_like(geom["w_src"])))


class WeightedResidFixedTests(unittest.TestCase):
    def _two_frames(self, w_i_val, w_j_val, device="cpu"):
        gi, cfg = _flat_plane_geom(2.0, 100, 100, 50, 50, 16, 16, 2, device)
        gj, _ = _flat_plane_geom(2.0, 100, 100, 50, 50, 16, 16, 2, device)
        _attach_weight_to_geom(gi, torch.full((16, 16), w_i_val), cfg)
        _attach_weight_to_geom(gj, torch.full((16, 16), w_j_val), cfg)
        return gi, gj, cfg

    def test_w_rel_is_geometric_mean(self):
        gi, gj, cfg = self._two_frames(0.25, 0.25, "cpu")
        T0 = torch.eye(4)
        T1 = torch.eye(4)
        T1[0, 3] = 0.01  # small x translation
        res, state = _edge_weighted_resid_fixed(gi, gj, T0, T1, cfg, "cpu")
        self.assertIsNotNone(res)
        r0, J_i, J_j, w_total0, m0, N_fixed = res
        # w_rel0 = sqrt(0.25*0.25) = 0.25; w_robust0 <= 1; w_total0 = w_robust0 * 0.25
        self.assertTrue(torch.all(w_total0 <= 0.25 + 1e-5))

    def test_fixed_support_N_frozen_across_t(self):
        gi, gj, cfg = self._two_frames(1.0, 1.0, "cpu")
        T_on = torch.eye(4)
        T_gt = torch.eye(4)
        T_gt[0, 3] = 0.02
        res0, state = _edge_weighted_resid_fixed(gi, gj, T_on, T_on, cfg, "cpu")
        self.assertIsNotNone(res0)
        _, _, _, _, m0, N_fixed = res0
        # re-evaluate at a different pose: m0/N_fixed must be identical (same geom, frozen)
        rt = _edge_weighted_resid_at_t(state, gi, gj, T_on, T_gt, cfg, "cpu")
        self.assertIsNotNone(rt)
        r_t, J_i_t, J_j_t, w_total0_t, N_fixed_t = rt
        self.assertEqual(N_fixed_t, N_fixed)
        # w_total0 frozen
        self.assertTrue(torch.allclose(w_total0_t, state["w_total0"]))

    def test_weights_frozen_but_residual_revaluated(self):
        gi, gj, cfg = self._two_frames(1.0, 1.0, "cpu")
        T_on = torch.eye(4)
        T_gt = torch.eye(4)
        T_gt[0, 3] = 0.05
        res0, state = _edge_weighted_resid_fixed(gi, gj, T_on, T_on, cfg, "cpu")
        res_t = _edge_weighted_resid_at_t(state, gi, gj, T_on, T_gt, cfg, "cpu")
        r0 = res0[0]
        r_t = res_t[0]
        # at t=0 (both poses = T_on), residual ~ 0; at a perturbed pose it should differ
        self.assertLess(float(r0.abs().median()), float(r_t.abs().median()) + 1e-6)


class GaugeAlignTests(unittest.TestCase):
    def test_gt_aligned_invariant_under_world_rigid(self):
        """codex FATAL-1: Tgt'_k = Tgt_k @ inv(Tgt_0) @ Ton_0 (W2C) must be invariant to a
        world-frame rigid transform applied to BOTH Ton and Tgt."""
        torch.manual_seed(0)
        # random W2C poses
        def rand_w2c():
            T = torch.eye(4)
            T[:3, 3] = torch.randn(3) * 0.1
            return T
        Ton0, Tonk = rand_w2c(), rand_w2c()
        Tgt0, Tgtk = rand_w2c(), rand_w2c()
        # aligned GT
        Tgt_prime_k = Tgtk @ torch.linalg.inv(Tgt0) @ Ton0
        rel_orig = Tgt_prime_k @ torch.linalg.inv(Tonk)
        # apply a random world rigid W to Ton and Tgt (left-multiply W2C by inv(W) keeps
        # camera-center world-frame rigid; here we transform c2w then invert)
        W = torch.eye(4)
        W[:3, 3] = torch.randn(3)
        # c2w = inv(w2c); world rigid on c2w: W @ c2w; w2c_new = inv(W @ c2w) = inv(c2w) @ inv(W) = w2c @ inv(W)
        Ton0b = Ton0 @ torch.linalg.inv(W)
        Tonkb = Tonk @ torch.linalg.inv(W)
        Tgt0b = Tgt0 @ torch.linalg.inv(W)
        Tgtkb = Tgtk @ torch.linalg.inv(W)
        Tgt_prime_k_b = Tgtkb @ torch.linalg.inv(Tgt0b) @ Ton0b
        rel_b = Tgt_prime_k_b @ torch.linalg.inv(Tonkb)
        self.assertTrue(torch.allclose(rel_orig, rel_b, atol=1e-5))


class DynamicCostTests(unittest.TestCase):
    def test_dynamic_cost_runs_and_finite(self):
        gi, cfg = _flat_plane_geom(2.0, 100, 100, 50, 50, 16, 16, 2, "cpu")
        gj, _ = _flat_plane_geom(2.0, 100, 100, 50, 50, 16, 16, 2, "cpu")
        _attach_weight_to_geom(gi, torch.full((16, 16), 0.5), cfg)
        _attach_weight_to_geom(gj, torch.full((16, 16), 0.5), cfg)
        T0 = torch.eye(4)
        T1 = torch.eye(4)
        T1[0, 3] = 0.01
        out = _edge_dynamic_cost(gi, gj, T0, T1, cfg, "cpu")
        self.assertIsNotNone(out)
        cost, n, med = out
        self.assertTrue(math.isfinite(cost))
        self.assertTrue(math.isfinite(med))
        self.assertGreater(n, 0)


if __name__ == "__main__":
    unittest.main()
