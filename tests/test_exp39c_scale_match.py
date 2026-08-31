"""exp39 Step C 尺度混杂修复的单测（2026-08-23 审计产物）。

为什么这个文件存在
------------------
Step C 的原 EMA 分支返回 ``c_rgb = sum(w)/count(valid)``（**平均**权重），再把它
**乘**到 loss 上，于是光度项按 ``w_bar**2`` 缩放。实测 ``w_bar`` = 239(E) / 538(S)
⇒ 相对硬 mask 臂膨胀 5.7e4 / 2.9e5 倍，而固定的 ``10 * isotropic_loss.mean()``
正则项没变 ⇒ 那两个臂事实上跑在"几乎无 isotropic 正则"的状态下。
因此原先所有 E-vs-H 的 ATE 差都混着五个数量级的尺度差，
"伤害来自 admission"这一结论不成立（已撤回）。

本文件的核心是 ``TestMathematicalEquivalenceToHard``：它证明打开
mass_match + zero_dynamic 后，**均匀权重经 EMA 代码分支算出的 loss 与硬 mask 分支
逐位相等**。这在零 GPU 下**解析地**排除了"代码分支本身造成差异"这个混杂，
不需要烧一个 run 去测（codex 对抗审核第 2 点）。
"""
import torch
import pytest

from utils.mapping_weight import (
    apply_ema_mass_match,
    ema_mass_matched,
    ema_zero_dynamic,
)
from utils.slam_utils import get_loss_mapping_rgbd


ALPHA = 0.95
RGB_TH = 0.01

# get_loss_mapping_rgbd 对 viewpoint.original_image 硬编码 .cuda()（生产路径恒在 GPU），
# 所以这些测试必须在 CUDA 上跑才是在测真实分支。
pytestmark = pytest.mark.skipif(
    not torch.cuda.is_available(), reason="loss 分支硬编码 .cuda()，需要 GPU"
)
DEV = "cuda" if torch.cuda.is_available() else "cpu"


def _cfg(**semantic):
    base = {"enabled": True, "mask_mapping": True}
    base.update(semantic)
    return {
        "Training": {"alpha": ALPHA, "rgb_boundary_threshold": RGB_TH},
        "SemanticMask": base,
    }


class _Viewpoint:
    """Minimal stand-in for the camera object the loss reads."""

    def __init__(self, gt_image, gt_depth):
        self.original_image = gt_image
        self.depth = gt_depth.squeeze(0).cpu().numpy()


@pytest.fixture
def scene():
    """A tiny deterministic scene: 1 invalid column, 1 dynamic block."""
    torch.manual_seed(0)
    H, W = 6, 8
    gt_image = (torch.rand(3, H, W).abs() + 0.5).to(DEV)
    gt_image[:, :, 0] = 0.0                          # column 0 -> invalid (near-black)
    gt_depth = torch.full((1, H, W), 2.0, device=DEV)
    image = gt_image + 0.1 * torch.randn(3, H, W, device=DEV)
    depth = gt_depth + 0.05 * torch.randn(1, H, W, device=DEV)

    dynamic_mask = torch.zeros(1, H, W, dtype=torch.bool, device=DEV)
    dynamic_mask[:, 1:3, 4:7] = True                 # a dynamic block inside valid area

    return {
        "image": image, "depth": depth,
        "viewpoint": _Viewpoint(gt_image, gt_depth),
        "dynamic_mask": dynamic_mask,
        "H": H, "W": W,
    }


def _hard_loss(scene):
    return get_loss_mapping_rgbd(
        _cfg(), scene["image"], scene["depth"], scene["viewpoint"],
        dynamic_mask=scene["dynamic_mask"],
    )


def _ema_loss(scene, weight_map, c_mass, **flags):
    return get_loss_mapping_rgbd(
        _cfg(**flags), scene["image"], scene["depth"], scene["viewpoint"],
        dynamic_mask=scene["dynamic_mask"],
        ema_weight_map=weight_map, ema_c_mass=c_mass,
    )


