"""Unit tests for the reliability signal core (utils/reliability_signal.py, method #8).

Pure CPU tensor tests: no RAFT, no GPU render, no dataset. Verifies the doc-10 §1
math: threshold-free MAD anomaly, rigid-flow geometry, K-frame persistence,
opacity-gated fusion, and the no-harm Cauchy weight.
"""

import math
import unittest

import torch

from utils.reliability_signal import (
    assemble_flow_consensus,
    backward_warp,
    cauchy_tracking_weight,
    compute_reliability_tracking_weight,
    flow_anomaly,
    fuse_static_evidence,
    geometric_anomaly,
    kframe_consensus,
    relative_pose_target_from_source,
    reliability_signal_enabled,
    rigid_flow,
    robust_anomaly,
)


class RobustAnomalyTests(unittest.TestCase):
    def test_constant_is_zero(self):
        v = torch.full((4, 4), 2.0)
        out = robust_anomaly(v)
        self.assertLess(float(out.max()), 1e-3)

    def test_single_outlier_flagged(self):
        v = torch.ones(2, 4)
        v[1, 3] = 10.0
        out = robust_anomaly(v)
        self.assertGreater(float(out[1, 3]), 0.99)
        out[1, 3] = 0.0
        self.assertLess(float(out.max()), 1e-3)

    def test_invalid_excluded_from_stats_and_output(self):
        v = torch.tensor([[1.0, 1.0, 1.0, 100.0]])
        valid = torch.tensor([[True, True, True, False]])
        out = robust_anomaly(v, valid)  # the 100 must not blow up the scale
        self.assertLess(float(out.max()), 1e-3)


class RigidFlowTests(unittest.TestCase):
    def test_identity_pose_zero_flow(self):
        depth = torch.full((8, 8), 2.0)
        R = torch.eye(3)
        t = torch.zeros(3)
        flow, valid = rigid_flow(depth, 100.0, 100.0, 50.0, 50.0, R, t)
        self.assertTrue(bool(valid.all()))
        self.assertLess(float(flow.abs().max()), 1e-4)

    def test_pure_translation_matches_analytic(self):
        fx = 100.0
        z = 2.0
        tx = 0.1
        depth = torch.full((64, 64), z)  # realistic-size image so predictions stay in-bounds
        flow, valid = rigid_flow(depth, fx, fx, 32.0, 32.0, torch.eye(3), torch.tensor([tx, 0.0, 0.0]))
        expected_u = fx * tx / z  # = 5 px, constant over all pixels
        self.assertAlmostEqual(float(flow[valid][..., 0].mean()), expected_u, places=3)
        self.assertLess(float(flow[valid][..., 1].abs().max()), 1e-4)


class FlowAnomalyTests(unittest.TestCase):
    def test_agreement_is_static(self):
        f = torch.randn(6, 6, 2)
        out = flow_anomaly(f, f.clone())
        self.assertLess(float(out.max()), 1e-3)

    def test_disagreement_flagged(self):
        f_static = torch.zeros(4, 4, 2)
        f_obs = torch.zeros(4, 4, 2)
        f_obs[0, 0] = torch.tensor([20.0, 0.0])  # one strongly-moving pixel
        out = flow_anomaly(f_obs, f_static)
        self.assertGreater(float(out[0, 0]), 0.99)


class KFrameConsensusTests(unittest.TestCase):
    def test_minority_spike_ignored(self):
        stack = torch.full((5, 3, 3), 0.1)
        stack[2] = 0.9  # one spiking frame
        e, valid = kframe_consensus(stack)
        self.assertTrue(bool(valid.all()))
        self.assertAlmostEqual(float(e.mean()), 0.1, places=5)

    def test_persistent_majority_survives(self):
        stack = torch.full((5, 3, 3), 0.1)
        stack[0] = stack[1] = stack[2] = 0.9
        e, _ = kframe_consensus(stack)
        self.assertAlmostEqual(float(e.mean()), 0.9, places=5)

    def test_masking_and_all_invalid(self):
        stack = torch.full((5, 2, 2), 0.8)
        valid = torch.zeros(5, 2, 2, dtype=torch.bool)
        valid[0] = valid[1] = True  # only 2 valid frames
        e, fv = kframe_consensus(stack, valid)
        self.assertAlmostEqual(float(e[0, 0]), 0.8, places=5)
        # a pixel with no valid frame -> nan + invalid
        valid2 = torch.zeros(5, 2, 2, dtype=torch.bool)
        e2, fv2 = kframe_consensus(stack, valid2)
        self.assertFalse(bool(fv2.any()))
        self.assertTrue(math.isnan(float(e2[0, 0])))


