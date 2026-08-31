"""exp39 A2 contract: continuous dynamic weighting of the mapping/BA loss.

The two identity anchors are the point of this file. The soft arm is only a legitimate
single-variable intervention if it *contains* the arm it replaces:
  floor=0.0 must reproduce today's hard mask bit-for-bit;
  floor=1.0 must reproduce no mask at all bit-for-bit.
Anything else means the treatment moved something besides the weight shape.

Per exp37's gate lesson (a gate that can never fail is not a gate) every guard here is
also fed a known-bad value and asserted to fail.
"""

import numpy as np
import pytest
import torch

from utils.mapping_weight import (
    mapping_scale_match_floor,
    mapping_soft_floor,
    scale_match_factor,
    weight_stats,
)
from utils.slam_utils import get_loss_mapping_rgbd


class _FakeViewpoint:
    def __init__(self, gt_image, gt_depth):
        self._gt_image = gt_image
        self.depth = gt_depth

    @property
    def original_image(self):
        class _Cudable:
            def __init__(self, tensor):
                self._tensor = tensor

            def cuda(self):
                return self._tensor

            def __getattr__(self, name):
                return getattr(self._tensor, name)

        return _Cudable(self._gt_image)


def _fixture(h=8, w=12, seed=0):
    gen = torch.Generator().manual_seed(seed)
    image = torch.rand(3, h, w, generator=gen)
    gt_image = torch.rand(3, h, w, generator=gen)
    depth = torch.rand(1, h, w, generator=gen) + 0.5
    gt_depth = (torch.rand(1, h, w, generator=gen) + 0.5).numpy().astype(np.float32)
    dynamic = torch.zeros(1, h, w, dtype=torch.bool)
    dynamic[:, :, : w // 3] = True  # a third of the frame is "dynamic"
    config = {"Training": {"alpha": 0.95, "rgb_boundary_threshold": 0.01}}
    return config, image, depth, _FakeViewpoint(gt_image, gt_depth), dynamic


def _loss(**kwargs):
    config, image, depth, viewpoint, dynamic = _fixture()
    return get_loss_mapping_rgbd(config, image, depth, viewpoint, **kwargs)


class TestIdentityAnchors:
    def test_floor_zero_reproduces_hard_mask_bitwise(self):
        config, image, depth, viewpoint, dynamic = _fixture()
        hard = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic
        )
        soft0 = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic, soft_floor=0.0
        )
        assert torch.equal(hard, soft0), (
            f"floor=0 must BE the hard mask, got {hard.item()} vs {soft0.item()}"
        )

    def test_floor_one_reproduces_no_mask_bitwise(self):
        config, image, depth, viewpoint, dynamic = _fixture()
        no_mask = get_loss_mapping_rgbd(config, image, depth, viewpoint)
        soft1 = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic, soft_floor=1.0
        )
        assert torch.equal(no_mask, soft1), (
            f"floor=1 must BE the unmasked loss, got {no_mask.item()} vs {soft1.item()}"
        )

    def test_anchors_would_catch_a_broken_floor(self):
        """Known-bad feed: an interior floor must NOT match either endpoint."""
        config, image, depth, viewpoint, dynamic = _fixture()
        hard = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic
        )
        no_mask = get_loss_mapping_rgbd(config, image, depth, viewpoint)
        mid = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic, soft_floor=0.5
        )
        assert not torch.equal(mid, hard)
        assert not torch.equal(mid, no_mask)

    def test_loss_is_monotone_in_floor(self):
        """Re-admitting dynamic pixels can only add non-negative residual mass."""
        losses = [
            _loss(dynamic_mask=_fixture()[4], soft_floor=f).item()
            for f in (0.0, 0.25, 0.5, 0.75, 1.0)
        ]
        assert losses == sorted(losses), losses


class TestDefaultOff:
    def test_no_kwargs_is_the_untouched_hard_path(self):
        config, image, depth, viewpoint, dynamic = _fixture()
        a = get_loss_mapping_rgbd(config, image, depth, viewpoint, dynamic_mask=dynamic)
        b = get_loss_mapping_rgbd(
            config,
            image,
            depth,
            viewpoint,
            dynamic_mask=dynamic,
            soft_floor=None,
            scale_match_floor=None,
        )
        assert torch.equal(a, b)

    def test_flags_are_inert_without_a_dynamic_mask(self):
        config, image, depth, viewpoint, _ = _fixture()
        base = get_loss_mapping_rgbd(config, image, depth, viewpoint)
        for kwargs in ({"soft_floor": 0.3}, {"scale_match_floor": 0.3}):
            assert torch.equal(
                base, get_loss_mapping_rgbd(config, image, depth, viewpoint, **kwargs)
            )


class TestScaleMatchControl:
    def test_scale_match_keeps_hard_mask_but_lifts_magnitude(self):
        config, image, depth, viewpoint, dynamic = _fixture()
        hard = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic
        )
        matched = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic, scale_match_floor=0.5
        )
        # Same masked residuals, strictly larger weight mass => strictly larger loss.
        assert matched.item() > hard.item()

    def test_scale_match_factor_matches_closed_form(self):
        h, w = 4, 6
        valid = torch.ones(1, h, w, dtype=torch.bool)
        static = torch.ones(1, h, w, dtype=torch.bool)
        static[:, :, :2] = False  # 1/3 dynamic
        floor = 0.5
        # soft mass = 16*1 + 8*0.5 = 20 ; hard mass = 16
        assert scale_match_factor(valid, static, floor) == pytest.approx(20.0 / 16.0)

    def test_scale_match_is_identity_at_floor_zero(self):
        config, image, depth, viewpoint, dynamic = _fixture()
        hard = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic
        )
        matched0 = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic, scale_match_floor=0.0
        )
        assert torch.equal(hard, matched0)

    def test_scale_match_carries_no_gradient_path(self):
        config, image, depth, viewpoint, dynamic = _fixture()
        image = image.clone().requires_grad_(True)
        loss = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic, scale_match_floor=0.5
        )
        loss.backward()
        # The factor is a python float: dynamic pixels stay hard-excluded from grads.
        assert torch.count_nonzero(image.grad[:, :, :4]) == 0


