"""CPU unit tests for the R2-P02 Fork B alpha exit+fill core (no GPU, no rasterizer).

Each test pins ONE mechanism's selection/geometry so a regression in the exit or
fill logic fails here before any GPU run. Run:
    /data/conda_envs/monogs-ours/bin/python -m unittest tests.test_alpha_lifecycle
"""

import unittest

import torch

from utils.alpha_lifecycle import (
    MODE_EXIT,
    MODE_EXIT_FILL,
    MODE_OBSERVE,
    MODE_OFF,
    AlphaLifecycleParams,
    alpha_lifecycle_active,
    alpha_lifecycle_mode,
    depth_inconsistency_evidence,
    detect_vacated_pixels,
    ema_alpha_update,
    plan_fill_points,
    project_gaussians_to_view,
    read_alpha_lifecycle_params,
    sample_map_at_gaussians,
    select_carve_mask,
    select_reset_mask,
    select_semantic_override_mask,
)

I4 = torch.eye(4, dtype=torch.float32)  # identity pose: camera frame == world frame


class ConfigReaderTests(unittest.TestCase):
    def test_absent_block_is_off_arm_b_parity(self):
        self.assertEqual(alpha_lifecycle_mode({}), MODE_OFF)
        self.assertFalse(alpha_lifecycle_active({}))
        p = read_alpha_lifecycle_params({})
        self.assertEqual(p.mode, MODE_OFF)
        self.assertFalse(p.updates_alpha or p.does_exit or p.does_fill)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            alpha_lifecycle_mode({"AlphaLifecycle": {"mode": "carve_everything"}})

    def test_arm_flags(self):
        observe = read_alpha_lifecycle_params({"AlphaLifecycle": {"mode": MODE_OBSERVE}})
        self.assertTrue(observe.updates_alpha)
        self.assertFalse(observe.does_exit or observe.does_fill)

        exit_ = read_alpha_lifecycle_params({"AlphaLifecycle": {"mode": MODE_EXIT}})
        self.assertTrue(exit_.updates_alpha and exit_.does_exit)
        self.assertFalse(exit_.does_fill)

        full = read_alpha_lifecycle_params({"AlphaLifecycle": {"mode": MODE_EXIT_FILL}})
        self.assertTrue(full.updates_alpha and full.does_exit and full.does_fill)

    def test_thresholds_are_read(self):
        p = read_alpha_lifecycle_params(
            {"AlphaLifecycle": {"mode": MODE_EXIT, "tau_carve": 0.05, "min_obs_count": 7}}
        )
        self.assertAlmostEqual(p.tau_carve, 0.05)
        self.assertAlmostEqual(p.min_obs_count, 7.0)
        self.assertIsInstance(AlphaLifecycleParams().fill_k, int)


class ProjectionTests(unittest.TestCase):
    def test_center_point_hits_principal_point(self):
        xyz = torch.tensor([[0.0, 0.0, 2.0]])
        u, v, z, valid = project_gaussians_to_view(xyz, I4, 500.0, 500.0, 320.0, 240.0, 480, 640)
        self.assertTrue(bool(valid[0]))
        self.assertAlmostEqual(float(u[0]), 320.0, places=4)
        self.assertAlmostEqual(float(v[0]), 240.0, places=4)
        self.assertAlmostEqual(float(z[0]), 2.0, places=4)

    def test_behind_and_offscreen_are_invalid(self):
        xyz = torch.tensor([[0.0, 0.0, -2.0], [100.0, 0.0, 1.0]])  # behind cam, far right
        _, _, _, valid = project_gaussians_to_view(xyz, I4, 500.0, 500.0, 320.0, 240.0, 480, 640)
        self.assertFalse(bool(valid[0]))
        self.assertFalse(bool(valid[1]))

    def test_sample_map_at_gaussians(self):
        field = torch.zeros(480, 640)
        field[240, 320] = 3.5
        u = torch.tensor([320.0])
        v = torch.tensor([240.0])
        got = sample_map_at_gaussians(field, u, v, torch.tensor([True]), 480, 640)
        self.assertAlmostEqual(float(got[0]), 3.5, places=5)


