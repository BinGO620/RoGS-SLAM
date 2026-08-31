"""CPU unit tests for the M2 anchor probe (task-B gate instrumentation).

The probe answers one question per frame: is the set of pixels that still CONSTRAIN
the pose thinning out, and are the survivors still the good ones? Design B would fire
a keyframe on that signal, so before spending 48 runs on M3 the probe has to be
demonstrably (a) inert when off and (b) measuring what it claims when on.

`_anchor_stats` is an instance method that touches only `self.config` and three
`anchor_*` attributes, so it is bound to a stub here rather than standing up a real
FrontEnd (which needs CUDA, a dataset and two processes).

Run:
    /data/conda_envs/monogs-ours/bin/python -m unittest tests.test_anchor_probe
"""

import types
import unittest

import torch

from utils.slam_frontend import (
    FrontEnd,
    reliability_frames_fields,
)

H = W = 16


def _probe(require_grad_mask=False, thresholds=(0.80, 0.90, 0.95)):
    stub = types.SimpleNamespace(
        config={"Training": {"rgb_boundary_threshold": 0.001}},
        anchor_thresholds=thresholds,
        anchor_require_grad_mask=require_grad_mask,
        _anchor_last=None,
    )
    stub._anchor_stats = FrontEnd._anchor_stats.__get__(stub, types.SimpleNamespace)
    return stub


def _view(grad_mask=None, brightness=0.5):
    return types.SimpleNamespace(
        uid=7,
        original_image=torch.full((3, H, W), brightness),
        grad_mask=grad_mask,
    )


def _inputs(s_hw, render_image=None, render_depth=None, obs_depth=None):
    return dict(
        s_map=s_hw,
        render_image=torch.full((3, H, W), 0.5) if render_image is None else render_image,
        render_depth=torch.full((H, W), 2.0) if render_depth is None else render_depth,
        obs_depth=torch.full((H, W), 2.0) if obs_depth is None else obs_depth,
    )


