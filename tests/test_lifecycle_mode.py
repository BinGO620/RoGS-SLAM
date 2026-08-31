"""Unit tests for the lifecycle_mode selector (utils/deferred_commit.py, method #9).

Pure config-dict tests: the 3-arm ablation selector + its back-compat with the
legacy DeferredCommit.enabled toggle.
"""

import unittest

from utils.deferred_commit import LIFECYCLE_MODES, lifecycle_mode


class LifecycleModeTests(unittest.TestCase):
    def test_default_is_immediate(self):
        self.assertEqual(lifecycle_mode({}), "immediate")
        self.assertEqual(lifecycle_mode({"DeferredCommit": {"enabled": False}}), "immediate")

    def test_legacy_enabled_maps_to_deferred(self):
        self.assertEqual(lifecycle_mode({"DeferredCommit": {"enabled": True}}), "deferred")

    def test_explicit_modes(self):
        for mode in LIFECYCLE_MODES:
            self.assertEqual(lifecycle_mode({"Mapping": {"lifecycle_mode": mode}}), mode)

    def test_case_insensitive(self):
        self.assertEqual(lifecycle_mode({"Mapping": {"lifecycle_mode": "PRUNE"}}), "prune")

    def test_canonical_overrides_legacy(self):
        cfg = {"Mapping": {"lifecycle_mode": "immediate"}, "DeferredCommit": {"enabled": True}}
        self.assertEqual(lifecycle_mode(cfg), "immediate")

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            lifecycle_mode({"Mapping": {"lifecycle_mode": "purne"}})


if __name__ == "__main__":
    unittest.main()
