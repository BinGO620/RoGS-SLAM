"""E0 contract for the R2-P03-DECOMP knob decomposition (config resolution only, CPU).

``R2-P03-SWEEP`` ended with one rung (``S6_maxpress``) dominating arm B while moving three
knobs at once — an admission-budget knob that exists only because the deferred mechanism does
(``DeferredCommit.ttl_keyframes``), and two stock MonoGS knobs (``Training.gaussian_th``,
``opt_params.densify_grad_threshold``). "Is the compactness win deferred-specific?" therefore
had no answer. This campaign runs the 2×2 factorial {ttl=1} × {densify 5e-4}, and its decisive
cell ``D1_densifyonly`` is only decisive if it really moved **one generic knob and nothing
else** — so the resolved-config diffs are pinned here, before any GPU time, exactly as
``test_r2_p03_sweep_configs.py`` does for the ladder.

Asserted, per cell:
  * diff vs the arm-A default (``oracle_prune_balloon.yaml``) is EXACTLY
    ``{method} | <the cell's declared knobs>`` over the resolved key set;
  * the declared knob values actually resolve, and differ from the arm-A default (a typo'd key
    would otherwise inherit the default and silently make the cell a replicate of arm A —
    which, for ``D1``, would read as "the generic knob cannot reach B" when nothing was tried);
  * the factorial is closed: ``D2`` carries exactly the union of ``D0``'s and ``D1``'s knobs,
    at the same values, so it is the interaction cell and not a fourth setting;
  * ``D2`` is ``S6_maxpress`` minus ``Training.gaussian_th`` and nothing else, which is what
    licenses reading D2-vs-S6 as the contribution of the native opacity prune;
  * ``D0`` is the SWEEP ``S2_ttl1`` config **verbatim** (identity, not equivalence), so the
    in-campaign ttl cell and SWEEP's are the same file;
  * the pose channel is untouched on every cell: same ``Oracle.pose_file`` as arms A and B,
    ``cam_rot_delta == cam_trans_delta == 0.0``, ``gt_pose`` off;
  * every cell stays in the prune family (``Mapping.lifecycle_mode == "prune"``) with the
    deferred candidate machinery and the evaluation block intact — the decomposition must not
    silently become a lifecycle experiment or rescore itself on different masks;
  * diff vs arm B is EXACTLY ``{method, Mapping.lifecycle_mode} | <knobs>``, so the dominance
    comparison the readout makes is between two arms that differ only where declared.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.r2_p03_decomp import ANCHORS, CELLS  # noqa: E402
from scripts.r2_p03_sweep import LEVELS  # noqa: E402
from utils.config_utils import load_config  # noqa: E402

A0 = ANCHORS["A0_prune"][0]      # arm A default = the factorial's "neither knob" cell
B = ANCHORS["B_deferred"][0]     # arm B -- the operating point under test

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


class R2P03DecompConfigContract(unittest.TestCase):
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

    def test_each_cell_moves_only_its_declared_knobs(self):
        base = self._cfg(A0)
        for cell, (path, knobs) in CELLS.items():
            self.assertEqual(
                _diff_keys(base, self._cfg(path)), {"method"} | set(knobs), cell
            )

    def test_declared_knob_values_actually_resolve(self):
        """A typo'd key passes the diff test (it just adds a key) but must not pass this."""
        base = _flatten(self._cfg(A0))
        for cell, (path, knobs) in CELLS.items():
            flat = _flatten(self._cfg(path))
            for key, value in knobs.items():
                self.assertIn(key, base, f"{cell}: {key} is not an existing config key")
                self.assertEqual(float(flat[key]), float(value), f"{cell}/{key}")
                self.assertNotEqual(
                    float(flat[key]), float(base[key]), f"{cell}/{key} equals the default"
                )

    def test_the_factorial_is_closed(self):
        """D2 must be exactly D0's knobs ∪ D1's knobs, at the same values."""
        d0, d1, d2 = (CELLS[c][1] for c in ("D0_ttl1", "D1_densifyonly", "D2_ttl1_densify"))
        self.assertEqual(set(d0) | set(d1), set(d2))
        for key, value in {**d0, **d1}.items():
            self.assertEqual(float(d2[key]), float(value), key)
        # single-knob cells must be single-knob
        self.assertEqual(set(d0), {TTL})
        self.assertEqual(set(d1), {DENSIFY})
        flat = _flatten(self._cfg(CELLS["D2_ttl1_densify"][0]))
        self.assertEqual(float(flat[TTL]), 1.0)
        self.assertEqual(float(flat[DENSIFY]), 0.0005)

    def test_d2_is_s6_minus_the_native_opacity_prune(self):
        """The one thing that licenses reading D2 vs S6 as gaussian_th's contribution."""
        s6 = _flatten(self._cfg(LEVELS["S6_maxpress"][0]))
        d2 = _flatten(self._cfg(CELLS["D2_ttl1_densify"][0]))
        diff = _diff_keys(self._cfg(LEVELS["S6_maxpress"][0]),
                          self._cfg(CELLS["D2_ttl1_densify"][0]))
        self.assertEqual(diff, {"method", GTH})
        self.assertEqual(float(d2[GTH]), float(_flatten(self._cfg(A0))[GTH]))  # D2 at default
        self.assertEqual(float(s6[GTH]), 0.9)
        self.assertEqual(float(s6[TTL]), float(d2[TTL]))
        self.assertEqual(float(s6[DENSIFY]), float(d2[DENSIFY]))

    def test_d0_reuses_the_frozen_sweep_config_verbatim(self):
        """Not 'equivalent to' S2 -- the same file, so the in-campaign ttl cell is S2."""
        self.assertEqual(CELLS["D0_ttl1"][0], LEVELS["S2_ttl1"][0])
        self.assertEqual(CELLS["D0_ttl1"][1], LEVELS["S2_ttl1"][1])

    def test_pose_channel_is_untouched_on_every_cell(self):
        pose_file = self._cfg(A0)["Oracle"]["pose_file"]
        self.assertTrue(pose_file)
        self.assertEqual(self._cfg(B)["Oracle"]["pose_file"], pose_file)
        for cell, (path, _) in CELLS.items():
            cfg = self._cfg(path)
            self.assertEqual(cfg["Oracle"]["pose_file"], pose_file, cell)
            self.assertFalse(cfg["Oracle"]["gt_pose"], cell)
            self.assertEqual(float(cfg["Training"]["lr"]["cam_rot_delta"]), 0.0, cell)
            self.assertEqual(float(cfg["Training"]["lr"]["cam_trans_delta"]), 0.0, cell)

    def test_every_cell_stays_prune_family_with_evaluation_intact(self):
        for cell, (path, _) in CELLS.items():
            cfg = self._cfg(path)
            self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "prune", cell)
            self.assertTrue(cfg["DeferredCommit"]["enabled"], cell)
            self.assertTrue(cfg["DeferredCommit"]["reliability_confirm"], cell)
            self.assertEqual(
                cfg["Results"]["static_bg_mask_subdir"], "dynamic_mask_gtmc", cell
            )
            self.assertTrue(cfg["Results"]["save_raw_metrics"], cell)
            self.assertEqual(
                cfg["Dataset"]["dataset_path"], "datasets/bonn/rgbd_bonn_balloon", cell
            )

    def test_diff_vs_arm_b_is_lifecycle_plus_declared_knobs(self):
        b_cfg = self._cfg(B)
        self.assertEqual(_diff_keys(self._cfg(A0), b_cfg), PAIR_ALLOWED)
        for cell, (path, knobs) in CELLS.items():
            self.assertEqual(
                _diff_keys(self._cfg(path), b_cfg), PAIR_ALLOWED | set(knobs), cell
            )

    def test_anchors_are_the_campaign_arms_verbatim(self):
        """No knobs on the anchors: they must be arms A and B exactly as R2-P02/SWEEP ran them."""
        for name, (_, knobs) in ANCHORS.items():
            self.assertEqual(knobs, {}, name)


if __name__ == "__main__":
    unittest.main()
