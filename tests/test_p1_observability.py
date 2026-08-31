"""P1 offline observability probe (``scripts/p1_observability_offline.py``).

Four things can silently corrupt the P1 verdict, so each gets a test:

1. the ``H_kept = H_all - H_removed`` shortcut (the whole run is built on it);
2. the shift null must preserve mask AREA and SHAPE exactly and stay in frame --
   otherwise "same-size blob elsewhere" is not what is being compared;
3. ``spectrum`` must report a singular information matrix as such, not as a tiny
   positive number (an unobservable DoF must not be silently rounded into an
   observable one);
4. a POSITIVE CONTROL: on a synthetic frame whose texture sits entirely inside the
   mask, the pipeline must actually SEE the collapse. Without this a FAIL verdict
   would be unreadable -- "no effect" and "cannot detect any effect" look identical
   (exp32 criterion #3: confirm the deadline is measurable before writing it in).
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.util  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "p1_observability_offline",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "scripts", "p1_observability_offline.py"),
)
p1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(p1)

torch = __import__("torch")

CALIB = dict(fx=500.0, fy=500.0, cx=64.0, cy=48.0, depth_scale=5000.0,
             width=128, height=96)


def _synthetic(h=96, w=128, textured=None, depth_val=2.0, seed=0):
    """Frame with depth ``depth_val`` everywhere and texture only where ``textured``."""
    rng = np.random.default_rng(seed)
    depth = np.full((h, w), depth_val, dtype=np.float32)
    rgb = np.full((h, w, 3), 128, dtype=np.uint8)
    if textured is None:
        textured = np.ones((h, w), dtype=bool)
    noise = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint16).astype(np.uint8)
    rgb[textured] = noise[textured]
    return depth, rgb


class TestHessianDecomposition(unittest.TestCase):
    def test_kept_equals_all_minus_removed(self):
        depth, rgb = _synthetic()
        J, G, jd, valid = p1.per_pixel_terms(depth, rgb, CALIB, "cpu")
        rm = torch.zeros_like(valid)
        rm[20:50, 30:70] = True
        rm = rm & valid
        H_all = p1.hessian_of(J, G, jd, valid)
        H_rm = p1.hessian_of(J, G, jd, rm)
        H_kept_direct = p1.hessian_of(J, G, jd, valid & ~rm)
        self.assertTrue(
            torch.allclose(H_all - H_rm, H_kept_direct, rtol=1e-9, atol=1e-9),
            msg=f"max dev {(H_all - H_rm - H_kept_direct).abs().max():.3e}",
        )

    def test_hessian_is_symmetric_psd(self):
        depth, rgb = _synthetic()
        J, G, jd, valid = p1.per_pixel_terms(depth, rgb, CALIB, "cpu")
        H = p1.hessian_of(J, G, jd, valid)
        self.assertTrue(torch.allclose(H, H.transpose(0, 1), atol=1e-9))
        ev = torch.linalg.eigvalsh(H)
        self.assertGreaterEqual(float(ev[0]), -1e-9)

    def test_empty_selection_is_zero(self):
        depth, rgb = _synthetic()
        J, G, jd, valid = p1.per_pixel_terms(depth, rgb, CALIB, "cpu")
        H = p1.hessian_of(J, G, jd, torch.zeros_like(valid))
        self.assertEqual(float(H.abs().max()), 0.0)


class TestShiftNull(unittest.TestCase):
    def _mask(self, h=96, w=128):
        m = np.zeros((h, w), dtype=bool)
        m[30:50, 40:70] = True
        m[35:38, 20:40] = True          # non-rectangular, to catch shape damage
        return m

    def test_area_and_shape_preserved_and_in_frame(self):
        m = self._mask()
        valid = np.ones_like(m)
        rng = np.random.default_rng(0)
        draws = p1.shifted_masks(m, valid, rng, 16, int(m.sum()))
        self.assertGreaterEqual(len(draws), 8)
        ref = np.sort(np.flatnonzero(m.ravel()))
        for mm, cnt, _ov in draws:
            self.assertEqual(int(mm.sum()), int(m.sum()))       # exact area
            self.assertEqual(cnt, int(m.sum()))
            ys, xs = np.nonzero(mm)
            self.assertTrue(ys.min() >= 0 and ys.max() < m.shape[0])
            self.assertTrue(xs.min() >= 0 and xs.max() < m.shape[1])
            # shape identical up to a pure translation
            ys0, xs0 = np.nonzero(m)
            dy, dx = ys.min() - ys0.min(), xs.min() - xs0.min()
            rolled = np.zeros_like(m)
            rolled[ys0 + dy, xs0 + dx] = True
            self.assertTrue(np.array_equal(rolled, mm))
            self.assertFalse(dy == 0 and dx == 0)
        self.assertEqual(ref.size, int(m.sum()))

    def test_count_matching_rejects_invalid_landings(self):
        m = self._mask()
        valid = np.zeros_like(m)
        valid[:, :64] = True            # right half invalid -> most shifts undercount
        rng = np.random.default_rng(1)
        target = int((m & valid).sum())
        draws = p1.shifted_masks(m, valid, rng, 16, target)
        for _mm, cnt, _ov in draws:
            self.assertLessEqual(abs(cnt - target), p1.COUNT_TOL * target)

    def test_full_frame_mask_is_infeasible(self):
        m = np.ones((96, 128), dtype=bool)
        draws = p1.shifted_masks(m, m, np.random.default_rng(0), 16, int(m.sum()))
        self.assertEqual(len(draws), 0)   # no non-zero shift keeps the bbox in frame


class TestSpectrum(unittest.TestCase):
    def test_singular_reports_nonpositive_lambda_min(self):
        H = torch.diag(torch.tensor([1.0, 1.0, 1.0, 1.0, 1.0, 0.0], dtype=torch.float64))
        lam, ld = p1.spectrum(H)
        self.assertLessEqual(lam, 1e-12)
        self.assertTrue(np.isnan(ld))

    def test_known_spectrum(self):
        d = torch.tensor([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], dtype=torch.float64)
        lam, ld = p1.spectrum(torch.diag(d))
        self.assertAlmostEqual(lam, 1.0, places=9)
        self.assertAlmostEqual(ld, float(torch.log(d).sum()), places=9)


class TestPositiveControl(unittest.TestCase):
    """Plant the effect the study is looking for; the pipeline must see it."""

    def test_texture_only_inside_mask_collapses_lambda_min(self):
        h, w = 96, 128
        blob = np.zeros((h, w), dtype=bool)
        blob[30:60, 40:90] = True
        depth, rgb = _synthetic(h, w, textured=blob)     # ALL texture inside the blob
        J, G, jd, valid = p1.per_pixel_terms(depth, rgb, CALIB, "cpu")
        H_all = p1.hessian_of(J, G, jd, valid)
        sel_gt = torch.as_tensor(blob) & valid
        lam_gt, _ = p1.spectrum(H_all - p1.hessian_of(J, G, jd, sel_gt))

        rng = np.random.default_rng(0)
        draws = p1.shifted_masks(blob, valid.numpy(), rng, 16, int(sel_gt.sum()))
        self.assertGreaterEqual(len(draws), 8)
        lam_null = []
        for mm, _c, _o in draws:
            s = torch.as_tensor(mm) & valid
            lam_null.append(p1.spectrum(H_all - p1.hessian_of(J, G, jd, s))[0])
        rho = lam_gt / float(np.median(lam_null))
        self.assertLess(rho, 0.67, msg=f"planted effect not detected: rho={rho:.3f}")
        self.assertLess(lam_gt, float(np.quantile(lam_null, 0.05)))

    def test_uniform_texture_gives_rho_near_one(self):
        """Negative control: no planted effect -> the true mask is unremarkable."""
        h, w = 96, 128
        depth, rgb = _synthetic(h, w, textured=None, seed=3)   # texture everywhere
        blob = np.zeros((h, w), dtype=bool)
        blob[30:60, 40:90] = True
        J, G, jd, valid = p1.per_pixel_terms(depth, rgb, CALIB, "cpu")
        H_all = p1.hessian_of(J, G, jd, valid)
        sel_gt = torch.as_tensor(blob) & valid
        lam_gt, _ = p1.spectrum(H_all - p1.hessian_of(J, G, jd, sel_gt))
        rng = np.random.default_rng(0)
        draws = p1.shifted_masks(blob, valid.numpy(), rng, 16, int(sel_gt.sum()))
        lam_null = [
            p1.spectrum(H_all - p1.hessian_of(J, G, jd, torch.as_tensor(mm) & valid))[0]
            for mm, _c, _o in draws
        ]
        rho = lam_gt / float(np.median(lam_null))
        self.assertGreater(rho, 0.80, msg=f"spurious effect on flat data: rho={rho:.3f}")
        self.assertLess(rho, 1.25)


if __name__ == "__main__":
    unittest.main()
