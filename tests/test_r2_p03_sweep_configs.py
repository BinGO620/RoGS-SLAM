"""E0 contract for the R2-P03-SWEEP prune-pressure ladder (config resolution only, CPU).

P0 of ``02-method.md`` asks whether arm B's ~11.3k-Gaussian operating point survives a
**matched-budget** comparison: give the insert-then-prune control (arm A) its own prune and
admission knobs, turn them up until the rate brackets B, and check whether any setting reaches
B's rate without paying fidelity. That test is only meaningful if each rung of the ladder
changes *the prune/admission channel and nothing else* -- so this file pins the resolved-config
diffs before any GPU time is spent, exactly as ``test_r2_oracle_configs.py`` and
``test_preflight_pose_configs.py`` do for R2-P01 / R2-P02.

Asserted, per level:
  * diff vs the arm-A default (``oracle_prune_balloon.yaml``) is EXACTLY
    ``{method} | <the level's declared knobs>`` over the resolved key set;  * the declared knob values are the ones actually resolved (a typo'd key would otherwise
    show up as an inherited default and silently make the rung a replicate of arm A);
  * the ladder is monotone in pressure on each single-knob axis (ttl decreasing,
    gaussian_th increasing) -- a mis-ordered rung would turn the Pareto sweep into noise;
  * the pose channel is untouched: same ``Oracle.pose_file`` string as arms A and B,
    ``cam_rot_delta == cam_trans_delta == 0.0``, ``gt_pose`` off;
  * every rung stays in the prune family (``Mapping.lifecycle_mode == "prune"``) with the
    deferred candidate machinery and the evaluation block intact -- the sweep must not
    silently become a lifecycle experiment or rescore itself on different masks;
  * diff vs arm B (``oracle_deferred_balloon.yaml``) is EXACTLY
    ``{method, Mapping.lifecycle_mode} | <knobs>``, so the dominance comparison the readout
    makes is a rate comparison between two arms that differ only where declared.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.r2_p03_sweep import ANCHORS, LEVELS  # noqa: E402
from utils.config_utils import load_config  # noqa: E402

# The ladder itself lives in the runner (scripts/r2_p03_sweep.py: LEVELS), which also
# re-checks these same knob values against the config each run actually dumped to disk.
# Importing it here means the contract test and the campaign can never drift apart.
A0 = ANCHORS["A0_prune"][0]      # arm A default
B = ANCHORS["B_deferred"][0]     # arm B -- the operating point under test

PAIR_ALLOWED = {"method", "Mapping.lifecycle_mode"}
IGNORED = {"inherit_from", "method_from"}


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


class R2P03SweepConfigContract(unittest.TestCase):
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

    def test_each_level_moves_only_its_declared_knobs(self):
        base = self._cfg(A0)
        for level, (path, knobs) in LEVELS.items():
            self.assertEqual(
                _diff_keys(base, self._cfg(path)), {"method"} | set(knobs), level
            )

    def test_declared_knob_values_actually_resolve(self):
        """A typo'd key passes the diff test (it just adds a key) but must not pass this."""
        base = _flatten(self._cfg(A0))
        for level, (path, knobs) in LEVELS.items():
            flat = _flatten(self._cfg(path))
            for key, value in knobs.items():
                self.assertIn(key, base, f"{level}: {key} is not an existing config key")
                self.assertEqual(float(flat[key]), float(value), f"{level}/{key}")
                self.assertNotEqual(
                    float(flat[key]), float(base[key]), f"{level}/{key} equals the default"
                )

    def test_ladder_is_monotone_in_pressure(self):
        ttl = "DeferredCommit.ttl_keyframes"
        gth = "Training.gaussian_th"
        base = _flatten(self._cfg(A0))
        self.assertGreater(float(base[ttl]), float(_flatten(self._cfg(LEVELS["S1_ttl2"][0]))[ttl]))
        self.assertGreater(
            float(_flatten(self._cfg(LEVELS["S1_ttl2"][0]))[ttl]),
            float(_flatten(self._cfg(LEVELS["S2_ttl1"][0]))[ttl]),
        )
        self.assertLess(float(base[gth]), float(_flatten(self._cfg(LEVELS["S4_gth080"][0]))[gth]))
        self.assertLess(
            float(_flatten(self._cfg(LEVELS["S4_gth080"][0]))[gth]),
            float(_flatten(self._cfg(LEVELS["S5_gth090"][0]))[gth]),
        )
        # the floor rung must be at least as aggressive as every single-knob rung it combines
        floor = _flatten(self._cfg(LEVELS["S6_maxpress"][0]))
        self.assertLessEqual(
            float(floor[ttl]), float(_flatten(self._cfg(LEVELS["S2_ttl1"][0]))[ttl])
        )
        self.assertGreaterEqual(
            float(floor[gth]), float(_flatten(self._cfg(LEVELS["S5_gth090"][0]))[gth])
        )

    def test_pose_channel_is_untouched_on_every_rung(self):
        pose_file = self._cfg(A0)["Oracle"]["pose_file"]
        self.assertTrue(pose_file)
        self.assertEqual(self._cfg(B)["Oracle"]["pose_file"], pose_file)
        for level, (path, _) in LEVELS.items():
            cfg = self._cfg(path)
            self.assertEqual(cfg["Oracle"]["pose_file"], pose_file, level)
            self.assertFalse(cfg["Oracle"]["gt_pose"], level)
            self.assertEqual(float(cfg["Training"]["lr"]["cam_rot_delta"]), 0.0, level)
            self.assertEqual(float(cfg["Training"]["lr"]["cam_trans_delta"]), 0.0, level)

    def test_every_rung_stays_prune_family_with_evaluation_intact(self):
        for level, (path, _) in LEVELS.items():
            cfg = self._cfg(path)
            self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "prune", level)
            self.assertTrue(cfg["DeferredCommit"]["enabled"], level)
            self.assertTrue(cfg["DeferredCommit"]["reliability_confirm"], level)
            self.assertEqual(
                cfg["Results"]["static_bg_mask_subdir"], "dynamic_mask_gtmc", level
            )
            self.assertTrue(cfg["Results"]["save_raw_metrics"], level)
            self.assertEqual(
                cfg["Dataset"]["dataset_path"], "datasets/bonn/rgbd_bonn_balloon", level
            )

    def test_diff_vs_arm_b_is_lifecycle_plus_declared_knobs(self):
        b_cfg = self._cfg(B)
        self.assertEqual(_diff_keys(self._cfg(A0), b_cfg), PAIR_ALLOWED)
        for level, (path, knobs) in LEVELS.items():
            self.assertEqual(
                _diff_keys(self._cfg(path), b_cfg), PAIR_ALLOWED | set(knobs), level
            )


if __name__ == "__main__":
    unittest.main()
