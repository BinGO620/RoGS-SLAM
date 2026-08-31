"""E0 contract for R2-P03-S6REPL (config resolution only, CPU).

This campaign exists to remove the last cross-campaign step from the project's load-bearing
verdict. ``R2-P03-SWEEP``'s ``S6_maxpress`` is the single rung that dominates arm B — the reason
``02-method.md``'s decision tree sits at narrative D — and ``R2-P03-DECOMP`` could only compare
it to its own ``D2`` cell **across campaigns**, on a stack where DECOMP then measured that a
ratio drifts ~21% between campaigns. So S6, D2 and the B anchor are all re-run here in one
launch, and the two questions become within-campaign contrasts.

That only works if the arms are the *same configurations* as the rows they replicate, and if the
S6/D2 pair really differs in one knob. Both are asserted here, before any GPU time:

  * **identity, not equivalence**: ``S6_maxpress`` is ``scripts/r2_p03_sweep.LEVELS``' entry
    (config path *and* declared knobs) and ``D2_ttl1_densify`` is
    ``scripts/r2_p03_decomp.CELLS``' entry, so no new or copied config file can drift away from
    the frozen ones — this campaign introduces no config file at all;
  * **the Q1 contrast is licensed**: the resolved diff between S6 and D2 is EXACTLY
    ``{method, Training.gaussian_th}``, D2 sits at the arm-A default for that key and S6 at 0.9,
    while ``ttl_keyframes`` and ``densify_grad_threshold`` agree — this is what makes S6 ÷ D2
    the multiplicative effect of the native opacity prune and nothing else (the same assertion
    ``test_r2_p03_decomp_configs.py`` made, re-pinned here because this campaign is the one that
    *measures* it);
  * **the declared knob values resolve** and differ from the arm-A default, so a typo'd key
    cannot silently turn an arm into a replicate of arm A;
  * **the anchor is arm B verbatim**, no knobs, the same file R2-P02 / SWEEP / DECOMP used, and
    the diff between each cell and arm B is exactly ``{method, Mapping.lifecycle_mode}`` plus
    the cell's declared knobs;
  * **the pose channel is untouched** on every arm (same ``Oracle.pose_file``,
    ``cam_rot_delta == cam_trans_delta == 0``, ``gt_pose`` off), so ATE stays frozen at 2.0618
    and every rate/fidelity difference is a map-admission difference;
  * **every cell stays in the prune family** with the deferred candidate machinery and the
    evaluation block intact, on the same sequence — a replication must not silently become a
    lifecycle experiment or rescore itself on different masks.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.r2_p03_decomp import ANCHORS as DECOMP_ANCHORS  # noqa: E402
from scripts.r2_p03_decomp import CELLS as DECOMP_CELLS  # noqa: E402
from scripts.r2_p03_s6repl import ANCHORS, CELLS, CORE_ARMS  # noqa: E402
from scripts.r2_p03_sweep import LEVELS as SWEEP_LEVELS  # noqa: E402
from utils.config_utils import load_config  # noqa: E402

A0 = DECOMP_ANCHORS["A0_prune"][0]   # arm A default -- not run here, but the knob reference
B = ANCHORS["B_deferred"][0]         # arm B -- the operating point under test

PAIR_ALLOWED = {"method", "Mapping.lifecycle_mode"}
IGNORED = {"inherit_from", "method_from"}
TTL = "DeferredCommit.ttl_keyframes"
DENSIFY = "opt_params.densify_grad_threshold"
GTH = "Training.gaussian_th"


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


class R2P03S6ReplConfigContract(unittest.TestCase):
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

    def test_arms_are_the_frozen_configs_of_the_campaigns_they_replicate(self):
        """Identity, not equivalence: no new config file, no copy that can drift."""
        self.assertEqual(CELLS["S6_maxpress"], SWEEP_LEVELS["S6_maxpress"])
        self.assertEqual(CELLS["D2_ttl1_densify"], DECOMP_CELLS["D2_ttl1_densify"])
        self.assertEqual(ANCHORS["B_deferred"], DECOMP_ANCHORS["B_deferred"])
        # and the campaign really introduces no config of its own
        for _, (path, _) in {**ANCHORS, **CELLS}.items():
            self.assertNotIn("r2_p03_s6repl", path)

    def test_s6_minus_d2_is_exactly_the_native_opacity_prune(self):
        """The assertion that licenses reading S6 ÷ D2 as gaussian_th's contribution."""
        s6_cfg = self._cfg(CELLS["S6_maxpress"][0])
        d2_cfg = self._cfg(CELLS["D2_ttl1_densify"][0])
        self.assertEqual(_diff_keys(s6_cfg, d2_cfg), {"method", GTH})
        s6, d2, base = _flatten(s6_cfg), _flatten(d2_cfg), _flatten(self._cfg(A0))
        self.assertEqual(float(s6[GTH]), 0.9)
        self.assertEqual(float(d2[GTH]), float(base[GTH]))      # D2 at the arm-A default
        self.assertEqual(float(s6[TTL]), float(d2[TTL]))        # the other two knobs agree
        self.assertEqual(float(s6[DENSIFY]), float(d2[DENSIFY]))
        self.assertEqual(float(s6[TTL]), 1.0)
        self.assertEqual(float(s6[DENSIFY]), 0.0005)

    def test_declared_knob_values_actually_resolve(self):
        """A typo'd key passes a diff test (it just adds a key) but must not pass this."""
        base = _flatten(self._cfg(A0))
        for arm, (path, knobs) in CELLS.items():
            flat = _flatten(self._cfg(path))
            for key, value in knobs.items():
                self.assertIn(key, base, f"{arm}: {key} is not an existing config key")
                self.assertEqual(float(flat[key]), float(value), f"{arm}/{key}")
                self.assertNotEqual(
                    float(flat[key]), float(base[key]), f"{arm}/{key} equals the default"
                )

    def test_declared_knobs_match_each_arms_config_family(self):
        """S6 declares three knobs, D2 the same minus gaussian_th -- no silent fourth knob."""
        self.assertEqual(set(CELLS["S6_maxpress"][1]), {TTL, GTH, DENSIFY})
        self.assertEqual(set(CELLS["D2_ttl1_densify"][1]), {TTL, DENSIFY})
        self.assertEqual(
            set(CELLS["S6_maxpress"][1]) - set(CELLS["D2_ttl1_densify"][1]), {GTH}
        )
        for key, value in CELLS["D2_ttl1_densify"][1].items():
            self.assertEqual(float(CELLS["S6_maxpress"][1][key]), float(value), key)

    def test_anchor_is_arm_b_verbatim(self):
        for name, (_, knobs) in ANCHORS.items():
            self.assertEqual(knobs, {}, name)
        self.assertEqual(_diff_keys(self._cfg(A0), self._cfg(B)), PAIR_ALLOWED)

    def test_diff_vs_arm_b_is_lifecycle_plus_declared_knobs(self):
        b_cfg = self._cfg(B)
        for arm, (path, knobs) in CELLS.items():
            self.assertEqual(
                _diff_keys(self._cfg(path), b_cfg), PAIR_ALLOWED | set(knobs), arm
            )

    def test_pose_channel_is_untouched_on_every_arm(self):
        pose_file = self._cfg(A0)["Oracle"]["pose_file"]
        self.assertTrue(pose_file)
        self.assertEqual(self._cfg(B)["Oracle"]["pose_file"], pose_file)
        for arm, (path, _) in CELLS.items():
            cfg = self._cfg(path)
            self.assertEqual(cfg["Oracle"]["pose_file"], pose_file, arm)
            self.assertFalse(cfg["Oracle"]["gt_pose"], arm)
            self.assertEqual(float(cfg["Training"]["lr"]["cam_rot_delta"]), 0.0, arm)
            self.assertEqual(float(cfg["Training"]["lr"]["cam_trans_delta"]), 0.0, arm)

    def test_every_cell_stays_prune_family_with_evaluation_intact(self):
        for arm, (path, _) in CELLS.items():
            cfg = self._cfg(path)
            self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "prune", arm)
            self.assertTrue(cfg["DeferredCommit"]["enabled"], arm)
            self.assertTrue(cfg["DeferredCommit"]["reliability_confirm"], arm)
            self.assertEqual(
                cfg["Results"]["static_bg_mask_subdir"], "dynamic_mask_gtmc", arm
            )
            self.assertTrue(cfg["Results"]["save_raw_metrics"], arm)
            self.assertEqual(
                cfg["Dataset"]["dataset_path"], "datasets/bonn/rgbd_bonn_balloon", arm
            )

    def test_the_q1_core_is_the_pair_that_differs_by_one_knob(self):
        """--arms CORE_ARMS must still answer Q1 without the anchor."""
        self.assertEqual(set(CORE_ARMS), set(CELLS))


if __name__ == "__main__":
    unittest.main()