class TestMathematicalEquivalenceToHard:
    """均匀权重 + mass_match + zero_dynamic 走 EMA 分支 ⇒ 必须等于硬 mask 分支。

    这是本次修复的关键正对照：它把"H 与 E/S 的差异可能来自代码分支（分母、
    有效像素数、梯度稀疏性）"这个混杂**解析地**排除，代价为零 GPU。
    """

    def test_uniform_weight_reproduces_hard_loss_exactly(self, scene):
        ones = torch.ones(1, scene["H"], scene["W"], device=DEV)
        hard = _hard_loss(scene)
        ema = _ema_loss(
            scene, ones, c_mass=1.0,
            mapping_ema_mass_match=True, mapping_ema_zero_dynamic=True,
        )
        assert torch.allclose(hard, ema, rtol=1e-6, atol=1e-8), (
            f"EMA 分支未能复现硬 mask: hard={hard.item():.10f} ema={ema.item():.10f}"
        )

    def test_nonuniform_weight_also_matches_after_mass_match(self, scene):
        """非均匀权重经 mass_match 后总质量必须等于硬臂 —— 只剩形状差异。"""
        torch.manual_seed(1)
        w = torch.rand(1, scene["H"], scene["W"], device=DEV) * 100 + 1
        ema = _ema_loss(
            scene, w, c_mass=999.0,     # c_mass 应被 mass_match 完全忽略
            mapping_ema_mass_match=True, mapping_ema_zero_dynamic=True,
        )
        hard = _hard_loss(scene)
        # 形状不同 ⇒ 数值不等，但必须同量级（不是 5 个数量级的差）
        ratio = float(ema / hard)
        assert 0.2 < ratio < 5.0, f"mass_match 后仍差 {ratio:.1f}x，尺度没对齐"

    def test_c_mass_is_ignored_when_mass_match_on(self, scene):
        ones = torch.ones(1, scene["H"], scene["W"], device=DEV)
        a = _ema_loss(scene, ones, c_mass=1.0,
                      mapping_ema_mass_match=True, mapping_ema_zero_dynamic=True)
        b = _ema_loss(scene, ones, c_mass=12345.0,
                      mapping_ema_mass_match=True, mapping_ema_zero_dynamic=True)
        assert torch.allclose(a, b), "mass_match 打开时 ema_c_mass 必须无效"


class TestScaleInflationRegression:
    """钉住被撤回结论的根因：旧路径确实按 w_bar**2 膨胀。"""

    def test_legacy_path_inflates_by_w_bar_squared(self, scene):
        """已知坏值复现：w=200 均匀、c_mass=mean(w) ⇒ 相对硬臂膨胀约 w**2。"""
        w_val = 200.0
        w = torch.full((1, scene["H"], scene["W"]), w_val, device=DEV)
        legacy = _ema_loss(scene, w, c_mass=w_val)       # 旧行为，两个 flag 都关
        hard = _hard_loss(scene)
        ratio = float(legacy / hard)
        assert ratio > 1e4, f"未复现尺度膨胀（只有 {ratio:.0f}x）"

    def test_mass_match_removes_the_inflation(self, scene):
        w_val = 200.0
        w = torch.full((1, scene["H"], scene["W"]), w_val, device=DEV)
        fixed = _ema_loss(scene, w, c_mass=w_val,
                          mapping_ema_mass_match=True, mapping_ema_zero_dynamic=True)
        hard = _hard_loss(scene)
        assert torch.allclose(hard, fixed, rtol=1e-6), "mass_match 未消除膨胀"


