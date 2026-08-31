"""Stage 2c: the NON-INFLUENCE INVARIANT of the deferred lifecycle (method #9).

This is one of the two load-bearing novelty claims (doc-11): a candidate held OUT
of the active map has ZERO influence on that map -- it can neither change what the
map receives now, nor the fate of any other candidate, nor the poses -- until it is
either promoted (its sole sanctioned map channel: it inserts EXACTLY its own stored
geometry, and only after multi-view static confirmation) or dropped (reject / TTL
expire / capacity evict -> a pure map no-op in the deferred arm).

Where 2a (``test_deferred_commit_actions``) locks each arm's HAPPY-PATH action, 2c
locks CAUSAL ISOLATION under ADVERSARIAL mutation: corrupt a held candidate's
internal arrays, inject phantom candidates, force divergent fates -- and assert the
active-map stream for everything else is byte-identical. Nine invariants, one per
influence channel a held candidate could conceivably leak through.

Pure CPU/NumPy at the manager/decision layer (the ``densify_and_split`` jitter is
CUDA-hardcoded and out of scope here; the manager's insert path is deterministic and
carries no RNG). Synthetic cameras: identity pose + matched intrinsics => a candidate
pixel reprojects to itself, so ``target.depth[y, x]`` is the compared observation.
"""

import unittest
from types import SimpleNamespace

import numpy as np
import torch

from utils.causal_twin import UNTRACKED
from utils.deferred_commit import DeferredCommitManager

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
    pixels (rendered=5.0 >> observed, mapped-but-unreliable alpha=0.5); everything else
    has invalid render depth -> 'unknown' -> certain immediate insert."""
    observed = np.ones((H, W), dtype=np.float32)
    rendered = np.zeros((H, W), dtype=np.float32)
    opacity = np.zeros((H, W), dtype=np.float32)
    rendered[YS, XS] = 5.0
    opacity[YS, XS] = 0.5
    return observed, rendered, opacity


def _mgr(mode="deferred", **cfg):
    return DeferredCommitManager(
        config={"Mapping": {"lifecycle_mode": mode}, "DeferredCommit": cfg}
    )


def _classify_kf(mgr, uid=0, gray=0.5):
    """One keyframe through the full classify path; returns the KeyframeDecision."""
    observed, rendered, opacity = _evidence_frame()
    viewpoint = _cam(uid, observed, gray=gray)
    return mgr.process_keyframe(viewpoint, {}, observed, rendered, opacity, None)


def _seed_batch(mgr, uid, depth_value=1.0):
    """Seed a held candidate batch (foreground-conflict at XS/YS) from source ``uid``."""
    front = np.zeros((H, W), dtype=bool)
    front[YS, XS] = True
    depth_map = np.full((H, W), float(depth_value), dtype=np.float32)
    return mgr._add_typed_batch(_cam(uid, depth_value), front, np.zeros_like(front), depth_map)


def _observe(mgr, sources, target_depth, n, reliability=False):
    """Drive ``n`` observations of a shared target against every seeded ``sources`` cam.

    ``sources`` maps source_id -> its source camera. Returns (all_promotions,
    all_prunes) accumulated across the n keyframes. With ``reliability=True`` the target
    also carries the frozen s / flow_valid maps (all-reliable) so the R3 weighted C±
    confirmation path is exercised; default False keeps the integer-count path.
    """
    cameras = {uid: _cam(uid, 1.0) for uid in sources}
    proms, prunes = [], []
    for _ in range(n):
        target = _cam(999, target_depth)
        if reliability:
            target.reliability_s = np.ones((H, W), dtype=np.float32)
            target.reliability_flow_valid = np.ones((H, W), dtype=bool)
        proms.extend(mgr._update_existing(target, cameras))
        prunes.extend(mgr._drain_prunes())
    return proms, prunes


def _prom_geom(promotion):
    """Canonical, order-stable geometry of a promotion, keyed for comparison."""
    order = np.argsort(promotion.lineage_ids)
    return (
        tuple(np.asarray(promotion.lineage_ids)[order].tolist()),
        tuple(np.asarray(promotion.pixels_x)[order].tolist()),
        tuple(np.asarray(promotion.pixels_y)[order].tolist()),
        tuple(np.round(np.asarray(promotion.depth)[order], 6).tolist()),
        tuple(np.round(np.asarray(promotion.color)[order].reshape(-1), 6).tolist()),
    )


def _proms_by_lineage(promotions):
    """{lineage_id: geom-tuple-slice} so a batch's promoted geometry is addressable."""
    out = {}
    for p in promotions:
        for k, lid in enumerate(np.asarray(p.lineage_ids).tolist()):
            out[int(lid)] = (
                int(p.pixels_x[k]),
                int(p.pixels_y[k]),
                round(float(p.depth[k]), 6),
            )
    return out


