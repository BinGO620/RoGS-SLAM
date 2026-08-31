"""E0 contract for P2-RT: the ReliableTracking-ON twins (config only, CPU).

P2-RT (2026-08-03) tests whether PROBE2-RT's ReliableTracking ATE win (balloon −41%
on the open-set prune base) transfers to the CURRENT combined maskboth backbone.
The spike's validity rests on the RT-on twin isolating exactly ONE knob vs the
paper's prune/deferred control arm — otherwise a spike difference would confound
the RT effect with a tracking/masking/lifecycle difference.

This contract asserts:

  * **the RT-on prune twin differs from the prune twin only in ReliableTracking.enabled**
    -- so any spike ATE delta is attributable to the adaptive-weight tracker, not to
    a mask / robust / keyframe / window / lifecycle difference that traveled with it;
  * **the RT-on deferred twin differs from the deferred twin only in ReliableTracking.enabled**
    -- same guarantee for the deferred arm (cell D of the 2×2);
  * **the two RT-on twins differ only in lifecycle** -- mirroring the P2 twin contract,
    so the RT-on main comparison (if RT is ever admitted) still isolates the lifecycle;
  * **the falsified module stays out** and **both are self-tracked** -- inherited
    guarantees from the P2 twin contract, re-asserted here so an RT-on config cannot
    silently regress them.

NOT asserted: that RT helps. balloon seed0 came back flat (+1.2%, subsumed by
mask-both); see results/evidence/p2_rt_spike_outcome.md. The main-table default
is RT OFF. These configs exist for the sufficiency ablation, not for promotion.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

CAND = "configs/rgbd/experiments/active/candidate"
METHOD_PRUNE = f"{CAND}/method_combined_maskboth_prune.yaml"
METHOD_DEFERRED = f"{CAND}/method_combined_maskboth_deferred.yaml"
METHOD_PRUNE_RTON = f"{CAND}/method_combined_maskboth_prune_rton.yaml"
METHOD_DEFERRED_RTON = f"{CAND}/method_combined_maskboth_deferred_rton.yaml"

IGNORED = {"inherit_from", "method_from", "method"}
RT_KNOB = "ReliableTracking.enabled"
LIFECYCLE = "Mapping.lifecycle_mode"
BACKBONE_BLOCKS = ("SemanticMask", "RobustTracking", "DynamicKeyframe", "Training",
                   "ReliabilitySignal", "TriReliability", "DeferredCommit")


def _flatten(node, prefix=""):
    out = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}{key}." if prefix else f"{key}."))
        return out
    out[prefix[:-1]] = node
    return out


def _diff_keys(cfg_a, cfg_b):
    flat_a, flat_b = _flatten(cfg_a), _flatten(cfg_b)
    return {
        k
        for k in set(flat_a) | set(flat_b)
        if k.split(".")[0] not in IGNORED and flat_a.get(k) != flat_b.get(k)
    }


class P2RTTwinContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(ROOT)
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    @classmethod
    def _cfg(cls, path):
        if path not in cls.cache:
            cls.cache[path] = load_config(path)
        return cls.cache[path]

    def test_rton_prune_differs_from_prune_only_in_rt(self):
        diff = _diff_keys(self._cfg(METHOD_PRUNE), self._cfg(METHOD_PRUNE_RTON))
        self.assertEqual(diff, {RT_KNOB}, f"RT-on prune differs beyond the RT knob: {diff}")

    def test_rton_deferred_differs_from_deferred_only_in_rt(self):
        diff = _diff_keys(self._cfg(METHOD_DEFERRED), self._cfg(METHOD_DEFERRED_RTON))
        self.assertEqual(diff, {RT_KNOB}, f"RT-on deferred differs beyond the RT knob: {diff}")

    def test_the_two_rton_twins_differ_only_in_lifecycle(self):
        diff = _diff_keys(self._cfg(METHOD_PRUNE_RTON), self._cfg(METHOD_DEFERRED_RTON))
        self.assertEqual(diff, {LIFECYCLE}, f"RT-on twins differ beyond the lifecycle: {diff}")

    def test_rt_is_actually_on_in_both_rton_twins(self):
        for path in (METHOD_PRUNE_RTON, METHOD_DEFERRED_RTON):
            self.assertTrue(self._cfg(path).get("ReliableTracking", {}).get("enabled"),
                            f"{path}: ReliableTracking.enabled must be true")

    def test_no_falsified_module_rides_along(self):
        for path in (METHOD_PRUNE_RTON, METHOD_DEFERRED_RTON):
            flat = _flatten(self._cfg(path))
            self.assertFalse(flat.get("CoarsePoseInit.enabled", False),
                             f"{path}: CoarsePoseInit was falsified by probe1 (Do Not Do #1)")

    def test_rton_twins_keep_mask_both_on(self):
        """RT is meant to be redundant after mask-both; the test of that requires mask-both on."""
        for path in (METHOD_PRUNE_RTON, METHOD_DEFERRED_RTON):
            flat = _flatten(self._cfg(path))
            for key in ("SemanticMask.enabled", "SemanticMask.mask_mapping",
                        "SemanticMask.mask_insertion"):
                self.assertTrue(flat.get(key), f"{path}: {key} must be on (RT-sufficiency test needs mask-both)")


if __name__ == "__main__":
    unittest.main()