class TestZeroDynamicIsolatesAdmission:
    def test_dynamic_pixels_carry_no_weight(self, scene):
        """zero_dynamic 打开时，动态像素的贡献必须精确为 0。

        做法：只在动态区改变 image，loss 必须完全不动。
        """
        torch.manual_seed(2)
        w = torch.rand(1, scene["H"], scene["W"], device=DEV) * 10 + 1
        flags = dict(mapping_ema_mass_match=True, mapping_ema_zero_dynamic=True)
        before = _ema_loss(scene, w, 1.0, **flags)

        perturbed = dict(scene)
        img = scene["image"].clone()
        img[:, 1:3, 4:7] += 5.0                       # 只动动态块
        perturbed["image"] = img
        after = _ema_loss(perturbed, w, 1.0, **flags)

        assert torch.allclose(before, after, rtol=1e-6), (
            "动态像素仍在贡献 loss，zero_dynamic 没生效"
        )

    def test_admitting_arm_does_react_to_dynamic_pixels(self, scene):
        """负对照：不开 zero_dynamic 时，动态像素必须影响 loss（否则门测不到 admission）。"""
        torch.manual_seed(2)
        w = torch.rand(1, scene["H"], scene["W"], device=DEV) * 10 + 1
        flags = dict(mapping_ema_mass_match=True)     # 允许 admission
        before = _ema_loss(scene, w, 1.0, **flags)

        perturbed = dict(scene)
        img = scene["image"].clone()
        img[:, 1:3, 4:7] += 5.0
        perturbed["image"] = img
        after = _ema_loss(perturbed, w, 1.0, **flags)

        assert not torch.allclose(before, after, rtol=1e-3), (
            "admission 臂对动态像素无反应 —— 两臂无法区分 admission"
        )


class TestMassMatchHelper:
    def test_rescales_to_target_mass(self):
        w = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
        contributing = torch.tensor([[True, True, True, False]])
        out = apply_ema_mass_match(w, contributing, target_mass=torch.tensor(3.0))
        assert torch.allclose((out * contributing).sum(), torch.tensor(3.0))

    def test_uniform_weight_is_unchanged_when_target_equals_count(self):
        w = torch.ones(1, 5)
        contributing = torch.ones(1, 5, dtype=torch.bool)
        out = apply_ema_mass_match(w, contributing, target_mass=torch.tensor(5.0))
        assert torch.allclose(out, w)

    def test_all_zero_weight_does_not_divide_by_zero(self):
        w = torch.zeros(1, 4)
        contributing = torch.ones(1, 4, dtype=torch.bool)
        out = apply_ema_mass_match(w, contributing, target_mass=torch.tensor(4.0))
        assert torch.isfinite(out).all()


class TestConfigFlags:
    def test_flags_default_off(self):
        assert ema_mass_matched(_cfg()) is False
        assert ema_zero_dynamic(_cfg()) is False

    def test_flags_read_from_semantic_mask(self):
        assert ema_mass_matched(_cfg(mapping_ema_mass_match=True)) is True
        assert ema_zero_dynamic(_cfg(mapping_ema_zero_dynamic=True)) is True


