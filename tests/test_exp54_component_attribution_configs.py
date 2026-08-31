"""CPU contract for EXP54 single-variable component attribution."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

P11 = "configs/rgbd/experiments/p11_maskonly"
EXP54 = "configs/rgbd/experiments/exp54_component_attribution"
P11_METHOD = f"{P11}/method_p11_maskonly.yaml"
METHODS = {
    "dynkf": f"{EXP54}/method_p11_dynkf_diag.yaml",
    "reliability": f"{EXP54}/method_p11_reliability_diag.yaml",
}
CONFIGS = {
    "dynkf_crowd2": f"{EXP54}/exp54_p11_dynkf_crowd2.yaml",
    "dynkf_mv_no_box": f"{EXP54}/exp54_p11_dynkf_mv_no_box.yaml",
    "reliability_crowd2": f"{EXP54}/exp54_p11_reliability_crowd2.yaml",
    "reliability_mv_no_box": f"{EXP54}/exp54_p11_reliability_mv_no_box.yaml",
}
P11_CONFIGS = {
    "crowd2": f"{P11}/p11_maskonly_crowd2.yaml",
    "mv_no_box": f"{P11}/p11_maskonly_mv_no_box.yaml",
}
IGNORED = {"inherit_from", "method_from", "method"}


def flatten(node, prefix=""):
    if not isinstance(node, dict):
        return {prefix[:-1]: node}
    out = {}
    for key, value in node.items():
        out.update(flatten(value, f"{prefix}{key}."))
    return out


def diff(a, b):
    fa, fb = flatten(a), flatten(b)
    return {
        key: (fa.get(key), fb.get(key))
        for key in sorted(set(fa) | set(fb))
        if key.split(".")[0] not in IGNORED and fa.get(key) != fb.get(key)
    }


class TestExp54ConfigContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_cwd = os.getcwd()
        os.chdir(ROOT)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.old_cwd)

    def test_methods_differ_from_p11_only_by_declared_switch_and_diag(self):
        p11 = load_config(P11_METHOD)
        for arm, path in METHODS.items():
            with self.subTest(arm=arm):
                changes = diff(load_config(path), p11)
                self.assertEqual(
                    set(changes),
                    {
                        "ReliabilitySignal.enabled",
                        "KeyframeDiag.enabled",
                    } if arm == "reliability" else {
                        "DynamicKeyframe.enabled",
                        "KeyframeDiag.enabled",
                    },
                    changes,
                )

    def test_dynkf_arm_is_single_intervention(self):
        for path in CONFIGS.values():
            cfg = load_config(path)
            self.assertTrue(cfg["SemanticMask"]["enabled"])
            self.assertTrue(cfg["SemanticMask"]["mask_mapping"])
            self.assertFalse(cfg["SemanticMask"]["mask_insertion"])
            self.assertTrue(cfg["RobustTracking"]["enabled"])
            self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "prune")
            self.assertTrue(cfg["KeyframeDiag"]["enabled"])

    def test_arm_switches_and_common_budget(self):
        for name, path in CONFIGS.items():
            cfg = load_config(path)
            if name.startswith("dynkf"):
                self.assertTrue(cfg["DynamicKeyframe"]["enabled"])
                self.assertFalse(cfg["ReliabilitySignal"]["enabled"])
            else:
                self.assertFalse(cfg["DynamicKeyframe"]["enabled"])
                self.assertTrue(cfg["ReliabilitySignal"]["enabled"])
            self.assertEqual(cfg["DynamicKeyframe"]["gap_cap"], 5)
            self.assertTrue(cfg["DeferredCommit"]["enabled"])
            self.assertTrue(cfg["DeferredCommit"]["reliability_confirm"])
            self.assertNotIn("async_iter_per_kf", flatten(cfg))

    def test_same_dataset_as_exp53_p11(self):
        for seq in ("crowd2", "mv_no_box"):
            expected = load_config(P11_CONFIGS[seq])["Dataset"]["dataset_path"]
            for name, path in CONFIGS.items():
                if name.endswith(seq):
                    self.assertEqual(load_config(path)["Dataset"]["dataset_path"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
