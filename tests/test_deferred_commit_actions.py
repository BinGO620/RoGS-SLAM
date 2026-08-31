"""Action-layer tests for the lifecycle decision/action split (method #9, Step 2a).

The decision engine ``_update_batch`` is locked byte-for-byte by
``tests/test_deferred_commit_decision.py``. THIS file locks the *action* layer the
three arms share it through -- the only thing that differs between
``immediate`` / ``prune`` / ``deferred`` (doc-11 make-or-break contract):

  * an uncertain pixel is inserted-now-untracked (immediate) / inserted-now-with-
    lineage (prune) / held-out-of-map (deferred);
  * on reject/expire the prune arm deletes exactly that candidate's lineage, the
    others do nothing;
  * on promote the deferred arm inserts (with lineage), the prune arm no-ops
    (already inserted), immediate never had a candidate.

Pure CPU/NumPy: synthetic cameras (identity pose + matched intrinsics => a candidate
pixel reprojects to itself, so ``target.depth[y, x]`` is the compared observation,
exactly as in the decision-engine tests) and a hand-built evidence frame (a few
foreground-conflict pixels over an otherwise unmapped/unknown background).
"""

import unittest
from types import SimpleNamespace

import numpy as np
import torch

from utils.causal_twin import UNTRACKED
from utils.deferred_commit import CandidateInsert, DeferredCommitManager

W, H = 8, 6
FX = FY = 4.0
CX, CY = 3.5, 2.5
# candidate pixels (x, y): identity pose + matched intrinsics -> reproject to self.
XS = np.array([2, 4], dtype=np.int32)
YS = np.array([1, 3], dtype=np.int32)


def _cam(uid, depth_value, gray=0.5, dynamic=None):
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


def _evidence_frame():
    """observed=1.0 everywhere (all valid); a handful of foreground-conflict candidate
    pixels (rendered=5.0 >> observed, mapped-but-not-reliable alpha=0.5); everything
    else has invalid render depth -> 'unknown' -> certain immediate insert."""
    observed = np.ones((H, W), dtype=np.float32)
    rendered = np.zeros((H, W), dtype=np.float32)
    opacity = np.zeros((H, W), dtype=np.float32)
    rendered[YS, XS] = 5.0
    opacity[YS, XS] = 0.5
    return observed, rendered, opacity


def _mgr(mode, **cfg):
    return DeferredCommitManager(
        config={"Mapping": {"lifecycle_mode": mode}, "DeferredCommit": cfg}
    )


def _process(mgr, gray=0.5):
    observed, rendered, opacity = _evidence_frame()
    viewpoint = _cam(0, observed, gray=gray)
    return mgr.process_keyframe(viewpoint, {}, observed, rendered, opacity, None)


class ClassifyActionTests(unittest.TestCase):
    """What each arm DOES with the uncertain pixels at classify time."""

    def test_immediate_folds_uncertain_and_keeps_no_batch(self):
        mgr = _mgr("immediate")
        decision = _process(mgr)
        # uncertain pixels are inserted NOW (vanilla): present in the immediate map.
        self.assertTrue(bool((decision.immediate_depth_map[YS, XS] == 1.0).all()))
        self.assertEqual(decision.candidate_inserts, [])
        self.assertEqual(decision.promotions, [])
        self.assertEqual(decision.prunes, [])
        self.assertEqual(len(mgr.batches), 0)  # no deferral, nothing tracked

    def test_deferred_holds_uncertain_out_of_map(self):
        mgr = _mgr("deferred")
        decision = _process(mgr)
        # uncertain pixels are HELD: absent from the immediate map...
        self.assertTrue(bool((decision.immediate_depth_map[YS, XS] == 0.0).all()))
        # ...but the certain (unknown) background IS inserted now.
        self.assertEqual(decision.immediate_depth_map[0, 0], 1.0)
        self.assertEqual(decision.candidate_inserts, [])  # nothing inserted yet
        self.assertEqual(len(mgr.batches), 1)  # tracked as a pending candidate batch
        self.assertEqual(mgr.batches[0].pending_count, len(XS))

    def test_prune_inserts_uncertain_now_with_lineage(self):
        mgr = _mgr("prune")
        decision = _process(mgr)
        # like deferred, uncertain is out of the immediate (o3d) depth map...
        self.assertTrue(bool((decision.immediate_depth_map[YS, XS] == 0.0).all()))
        # ...but emitted as a direct-builder candidate insert WITH lineage ids.
        self.assertEqual(len(decision.candidate_inserts), 1)
        ins = decision.candidate_inserts[0]
        self.assertIsInstance(ins, CandidateInsert)
        self.assertEqual(len(ins.lineage_ids), len(XS))
        self.assertTrue(bool((ins.lineage_ids != UNTRACKED).all()))
        # the inserted candidates == the tracked batch (same lineage), still pending.
        np.testing.assert_array_equal(ins.lineage_ids, mgr.batches[0].lineage_id)
        self.assertEqual(mgr.batches[0].pending_count, len(XS))
        self.assertEqual(mgr.summary["prune_immediate_insert"], len(XS))

    def test_all_arms_share_the_certain_immediate_map(self):
        maps = {}
        for mode in ("immediate", "prune", "deferred"):
            maps[mode] = _process(_mgr(mode)).immediate_depth_map
        # the certain (non-candidate) background is inserted identically by every arm;
        # arms differ ONLY on the candidate pixels.
        for mode in ("prune", "deferred"):
            bg = np.ones((H, W), dtype=bool)
            bg[YS, XS] = False
            np.testing.assert_array_equal(maps["immediate"][bg], maps[mode][bg])