class TestScrambleMassPreservation:
    """D-3 置换必须在 valid 内部做 —— 旧版全图置换把无效区的 ~1e4 权重搬进 valid。"""

    def test_scramble_preserves_valid_restricted_mass(self):
        from utils.mapping_probe import MappingEMARecorder

        cfg = {
            "Training": {"alpha": ALPHA, "rgb_boundary_threshold": RGB_TH},
            "SemanticMask": {
                "enabled": True, "mask_mapping": True, "mapping_ema": True,
                "mapping_ema_sigma_min": 0.01,
            },
        }
        torch.manual_seed(3)
        H, W = 8, 10
        rgb_valid = torch.ones(1, H, W, dtype=torch.bool)
        rgb_valid[:, :, :3] = False                   # 3 列无效

        plain, scrambled = MappingEMARecorder(cfg), MappingEMARecorder(cfg)
        scrambled.scramble = True
        # 无效区残差 ~0（=> 权重 ~1/sigma_min^2 ~ 1e4），有效区残差正常
        rgb_err = torch.rand(1, H, W) * 0.2 + 0.05
        rgb_err[:, :, :3] = 0.0
        depth_err = torch.rand(1, H, W) * 0.05
        for rec in (plain, scrambled):
            rec.update(rgb_err, depth_err)

        w_plain, _ = plain.compute_weights(rgb_valid, torch.float32)
        w_scr, _ = scrambled.compute_weights(rgb_valid, torch.float32)

        mass_plain = float(w_plain[rgb_valid].sum())
        mass_scr = float(w_scr[rgb_valid].sum())
        assert mass_plain == pytest.approx(mass_scr, rel=1e-5), (
            f"置换改变了 valid 内总质量: {mass_plain:.2f} -> {mass_scr:.2f} "
            "（旧版全图置换正是这样把 1e4 权重搬进 valid，w_bar 239->538）"
        )

    def test_scramble_actually_permutes(self):
        from utils.mapping_probe import MappingEMARecorder

        cfg = {
            "Training": {"alpha": ALPHA, "rgb_boundary_threshold": RGB_TH},
            "SemanticMask": {"enabled": True, "mask_mapping": True,
                             "mapping_ema": True, "mapping_ema_sigma_min": 0.01},
        }
        torch.manual_seed(4)
        rgb_valid = torch.ones(1, 8, 10, dtype=torch.bool)
        rec = MappingEMARecorder(cfg)
        rec.scramble = True
        rgb_err = torch.rand(1, 8, 10)
        rec.update(rgb_err, torch.rand(1, 8, 10) * 0.05)
        a, _ = rec.compute_weights(rgb_valid, torch.float32)
        b, _ = rec.compute_weights(rgb_valid, torch.float32)
        assert not torch.allclose(a, b), "两次置换结果相同，打乱没有真正发生"


class TestProbeReportsObjectiveWeight:
    """probe 报的必须是**目标函数**用的权重，不是 EMA 原始状态。

    2026-08-23：G-2 门在一个配置完全正确的 zeromask 臂上返回 FAIL，
    因为 zero_dynamic / mass_match 的施加发生在 get_loss_mapping_rgbd 里，
    而 probe 读的是 compute_weights() 的原始输出 ⇒ 门量的不是目标函数的权重。
    这组测试钉住"probe 的有效权重 == loss 的有效权重"。
    """

    def _effective_probe_weight(self, raw_w, rgb_valid, static, cfg):
        """复刻 probe 内的有效权重推导（与 mapping_probe 中同一套 helper）。"""
        from utils.mapping_weight import (
            apply_ema_mass_match, ema_mass_matched, ema_zero_dynamic,
        )
        w = raw_w.clone()
        zero_dyn = ema_zero_dynamic(cfg)
        if zero_dyn:
            w = w * static.to(dtype=w.dtype)
        if ema_mass_matched(cfg):
            target = (rgb_valid & static).to(dtype=w.dtype).sum()
            contributing = rgb_valid & (static if zero_dyn else rgb_valid)
            w = apply_ema_mass_match(w, contributing, target)
        return w

    def test_zeromask_effective_weight_is_zero_on_dynamic(self, scene):
        """G-2 的意图：有效权重在动态像素上必须恒为 0。"""
        torch.manual_seed(5)
        raw = torch.rand(1, scene["H"], scene["W"], device=DEV) * 500 + 1
        gt = scene["viewpoint"].original_image
        rgb_valid = (gt.sum(dim=0) > RGB_TH).view(1, scene["H"], scene["W"])
        static = ~scene["dynamic_mask"]
        cfg = _cfg(mapping_ema_mass_match=True, mapping_ema_zero_dynamic=True)

        eff = self._effective_probe_weight(raw, rgb_valid, static, cfg)
        dyn = ~static
        assert float(eff[dyn].abs().max()) == 0.0, (
            "有效权重在动态像素上非 0 —— G-2 会误判"
        )

    def test_admitting_arm_effective_weight_is_positive_on_dynamic(self, scene):
        """G-3 的意图：admission 臂的动态像素有效权重必须 > 0。"""
        torch.manual_seed(5)
        raw = torch.rand(1, scene["H"], scene["W"], device=DEV) * 500 + 1
        gt = scene["viewpoint"].original_image
        rgb_valid = (gt.sum(dim=0) > RGB_TH).view(1, scene["H"], scene["W"])
        static = ~scene["dynamic_mask"]
        cfg = _cfg(mapping_ema_mass_match=True)      # admission 开

        eff = self._effective_probe_weight(raw, rgb_valid, static, cfg)
        dyn = (~static) & rgb_valid
        assert float(eff[dyn].min()) > 0.0

    def test_effective_weight_matches_loss_exactly(self, scene):
        """probe 的有效权重代入手算 loss，必须等于 get_loss_mapping_rgbd 的输出。

        这是把 probe 与 loss 钉在同一个目标函数上的等价性检查。
        """
        torch.manual_seed(6)
        raw = torch.rand(1, scene["H"], scene["W"], device=DEV) * 50 + 1
        gt = scene["viewpoint"].original_image
        gt_depth = torch.from_numpy(scene["viewpoint"].depth).to(
            dtype=torch.float32, device=DEV
        )[None]
        rgb_valid = (gt.sum(dim=0) > RGB_TH).view(1, scene["H"], scene["W"])
        depth_valid = gt_depth > 0.01
        static = ~scene["dynamic_mask"]

        for flags in (
            dict(mapping_ema_mass_match=True, mapping_ema_zero_dynamic=True),
            dict(mapping_ema_mass_match=True),
        ):
            cfg = _cfg(**flags)
            eff = self._effective_probe_weight(raw, rgb_valid, static, cfg)
            manual = (
                ALPHA * ((scene["image"] - gt).abs() * (rgb_valid * eff)).mean()
                + (1 - ALPHA)
                * ((scene["depth"] - gt_depth).abs() * (depth_valid * eff)).mean()
            )
            actual = _ema_loss(scene, raw, 1.0, **flags)
            assert torch.allclose(manual, actual, rtol=1e-5), (
                f"flags={flags}: probe 有效权重与 loss 不一致 "
                f"manual={manual.item():.8f} actual={actual.item():.8f}"
            )