class EvidenceTests(unittest.TestCase):
    def test_within_band_is_static_far_is_dynamic(self):
        rendered = torch.tensor([[2.00, 2.00, 2.00]])
        observed = torch.tensor([[2.01, 3.50, 0.00]])  # in-band, far, invalid
        ev, valid = depth_inconsistency_evidence(rendered, observed, 0.05, 0.02)
        ev = ev.squeeze()
        self.assertLess(float(ev[0]), 0.05)   # inside band -> ~0
        self.assertGreater(float(ev[1]), 0.5)  # 1.5m off -> strong dynamic evidence
        self.assertEqual(float(ev[2]), 0.0)     # invalid obs -> 0 evidence
        self.assertFalse(bool(valid.squeeze()[2]))


class ExitSelectionTests(unittest.TestCase):
    def setUp(self):
        # 4 Gaussians, all validly projected, observed surface at 2.0m.
        self.valid = torch.tensor([True, True, True, True])
        self.obs = torch.tensor([2.0, 2.0, 2.0, 2.0])

    def test_reset_selects_low_alpha_occluders_only(self):
        z = torch.tensor([1.5, 1.5, 2.0, 1.5])         # #0,#1,#3 in front; #2 at surface
        alpha = torch.tensor([0.1, 0.9, 0.1, 0.1])     # #1 trusted; #2 at surface; #3 in front
        mask = select_reset_mask(z, self.obs, alpha, self.valid, tau_reset=0.35, delta_occlude_m=0.05)
        self.assertTrue(bool(mask[0]))    # low-alpha occluder -> reset
        self.assertFalse(bool(mask[1]))   # high-alpha (static protected) -> keep
        self.assertFalse(bool(mask[2]))   # at surface, not occluding -> keep
        self.assertTrue(bool(mask[3]))

    def test_carve_requires_persistence_and_deeper_gate(self):
        z = torch.tensor([1.8, 1.8, 1.8, 1.95])        # #0..2 float 0.2m ahead; #3 only 0.05m
        alpha = torch.tensor([0.1, 0.1, 0.9, 0.1])
        obs_count = torch.tensor([5.0, 1.0, 5.0, 5.0])  # #1 not persistent yet
        mask = select_carve_mask(
            z, self.obs, alpha, obs_count, self.valid,
            tau_carve=0.2, delta_free_m=0.10, min_obs_count=3.0,
        )
        self.assertTrue(bool(mask[0]))    # persistent, low-alpha, clearly in front -> carve
        self.assertFalse(bool(mask[1]))   # NOT persistent (obs_count 1 < 3) -> spared
        self.assertFalse(bool(mask[2]))   # high-alpha static -> spared
        self.assertFalse(bool(mask[3]))   # only 0.05m in front < delta_free -> spared

    def test_invalid_or_missing_obs_never_selected(self):
        z = torch.tensor([1.0])
        alpha = torch.tensor([0.0])
        obs_bad = torch.tensor([0.0])  # no observation
        valid = torch.tensor([True])
        self.assertFalse(bool(select_reset_mask(z, obs_bad, alpha, valid, 0.35, 0.05)[0]))
        self.assertFalse(
            bool(select_carve_mask(z, obs_bad, alpha, torch.tensor([9.0]), valid, 0.2, 0.10, 3.0)[0])
        )