class FusionTests(unittest.TestCase):
    def test_ranges_and_opacity_gating(self):
        g = torch.ones(3, 3)  # high geometric residual everywhere
        e = torch.zeros(3, 3)  # no motion
        v_high = torch.ones(3, 3)  # mapped region
        v_low = torch.zeros(3, 3)  # unmapped / newly revealed
        s_mapped = fuse_static_evidence(g, e, v_high)  # dynamic change over map -> low
        s_new = fuse_static_evidence(g, e, v_low)  # new static geometry -> high
        self.assertLess(float(s_mapped.max()), 1e-4)
        self.assertGreater(float(s_new.min()), 1.0 - 1e-4)

    def test_motion_lowers_s_and_nan_flow_is_neutral(self):
        g = torch.zeros(2, 2)
        v = torch.ones(2, 2)
        e = torch.tensor([[0.0, 0.6], [float("nan"), 1.0]])
        s = fuse_static_evidence(g, e, v)
        self.assertAlmostEqual(float(s[0, 0]), 1.0, places=5)
        self.assertAlmostEqual(float(s[0, 1]), 0.4, places=5)
        self.assertAlmostEqual(float(s[1, 0]), 1.0, places=5)  # nan flow -> neutral
        self.assertAlmostEqual(float(s[1, 1]), 0.0, places=5)


class CauchyWeightTests(unittest.TestCase):
    def test_all_static_is_no_harm(self):
        s = torch.ones(4, 4)
        w = cauchy_tracking_weight(s)
        self.assertGreater(float(w.min()), 1.0 - 1e-6)

    def test_monotonic_decreasing_and_bounded(self):
        s = torch.tensor([1.0, 0.8, 0.5, 0.2])
        w = cauchy_tracking_weight(s)
        self.assertAlmostEqual(float(w[0]), 1.0, places=6)
        self.assertTrue(bool((w[:-1] > w[1:]).all()))
        self.assertTrue(bool(((w > 0) & (w <= 1.0 + 1e-6)).all()))


class GeometricAnomalyTests(unittest.TestCase):
    def test_match_is_zero_and_mismatch_flagged(self):
        obs = torch.full((3, 3), 2.0)
        ren = torch.full((3, 3), 2.0)
        ren[1, 1] = 3.0  # 1 m depth error at one pixel
        g = geometric_anomaly(obs, ren)
        self.assertGreater(float(g[1, 1]), 0.99)
        g[1, 1] = 0.0
        self.assertLess(float(g.max()), 1e-3)

    def test_invalid_depth_excluded(self):
        obs = torch.full((1, 4), 2.0)
        ren = torch.tensor([[2.0, 2.0, 2.0, 0.0]])  # last pixel unmapped (render depth 0)
        g = geometric_anomaly(obs, ren)
        self.assertEqual(float(g[0, 3]), 0.0)  # invalid depth -> 0, not an anomaly