class RejectExpireActionTests(unittest.TestCase):
    """What each arm DOES when the decision engine rejects/expires a candidate."""

    def _seed_batch(self, mgr, depth_value=1.0):
        front = np.zeros((H, W), dtype=bool)
        front[YS, XS] = True
        depth_map = np.full((H, W), float(depth_value), dtype=np.float32)
        return mgr._add_typed_batch(_cam(0, depth_value), front, np.zeros_like(front), depth_map)

    def _observe(self, mgr, target_depth, n):
        """Drive n observations of a fresh contradicting/supporting target."""
        cameras = {0: _cam(0, 1.0)}
        last = None
        for _ in range(n):
            last = mgr._update_existing(_cam(1, target_depth), cameras)
        return last

    def test_prune_reject_queues_lineage_delete(self):
        mgr = _mgr("prune")
        batch = self._seed_batch(mgr)
        expected = batch.lineage_id.copy()
        self._observe(mgr, 1.5, 2)  # 0.5 m farther twice -> contradiction -> reject
        self.assertEqual(mgr.summary["rejected"], len(XS))
        self.assertEqual(mgr.summary["pruned"], len(XS))
        self.assertCountEqual(mgr._drain_prunes(), [int(i) for i in expected])

    def test_deferred_reject_prunes_nothing(self):
        mgr = _mgr("deferred")
        self._seed_batch(mgr)
        self._observe(mgr, 1.5, 2)  # reject
        self.assertEqual(mgr.summary["rejected"], len(XS))
        self.assertEqual(mgr.summary["pruned"], 0)
        self.assertEqual(mgr._drain_prunes(), [])

    def test_deferred_promote_emits_lineage_no_prune(self):
        mgr = _mgr("deferred")
        batch = self._seed_batch(mgr)
        expected = batch.lineage_id.copy()
        promotions = self._observe(mgr, 1.0, 2)  # exact depth+color twice -> promote
        self.assertEqual(mgr.summary["promoted"], len(XS))
        self.assertEqual(len(promotions), 1)
        np.testing.assert_array_equal(
            np.sort(promotions[0].lineage_ids), np.sort(expected)
        )
        self.assertEqual(mgr._drain_prunes(), [])

    def test_prune_promote_is_a_noop_insert(self):
        mgr = _mgr("prune")
        self._seed_batch(mgr)
        promotions = self._observe(mgr, 1.0, 2)  # promote in the decision engine...
        self.assertEqual(mgr.summary["promoted"], len(XS))
        self.assertEqual(promotions, [])  # ...but no re-insert (already in the map)
        self.assertEqual(mgr._drain_prunes(), [])  # and not pruned either

    def test_prune_expire_queues_lineage_delete(self):
        mgr = _mgr("prune", ttl_keyframes=2)
        batch = self._seed_batch(mgr)
        expected = batch.lineage_id.copy()
        self._observe(mgr, 0.0, 2)  # invalid target -> unknown, no support -> ttl expire
        self.assertEqual(mgr.summary["expired"], len(XS))
        self.assertCountEqual(mgr._drain_prunes(), [int(i) for i in expected])

    def test_prune_capacity_drop_queues_lineage_delete(self):
        mgr = _mgr("prune", max_pending_keyframes=1)
        b0 = self._seed_batch(mgr)
        self._seed_batch(mgr)  # second batch pushes the first over capacity
        mgr._enforce_capacity()
        self.assertCountEqual(
            mgr._drain_prunes(), [int(i) for i in b0.lineage_id]
        )


class LineageAllocationTests(unittest.TestCase):
    def test_ids_are_unique_across_batches(self):
        mgr = _mgr("prune")
        front = np.zeros((H, W), dtype=bool)
        front[YS, XS] = True
        dm = np.ones((H, W), dtype=np.float32)
        a = mgr._add_typed_batch(_cam(0, 1.0), front, np.zeros_like(front), dm)
        b = mgr._add_typed_batch(_cam(1, 1.0), front, np.zeros_like(front), dm)
        self.assertEqual(len(set(a.lineage_id) & set(b.lineage_id)), 0)
        self.assertTrue(bool((a.lineage_id >= 0).all()))


if __name__ == "__main__":
    unittest.main()
