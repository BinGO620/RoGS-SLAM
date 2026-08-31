"""EXP59 contract: 6 unseen sequences x 2 arms; combined/maskfree method bases."""
import os, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP = "configs/rgbd/experiments/exp59_boundary_validation"
SEQS = ["crowd3", "kidnapping_box", "kidnapping_box2",
        "balloon_tracking", "balloon_tracking2", "placing_nonobstructing_box"]


def load(rel):
    with open(os.path.join(ROOT, rel)) as fh:
        return yaml.safe_load(fh)


def test_all_configs_present_and_identity():
    for seq in SEQS:
        c = load(os.path.join(EXP, f"exp59_combined_{seq}.yaml"))
        m = load(os.path.join(EXP, f"exp59_maskfree_{seq}.yaml"))
        assert c["inherit_from"] == f"configs/rgbd/bonn/{seq}.yaml", seq
        assert c["method_from"].endswith("method_combined_maskboth_prune.yaml"), seq
        assert m["method_from"].endswith("method_combined_maskoff_prune.yaml"), seq
        assert c["method"] == f"EXP59-combined-{seq}"
        assert m["method"] == f"EXP59-maskfree-{seq}"


def test_dataset_yamls_exist():
    for seq in SEQS:
        p = os.path.join(ROOT, "configs", "rgbd", "bonn", f"{seq}.yaml")
        assert os.path.isfile(p), f"missing dataset yaml for {seq}"
        cfg = load(f"configs/rgbd/bonn/{seq}.yaml")
        assert "dataset_path" in str(cfg), seq
