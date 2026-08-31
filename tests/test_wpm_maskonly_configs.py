"""WP-M MASK-ONLY config contract (2026-08-15, exp22).

The mask-only arm exists to answer ONE question: how much of ``combined``'s absolute
competitiveness is just an off-the-shelf Mask R-CNN bolted onto MonoGS? That question
is only answerable if the arm is a *twin* of the combined main-table arm whose ONLY
difference is the three kernel components. This test pins exactly that, so a silent
config drift cannot turn the comparison into a different experiment (the WP-B lesson:
an unsynced device made a whole campaign measure the wrong thing).

Checked here:
  * every one of the 18 main-table sequences has a run config;
  * each one's EFFECTIVE config (after inherit_from + method_from resolution) differs
    from its combined twin (``<seq>.yaml`` + ``method_combined_maskboth_prune.yaml``,
    i.e. what ``p6_mason_combined_*.yaml`` runs) in EXACTLY the three keys
    RobustTracking.enabled / DynamicKeyframe.enabled / ReliabilitySignal.enabled,
    all flipped True -> False, plus the free-text ``method`` label;
  * the Mask R-CNN block is bit-identical to combined (same detector, class, dilation,
    and both mask_mapping and mask_insertion still on) -- otherwise "mask-only" would
    not be the same mask the combined arm consumes;
  * the lifecycle stays ``prune`` and DeferredCommit stays on, matching both the
    combined twin and the WP-A convention for L=0 cells.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_utils import load_config  # noqa: E402

WPM_DIR = "configs/rgbd/experiments/wpm_maskonly"
COMBINED_METHOD = (
    "configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml"
)
SEQUENCES = {
    "balloon": "configs/rgbd/bonn/balloon.yaml",
    "balloon2": "configs/rgbd/bonn/balloon2.yaml",
    "crowd": "configs/rgbd/bonn/crowd.yaml",
    "crowd2": "configs/rgbd/bonn/crowd2.yaml",
    "mv_no_box": "configs/rgbd/bonn/moving_nonobstructing_box.yaml",
    "mv_no_box2": "configs/rgbd/bonn/moving_nonobstructing_box2.yaml",
    "pt1": "configs/rgbd/bonn/person_tracking.yaml",
    "pt2": "configs/rgbd/bonn/person_tracking2.yaml",
    "f1_desk": "configs/rgbd/tum/f1_desk.yaml",
    "f2_xyz": "configs/rgbd/tum/f2_xyz.yaml",
    "f2_person": "configs/rgbd/tum/f2_person.yaml",
    "f3_office": "configs/rgbd/tum/f3_office.yaml",
    "f3_st_hf": "configs/rgbd/tum/f3_st_hf.yaml",
    "f3_st_rpy": "configs/rgbd/tum/f3_st_rpy.yaml",
    "f3_st_xyz": "configs/rgbd/tum/f3_st_xyz.yaml",
    "f3_wk_hf": "configs/rgbd/tum/f3_wk_hf.yaml",
    "f3_wk_rpy": "configs/rgbd/tum/f3_wk_rpy.yaml",
    "f3_wk_xyz": "configs/rgbd/tum/f3_wk_xyz.yaml",
}
KERNEL_KEYS = {
    "RobustTracking.enabled",
    "DynamicKeyframe.enabled",
    "ReliabilitySignal.enabled",
}


def flatten(cfg, prefix=""):
    flat = {}
    for key, value in cfg.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def combined_twin(seq_config):
    """The effective config the combined main-table arm runs for this sequence."""
    cfg = load_config(seq_config)
    from utils.config_utils import update_recursive

    update_recursive(cfg, load_config(COMBINED_METHOD))
    return cfg


class TestWpmMaskOnlyConfigs(unittest.TestCase):
    def test_all_18_sequences_present(self):
        for name in SEQUENCES:
            self.assertTrue(
                os.path.exists(f"{WPM_DIR}/wpm_{name}_maskonly.yaml"),
                f"missing WP-M run config for {name}",
            )

    def test_diff_vs_combined_is_exactly_the_three_kernel_flags(self):
        for name, seq_config in SEQUENCES.items():
            with self.subTest(sequence=name):
                mask_only = flatten(load_config(f"{WPM_DIR}/wpm_{name}_maskonly.yaml"))
                combined = flatten(combined_twin(seq_config))
                keys = set(mask_only) | set(combined)
                differing = {
                    k
                    for k in keys
                    if mask_only.get(k, "<absent>") != combined.get(k, "<absent>")
                }
                # the free-text label is expected to differ; inherit bookkeeping is ignored
                differing -= {"method", "inherit_from", "method_from"}
                self.assertEqual(
                    differing,
                    KERNEL_KEYS,
                    f"{name}: diff vs combined twin must be exactly the kernel flags, "
                    f"got {sorted(differing)}",
                )
                for key in KERNEL_KEYS:
                    self.assertTrue(combined[key], f"{name}: combined must have {key} on")
                    self.assertFalse(
                        mask_only[key], f"{name}: mask-only must have {key} off"
                    )

    def test_mask_block_and_lifecycle_identical_to_combined(self):
        for name, seq_config in SEQUENCES.items():
            with self.subTest(sequence=name):
                cfg = load_config(f"{WPM_DIR}/wpm_{name}_maskonly.yaml")
                ref = combined_twin(seq_config)
                self.assertEqual(cfg["SemanticMask"], ref["SemanticMask"])
                self.assertTrue(cfg["SemanticMask"]["enabled"])
                self.assertEqual(cfg["SemanticMask"]["model"], "maskrcnn")
                self.assertTrue(cfg["SemanticMask"]["mask_mapping"])
                self.assertTrue(cfg["SemanticMask"]["mask_insertion"])
                self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "prune")
                self.assertTrue(cfg["DeferredCommit"]["enabled"])


if __name__ == "__main__":
    unittest.main()
