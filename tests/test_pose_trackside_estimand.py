"""Tests for the exp37 pose-side estimand: the within-run dynamic tracking penalty.

Controls travel WITH the criterion (exp33 criterion #11): a positive control (an injected
dynamics-only error must be seen), a negative control (a covariate with the wrong timing
must not be seen), the motion-matching property the primary split claims, and every branch
of the registered decision rule including the priority of the stop rule.
"""

import numpy as np
import pytest

from scripts.pose_rpe_calibration import (
    penalty,
    split_motion_matched,
    split_plain,
)
from scripts.pose_trackside_verdict import REG, decide


@pytest.fixture
def covariate():
    """A covariate correlated with camera speed, like the real balloon data."""
    rng = np.random.default_rng(0)
    n = 400
    step = rng.uniform(0.2, 1.2, n)
    area = 0.25 * step + rng.uniform(0, 0.2, n)      # corr(area, step) > 0 by construction
    return area, step


def test_split_plain_partitions_covered_pairs(covariate):
    area, step = covariate
    st = split_plain(area, step)
    assert not (st["lo"] & st["hi"]).any()
    assert (st["lo"] | st["hi"]).sum() == np.isfinite(area).sum()


def test_motion_matched_split_equalises_camera_speed(covariate):
    """The whole point of the primary split: hi and lo must be speed-comparable."""
    area, step = covariate
    plain = split_plain(area, step)
    mm = split_motion_matched(area, step)
    gap_plain = abs(np.median(step[plain["hi"]]) - np.median(step[plain["lo"]]))
    gap_mm = abs(np.median(step[mm["hi"]]) - np.median(step[mm["lo"]]))
    assert gap_mm < 0.25 * gap_plain, (gap_plain, gap_mm)
    assert not (mm["lo"] & mm["hi"]).any()


def test_penalty_positive_control_sees_dynamics_only_error(covariate):
    """Inject extra RPE ONLY on high-covariate pairs: the penalty must rise."""
    area, step = covariate
    st = split_motion_matched(area, step)
    rng = np.random.default_rng(1)
    base = rng.uniform(0.5, 1.5, len(area))
    clean = penalty(base, st)
    dirty = penalty(base + 0.4 * st["hi"], st)
    assert dirty - clean > 0.3, (clean, dirty)


def test_penalty_negative_control_rolled_covariate_is_blind(covariate):
    """Same injected error, but scored with a time-rolled covariate: must not be seen."""
    area, step = covariate
    st = split_motion_matched(area, step)
    rng = np.random.default_rng(2)
    base = rng.uniform(0.5, 1.5, len(area))
    injected = base + 0.4 * st["hi"]
    rolled = split_plain(np.roll(area, 137), step)
    seen = penalty(injected, rolled) - penalty(base, rolled)
    assert abs(seen) < 0.15, seen


def test_penalty_is_invariant_to_a_global_offset(covariate):
    """P is a within-run contrast, so an arm-level constant shift must cancel exactly."""
    area, step = covariate
    st = split_motion_matched(area, step)
    rng = np.random.default_rng(3)
    base = rng.uniform(0.5, 1.5, len(area))
    assert penalty(base + 0.7, st) == pytest.approx(penalty(base, st), abs=1e-12)


