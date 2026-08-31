"""E0 contract for EXP53: P11 Phase-2 sequence expansion vs the Combined arm.

EXP53 (2026-08-28) expands the EXP52 BRANCH-1 verdict: P11 (sparse-KF + mask-only)
is revalidated on four more sequences (balloon2 / crowd2 / mv_no_box / f2_xyz) and
compared head-to-head with the Combined main-table arm (mask-ON full kernel) on five
sequences (incl. balloon, where the P11 side reuses EXP52 P11B at the same HEAD).

This contract pins:

  * P11 arms reuse the frozen exp28 config files unchanged: vanilla KF (DynamicKeyframe
    off) + SemanticMask{mapping ON, insertion OFF} + RobustTracking huber +
    ReliabilitySignal off.
  * Combined arms (new exp53 configs): DynamicKeyframe ON gap_cap=5 + ReliabilitySignal
    ON + DeferredCommit ON + RobustTracking huber + prune lifecycle +
    SemanticMask{mapping ON, insertion ON} -- the main-table arm verbatim.
  * Budget matching: NO arm sets Training.async_iter_per_kf (both run the code default
    10, the main-table operating point).
  * Per sequence, P11 and Combined resolve to the SAME dataset_path.
  * Combined method side is identical across all five sequences modulo the Dataset block.

Deliberately NOT changed: shared base configs, vanilla defaults, gap_cap (stays 5),
and the existing p11_maskonly config files.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

P11 = "configs/rgbd/experiments/p11_maskonly"
EXP53 = "configs/rgbd/experiments/exp53_p11phase2"
COMBINED_METHOD = "configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml"

# sequence -> (P11 config, Combined config, dataset_path)
PAIRS = {
    "balloon": (
        f"{P11}/p11_maskonly_balloon.yaml",
        f"{EXP53}/exp53_combined_balloon.yaml",
        "datasets/bonn/rgbd_bonn_balloon",
    ),
    "balloon2": (
        f"{P11}/p11_maskonly_balloon2.yaml",
        f"{EXP53}/exp53_combined_balloon2.yaml",
        "datasets/bonn/rgbd_bonn_balloon2",
    ),
    "crowd2": (
        f"{P11}/p11_maskonly_crowd2.yaml",
        f"{EXP53}/exp53_combined_crowd2.yaml",
        "datasets/bonn/rgbd_bonn_crowd2",
    ),
    "mv_no_box": (
        f"{P11}/p11_maskonly_mv_no_box.yaml",
        f"{EXP53}/exp53_combined_mv_no_box.yaml",
        "datasets/bonn/rgbd_bonn_moving_nonobstructing_box",
    ),
    "f2_xyz": (
        f"{P11}/p11_maskonly_f2_xyz.yaml",
        f"{EXP53}/exp53_combined_f2_xyz.yaml",
        "datasets/tum/rgbd_dataset_freiburg2_xyz",
    ),
}

IGNORED = {"inherit_from", "method_from", "method"}


def _flatten(node, prefix=""):
    out = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}{key}." if prefix else f"{key}."))
        return out
    out[prefix[:-1]] = node
    return out


def _diff_keys(cfg_a, cfg_b, ignored=frozenset(IGNORED)):
    flat_a, flat_b = _flatten(cfg_a), _flatten(cfg_b)
    diffs = {}
    for key in sorted(set(flat_a) | set(flat_b)):
        if key in ignored:
            continue
        if flat_a.get(key) != flat_b.get(key):
            diffs[key] = (flat_a.get(key), flat_b.get(key))
    return diffs


class TestExp53ConfigContract(unittest.TestCase):
    def test_p11_arms_spec_frozen(self):
        for seq, (p11_path, _, _) in PAIRS.items():
            cfg = load_config(p11_path)
            self.assertTrue(cfg["SemanticMask"]["enabled"], seq)
            self.assertTrue(cfg["SemanticMask"]["mask_mapping"], seq)
            self.assertFalse(cfg["SemanticMask"]["mask_insertion"], seq)
            self.assertTrue(cfg["RobustTracking"]["enabled"], seq)
            self.assertEqual(cfg["RobustTracking"]["kernel"], "huber", seq)
            self.assertFalse(cfg["DynamicKeyframe"]["enabled"], seq)
            self.assertFalse(cfg["ReliabilitySignal"]["enabled"], seq)
            self.assertTrue(cfg["DeferredCommit"]["enabled"], seq)
            self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "prune", seq)

    def test_combined_arms_spec(self):
        for seq, (_, c_path, _) in PAIRS.items():
            cfg = load_config(c_path)
            self.assertTrue(cfg["SemanticMask"]["enabled"], seq)
            self.assertTrue(cfg["SemanticMask"]["mask_mapping"], seq)
            self.assertTrue(cfg["SemanticMask"]["mask_insertion"], seq)
            self.assertTrue(cfg["DynamicKeyframe"]["enabled"], seq)
            self.assertEqual(cfg["DynamicKeyframe"]["gap_cap"], 5, seq)
            self.assertTrue(cfg["ReliabilitySignal"]["enabled"], seq)
            self.assertTrue(cfg["DeferredCommit"]["enabled"], seq)
            self.assertTrue(cfg["RobustTracking"]["enabled"], seq)
            self.assertEqual(cfg["RobustTracking"]["kernel"], "huber", seq)
            self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "prune", seq)

    def test_p11_vs_combined_diff_is_kernel_and_insertion(self):
        # The structural diff P11 vs Combined must be exactly the kernel switches
        # (RobustTracking stays huber in both) -- mask_mapping is ON in both.
        for seq, (p11_path, c_path, _) in PAIRS.items():
            diffs = _diff_keys(load_config(p11_path), load_config(c_path))
            self.assertEqual(
                diffs,
                {
                    "DynamicKeyframe.enabled": (False, True),
                    "ReliabilitySignal.enabled": (False, True),
                    "SemanticMask.mask_insertion": (False, True),
                },
                f"unexpected diff for {seq}: {diffs}",
            )

    def test_no_arm_sets_async_budget(self):
        for seq, (p11_path, c_path, _) in PAIRS.items():
            for path in (p11_path, c_path):
                self.assertNotIn(
                    "async_iter_per_kf", _flatten(load_config(path)),
                    f"{seq}: {path} must not set async_iter_per_kf",
                )

    def test_same_dataset_per_sequence(self):
        for seq, (p11_path, c_path, expected) in PAIRS.items():
            p11 = load_config(p11_path)["Dataset"]["dataset_path"]
            comb = load_config(c_path)["Dataset"]["dataset_path"]
            self.assertEqual(p11, comb, seq)
            self.assertEqual(p11, expected, seq)

    def test_combined_method_side_identical_across_sequences(self):
        base_seq = "balloon"
        base = load_config(PAIRS[base_seq][1])
        base.pop("Dataset")
        for seq, (_, c_path, _) in PAIRS.items():
            cfg = load_config(c_path)
            cfg.pop("Dataset")
            self.assertEqual(_diff_keys(cfg, base), {}, f"{seq} method side drift")


if __name__ == "__main__":
    unittest.main(verbosity=2)