class TestDiagnosticPolarity:
    """钉住 ema_* 诊断的极性。

    2026-08-23：``ema_weight_diagnostics`` / ``ema_component_decomposition`` 的第三个
    形参名为 ``static_mask``，但两个调用点传的都是动态掩码 ⇒ 两个字段标签互换、
    ``ema_dynamic_over_static`` 变成自己的倒数。Step C 四轮
    （−3.21 / −3.51 / −3.91 / −2.15）全是透过这个反转读的，预注册主判据
    被判在了翻转的符号上。这组测试喂"动态权重已知更低"的构造值，
    任何一次标签互换都会让它们失败。
    """

    @staticmethod
    def _masks(H=4, W=6):
        valid = torch.ones(1, H, W, dtype=torch.bool)
        dynamic = torch.zeros(1, H, W, dtype=torch.bool)
        dynamic[:, :, :2] = True                 # 前两列 = 动态
        return valid, dynamic

    def test_suppressed_dynamic_gives_ratio_below_one(self):
        """动态权重 1、静态权重 10 ⇒ ratio 必须是 0.1，bias_suppression = +0.9。"""
        from utils.mapping_weight import ema_weight_diagnostics
        valid, dynamic = self._masks()
        w = torch.where(dynamic, torch.ones_like(dynamic, dtype=torch.float32),
                        torch.full(dynamic.shape, 10.0))
        d = ema_weight_diagnostics(w, valid, dynamic)
        assert d["ema_mean_weight_dynamic"] == pytest.approx(1.0)
        assert d["ema_mean_weight_static"] == pytest.approx(10.0)
        assert d["ema_dynamic_over_static"] == pytest.approx(0.1)
        assert d["ema_bias_suppression"] == pytest.approx(0.9)

    def test_amplified_dynamic_gives_ratio_above_one(self):
        """已知坏值方向：动态权重 10、静态 1 ⇒ ratio 10，bias_suppression = −9。"""
        from utils.mapping_weight import ema_weight_diagnostics
        valid, dynamic = self._masks()
        w = torch.where(dynamic, torch.full(dynamic.shape, 10.0),
                        torch.ones_like(dynamic, dtype=torch.float32))
        d = ema_weight_diagnostics(w, valid, dynamic)
        assert d["ema_dynamic_over_static"] == pytest.approx(10.0)
        assert d["ema_bias_suppression"] == pytest.approx(-9.0)

    def test_zeroed_dynamic_reports_zero_under_the_dynamic_name(self):
        """zero_dynamic 臂的实测特征：动态均值 0 必须出现在 _dynamic 字段下。

        互换时它会出现在 _static 字段下 —— 这正是 G-2 门误判 FAIL 的现场。
        """
        from utils.mapping_weight import ema_weight_diagnostics
        valid, dynamic = self._masks()
        w = torch.where(dynamic, torch.zeros(dynamic.shape),
                        torch.ones(dynamic.shape))
        d = ema_weight_diagnostics(w, valid, dynamic)
        assert d["ema_mean_weight_dynamic"] == 0.0, "标签仍是互换的"
        assert d["ema_mean_weight_static"] == pytest.approx(1.0)

    def test_component_decomposition_polarity(self):
        """μ² 分量：动态残差更大 ⇒ ema_mu2_dynamic 必须更大。"""
        from utils.mapping_probe import MappingEMARecorder
        from utils.mapping_weight import ema_component_decomposition

        cfg = {
            "Training": {"alpha": ALPHA, "rgb_boundary_threshold": RGB_TH},
            "SemanticMask": {"enabled": True, "mask_mapping": True,
                             "mapping_ema": True, "mapping_ema_sigma_min": 0.01},
        }
        valid, dynamic = self._masks()
        rec = MappingEMARecorder(cfg)
        # 动态像素残差 0.5，静态 0.05 ⇒ 动态 μ² 应大 100 倍
        rgb_err = torch.where(dynamic, torch.full(dynamic.shape, 0.5),
                              torch.full(dynamic.shape, 0.05))
        rec.update(rgb_err, torch.zeros(dynamic.shape))

        d = ema_component_decomposition(rec, valid, dynamic)
        assert d["ema_mu2_dynamic"] > d["ema_mu2_static"], (
            "μ² 极性反了：动态残差更大时 ema_mu2_dynamic 必须更大"
        )
        assert d["ema_mu2_ratio"] == pytest.approx(100.0, rel=1e-3)


