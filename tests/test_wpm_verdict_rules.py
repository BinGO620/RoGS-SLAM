"""WP-M verdict rule contract (2026-08-15, exp23).

The branch this readout picks decides what the paper is allowed to claim about
combined(mask-ON): M1 keeps "mask + kernel > mask alone", M2 forces the headline back
to the mask-free kernel, M3 says the kernel actively hurts under a mask. That makes
``build_wpm_verdict.classify``/``verdict`` the highest-stakes twenty lines in the repo,
and they run exactly once on data nobody has seen -- so they are pinned here against
synthetic inputs where the correct answer is known by construction.

Rules pinned (verbatim from results/evidence/wpm_maskonly_prereg.md, FROZEN):
  * delta = 0.15, denominator fixed at 18, evaluation order M0 -> M3 -> M1 -> M2 -> M4;
  * per-sequence: k<2 -> M0-UNRESOLVED; sd(Delta) > delta -> INDETERMINATE (counted in
    neither ">=delta" nor "<delta"); else mean vs +-delta;
  * M3 needs >=2 sequences where mask-only wins by delta AND all 3 seeds agree in sign;
  * M1 needs >=6 combined-better AND <=1 mask-only-better;
  * M2 needs >=12 no-difference.
If a rule below ever has to change, the prereg was violated -- fix the prereg trail
first (append a correction, never edit the frozen criteria).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts"))

import build_wpm_verdict as W  # noqa: E402


def seqs(**counts):
    """Build a {seq: classification} map from per-class counts, using real deltas."""
    rows, n = {}, 0
    recipes = {
        # class            -> per-seed Delta values that must produce it
        "combined-better": [0.40, 0.42, 0.44],     # mean +0.42 > delta, sd tiny
        "maskonly-better": [-0.40, -0.42, -0.44],  # mean -0.42 < -delta, 3/3 same sign
        "no-difference": [0.01, 0.00, -0.01],      # |mean| <= delta
        "INDETERMINATE": [-0.60, 0.00, 0.60],      # sd 0.60 > delta
    }
    for cls, k in counts.items():
        for _ in range(k):
            n += 1
            rows[f"seq{n}"] = W.classify(dict(enumerate(recipes[cls])))
    return rows


class ClassifyRule(unittest.TestCase):
    def test_delta_is_frozen(self):
        self.assertEqual(W.DELTA, 0.15)
        self.assertEqual(W.N_SEQ_DENOM, 18)
        self.assertEqual(W.COMPLETION_FRAC, 0.95)
        self.assertEqual(len(W.SEQORDER), 18)

    def test_k_below_two_is_unresolved(self):
        for deltas in ({}, {0: 0.9}):
            self.assertEqual(W.classify(deltas)["cls"], "M0-UNRESOLVED")

    def test_spread_beats_mean(self):
        """sd > delta is INDETERMINATE even when the mean looks decisive."""
        r = W.classify({0: 1.0, 1: 1.0, 2: -0.5})  # mean +0.5, sd 0.87
        self.assertEqual(r["cls"], "INDETERMINATE")

    def test_mean_thresholds(self):
        self.assertEqual(W.classify({0: 0.2, 1: 0.2, 2: 0.2})["cls"], "combined-better")
        self.assertEqual(W.classify({0: -0.2, 1: -0.2, 2: -0.2})["cls"], "maskonly-better")
        self.assertEqual(W.classify({0: 0.1, 1: 0.1, 2: 0.1})["cls"], "no-difference")

    def test_boundary_goes_to_no_difference(self):
        """|mean| == delta is the conservative bucket (makes M2 easier, not our claim)."""
        self.assertEqual(W.classify({0: 0.15, 1: 0.15, 2: 0.15})["cls"], "no-difference")

    def test_two_seeds_are_classifiable(self):
        r = W.classify({0: 0.3, 1: 0.32})
        self.assertEqual((r["k"], r["cls"]), (2, "combined-better"))

    def test_direction_convention(self):
        """Delta = log(maskonly/combined): positive MUST mean combined is better."""
        import math
        d = {s: math.log(10.0 / 5.0) for s in range(3)}  # mask-only 10cm vs combined 5cm
        self.assertEqual(W.classify(d)["cls"], "combined-better")


class BranchOrder(unittest.TestCase):
    def test_m0_campaign_guard(self):
        self.assertEqual(W.verdict(seqs())["branch"], "M0-CAMPAIGN-UNRESOLVED")
        allm0 = {f"seq{i}": W.classify({0: 0.5}) for i in range(18)}
        self.assertEqual(W.verdict(allm0)["branch"], "M0-CAMPAIGN-UNRESOLVED")

    def test_m3_fires_at_two_and_outranks_m1(self):
        v = W.verdict(seqs(**{"maskonly-better": 2, "combined-better": 10,
                              "no-difference": 6}))
        self.assertEqual(v["branch"], "M3-kernel-harmful-under-mask")

    def test_m3_needs_three_same_sign_seeds(self):
        """A mask-only win whose seeds disagree in sign must NOT trigger M3."""
        rows = seqs(**{"combined-better": 6, "no-difference": 10})
        # two mask-only wins by delta whose seed2 flips sign, with sd still <= delta
        # (mean -0.160 < -delta, sd 0.139): reachable, and must NOT count toward M3.
        rows["mixA"] = W.classify({0: -0.24, 1: -0.24, 2: 0.001})
        rows["mixB"] = W.classify({0: -0.24, 1: -0.24, 2: 0.001})
        v = W.verdict(rows)
        self.assertEqual(sorted(v["seqs"]["maskonly-better"]), ["mixA", "mixB"])
        self.assertEqual(v["seqs"]["M3-qualifying"], [])
        self.assertNotEqual(v["branch"], "M3-kernel-harmful-under-mask")

    def test_m1_needs_six_and_at_most_one_reversal(self):
        self.assertEqual(W.verdict(seqs(**{"combined-better": 6, "no-difference": 12}))[
            "branch"], "M1-kernel-adds-on-top-of-mask")
        self.assertEqual(W.verdict(seqs(**{"combined-better": 6, "maskonly-better": 1,
                                           "no-difference": 11}))["branch"],
                         "M1-kernel-adds-on-top-of-mask")
        # 5 is not 6 -> falls through (12 no-difference -> M2)
        self.assertEqual(W.verdict(seqs(**{"combined-better": 5, "no-difference": 12}))[
            "branch"], "M2-mask-dominates-kernel-redundant")

    def test_m2_needs_twelve(self):
        self.assertEqual(W.verdict(seqs(**{"no-difference": 12, "combined-better": 5}))[
            "branch"], "M2-mask-dominates-kernel-redundant")
        self.assertEqual(W.verdict(seqs(**{"no-difference": 11, "combined-better": 5,
                                           "INDETERMINATE": 2}))["branch"],
                         "M4-heterogeneous-stratified")

    def test_indeterminate_is_counted_in_neither_bucket(self):
        v = W.verdict(seqs(**{"INDETERMINATE": 18}))
        self.assertEqual(v["counts"]["INDETERMINATE"], 18)
        self.assertEqual(v["counts"]["no-difference"], 0)
        self.assertEqual(v["counts"]["combined-better"], 0)
        self.assertEqual(v["branch"], "M4-heterogeneous-stratified")

    def test_denominator_never_shrinks(self):
        """M0/INDETERMINATE sequences leave the denominator at 18 (no post-hoc dropping)."""
        v = W.verdict(seqs(**{"combined-better": 5, "no-difference": 3,
                              "INDETERMINATE": 2}))
        self.assertEqual(v["counts"]["denominator"], 18)
        self.assertEqual(v["branch"], "M4-heterogeneous-stratified")


class CompletionGate(unittest.TestCase):
    def _rec(self, ate, n_traj):
        return {"ate": ate, "n_traj": n_traj}

    def test_gate(self):
        self.assertTrue(W.completed(self._rec(5.0, 950), 1000))
        self.assertTrue(W.completed(self._rec(5.0, 1000), 1000))
        self.assertFalse(W.completed(self._rec(5.0, 949), 1000))

    def test_missing_denominator_fails_closed(self):
        self.assertFalse(W.completed(self._rec(5.0, 1000), None))

    def test_bad_ate_cannot_pair(self):
        self.assertFalse(W.completed(self._rec(None, 1000), 1000))
        self.assertFalse(W.completed(None, 1000))


class ArmResolution(unittest.TestCase):
    """The combined sources must partition the 18 sequences exactly as the main table
    resolves them, or the paired comparison would quote a different run."""

    def test_combined_sources_partition_18(self):
        self.assertEqual(len(W.P6MASON_COMBINED | W.MASON8_COMBINED), 13)
        self.assertFalse(W.P6MASON_COMBINED & W.MASON8_COMBINED)
        rest = set(W.SEQORDER) - W.P6MASON_COMBINED - W.MASON8_COMBINED
        self.assertEqual(rest, {"balloon", "balloon2", "mv_no_box", "mv_no_box2", "pt2"})

    def test_fullkern_takes_precedence_over_the_tainted_originals(self):
        """The 11 silent-K1R1L0 sequences must resolve to the RERUN, never the original.

        FULLKERN_COMBINED overlaps both P6MASON_COMBINED and MASON8_COMBINED on purpose:
        those originals ran with no flow_raft, so ReliabilitySignal silently no-op'd and
        they are mislabelled. Routing order is the only thing standing between this
        readout and a mask-only-vs-tainted-combined comparison, so it is pinned here.
        """
        self.assertTrue(W.FULLKERN_COMBINED & W.P6MASON_COMBINED)
        self.assertTrue(W.FULLKERN_COMBINED & W.MASON8_COMBINED)
        for seq in sorted(W.FULLKERN_COMBINED):
            self.assertIn("P6/P6-FULLKERN/", W.run_dir("results/runs", "combined", seq, 0),
                          f"{seq} must come from the FULLKERN rerun")

    def test_untainted_sequences_keep_their_original_source(self):
        """f3_wk_xyz / pt1 had flow all along -> they must NOT be re-routed."""
        for seq in ("f3_wk_xyz", "pt1"):
            self.assertNotIn(seq, W.FULLKERN_COMBINED)
            self.assertIn("P6/P6-MASON/", W.run_dir("results/runs", "combined", seq, 0))

    def test_paths(self):
        r = "results/runs"
        self.assertTrue(W.run_dir(r, "combined", "pt1", 0).endswith(
            "P6/P6-MASON/pt1_combined_seed0"))
        # f1_desk is one of the 11 reran sequences -> FULLKERN, not P6-MASON-8SEQ
        self.assertTrue(W.run_dir(r, "combined", "f1_desk", 1).endswith(
            "P6/P6-FULLKERN/f1_desk_combined_seed1"))
        self.assertTrue(W.run_dir(r, "combined", "balloon", 2).endswith(
            "P2/P2-T_3090/balloon_prune_seed2"))
        self.assertTrue(W.run_dir(r, "maskonly", "pt2", 0).endswith(
            "WPM/WPM-MASKONLY/wpm_pt2_maskonly_seed0"))
        self.assertTrue(W.run_dir(r, "vanilla", "pt2", 0).endswith(
            "WPA/WPA-FACTORIAL/wpa_pt2_K0R0L0_seed0"))

    def test_vanilla_scope_is_wpa_five(self):
        """Pairing against the main table's EXTERNAL MonoGS numbers is forbidden."""
        self.assertEqual(W.VANILLA_SEQS,
                         {"balloon", "mv_no_box", "mv_no_box2", "pt1", "pt2"})


if __name__ == "__main__":
    unittest.main()