class RobustnessGuardTests(unittest.TestCase):
    def test_mad_zero_saturation_is_declared(self):
        # >50% identical -> MAD=0 -> scale=eps -> tiny deviation saturates. Declared behaviour.
        v = torch.full((3, 3), 1.0)
        v[0, 0] = 1.0 + 1e-3
        out = robust_anomaly(v)
        self.assertGreater(float(out[0, 0]), 0.99)

    def test_scale_floor_mitigates_mad_collapse(self):
        # Same MAD=0 collapse, but a noise-floor prior (>> the 1e-3 deviation) keeps
        # the noise-magnitude residual well below saturation -> static no-harm.
        v = torch.full((3, 3), 1.0)
        v[0, 0] = 1.0 + 1e-3
        self.assertGreater(float(robust_anomaly(v)[0, 0]), 0.99)  # collapses without floor
        floored = robust_anomaly(v, scale_floor=0.1)
        self.assertLess(float(floored[0, 0]), 0.05)  # noise stays sub-saturation

    def test_scale_floor_preserves_real_outlier(self):
        # A genuine outlier (>> floor) still flags ~1: the floor de-sensitises noise,
        # NOT real motion.
        v = torch.ones(3, 3)
        v[0, 0] = 10.0
        self.assertGreater(float(robust_anomaly(v, scale_floor=0.1)[0, 0]), 0.99)

    def test_scale_floor_default_is_noop(self):
        v = torch.tensor([[1.0, 1.2, 1.0, 5.0], [1.1, 1.0, 2.0, 1.0]])
        self.assertTrue(
            torch.allclose(robust_anomaly(v), robust_anomaly(v, scale_floor=0.0))
        )

    def test_flow_anomaly_scale_floor_suppresses_noise(self):
        fs = torch.zeros(3, 3, 2)
        fo = torch.zeros(3, 3, 2)
        fo[0, 0, 0] = 1e-3  # sub-pixel flow noise on an otherwise-static (MAD=0) frame
        self.assertGreater(float(flow_anomaly(fo, fs)[0, 0]), 0.99)
        self.assertLess(float(flow_anomaly(fo, fs, scale_floor=0.5)[0, 0]), 0.05)

    def test_geometric_anomaly_scale_floor_suppresses_noise(self):
        ren = torch.full((3, 3), 2.0)
        obs = torch.full((3, 3), 2.0)
        obs[0, 0] = 2.0 + 1e-3  # mm-level depth noise on a MAD=0 frame
        self.assertGreater(float(geometric_anomaly(obs, ren)[0, 0]), 0.99)
        self.assertLess(float(geometric_anomaly(obs, ren, scale_floor=0.03)[0, 0]), 0.05)

    def test_nan_input_excluded_not_propagated(self):
        v = torch.ones(2, 3)
        v[0, 0] = float("nan")
        out = robust_anomaly(v)  # valid=None -> nan auto-excluded from stats + output
        self.assertTrue(bool(torch.isfinite(out).all()))
        self.assertEqual(float(out[0, 0]), 0.0)

    def test_outputs_are_detached(self):
        obs = torch.full((3, 3), 2.0, requires_grad=True)
        ren = torch.full((3, 3), 2.5, requires_grad=True)
        g = geometric_anomaly(obs, ren)
        s = fuse_static_evidence(g, torch.zeros(3, 3), torch.ones(3, 3, requires_grad=True))
        w = cauchy_tracking_weight(s)
        self.assertFalse(g.requires_grad)
        self.assertFalse(s.requires_grad)
        self.assertFalse(w.requires_grad)

    def test_cauchy_handles_nan_s_as_neutral(self):
        s = torch.ones(2, 2)
        s[0, 0] = float("nan")
        w = cauchy_tracking_weight(s)
        self.assertAlmostEqual(float(w[0, 0]), 1.0, places=6)
        self.assertTrue(bool(torch.isfinite(w).all()))

    def test_consensus_nan_marked_valid_is_handled(self):
        stack = torch.full((3, 2, 2), 0.5)
        stack[0, 0, 0] = float("nan")
        valid = torch.ones(3, 2, 2, dtype=torch.bool)  # nan wrongly marked valid
        e, fv = kframe_consensus(stack, valid)
        self.assertTrue(bool(torch.isfinite(e[fv]).all()))

    def test_even_k_tie_resolves_conservative(self):
        stack = torch.stack(
            [torch.full((2, 2), 0.1), torch.full((2, 2), 0.1),
             torch.full((2, 2), 0.9), torch.full((2, 2), 0.9)]
        )
        e, _ = kframe_consensus(stack)  # 2 low / 2 high -> lower median -> static
        self.assertAlmostEqual(float(e.mean()), 0.1, places=5)


