"""E0 contract for P2-T: the run-level config pairs across all 6 dynamic sequences.

``tests/test_p2_combined_twin_configs.py`` covers the BACKBONE contract on balloon (the
method bases differ only in lifecycle). This file covers the RUN-LEVEL pairs for every
sequence in the P2-T matrix, so the main table's per-sequence comparisons are each licensed
by the same "only the lifecycle differs" guarantee.

It asserts, for each of the 6 dynamic sequences (balloon / balloon2 / mv_no_box /
mv_no_box2 / pt1 / pt2):

  * the resolved twin pair differs ONLY in ``Mapping.lifecycle_mode`` (+ the cosmetic
    ``method`` / ``method_from`` which point to the right base, excluded as non-functional);
  * both arms are genuinely self-tracked (no ``Oracle.pose_file``, non-zero camera lrs);
  * both arms carry the frozen ``dynamic_mask_gtmc`` eval mask (so neither scores itself on
    a different support set);
  * pt1 specifically: its GTMC mask was frozen (sha 06f9c475) BEFORE this config was
    written, so pt1 is not a sequence whose eval oracle was tuned to look good.

NOT asserted here: that the combined backbone's Bonn ATE is competitive (P2-S measured it
on balloon/pt2; the other seqs are measured by the campaign itself).
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

P2 = "configs/rgbd/experiments/p2_render"

# (short, seq-config-basename) — the run configs are p2s_combined_{prune,deferred}_{short}.yaml
SEQS = ["balloon", "balloon2", "mv_no_box", "mv_no_box2", "pt1", "pt2"]

IGNORED = {"inherit_from", "method_from", "method"}
LIFECYCLE = "Mapping.lifecycle_mode"
SELF_TRACK_KEYS = ("Oracle.pose_file", "Training.lr.cam_rot_delta", "Training.lr.cam_trans_delta")
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
    return {k for k in set(flat_a) | set(flat_b)
            if k.split(".")[0] not in IGNORED and flat_a.get(k) != flat_b.get(k)}


def _pair(seq):
    return (f"{P2}/p2s_combined_prune_{seq}.yaml",
            f"{P2}/p2s_combined_deferred_{seq}.yaml")


class P2TRunContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(ROOT)
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    @classmethod
    def _cfg(cls, path):
        if path not in cls.cache:
            cls.cache[path] = load_config(path)
        return cls.cache[path]

    def _test_pair_only_lifecycle_differs(self, seq):
        prune, deferred = _pair(seq)
        diff = _diff_keys(self._cfg(prune), self._cfg(deferred))
        self.assertEqual(diff, {LIFECYCLE}, f"{seq}: twin differs beyond lifecycle: {diff}")

    def _test_pair_self_tracked(self, seq):
        for path in _pair(seq):
            flat = _flatten(self._cfg(path))
            self.assertIn(flat.get("Oracle.pose_file", ""), ("", None),
                          f"{seq}/{path}: must not inject a trajectory")
            for key in SELF_TRACK_KEYS[1:]:
                lr = flat.get(key)
                if lr is not None:
                    self.assertGreater(lr, 0.0, f"{seq}/{path}: {key} zeroed -> pose frozen")

    def _test_pair_eval_identical(self, seq):
        prune, deferred = _pair(seq)
        fp, fd = _flatten(self._cfg(prune)), _flatten(self._cfg(deferred))
        for key in EVAL_KEYS:
            self.assertEqual(fp.get(key), fd.get(key), f"{seq}: {key} differs across twin")
        self.assertEqual(fp.get("Results.static_bg_mask_subdir"), "dynamic_mask_gtmc",
                         f"{seq}: must score on frozen GTMC, not a method mask")

    def test_all_six_pairs_only_lifecycle_differs(self):
        for seq in SEQS:
            with self.subTest(seq=seq):
                self._test_pair_only_lifecycle_differs(seq)

    def test_all_six_pairs_self_tracked(self):
        for seq in SEQS:
            with self.subTest(seq=seq):
                self._test_pair_self_tracked(seq)

    def test_all_six_pairs_eval_identical(self):
        for seq in SEQS:
            with self.subTest(seq=seq):
                self._test_pair_eval_identical(seq)

    def test_pt1_gtmc_mask_frozen_before_config(self):
        """pt1 is the H-D high-coverage independent sample; its oracle must predate the run
        config so the eval was not tuned to the result. The mask was built 2026-07-31."""
        prune = self._cfg(_pair("pt1")[0])
        # dataset_path resolves to the bonn person_tracking dir whose GTMC was just frozen
        ds = prune.get("Dataset", {}).get("dataset_path", "")
        self.assertIn("person_tracking", ds.replace("person_tracking2", "X"),
                      "pt1 must point at person_tracking (not pt2)")

    def test_mv_no_box_pairs_resolve_to_the_box_family(self):
        for short, want in (("mv_no_box", "moving_nonobstructing_box"),
                            ("mv_no_box2", "moving_nonobstructing_box2")):
            with self.subTest(seq=short):
                flat = _flatten(self._cfg(_pair(short)[0]))
                self.assertIn(want, flat.get("Dataset.dataset_path", ""),
                              f"{short}: dataset path must point at {want}")


if __name__ == "__main__":
    unittest.main()
