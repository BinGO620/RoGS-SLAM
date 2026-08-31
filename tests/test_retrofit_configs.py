"""Config contracts for the three retrofit campaigns (M2 anchor probe, T2 adaptive-quota
MAD isolation, T3 semantic alpha override).

Every one of them is a DEFAULT-OFF retrofit whose whole claim rests on "the control arm
is the current trunk, unchanged". That claim is a config property, and this project has
already paid for leaving such a property untested twice: a hard-coded column whitelist
silently deleted the entire P8 ego_* provenance block, and the P7 default-arm assertion
sat green for a whole campaign while asserting nothing (a bare leaf name against a set of
dotted paths). So each arm here is pinned to differ from its control in EXACTLY the keys
that name its mechanism -- no re-tune, no dropped component, no drifted dataset.

Run:
    /data/conda_envs/monogs-ours/bin/python -m unittest tests.test_retrofit_configs
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

CAND = "configs/rgbd/experiments/active/candidate"
M2 = "configs/rgbd/experiments/m2_anchor_probe"
T2 = "configs/rgbd/experiments/t2_mad_quota"
T3 = "configs/rgbd/experiments/t3_semantic_alpha"

TRUNK_MASKFREE = f"{CAND}/method_combined_maskoff_prune.yaml"
TRUNK_MASKON = f"{CAND}/method_combined_maskboth_prune.yaml"

IGNORED = {"inherit_from", "method_from", "method"}

T2_SEQS = ("balloon", "mv_no_box", "crowd2", "f3_st_hf", "f2_xyz")
T3_SEQS = ("balloon", "mv_no_box", "pt2")

# resolved dataset_path tails -- the short campaign alias is NOT what lands in the
# config, so matching on it would pass vacuously the way the P7 assertion did
DATASET_TAIL = {
    "balloon": "rgbd_bonn_balloon",
    "mv_no_box": "rgbd_bonn_moving_nonobstructing_box",
    "crowd2": "rgbd_bonn_crowd2",
    "pt2": "rgbd_bonn_person_tracking2",
    "f3_st_hf": "rgbd_dataset_freiburg3_sitting_halfsphere",
    "f2_xyz": "rgbd_dataset_freiburg2_xyz",
}


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
        k: (flat_a.get(k), flat_b.get(k))
        for k in sorted(set(flat_a) | set(flat_b))
        if k not in IGNORED and flat_a.get(k) != flat_b.get(k)
    }


class M2AnchorProbeContract(unittest.TestCase):
    """M2 is a READ-ONLY probe: its only licence to exist is that it cannot change the
    run it is measuring. If the overlay ever touches a second key, an anchor 'inflection'
    could be an artefact of that key instead of evidence for Design B."""

    def test_overlay_differs_from_trunk_only_in_the_probe_block(self):
        diff = _diff_keys(load_config(f"{M2}/method_anchor_probe.yaml"),
                          load_config(TRUNK_MASKFREE))
        self.assertEqual(
            set(diff),
            {"DynamicKeyframe.anchor_probe", "DynamicKeyframe.anchor_thresholds",
             "DynamicKeyframe.anchor_require_grad_mask"},
            f"M2 overlay must only add the probe block: {diff}",
        )

    def test_probe_is_on_and_the_trunk_default_is_off(self):
        cfg = load_config(f"{M2}/method_anchor_probe.yaml")
        self.assertTrue(cfg["DynamicKeyframe"]["anchor_probe"])
        trunk = load_config(TRUNK_MASKFREE)
        self.assertFalse(trunk.get("DynamicKeyframe", {}).get("anchor_probe", False))

    def test_run_configs_resolve_their_own_sequence_and_stay_self_tracked(self):
        for seq in ("f3_st_hf", "f2_xyz", "balloon"):
            cfg = load_config(f"{M2}/anchor_{seq}.yaml")
            self.assertIn(DATASET_TAIL[seq], cfg["Dataset"]["dataset_path"], seq)
            self.assertTrue(cfg["DynamicKeyframe"]["anchor_probe"], seq)
            # a probe run that borrowed a trajectory would measure someone else's
            # anchors, not the collapse we are trying to catch
            self.assertFalse(cfg.get("Oracle", {}).get("pose_file") or False, seq)
            self.assertFalse(cfg.get("Oracle", {}).get("gt_pose", False), seq)


class T2QuotaContract(unittest.TestCase):
    MECH = {
        "ReliabilitySignal.mad_exclusion",
        "ReliabilitySignal.mad_excl_candidates",
        "ReliabilitySignal.mad_excl_e_thresh",
        "ReliabilitySignal.mad_excl_max_zero_frac",
        "ReliabilitySignal.mad_excl_min_keep_frac",
        "ReliabilitySignal.mad_excl_tau_floor",
    }

    def test_controls_are_the_trunks_with_the_mechanism_declared_off(self):
        for arm, trunk in (("control_maskfree", TRUNK_MASKFREE),
                           ("control_maskon", TRUNK_MASKON)):
            diff = _diff_keys(load_config(f"{T2}/method_t2_{arm}.yaml"), load_config(trunk))
            self.assertEqual(set(diff), {"ReliabilitySignal.mad_exclusion"}, arm)
            self.assertEqual(diff["ReliabilitySignal.mad_exclusion"], (False, None), arm)

    def test_each_treatment_differs_from_its_control_only_in_the_mechanism(self):
        for arm, ctrl in (("eflow", "control_maskfree"),
                          ("eboth", "control_maskon"),
                          ("qfree", "control_maskfree")):
            diff = _diff_keys(load_config(f"{T2}/method_t2_{arm}.yaml"),
                              load_config(f"{T2}/method_t2_{ctrl}.yaml"))
            self.assertTrue(
                set(diff) <= self.MECH,
                f"{arm} must differ from {ctrl} only in the T2 block: {diff}",
            )
            self.assertIn("ReliabilitySignal.mad_exclusion", diff, arm)

    def test_eboth_is_the_only_arm_that_can_see_a_semantic_mask(self):
        """The 追加约束 in config form. `mad_excl_candidates: cue` unions the semantic
        mask into the candidate set, so E-both is the only cue arm whose candidates can
        escape the frame-median normalisation that caps E-flow."""
        self.assertTrue(load_config(f"{T2}/method_t2_eboth.yaml")["SemanticMask"]["enabled"])
        for arm in ("eflow", "qfree", "control_maskfree"):
            self.assertFalse(
                load_config(f"{T2}/method_t2_{arm}.yaml")["SemanticMask"]["enabled"], arm
            )

    def test_qfree_is_cue_free_and_the_e_arms_are_not(self):
        self.assertEqual(
            load_config(f"{T2}/method_t2_qfree.yaml")["ReliabilitySignal"]["mad_excl_candidates"],
            "all",
        )
        for arm in ("eflow", "eboth"):
            self.assertEqual(
                load_config(f"{T2}/method_t2_{arm}.yaml")["ReliabilitySignal"]["mad_excl_candidates"],
                "cue", arm,
            )

    def test_quota_stays_below_the_collapse_boundary_in_every_arm(self):
        """max_zero_frac must stay strictly under 1/2. At 1/2 both median(d) and MAD(d)
        can be 0 and tau collapses to eps -- the exact pathology the quota replaces."""
        for arm in ("eflow", "eboth", "qfree"):
            rel = load_config(f"{T2}/method_t2_{arm}.yaml")["ReliabilitySignal"]
            self.assertLess(rel["mad_excl_max_zero_frac"], 0.5, arm)
            self.assertGreater(rel["mad_excl_min_keep_frac"], 0.0, arm)
            # exclusion and tau_floor push mean_w in OPPOSITE directions (M0 §5.3-2);
            # enabling both silently would make the arm uninterpretable
            self.assertEqual(rel["mad_excl_tau_floor"], 0.0, arm)

    def test_every_arm_covers_every_sequence_on_its_own_dataset(self):
        for arm in ("control_maskfree", "control_maskon", "eflow", "eboth", "qfree"):
            for seq in T2_SEQS:
                cfg = load_config(f"{T2}/t2_{arm}_{seq}.yaml")
                self.assertIn(
                    DATASET_TAIL[seq], cfg["Dataset"]["dataset_path"], f"{arm}/{seq}"
                )

    def test_static_guard_sequences_are_present(self):
        """The no-harm guardrail is only readable if the static sequences are in the
        campaign; M0 showed exclusion LOWERS mean_w, so static must be watched."""
        self.assertIn("f3_st_hf", T2_SEQS)
        self.assertIn("f2_xyz", T2_SEQS)


class T3SemanticOverrideContract(unittest.TestCase):
    def test_two_arms_differ_only_in_the_override(self):
        diff = _diff_keys(load_config(f"{T3}/method_t3_sem.yaml"),
                          load_config(f"{T3}/method_t3_off.yaml"))
        self.assertEqual(set(diff), {"AlphaLifecycle.semantic_alpha_override"})
        self.assertEqual(diff["AlphaLifecycle.semantic_alpha_override"], (0.0, None))

    def test_both_arms_are_mask_on(self):
        """Without a semantic mask `viewpoint.dynamic_mask` is None and the override is
        a permanent no-op -- the two arms would be byte-identical and the campaign would
        measure nothing. This is why T3 could NOT be built on R2-P02 arm D, which
        resolves to SemanticMask.enabled = False."""
        for arm in ("off", "sem"):
            self.assertTrue(
                load_config(f"{T3}/method_t3_{arm}.yaml")["SemanticMask"]["enabled"], arm
            )

    def test_alpha_lifecycle_is_on_in_the_arm_and_absent_from_the_trunk(self):
        """拍板③: T3 lives in its own arm and never enters the combined main trunk."""
        for arm in ("off", "sem"):
            self.assertEqual(
                load_config(f"{T3}/method_t3_{arm}.yaml")["AlphaLifecycle"]["mode"], "exit", arm
            )
        for trunk in (TRUNK_MASKON, TRUNK_MASKFREE):
            self.assertIsNone(load_config(trunk).get("AlphaLifecycle"), trunk)

    def test_run_configs_cover_both_arms_on_every_sequence(self):
        for arm in ("off", "sem"):
            for seq in T3_SEQS:
                cfg = load_config(f"{T3}/t3_{arm}_{seq}.yaml")
                self.assertIn(
                    DATASET_TAIL[seq], cfg["Dataset"]["dataset_path"], f"{arm}/{seq}"
                )
                self.assertTrue(cfg["SemanticMask"]["enabled"], f"{arm}/{seq}")


class DefaultOffAcrossTheTrunk(unittest.TestCase):
    """The single property all three retrofits share: with none of the new keys set, the
    trunk resolves exactly as before. Asserted on the trunks themselves so a stray key
    committed into a shared candidate config is caught here rather than in a 60-run batch."""

    def test_no_retrofit_key_leaks_into_either_trunk(self):
        leaked = (
            "DynamicKeyframe.anchor_probe",
            "ReliabilitySignal.mad_exclusion",
            "ReliabilitySignal.mad_excl_candidates",
            "AlphaLifecycle.semantic_alpha_override",
        )
        for trunk in (TRUNK_MASKON, TRUNK_MASKFREE):
            flat = _flatten(load_config(trunk))
            for key in leaked:
                self.assertNotIn(key, flat, f"{trunk} must not carry {key}")


if __name__ == "__main__":
    unittest.main()