class TestConfigGuards:
    def _cfg(self, **semantic):
        base = {"enabled": True, "mask_mapping": True}
        base.update(semantic)
        return {"SemanticMask": base}

    def test_off_by_default(self):
        assert mapping_soft_floor(self._cfg()) is None
        assert mapping_scale_match_floor(self._cfg()) is None

    def test_soft_floor_reads_config(self):
        assert mapping_soft_floor(
            self._cfg(soft_mapping=True, mapping_floor=0.2)
        ) == pytest.approx(0.2)

    def test_inert_when_mask_mapping_off(self):
        """An arm that cannot act must not report itself as live."""
        cfg = {
            "SemanticMask": {
                "enabled": True,
                "mask_mapping": False,
                "soft_mapping": True,
                "mapping_floor": 0.2,
            }
        }
        assert mapping_soft_floor(cfg) is None

    def test_treatment_and_control_cannot_coexist(self):
        with pytest.raises(ValueError, match="unidentifiable"):
            mapping_soft_floor(
                self._cfg(soft_mapping=True, mapping_scale_match=True, mapping_floor=0.2)
            )

    @pytest.mark.parametrize("bad", [-0.1, 1.5])
    def test_out_of_range_floor_rejected(self, bad):
        with pytest.raises(ValueError, match="must be in"):
            mapping_soft_floor(self._cfg(soft_mapping=True, mapping_floor=bad))


class TestPhase0Probe:
    """The probe's own identity: at floor=0 the dynamic population must contribute
    exactly zero, so a non-zero dynamic gradient share in a Phase-0 control run is
    proof the arm is not what it claims to be (not merely 'a small effect')."""

    def test_dynamic_term_is_exactly_zero_at_floor_zero(self):
        from utils.mapping_probe import _split_losses

        config, image, depth, viewpoint, dynamic = _fixture()
        l_dyn, l_stat, _, _ = _split_losses(config, image, depth, viewpoint, dynamic, 0.0)
        assert l_dyn.item() == 0.0
        assert l_stat.item() > 0.0

    def test_dynamic_term_is_live_at_positive_floor(self):
        from utils.mapping_probe import _split_losses

        config, image, depth, viewpoint, dynamic = _fixture()
        l_dyn, _, _, _ = _split_losses(config, image, depth, viewpoint, dynamic, 0.25)
        assert l_dyn.item() > 0.0

    def test_split_reconstructs_the_treatment_loss(self):
        """L_dyn + L_stat must equal the loss the run actually optimises, otherwise the
        attribution is of some other objective."""
        from utils.mapping_probe import _split_losses

        config, image, depth, viewpoint, dynamic = _fixture()
        floor = 0.25
        l_dyn, l_stat, _, _ = _split_losses(config, image, depth, viewpoint, dynamic, floor)
        total = get_loss_mapping_rgbd(
            config, image, depth, viewpoint, dynamic_mask=dynamic, soft_floor=floor
        )
        assert (l_dyn + l_stat).item() == pytest.approx(total.item(), rel=1e-6)

    def test_probe_is_off_by_default_and_configurable(self):
        from utils.mapping_probe import mapping_probe_enabled, mapping_probe_interval

        assert mapping_probe_enabled({}) is False
        assert mapping_probe_enabled({"MappingProbe": {"enabled": True}}) is True
        assert mapping_probe_interval({"MappingProbe": {"interval": 25}}) == 25

    def test_probe_is_inert_without_a_mask(self):
        from utils.mapping_probe import probe_mapping_attribution

        assert (
            probe_mapping_attribution(
                {}, None, None, None, None, dynamic_mask=None, floor=0.25
            )
            is None
        )


class TestWeightStats:
    def test_counters_track_the_known_geometry(self):
        h, w = 4, 6
        valid = torch.ones(1, h, w, dtype=torch.bool)
        static = torch.ones(1, h, w, dtype=torch.bool)
        static[:, :, :2] = False  # exactly 1/3 dynamic
        stats = weight_stats(valid, static, 0.25)
        assert stats["dynamic_frac"] == pytest.approx(1 / 3)
        assert stats["applied_frac"] == pytest.approx(1 / 3)
        assert stats["mean_w_static"] == pytest.approx(1.0)
        assert stats["mean_w_dynamic"] == pytest.approx(0.25)
        assert stats["weight_mass"] == pytest.approx(16 + 8 * 0.25)

    def test_applied_frac_is_zero_when_floor_disables_the_arm(self):
        """Known-bad feed: at floor=1 nothing is down-weighted, and the counter
        must say so rather than reporting the dynamic area as 'applied'."""
        h, w = 4, 6
        valid = torch.ones(1, h, w, dtype=torch.bool)
        static = torch.ones(1, h, w, dtype=torch.bool)
        static[:, :, :2] = False
        assert weight_stats(valid, static, 1.0)["applied_frac"] == 0.0

    def test_ess_falls_when_weights_spread(self):
        h, w = 4, 6
        valid = torch.ones(1, h, w, dtype=torch.bool)
        static = torch.ones(1, h, w, dtype=torch.bool)
        static[:, :, :2] = False
        uniform = weight_stats(valid, static, 1.0)["ess_frac"]
        spread = weight_stats(valid, static, 0.25)["ess_frac"]
        assert uniform == pytest.approx(1.0)
        assert spread < uniform