class TestAdmissionDoseCap:
    """剂量扫描：mapping_ema_dynamic_cap 必须精确交付配置的份额。

    G-4 门押的就是这个量。cap 的意义是让
    ``mean_w(dyn)/mean_w(stat)`` 等于配置值，且该比值对随后的 mass_match
    （全像素同倍缩放）不变 —— 剂量与总质量是两个独立旋钮。
    """

    @staticmethod
    def _masks(H=6, W=8):
        valid = torch.ones(1, H, W, dtype=torch.bool, device=DEV)
        dynamic = torch.zeros(1, H, W, dtype=torch.bool, device=DEV)
        dynamic[:, :, :3] = True
        return valid, dynamic

    @pytest.mark.parametrize("cap", [0.5, 0.05, 0.01, 0.0])
    def test_cap_delivers_exact_ratio(self, cap):
        from utils.mapping_weight import apply_ema_dynamic_cap, ema_weight_diagnostics
        valid, dynamic = self._masks()
        torch.manual_seed(7)
        w = torch.rand(1, 6, 8, device=DEV) * 100 + 10
        out = apply_ema_dynamic_cap(w, valid, dynamic, cap)
        d = ema_weight_diagnostics(out, valid, dynamic)
        assert d["ema_dynamic_over_static"] == pytest.approx(cap, abs=1e-5), (
            f"cap={cap} 未被交付，实测 {d['ema_dynamic_over_static']}"
        )

    def test_cap_ratio_survives_mass_match(self):
        """mass_match 是全像素同倍缩放 ⇒ 剂量比值必须不变。"""
        from utils.mapping_weight import (
            apply_ema_dynamic_cap, apply_ema_mass_match, ema_weight_diagnostics,
        )
        valid, dynamic = self._masks()
        torch.manual_seed(8)
        w = torch.rand(1, 6, 8, device=DEV) * 100 + 10
        capped = apply_ema_dynamic_cap(w, valid, dynamic, 0.05)
        before = ema_weight_diagnostics(capped, valid, dynamic)["ema_dynamic_over_static"]

        static = ~dynamic
        target = (valid & static).to(dtype=w.dtype).sum()
        massed = apply_ema_mass_match(capped, valid, target)
        after = ema_weight_diagnostics(massed, valid, dynamic)["ema_dynamic_over_static"]

        assert after == pytest.approx(before, rel=1e-5), "mass_match 改变了剂量比值"

    def test_cap_preserves_shape_within_dynamic_population(self):
        """cap 是均值重标定，不是逐像素截断 ⇒ 动态内部的相对形状保持。"""
        from utils.mapping_weight import apply_ema_dynamic_cap
        valid, dynamic = self._masks()
        torch.manual_seed(9)
        w = torch.rand(1, 6, 8, device=DEV) * 100 + 10
        out = apply_ema_dynamic_cap(w, valid, dynamic, 0.05)
        dyn = dynamic & valid
        ratio = out[dyn] / w[dyn]
        assert torch.allclose(ratio, ratio[0].expand_as(ratio), rtol=1e-5), (
            "动态内部不是同一倍率 ⇒ 形状被改动（应为均值重标定）"
        )

    def test_static_weights_untouched_by_cap(self):
        from utils.mapping_weight import apply_ema_dynamic_cap
        valid, dynamic = self._masks()
        torch.manual_seed(10)
        w = torch.rand(1, 6, 8, device=DEV) * 100 + 10
        out = apply_ema_dynamic_cap(w, valid, dynamic, 0.05)
        stat = (~dynamic) & valid
        assert torch.allclose(out[stat], w[stat]), "cap 动到了静态像素"

    def test_cap_reaches_the_loss(self, scene):
        """端到端：cap 必须改变 get_loss_mapping_rgbd 的输出。"""
        torch.manual_seed(11)
        raw = torch.rand(1, scene["H"], scene["W"], device=DEV) * 50 + 1
        a = _ema_loss(scene, raw, 1.0, mapping_ema_mass_match=True,
                      mapping_ema_dynamic_cap=0.30)
        b = _ema_loss(scene, raw, 1.0, mapping_ema_mass_match=True,
                      mapping_ema_dynamic_cap=0.01)
        assert not torch.allclose(a, b, rtol=1e-4), "cap 没有进到 loss"

    def test_cap_zero_matches_zero_dynamic_arm(self, scene):
        """cap=0 与 zero_dynamic 在数学上等价（两条路都让动态贡献为 0）。"""
        torch.manual_seed(12)
        raw = torch.rand(1, scene["H"], scene["W"], device=DEV) * 50 + 1
        via_cap = _ema_loss(scene, raw, 1.0, mapping_ema_mass_match=True,
                            mapping_ema_dynamic_cap=0.0)
        via_flag = _ema_loss(scene, raw, 1.0, mapping_ema_mass_match=True,
                             mapping_ema_zero_dynamic=True)
        assert torch.allclose(via_cap, via_flag, rtol=1e-5), (
            f"cap=0 {via_cap.item():.8f} != zero_dynamic {via_flag.item():.8f}"
        )

    def test_invalid_cap_rejected(self):
        from utils.mapping_weight import ema_dynamic_cap
        for bad in (-0.1, 1.5):
            with pytest.raises(ValueError):
                ema_dynamic_cap(_cfg(mapping_ema_dynamic_cap=bad))

    def test_cap_default_is_none(self):
        from utils.mapping_weight import ema_dynamic_cap
        assert ema_dynamic_cap(_cfg()) is None