class AlphaUpdateTests(unittest.TestCase):
    def test_static_evidence_raises_alpha_dynamic_lowers_it(self):
        alpha = torch.tensor([0.5, 0.5])
        obs = torch.tensor([0.0, 0.0])
        mask = torch.tensor([True, True])
        static_ev = torch.tensor([0.0, 0.0])   # fully static
        dyn_ev = torch.tensor([1.0, 1.0])       # fully dynamic
        a1, c1 = ema_alpha_update(alpha, obs, static_ev, mask, beta=0.9)
        a2, c2 = ema_alpha_update(alpha, obs, dyn_ev, mask, beta=0.9)
        self.assertTrue(bool((a1 > 0.5).all()))   # static -> up
        self.assertTrue(bool((a2 < 0.5).all()))   # dynamic -> down
        self.assertTrue(bool((c1 == 1.0).all()))  # counter bumped

    def test_persistent_dynamic_converges_toward_zero(self):
        alpha = torch.tensor([0.7])
        obs = torch.tensor([0.0])
        mask = torch.tensor([True])
        for _ in range(50):
            alpha, obs = ema_alpha_update(alpha, obs, torch.tensor([1.0]), mask, beta=0.9)
        self.assertLess(float(alpha[0]), 0.05)
        self.assertAlmostEqual(float(obs[0]), 50.0)

    def test_unmasked_gaussians_do_not_move(self):
        alpha = torch.tensor([0.5, 0.5])
        obs = torch.tensor([0.0, 0.0])
        mask = torch.tensor([True, False])
        a1, c1 = ema_alpha_update(alpha, obs, torch.tensor([0.0, 0.0]), mask, beta=0.9)
        self.assertGreater(float(a1[0]), 0.5)
        self.assertAlmostEqual(float(a1[1]), 0.5)   # untouched
        self.assertAlmostEqual(float(c1[1]), 0.0)


class FillTests(unittest.TestCase):
    def test_backprojection_roundtrips_and_colors_from_neighbors(self):
        # vacated pixel at principal point, observed background depth 3.0m.
        pixels = torch.tensor([[320.0, 240.0]])
        depth = torch.tensor([3.0])
        neighbor_xyz = torch.tensor([[0.0, 0.0, 3.0], [0.01, 0.0, 3.0]])
        neighbor_color = torch.tensor([[0.2, 0.4, 0.6], [0.4, 0.6, 0.8]])
        world, color = plan_fill_points(
            pixels, depth, I4, 500.0, 500.0, 320.0, 240.0,
            neighbor_xyz, neighbor_color, k=2, max_points=2000,
        )
        self.assertEqual(tuple(world.shape), (1, 3))
        # cam_to_world identity => world == camera point (0,0,3)
        self.assertAlmostEqual(float(world[0, 2]), 3.0, places=4)
        self.assertAlmostEqual(float(world[0, 0]), 0.0, places=4)
        # color = mean of the 2 neighbors
        self.assertAlmostEqual(float(color[0, 0]), 0.3, places=5)

        # and it round-trips back to the same pixel under projection
        u, v, _, valid = project_gaussians_to_view(world, I4, 500.0, 500.0, 320.0, 240.0, 480, 640)
        self.assertTrue(bool(valid[0]))
        self.assertAlmostEqual(float(u[0]), 320.0, places=3)
        self.assertAlmostEqual(float(v[0]), 240.0, places=3)

    def test_empty_inputs_return_empty(self):
        world, color = plan_fill_points(
            torch.zeros(0, 2), torch.zeros(0), I4, 500.0, 500.0, 320.0, 240.0,
            torch.zeros(0, 3), torch.zeros(0, 3), k=8,
        )
        self.assertEqual(tuple(world.shape), (0, 3))
        self.assertEqual(tuple(color.shape), (0, 3))

    def test_max_points_caps_output(self):
        n = 100
        pixels = torch.stack([torch.linspace(10, 600, n), torch.full((n,), 240.0)], dim=1)
        depth = torch.full((n,), 3.0)
        nbr = torch.tensor([[0.0, 0.0, 3.0]])
        world, color = plan_fill_points(
            pixels, depth, I4, 500.0, 500.0, 320.0, 240.0, nbr,
            torch.tensor([[0.5, 0.5, 0.5]]), k=1, max_points=10,
        )
        self.assertLessEqual(world.shape[0], 10)


