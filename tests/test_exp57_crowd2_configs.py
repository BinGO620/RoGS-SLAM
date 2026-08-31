"""EXP57 config contract: mask_insertion is the only override on the P11 base."""
import os, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = "configs/rgbd/experiments/exp57_crowd2_attribution/exp57_p11_mask_insertion_crowd2.yaml"
METHOD = "configs/rgbd/experiments/exp57_crowd2_attribution/method_p11_mask_insertion.yaml"
P11_BASE = "configs/rgbd/experiments/p11_maskonly/method_p11_maskonly.yaml"


def load(rel):
    with open(os.path.join(ROOT, rel)) as fh:
        return yaml.safe_load(fh)


def test_run_config_identity():
    cfg = load(RUN)
    assert cfg["inherit_from"] == "configs/rgbd/bonn/crowd2.yaml"
    assert cfg["method_from"] == METHOD
    assert cfg["method"] == "EXP57-P11-MaskIns-crowd2"


def test_method_overrides_only_mask_insertion():
    cfg = load(METHOD)
    assert cfg.get("inherit_from") == P11_BASE
    assert cfg["SemanticMask"]["mask_insertion"] is True
    extra = set(cfg.keys()) - {"inherit_from", "SemanticMask"}
    assert not extra, f"unexpected keys: {extra}"
    # DynKF / Reliability must NOT be overridden (stay off via P11 base)
    assert "DynamicKeyframe" not in cfg
    assert "ReliabilitySignal" not in cfg


def test_p11_base_components_off():
    base = load(P11_BASE)
    assert base.get("DynamicKeyframe", {}).get("enabled", False) is False
    assert base.get("ReliabilitySignal", {}).get("enabled", False) is False
