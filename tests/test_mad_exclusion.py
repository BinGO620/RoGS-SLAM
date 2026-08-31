"""CPU unit tests for the T2 adaptive-quota MAD scale-domain isolation.

The mechanism under test estimates the Cauchy ``tau`` on the STATIC subgroup by
removing the ``k`` most-anomalous candidate pixels, where ``k`` comes from a closed
form that makes the zero-mass MAD collapse UNREACHABLE rather than merely guarded:

    zero_frac_after = zero_frac_before / (1 - excl_frac) <= max_zero_frac

M0 (``results/evidence/m0_mad_exclusion/``) measured the failure this replaces: a
fixed ``e_flow > 0.5`` threshold drove 47.5% of frames past ``zero_frac = 0.5``, where
``median(d) == MAD(d) == 0``, ``tau`` collapses to ``eps``, and ``w`` degenerates into
a hard binary mask. Test 3 pins exactly that scenario and asserts the quota refuses it.

Run:
    /data/conda_envs/monogs-ours/bin/python -m unittest tests.test_mad_exclusion
"""

import unittest

import torch

from utils.reliability_signal import (
    _MAD_CONST,
    cauchy_tracking_weight,
    compute_reliability_tracking_weight,
    _mad_exclusion_candidates,
)


def _tau_of(d):
    med = d.median()
    return float(med + _MAD_CONST * (d - med).abs().median() + 1e-6)


def _frame(zero_frac, mover_frac, n=10000, seed=0):
    """Synthetic ``s`` with an exact exactly-zero mass, a high-``d`` mover block, and a
    low-``d`` static remainder. ``d = 1 - s``, so ``s == 1`` is the zero-``d`` mass."""
    g = torch.Generator().manual_seed(seed)
    n_zero = int(round(zero_frac * n))
    n_mov = int(round(mover_frac * n))
    d = torch.empty(n)
    d[:n_zero] = 0.0
    d[n_zero:n_zero + n_mov] = 0.9
    rest = n - n_zero - n_mov
    d[n_zero + n_mov:] = torch.rand(rest, generator=g) * 0.1
    s = (1.0 - d).reshape(100, -1)
    mover = torch.zeros(n, dtype=torch.bool)
    mover[n_zero:n_zero + n_mov] = True
    return s, mover.reshape(100, -1)


class ScaleCounterfactual(unittest.TestCase):
    """`tau_scale` is the T2-scale arm: no exclusion, tau *= c. It exists so the
    campaign can LOSE the isolation story -- if a fixed c reproduces the quota's ATE,
    the mechanism's real name is "sharper robust kernel", not "static-subgroup
    isolation" (REVIEW §7.1). These tests pin the two properties the comparison rests
    on: the default is an exact no-op, and the knob does nothing but scale tau."""

    def test_default_is_an_exact_no_op(self):
        """Every non-scale arm runs this same code path, so 1.0 must not merely be
        close -- it must be bit-identical, or the whole campaign is cross-commit."""
        s, mover = _frame(0.30, 0.25)
        for kwargs in ({}, {"exclusion_mask": mover}, {"tau_floor": 0.3}):
            base = cauchy_tracking_weight(s, **kwargs)
            got = cauchy_tracking_weight(s, tau_scale=1.0, **kwargs)
            self.assertTrue(torch.equal(base, got), f"drifted with {kwargs}")

    def test_scale_is_exactly_a_tau_multiply(self):
        """w = 1/(1+(d/(c*tau))^2) -- read off the closed form, not re-derived from
        the code, so an implementation that scaled `d` instead would fail here."""
        s, _ = _frame(0.30, 0.25)
        d = 1.0 - s
        tau = _tau_of(d[torch.isfinite(d)])
        c = 0.45
        got = cauchy_tracking_weight(s, tau_scale=c)
        want = 1.0 / (1.0 + (d / (c * tau)) ** 2)
        self.assertTrue(torch.allclose(got, want, atol=1e-6))

    def test_c_below_one_lowers_mean_w_like_exclusion_does(self):
        """Direction check: this is WHY the two arms are confusable. Both push mean_w
        down; only the campaign can say whether they land in the same place."""
        s, mover = _frame(0.30, 0.25)
        w_ctrl = cauchy_tracking_weight(s)
        w_scale = cauchy_tracking_weight(s, tau_scale=0.45)
        w_excl = cauchy_tracking_weight(s, exclusion_mask=mover)
        self.assertLess(float(w_scale.mean()), float(w_ctrl.mean()))
        self.assertLess(float(w_excl.mean()), float(w_ctrl.mean()))

    def test_scale_does_not_touch_the_exclusion_stats(self):
        """The scale arm must be readable on disk as "no exclusion happened"."""
        s, _ = _frame(0.30, 0.25)
        stats = {}
        cauchy_tracking_weight(s, tau_scale=0.45, stats_out=stats)
        self.assertNotIn("mad_excl_k", stats)