class RigidFlowGuardTests(unittest.TestCase):
    def test_yaw_rotation_flow_nonzero_and_finite(self):
        depth = torch.full((16, 16), 2.0)
        th = 0.05
        R = torch.tensor(
            [[math.cos(th), 0.0, math.sin(th)],
             [0.0, 1.0, 0.0],
             [-math.sin(th), 0.0, math.cos(th)]]
        )
        flow, valid = rigid_flow(depth, 100.0, 100.0, 8.0, 8.0, R, torch.zeros(3))
        self.assertTrue(bool(torch.isfinite(flow[valid]).all()))
        self.assertGreater(float(flow[valid].abs().max()), 0.0)

    def test_inf_depth_invalid_no_nan_leak(self):
        depth = torch.full((8, 8), 2.0)
        depth[0, 0] = float("inf")
        flow, valid = rigid_flow(depth, 100.0, 100.0, 4.0, 4.0, torch.eye(3), torch.zeros(3))
        self.assertFalse(bool(valid[0, 0]))  # inf depth -> invalid
        self.assertTrue(bool(valid[4, 4]))  # a normal pixel stays valid under identity
        self.assertTrue(bool(torch.isfinite(flow).all()))  # no NaN leak

    def test_offimage_projection_invalid(self):
        depth = torch.full((8, 8), 1.0)
        # huge lateral translation -> static prediction leaves the image -> invalid
        flow, valid = rigid_flow(depth, 100.0, 100.0, 4.0, 4.0, torch.eye(3), torch.tensor([50.0, 0.0, 0.0]))
        self.assertFalse(bool(valid.all()))
        self.assertTrue(bool(torch.isfinite(flow).all()))


class RelativePoseTests(unittest.TestCase):
    def test_identity(self):
        R, t = relative_pose_target_from_source(torch.eye(4), torch.eye(4))
        self.assertTrue(bool(torch.allclose(R, torch.eye(3), atol=1e-6)))
        self.assertLess(float(t.abs().max()), 1e-6)

    def test_translation_composition(self):
        ts = torch.eye(4)
        tt = torch.eye(4)
        tt[:3, 3] = torch.tensor([0.1, 0.2, 0.3])
        R, t = relative_pose_target_from_source(tt, ts)
        self.assertTrue(bool(torch.allclose(R, torch.eye(3), atol=1e-6)))
        self.assertTrue(bool(torch.allclose(t, torch.tensor([0.1, 0.2, 0.3]), atol=1e-6)))


class BackwardWarpTests(unittest.TestCase):
    def test_zero_flow_identity(self):
        field = torch.arange(16.0).reshape(4, 4)
        out, valid = backward_warp(field, torch.zeros(4, 4, 2))
        self.assertTrue(torch.allclose(out, field, atol=1e-4))
        self.assertTrue(bool(valid.all()))

    def test_constant_shift_reads_neighbor(self):
        w = 6
        field = torch.arange(float(w)).view(1, w).expand(4, w).contiguous()
        flow = torch.zeros(4, w, 2)
        flow[..., 0] = 1.0  # current pixel u reads source at u-1
        out, valid = backward_warp(field, flow)
        self.assertAlmostEqual(float(out[0, 3]), 2.0, places=4)
        self.assertFalse(bool(valid[0, 0]))  # column 0 -> source x=-1 out of bounds

    def test_out_of_bounds_invalid(self):
        flow = torch.zeros(4, 4, 2)
        flow[..., 0] = 100.0
        _, valid = backward_warp(torch.ones(4, 4), flow)
        self.assertFalse(bool(valid.any()))

    def test_source_validity_propagates(self):
        valid = torch.ones(4, 4, dtype=torch.bool)
        valid[0, 0] = False
        _, wv = backward_warp(torch.ones(4, 4), torch.zeros(4, 4, 2), valid)
        self.assertFalse(bool(wv[0, 0]))
        self.assertTrue(bool(wv[2, 2]))


