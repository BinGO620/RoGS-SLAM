"""Characterization tests for DeferredCommitManager decision logic (method #9, Step 1).

These LOCK the current promote / reject / expire / support / contradiction /
occluded / fast-promote / capacity semantics of ``DeferredCommitManager`` BEFORE
the make-or-break refactor splits the shared *decision* logic from the arm-specific
*action* (immediate / prune / deferred). codex flagged this class as untested; the
3-arm ablation is only credible if the decision engine is provably unchanged by the
refactor, so every property asserted here must survive it byte-for-byte.

Strategy: drive ``_update_batch`` -- the decision engine -- directly with synthetic
source/target cameras (identity pose, matched intrinsics => reprojection is the
identity map, so candidate pixel (x,y) samples target.depth[y,x] and the signed
depth delta is fully controlled). Pure CPU/NumPy, no GaussianModel, no CUDA.
"""

import unittest
from types import SimpleNamespace

import numpy as np
import torch

from utils.deferred_commit import DeferredCommitManager, PendingBatch

W, H = 8, 6
FX = FY = 4.0
CX, CY = 3.5, 2.5
# candidate pixels: (x=2,y=1) and (x=4,y=3); with identity pose + matched intrinsics
# they reproject to themselves, so target.depth[y,x] is the compared observation.
XS = np.array([2, 4], dtype=np.int32)
YS = np.array([1, 3], dtype=np.int32)


def _cam(uid, depth_value, gray=0.5, dynamic=None):
    """A camera whose depth map is uniform ``depth_value`` (scalar or HxW array)."""
    depth = (
        np.full((H, W), float(depth_value), dtype=np.float32)
        if np.isscalar(depth_value)
        else np.asarray(depth_value, dtype=np.float32)
    )
    return SimpleNamespace(
        uid=uid,
        depth=depth,
        original_image=torch.full((3, H, W), float(gray)),
        R=torch.eye(3),
        T=torch.zeros(3),
        fx=FX, fy=FY, cx=CX, cy=CY,
        image_width=W, image_height=H,
        dynamic_mask=dynamic,
    )


def _batch(depths=(1.0, 1.0), color_gray=0.5):
    n = len(depths)
    return PendingBatch(
        source_id=0, height=H, width=W,
        x=XS[:n].copy(), y=YS[:n].copy(),
        depth=np.asarray(depths, dtype=np.float32),
        color=np.full((n, 3), float(color_gray), dtype=np.float32),
        support=np.zeros(n, dtype=np.int16),
        contradictions=np.zeros(n, dtype=np.int16),
        pending=np.ones(n, dtype=bool),
        candidate_type=np.zeros(n, dtype=np.int8),
    )


def _rel_cam(uid, depth_value, s_val=1.0, fv_val=True, gray=0.5):
    """A target camera that also carries the frozen reliability maps R3 confirmation
    reads: uniform ``s`` and ``flow_valid`` (the single-candidate tests only sample the
    reprojected pixel, so a uniform map fully controls the observed cue)."""
    cam = _cam(uid, depth_value, gray=gray)
    cam.reliability_s = np.full((H, W), float(s_val), dtype=np.float32)
    cam.reliability_flow_valid = np.full((H, W), bool(fv_val), dtype=bool)
    return cam


