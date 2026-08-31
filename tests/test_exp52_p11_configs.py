"""E0 contract for EXP52: P11 sparse-KF mask-only revalidation vs MRCS+async50 matched arm.

EXP52 (Phase 1, 2026-08-27) revalidates P11 (sparse-KF + mask-only) at the current HEAD on
the jiangwenheng 3090s and runs the matched balloon comparison against MRCS+async50 (the
EXP51 A2 method chain), to decide whether "dense-KF + ReliabilitySignal" stays in the next
method version or yields to sparse-KF + mask-only.

This contract pins:

  * P11 arms (P11F f3_st_hf / P11B balloon): vanilla KF (DynamicKeyframe off) +
    SemanticMask{mapping ON, insertion OFF} + RobustTracking huber + ReliabilitySignal off.
    Resolved diff vs the exp22 WP-M maskonly chain must be EXACTLY the two P11 spec flips
    ({RobustTracking ON, mask_insertion OFF}).
  * M50B arm: MRCS (mask-free combined) + async_iter_per_kf=50 on balloon; method side
    byte-identical to the already-verified p10_async50_balloon.yaml and to EXP51 A2
    (modulo the sequence), so EXP51 f3_st_hf evidence is reusable for the static side.
  * datasets: P11F -> f3_st_hf; P11B and M50B -> the same balloon path.

Deliberately NOT changed: shared `tum`/`bonn` base configs, vanilla defaults,
`DynamicKeyframe.gap_cap` (stays 5), and the existing p11_maskonly config files.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

P11 = "configs/rgbd/experiments/p11_maskonly"
EXP51 = "configs/rgbd/experiments/exp51_f3_submit"
EXP52 = "configs/rgbd/experiments/exp52_p11"
P10 = "configs/rgbd/experiments/p10_dynamic_verify"

ARMS = {
    "P11F": f"{P11}/p11_maskonly_f3_st_hf.yaml",
    "P11B": f"{P11}/p11_maskonly_balloon.yaml",
    "M50B": f"{EXP52}/exp52_mrcs_async50_balloon.yaml",
}
WPM_MASKONLY_METHOD = "configs/rgbd/experiments/wpm_maskonly/method_maskonly.yaml"
P11_METHOD = f"{P11}/method_p11_maskonly.yaml"
EXP51_A2 = f"{EXP51}/exp51_mrcs_async50_f3_st_hf.yaml"
P10_ASYNC50_BALLOON = f"{P10}/p10_async50_balloon.yaml"

F3_PATH = "datasets/tum/rgbd_dataset_freiburg3_sitting_halfsphere"
BALLOON_PATH = "datasets/bonn/rgbd_bonn_balloon"

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


class TestExp52ConfigContract(unittest.TestCase):
    def test_p11_arms_spec(self):
        for name in ("P11F", "P11B"):
            cfg = load_config(ARMS[name])
            self.assertTrue(cfg["SemanticMask"]["enabled"])
            self.assertTrue(cfg["SemanticMask"]["mask_mapping"])
            self.assertFalse(cfg["SemanticMask"]["mask_insertion"])
            self.assertTrue(cfg["RobustTracking"]["enabled"])
            self.assertEqual(cfg["RobustTracking"]["kernel"], "huber")
            self.assertFalse(cfg["DynamicKeyframe"]["enabled"])
            self.assertFalse(cfg["ReliabilitySignal"]["enabled"])
            self.assertTrue(cfg["DeferredCommit"]["enabled"])
            self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "prune")

    def test_p11_diff_vs_wpm_maskonly_is_exactly_two_flips(self):
        diffs = _diff_keys(load_config(P11_METHOD), load_config(WPM_MASKONLY_METHOD))
        self.assertEqual(
            diffs,
            {
                "RobustTracking.enabled": (True, False),
                "SemanticMask.mask_insertion": (False, True),
            },
        )

    def test_p11_budget_stays_code_default(self):
        # P11 arms must NOT set async_iter_per_kf: the sparse-KF budget question is
        # orthogonal here, and exp28 anchors were produced at the code default (10).
        for name in ("P11F", "P11B"):
            self.assertNotIn("async_iter_per_kf", _flatten(load_config(ARMS[name])))

    def test_m50b_is_mrcs_maskfree_async50(self):
        cfg = load_config(ARMS["M50B"])
        self.assertFalse(cfg["SemanticMask"]["enabled"])
        self.assertTrue(cfg["DynamicKeyframe"]["enabled"])
        self.assertEqual(cfg["DynamicKeyframe"]["gap_cap"], 5)
        self.assertTrue(cfg["ReliabilitySignal"]["enabled"])
        self.assertTrue(cfg["DeferredCommit"]["enabled"])
        self.assertTrue(cfg["RobustTracking"]["enabled"])
        self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "prune")
        self.assertEqual(cfg["Training"]["async_iter_per_kf"], 50)

    def test_m50b_method_side_matches_p10_async50_balloon(self):
        # Byte-identity with the verified P10 balloon async50 config: both inherit the
        # same balloon sequence, so only the ignored method metadata may ever differ.
        diffs = _diff_keys(load_config(ARMS["M50B"]), load_config(P10_ASYNC50_BALLOON))
        self.assertEqual(diffs, {})

    def test_m50b_method_side_matches_exp51_a2(self):
        # Same chain as EXP51 A2 (f3_st_hf); the Dataset block is the only allowed
        # difference, which is what licenses reusing A2 for the f3_st_hf side of G3.
        a2 = load_config(EXP51_A2)
        m50b = load_config(ARMS["M50B"])
        a2.pop("Dataset"), m50b.pop("Dataset")
        self.assertEqual(_diff_keys(m50b, a2), {})

    def test_datasets(self):
        self.assertEqual(load_config(ARMS["P11F"])["Dataset"]["dataset_path"], F3_PATH)
        self.assertEqual(load_config(ARMS["P11B"])["Dataset"]["dataset_path"], BALLOON_PATH)
        self.assertEqual(load_config(ARMS["M50B"])["Dataset"]["dataset_path"], BALLOON_PATH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