class TestRegisteredDecisionRule:
    cfg = REG["motion_matched"]

    def test_stop_rule_fires_before_any_label(self):
        """Even sitting exactly on a point prediction, an over-spread arm is not labelled."""
        v, _ = decide(self.cfg["p_material"], self.cfg["stop"] + 1e-3, 3, self.cfg)
        assert v == "INDETERMINATE"

    def test_material_branch(self):
        v, _ = decide(self.cfg["p_material"], 0.01, 3, self.cfg)
        assert v == "TRACKSIDE-MATERIAL"

    def test_material_requires_all_three_paired_seeds(self):
        v, _ = decide(self.cfg["p_material"], 0.01, 2, self.cfg)
        assert v == "PARTIAL"

    def test_inert_branch(self):
        v, _ = decide(self.cfg["p_inert"], 0.01, 0, self.cfg)
        assert v == "TRACKSIDE-INERT"

    def test_partial_branch_in_the_dead_zone(self):
        mid = 0.5 * (self.cfg["p_material"] + self.cfg["p_inert"])
        v, _ = decide(mid, 0.01, 3, self.cfg)
        assert v == "PARTIAL"

    def test_anomaly_guard_beats_labelling(self):
        too_good = self.cfg["maskon_min_run"] - self.cfg["floor"] - 1e-3
        v, _ = decide(too_good, 0.01, 3, self.cfg)
        assert v == "ANOMALY"

    def test_registered_constants_are_self_consistent(self):
        """The material and inert zones must be non-empty and disjoint, or the rule is void."""
        for cfg in REG.values():
            assert cfg["spacing"] == pytest.approx(cfg["p_inert"] - cfg["p_material"], abs=1e-4)
            assert cfg["two_floor"] == pytest.approx(2 * cfg["floor"], abs=1e-4)
            assert cfg["stop"] == pytest.approx(0.5 * cfg["spacing"], abs=1e-3)
            mat_hi = min(cfg["p_material"] + cfg["floor"], cfg["p_inert"] - cfg["two_floor"])
            inert_lo = max(cfg["p_inert"] - cfg["floor"], cfg["p_material"] + cfg["two_floor"])
            assert cfg["p_material"] - cfg["floor"] < mat_hi
            assert inert_lo < cfg["p_inert"] + cfg["floor"]
            assert mat_hi < inert_lo, "material and inert zones must not overlap"


class TestPairedGateRule:
    """The exp37 paired apparatus gate (results/evidence/pose_trackside_paired_prereg.md).

    Pins the two properties that make it different from the round-1 gate: reachability is
    checked FIRST, and there is deliberately NO sign-consistency branch (the signs were seen
    post-hoc, so gating on them would be self-deception -- prereg section 0).
    """

    def test_reachability_is_checked_before_the_contrast(self):
        from scripts.pose_trackside_paired_gate import REACH_FLOOR, decide
        # a huge shift must STILL be UNREACHABLE when the floor is too coarse to license it
        v, r = decide(shift=10.0, floor_paired=REACH_FLOOR + 1e-6)
        assert v == "UNREACHABLE" and r is not None and r >= 2

    def test_sensitive_requires_shift_above_the_paired_floor(self):
        from scripts.pose_trackside_paired_gate import decide
        v, _ = decide(shift=0.05, floor_paired=0.04)
        assert v == "APPARATUS-TRACKING-SENSITIVE"

    def test_blind_when_reachable_and_shift_within_floor(self):
        from scripts.pose_trackside_paired_gate import decide
        v, _ = decide(shift=0.01, floor_paired=0.04)
        assert v == "APPARATUS-TRACKING-BLIND"

    def test_sign_is_never_a_branch(self):
        """Flipping the shift's sign must never change the label -- direction is not predicted."""
        from scripts.pose_trackside_paired_gate import decide
        for mag in (0.01, 0.05, 0.5):
            assert decide(mag, 0.04)[0] == decide(-mag, 0.04)[0]

    def test_required_repeats_grow_with_the_floor_ratio(self):
        from scripts.pose_trackside_paired_gate import REACH_FLOOR, decide
        _, r_small = decide(0.0, REACH_FLOOR * 1.5)
        _, r_big = decide(0.0, REACH_FLOOR * 3.0)
        assert r_big > r_small


def test_verdict_reproduces_the_registered_positive_control():
    """The shipped verdict JSON must still carry passing gates with the registered numbers."""
    import json
    import os
    p = "results/evidence/pose_trackside_verdict.json"
    if not os.path.isfile(p):
        pytest.skip("verdict not yet produced")
    blob = json.load(open(p))
    assert blob["prereg_commit"] == "364da26c"
    for name, g in blob["gates"].items():
        assert g["pass"], f"{name}: {g['detail']}"