class QuotaExclusionCore(unittest.TestCase):
    def test_default_path_is_byte_identical(self):
        """No exclusion_mask => the historic single-domain estimate, bit for bit.
        This is the byte-identical fallback the whole retrofit rests on."""
        s, _ = _frame(0.30, 0.25)
        base = cauchy_tracking_weight(s)
        for kwargs in (
            {},
            {"max_zero_frac": 0.45, "min_keep_frac": 0.20},
            {"exclusion_mask": None, "tau_floor": 0.0},
            {"stats_out": {}},
        ):
            got = cauchy_tracking_weight(s, **kwargs)
            self.assertTrue(torch.equal(base, got), f"drifted with {kwargs}")

    def test_isolation_sharpens_the_mover_background_contrast(self):
        """Positive mechanism, stated honestly. Removing a 25% mover from the
        ESTIMATION domain pulls tau down onto the static population, which sharpens the
        CONTRAST between mover weight and background weight -- the thing the mechanism
        exists to do.

        It does NOT leave the background untouched: a tighter tau down-weights every
        non-zero-d pixel, so mean_w falls overall. That is the measured M0 result
        (mean_w 0.624 -> 0.592 on f3_st_hf) and the reason exclusion and `tau_floor`
        are ANTAGONISTIC, not complementary. Pinned here so nobody re-reads this
        mechanism as a no-harm one."""
        s, mover = _frame(0.30, 0.25)
        stats = {}
        w0 = cauchy_tracking_weight(s)
        w1 = cauchy_tracking_weight(s, exclusion_mask=mover, stats_out=stats)
        self.assertGreater(stats["mad_excl_k"], 0)
        self.assertLess(stats["mad_tau_after"], stats["mad_tau_before"])
        c0 = float(w0[mover].mean()) / float(w0[~mover].mean())
        c1 = float(w1[mover].mean()) / float(w1[~mover].mean())
        self.assertLess(c1, 0.5 * c0)
        self.assertLess(float(w1[~mover].mean()), float(w0[~mover].mean()))

    def test_collapse_is_unreachable_not_merely_guarded(self):
        """THE M0 scenario. zero_frac_before=0.45 with a 25% candidate block would give
        0.45/0.75 = 0.60 > 0.5 under the old fixed threshold => median=MAD=0 => tau=eps.
        The quota must cap k so the frame never crosses max_zero_frac, and tau must stay
        far away from the eps floor."""
        s, mover = _frame(0.45, 0.25)
        stats = {}
        w = cauchy_tracking_weight(
            s, exclusion_mask=mover, max_zero_frac=0.45, stats_out=stats
        )
        self.assertLessEqual(stats["mad_zero_frac_after"], 0.45 + 1e-9)
        self.assertGreater(stats["mad_tau_after"], 1e-4)
        self.assertGreater(float(w.min()), 0.0)

    def test_frame_already_past_the_cap_excludes_nothing(self):
        """zero_frac_before > max_zero_frac => the closed form yields k <= 0 => the
        estimate falls back to the full domain, bit for bit. This is the f3_st_hf case
        M0 found (quota ceiling computed NEGATIVE): a static sequence correctly admits
        no exclusion at all."""
        s, mover = _frame(0.55, 0.20)
        stats = {}
        w = cauchy_tracking_weight(
            s, exclusion_mask=mover, max_zero_frac=0.45, stats_out=stats
        )
        self.assertEqual(stats["mad_excl_k"], 0)
        self.assertEqual(stats["mad_excl_applied"], 0)
        self.assertEqual(stats["mad_excl_bind"], "none")
        self.assertTrue(torch.equal(w, cauchy_tracking_weight(s)))

    def test_min_keep_frac_caps_a_greedy_quota(self):
        """With almost no zero mass the quota alone would allow removing nearly the
        whole frame; min_keep_frac has to hold the domain open."""
        s, _ = _frame(0.02, 0.30)
        allmask = torch.ones_like(s, dtype=torch.bool)
        stats = {}
        cauchy_tracking_weight(
            s, exclusion_mask=allmask, min_keep_frac=0.20, stats_out=stats
        )
        self.assertEqual(stats["mad_excl_bind"], "min_keep")
        self.assertLessEqual(stats["mad_excl_frac"], 0.80 + 1e-9)

    def test_k_is_capped_by_the_candidate_set(self):
        """A small cue selects little even when the quota would allow much more; the
        binding cap must be reported as `candidates` so a weak arm is attributable."""
        s, _ = _frame(0.05, 0.30)
        cand = torch.zeros_like(s, dtype=torch.bool)
        cand.reshape(-1)[500:800] = True  # 3% of the frame, inside the mover block
        stats = {}
        cauchy_tracking_weight(s, exclusion_mask=cand, stats_out=stats)
        self.assertEqual(stats["mad_excl_bind"], "candidates")
        self.assertEqual(stats["mad_excl_k"], 300)

    def test_zero_d_pixels_are_never_removed(self):
        """The closed form assumes the zero mass is invariant under exclusion. If a
        zero-d pixel could be removed the identity breaks and the cap stops binding."""
        s, _ = _frame(0.30, 0.25)
        allmask = torch.ones_like(s, dtype=torch.bool)
        stats = {}
        cauchy_tracking_weight(s, exclusion_mask=allmask, stats_out=stats)
        n = s.numel()
        kept = n - stats["mad_excl_k"]
        self.assertAlmostEqual(
            stats["mad_zero_frac_after"], 0.30 * n / kept, places=6
        )

    def test_excluded_pixels_still_receive_a_weight(self):
        """Semantics: exclusion touches the ESTIMATION DOMAIN of tau only. Excluded
        pixels are not zero-weighted and not dropped from the loss."""
        s, mover = _frame(0.30, 0.25)
        w = cauchy_tracking_weight(s, exclusion_mask=mover)
        self.assertTrue(bool((w[mover] > 0).all()))
        self.assertTrue(bool(torch.isfinite(w).all()))

    def test_tau_floor_is_orthogonal_and_raises_w(self):
        """tau_floor is a separate knob that pushes mean_w the OPPOSITE way to
        exclusion (M0 §5.3-2). Pin the direction so the two are never conflated."""
        s, mover = _frame(0.30, 0.25)
        w_lo = cauchy_tracking_weight(s, exclusion_mask=mover)
        w_hi = cauchy_tracking_weight(s, exclusion_mask=mover, tau_floor=0.5)
        self.assertGreater(float(w_hi.mean()), float(w_lo.mean()))

    def test_single_cue_mode_is_inert_by_construction(self):
        """flow-only s has tau already collapsed (M0 / probe_mad_exclusion): d is a
        two-valued field whose median is 0, so no domain surgery can move tau. Pinning
        it here stops a future campaign expecting the P7 single-cue arms to react."""
        d = torch.zeros(100, 100)
        d[:40] = 0.9                       # 40% "dynamic", 60% exactly zero
        s = 1.0 - d
        cand = d > 0.5
        self.assertTrue(torch.equal(
            cauchy_tracking_weight(s),
            cauchy_tracking_weight(s, exclusion_mask=cand),
        ))


