"""E0 contract for R2-P04-MASKRATE (config resolution only, CPU).

This campaign supplies the one comparator the project's compactness claim has never been
measured against. Every arm in the 46 accounted runs of R2-P03 (SWEEP / DECOMP / S6REPL) ran
with ``SemanticMask.enabled == false`` -- asserted below against the frozen anchors themselves,
not asserted in prose -- so ``B vs A`` -55% is a result against insert-then-prune and says
nothing about a hard-mask competitor. External review's structural argument is that a hard mask
is a strict SUBSET of what the deferred arm admits, hence arm B's Gaussian count should be >=
the mask arm's. That is a rate-axis prediction, and this campaign tests it in-campaign.

What this contract has to guarantee, before any GPU time:

  * **the mask arm differs from arm A in the mask and nothing else**: the resolved diff is
    exactly ``{method} | SemanticMask.*``, so a rate difference cannot be a lifecycle,
    tracking, keyframing or window difference wearing the mask's name;
  * **the falsified and the bundled lineages are both kept out**: ``CoarsePoseInit`` stays off
    (probe1 measured its drift; HANDOFF "Do Not Do" #1) and no ``DynamicKeyframe`` /
    ``RobustTracking`` / ``Training.window_size`` change rides along -- the two existing
    mask-both files in the repo carry exactly those, which is why this arm is a fresh minimal
    overlay rather than an inherit from either;
  * **the mask really is ON and really is both-consumer**: ``enabled`` /``mask_mapping`` /
    ``mask_insertion`` all true and the model is the stronger ``maskrcnn`` -- a silently-off
    mask would turn this arm into a duplicate of arm A and the campaign would "measure" a null
    that is pure apparatus;
  * **the two anchors are the frozen files by identity**, the same ones R2-P02 / SWEEP / DECOMP
    / S6REPL ran, so this campaign's B anchor is comparable to the rows it is read against and
    introduces no copy that can drift;
  * **the pose channel is untouched** on all three arms (same ``Oracle.pose_file``, both cam
    lrs 0, ``gt_pose`` off), so ATE stays frozen at 2.0618 and every rate/fidelity difference
    is a map-admission difference;
  * **the evaluation block is identical** on all three arms -- same frozen ``dynamic_mask_gtmc``
    subdir, same bands, ``save_raw_metrics`` on. The frozen masks are loaded at eval time and
    never written to ``frame.dynamic_mask`` (``utils/eval_utils.py:644-648``), so enabling the
    method's own semantic mask cannot let the mask arm rescore itself on an easier support set.

NOT asserted here, because it is not true and the evidence file says so in advance: that this
campaign can measure *recovery*. ``apply_semantic_insertion_gate`` zeroes person depth inside
``add_new_keyframe`` (``utils/slam_frontend.py:299,309``) and that same array is what reaches
``_classify_new_keyframe``, where ``valid = isfinite(observed) & (observed > 0.01)`` drops the
zeroed pixels and ``uncertain`` -- the only set that becomes a candidate batch -- is gated by
``static_valid``. A masked pixel therefore cannot be promoted back by any config. See
``results/evidence/r2_p04_maskrate.md`` §3.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.r2_p03_decomp import ANCHORS as DECOMP_ANCHORS  # noqa: E402
from scripts.r2_p04_maskrate import ANCHORS, CELLS, CORE_ARMS  # noqa: E402
from utils.config_utils import load_config  # noqa: E402

A0 = ANCHORS["A0_prune"][0]      # insert-then-prune control -- the mask arm's base
B = ANCHORS["B_deferred"][0]     # the operating point whose budget is under test
M = CELLS["M_mask"][0]

IGNORED = {"inherit_from", "method_from"}
SEM = "SemanticMask"
MASK_KEYS = ("enabled", "mask_mapping", "mask_insertion")


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


class R2P04MaskRateConfigContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(ROOT)  # inherit_from/method_from are repo-root relative
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    @classmethod
    def _cfg(cls, path):
        if path not in cls.cache:
            cls.cache[path] = load_config(path)
        return cls.cache[path]

    def test_anchors_are_the_frozen_files_of_the_earlier_campaigns(self):
        """Identity, not equivalence: the B anchor is the file SWEEP/DECOMP/S6REPL ran."""
        self.assertEqual(ANCHORS["A0_prune"], DECOMP_ANCHORS["A0_prune"])
        self.assertEqual(ANCHORS["B_deferred"], DECOMP_ANCHORS["B_deferred"])
        for name, (path, knobs) in ANCHORS.items():
            self.assertEqual(knobs, {}, name)
            self.assertNotIn("r2_p04", path, name)

    def test_mask_arm_differs_from_arm_a_in_the_mask_and_nothing_else(self):
        """The assertion that licenses reading M ÷ A as the hard mask's effect."""
        diff = _diff_keys(self._cfg(M), self._cfg(A0))
        self.assertTrue(diff, "M is identical to arm A -- the mask did not resolve")
        self.assertEqual(
            {k for k in diff if not k.startswith(f"{SEM}.")},
            {"method"},
            f"M vs A moved something other than the mask: {sorted(diff)}",
        )

    def test_mask_is_on_and_masks_both_consumers(self):
        """A silently-off mask would make this arm a duplicate of arm A."""
        mask = self._cfg(M)[SEM]
        for key in MASK_KEYS:
            self.assertTrue(mask[key], f"{SEM}.{key} must be true on the mask arm")
        self.assertEqual(mask["model"], "maskrcnn")
        self.assertEqual(list(mask["dynamic_classes"]), [1])  # COCO person
        self.assertFalse(mask["soft"], "hard mask, not soft down-weighting")

    def test_both_anchors_have_the_mask_off(self):
        """Why the -55% result is silent about hard masking: no R2-P03 arm ever enabled it."""
        for name, (path, _) in ANCHORS.items():
            self.assertFalse(self._cfg(path)[SEM]["enabled"], name)
            for key in MASK_KEYS:
                self.assertFalse(self._cfg(path)[SEM][key], f"{name}/{key}")

    def test_no_falsified_or_bundled_module_rides_along(self):
        """probe1 falsified CoarsePoseInit; the repo's two mask-both files bundle four knobs."""
        for arm, (path, _) in {**ANCHORS, **CELLS}.items():
            cfg = self._cfg(path)
            self.assertFalse(cfg["CoarsePoseInit"]["enabled"], arm)
            self.assertFalse(cfg["RobustTracking"]["enabled"], arm)
            self.assertNotIn("DynamicKeyframe", cfg, arm)
            self.assertEqual(int(cfg["Training"]["window_size"]), 8, arm)
            self.assertEqual(int(cfg["Training"]["pose_window"]), 3, arm)

    def test_lifecycle_is_the_only_thing_separating_the_two_anchors(self):
        self.assertEqual(
            _diff_keys(self._cfg(A0), self._cfg(B)), {"method", "Mapping.lifecycle_mode"}
        )
        # and the mask arm sits on arm A's lifecycle, so M vs B is mask + lifecycle
        self.assertEqual(self._cfg(M)["Mapping"]["lifecycle_mode"], "prune")
        self.assertEqual(self._cfg(B)["Mapping"]["lifecycle_mode"], "deferred")

    def test_pose_channel_is_untouched_on_every_arm(self):
        pose_file = self._cfg(A0)["Oracle"]["pose_file"]
        self.assertTrue(pose_file)
        for arm, (path, _) in {**ANCHORS, **CELLS}.items():
            cfg = self._cfg(path)
            self.assertEqual(cfg["Oracle"]["pose_file"], pose_file, arm)
            self.assertFalse(cfg["Oracle"]["gt_pose"], arm)
            self.assertEqual(float(cfg["Training"]["lr"]["cam_rot_delta"]), 0.0, arm)
            self.assertEqual(float(cfg["Training"]["lr"]["cam_trans_delta"]), 0.0, arm)

    def test_evaluation_block_is_identical_on_every_arm(self):
        """The support set must stay method-independent -- no arm rescores itself."""
        for arm, (path, _) in {**ANCHORS, **CELLS}.items():
            cfg = self._cfg(path)
            self.assertEqual(
                cfg["Results"]["static_bg_mask_subdir"], "dynamic_mask_gtmc", arm
            )
            self.assertTrue(cfg["Results"]["save_raw_metrics"], arm)
            self.assertEqual(
                list(cfg["Results"]["static_bg_band_px"]),
                list(self._cfg(A0)["Results"]["static_bg_band_px"]),
                arm,
            )
            self.assertEqual(
                cfg["Dataset"]["dataset_path"], "datasets/bonn/rgbd_bonn_balloon", arm
            )

    def test_the_admission_knobs_are_at_their_defaults_on_every_arm(self):
        """No R2-P03 pressure knob is in this campaign: the mask is the only variable."""
        base = _flatten(self._cfg(A0))
        for arm, (path, _) in {**ANCHORS, **CELLS}.items():
            flat = _flatten(self._cfg(path))
            for key in ("DeferredCommit.ttl_keyframes", "Training.gaussian_th",
                        "opt_params.densify_grad_threshold",
                        "DeferredCommit.max_candidates_per_keyframe"):
                self.assertEqual(flat[key], base[key], f"{arm}/{key}")

    def test_core_arms_are_the_pair_the_prediction_is_about(self):
        """--arms CORE_ARMS must still answer the rate question (M vs the B anchor)."""
        self.assertEqual(CORE_ARMS, ["B_deferred", "M_mask"])
        self.assertEqual(set(CELLS), {"M_mask"})


if __name__ == "__main__":
    unittest.main()
