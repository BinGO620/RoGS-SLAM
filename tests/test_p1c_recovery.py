"""P1c perturbation-recovery apparatus (``scripts/p1c_recovery_*.py``).

Criterion (11): the positive and the negative control travel with the judgement, in the
test suite, or else "did not see the dynamic object" and "cannot see any dynamic object"
are indistinguishable -- which is exactly how P1b produced an unreadable table.

1. ``se3_exp``/``se3_log``/``pose_err`` roundtrip -- the endpoint is a pose difference,
   so a convention slip here silently rescales every number in the study;
2. NEGATIVE control: a block that moves WITH the scene must not make ``oracle`` beat
   ``all`` (removing pixels is not free but must not look like a win);
3. POSITIVE control: a block with a known coherent displacement must make ``oracle``
   recover where ``all`` does not;
4. the verdict rule's branches, including the one that matters most -- "the gates pass
   but there is no signal", which is a publishable NEGATIVE, not a NO VERDICT.
"""

import importlib.util
import os
import sys
import unittest

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _load(mod):
    spec = importlib.util.spec_from_file_location(
        mod, os.path.join(_ROOT, "scripts", f"{mod}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


p1c = _load("p1c_recovery_synthetic")
real = _load("p1c_recovery_real")
torch = __import__("torch")

K = (250.0, 250.0, 64.0, 48.0)
H, W = 96, 128


def _scene(device="cpu", seed=0):
    """A textured image + smooth depth: enough gradient for photometric GN to bite."""
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float64)
    img = np.zeros((H, W, 3))
    for c in range(3):
        for _ in range(6):
            fx_, fy_ = rng.uniform(0.05, 0.35, size=2)
            ph = rng.uniform(0, 2 * np.pi)
            img[..., c] += np.sin(fx_ * xs + fy_ * ys + ph)
    img = (img - img.min()) / (img.max() - img.min())
    depth = 2.0 + 0.3 * (xs / W) + 0.2 * (ys / H)
    Ip = torch.as_tensor(img, dtype=torch.float32, device=device).permute(2, 0, 1)
    D = torch.as_tensor(depth, dtype=torch.float32, device=device)
    T_star = p1c.se3_exp(np.array([0.01, -0.005, 0.008, 0.002, 0.001, -0.0015]))
    return Ip, D, T_star


def _run_arms(block, disp, device="cpu", eps_t=0.010, eps_r=0.002):
    Ip, D, T_star = _scene(device)
    It, _ = p1c.render_It(Ip, D, K, T_star, device, block=block, disp=disp)
    eps = np.concatenate([np.array([1.0, 0, 0]) * eps_t, np.array([0, 1.0, 0]) * eps_r])
    T_init = p1c.se3_exp(eps) @ T_star
    out = {}
    for arm, blk in (("all", None), ("oracle", block)):
        res = p1c.recover(Ip, It, D, K, T_init, T_star, device, arm, blk, steps=8)
        out[arm] = None if res is None else res[0] / (1000.0 * eps_t)
    return out


class TestSE3(unittest.TestCase):
    def test_exp_log_roundtrip(self):
        rng = np.random.default_rng(0)
        for _ in range(20):
            xi = np.concatenate([rng.normal(size=3) * 0.05, rng.normal(size=3) * 0.02])
            np.testing.assert_allclose(p1c.se3_log(p1c.se3_exp(xi)), xi, atol=1e-10)

    def test_pose_err_units(self):
        T = p1c.se3_exp(np.array([0.005, 0.0, 0.0, 0.0, 0.0, 0.002]))
        dt, dr = p1c.pose_err(T, np.eye(4))
        self.assertAlmostEqual(dt, 5.0, places=6)     # mm
        self.assertAlmostEqual(dr, 2.0, places=6)     # mrad

    def test_identity_is_zero_error(self):
        _Ip, _D, T_star = _scene()
        dt, dr = p1c.pose_err(T_star, T_star)
        self.assertLess(dt, 1e-9)
        self.assertLess(dr, 1e-9)


class TestApparatusControls(unittest.TestCase):
    """MIN_VALID is a real-image guard; this scene is 96x128, so relax it here only."""

    def setUp(self):
        self._mv = p1c.MIN_VALID
        p1c.MIN_VALID = 500

    def tearDown(self):
        p1c.MIN_VALID = self._mv

    def test_clean_pair_recovers(self):
        """No block at all: 8 GN steps must undo the injected perturbation."""
        out = _run_arms(np.zeros((H, W), dtype=bool), (0.0, 0.0))
        self.assertLess(out["all"], 0.05, f"clean recovery floor too high: {out}")

    def test_negative_control_block_moves_with_scene(self):
        """disp = 0: the block is not dynamic, so removing it must not look like a win."""
        block = np.zeros((H, W), dtype=bool)
        block[20:70, 30:80] = True
        out = _run_arms(block, (0.0, 0.0))
        self.assertLess(out["all"], 0.05)
        self.assertLess(abs(out["all"] - out["oracle"]), 0.05, f"negative control: {out}")

    def test_positive_control_coherent_displacement(self):
        """A known moving block must break `all` and leave `oracle` intact."""
        block = np.zeros((H, W), dtype=bool)
        block[20:70, 30:80] = True
        out = _run_arms(block, (6.0, 0.0))
        self.assertLess(out["oracle"], 0.10, f"oracle must still recover: {out}")
        self.assertGreater(out["all"], out["oracle"] + 0.10,
                           f"apparatus cannot see a known moving block: {out}")

    def test_block_area_fraction_is_honoured(self):
        rng = np.random.default_rng(3)
        for frac in (0.05, 0.20):
            m = p1c.make_block(480, 640, frac, rng)
            self.assertAlmostEqual(m.mean(), frac, delta=0.25 * frac)


class TestExclusionAndExposure(unittest.TestCase):
    def test_depth_edge_and_invalid_are_excluded(self):
        D = torch.full((H, W), 2.0)
        D[:, 64:] = 2.5                     # a 0.5 m step -> discontinuity
        D[10:14, 10:14] = 0.0               # invalid patch
        drop = real._exclusion(D, "cpu").numpy()
        self.assertTrue(drop[:, 63:66].all(), "depth step not excluded")
        self.assertTrue(drop[10:14, 10:14].all(), "invalid depth not excluded")
        self.assertFalse(drop[40:60, 20:40].any(), "flat valid region wrongly excluded")

    def test_affine_exposure_recovers_a_known_gain(self):
        Ip, _D, _T = _scene()
        valid = torch.ones((H, W), dtype=torch.bool)
        a, b = real._affine_exposure(Ip, 1.3 * Ip + 0.05, valid)
        self.assertAlmostEqual(a, 1.3, delta=0.08)
        self.assertAlmostEqual(b, 0.05, delta=0.05)

    def test_affine_exposure_is_identity_on_identical_frames(self):
        Ip, _D, _T = _scene()
        valid = torch.ones((H, W), dtype=torch.bool)
        a, b = real._affine_exposure(Ip, Ip, valid)
        self.assertAlmostEqual(a, 1.0, delta=1e-6)
        self.assertAlmostEqual(b, 0.0, delta=1e-6)


def _write(tmp, name, med, frac_informative=1.0, res=0.05):
    """One CSV of 20 frames with the given per-arm medians and informative fraction."""
    import csv as _csv
    fields = ["frame", "stem", "n_valid", "n_removed", "area_frac", "resolution_mm",
              "oracle_mm", "oracle_mrad", "oracle_x", "oracle_y", "oracle_z",
              "res_all_mm", "res_robust_mm", "res_oracle_mm", "res_mrcs_mm",
              "res_shift_mm",
              "robust_mm", "robust_pi", "mrcs_mm", "mrcs_pi",
              "shift_mm", "shift_max_mm", "shift_pi"]
    n = 20
    with open(os.path.join(tmp, f"{name}.csv"), "w", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for i in range(n):
            informative = i < int(round(frac_informative * n))
            row = {k: 0.0 for k in fields}
            row["stem"] = f"{i:04d}"
            row["frame"], row["n_valid"], row["n_removed"] = i, 200000, 6000
            row["area_frac"] = 0.03
            row["resolution_mm"] = res
            for a in ("all", "robust", "oracle", "mrcs", "shift"):
                row[f"res_{a}_mm"] = res
            # informative <=> oracle_mm clears both the resolution and the shift null
            row["oracle_mm"] = med["oracle_mm"] if informative else 0.5 * med["shift_max_mm"]
            row["oracle_x"] = row["oracle_mm"]
            row["shift_mm"] = med["shift_max_mm"]
            row["shift_max_mm"] = med["shift_max_mm"]
            row["robust_mm"] = med.get("robust_mm", 1.0)
            row["mrcs_mm"] = med.get("mrcs_mm", 1.0)
            for a in ("robust", "mrcs", "shift"):
                row[f"{a}_pi"] = med.get(f"{a}_pi", 0.0)
            w.writerow(row)


DYN_OK = {"oracle_mm": 4.0, "shift_max_mm": 0.5, "robust_mm": 3.0, "mrcs_mm": 3.0,
          "robust_pi": 0.3, "mrcs_pi": 0.8, "shift_pi": 0.02}


class TestVerdictRule(unittest.TestCase):
    def _verdict(self, dyn, ctl=None, dyn_inf=1.0, ctl_inf=0.0, res=0.05):
        import tempfile
        tmp = tempfile.mkdtemp()
        for s in real.DYN_SEQUENCES:
            _write(tmp, s, dyn, frac_informative=dyn_inf, res=res)
        _write(tmp, real.STATIC_CONTROL, ctl or dyn, frac_informative=ctl_inf, res=res)
        return real.verdict(tmp)

    def test_no_signal_is_a_negative_not_a_no_verdict(self):
        """The oracle never clears the shift null -> NEGATIVE, a publishable result."""
        v = self._verdict(DYN_OK, dyn_inf=0.05)
        self.assertTrue(v["verdict"].startswith("NEGATIVE"), v)

    def test_gate_fires_when_resolution_cannot_resolve_the_effect(self):
        """Two starts of the SAME arm disagree as much as the arms do -> NO VERDICT."""
        v = self._verdict(DYN_OK, res=3.0)
        self.assertTrue(v["verdict"].startswith("NO VERDICT"), v)
        self.assertIn("G1", v["why"])

    def test_negative_control_blocks_the_verdict(self):
        v = self._verdict(DYN_OK, ctl_inf=1.0)
        self.assertTrue(v["verdict"].startswith("NO VERDICT"), v)
        self.assertIn("G2", v["why"])

    def test_pass_and_fail_turn_on_pi_not_on_magnitude(self):
        """Same |move| as the oracle, but orthogonal to it, must FAIL."""
        self.assertEqual(self._verdict(DYN_OK)["verdict"], "PASS")
        orthogonal = dict(DYN_OK, mrcs_pi=0.0, mrcs_mm=4.0)
        self.assertEqual(self._verdict(orthogonal)["verdict"], "FAIL")

    def test_opposite_move_is_a_fail_not_a_pass(self):
        """P1b flag (2): a policy moving the pose the OTHER way must not score as helping."""
        v = self._verdict(dict(DYN_OK, mrcs_pi=-0.9))
        self.assertEqual(v["verdict"], "FAIL")

    def test_pass_requires_mrcs_move_to_be_reproducible(self):
        """Same pi, but mrcs's own two starts disagree as much as its move -> NO VERDICT."""
        v = self._verdict(dict(DYN_OK, mrcs_mm=0.1))
        self.assertTrue(v["verdict"].startswith("NO VERDICT"), v)
        self.assertIn("reproducible", v["why"])

    def test_frames_with_no_null_are_excluded_not_counted_as_no_signal(self):
        """A frame whose shift draws all failed has no null -- it cannot vote either way."""
        import tempfile
        tmp = tempfile.mkdtemp()
        for s in real.DYN_SEQUENCES + [real.STATIC_CONTROL]:
            _write(tmp, s, DYN_OK, frac_informative=1.0)
        # half the frames of one sequence lose their null entirely
        path = os.path.join(tmp, real.DYN_SEQUENCES[0] + ".csv")
        import csv as _csv
        rows = list(_csv.DictReader(open(path)))
        for r in rows[:10]:
            r["shift_max_mm"] = "nan"
        with open(path, "w", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        agg = real._agg(path)
        self.assertEqual(agg["n_unusable"], 10)
        self.assertEqual(agg["frac_informative"], 1.0)          # over usable frames
        self.assertAlmostEqual(agg["frac_informative_all_frames"], 0.5)


class TestProjectionEstimand(unittest.TestCase):
    def test_pi_is_1_for_the_oracle_itself(self):
        u = np.array([1.0, -2.0, 0.5])
        self.assertAlmostEqual(real._pi(u, u), 1.0)

    def test_pi_is_0_for_an_orthogonal_move(self):
        self.assertAlmostEqual(real._pi(np.array([0.0, 1.0, 0.0]),
                                        np.array([1.0, 0.0, 0.0])), 0.0)

    def test_pi_is_negative_for_an_opposite_move(self):
        u = np.array([1.0, 0.0, 0.0])
        self.assertAlmostEqual(real._pi(-0.5 * u, u), -0.5)

    def test_u_is_a_pose_difference_in_mm(self):
        T = p1c.se3_exp(np.array([0.004, 0.0, 0.0, 0.0, 0.0, 0.003]))
        ut, ur = real._u(T, np.eye(4))
        self.assertAlmostEqual(float(np.linalg.norm(ut)), 4.0, places=6)
        self.assertAlmostEqual(float(np.linalg.norm(ur)), 3.0, places=6)


if __name__ == "__main__":
    unittest.main()
