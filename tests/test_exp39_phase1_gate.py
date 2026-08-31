"""exp39 Phase-1 decision-rule tests — known-bad feeds for each branch.

The three-branch rule is the whole point of paying for the scale-matched arm, so each
branch is exercised with numbers that must land there and not somewhere flattering.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from exp39_phase1_gate import NOISE_FLOOR_REL, classify  # noqa: E402


class TestThreeBranchRule:
    def test_shape_material_needs_to_beat_the_scale_control(self):
        # H=10, S=9.8, W=8.5: W beats both by more than 6%
        assert classify(10.0, 8.5, 9.8)[0] == "SHAPE-MATERIAL"

    def test_scale_explained_when_the_control_captures_the_gain(self):
        """The trap the scale-matched arm exists to catch: W looks good against H, but
        the hard arm rescaled to the same weight mass is just as good."""
        assert classify(10.0, 8.5, 8.5)[0] == "SCALE-EXPLAINED"

    def test_indistinguishable_when_nothing_clears_the_floor(self):
        assert classify(10.0, 9.8, 9.9)[0] == "INDISTINGUISHABLE"

    def test_soft_worse_is_reported_not_swallowed(self):
        assert classify(10.0, 12.0, 10.1)[0] == "SOFT-WORSE"

    def test_missing_arm_is_no_verdict_not_a_two_arm_read(self):
        assert classify(10.0, 8.0, None)[0] == "NO VERDICT"

    def test_a_gain_exactly_at_the_floor_does_not_count(self):
        """Strictly greater than the floor: a difference equal to the noise floor is
        exactly the case the floor says is unreadable."""
        hard = 10.0
        soft = hard - hard * NOISE_FLOOR_REL
        assert classify(hard, soft, hard)[0] != "SHAPE-MATERIAL"

    def test_floor_scales_with_the_arm_it_is_compared_against(self):
        """A 0.5 cm gap is decisive at ATE ~3 cm and noise at ATE ~30 cm."""
        assert classify(3.0, 2.5, 3.0)[0] == "SHAPE-MATERIAL"
        assert classify(30.0, 29.5, 30.0)[0] == "INDISTINGUISHABLE"
