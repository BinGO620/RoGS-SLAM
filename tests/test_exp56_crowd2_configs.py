"""EXP56 config contract: double-variable arm differs from Combined only in
mask_insertion; differs from EXP54 single-variable arms in exactly the second
component being enabled."""
import os, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = "configs/rgbd/experiments/exp56_crowd2_attribution/exp56_p11_dynkf_reliability_crowd2.yaml"
METHOD = "configs/rgbd/experiments/exp56_crowd2_attribution/method_p11_dynkf_reliability.yaml"
P11_BASE = "configs/rgbd/experiments/p11_maskonly/method_p11_maskonly.yaml"


def load(rel):
    with open(os.path.join(ROOT, rel)) as fh:
        return yaml.safe_load(fh)


def test_run_config_identity():
    cfg = load(RUN)
    assert cfg["inherit_from"] == "configs/rgbd/bonn/crowd2.yaml"
    assert cfg["method_from"] == METHOD
    assert cfg["method"] == "EXP56-P11-DynKF-Rel-crowd2"


def test_method_enables_exactly_two_components():
    cfg = load(METHOD)
    assert cfg.get("inherit_from") == P11_BASE
    assert cfg["DynamicKeyframe"]["enabled"] is True
    assert cfg["ReliabilitySignal"]["enabled"] is True
    extra = set(cfg.keys()) - {"inherit_from", "DynamicKeyframe", "ReliabilitySignal"}
    assert not extra, f"unexpected override keys: {extra}"


def test_p11_base_has_mask_insertion_off():
    base = load(P11_BASE)
    sm = base.get("SemanticMask", {})
    assert sm.get("mask_insertion") in (False, None), (
        "P11 base must keep mask_insertion off — it is the remaining Combined difference")
