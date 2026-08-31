"""exp39 Step C 跨序列链条的结构对等性单测（零 GPU）。

跨序列判决只有在**两条链除数据集外无第二个差异**时才成立——否则"迁移与否"
混着配置差异。本文件把这条从口头承诺变成可执行断言（exp36 判据 #17：
把装置 claim 变成可执行断言）。

balloon 根 = t2_eboth_balloon（balloon + method_t2_eboth）
f3      根 = pba_eboth_f3_wk_xyz（f3_wk_xyz + 同一个 method_t2_eboth）
"""
from pathlib import Path

import pytest

from utils.config_utils import load_config

D = "configs/rgbd/experiments/exp39_mapping_soft"
ARMS = [
    ("hard", "exp39c_hard"),
    ("zeromask", "exp39c_sm_zeromask"),
    ("sm", "exp39c_sm"),
    ("cap05", "exp39c_cap05"),
]
# 允许逐序列不同的键：数据集路径、标签、标定、以及一切 Dataset./Calibration. 前缀
LABEL_KEYS = {"method", "inherit_from", "method_from"}


def _flat(cfg, prefix=""):
    out = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            out.update(_flat(v, prefix + k + "."))
        else:
            out[prefix + k] = v
    return out


def _sequence_local(key):
    return (
        key in LABEL_KEYS
        or key.startswith("Dataset.")
        or key.startswith("Calibration")
    )


class TestCrossSequenceChainParity:
    @pytest.mark.parametrize("name,stem", ARMS)
    def test_f3_arm_differs_from_balloon_only_by_sequence(self, name, stem):
        b = _flat(load_config(f"{D}/{stem}_balloon.yaml"))
        f = _flat(load_config(f"{D}/{stem}_f3_wk_xyz.yaml"))
        diff = sorted(k for k in set(b) | set(f) if b.get(k) != f.get(k))
        extra = [k for k in diff if not _sequence_local(k)]
        assert not extra, (
            f"{name} 臂在 balloon 与 f3 之间存在非数据集差异 {extra} "
            "⇒ 跨序列比较混着配置差异，迁移判决不成立"
        )

    @pytest.mark.parametrize("name,stem", ARMS)
    def test_f3_arm_actually_points_at_f3(self, name, stem):
        cfg = load_config(f"{D}/{stem}_f3_wk_xyz.yaml")
        path = cfg["Dataset"]["dataset_path"]
        assert "freiburg3_walking_xyz" in path, f"{name} 臂数据集是 {path}"

    def test_dose_knobs_resolve_as_intended_on_f3(self):
        """四臂在 f3 上的剂量旋钮必须解析成预期值（否则读的不是设计的剂量）。"""
        expect = {
            "hard": dict(ema=False, mass=None, zero=None, cap=None),
            "zeromask": dict(ema=True, mass=True, zero=True, cap=None),
            "sm": dict(ema=True, mass=True, zero=False, cap=None),
            "cap05": dict(ema=True, mass=True, zero=False, cap=0.05),
        }
        for name, stem in ARMS:
            sm = load_config(f"{D}/{stem}_f3_wk_xyz.yaml")["SemanticMask"]
            e = expect[name]
            assert sm.get("mapping_ema") == e["ema"], name
            assert sm.get("mapping_ema_mass_match") == e["mass"], name
            assert sm.get("mapping_ema_zero_dynamic") == e["zero"], name
            assert sm.get("mapping_ema_dynamic_cap") == e["cap"], name

    @pytest.mark.parametrize("name,stem", ARMS)
    def test_mask_mapping_on_for_every_f3_arm(self, name, stem):
        """mask_mapping 必须在场——它是剂量旋钮的作用前提。"""
        sm = load_config(f"{D}/{stem}_f3_wk_xyz.yaml")["SemanticMask"]
        assert sm.get("enabled") is True, name
        assert sm.get("mask_mapping") is True, name

    def test_probe_enabled_so_gates_are_readable(self):
        """G-4/G-5 靠 probe 落盘；probe 关着门就没数据可读。"""
        for name, stem in ARMS:
            cfg = load_config(f"{D}/{stem}_f3_wk_xyz.yaml")
            assert cfg.get("MappingProbe", {}).get("enabled") is True, name

    def test_configs_exist(self):
        for _, stem in ARMS:
            assert Path(f"{D}/{stem}_f3_wk_xyz.yaml").exists(), stem