class CandidateAssembly(unittest.TestCase):
    def setUp(self):
        self.e = torch.zeros(8, 8)
        self.e[:2] = 0.9
        self.fv = torch.ones(8, 8, dtype=torch.bool)

    def test_cue_without_semantic_is_the_flow_term(self):
        mask, used = _mad_exclusion_candidates(self.e, self.fv, None, 0.5, "cue")
        self.assertEqual(used, 0)
        self.assertTrue(torch.equal(mask, self.e > 0.5))

    def test_cue_unions_the_semantic_mask(self):
        sem = torch.zeros(1, 8, 8, dtype=torch.bool)
        sem[0, 6:] = True
        mask, used = _mad_exclusion_candidates(self.e, self.fv, sem, 0.5, "cue")
        self.assertEqual(used, 1)
        self.assertEqual(int(mask.sum()), 32)

    def test_shape_mismatch_is_reported_not_silently_dropped(self):
        sem = torch.ones(1, 4, 4, dtype=torch.bool)
        mask, used = _mad_exclusion_candidates(self.e, self.fv, sem, 0.5, "cue")
        self.assertEqual(used, 0)
        self.assertTrue(torch.equal(mask, self.e > 0.5))

    def test_all_mode_is_cue_free(self):
        mask, used = _mad_exclusion_candidates(self.e, self.fv, None, 0.5, "all")
        self.assertEqual(used, 0)
        self.assertTrue(bool(mask.all()))

    def test_unknown_candidate_mode_raises(self):
        with self.assertRaises(ValueError):
            _mad_exclusion_candidates(self.e, self.fv, None, 0.5, "everything")

    def test_invalid_flow_pixels_are_not_candidates(self):
        fv = self.fv.clone()
        fv[:1] = False
        mask, _ = _mad_exclusion_candidates(self.e, fv, None, 0.5, "cue")
        self.assertTrue(bool((~mask[:1]).all()))