class AssembleFlowConsensusTests(unittest.TestCase):
    def _static(self, h=4, w=4):
        return torch.zeros(h, w, 2), torch.zeros(h, w, 2), torch.ones(h, w, dtype=torch.bool)

    def test_current_frame_static_is_zero(self):
        fo, fs, v = self._static()
        e, fv = assemble_flow_consensus([fo], [fs], [v])
        self.assertTrue(bool(fv.all()))
        self.assertLess(float(e.max()), 1e-3)

    def test_current_frame_mover_flagged_in_place(self):
        # backward flow: current mover at (1,1) moves, ego predicts 0 -> flagged AT (1,1),
        # NO warp (k=0 is current-anchored). This is the load-bearing correctness property.
        fo, fs, v = self._static()
        fo[1, 1] = torch.tensor([15.0, 0.0])
        e, _ = assemble_flow_consensus([fo], [fs], [v])
        self.assertGreater(float(e[1, 1]), 0.99)
        e[1, 1] = 0.0
        self.assertLess(float(e.max()), 1e-3)

    def test_kframe_persistence_vs_glitch(self):
        # zero OBSERVED flow -> identity warps; inject disagreement via f_static so the
        # consensus (median over K) is isolated from any warp displacement.
        h = w = 3
        fos = [torch.zeros(h, w, 2) for _ in range(3)]
        fss = [torch.zeros(h, w, 2) for _ in range(3)]
        vs = [torch.ones(h, w, dtype=torch.bool) for _ in range(3)]
        for fs in fss:
            fs[0, 0] = torch.tensor([9.0, 0.0])  # persistent disagreement in all 3
        fss[1][2, 2] = torch.tensor([9.0, 0.0])  # 1-frame glitch
        e, _ = assemble_flow_consensus(fos, fss, vs)
        self.assertGreater(float(e[0, 0]), 0.99)  # persistent survives lower median
        self.assertLess(float(e[2, 2]), 0.5)      # 1/3 glitch killed by median

    def test_fast_mover_carried_by_current_when_older_is_oob(self):
        # 2 frames: current mover at (1,1) w/ 15px flow; older frame static. The older
        # frame's contribution at (1,1) warps to an off-image source -> invalid, so the
        # current frame alone (correctly) flags the mover -- current-frame anchoring.
        fo0, fs0, v0 = self._static()
        fo0[1, 1] = torch.tensor([15.0, 0.0])
        fo1, fs1, v1 = self._static()
        e, fv = assemble_flow_consensus([fo0, fo1], [fs0, fs1], [v0, v1])
        self.assertGreater(float(e[1, 1]), 0.99)
        self.assertTrue(bool(fv[1, 1]))

    def test_all_invalid_is_missing(self):
        fo, fs, _ = self._static()
        v = torch.zeros(4, 4, dtype=torch.bool)
        e, fv = assemble_flow_consensus([fo], [fs], [v])
        self.assertFalse(bool(fv.any()))
        self.assertTrue(bool(torch.isnan(e).all()))

    def test_length_mismatch_raises(self):
        fo, fs, v = self._static()
        with self.assertRaises(ValueError):
            assemble_flow_consensus([fo], [fs, fs], [v])

    def test_outputs_detached(self):
        fo = torch.zeros(4, 4, 2, requires_grad=True)
        fs = torch.zeros(4, 4, 2, requires_grad=True)
        e, _ = assemble_flow_consensus([fo], [fs], [torch.ones(4, 4, dtype=torch.bool)])
        self.assertFalse(e.requires_grad)


class ReliabilityTrackingWeightTests(unittest.TestCase):
    def _inputs(self, h=8, w=8):
        obs = torch.full((h, w), 2.0)
        ren = torch.full((h, w), 2.0)
        opac = torch.ones(h, w)
        f_obs = torch.zeros(h, w, 2)
        return obs, ren, opac, f_obs, torch.eye(3), torch.zeros(3)

    def test_static_frame_is_no_harm(self):
        obs, ren, opac, f_obs, R, t = self._inputs()
        s, w, fv, st = compute_reliability_tracking_weight(
            obs, ren, opac, f_obs, R, t, 100.0, 100.0, 4.0, 4.0
        )
        self.assertGreater(float(w.min()), 1.0 - 1e-3)   # w ~ 1 everywhere
        self.assertGreater(st["mean_s"], 1.0 - 1e-3)
        self.assertEqual(tuple(fv.shape), (8, 8))        # flow_valid map surfaced
        self.assertTrue(bool(fv.all()))                  # static frame -> all supported
        self.assertFalse(w.requires_grad)

    def test_mover_is_downweighted(self):
        obs, ren, opac, f_obs, R, t = self._inputs()
        f_obs[3, 3] = torch.tensor([15.0, 0.0])  # observed motion; ego (identity) predicts 0
        s, w, fv, st = compute_reliability_tracking_weight(
            obs, ren, opac, f_obs, R, t, 100.0, 100.0, 4.0, 4.0
        )
        self.assertLess(float(w[3, 3]), 0.5)             # the mover is trusted less
        w[3, 3] = 1.0
        self.assertGreater(float(w.min()), 1.0 - 1e-3)   # static pixels untouched

    def test_config_gate(self):
        self.assertFalse(reliability_signal_enabled({}))
        self.assertTrue(reliability_signal_enabled({"ReliabilitySignal": {"enabled": True}}))


if __name__ == "__main__":
    unittest.main()
