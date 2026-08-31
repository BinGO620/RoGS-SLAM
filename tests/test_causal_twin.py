"""Unit tests for causal-twin infrastructure (utils/causal_twin.py, method #7).

Pure CPU tensor tests. The load-bearing assertions are the twin invariants:
same base_key + same event_key => identical draw (arms are paired), different
seed => divergent draw (real multi-seed variance), and full-lineage prune masks.
"""

import unittest

import torch

from utils.causal_twin import (
    UNTRACKED,
    CounterRNG,
    LineageAllocator,
    base_rng_key,
    key_to_seed,
    lineage_prune_mask,
)


class KeyToSeedTests(unittest.TestCase):
    def test_deterministic_and_in_range(self):
        s1 = key_to_seed("walking_xyz", 0, 5, "split", 2)
        s2 = key_to_seed("walking_xyz", 0, 5, "split", 2)
        self.assertEqual(s1, s2)
        self.assertGreaterEqual(s1, 0)
        self.assertLess(s1, 1 << 63)

    def test_distinct_keys_distinct_seeds(self):
        seeds = {
            key_to_seed("seq", 0),
            key_to_seed("seq", 1),
            key_to_seed("seq", 0, 1),
            key_to_seed("seq2", 0),
        }
        self.assertEqual(len(seeds), 4)  # no collisions on these near-identical keys

    def test_order_matters(self):
        self.assertNotEqual(key_to_seed("a", "b"), key_to_seed("b", "a"))


class CounterRNGPairingTests(unittest.TestCase):
    def test_same_base_and_event_is_identical_across_instances(self):
        # Two arms = two independent CounterRNG with the SAME base_key. At the same
        # logical event they MUST draw identically (the causal-twin invariant).
        arm_a = CounterRNG("walking_xyz", 7)
        arm_b = CounterRNG("walking_xyz", 7)
        xa = arm_a.randn((4, 3), 12, "split", 0)
        xb = arm_b.randn((4, 3), 12, "split", 0)
        self.assertTrue(bool(torch.equal(xa, xb)))

    def test_different_seed_diverges(self):
        a = CounterRNG("walking_xyz", 0)
        b = CounterRNG("walking_xyz", 1)
        xa = a.randn((8,), 3, "jitter", 0)
        xb = b.randn((8,), 3, "jitter", 0)
        self.assertFalse(bool(torch.equal(xa, xb)))

    def test_different_event_diverges(self):
        a = CounterRNG("seq", 0)
        x0 = a.randn((8,), 3, "jitter", 0)
        x1 = a.randn((8,), 3, "jitter", 1)  # call_index differs
        x2 = a.randn((8,), 4, "jitter", 0)  # frame differs
        self.assertFalse(bool(torch.equal(x0, x1)))
        self.assertFalse(bool(torch.equal(x0, x2)))

    def test_repeatable_within_instance(self):
        a = CounterRNG("seq", 0)
        self.assertTrue(bool(torch.equal(a.randn((5,), 1, "e", 0), a.randn((5,), 1, "e", 0))))