class WrapperProvenance(unittest.TestCase):
    """The wrapper must declare the mechanism on EVERY run and measure it only when
    it ran -- the ego_* column contract (a hard-coded whitelist once deleted an entire
    campaign's provenance, see reliability_frames_fields)."""

    def _call(self, **kw):
        h = w = 24
        obs = torch.full((h, w), 2.0)
        ren = obs.clone()
        ren[:6] += 0.6
        return compute_reliability_tracking_weight(
            obs, ren, torch.ones(h, w), torch.zeros(h, w, 2),
            torch.eye(3), torch.zeros(3),
            300.0, 300.0, w / 2, h / 2, **kw
        )

    def test_off_declares_and_does_not_measure(self):
        _, _, _, stats = self._call()
        self.assertEqual(stats["mad_exclusion"], 0)
        self.assertNotIn("mad_excl_applied", stats)
        self.assertNotIn("mad_tau_after", stats)

    def test_on_declares_and_measures(self):
        _, _, _, stats = self._call(mad_exclusion=True, mad_excl_candidates="all")
        self.assertEqual(stats["mad_exclusion"], 1)
        for key in (
            "mad_excl_applied", "mad_excl_k", "mad_excl_frac", "mad_excl_bind",
            "mad_zero_frac_before", "mad_zero_frac_after",
            "mad_tau_before", "mad_tau_after", "mad_excl_semantic",
        ):
            self.assertIn(key, stats)
        # THE invariant, in the form that also covers a frame already past the cap:
        # the quota may leave zero_frac where it found it, but it may never push it
        # above the cap. (This synthetic frame has zero_frac_before ~= 0.65 -- the
        # geometric cue alone puts three quarters of the pixels at exactly d == 0 --
        # so the correct behaviour here is to exclude nothing.)
        self.assertLessEqual(
            stats["mad_zero_frac_after"],
            max(stats["mad_zero_frac_before"], 0.45) + 1e-9,
        )

    def test_off_reproduces_the_historic_weight(self):
        _, w_off, _, _ = self._call()
        _, w_default, _, _ = self._call(
            mad_exclusion=False, mad_excl_candidates="all", mad_excl_tau_floor=0.0
        )
        self.assertTrue(torch.equal(w_off, w_default))

    def test_tau_scale_is_declared_on_every_run(self):
        """T2-scale leaves no `mad_excl_*` fingerprint (it excludes nothing), so
        without a declaration column a scale row and a control row are
        indistinguishable on disk -- the exact failure the ego_* whitelist incident
        cost this project a campaign for."""
        _, _, _, off = self._call()
        _, _, _, on = self._call(tau_scale=0.45)
        self.assertEqual(off["tau_scale"], 1.0)
        self.assertEqual(on["tau_scale"], 0.45)
        self.assertEqual(on["mad_exclusion"], 0)
        self.assertNotIn("mad_excl_k", on)

    def test_tau_scale_default_leaves_the_wrapper_weight_untouched(self):
        _, w_off, _, _ = self._call()
        _, w_one, _, _ = self._call(tau_scale=1.0)
        self.assertTrue(torch.equal(w_off, w_one))


if __name__ == "__main__":
    unittest.main()
