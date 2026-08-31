"""E0 contract for P3-S6X (config resolution + apparatus identity, CPU only).

This campaign moves ONE thing: the ``S6_maxpress`` knob group, from the regime it was measured in
(balloon, injected RGD trajectory, ``ate_rmse_cm`` == 2.0618 on all 46 runs of R2-P03) into the
regime the paper's main table uses (6 sequences, self-tracked, combined backbone). Everything
that could quietly make it a *different* experiment is asserted here, before any GPU time:

  * **the three arms differ by exactly the S6 knob group** — ``s6`` vs the ``prune`` anchor is
    ``{ttl_keyframes, gaussian_th, densify_grad_threshold}`` and nothing else, on all 6
    sequences; the two anchors differ from each other by exactly ``Mapping.lifecycle_mode``;
  * **the knob VALUES are SWEEP's, by identity** (``scripts.r2_p03_sweep.LEVELS``), so this
    campaign cannot migrate a *nearby* baseline and call it S6;
  * **the anchors are P2-T's frozen run configs, by identity** (``scripts.r2_p2_t.ARMS``), and
    this campaign introduces no anchor config of its own;
  * **both anchors are re-run HERE, never borrowed** — the readout's loader is checked to ignore
    a P2-T results file placed in its own out-dir, which is the cross-campaign ban made
    executable rather than promised in prose (same-config ratios have drifted +21% / +29% /
    −23% between campaigns);
  * **the regime really changed** — SWEEP's S6 config resolves with an injected trajectory and
    zeroed camera lrs; every arm here resolves self-tracked. This is the campaign's whole claim,
    so it is a test, not a comment. The runner's inverted pose gate is unit-tested too;
  * **the decision rule is imported, not copied** — the readout's ``DECISION`` is the same object
    that judged SWEEP/DECOMP/S6REPL/MASKRATE, and the ATE band is P2-T's;
  * **no sequence shopping** — the sequence set is the main table's six, by identity;
  * **the eval channel is common to all three arms** (same frozen GTMC support, same dataset),
    so no arm scores itself on a different support set.

NOT asserted here: anything about the outcome. Whether S6's rate advantage survives and whether
its ATE holds is what the 18 runs of batch 1 measure.
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scripts.p3_s6x as runner  # noqa: E402
import scripts.p3_s6x_readout as readout  # noqa: E402
import scripts.r2_p03_sweep_readout as sweep_readout  # noqa: E402
import scripts.r2_p2_t as p2t  # noqa: E402
import scripts.r2_p2_t_readout as p2t_readout  # noqa: E402
from scripts.r2_p03_sweep import LEVELS as SWEEP_LEVELS  # noqa: E402
from utils.config_utils import load_config  # noqa: E402

IGNORED = {"inherit_from", "method_from", "method"}
LIFECYCLE = "Mapping.lifecycle_mode"
TTL = "DeferredCommit.ttl_keyframes"
GTH = "Training.gaussian_th"
DENSIFY = "opt_params.densify_grad_threshold"
KNOB_KEYS = {TTL, GTH, DENSIFY}
EVAL_KEYS = ("Results.save_raw_metrics", "Results.static_bg_mask_subdir",
             "Results.static_bg_band_px")
SWEEP_S6_CFG = SWEEP_LEVELS["S6_maxpress"][0]


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


class P3S6XConfigContract(unittest.TestCase):
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

    def test_s6_minus_prune_anchor_is_exactly_the_s6_knob_group(self):
        """The assertion that licenses reading this campaign as "the same knobs, new regime"."""
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                diff = _diff_keys(self._cfg("s6", seq), self._cfg("prune", seq))
                self.assertEqual(diff, KNOB_KEYS, f"{seq}: s6 differs from its anchor beyond "
                                                  f"the S6 knob group: {diff}")

    def test_the_two_anchors_differ_only_by_lifecycle(self):
        """Re-pinned here because THIS campaign re-runs them; P2-T's pin covers P2-T's runs."""
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                diff = _diff_keys(self._cfg("deferred", seq), self._cfg("prune", seq))
                self.assertEqual(diff, {LIFECYCLE}, f"{seq}: anchors differ beyond lifecycle")

    def test_s6_vs_deferred_is_lifecycle_plus_the_knob_group(self):
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                diff = _diff_keys(self._cfg("s6", seq), self._cfg("deferred", seq))
                self.assertEqual(diff, KNOB_KEYS | {LIFECYCLE}, seq)

    # --- identity: the knobs are SWEEP's, the anchors are P2-T's ------------------------

    def test_knob_group_is_sweeps_s6_by_identity(self):
        """A typo'd or re-typed value here would migrate a different baseline under S6's name."""
        self.assertEqual(runner.S6_KNOBS, SWEEP_LEVELS["S6_maxpress"][1])
        self.assertIs(runner.ARMS["s6"][1], runner.S6_KNOBS)
        self.assertEqual(set(runner.S6_KNOBS), KNOB_KEYS)
        self.assertEqual(float(runner.S6_KNOBS[TTL]), 1.0)
        self.assertEqual(float(runner.S6_KNOBS[GTH]), 0.9)
        self.assertEqual(float(runner.S6_KNOBS[DENSIFY]), 0.0005)

    def test_declared_knobs_resolve_and_actually_move_the_backbone_default(self):
        """A mistyped key passes a diff test (it just adds a key); it must not pass this."""
        for seq in runner.SEQS:
            base = _flatten(self._cfg("prune", seq))
            got = _flatten(self._cfg("s6", seq))
            for key, value in runner.S6_KNOBS.items():
                with self.subTest(seq=seq, key=key):
                    self.assertIn(key, base, f"{key} is not an existing backbone config key")
                    self.assertEqual(float(got[key]), float(value))
                    self.assertNotEqual(float(got[key]), float(base[key]),
                                        f"{seq}/{key}: equals the backbone default")

    def test_anchors_are_the_p2t_run_configs_by_identity(self):
        self.assertEqual(runner.ARMS["prune"][0], p2t.ARMS["prune"])
        self.assertEqual(runner.ARMS["deferred"][0], p2t.ARMS["deferred"])
        for arm in ("prune", "deferred"):
            self.assertEqual(runner.ARMS[arm][1], {}, f"{arm}: an anchor may carry no knobs")
            for seq in runner.SEQS:
                self.assertNotIn("p3_s6x", runner.seq_cfg(arm, seq),
                                 "this campaign introduces no anchor config of its own")

    def test_sequence_set_is_the_main_tables_six_by_identity(self):
        self.assertEqual(runner.SEQS, list(p2t.SEQS))
        self.assertEqual(set(runner.ARMS), {"prune", "deferred", "s6"})
        self.assertEqual(set(runner.ARM_ORDER), set(runner.ARMS))

    # --- the cross-campaign ban, made executable ----------------------------------------

    def test_campaign_has_its_own_results_channel(self):
        self.assertNotEqual(runner.OUT_DIR, p2t.OUT_DIR)
        self.assertNotEqual(runner.RESULTS, p2t.RESULTS)
        self.assertEqual(runner.RESULTS, "p3s6x_results.jsonl")

    def test_readout_ignores_a_p2t_results_file_in_its_own_out_dir(self):
        """Borrowing P2-T's anchor rows is the prohibited move, so it is made impossible.

        Ratios of the SAME config re-run have drifted +21% / +29% / −23% across campaigns on this
        stack, which is why 18 runs exist instead of 6.
        """
        row = {"arm": "prune", "seq": "balloon", "seed": 0, "exit": 0,
               "metrics": {"refined_num_gaussians": 1.0}}
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, p2t.RESULTS), "w", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            from pathlib import Path
            self.assertEqual(readout.load(Path(tmp)), {},
                             "the readout must read only this campaign's results file")

    def test_anchor_coverage_gate_flags_a_cell_whose_anchor_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            complete = [{"seq": "balloon", "arm": a, "seed": 0, "exit": 0}
                        for a in ("prune", "deferred", "s6")]
            self.assertTrue(runner.anchor_coverage(complete, tmp))
            orphan = [{"seq": "balloon", "arm": a, "seed": 0, "exit": 0}
                      for a in ("prune", "s6")]
            self.assertFalse(runner.anchor_coverage(orphan, tmp),
                             "an s6 cell without both in-campaign anchors is not readable")

    # --- the regime change is the treatment, so it is a test ----------------------------

    def test_every_arm_is_self_tracked_here(self):
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

    def test_the_campaign_that_measured_s6_was_a_different_regime(self):
        """Pins the premise: S6's dominance was measured where ATE could not move."""
        flat = _flatten(load_config(SWEEP_S6_CFG))
        self.assertTrue(flat.get("Oracle.pose_file"),
                        "SWEEP's S6 must resolve with an INJECTED trajectory")
        for key in ("Training.lr.cam_rot_delta", "Training.lr.cam_trans_delta"):
            self.assertEqual(float(flat.get(key)), 0.0,
                             f"SWEEP's S6 must resolve with {key} zeroed")

    def test_self_tracked_gate_rejects_a_frozen_run_and_accepts_a_tracked_one(self):
        """Unit-test of the runner's INVERTED pose gate (R2-P03 asserted the opposite)."""
        import yaml
        frozen = {"Oracle": {"pose_file": "/some/trj.json", "gt_pose": False},
                  "Training": {"lr": {"cam_rot_delta": 0.0, "cam_trans_delta": 0.0}}}
        tracked = {"Oracle": {"pose_file": "", "gt_pose": False},
                   "Training": {"lr": {"cam_rot_delta": 0.003, "cam_trans_delta": 0.001}}}
        for cfg, ate, expect in ((frozen, 2.0618, False), (tracked, 3.05, True),
                                 (tracked, 2.0618, False)):
            with tempfile.TemporaryDirectory() as tmp:
                with open(os.path.join(tmp, "config.yml"), "w", encoding="utf-8") as f:
                    yaml.safe_dump(cfg, f)
                ok, detail = runner.check_self_tracked(tmp, ate)
                self.assertEqual(ok, expect, detail)

    # --- common eval channel ------------------------------------------------------------

    def test_all_three_arms_score_on_the_same_frozen_support(self):
        for seq in runner.SEQS:
            flats = {arm: _flatten(self._cfg(arm, seq)) for arm in runner.ARM_ORDER}
            for key in EVAL_KEYS:
                with self.subTest(seq=seq, key=key):
                    values = {arm: flat.get(key) for arm, flat in flats.items()}
                    self.assertEqual(len(set(map(repr, values.values()))), 1,
                                     f"{seq}: {key} differs across arms: {values}")
            self.assertEqual(flats["s6"].get("Results.static_bg_mask_subdir"),
                             "dynamic_mask_gtmc",
                             f"{seq}: must score on the frozen GTMC, not a method mask")

    def test_all_three_arms_run_the_same_dataset(self):
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                paths = {self._cfg(arm, seq)["Dataset"]["dataset_path"]
                         for arm in runner.ARM_ORDER}
                self.assertEqual(len(paths), 1, f"{seq}: arms point at different datasets")

    def test_s6_stays_in_the_prune_family(self):
        """S6 is a TUNED BASELINE — the thing that dominated arm B. It must not be deferred."""
        for seq in runner.SEQS:
            with self.subTest(seq=seq):
                self.assertEqual(self._cfg("s6", seq)["Mapping"]["lifecycle_mode"], "prune")
                self.assertEqual(self._cfg("prune", seq)["Mapping"]["lifecycle_mode"], "prune")
                self.assertEqual(self._cfg("deferred", seq)["Mapping"]["lifecycle_mode"],
                                 "deferred")

    # --- the rule is inherited, not re-typed --------------------------------------------

    def test_decision_rule_and_ate_band_are_imported_objects(self):
        self.assertIs(readout.DECISION, sweep_readout.DECISION)
        self.assertIs(readout.RATE, sweep_readout.RATE)
        self.assertEqual(readout.ATE_NOHARM_PCT, p2t_readout.ATE_NOHARM_PCT)
        self.assertEqual(readout.ATE, "ate_rmse_cm")  # tracking_raw.csv, full trajectory
        self.assertEqual(set(readout.DECISION), {"static_vacated_depth_l1_pen_cm",
                                                 "static_vacated_psnr"})
        self.assertEqual(readout.DECISION["static_vacated_depth_l1_pen_cm"][1], 1.56)
        self.assertEqual(readout.DECISION["static_vacated_psnr"][1], 0.28)


if __name__ == "__main__":
    unittest.main()