class CounterRNGSamplingTests(unittest.TestCase):
    def test_normal_like_matches_split_site(self):
        std = torch.tensor([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        rng = CounterRNG("seq", 0)
        s1 = rng.normal_like(std, 9, "split", 0)
        s2 = rng.normal_like(std, 9, "split", 0)
        self.assertEqual(s1.shape, std.shape)
        self.assertEqual(s1.device, std.device)
        self.assertTrue(bool(torch.equal(s1, s2)))

    def test_normal_like_zero_std_is_zero(self):
        std = torch.zeros(3, 3)
        s = CounterRNG("seq", 0).normal_like(std, 1, "e", 0)
        self.assertLess(float(s.abs().max()), 1e-6)

    def test_subsample_deterministic_sorted_subset(self):
        rng = CounterRNG("seq", 0)
        idx1 = rng.subsample_indices(100, 30, 5, "init", 0)
        idx2 = rng.subsample_indices(100, 30, 5, "init", 0)
        self.assertEqual(idx1.numel(), 30)
        self.assertTrue(bool(torch.equal(idx1, idx2)))
        self.assertTrue(bool((idx1[1:] > idx1[:-1]).all()))  # strictly sorted, unique
        self.assertGreaterEqual(int(idx1.min()), 0)
        self.assertLess(int(idx1.max()), 100)

    def test_subsample_paired_across_arms(self):
        a = CounterRNG("seq", 3)
        b = CounterRNG("seq", 3)
        self.assertTrue(
            bool(torch.equal(a.subsample_indices(50, 20, 2, "init", 0),
                             b.subsample_indices(50, 20, 2, "init", 0)))
        )

    def test_subsample_edge_cases(self):
        rng = CounterRNG("seq", 0)
        self.assertEqual(rng.subsample_indices(10, 0, 1, "e", 0).numel(), 0)
        self.assertEqual(rng.subsample_indices(0, 5, 1, "e", 0).numel(), 0)
        full = rng.subsample_indices(6, 10, 1, "e", 0)  # k > n -> all, in order
        self.assertTrue(bool(torch.equal(full, torch.arange(6))))


class LineageAllocatorTests(unittest.TestCase):
    def test_contiguous_fresh_ids(self):
        alloc = LineageAllocator()
        a = alloc.allocate(3)
        b = alloc.allocate(2)
        self.assertTrue(bool(torch.equal(a, torch.tensor([0, 1, 2], dtype=torch.int32))))
        self.assertTrue(bool(torch.equal(b, torch.tensor([3, 4], dtype=torch.int32))))
        self.assertEqual(alloc.count, 5)
        # no overlap between successive allocations
        self.assertEqual(len(set(a.tolist()) & set(b.tolist())), 0)

    def test_dtype_matches_unique_kfids(self):
        # lineage_id must be int (mirrors GaussianModel.unique_kfIDs = .int())
        self.assertEqual(LineageAllocator().allocate(1).dtype, torch.int32)

    def test_reset_and_start(self):
        alloc = LineageAllocator(start=100)
        self.assertTrue(bool(torch.equal(alloc.allocate(2), torch.tensor([100, 101], dtype=torch.int32))))
        alloc.reset()
        self.assertEqual(alloc.count, 0)

    def test_zero_and_negative(self):
        alloc = LineageAllocator()
        self.assertEqual(alloc.allocate(0).numel(), 0)
        self.assertEqual(alloc.count, 0)
        with self.assertRaises(ValueError):
            alloc.allocate(-1)


class LineagePruneMaskTests(unittest.TestCase):
    def test_selects_targets_including_descendants(self):
        # ids 2 appears 3x (a candidate + its 2 split children) -> all pruned together
        lineage = torch.tensor([UNTRACKED, 2, 5, 2, 2, 5], dtype=torch.int32)
        mask = lineage_prune_mask(lineage, [2])
        self.assertTrue(bool(torch.equal(
            mask, torch.tensor([False, True, False, True, True, False]))))

    def test_multiple_targets(self):
        lineage = torch.tensor([0, 1, 2, 3], dtype=torch.int32)
        mask = lineage_prune_mask(lineage, [1, 3])
        self.assertEqual(mask.sum().item(), 2)
        self.assertTrue(bool(mask[1] and mask[3]))

    def test_empty_targets_prunes_nothing(self):
        lineage = torch.tensor([0, 1, 2], dtype=torch.int32)
        self.assertFalse(bool(lineage_prune_mask(lineage, []).any()))

    def test_untracked_not_matched_unless_requested(self):
        lineage = torch.tensor([UNTRACKED, UNTRACKED, 0], dtype=torch.int32)
        self.assertFalse(bool(lineage_prune_mask(lineage, [0])[:2].any()))
        self.assertTrue(bool(lineage_prune_mask(lineage, [UNTRACKED])[:2].all()))


class BaseRngKeyTests(unittest.TestCase):
    def _cfg(self, seq="walking_xyz", seed=0, mode="deferred"):
        return {
            "Dataset": {"sequence": seq},
            "seed": seed,
            "Mapping": {"lifecycle_mode": mode},
        }

    def test_varies_by_seed(self):
        self.assertNotEqual(
            base_rng_key(self._cfg(seed=0)), base_rng_key(self._cfg(seed=1))
        )

    def test_invariant_to_lifecycle_mode(self):
        # THE load-bearing property: the three arms must share the base key so
        # they draw identical streams at identical events.
        k_imm = base_rng_key(self._cfg(mode="immediate"))
        k_prune = base_rng_key(self._cfg(mode="prune"))
        k_def = base_rng_key(self._cfg(mode="deferred"))
        self.assertEqual(k_imm, k_prune)
        self.assertEqual(k_prune, k_def)

    def test_paired_across_arms_at_same_event(self):
        # Two arms (different lifecycle_mode, same seed) -> a CounterRNG built
        # from each base key draws the SAME sample at the same event key.
        rng_a = CounterRNG(*base_rng_key(self._cfg(mode="prune")))
        rng_b = CounterRNG(*base_rng_key(self._cfg(mode="deferred")))
        std = torch.ones(4, 3)
        self.assertTrue(
            torch.equal(
                rng_a.normal_like(std, "densify_split", 7),
                rng_b.normal_like(std, "densify_split", 7),
            )
        )

    def test_falls_back_without_config(self):
        # Non-SLAM callers (mesh render, unit tests): None / missing keys stay
        # deterministic rather than crashing.
        self.assertEqual(base_rng_key(None), ("", 0))
        self.assertEqual(base_rng_key({}), ("", 0))
        self.assertEqual(base_rng_key(self._cfg()), ("walking_xyz", 0))

    def test_dataset_path_fallback_for_sequence(self):
        cfg = {"Dataset": {"dataset_path": "/data/bonn/balloon"}, "seed": 3}
        self.assertEqual(base_rng_key(cfg), ("/data/bonn/balloon", 3))


if __name__ == "__main__":
    unittest.main()
