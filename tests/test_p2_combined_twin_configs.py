"""E0 contract for P2-0: the COMBINED backbone's prune/deferred twin (config only, CPU).

P2 is the paper's main table, and `02-method.md` Non-negotiables require it to be full-SLAM
self-tracked. Scoping P2 on 2026-07-31 found the table unbuildable: only the deferred half of
the combined backbone existed as a config, so there was no control arm to put beside it. The
obvious substitute -- R2-P01-E2's `*_rtoff` arms -- cannot serve, because those run
`method_openset_prune` with `ReliableTracking` off: no adaptive tracking and no mask at all,
self-tracked ATE 37.72 / 29.03 cm on balloon against RGD-SLAM 2.26 and DG-SLAM 3.65.

`method_combined_maskboth_prune.yaml` is the missing half. This contract exists so that the
pair can only ever isolate ONE mechanism, and asserts:

  * **the lifecycle is the only difference between the two method bases** -- the resolved diff
    is exactly ``Mapping.lifecycle_mode``, so any main-table difference is attributable to the
    lifecycle rather than to a tracking, masking, keyframing or window difference that happened
    to travel with it;
  * **the backbone was copied, not re-tuned** -- the prune twin's mask / RobustTracking /
    DynamicKeyframe / Training blocks equal the deferred twin's field for field, so the control
    is the method's own backbone rather than a weaker one;
  * **the falsified module stays out** -- ``CoarsePoseInit`` is off on both arms. probe1
    measured it as the sole cause of the f2_xyz drift (15.4 cm -> 1.81 cm on removal; HANDOFF
    "Do Not Do" #1), and the v1 lineage this backbone descends from does carry it;
  * **both run configs are genuinely self-tracked** -- no ``Oracle.pose_file`` and non-zero
    camera learning rates on both arms. A frozen-pose main table is forbidden by amendment #01
    §4, and the failure mode is silent: a pose file inherited by accident would pin ATE and
    make the table look clean while measuring nothing about tracking;
  * **the evaluation block is identical** on both arms -- same frozen ``dynamic_mask_gtmc``
    subdir, same bands, ``save_raw_metrics`` on -- so neither arm scores itself on a different
    support set.

NOT asserted here: that the backbone's Bonn ATE is competitive. It has never been measured
(registry has zero combined/maskboth rows; the ~3 cm figure is V1-FIXED5 on TUM f3_wk_xyz,
whose universal-V1 sibling drifted to 55.54 cm on f2_xyz). That is exactly what P2-S's 2 runs
are for, and it is why the ladder buys it with 2 runs instead of assuming it across 36.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

CAND = "configs/rgbd/experiments/active/candidate"
P2 = "configs/rgbd/experiments/p2_render"

METHOD_PRUNE = f"{CAND}/method_combined_maskboth_prune.yaml"
METHOD_DEFERRED = f"{CAND}/method_combined_maskboth_deferred.yaml"
RUN_PRUNE = f"{P2}/p2s_combined_prune_balloon.yaml"
RUN_DEFERRED = f"{P2}/p2s_combined_deferred_balloon.yaml"

IGNORED = {"inherit_from", "method_from", "method"}
LIFECYCLE = "Mapping.lifecycle_mode"
BACKBONE_BLOCKS = ("SemanticMask", "RobustTracking", "DynamicKeyframe", "Training",
                   "ReliabilitySignal", "TriReliability", "DeferredCommit")
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


class P2CombinedTwinContract(unittest.TestCase):
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

    def test_the_lifecycle_is_the_only_difference_between_the_method_bases(self):
        """The assertion that licenses reading the main table as a lifecycle result."""
        diff = _diff_keys(self._cfg(METHOD_PRUNE), self._cfg(METHOD_DEFERRED))
        self.assertEqual(diff, {LIFECYCLE}, f"method bases differ beyond the lifecycle: {diff}")

    def test_the_lifecycle_is_the_only_difference_between_the_run_configs(self):
        """Same guarantee after dataset resolution -- inheritance can reintroduce a field."""
        diff = _diff_keys(self._cfg(RUN_PRUNE), self._cfg(RUN_DEFERRED))
        self.assertEqual(diff, {LIFECYCLE}, f"run configs differ beyond the lifecycle: {diff}")

    def test_the_lifecycle_values_are_the_two_arms(self):
        flat_p = _flatten(self._cfg(RUN_PRUNE))
        flat_d = _flatten(self._cfg(RUN_DEFERRED))
        self.assertEqual(flat_p.get(LIFECYCLE), "prune")
        self.assertEqual(flat_d.get(LIFECYCLE), "deferred")

    def test_the_backbone_was_copied_not_retuned(self):
        """The control must be the method's own backbone, not a weaker one."""
        flat_p = _flatten(self._cfg(RUN_PRUNE))
        flat_d = _flatten(self._cfg(RUN_DEFERRED))
        for block in BACKBONE_BLOCKS:
            keys = {k for k in set(flat_p) | set(flat_d) if k.split(".")[0] == block}
            for key in keys:
                if key == LIFECYCLE:
                    continue
                self.assertEqual(flat_p.get(key), flat_d.get(key),
                                 f"{key} differs across the twin: backbone was re-tuned")

    def test_the_mask_is_on_and_both_consumer_on_both_arms(self):
        """A main table where only one arm masks would confound the lifecycle with the mask."""
        for path in (RUN_PRUNE, RUN_DEFERRED):
            flat = _flatten(self._cfg(path))
            for key in ("SemanticMask.enabled", "SemanticMask.mask_mapping",
                        "SemanticMask.mask_insertion"):
                self.assertTrue(flat.get(key), f"{path}: {key} must be on")
            self.assertEqual(flat.get("SemanticMask.model"), "maskrcnn", path)

    def test_no_falsified_module_rides_along(self):
        """probe1 falsified CoarsePoseInit; the v1 lineage this backbone descends from has it."""
        for path in (METHOD_PRUNE, METHOD_DEFERRED, RUN_PRUNE, RUN_DEFERRED):
            flat = _flatten(self._cfg(path))
            self.assertFalse(flat.get("CoarsePoseInit.enabled", False),
                             f"{path}: CoarsePoseInit was falsified by probe1 (Do Not Do #1)")

    def test_both_run_configs_are_self_tracked(self):
        """The main table must be full-SLAM self-tracked (amendment #01 §4 forbids otherwise).

        A pose file inherited by accident would pin ATE and make the table look clean while
        measuring nothing about tracking -- a silent failure, hence an assertion.
        """
        for path in (RUN_PRUNE, RUN_DEFERRED):
            flat = _flatten(self._cfg(path))
            self.assertIn(flat.get("Oracle.pose_file", ""), ("", None),
                          f"{path}: main-table arms must not inject a trajectory")
            for key in ("Training.lr.cam_rot_delta", "Training.lr.cam_trans_delta"):
                lr = flat.get(key)
                if lr is not None:
                    self.assertGreater(lr, 0.0, f"{path}: {key} zeroed -> pose frozen")

    def test_the_evaluation_block_is_identical_on_both_arms(self):
        flat_p = _flatten(self._cfg(RUN_PRUNE))
        flat_d = _flatten(self._cfg(RUN_DEFERRED))
        for key in EVAL_KEYS:
            self.assertEqual(flat_p.get(key), flat_d.get(key), f"{key} differs across the twin")
        self.assertEqual(flat_p.get("Results.static_bg_mask_subdir"), "dynamic_mask_gtmc")


if __name__ == "__main__":
    unittest.main()