class VacatedPixelTests(unittest.TestCase):
    def test_fill_only_where_exit_cleared_a_near_occluder(self):
        # observed background at 3.0m; near occluder rendered at 2.0m (pre-exit).
        pre_depth = torch.tensor([[2.0, 2.0, 2.0, 2.0]])
        pre_op = torch.tensor([[0.9, 0.9, 0.9, 0.4]])   # opaque x3, thin x1
        post_op = torch.tensor([[0.1, 0.9, 0.1, 0.1]])  # cleared, kept, cleared, cleared
        observed = torch.tensor([[3.0, 3.0, 2.0, 3.0]])  # far, far, in-band, far
        mask = detect_vacated_pixels(
            pre_depth, pre_op, post_op, observed, 0.10, 0.03, 0.5
        ).squeeze()
        self.assertTrue(bool(mask[0]))    # opaque occluder over far bg, exit cleared it -> fill
        self.assertFalse(bool(mask[1]))   # occluder still opaque post-exit -> no hole -> no fill
        self.assertFalse(bool(mask[2]))   # obs within band: real surface, not an occluder
        self.assertFalse(bool(mask[3]))   # pre-op thin (<0.5): never an opaque occluder

    def test_no_exit_no_fill(self):
        # coupling invariant: if exit clears nothing (post_op == pre_op), the
        # vacated mask is empty regardless of how much bg the map occludes.
        pre_depth = torch.tensor([[2.0, 2.0]])
        op = torch.tensor([[0.9, 0.9]])                  # opaque near occluders...
        observed = torch.tensor([[3.0, 3.0]])            # ...over far background...
        mask = detect_vacated_pixels(
            pre_depth, op, op, observed, 0.10, 0.03, 0.5
        ).squeeze()
        self.assertFalse(bool(mask.any()))               # ...but exit removed nothing -> 0 fill

    def test_diagnostics_attribute_an_empty_result(self):
        # A zero fill is ambiguous without per-conjunct counts: "the mechanism is
        # broken" and "exit opened no hole" are the same zero. That ambiguity let an
        # inert arm reach make-or-break in R2-P02-E2. now_cleared discriminates.
        pre_depth = torch.tensor([[2.0, 2.0]])
        observed = torch.tensor([[3.0, 3.0]])  # far background behind both

        # Case 1: exit cleared NOTHING -> now_cleared == 0. The post-exit render still
        # shows an opaque surface, i.e. accumulated alpha stayed above min_opacity.
        opaque = torch.tensor([[0.9, 0.9]])
        mask, dbg = detect_vacated_pixels(
            pre_depth, opaque, opaque, observed, 0.10, 0.03, 0.5,
            return_diagnostics=True,
        )
        self.assertFalse(bool(mask.any()))
        self.assertEqual(dbg["n_now_cleared"], 0)
        self.assertEqual(dbg["n_pre_occluded"], 2)   # the occluders were there...
        self.assertEqual(dbg["n_vacated"], 0)        # ...exit just never removed them

        # Case 2: exit DID clear both pixels, but nothing was being occluded (observed
        # sits at the rendered depth) -> cleared > 0 while vacated == 0. Correctly
        # nothing to fill, and now distinguishable from case 1.
        cleared = torch.tensor([[0.1, 0.1]])
        at_surface = torch.tensor([[2.0, 2.0]])
        mask2, dbg2 = detect_vacated_pixels(
            pre_depth, opaque, cleared, at_surface, 0.10, 0.03, 0.5,
            return_diagnostics=True,
        )
        self.assertFalse(bool(mask2.any()))
        self.assertEqual(dbg2["n_now_cleared"], 2)   # exit DID open coverage...
        self.assertEqual(dbg2["n_pre_occluded"], 0)  # ...but nothing hid behind it
        self.assertEqual(dbg2["n_vacated"], 0)

    def test_diagnostics_do_not_change_the_mask(self):
        # The flag is observability only: same inputs -> same mask either way.
        pre_depth = torch.tensor([[2.0, 2.0, 2.0, 2.0]])
        pre_op = torch.tensor([[0.9, 0.9, 0.9, 0.4]])
        post_op = torch.tensor([[0.1, 0.9, 0.1, 0.1]])
        observed = torch.tensor([[3.0, 3.0, 2.0, 3.0]])
        plain = detect_vacated_pixels(pre_depth, pre_op, post_op, observed)
        withdbg, dbg = detect_vacated_pixels(
            pre_depth, pre_op, post_op, observed, return_diagnostics=True
        )
        self.assertTrue(bool(torch.equal(plain, withdbg)))
        self.assertEqual(dbg["n_vacated"], int(plain.sum()))
        self.assertEqual(dbg["n_px"], plain.numel())


