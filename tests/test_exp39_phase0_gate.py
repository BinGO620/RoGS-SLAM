"""exp39 Phase-0 gate unit tests — every gate is fed a known-bad value.

exp37 lesson (criterion #9/#11): a gate that cannot fail is not a gate. Each test below
feeds the evaluator an input that MUST be rejected, so a green Phase-0 verdict means the
gates actually discriminated rather than waved everything through.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from exp39_phase0_gate import INERT_SHARE, MASS_SHARE, evaluate  # noqa: E402

GOOD_AREAS = [0.12] * 30


def hard_arm(**over):
    base = {
        "rows": 100,
        "floor": 0.0,
        "dyn_share_map": 0.0,
        "dyn_share_pose": 0.0,
        "pose_to_map_ratio": 12.0,
        "max_dyn_share_map": 0.0,
        "max_dyn_share_pose": 0.0,
    }
    base.update(over)
    return base


def soft_arm(**over):
    base = {
        "rows": 100,
        "floor": 0.25,
        "dyn_share_map": 0.35,
        "dyn_share_pose": 0.20,
        "pose_to_map_ratio": 11.0,
        "max_dyn_share_map": 0.6,
        "max_dyn_share_pose": 0.4,
    }
    base.update(over)
    return base


class TestGatesRejectKnownBad:
    def test_nonzero_control_share_fails_g2(self):
        """A control arm showing ANY dynamic gradient means the probe is mis-measuring."""
        verdict, gates, _ = evaluate(
            hard_arm(max_dyn_share_map=1e-9), soft_arm(), GOOD_AREAS, GOOD_AREAS
        )
        assert gates["G-2 negative control"] is False
        assert verdict == "NO VERDICT"

    def test_thin_probe_coverage_fails_g3a(self):
        verdict, gates, _ = evaluate(
            hard_arm(rows=5), soft_arm(), GOOD_AREAS, GOOD_AREAS
        )
        assert gates["G-3a probe coverage"] is False
        assert verdict == "NO VERDICT"

    def test_mask_area_far_from_audit_fails_g3b(self):
        verdict, gates, _ = evaluate(
            hard_arm(), soft_arm(), [0.40] * 30, [0.40] * 30
        )
        assert gates["G-3b mask area vs audit"] is False
        assert verdict == "NO VERDICT"

    def test_wrong_floor_fails_g0(self):
        verdict, gates, _ = evaluate(
            hard_arm(), soft_arm(floor=0.5), GOOD_AREAS, GOOD_AREAS
        )
        assert gates["G-0 floors as registered"] is False
        assert verdict == "NO VERDICT"


class TestDecisionRule:
    def test_live_when_both_shares_exceed_mass_share(self):
        verdict, _, _ = evaluate(hard_arm(), soft_arm(), GOOD_AREAS, GOOD_AREAS)
        assert verdict == "MECHANISM-LIVE"

    def test_inert_when_a_share_collapses(self):
        verdict, _, _ = evaluate(
            hard_arm(),
            soft_arm(dyn_share_pose=INERT_SHARE / 2),
            GOOD_AREAS,
            GOOD_AREAS,
        )
        assert verdict == "MECHANISM-INERT"

    def test_partial_between_the_two_thresholds(self):
        verdict, _, _ = evaluate(
            hard_arm(),
            soft_arm(dyn_share_pose=(INERT_SHARE + MASS_SHARE) / 2),
            GOOD_AREAS,
            GOOD_AREAS,
        )
        assert verdict == "PARTIAL"

    def test_reshaping_beats_the_share_reading(self):
        """The dead DBAphoto failure mode outranks a healthy-looking share: if the joint
        BA was reshaped, a large dynamic share is not evidence the arm is working."""
        verdict, _, _ = evaluate(
            hard_arm(pose_to_map_ratio=12.0),
            soft_arm(pose_to_map_ratio=30.0),
            GOOD_AREAS,
            GOOD_AREAS,
        )
        assert verdict == "MECHANISM-RESHAPING"

    def test_reshaping_triggers_in_the_collapse_direction_too(self):
        verdict, _, _ = evaluate(
            hard_arm(pose_to_map_ratio=12.0),
            soft_arm(pose_to_map_ratio=4.0),
            GOOD_AREAS,
            GOOD_AREAS,
        )
        assert verdict == "MECHANISM-RESHAPING"