class DeferredDecisionCharacterization(unittest.TestCase):
    def _mgr(self, **cfg):
        return DeferredCommitManager(config={"DeferredCommit": cfg})

    def _drive(self, mgr, batch, target_depth, n, gray=0.5, dynamic=None):
        """Call _update_batch n times against a fresh target of the given depth."""
        source = _cam(0, 1.0)
        last = None
        for _ in range(n):
            last = mgr._update_batch(batch, source, _cam(1, target_depth, gray, dynamic))
        return last

    # --- support -> promote ------------------------------------------------
    def test_single_support_does_not_promote(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        result = self._drive(mgr, batch, 1.0, 1)
        self.assertIsNone(result)
        self.assertEqual(int(batch.support[0]), 1)
        self.assertTrue(bool(batch.pending[0]))
        self.assertEqual(mgr.summary["promoted"], 0)

    def test_two_supports_promote(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        self.assertIsNone(self._drive(mgr, batch, 1.0, 1))  # support 1
        result = self._drive(mgr, batch, 1.0, 1)  # support 2 -> promote
        self.assertIsNotNone(result)
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.fast_count, 0)
        self.assertFalse(bool(batch.pending[0]))
        self.assertEqual(mgr.summary["promoted"], 1)
        # promotion depth map carries the candidate's own depth at its pixel
        self.assertAlmostEqual(float(result.depth_map[YS[0], XS[0]]), 1.0, places=5)

    # --- contradiction -> reject ------------------------------------------
    def test_two_contradictions_reject(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        self._drive(mgr, batch, 1.5, 2)  # observed 0.5m FARTHER -> surface gone
        self.assertFalse(bool(batch.pending[0]))
        self.assertEqual(mgr.summary["rejected"], 1)
        self.assertEqual(mgr.summary["promoted"], 0)

    def test_single_contradiction_keeps_pending(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        self._drive(mgr, batch, 1.5, 1)
        self.assertEqual(int(batch.contradictions[0]), 1)
        self.assertTrue(bool(batch.pending[0]))
        self.assertEqual(mgr.summary["rejected"], 0)

    # --- occluded is NOT a contradiction ----------------------------------
    def test_occluded_does_not_reject(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        self._drive(mgr, batch, 0.6, 3)  # observed CLOSER -> occluded by nearer surface
        self.assertEqual(int(batch.contradictions[0]), 0)
        self.assertEqual(mgr.summary["rejected"], 0)
        self.assertGreater(mgr.summary["occluded_observations"], 0)

    # --- unknown (invalid target depth) -----------------------------------
    def test_unknown_when_target_depth_invalid(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        self._drive(mgr, batch, 0.0, 1)  # target depth 0 -> no valid observation
        self.assertEqual(int(batch.support[0]), 0)
        self.assertEqual(int(batch.contradictions[0]), 0)
        self.assertGreater(mgr.summary["unknown_observations"], 0)

    # --- color gate blocks support even at matching depth -----------------
    def test_color_mismatch_blocks_support(self):
        mgr = self._mgr()
        batch = _batch((1.0,), color_gray=0.5)
        self._drive(mgr, batch, 1.0, 2, gray=0.95)  # depth matches, color L1 ~0.45 > 0.15
        self.assertEqual(int(batch.support[0]), 0)
        self.assertEqual(mgr.summary["promoted"], 0)

    # --- semantic dynamic mask suppresses the observation -----------------
    def test_dynamic_mask_blocks_support(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        dyn = np.zeros((H, W), dtype=bool)
        dyn[YS[0], XS[0]] = True
        self._drive(mgr, batch, 1.0, 2, dynamic=dyn)
        self.assertEqual(int(batch.support[0]), 0)
        self.assertEqual(mgr.summary["promoted"], 0)

    # --- expiry at ttl -----------------------------------------------------
    def test_expire_after_ttl(self):
        mgr = self._mgr(ttl_keyframes=3)
        batch = _batch((1.0,))
        self._drive(mgr, batch, 0.0, 2)  # unknown observations, no support/contra
        self.assertTrue(bool(batch.pending[0]))  # age 2 < ttl 3
        self._drive(mgr, batch, 0.0, 1)  # age 3 >= ttl -> expire
        self.assertFalse(bool(batch.pending[0]))
        self.assertEqual(mgr.summary["expired"], 1)

    # --- fast promotion in a single tight observation ---------------------
    def test_fast_promotion_single_call(self):
        mgr = self._mgr(fast_promotion=True)
        batch = _batch((1.0,))
        result = self._drive(mgr, batch, 1.0, 1)  # exact depth+color -> fast path
        self.assertIsNotNone(result)
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.fast_count, 1)
        self.assertEqual(mgr.summary["fast_promoted"], 1)

    # --- capacity enforcement drops the oldest pending batch --------------
    def test_capacity_drop_oldest(self):
        mgr = self._mgr(max_pending_keyframes=2)
        for i in range(4):
            b = _batch((1.0,))
            b.source_id = i
            mgr.batches.append(b)
        mgr._enforce_capacity()
        self.assertEqual(len(mgr.batches), 2)
        self.assertEqual([b.source_id for b in mgr.batches], [2, 3])  # oldest 0,1 dropped
        self.assertEqual(mgr.summary["dropped_capacity"], 2)  # each had 1 pending

    # --- initial keyframe: immediate insert + dynamic accounting ----------
    def test_process_initial_keyframe(self):
        mgr = self._mgr()
        depth = np.ones((H, W), dtype=np.float32)
        dyn = np.zeros((H, W), dtype=bool)
        dyn[0, :] = True  # one row is dynamic
        viewpoint = SimpleNamespace(uid=0)
        out = mgr.process_initial_keyframe(viewpoint, depth, dynamic_mask=dyn)
        self.assertTrue(bool((out[0, :] == 0.0).all()))  # dynamic row zeroed
        self.assertTrue(bool((out[1:, :] == 1.0).all()))  # static rows inserted
        self.assertEqual(mgr.summary["immediate_insert"], (H - 1) * W)
        self.assertEqual(mgr.summary["semantic_dynamic"], W)


class ReliabilityConfirmDecision(unittest.TestCase):
    """R3: weighted symmetric confirmation C± driven by the reliability signal s +
    flow_valid (doc-10 §6). Opt-in via ``DeferredCommit.reliability_confirm``; the target
    keyframe carries the frozen ``reliability_s`` / ``reliability_flow_valid`` maps. The
    load-bearing property is the MISSING-CUE POLICY: a view with no valid frozen-flow
    consensus is gated OUT of BOTH C⁺ and C⁻ (it neither supports nor contradicts).
    """

    def _mgr(self, **cfg):
        cfg.setdefault("reliability_confirm", True)
        return DeferredCommitManager(config={"DeferredCommit": cfg})

    def _drive(self, mgr, batch, target_depth, n, s_val=1.0, fv_val=True, gray=0.5):
        source = _cam(0, 1.0)
        last = None
        for _ in range(n):
            last = mgr._update_batch(
                batch, source, _rel_cam(1, target_depth, s_val, fv_val, gray)
            )
        return last

    # --- reliable static views promote, weighted by s*h --------------------
    def test_reliable_static_views_promote(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        self.assertIsNone(self._drive(mgr, batch, 1.0, 1))          # C+=1.0 (s*h, exact)
        result = self._drive(mgr, batch, 1.0, 1)                    # C+=2.0 -> promote
        self.assertIsNotNone(result)
        self.assertEqual(mgr.summary["promoted"], 1)
        self.assertAlmostEqual(float(batch.c_plus[0]), 2.0, places=5)  # h=1 at exact depth
        self.assertAlmostEqual(float(batch.c_minus[0]), 0.0, places=5)

    # --- an UNRELIABLE pixel earns no support even at matching depth -------
    def test_unreliable_pixel_blocks_support(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        result = self._drive(mgr, batch, 1.0, 3, s_val=0.0)  # depth matches, but s=0
        self.assertIsNone(result)
        self.assertEqual(mgr.summary["promoted"], 0)
        self.assertAlmostEqual(float(batch.c_plus[0]), 0.0, places=5)
        self.assertTrue(bool(batch.pending[0]))              # not rejected either
        self.assertEqual(int(batch.support[0]), 3)           # integer count still moves...
        # ...but the weighted decision (not the integer count) governs -> no promote.

    # --- MISSING FLOW is gated out of BOTH C+ and C- (the load-bearing policy)
    def test_missing_flow_neither_supports_nor_contradicts(self):
        mgr = self._mgr(ttl_keyframes=99)
        batch = _batch((1.0,))
        result = self._drive(mgr, batch, 1.0, 3, fv_val=False)  # exact depth, flow missing
        self.assertIsNone(result)
        self.assertAlmostEqual(float(batch.c_plus[0]), 0.0, places=5)
        self.assertAlmostEqual(float(batch.c_minus[0]), 0.0, places=5)
        self.assertTrue(bool(batch.pending[0]))                 # still pending, undecided
        self.assertEqual(mgr.summary["promoted"], 0)
        self.assertEqual(mgr.summary["rejected"], 0)

    # --- reliable contradiction (surface gone) rejects, weighted by s ------
    def test_reliable_contradiction_rejects(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        self._drive(mgr, batch, 1.5, 2, s_val=1.0)  # observed 0.5 m FARTHER -> surface gone
        self.assertFalse(bool(batch.pending[0]))
        self.assertEqual(mgr.summary["rejected"], 1)
        self.assertEqual(mgr.summary["promoted"], 0)
        self.assertAlmostEqual(float(batch.c_minus[0]), 2.0, places=5)

    # --- missing flow blocks a contradiction just as it blocks support -----
    def test_missing_flow_blocks_contradiction(self):
        mgr = self._mgr(ttl_keyframes=99)
        batch = _batch((1.0,))
        self._drive(mgr, batch, 1.5, 3, fv_val=False)  # would contradict, but flow missing
        self.assertTrue(bool(batch.pending[0]))         # NOT rejected
        self.assertEqual(mgr.summary["rejected"], 0)
        self.assertAlmostEqual(float(batch.c_minus[0]), 0.0, places=5)

    # --- occlusion (nearer surface) is still neither, under the weighted path
    def test_occlusion_is_neither_weighted(self):
        mgr = self._mgr(ttl_keyframes=99)
        batch = _batch((1.0,))
        self._drive(mgr, batch, 0.6, 3, s_val=1.0)  # observed CLOSER -> occluded
        self.assertAlmostEqual(float(batch.c_plus[0]), 0.0, places=5)
        self.assertAlmostEqual(float(batch.c_minus[0]), 0.0, places=5)
        self.assertTrue(bool(batch.pending[0]))
        self.assertGreater(mgr.summary["occluded_observations"], 0)

    # --- partial reliability needs proportionally more views (continuous N) -
    def test_partial_reliability_needs_more_views(self):
        mgr = self._mgr()
        batch = _batch((1.0,))
        self.assertIsNone(self._drive(mgr, batch, 1.0, 3, s_val=0.5))  # C+=1.5 < 2
        self.assertEqual(mgr.summary["promoted"], 0)
        result = self._drive(mgr, batch, 1.0, 1, s_val=0.5)            # C+=2.0 -> promote
        self.assertIsNotNone(result)
        self.assertEqual(mgr.summary["promoted"], 1)

    # --- with the flag OFF, the maps are inert (byte-identical integer path)
    def test_flag_off_ignores_maps(self):
        mgr = DeferredCommitManager(config={"DeferredCommit": {}})  # reliability_confirm off
        batch = _batch((1.0,))
        source = _cam(0, 1.0)
        # s=0 maps WOULD block support in the weighted path; here they must be ignored.
        for _ in range(2):
            mgr._update_batch(batch, source, _rel_cam(1, 1.0, s_val=0.0))
        self.assertEqual(mgr.summary["promoted"], 1)          # integer path promoted
        self.assertAlmostEqual(float(batch.c_plus[0]), 0.0, places=5)  # weighted untouched


if __name__ == "__main__":
    unittest.main()