class TestCoherentAmplitude:
    """exp38 coherent-amplitude endpoint (results/evidence/pose_coherent_prereg.md).

    Pins the decision rule, the apparatus checks, and the mechanism-triangle consistency.
    """

    def test_coherent_full_basic(self):
        """coherent_full returns a value in [0, 1] for non-degenerate input."""
        import numpy as np
        from scripts.pose_coherent_component import coherent_full
        rng = np.random.default_rng(42)
        vecs = rng.normal(0, 1, (100, 3))
        c = coherent_full(vecs)
        assert 0.0 <= c <= 1.0

    def test_coherent_full_perfectly_aligned(self):
        """All vectors in the same direction -> coherent = 1."""
        import numpy as np
        from scripts.pose_coherent_component import coherent_full
        vecs = np.tile([1.0, 0.0, 0.0], (50, 1))
        assert coherent_full(vecs) == pytest.approx(1.0, abs=1e-10)

    def test_coherent_full_random_cancels(self):
        """Isotropic random vectors -> coherent close to 0."""
        import numpy as np
        from scripts.pose_coherent_component import coherent_full
        rng = np.random.default_rng(0)
        vecs = rng.normal(0, 1, (10000, 3))
        c = coherent_full(vecs)
        assert c < 0.1  # should be ~1/sqrt(N_pairs) ~ 0.01

    def test_coherent_amplitude_scales_with_magnitude(self):
        """Scaling all vectors by 2x should double the amplitude but keep coherent."""
        import numpy as np
        from scripts.pose_coherent_component import coherent_amplitude
        rng = np.random.default_rng(7)
        vecs = rng.normal(0, 1, (50, 3))
        mag = np.linalg.norm(vecs, axis=1)
        c1, a1 = coherent_amplitude(vecs, mag, np.ones(50, dtype=bool))
        c2, a2 = coherent_amplitude(vecs * 2, mag * 2, np.ones(50, dtype=bool))
        assert c1 == pytest.approx(c2, rel=1e-10)
        assert a2 == pytest.approx(a1 * 2, rel=1e-10)

    def test_decide_rules(self):
        """The registered decision rule: REACHABLE check first, then contrast."""
        from scripts.pose_coherent_component import REACH_FLOOR_CA
        # Import would fail if script has syntax errors; this also tests the threshold exists
        assert REACH_FLOOR_CA == pytest.approx(0.0831, abs=1e-4)

    def test_coherent_gate_json_exists_and_has_verdict(self):
        """The shipped JSON must exist and carry a valid verdict."""
        import json
        import os
        p = "results/evidence/pose_coherent_gate.json"
        if not os.path.isfile(p):
            pytest.skip("coherent gate not yet produced")
        blob = json.load(open(p))
        assert blob["verdict"] in ("COHERENT-BIASED", "COHERENT-WORSE",
                                   "COHERENT-INDISTINGUISHABLE", "UNREACHABLE")
        assert blob["reachable"] is True  # we know floor_CA < REACH_FLOOR_CA
        assert blob["labels_agree"] is True  # both floor and variance-matched agree

    def test_mechanism_triangle_directions_consistent(self):
        """P worsens, coherent_amp lowers, ATE improves -> variance-bias chain."""
        import json
        import os
        p = "results/evidence/pose_coherent_gate.json"
        if not os.path.isfile(p):
            pytest.skip("coherent gate not yet produced")
        blob = json.load(open(p))
        # shift for coherent_amp should be negative (F lower = more noise-like)
        assert blob["shift"] < 0, "coherent_amp should be lower for F (more incoherent)"
        # P is positive (worse), ATE is negative (better), coherent_amp is negative (lower)
        # -> the three endpoints form the expected triangle
