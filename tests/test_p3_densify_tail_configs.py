"""E0 contract for P3-DENSIFY-TAIL (config resolution + apparatus identity, CPU only).

This campaign moves ONE knob — ``opt_params.densify_grad_threshold`` — away from the P2-T
prune family, to TEST whether that knob systematically changes the terminal-map op<0.01 tail
width (the predictive consequence of `papers/mmm/mechanism.md` §2). Everything that could
quietly make it a *different* experiment is asserted here, before any GPU time:

  * **the three arms differ by exactly the densify knob** — ``lo``/``hi`` vs the ``base`` anchor
    is ``{opt_params.densify_grad_threshold}`` and nothing else, on all 6 sequences;
  * **the knob values move away from the backbone default in opposite directions** (lo=0.0001,
    base=0.0002, hi=0.0005), so the test is genuinely bidirectional, not just "less densify";
  * **the ``base`` anchor is P2-T's frozen prune run config, by identity**
    (``scripts.r2_p2_t.ARMS``), re-run HERE — this campaign introduces no anchor config;
  * **``lo``/``hi`` derive from the prune anchor by ``inherit_from``** and add exactly the knob,
    so there is no second copy of the backbone that can drift;
  * **every arm is self-tracked** (empty ``Oracle.pose_file``, non-zero camera lrs) — this is a
    self-tracked map study, and a frozen pose would not produce a real final map;
  * **the knob actually moves the backbone default** (a mistyped key would just add a dead key);
  * **the sequence set is the main table's six**, by identity — no seq shopping;
  * **the eval channel is common to all three arms** (same frozen GTMC support, same dataset).

NOT asserted here: anything about the outcome. Whether the tail actually tracks the densify
threshold is what the 18 runs of batch 1 / 54 runs total measure.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scripts.p3_densify_tail as runner  # noqa: E402
import scripts.r2_p2_t as p2t  # noqa: E402
from utils.config_utils import load_config  # noqa: E402

IGNORED = {"inherit_from", "method_from", "method"}
DENSIFY = "opt_params.densify_grad_threshold"
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


class P3DensifyTailConfigContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(ROOT)  # inherit_from / method_from are repo-root relative
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    @classmethod
    def _cfg(cls, arm, seq):
        path = runner.seq_cfg(arm, seq)
        if path not in cls.cache:
            cls.cache[path] = load_config(path)
        return cls.cache[path]

    # --- the one difference the campaign is allowed to have -----------------------------

    def test_lo_minus_base_is_exactly_the_knob(self):
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                diff = _diff_keys(self._cfg("lo", seq), self._cfg("base", seq))
                self.assertEqual(diff, {DENSIFY}, f"{seq}: lo differs from base beyond the "
                                                  f"densify knob: {diff}")

    def test_hi_minus_base_is_exactly_the_knob(self):
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                diff = _diff_keys(self._cfg("hi", seq), self._cfg("base", seq))
                self.assertEqual(diff, {DENSIFY}, f"{seq}: hi differs from base beyond the "
                                                  f"densify knob: {diff}")

    def test_the_two_derived_arms_differ_only_by_the_knob_value(self):
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                diff = _diff_keys(self._cfg("lo", seq), self._cfg("hi", seq))
                self.assertEqual(diff, {DENSIFY}, f"{seq}: lo/hi differ beyond the knob value")

    # --- the knob is a real bidirectional move away from the default --------------------

    def test_knob_values_bracket_the_backbone_default(self):
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                vals = {arm: float(_flatten(self._cfg(arm, seq))[DENSIFY]) for arm in runner.ARM_ORDER}
                self.assertGreater(vals["lo"], 0.0)
                self.assertGreater(vals["hi"], vals["base"])
                self.assertGreater(vals["base"], vals["lo"])  # lo < base < hi: bidirectional
                self.assertEqual(vals["base"], 0.0002)   # the backbone default
                self.assertEqual(vals["lo"], 0.0001)     # half default -> MORE densify
                self.assertEqual(vals["hi"], 0.0005)     # 2.5x default -> LESS densify

    def test_the_knob_is_an_existing_backbone_key_and_moves_it(self):
        for seq in runner.SEQS:
            base = _flatten(self._cfg("base", seq))
            for arm in ("lo", "hi"):
                got = _flatten(self._cfg(arm, seq))
                with self.subTest(seq=seq, arm=arm):
                    self.assertIn(DENSIFY, base, "densify_grad_threshold is not a real key")
                    self.assertNotEqual(float(got[DENSIFY]), float(base[DENSIFY]),
                                        f"{seq}/{arm}: equals the backbone default")

    # --- the anchor is P2-T's prune run config, by identity -----------------------------

    def test_base_anchor_is_the_p2t_prune_config_by_identity(self):
        self.assertEqual(runner.ARMS["base"][0], p2t.ARMS["prune"])
        self.assertEqual(runner.ARMS["base"][1], {}, "base may carry no knob")

    def test_sequence_set_is_the_main_tables_six_by_identity(self):
        self.assertEqual(runner.SEQS, list(p2t.SEQS))
        self.assertEqual(set(runner.ARMS), {"lo", "base", "hi"})
        self.assertEqual(set(runner.ARM_ORDER), set(runner.ARMS))

    # --- self-tracked (this is a self-tracked map study) --------------------------------

    def test_every_arm_is_self_tracked(self):
        for seq in runner.SEQS:
            for arm in runner.ARM_ORDER:
                with self.subTest(seq=seq, arm=arm):
                    flat = _flatten(self._cfg(arm, seq))
                    self.assertIn(flat.get("Oracle.pose_file", ""), ("", None),
                                  "must not inject a trajectory")
                    self.assertFalse(flat.get("Oracle.gt_pose"), "must not inject GT pose")
                    for key in ("Training.lr.cam_rot_delta", "Training.lr.cam_trans_delta"):
                        self.assertGreater(float(flat.get(key, 0.0)), 0.0,
                                           f"{key} zeroed -> pose frozen")

    def test_all_three_arms_score_on_the_same_frozen_support(self):
        for seq in runner.SEQS:
            flats = {arm: _flatten(self._cfg(arm, seq)) for arm in runner.ARM_ORDER}
            for key in EVAL_KEYS:
                with self.subTest(seq=seq, key=key):
                    values = {arm: flat.get(key) for arm, flat in flats.items()}
                    self.assertEqual(len(set(map(repr, values.values()))), 1,
                                     f"{seq}: {key} differs across arms: {values}")
            self.assertEqual(flats["base"].get("Results.static_bg_mask_subdir"),
                             "dynamic_mask_gtmc",
                             f"{seq}: must score on the frozen GTMC, not a method mask")

    def test_all_three_arms_run_the_same_dataset(self):
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                paths = {self._cfg(arm, seq)["Dataset"]["dataset_path"]
                         for arm in runner.ARM_ORDER}
                self.assertEqual(len(paths), 1, f"{seq}: arms point at different datasets")

    def test_all_three_arms_stay_in_the_prune_family(self):
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                for arm in runner.ARM_ORDER:
                    self.assertEqual(self._cfg(arm, seq)["Mapping"]["lifecycle_mode"], "prune",
                                     f"{seq}/{arm}: lifecycle must stay prune (densify is the "
                                     "only knob under test)")


if __name__ == "__main__":
    unittest.main()
