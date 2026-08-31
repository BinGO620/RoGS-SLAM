"""E0 contract for EXP51: f3_st_hf static ATE budget-fairness control.

EXP51 (Phase 1, 2026-08-27) checks that the MRCS static regression on f3_st_hf
(35.6-35.9 cm, 0/5 escape) is a backend-budget artifact, by holding the mapping budget
fair between MRCS and the vanilla backbone at async_iter_per_kf=10 vs 50.

This contract pins that the four arms differ in EXACTLY two dims, nothing else:

  * method arm: MRCS (mask-free, `method_combined_maskoff_prune`) vs vanilla (P9,
    four mechanisms off)
  * budget: `Training.async_iter_per_kf` in {10, 50}

So any ATE difference within a method arm is attributable to the budget alone, and any
within a budget is attributable to the method kernel alone. It also asserts A2 (MRCS+50)
resolves byte-identically (method side) to the already-verified P10 async50 config, so
historical 3090 evidence may be reused under the same-commit rule.

Deliberately NOT changed here: shared `tum/base_config.yaml`, vanilla default budget,
`DynamicKeyframe.gap_cap` (stays 5). All four are experiment-only overlays.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

CAND = "configs/rgbd/experiments/active/candidate"
EXP51 = "configs/rgbd/experiments/exp51_f3_submit"

METHOD_MRCS = f"{CAND}/method_combined_maskoff_prune.yaml"
SEQ = "configs/rgbd/tum/f3_st_hf.yaml"

ARMS = {
    "A1": f"{EXP51}/exp51_mrcs_async10_f3_st_hf.yaml",
    "A2": f"{EXP51}/exp51_mrcs_async50_f3_st_hf.yaml",
    "B1": f"{EXP51}/exp51_vanilla_async10_f3_st_hf.yaml",
    "B2": f"{EXP51}/exp51_vanilla_async50_f3_st_hf.yaml",
}
P10_ASYNC50 = "configs/rgbd/experiments/p10_async_budget/p10_async50_f3_st_hf.yaml"

IGNORED = {"inherit_from", "method_from", "method"}


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
    keys_a, keys_b = set(flat_a), set(flat_b)
    diffs = {}
    for key in sorted(keys_a | keys_b):
        if key in IGNORED:
            continue
        if flat_a.get(key) != flat_b.get(key):
            diffs[key] = (flat_a.get(key), flat_b.get(key))
    return diffs


class TestExp51ConfigContract(unittest.TestCase):
    def test_method_arm_is_mrcs_maskfree(self):
        for name in ("A1", "A2"):
            cfg = load_config(ARMS[name])
            self.assertTrue(cfg["RobustTracking"]["enabled"])
            self.assertFalse(cfg["SemanticMask"]["enabled"])
            self.assertTrue(cfg["DynamicKeyframe"]["enabled"])
            self.assertEqual(cfg["DynamicKeyframe"]["gap_cap"], 5)
            self.assertTrue(cfg["ReliabilitySignal"]["enabled"])
            self.assertTrue(cfg["DeferredCommit"]["enabled"])
            self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "prune")

    def test_vanilla_arm_is_p9_vanilla(self):
        for name in ("B1", "B2"):
            cfg = load_config(ARMS[name])
            for block in ("RobustTracking", "SemanticMask", "DynamicKeyframe",
                          "ReliabilitySignal", "DeferredCommit"):
                self.assertFalse(cfg.get(block, {}).get("enabled", False),
                                 f"{block} should be off for {name}")

    def test_mrcs_arms_differ_only_in_budget(self):
        diffs = _diff_keys(load_config(ARMS["A1"]), load_config(ARMS["A2"]))
        self.assertEqual(diffs, {"Training.async_iter_per_kf": (10, 50)})

    def test_vanilla_arms_differ_only_in_budget(self):
        diffs = _diff_keys(load_config(ARMS["B1"]), load_config(ARMS["B2"]))
        self.assertEqual(diffs, {"Training.async_iter_per_kf": (10, 50)})

    def test_a2_matches_p10_async50_method_side(self):
        # Method-side: async50 must be byte-identical to the already-verified P10 config,
        # so historical 3090 evidence can be reused under the same-commit rule.
        a2 = load_config(ARMS["A2"])
        p10 = load_config(P10_ASYNC50)
        diffs = _diff_keys(a2, p10)
        # only the "method"/comment-ish metadata may differ; method-side must match
        self.assertEqual(diffs, {})

    def test_same_dataset_all_arms(self):
        paths = {load_config(p)["Dataset"]["dataset_path"] for p in ARMS.values()}
        self.assertEqual(paths, {"datasets/tum/rgbd_dataset_freiburg3_sitting_halfsphere"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
