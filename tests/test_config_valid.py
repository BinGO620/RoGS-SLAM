#!/usr/bin/env python
"""test_config_valid.py — L1 config 门禁

验证 configs/experiments/ 下所有实验 config 能否正确加载、必要字段齐全、数据集路径存在。

用法: pytest tests/test_config_valid.py -v
"""
import os
from pathlib import Path

import pytest
import yaml

# 所有实验 config 目录
EXPERIMENTS_DIR = Path("configs/experiments")

# 继承链上的 base config（相对项目根）
BASE_CONFIGS = [
    "configs/rgbd/tum/base_config.yaml",
    "configs/rgbd/bonn/base_config.yaml",
]

# 必须存在的顶层字段
REQUIRED_TOP_FIELDS = ["Dataset", "Training", "Results"]

# Dataset 下必须存在的字段（type 等由 base config 提供，实验 config 不需显式定义）
REQUIRED_DATASET_FIELDS = ["dataset_path"]


def find_experiment_configs():
    """发现 configs/experiments/ 下的序列级 config（排除纯 method overlay）"""
    configs = []
    if not EXPERIMENTS_DIR.exists():
        return configs
    for yaml_file in sorted(EXPERIMENTS_DIR.rglob("*.yaml")):
        # method overlay 文件没有 inherit_from，跳过
        with open(yaml_file) as f:
            cfg = yaml.full_load(f)
        if cfg and cfg.get("inherit_from"):
            configs.append(yaml_file)
    return configs


def load_config_with_inherit(path, _seen=None):
    """模拟 config_utils.load_config 的继承逻辑（递归）"""
    if _seen is None:
        _seen = set()
    # 用相对于项目根的路径做去重
    norm = str(Path(path))
    if norm in _seen:
        return {}
    _seen.add(norm)

    with open(path) as f:
        cfg = yaml.full_load(f)
    if cfg is None:
        cfg = {}

    inherit_from = cfg.pop("inherit_from", None)
    method_from = cfg.pop("method_from", None)
    cfg.pop("method", None)

    if inherit_from:
        base = load_config_with_inherit(inherit_from, _seen)
        if method_from:
            method_cfg = load_config_with_inherit(method_from, _seen)
            base.update(method_cfg)
        base.update(cfg)
        return base
    return cfg


class TestBaseConfigs:
    """验证 base config 存在且可加载"""

    @pytest.mark.parametrize("config_path", BASE_CONFIGS)
    def test_base_config_exists(self, config_path):
        assert Path(config_path).exists(), f"base config 不存在: {config_path}"

    @pytest.mark.parametrize("config_path", BASE_CONFIGS)
    def test_base_config_loadable(self, config_path):
        with open(config_path) as f:
            cfg = yaml.full_load(f)
        assert isinstance(cfg, dict), f"config 不是 dict: {config_path}"


class TestExperimentConfigs:
    """验证实验 config 可加载、字段完整、数据集路径存在"""

    @pytest.fixture
    def experiment_configs(self):
        return find_experiment_configs()

    def test_has_experiment_configs(self, experiment_configs):
        assert len(experiment_configs) > 0, "configs/experiments/ 下没有找到任何 .yaml"

    def test_all_configs_loadable(self, experiment_configs):
        """所有实验 config 能通过继承链加载"""
        errors = []
        for cfg_path in experiment_configs:
            try:
                load_config_with_inherit(cfg_path)
            except Exception as e:
                errors.append(f"{cfg_path}: {e}")
        assert not errors, "以下 config 加载失败:\n" + "\n".join(errors)

    def test_required_top_fields(self, experiment_configs):
        """所有实验 config 包含必要顶层字段"""
        errors = []
        for cfg_path in experiment_configs:
            cfg = load_config_with_inherit(cfg_path)
            missing = [f for f in REQUIRED_TOP_FIELDS if f not in cfg]
            if missing:
                errors.append(f"{cfg_path}: 缺少 {missing}")
        assert not errors, "以下 config 缺少必要字段:\n" + "\n".join(errors)

    def test_dataset_path_exists(self, experiment_configs):
        """所有实验 config 的数据集路径存在（兼容大小写软链接）"""
        errors = []
        for cfg_path in experiment_configs:
            cfg = load_config_with_inherit(cfg_path)
            ds_cfg = cfg.get("Dataset", {})
            ds_path = ds_cfg.get("dataset_path")
            if ds_path:
                p = Path(ds_path)
                if not p.exists():
                    # 尝试逐级大小写匹配
                    parts = list(p.parts)
                    resolved = Path("")
                    failed = False
                    for part in parts:
                        if resolved.exists() and part.lower() in [f.name.lower() for f in resolved.iterdir()]:
                            match = [f for f in resolved.iterdir() if f.name.lower() == part.lower()][0]
                            resolved = match
                        elif resolved.exists() / part:
                            resolved = resolved / part
                        else:
                            failed = True
                            break
                    if failed or not resolved.exists():
                        errors.append(f"{cfg_path}: dataset_path 不存在: {ds_path}")
        assert not errors, "以下 config 的数据集路径不存在:\n" + "\n".join(errors)

    def test_dataset_fields_complete(self, experiment_configs):
        """所有实验 config 的 Dataset 字段完整"""
        errors = []
        for cfg_path in experiment_configs:
            cfg = load_config_with_inherit(cfg_path)
            ds_cfg = cfg.get("Dataset", {})
            missing = [f for f in REQUIRED_DATASET_FIELDS if f not in ds_cfg]
            if missing:
                errors.append(f"{cfg_path}: Dataset 缺少 {missing}")
        assert not errors, "以下 config 的 Dataset 字段不完整:\n" + "\n".join(errors)
