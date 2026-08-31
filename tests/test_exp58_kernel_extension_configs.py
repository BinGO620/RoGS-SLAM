"""EXP58 contract: run configs inherit the right datasets and reuse the EXP55
method configs (kernel-only override). Resolved kernel must equal expected."""
import os, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP = "configs/rgbd/experiments/exp58_kernel_extension"
RUNS = {
    "exp58_cauchy_mv_no_box.yaml": ("configs/rgbd/bonn/moving_nonobstructing_box.yaml", "cauchy"),
    "exp58_gm_mv_no_box.yaml": ("configs/rgbd/bonn/moving_nonobstructing_box.yaml", "gm"),
    "exp58_cauchy_pt1.yaml": ("configs/rgbd/bonn/person_tracking.yaml", "cauchy"),
    "exp58_gm_pt1.yaml": ("configs/rgbd/bonn/person_tracking.yaml", "gm"),
    "exp58_cauchy_f3_wk_hf.yaml": ("configs/rgbd/tum/f3_wk_hf.yaml", "cauchy"),
    "exp58_gm_f3_wk_hf.yaml": ("configs/rgbd/tum/f3_wk_hf.yaml", "gm"),
    "exp58_cauchy_crowd.yaml": ("configs/rgbd/bonn/crowd.yaml", "cauchy"),
    "exp58_gm_crowd.yaml": ("configs/rgbd/bonn/crowd.yaml", "gm"),
}


def load(rel):
    with open(os.path.join(ROOT, rel)) as fh:
        return yaml.safe_load(fh)


def test_run_configs():
    for rel, (ds, kernel) in RUNS.items():
        cfg = load(os.path.join(EXP, rel))
        assert cfg["inherit_from"] == ds, rel
        assert cfg["method_from"].endswith(f"method_combined_{kernel}.yaml"), rel
        assert cfg["method"].startswith("EXP58-Combined-"), rel
        assert set(cfg.keys()) == {"inherit_from", "method_from", "method"}, rel


def test_reused_exp55_methods_unchanged():
    for k in ("cauchy", "gm"):
        m = load(f"configs/rgbd/experiments/exp55_kernel_ablation/method_combined_{k}.yaml")
        assert m["RobustTracking"] == {"kernel": k}, f"{k} method must stay kernel-only"
