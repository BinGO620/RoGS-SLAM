"""Smoke test for PBA BA-coupling config (``configs/rgbd/experiments/pba_ba_coupling/``).

Verifies the minimal intervention: mask_mapping = false, everything else matches eboth.
"""
import importlib.util
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

def _load_utils():
    spec = importlib.util.spec_from_file_location(
        "config_utils", os.path.join(_ROOT, "utils", "config_utils.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

class TestPBAConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cu = _load_utils()
        cls.pba = cu.load_config("configs/rgbd/experiments/pba_ba_coupling/pba_mapping_off_balloon.yaml")
        cls.eboth = cu.load_config("configs/rgbd/experiments/t2_mad_quota/t2_eboth_balloon.yaml")

    def test_mask_mapping_is_off(self):
        self.assertFalse(self.pba["SemanticMask"]["mask_mapping"])

    def test_mask_insertion_is_on(self):
        self.assertTrue(self.pba["SemanticMask"]["mask_insertion"])

    def test_inherits_from_eboth(self):
        """Everything else must match eboth (isolation of single variable)."""
        for key in ("RobustTracking", "DynamicKeyframe", "Dataset"):
            self.assertEqual(self.pba[key], self.eboth[key],
                             f"{key} differs from eboth — violates single-variable constraint")

    def test_dataset_path_is_balloon(self):
        self.assertIn("balloon", self.pba["Dataset"]["dataset_path"])

class TestPBATrackingOnlyConfigs(unittest.TestCase):
    """The 2x2 factorial's fourth cell: mask_mapping ON, mask_insertion OFF.

    Pre-registration: results/evidence/insertion_channel_prereg.md. The single
    variable relative to the eboth control is ``mask_insertion``; anything else
    differing would break the isolation the share_insertion readout assumes.
    """

    SEQS = ("balloon", "f3_wk_xyz", "pt1")

    @classmethod
    def setUpClass(cls):
        cu = _load_utils()
        base = "configs/rgbd/experiments/pba_ba_coupling"
        cls.tracking_only = {
            seq: cu.load_config(f"{base}/pba_tracking_only_{seq}.yaml")
            for seq in cls.SEQS
        }
        # balloon's eboth lives in t2_mad_quota (the PBA campaign inherited it);
        # the other two have a pba_eboth_* wrapper over the same method overlay.
        cls.eboth = {
            "balloon": cu.load_config(
                "configs/rgbd/experiments/t2_mad_quota/t2_eboth_balloon.yaml"),
            "f3_wk_xyz": cu.load_config(f"{base}/pba_eboth_f3_wk_xyz.yaml"),
            "pt1": cu.load_config(f"{base}/pba_eboth_pt1.yaml"),
        }

    def test_mask_insertion_is_off(self):
        for seq, cfg in self.tracking_only.items():
            self.assertFalse(cfg["SemanticMask"]["mask_insertion"],
                             f"{seq}: mask_insertion must be OFF (this is the intervention)")

    def test_mask_mapping_stays_on(self):
        """Opposite of PBA: the BA-side mask must stay ON, or the arm collapses
        onto maskfree and the factorial has three cells, not four."""
        for seq, cfg in self.tracking_only.items():
            self.assertTrue(cfg["SemanticMask"]["mask_mapping"],
                            f"{seq}: mask_mapping must stay ON")

    def test_single_variable_vs_eboth(self):
        """Everything except mask_insertion must match the eboth control."""
        for seq in self.SEQS:
            arm, ctrl = self.tracking_only[seq], self.eboth[seq]
            for key in ("RobustTracking", "DynamicKeyframe", "Dataset",
                        "ReliabilitySignal", "DeferredCommit", "Mapping"):
                self.assertEqual(arm[key], ctrl[key],
                                 f"{seq}/{key} differs from eboth -- breaks single-variable isolation")
            arm_sem = dict(arm["SemanticMask"])
            ctrl_sem = dict(ctrl["SemanticMask"])
            self.assertTrue(ctrl_sem.pop("mask_insertion"))
            self.assertFalse(arm_sem.pop("mask_insertion"))
            self.assertEqual(arm_sem, ctrl_sem,
                             f"{seq}: SemanticMask differs beyond mask_insertion")

    def test_dataset_paths_match_sequence(self):
        expect = {"balloon": "balloon", "f3_wk_xyz": "walking_xyz", "pt1": "person_tracking"}
        for seq, cfg in self.tracking_only.items():
            self.assertIn(expect[seq], cfg["Dataset"]["dataset_path"],
                          f"{seq}: dataset path does not point at the intended sequence")


class TestPBATracksideOnlyConfigs(unittest.TestCase):
    """exp36's cell: BOTH mask consumers off, the mask itself still computed.

    Pre-registration: results/evidence/trackside_channel_prereg.md. This is the arm the
    misnamed ``pba_tracking_only_*`` files claim to be but are not (they keep
    ``mask_mapping: true``). Two flips relative to eboth is intentional here -- the arm's
    purpose is to leave ONLY the tracking-side consumption of the mask alive, and its
    clean single-variable partner is ``pba_mapping_off_*`` (differs by mask_insertion).
    """

    SEQS = ("balloon", "f3_wk_xyz", "pt1")

    @classmethod
    def setUpClass(cls):
        cu = _load_utils()
        base = "configs/rgbd/experiments/pba_ba_coupling"
        cls.trackside = {
            seq: cu.load_config(f"{base}/pba_trackside_only_{seq}.yaml")
            for seq in cls.SEQS
        }
        cls.mapping_off = {
            seq: cu.load_config(f"{base}/pba_mapping_off_{seq}.yaml")
            for seq in cls.SEQS
        }
        cls.eboth = {
            "balloon": cu.load_config(
                "configs/rgbd/experiments/t2_mad_quota/t2_eboth_balloon.yaml"),
            "f3_wk_xyz": cu.load_config(f"{base}/pba_eboth_f3_wk_xyz.yaml"),
            "pt1": cu.load_config(f"{base}/pba_eboth_pt1.yaml"),
        }

    def test_both_consumers_off_but_mask_still_enabled(self):
        """``enabled`` must stay true: with it false the arm collapses onto maskfree and
        measures nothing (that cell already exists)."""
        for seq, cfg in self.trackside.items():
            sem = cfg["SemanticMask"]
            self.assertTrue(sem["enabled"], f"{seq}: SemanticMask.enabled must stay ON")
            self.assertFalse(sem["mask_mapping"], f"{seq}: mask_mapping must be OFF")
            self.assertFalse(sem["mask_insertion"], f"{seq}: mask_insertion must be OFF")

    def test_single_variable_vs_mapping_off(self):
        """The readable contrast: exactly ``mask_insertion`` separates this arm from the
        exp34 PBA arm, so C-vs-E tests insertion in the mapping-OFF regime."""
        for seq in self.SEQS:
            arm, ctrl = self.trackside[seq], self.mapping_off[seq]
            for key in ("RobustTracking", "DynamicKeyframe", "Dataset",
                        "ReliabilitySignal", "DeferredCommit", "Mapping", "Training"):
                self.assertEqual(arm[key], ctrl[key],
                                 f"{seq}/{key} differs from pba_mapping_off -- breaks isolation")
            arm_sem, ctrl_sem = dict(arm["SemanticMask"]), dict(ctrl["SemanticMask"])
            self.assertFalse(arm_sem.pop("mask_insertion"))
            self.assertTrue(ctrl_sem.pop("mask_insertion"))
            self.assertEqual(arm_sem, ctrl_sem,
                             f"{seq}: SemanticMask differs beyond mask_insertion")

    def test_two_variables_vs_eboth(self):
        for seq in self.SEQS:
            arm, ctrl = self.trackside[seq], self.eboth[seq]
            arm_sem, ctrl_sem = dict(arm["SemanticMask"]), dict(ctrl["SemanticMask"])
            for k in ("mask_mapping", "mask_insertion"):
                self.assertFalse(arm_sem.pop(k))
                self.assertTrue(ctrl_sem.pop(k))
            self.assertEqual(arm_sem, ctrl_sem,
                             f"{seq}: SemanticMask differs beyond the two consumer flags")

    def test_mad_exclusion_stays_on_so_the_cue_channel_matches_eboth(self):
        """The MAD-exclusion candidate set (semantic | e_flow) is the second live
        tracking-side channel; it must be configured exactly as in eboth or the arm
        changes two things at once for reasons unrelated to the mask consumers."""
        for seq in self.SEQS:
            self.assertTrue(self.trackside[seq]["ReliabilitySignal"]["mad_exclusion"],
                            f"{seq}: mad_exclusion must match eboth (true)")
            self.assertEqual(self.trackside[seq]["ReliabilitySignal"]["mad_excl_candidates"],
                             self.eboth[seq]["ReliabilitySignal"]["mad_excl_candidates"])


class TestTrackingChannelIsLive(unittest.TestCase):
    """Pins the CODE PATH the trackside arm depends on -- the claim that the hard
    semantic mask reaches the tracking loss at all in this backbone.

    ``utils/slam_utils.py:126-153``: when a soft weight is present (reliability, from
    iteration ``warmup_iters``) the hard mask is BYPASSED unless
    ``SemanticMask.hard_tracking_mask`` is set -- which this arm family does not set. So
    the tracking channel is live only for iterations ``0..warmup_iters-1``. If a future
    refactor routes the hard mask into the soft branch (or drops it), the trackside arm
    would silently measure a different channel; this test is what fails first.
    """

    @staticmethod
    def _routing(soft_present, hard_flag):
        """Mirror of the branch ladder in get_loss_tracking_rgbd (config-level only)."""
        if soft_present:
            return "hardsoft" if hard_flag else "soft_only"
        return "hard_mask"

    def test_hard_mask_bypassed_after_warmup_in_this_backbone(self):
        cu = _load_utils()
        cfg = cu.load_config(
            "configs/rgbd/experiments/pba_ba_coupling/pba_trackside_only_balloon.yaml")
        sem = cfg["SemanticMask"]
        hard_flag = bool(sem.get("hard_tracking_mask",
                                 cfg.get("HardTrackingMask", {}).get("enabled", False)))
        self.assertFalse(hard_flag,
                         "hard_tracking_mask is set: the tracking channel would be live for "
                         "ALL iterations and the prereg's 10/100 arithmetic is wrong")
        self.assertEqual(self._routing(False, hard_flag), "hard_mask")
        self.assertEqual(self._routing(True, hard_flag), "soft_only")

    def test_warmup_iters_and_tracking_itr_num_are_the_prereg_numbers(self):
        cu = _load_utils()
        cfg = cu.load_config(
            "configs/rgbd/experiments/pba_ba_coupling/pba_trackside_only_balloon.yaml")
        self.assertEqual(int(cfg["ReliabilitySignal"]["warmup_iters"]), 10)
        self.assertEqual(int(cfg["Training"]["tracking_itr_num"]), 100)

    def test_branch_ladder_matches_slam_utils_source(self):
        """Guard against the mirror above drifting from the real ladder."""
        src = open(os.path.join(_ROOT, "utils", "slam_utils.py")).read()
        idx_soft = src.index("if tracking_dynamic_soft is not None:")
        idx_hard = src.index("if tracking_dynamic_mask is not None:", idx_soft)
        self.assertLess(idx_soft, idx_hard,
                        "the soft branch must still precede the hard-mask branch")
        self.assertIn("hard_tracking_mask", src[idx_soft:idx_hard],
                      "the hard-mask composition flag disappeared from the soft branch")


class TestPBATracksideHardConfig(unittest.TestCase):
    """Gate H-0/H-1 of ``pose_trackside_prereg_addendum.md``: the exp37 tracking-side
    POSITIVE CONTROL must differ from the trackside arm in exactly one flag, and that flag
    must be the one that stops the hard mask from being bypassed after warm-up.

    Without this arm, exp37's ``TRACKSIDE-INERT`` cannot be told apart from "the estimand is
    blind to the tracking side": its only positive control is a mapping-side channel.
    """

    ARM = "configs/rgbd/experiments/pba_ba_coupling/pba_trackside_hard_balloon.yaml"
    BASE = "configs/rgbd/experiments/pba_ba_coupling/pba_trackside_only_balloon.yaml"

    def setUp(self):
        cu = _load_utils()
        self.hard = cu.load_config(self.ARM)
        self.soft = cu.load_config(self.BASE)

    def test_channel_flags_are_the_trackside_arm_plus_the_hard_flag(self):
        sem = self.hard["SemanticMask"]
        self.assertTrue(sem["enabled"])
        self.assertFalse(sem["mask_mapping"])
        self.assertFalse(sem["mask_insertion"])
        self.assertTrue(sem.get("hard_tracking_mask", False),
                        "the positive control must switch the hard tracking mask ON")

    def test_hard_flag_is_the_only_difference_from_the_trackside_arm(self):
        """A second changed knob would make the gate read a different intervention."""
        diffs = []

        def walk(a, b, path=""):
            keys = set(a) | set(b)
            for k in sorted(keys):
                va, vb = a.get(k), b.get(k)
                if isinstance(va, dict) and isinstance(vb, dict):
                    walk(va, vb, f"{path}{k}.")
                elif va != vb:
                    diffs.append(f"{path}{k}")

        walk(self.hard, self.soft)
        # ``inherit_from``/``method`` are provenance bookkeeping, not channel knobs: this arm
        # inherits FROM the trackside arm, so those two must differ. Anything else would mean
        # the gate is reading more than one intervention.
        self.assertEqual(sorted(diffs),
                         ["SemanticMask.hard_tracking_mask", "inherit_from", "method"],
                         f"unexpected config differences: {diffs}")

    def test_routing_flips_to_hardsoft_for_the_post_warmup_iterations(self):
        """The whole point: after warm-up this arm keeps the hard mask, the base arm drops it."""
        mirror = TestTrackingChannelIsLive._routing
        hard_flag = bool(self.hard["SemanticMask"]["hard_tracking_mask"])
        self.assertEqual(mirror(True, hard_flag), "hardsoft")
        self.assertEqual(mirror(True, False), "soft_only")
        self.assertEqual(mirror(False, hard_flag), "hard_mask")

    def test_reliability_warmup_is_untouched(self):
        """The scope change must come from the routing flag, not from moving warm-up."""
        self.assertEqual(int(self.hard["ReliabilitySignal"]["warmup_iters"]),
                         int(self.soft["ReliabilitySignal"]["warmup_iters"]))


if __name__ == "__main__":
    unittest.main()
