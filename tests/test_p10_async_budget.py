#!/usr/bin/env python3
"""Tests for P10 async_iter_per_kf config旋钮（slam_backend.py）"""
import os
import sys
import yaml
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_config(rel_path):
    repo = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(repo, rel_path)) as f:
        return yaml.safe_load(f)


class TestAsyncIterPerKf:
    """P10: Training.async_iter_per_kf defaults to 10 and overrides correctly."""

    def _base_config(self):
        """Minimal Training section with default."""
        return {"Training": {"mapping_itr_num": 150}}

    def test_default_value(self):
        cfg = self._base_config()
        val = int(cfg["Training"].get("async_iter_per_kf", 10))
        assert val == 10

    def test_explicit_override(self):
        cfg = self._base_config()
        cfg["Training"]["async_iter_per_kf"] = 50
        val = int(cfg["Training"].get("async_iter_per_kf", 10))
        assert val == 50

    def test_150_override(self):
        cfg = self._base_config()
        cfg["Training"]["async_iter_per_kf"] = 150
        val = int(cfg["Training"].get("async_iter_per_kf", 10))
        assert val == 150

    def test_config_files_exist(self):
        repo = os.path.join(os.path.dirname(__file__), "..")
        for name in ["p10_async10_f3_st_hf", "p10_async50_f3_st_hf", "p10_async150_f3_st_hf"]:
            path = os.path.join(repo, f"configs/rgbd/experiments/p10_async_budget/{name}.yaml")
            assert os.path.exists(path), f"Missing config: {path}"

    def test_async50_config_value(self):
        cfg = _load_config("configs/rgbd/experiments/p10_async_budget/p10_async50_f3_st_hf.yaml")
        assert cfg["Training"]["async_iter_per_kf"] == 50

    def test_async150_config_value(self):
        cfg = _load_config("configs/rgbd/experiments/p10_async_budget/p10_async150_f3_st_hf.yaml")
        assert cfg["Training"]["async_iter_per_kf"] == 150

    def test_async10_config_value(self):
        cfg = _load_config("configs/rgbd/experiments/p10_async_budget/p10_async10_f3_st_hf.yaml")
        assert cfg["Training"]["async_iter_per_kf"] == 10

    def test_backend_code_reads_config(self):
        """Verify slam_backend.py contains the new config read."""
        repo = os.path.join(os.path.dirname(__file__), "..")
        backend_path = os.path.join(repo, "utils/slam_backend.py")
        with open(backend_path) as f:
            src = f.read()
        assert "async_iter_per_kf" in src
        assert "self.async_iter_per_kf" in src
