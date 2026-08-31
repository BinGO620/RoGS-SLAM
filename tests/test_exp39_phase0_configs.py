"""exp39 Phase-0 config contract (pre-registration gate G-0).

The Phase-0 claim is that W and H differ in exactly one thing: how the mapping/BA loss
aggregates dynamic pixels. That claim is only as good as this file -- if any other field
drifts between the two arms, the probe readings attribute a difference to the floor that
some other knob produced.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_utils import load_config  # noqa: E402
from utils.mapping_weight import (  # noqa: E402
    mapping_scale_match_floor,
    mapping_soft_floor,
)

ARMS = {
    "hard": "configs/rgbd/experiments/exp39_mapping_soft/exp39_hard_balloon.yaml",
    "soft025": "configs/rgbd/experiments/exp39_mapping_soft/exp39_soft025_balloon.yaml",
}
# Phase 1 adds the scale-matched control and a second sequence. Every arm of every
# sequence must still differ only in the aggregation knob.
PHASE1 = {
    seq: {
        arm: f"configs/rgbd/experiments/exp39_mapping_soft/exp39_{arm}_{seq}.yaml"
        for arm in ("hard", "soft025", "scale025")
    }
    for seq in ("balloon", "mv_no_box")
}
FLOOR = 0.25
# The knobs the arms are allowed to differ in. `method` is the run label.
ALLOWED_DIFF = {"soft_mapping", "mapping_floor", "mapping_scale_match"}


@pytest.fixture(scope="module")
def configs():
    return {name: load_config(path) for name, path in ARMS.items()}


class TestExp39Phase0Configs:
    def test_only_the_aggregation_knob_differs(self, configs):
        hard, soft = configs["hard"]["SemanticMask"], configs["soft025"]["SemanticMask"]
        differing = {
            key
            for key in set(hard) | set(soft)
            if hard.get(key) != soft.get(key)
        }
        assert differing <= ALLOWED_DIFF, f"arms drifted in {differing - ALLOWED_DIFF}"

    def test_nothing_outside_semanticmask_differs(self, configs):
        hard, soft = configs["hard"], configs["soft025"]
        differing = {
            key
            for key in set(hard) | set(soft)
            if key not in ("SemanticMask", "method", "Results")
            and hard.get(key) != soft.get(key)
        }
        assert not differing, f"arms differ outside SemanticMask: {differing}"

    def test_treatment_floor_is_the_registered_value(self, configs):
        assert mapping_soft_floor(configs["soft025"]) == pytest.approx(FLOOR)

    def test_control_is_the_hard_mask(self, configs):
        assert mapping_soft_floor(configs["hard"]) is None

    def test_neither_arm_enables_the_phase1_scale_match(self, configs):
        """Scale matching is a Phase-1 arm; smuggling it into Phase 0 would make the
        control neither the frozen hard arm nor the registered control."""
        for name, config in configs.items():
            assert mapping_scale_match_floor(config) is None, name

    def test_mask_mapping_is_on_in_both(self, configs):
        """With mask_mapping off the floor is inert -- the arm would silently be a no-op."""
        for name, config in configs.items():
            assert config["SemanticMask"]["mask_mapping"] is True, name

    def test_probe_is_armed_in_both(self, configs):
        """G-2 (the negative control) needs probe rows from the CONTROL arm too."""
        for name, config in configs.items():
            probe = config.get("MappingProbe", {})
            assert probe.get("enabled") is True, name
            assert probe.get("interval") == 50, name


class TestExp39Phase1Configs:
    """Phase 1 = three arms x two sequences. The scale-matched control S is the one that
    makes a W-vs-H difference attributable to the weight SHAPE rather than to the
    photometric term's magnitude, so its contract matters as much as the treatment's."""

    @pytest.mark.parametrize("seq", sorted(PHASE1))
    def test_three_arms_differ_only_in_the_aggregation_knob(self, seq):
        blocks = {
            arm: load_config(path)["SemanticMask"] for arm, path in PHASE1[seq].items()
        }
        keys = set().union(*(set(b) for b in blocks.values()))
        differing = {
            key
            for key in keys
            if len({str(b.get(key)) for b in blocks.values()}) > 1
        }
        assert differing <= ALLOWED_DIFF, f"{seq}: arms drifted in {differing - ALLOWED_DIFF}"

    @pytest.mark.parametrize("seq", sorted(PHASE1))
    def test_each_arm_is_the_arm_it_claims(self, seq):
        configs = {arm: load_config(path) for arm, path in PHASE1[seq].items()}
        assert mapping_soft_floor(configs["hard"]) is None
        assert mapping_scale_match_floor(configs["hard"]) is None
        assert mapping_soft_floor(configs["soft025"]) == pytest.approx(FLOOR)
        assert mapping_scale_match_floor(configs["soft025"]) is None
        assert mapping_soft_floor(configs["scale025"]) is None
        assert mapping_scale_match_floor(configs["scale025"]) == pytest.approx(FLOOR)

    @pytest.mark.parametrize("seq", sorted(PHASE1))
    def test_scale_control_matches_the_treatment_floor(self, seq):
        """S must match W's floor: matching a different floor would control for a scale
        the treatment never had."""
        soft = load_config(PHASE1[seq]["soft025"])
        scale = load_config(PHASE1[seq]["scale025"])
        assert mapping_scale_match_floor(scale) == pytest.approx(mapping_soft_floor(soft))

    @pytest.mark.parametrize("seq", sorted(PHASE1))
    def test_probe_armed_and_mask_mapping_on(self, seq):
        for arm, path in PHASE1[seq].items():
            config = load_config(path)
            assert config["SemanticMask"]["mask_mapping"] is True, f"{seq}/{arm}"
            assert config.get("MappingProbe", {}).get("enabled") is True, f"{seq}/{arm}"
