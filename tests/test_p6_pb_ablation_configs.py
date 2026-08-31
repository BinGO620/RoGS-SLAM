"""E0 contract for P-B (mask x dynKF) 2x2 ablation configs.

P6 mask-off (p6_maskoff_3seed) showed mask-free still holds ~3cm on mv_no_box (kernel
NOT in the borrowed mask). P-B asks: which component (dense-keyframing vs the mask)
is the actual driver? Builds a clean 2x2 on top of the existing two cells:

    ({mask on, mask off} x {dynKF on, dynKF off})

Existing measured cells:
  mask + dynKF  = method_combined_maskboth_prune (P2-T ~3.06cm balloon / 2.66 mv)
  maskoff+dynKF = method_combined_maskoff_prune  (P6  ~12.11cm balloon / 3.09 mv)
New cells (this contract):
  mask + dynKF-off
  maskoff+dynKF-off

Each new arm resolves to EXACTLY one toggled field from the combined prune base, and
inherits the same self-tracking / evaluation / no-falsified-module guarantees.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from utils.config_utils import load_config

CAND = "configs/rgbd/experiments/active/candidate"
BASE = f"{CAND}/method_combined_maskboth_prune.yaml"
ARM_MASK_DKFOFF = f"{CAND}/method_combined_mask_dynkfoff_prune.yaml"
ARM_MASKOFF_DKFOFF = f"{CAND}/method_combined_maskoff_dynkf_prune.yaml"
RUNS = "configs/rgbd/experiments/p6_pb_ablation"
ALL_METHOD = [BASE, ARM_MASK_DKFOFF, ARM_MASKOFF_DKFOFF]
ALL_RUNS = [
    f"{RUNS}/p6_pb_mask_dynkfoff_balloon.yaml",
    f"{RUNS}/p6_pb_mask_dynkfoff_mv_no_box.yaml",
    f"{RUNS}/p6_pb_maskoff_dynkfoff_balloon.yaml",
    f"{RUNS}/p6_pb_maskoff_dynkfoff_mv_no_box.yaml",
]
IGNORED = {"inherit_from", "method_from", "method"}
MASKOFF = "SemanticMask.enabled"
DKFOFF = "DynamicKeyframe.enabled"


def _flatten(node, prefix=""):
    out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(_flatten(v, f"{prefix}{k}." if prefix else f"{k}."))
        return out
    out[prefix[:-1]] = node
    return out


def _diff(a, b):
    fa, fb = _flatten(a), _flatten(b)
    return {k for k in set(fa) | set(fb)
            if k.split(".")[0] not in IGNORED and fa.get(k) != fb.get(k)}


class PB2x2Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(ROOT)
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    @classmethod
    def cfg(cls, p):
        if p not in cls.cache:
            cls.cache[p] = load_config(p)
        return cls.cache[p]

    def test_mask_dynkfoff_differs_only_by_dynkf(self):
        self.assertEqual({DKFOFF}, _diff(self.cfg(BASE), self.cfg(ARM_MASK_DKFOFF)))

    def test_maskoff_dynkfoff_differs_only_by_mask_and_dynkf(self):
        self.assertEqual({MASKOFF, DKFOFF}, _diff(self.cfg(BASE), self.cfg(ARM_MASKOFF_DKFOFF)))

    def test_mask_dynkfoff_mask_on_dynkf_off(self):
        f = _flatten(self.cfg(ARM_MASK_DKFOFF))
        self.assertTrue(f[MASKOFF])
        self.assertFalse(f[DKFOFF])

    def test_maskoff_dynkfoff_both_off(self):
        f = _flatten(self.cfg(ARM_MASKOFF_DKFOFF))
        self.assertFalse(f[MASKOFF])
        self.assertFalse(f[DKFOFF])

    def test_runs_share_base_toggle(self):
        for run in ALL_RUNS:
            base = self.cfg(run)
            f = _flatten(base)
            # self-tracked
            self.assertIn(f.get("Oracle.pose_file", ""), ("", None), run)
            for k in ("Training.lr.cam_rot_delta", "Training.lr.cam_trans_delta"):
                lr = f.get(k)
                if lr is not None:
                    self.assertGreater(lr, 0.0, f"{run} {k}")
            # prune lifecycle preserved
            self.assertEqual(f.get("Mapping.lifecycle_mode"), "prune", run)
            # no falsified module
            self.assertFalse(f.get("CoarsePoseInit.enabled", False), run)


if __name__ == "__main__":
    unittest.main()
