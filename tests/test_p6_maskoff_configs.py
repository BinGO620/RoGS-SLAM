"""E0 contract for P6 MASK-OFF ablation: the ONLY difference from the combined prune
backbone is SemanticMask.enabled (true -> false).

P6 (p6_maskoff_prereg.md) is the life-or-death verdict for the combined backbone's 4-14x ATE
headline: whether the method kernel lives OUTSIDE the borrowed standard Mask R-CNN semantic
mask. If mask-off still beats vanilla (balloon far below 43 cm), the bundle carries its own
kernel; if it falls back to vanilla level, the bundle is mask + borrowed parts.

This contract exists so that the mask-off arm can only ever isolate the mask. It asserts:

  * the resolved diff between ``method_combined_maskoff_prune`` and ``method_combined_maskboth_prune``
    is EXACTLY ``SemanticMask.enabled`` (false vs true) — nothing else (no re-tune, no dropped
    RobustTracking / DynamicKeyframe / ReliabilitySignal / prune lifecycle);
  * each p6 run config resolves to the same dataset as its p2s combined twin AND differs from
    the twin only in method_from (maskoff vs maskboth) — same support set, same self-tracking;
  * self-tracked (no Oracle.pose_file, non-zero cam lrs) — mask-off still runs its own tracker;
  * the evaluation block is identical to the combined twin (same frozen dynamic_mask_gtmc,
    same bands, save_raw_metrics on) — so mask-off scores on the same support.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

CAND = "configs/rgbd/experiments/active/candidate"
P2 = "configs/rgbd/experiments/p2_render"
P6 = "configs/rgbd/experiments/p6_maskoff"

METHOD_KEEP = f"{CAND}/method_combined_maskboth_prune.yaml"
METHOD_OFF = f"{CAND}/method_combined_maskoff_prune.yaml"

RUNDIFF = {
    "balloon": ("p2s_combined_prune_balloon.yaml", "p6_maskoff_prune_balloon.yaml"),
    "mv_no_box": ("p2s_combined_prune_mv_no_box.yaml", "p6_maskoff_prune_mv_no_box.yaml"),
    "pt2": ("p2s_combined_prune_pt2.yaml", "p6_maskoff_prune_pt2.yaml"),
}

IGNORED = {"inherit_from", "method_from", "method"}
MASKOFF_KEY = "SemanticMask.enabled"
EVAL_KEYS = ("Results.save_raw_metrics", "Results.static_bg_mask_subdir",
             "Results.static_bg_band_px")


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


class P6MaskOffContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(ROOT)  # inherit_from / method_from are repo-root relative
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    @classmethod
    def _cfg(cls, path):
        if path not in cls.cache:
            cls.cache[path] = load_config(path)
        return cls.cache[path]

    def test_the_mask_is_the_only_difference_between_the_method_bases(self):
        diff = _diff_keys(self._cfg(METHOD_KEEP), self._cfg(METHOD_OFF))
        self.assertEqual({MASKOFF_KEY}, diff,
                         f"method bases differ beyond SemanticMask.enabled: {diff}")

    def test_maskoff_has_mask_off_keep_has_mask_on(self):
        self.assertFalse(_flatten(self._cfg(METHOD_OFF)).get(MASKOFF_KEY, False))
        self.assertTrue(_flatten(self._cfg(METHOD_KEEP)).get(MASKOFF_KEY))

    def test_backbone_blocks_present_and_equal_outside_mask(self):
        """mask-off still carries RobustTracking, DynamicKeyframe, Reliability, prune lifecycle."""
        flat_keep = _flatten(self._cfg(METHOD_KEEP))
        flat_off = _flatten(self._cfg(METHOD_OFF))
        self.assertTrue(flat_off.get("RobustTracking.enabled"))
        self.assertTrue(flat_off.get("DynamicKeyframe.enabled"))
        self.assertTrue(flat_off.get("ReliabilitySignal.enabled"))
        self.assertEqual(flat_off.get("Mapping.lifecycle_mode"), "prune")
        # and these agree with the keep-arm
        for key in ("RobustTracking.enabled", "DynamicKeyframe.enabled",
                    "ReliabilitySignal.enabled", "Mapping.lifecycle_mode"):
            self.assertEqual(flat_keep.get(key), flat_off.get(key), key)

    def test_no_falsified_module_rides_along(self):
        for path in (METHOD_KEEP, METHOD_OFF):
            flat = _flatten(self._cfg(path))
            self.assertFalse(flat.get("CoarsePoseInit.enabled", False),
                             f"{path}: CoarsePoseInit was falsified by probe1")

    def test_each_run_config_differs_from_its_twin_only_in_method_from(self):
        """Same dataset, same evaluation; the only spec-level diff is the method base."""
        for seq, (twin_f, off_f) in RUNDIFF.items():
            twin = self._cfg(f"{P2}/{twin_f}")
            off = self._cfg(f"{P6}/{off_f}")
            diff = _diff_keys(twin, off)
            # method_from propagates through SemanticMask.enabled — that IS the ablation;
            # the contract is that nothing else leaks (no re-tune, no dropped module).
            self.assertEqual({MASKOFF_KEY}, diff,
                             f"{seq}: run configs differ beyond the mask: {diff}")
            # dataset resolution equal
            self.assertEqual(_flatten(twin).get("Dataset"),
                             _flatten(off).get("Dataset"), seq)

    def test_both_run_arms_self_tracked(self):
        for _, off_f in RUNDIFF.values():
            flat = _flatten(self._cfg(f"{P6}/{off_f}"))
            self.assertIn(flat.get("Oracle.pose_file", ""), ("", None),
                          f"{off_f}: mask-off must not inject a trajectory")
            for key in ("Training.lr.cam_rot_delta", "Training.lr.cam_trans_delta"):
                lr = flat.get(key)
                if lr is not None:
                    self.assertGreater(lr, 0.0, f"{off_f}: {key} zeroed -> pose frozen")

    def test_evaluation_block_identical_to_combined_twin(self):
        for seq, (twin_f, off_f) in RUNDIFF.items():
            twin = _flatten(self._cfg(f"{P2}/{twin_f}"))
            off = _flatten(self._cfg(f"{P6}/{off_f}"))
            for key in EVAL_KEYS:
                self.assertEqual(twin.get(key), off.get(key),
                                 f"{seq}: eval key {key} differs")
            self.assertEqual(off.get("Results.static_bg_mask_subdir"), "dynamic_mask_gtmc", seq)


if __name__ == "__main__":
    unittest.main()