class AnchorProbeGeometry(unittest.TestCase):
    def test_half_reliable_frame_gives_half_survival(self):
        s = torch.zeros(H, W)
        s[: H // 2] = 1.0
        out = _probe()._anchor_stats(_view(), **_inputs(s))
        self.assertAlmostEqual(out["anchor_frac_s90"], 0.5, places=6)
        self.assertEqual(out["anchor_n_s90"], H * W // 2)
        self.assertEqual(out["anchor_support_frac"], 1.0)

    def test_thresholds_are_nested(self):
        s = torch.linspace(0.0, 1.0, H * W).reshape(H, W)
        out = _probe()._anchor_stats(_view(), **_inputs(s))
        self.assertGreaterEqual(out["anchor_frac_s80"], out["anchor_frac_s90"])
        self.assertGreaterEqual(out["anchor_frac_s90"], out["anchor_frac_s95"])

    def test_support_excludes_black_pixels(self):
        """The probe measures inside the photometric support the tracker actually
        optimises; a black region contributes no constraint and must not dilute the
        denominator."""
        v = _view()
        v.original_image[:, :, : W // 2] = 0.0
        out = _probe()._anchor_stats(v, **_inputs(torch.ones(H, W)))
        self.assertAlmostEqual(out["anchor_support_frac"], 0.5, places=6)
        self.assertEqual(out["anchor_support_n"], H * W // 2)

    def test_grad_mask_narrows_the_support_when_requested(self):
        gm = torch.zeros(1, H, W, dtype=torch.bool)
        gm[0, :, : W // 4] = True
        out = _probe(require_grad_mask=True)._anchor_stats(
            _view(grad_mask=gm), **_inputs(torch.ones(H, W))
        )
        self.assertAlmostEqual(out["anchor_support_frac"], 0.25, places=6)

    def test_missing_grad_mask_falls_back_to_rgb_support(self):
        out = _probe(require_grad_mask=True)._anchor_stats(
            _view(grad_mask=None), **_inputs(torch.ones(H, W))
        )
        self.assertEqual(out["anchor_support_frac"], 1.0)


class AnchorRatioSemantics(unittest.TestCase):
    """`anchor_ratio` is the judgement variable, not `anchor_frac`: the survival rate
    falls whenever the support shrinks for any reason, whereas the ratio says whether
    the pixels that survived are still the GOOD ones."""

    def _ratio(self, anchor_err, bg_err):
        s = torch.zeros(H, W)
        s[: H // 2] = 1.0                      # top half = anchors
        img = torch.full((3, H, W), 0.5)
        img[:, : H // 2] += anchor_err
        img[:, H // 2:] += bg_err
        out = _probe()._anchor_stats(_view(), **_inputs(s, render_image=img))
        return out

    def test_good_anchors_give_ratio_below_one(self):
        out = self._ratio(anchor_err=0.01, bg_err=0.10)
        self.assertLess(out["anchor_ratio_s90"], 1.0)
        self.assertAlmostEqual(out["anchor_rgb_med_s90"], 0.01, places=5)
        self.assertAlmostEqual(out["anchor_rgb_med_bg_s90"], 0.10, places=5)

    def test_bad_anchors_give_ratio_above_one(self):
        out = self._ratio(anchor_err=0.10, bg_err=0.01)
        self.assertGreater(out["anchor_ratio_s90"], 1.0)

    def test_empty_complement_is_nan_not_a_crash(self):
        """s == 1 everywhere: every support pixel is an anchor, so the background
        median is undefined. It must read nan, not 0 (which would look like a
        perfect-contrast frame) and not raise."""
        out = _probe()._anchor_stats(_view(), **_inputs(torch.ones(H, W)))
        self.assertNotEqual(out["anchor_rgb_med_bg_s90"], out["anchor_rgb_med_bg_s90"])
        self.assertNotEqual(out["anchor_ratio_s90"], out["anchor_ratio_s90"])
        self.assertEqual(out["anchor_probe"], 1)

    def test_depth_residual_ignores_missing_depth(self):
        obs = torch.full((H, W), 2.0)
        obs[: H // 4] = 0.0                    # no depth return
        ren = torch.full((H, W), 2.3)
        out = _probe()._anchor_stats(
            _view(), **_inputs(torch.ones(H, W), render_depth=ren, obs_depth=obs)
        )
        self.assertAlmostEqual(out["anchor_dep_med_s90"], 0.3, places=5)


class AnchorProbeContract(unittest.TestCase):
    def test_failure_is_reported_not_swallowed(self):
        """A diagnostic must never kill a run, but a failed probe must be
        distinguishable on disk from a probe that was off (which emits no columns)."""
        stub = _probe()
        stub.config = {"Training": {}}          # KeyError inside the probe
        out = stub._anchor_stats(_view(), **_inputs(torch.ones(H, W)))
        self.assertEqual(out, {"anchor_probe": 0})

    def test_probe_has_no_side_effects_on_its_inputs(self):
        s = torch.rand(H, W)
        v = _view()
        img = torch.rand(3, H, W)
        ren, obs = torch.rand(H, W) + 1.0, torch.rand(H, W) + 1.0
        before = (s.clone(), v.original_image.clone(), img.clone(), ren.clone(), obs.clone())
        _probe()._anchor_stats(
            v, **_inputs(s, render_image=img, render_depth=ren, obs_depth=obs)
        )
        for got, want in zip((s, v.original_image, img, ren, obs), before):
            self.assertTrue(torch.equal(got, want))

    def test_last_snapshot_is_stashed_for_m3(self):
        stub = _probe()
        out = stub._anchor_stats(_view(), **_inputs(torch.ones(H, W)))
        self.assertEqual(stub._anchor_last, out)

    def test_off_leaves_the_frames_csv_schema_untouched(self):
        """The byte-identical guard: with the probe off the row carries no anchor_*
        key, so the derived column set is exactly the historic one."""
        historic = {
            "frame": 1, "tracking_itr": 10, "mean_s": 0.9, "min_s": 0.0,
            "mean_w": 0.7, "min_w": 0.0, "flow_valid_frac": 0.5,
            "e_flow_mean_valid": 0.1, "g_mean": 0.2,
            "ego_projection": 0, "tracking_downweight_off": 0, "mad_exclusion": 0,
        }
        self.assertFalse(
            any(k.startswith("anchor_") for k in reliability_frames_fields([historic]))
        )

    def test_on_appends_every_anchor_column(self):
        row = {
            "frame": 1, "tracking_itr": 10, "mean_s": 0.9, "min_s": 0.0,
            "mean_w": 0.7, "min_w": 0.0, "flow_valid_frac": 0.5,
            "e_flow_mean_valid": 0.1, "g_mean": 0.2,
        }
        row.update(_probe()._anchor_stats(_view(), **_inputs(torch.ones(H, W))))
        fields = reliability_frames_fields([row])
        for tag in ("s80", "s90", "s95"):
            for stem in ("frac", "n", "rgb_med", "rgb_med_bg", "dep_med", "ratio"):
                self.assertIn(f"anchor_{stem}_{tag}", fields)
        self.assertIn("anchor_support_frac", fields)
        self.assertIn("anchor_probe", fields)


if __name__ == "__main__":
    unittest.main()