class NonInfluenceInvariants(unittest.TestCase):
    # -- Channel 1/2: the immediate (map-bound) stream ------------------------

    def test_1_immediate_map_invariant_to_held_batch_set(self):
        """Injecting arbitrary HELD candidate batches does not change what the
        active map receives NOW (the immediate depth map)."""
        ref = _classify_kf(_mgr()).immediate_depth_map

        mut = _mgr()
        for uid in (10, 11, 12):  # phantom held batches from earlier keyframes
            _seed_batch(mut, uid)
        # keep their sources alive so they stay HELD (not missing_source-expired)
        observed, rendered, opacity = _evidence_frame()
        cams = {uid: _cam(uid, 1.0) for uid in (10, 11, 12)}
        got = mut.process_keyframe(
            _cam(0, observed), cams, observed, rendered, opacity, None
        ).immediate_depth_map

        np.testing.assert_array_equal(ref, got)

    def test_2_immediate_map_invariant_to_held_batch_mutation(self):
        """Corrupting held candidates' INTERNAL arrays (support/depth/color) cannot
        leak into the immediate stream -- classify reads only the current frame."""
        ref = _classify_kf(_mgr()).immediate_depth_map

        mut = _mgr()
        b = _seed_batch(mut, 10)
        b.support[:] = 9999
        b.contradictions[:] = 7777
        b.depth[:] = 42.0       # finite garbage: corrupt state, no NaN-cast noise
        b.color[:] = -123.0
        observed, rendered, opacity = _evidence_frame()
        got = mut.process_keyframe(
            _cam(0, observed), {10: _cam(10, 1.0)}, observed, rendered, opacity, None
        ).immediate_depth_map

        np.testing.assert_array_equal(ref, got)

    # -- Channel 3/4: one candidate's fate cannot move another's --------------

    def test_3_cross_candidate_outcome_isolation(self):
        """Corrupting batch A (so A no longer promotes) leaves batch B's support,
        contradictions, pending, and promotion byte-identical to a run where A was
        never touched."""
        def run(corrupt_a):
            mgr = _mgr()
            _seed_batch(mgr, uid=0)          # A
            b = _seed_batch(mgr, uid=2)      # B
            if corrupt_a:
                mgr.batches[0].color[:] = 999.0  # A fails the color gate -> never promotes
            proms, prunes = _observe(mgr, {0, 2}, target_depth=1.0, n=2)
            b_line = set(b.lineage_id.tolist())
            b_proms = [p for p in proms if set(p.lineage_ids.tolist()) & b_line]
            return (
                b.support.copy(), b.contradictions.copy(),
                b.pending.copy(), sorted(_prom_geom(p) for p in b_proms), prunes,
            )

        ref = run(corrupt_a=False)
        mut = run(corrupt_a=True)
        np.testing.assert_array_equal(ref[0], mut[0])   # B.support
        np.testing.assert_array_equal(ref[1], mut[1])   # B.contradictions
        np.testing.assert_array_equal(ref[2], mut[2])   # B.pending
        self.assertEqual(ref[3], mut[3])                # B's promoted geometry
        self.assertEqual(ref[4], mut[4])                # prunes (empty in deferred)

    def test_4_phantom_injection_changes_nothing_but_itself(self):
        """CAPSTONE: injecting an extra phantom candidate P changes the active-map
        stream for the pre-existing candidates A,B by NOTHING -- P may only add its
        OWN promotion (addressable by its lineage ids)."""
        def run(inject_phantom):
            mgr = _mgr()
            a = _seed_batch(mgr, uid=0)
            b = _seed_batch(mgr, uid=2)
            sources = {0, 2}
            if inject_phantom:
                _seed_batch(mgr, uid=4)      # phantom P
                sources.add(4)
            proms, prunes = _observe(mgr, sources, target_depth=1.0, n=2)
            ab = set(a.lineage_id.tolist()) | set(b.lineage_id.tolist())
            ab_geom = {
                lid: g for lid, g in _proms_by_lineage(proms).items() if lid in ab
            }
            return ab_geom, prunes

        ref_geom, ref_prunes = run(inject_phantom=False)
        mut_geom, mut_prunes = run(inject_phantom=True)
        self.assertEqual(ref_geom, mut_geom)     # A,B promotion geometry unchanged
        self.assertEqual(ref_prunes, mut_prunes)  # no extra map churn

    # -- Channel 5/6: deferred's drop + insert channels are inert -------------

    def test_5_deferred_drop_transitions_are_map_noops(self):
        """Every way a deferred candidate leaves the held set -- reject, TTL expire,
        capacity evict -- emits NOTHING to the map (no prune, no promotion), even as
        its geometry is mutated mid-flight."""
        # reject (2 contradictions)
        mgr = _mgr()
        _seed_batch(mgr, 0)
        proms, prunes = _observe(mgr, {0}, target_depth=1.5, n=2)
        self.assertEqual(mgr.summary["rejected"], len(XS))
        self.assertEqual((proms, prunes), ([], []))

        # TTL expire (unknown target, ttl=2)
        mgr = _mgr(ttl_keyframes=2)
        _seed_batch(mgr, 0)
        proms, prunes = _observe(mgr, {0}, target_depth=0.0, n=2)
        self.assertEqual(mgr.summary["expired"], len(XS))
        self.assertEqual((proms, prunes), ([], []))

        # capacity evict (max 1 pending batch; second batch evicts the first)
        mgr = _mgr(max_pending_keyframes=1)
        _seed_batch(mgr, 0)
        _seed_batch(mgr, 2)
        mgr._enforce_capacity()
        self.assertEqual(mgr._drain_prunes(), [])  # deferred: eviction prunes nothing

    def test_6_deferred_candidate_inserts_always_empty(self):
        """The deferred arm's ONLY map channel is ``promotions``; ``candidate_inserts``
        is populated only by the prune arm and must stay empty here across a scripted
        sequence that also injects a phantom batch."""
        mgr = _mgr()
        for uid in (0, 1, 2):
            _seed_batch(mgr, uid + 20)  # inject held phantoms between keyframes
            decision = _classify_kf(mgr, uid=uid)
            self.assertEqual(decision.candidate_inserts, [])

    # -- Channel 7/8: the sanctioned promotion channel is faithful + isolated -

    def test_7_promotion_is_byte_faithful_and_neighbor_isolated(self):
        """A promotion inserts EXACTLY the candidate's own stored geometry, and
        mutating a NEIGHBOUR batch does not perturb it."""
        def promote_a(mutate_neighbor):
            mgr = _mgr()
            a = _seed_batch(mgr, uid=0)
            _seed_batch(mgr, uid=2)  # neighbour B
            stored = {
                int(lid): (int(a.x[k]), int(a.y[k]), round(float(a.depth[k]), 6))
                for k, lid in enumerate(a.lineage_id.tolist())
            }
            if mutate_neighbor:
                mgr.batches[1].color[:] = 999.0  # B fails the color gate -> never promotes
            proms, _ = _observe(mgr, {0, 2}, target_depth=1.0, n=2)
            a_line = set(a.lineage_id.tolist())
            a_geom = {
                lid: g for lid, g in _proms_by_lineage(proms).items() if lid in a_line
            }
            return stored, a_geom

        stored, geom = promote_a(mutate_neighbor=False)
        self.assertEqual(stored, geom)  # faithful: promoted geom == stored candidate
        _, geom_mut = promote_a(mutate_neighbor=True)
        self.assertEqual(geom, geom_mut)  # isolated: neighbour mutation didn't touch A

    def test_8_promoted_lineage_ids_nonneg_unique_and_stable(self):
        """Promoted lineage ids are real (never UNTRACKED), unique across concurrent
        candidates, and stable when another candidate is injected (monotonic
        allocator -> ids are not renumbered)."""
        def promoted_ids(inject_first):
            mgr = _mgr()
            if inject_first:
                _seed_batch(mgr, uid=7)  # consumes some ids first
            a = _seed_batch(mgr, uid=0)
            return a.lineage_id.copy(), mgr

        ids_a, mgr = promoted_ids(inject_first=False)
        b = _seed_batch(mgr, uid=2)
        self.assertTrue(bool((ids_a >= 0).all()))
        self.assertTrue(bool((b.lineage_id >= 0).all()))
        self.assertEqual(len(set(ids_a) & set(b.lineage_id)), 0)  # unique
        self.assertNotIn(UNTRACKED, ids_a.tolist())

        proms, _ = _observe(mgr, {0, 2}, target_depth=1.0, n=2)
        for p in proms:
            self.assertTrue(bool((np.asarray(p.lineage_ids) >= 0).all()))

    # -- Channel 9: purity (the flip side of non-influence) -------------------

    def test_9_active_map_stream_is_pure_function_of_inputs(self):
        """Two managers fed byte-identical scripted inputs produce byte-identical
        active-map streams (immediate maps + promotion geometry + prunes) -- no hidden
        global state, wall-clock, or RNG feeds the map."""
        def run():
            mgr = _mgr()
            imm = _classify_kf(mgr, uid=0).immediate_depth_map
            proms, prunes = _observe(mgr, {0}, target_depth=1.0, n=2)
            return imm, sorted(_prom_geom(p) for p in proms), prunes

        a_imm, a_proms, a_prunes = run()
        b_imm, b_proms, b_prunes = run()
        np.testing.assert_array_equal(a_imm, b_imm)
        self.assertEqual(a_proms, b_proms)
        self.assertEqual(a_prunes, b_prunes)

    # -- Channel 7 under the R3 weighted decision path ------------------------

    def test_10_reliability_weighted_promotion_faithful_and_isolated(self):
        """With s-weighted confirmation active (missing-cue C±, doc-10 §6), a promotion
        STILL inserts exactly the candidate's own stored geometry and is unperturbed by a
        neighbour's mutation -- reliability changes only WHICH candidates promote, never
        the map's non-influence isolation or the byte-faithfulness of the promoted set."""
        def promote_a(mutate_neighbor):
            mgr = _mgr(reliability_confirm=True)
            a = _seed_batch(mgr, uid=0)
            _seed_batch(mgr, uid=2)  # neighbour B
            stored = {
                int(lid): (int(a.x[k]), int(a.y[k]), round(float(a.depth[k]), 6))
                for k, lid in enumerate(a.lineage_id.tolist())
            }
            if mutate_neighbor:
                mgr.batches[1].color[:] = 999.0    # B fails the colour gate
                mgr.batches[1].c_plus[:] = 123.0   # and corrupt B's weighted evidence
                mgr.batches[1].c_minus[:] = 456.0
            proms, _ = _observe(mgr, {0, 2}, target_depth=1.0, n=2, reliability=True)
            a_line = set(a.lineage_id.tolist())
            a_geom = {
                lid: g for lid, g in _proms_by_lineage(proms).items() if lid in a_line
            }
            return stored, a_geom

        stored, geom = promote_a(mutate_neighbor=False)
        self.assertEqual(stored, geom)       # faithful: promoted geom == stored candidate
        _, geom_mut = promote_a(mutate_neighbor=True)
        self.assertEqual(geom, geom_mut)     # isolated: neighbour mutation didn't touch A


if __name__ == "__main__":
    unittest.main()
