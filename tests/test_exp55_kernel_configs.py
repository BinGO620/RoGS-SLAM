"""EXP55 kernel-ablation config contract (prereg §2/§4, frozen).

Pins:
  1. each run config inherits the correct dataset config and the correct EXP55
     method config, and the run name matches EXP55-Combined-<kernel>-<seq>;
  2. each EXP55 method config inherits the main-table combined-prune method base
     and overrides ONLY RobustTracking.kernel (cauchy / gm) — delta values and
     every other key stay at the base identity;
  3. the merged resolution of each run config carries kernel=<expected> and
     enabled=true (guards the silent all-ones-weight fallback for unknown
     kernel strings, prereg §4 E0).
"""
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP = "configs/rgbd/experiments/exp55_kernel_ablation"
BASE_METHOD = "configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml"

RUN_CONFIGS = {
    "exp55_cauchy_balloon.yaml": ("configs/rgbd/bonn/balloon.yaml", "cauchy", "balloon"),
    "exp55_gm_balloon.yaml": ("configs/rgbd/bonn/balloon.yaml", "gm", "balloon"),
    "exp55_cauchy_pt2.yaml": ("configs/rgbd/bonn/person_tracking2.yaml", "cauchy", "pt2"),
    "exp55_gm_pt2.yaml": ("configs/rgbd/bonn/person_tracking2.yaml", "gm", "pt2"),
}
METHOD_CONFIGS = {
    "method_combined_cauchy.yaml": "cauchy",
    "method_combined_gm.yaml": "gm",
}


def load(rel):
    with open(os.path.join(ROOT, rel)) as fh:
        return yaml.safe_load(fh)


def deep_inherit(rel, memo=None):
    """Resolve the inherit_from chain (dataset configs have no further parents in
    this repo's loader, but method_from is a separate single-level link)."""
    cfg = load(rel)
    parent = cfg.pop("inherit_from", None)
    if parent:
        memo = memo or {}
        base = deep_inherit(parent, memo)
        merged = dict(base)
        merged.update(cfg)
        return merged
    return cfg


def test_method_configs_override_only_kernel():
    base = load(BASE_METHOD)
    for rel, kernel in METHOD_CONFIGS.items():
        cfg = load(os.path.join(EXP, rel))
        assert cfg.get("inherit_from") == BASE_METHOD, f"{rel}: wrong inherit_from"
        # every top-level key except RobustTracking must be absent (single-knob)
        extra = set(cfg.keys()) - {"inherit_from", "RobustTracking"}
        assert not extra, f"{rel}: unexpected override keys {extra}"
        rt = cfg.get("RobustTracking", {})
        assert set(rt.keys()) == {"kernel"}, f"{rel}: RobustTracking must override only kernel"
        assert rt["kernel"] == kernel, f"{rel}: kernel must be {kernel}"


def test_run_configs_identity():
    for rel, (dataset, kernel, seq) in RUN_CONFIGS.items():
        cfg = load(os.path.join(EXP, rel))
        assert cfg["inherit_from"] == dataset, f"{rel}: wrong dataset"
        assert cfg["method_from"] == os.path.join(EXP, f"method_combined_{kernel}.yaml"), (
            f"{rel}: wrong method_from")
        assert cfg["method"] == f"EXP55-Combined-{kernel}-{seq}", f"{rel}: wrong run name"
        assert set(cfg.keys()) == {"inherit_from", "method_from", "method"}, (
            f"{rel}: run config must not add keys")


def test_resolved_kernel_reaches_merged_view():
    """The loader merges method_from over the dataset config; emulate that here so
    the test fails loudly if the key path changes (E0 silent-all-ones guard)."""
    for rel, (_, kernel, _) in RUN_CONFIGS.items():
        run = load(os.path.join(EXP, rel))
        method = load(run["method_from"])
        base = load(BASE_METHOD)
        merged_rt = {**base.get("RobustTracking", {}), **method.get("RobustTracking", {})}
        assert merged_rt["kernel"] == kernel, (
            f"{rel}: resolved kernel is {merged_rt['kernel']}, expected {kernel}")
        assert merged_rt["enabled"] is True, f"{rel}: RobustTracking must stay enabled"
        assert merged_rt["rgb_delta"] == 0.10 and merged_rt["depth_delta"] == 0.10, (
            f"{rel}: delta values must stay at base identity")