class SemanticOverrideTests(unittest.TestCase):
    """T3: semantic alpha override with a STRICT geometry gate.

    Four Gaussians against an observed surface at 3.0 m, delta_m = 0.10:
      0  floater at 2.0 m, semantics says person  -> override (the target case)
      1  at the surface (3.0 m), semantics says person -> PROTECTED (a person
         standing still IS the observed surface; killing them deletes real geometry)
      2  floater at 2.0 m, semantics silent -> untouched (this is the EMA's job)
      3  behind the surface at 4.0 m, semantics says person -> untouched
    """

    def setUp(self):
        self.z = torch.tensor([2.0, 3.0, 2.0, 4.0])
        self.obs = torch.tensor([3.0, 3.0, 3.0, 3.0])
        self.sem = torch.tensor([True, True, False, True])
        self.valid = torch.tensor([True, True, True, True])

    def test_geometry_gate_protects_a_stationary_person(self):
        m = select_semantic_override_mask(self.z, self.obs, self.sem, self.valid, 0.10)
        self.assertEqual(m.tolist(), [True, False, False, False])

    def test_semantics_is_required_not_just_geometry(self):
        none_hit = torch.zeros(4, dtype=torch.bool)
        m = select_semantic_override_mask(self.z, self.obs, none_hit, self.valid, 0.10)
        self.assertFalse(bool(m.any()))

    def test_invalid_or_missing_observation_never_overridden(self):
        obs = torch.tensor([0.0, 3.0, 3.0, float("nan")])
        sem = torch.ones(4, dtype=torch.bool)
        z = torch.tensor([1.0, 1.0, 1.0, 1.0])
        m = select_semantic_override_mask(z, obs, sem, self.valid, 0.10)
        self.assertEqual(m.tolist(), [False, True, True, False])

    def test_gate_is_stricter_than_the_reset_gate(self):
        """delta_m (0.10) > delta_occlude_m (0.05), so the override set is a SUBSET of
        the geometry the reset pass already treats as occluding. A Gaussian 0.07 m in
        front is close enough for reset but not for the override."""
        z = torch.tensor([2.93, 2.93, 2.93, 2.93])
        sem = torch.ones(4, dtype=torch.bool)
        alpha = torch.zeros(4)
        override = select_semantic_override_mask(z, self.obs, sem, self.valid, 0.10)
        reset = select_reset_mask(z, self.obs, alpha, self.valid, 0.35, 0.05)
        self.assertFalse(bool(override.any()))
        self.assertTrue(bool(reset.all()))

    def test_override_is_self_limiting_at_the_documented_rate(self):
        """A false positive is recoverable, not permanent: alpha climbs back as
        1 - beta^k under static evidence. Pins the table the plan quotes -- above
        tau_carve (0.20) after 3 keyframes, above tau_reset (0.35) after 5."""
        alpha = torch.zeros(1)
        obs_count = torch.zeros(1)
        static = torch.zeros(1)  # evidence 0 == "looks static"
        m = torch.ones(1, dtype=torch.bool)
        seen = []
        for _ in range(5):
            alpha, obs_count = ema_alpha_update(alpha, obs_count, static, m, 0.9)
            seen.append(round(float(alpha[0]), 4))
        self.assertEqual(seen, [0.1, 0.19, 0.271, 0.3439, 0.4095])
        self.assertGreater(seen[2], 0.20)  # past tau_carve
        self.assertGreater(seen[4], 0.35)  # past tau_reset

    def test_params_default_to_off_and_reuse_delta_free(self):
        p = read_alpha_lifecycle_params({"AlphaLifecycle": {"mode": "exit"}})
        self.assertIsNone(p.semantic_alpha_override)
        self.assertFalse(p.does_semantic_override)
        self.assertEqual(p.semantic_override_delta_m, p.delta_free_m)

    def test_params_read_the_override_and_inherit_a_custom_delta_free(self):
        p = read_alpha_lifecycle_params({
            "AlphaLifecycle": {
                "mode": "exit", "semantic_alpha_override": 0.0, "delta_free_m": 0.25,
            }
        })
        self.assertEqual(p.semantic_alpha_override, 0.0)
        self.assertTrue(p.does_semantic_override)
        self.assertEqual(p.semantic_override_delta_m, 0.25)

    def test_override_never_fires_outside_an_exit_arm(self):
        """In `observe` (the placebo arm) nothing acts on alpha, so writing to it there
        would be a silent confound rather than an ablation."""
        for mode in ("observe", "off"):
            p = read_alpha_lifecycle_params({
                "AlphaLifecycle": {"mode": mode, "semantic_alpha_override": 0.0}
            })
            self.assertFalse(p.does_semantic_override, mode)

    def test_bool_mask_samples_to_gaussians(self):
        """The backend feeds a semantic BOOL map straight into sample_map_at_gaussians;
        pin that it survives the float cast and thresholds back cleanly."""
        mask = torch.zeros(4, 4, dtype=torch.bool)
        mask[1, 2] = True
        hit = sample_map_at_gaussians(
            mask.to(torch.float32),
            torch.tensor([2.0, 0.0]), torch.tensor([1.0, 0.0]),
            torch.ones(2, dtype=torch.bool), 4, 4,
        ) > 0.5
        self.assertEqual(hit.tolist(), [True, False])


class OverrideAuditTrailTests(unittest.TestCase):
    """The misfire guardrail (<= 5% of overridden Gaussians landing in GT-static) can
    only be computed from the pixel each override landed on, recorded AT override time:
    an overridden Gaussian can be pruned later, so the final map cannot answer it. These
    pin the writer, because a guardrail that silently writes nothing reads exactly like
    a guardrail that passed."""

    def _writer(self, save_dir):
        from utils.slam_backend import BackEnd
        stub = BackEnd.__new__(BackEnd)
        stub.config = {"Results": {"save_dir": save_dir}}
        return stub

    def _view(self, uid=7):
        class V:
            pass
        v = V()
        v.uid = uid
        return v

    def test_one_row_per_overridden_gaussian_with_header_once(self):
        import csv as _csv
        import os as _os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            w = self._writer(tmp)
            mask = torch.tensor([True, False, True, False])
            u = torch.tensor([1.0, 2.0, 3.0, 4.0])
            v = torch.tensor([5.0, 6.0, 7.0, 8.0])
            z = torch.tensor([0.5, 0.6, 0.7, 0.8])
            obs = torch.tensor([1.5, 1.6, 1.7, 1.8])
            w._log_semantic_overrides(self._view(7), mask, u, v, z, obs)
            w._log_semantic_overrides(self._view(9), mask, u, v, z, obs)
            path = _os.path.join(tmp, "alpha_semantic", "overrides.csv")
            with open(path, newline="") as fh:
                rows = list(_csv.DictReader(fh))
            self.assertEqual(len(rows), 4)                       # 2 per call, header once
            self.assertEqual([r["kf_uid"] for r in rows], ["7", "7", "9", "9"])
            self.assertEqual([r["gauss_idx"] for r in rows], ["0", "2", "0", "2"])
            self.assertEqual(rows[0]["u"], "1.00")
            self.assertEqual(rows[1]["v"], "7.00")

    def test_a_broken_write_cannot_kill_the_run(self):
        """A diagnostic must never take mapping down with it."""
        w = self._writer("/proc/this/cannot/exist")
        w._log_semantic_overrides(
            self._view(), torch.tensor([True]), torch.tensor([1.0]),
            torch.tensor([1.0]), torch.tensor([1.0]), torch.tensor([1.0]),
        )

    def test_no_save_dir_writes_nothing(self):
        from utils.slam_backend import BackEnd
        stub = BackEnd.__new__(BackEnd)
        stub.config = {"Results": {}}
        stub._log_semantic_overrides(
            self._view(), torch.tensor([True]), torch.tensor([1.0]),
            torch.tensor([1.0]), torch.tensor([1.0]), torch.tensor([1.0]),
        )


if __name__ == "__main__":
    unittest.main()
