"""WP-B flow-mask baseline config contract (CCF-C 整改执行卡 v3 §4 WP-B).

Asserts the flow-mask arm differs from the MRCS/mask-free backbone ONLY in the mask SOURCE:
  * SemanticMask.enabled:true + source:'flow_threshold' (vs mask-free enabled:false);
  * everything else (K/R/L, lifecycle prune, DeferredCommit, window/optimizer/…) byte-identical
    to the K1R1L1 (hero) / K0R0L0 (vanilla) WP-A cells.
Because the whole point of WP-B is 'the gain vs ANY anti-dynamic handling', the flow-mask arm
= vanilla (K0R0L0) + flow_threshold semantic mask, i.e. the most naive anti-dynamic addition.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from utils.config_utils import load_config  # noqa: E402

WPA = "configs/rgbd/experiments/wpa_factorial"
WPB = "configs/rgbd/experiments/wpb_flowmask"
VANILLA_ARM = f"{WPA}/method_mf_K0R0L0.yaml"  # vanilla (all mechanisms off)

IGNORED = {"inherit_from", "method_from", "method"}


def _flatten(n, p=""):
    o = {}
    if isinstance(n, dict):
        for k, v in n.items():
            o.update(_flatten(v, f"{p}{k}." if p else f"{k}."))
        return o
    o[p[:-1]] = n
    return o


class WpbFlowmaskConfigContract(unittest.TestCase):
    def test_flowmask_differs_from_vanilla_only_in_semanticmask(self):
        arm = load_config(f"{WPB}/flowmask_vanilla.yaml")
        vanilla = load_config(VANILLA_ARM)
        fa, fv = _flatten(arm), _flatten(vanilla)
        diffs = {
            k: (fv.get(k), fa.get(k))
            for k in sorted(set(fa) | set(fv))
            if k not in IGNORED and fa.get(k) != fv.get(k)
        }
        unexpected = {k: v for k, v in diffs.items()
                      if not k.startswith("SemanticMask.")}
        self.assertEqual(unexpected, {}, f"flowmask vs vanilla differs outside SemanticMask: {unexpected}")
        # flow-mask must enable mask + source flow_threshold; vanilla has SemanticMask off.
        sm = arm.get("SemanticMask", {})
        self.assertTrue(sm.get("enabled", False), "flow-mask must enable SemanticMask")
        self.assertEqual(sm.get("source", "maskrcnn"), "flow_threshold")

    def test_run_configs_resolve_seq_and_flowmask(self):
        seqs = ["mv_no_box", "balloon"]
        arm = _flatten(load_config(f"{WPB}/flowmask_vanilla.yaml"))
        for seq in seqs:
            run = _flatten(load_config(f"{WPB}/run_{seq}.yaml"))
            # dataset points at the seq
            self.assertIn("moving_nonobstructing_box" if seq=="mv_no_box" else seq, run.get("Dataset.dataset_path",""), f"{seq}: bad dataset")
            # K/R/L all OFF (vanilla + flow-mask), same as the arm
            for k in ("DynamicKeyframe.enabled", "RobustTracking.enabled", "ReliabilitySignal.enabled"):
                self.assertEqual(run.get(k), False, f"{seq}/{k}: must stay vanilla")
            # SemanticMask flow_threshold active
            self.assertTrue(run.get("SemanticMask.enabled") and run.get("SemanticMask.source") == "flow_threshold")
            # lifecycle prune, DeferredCommit same as WP-A K0R0L0
            self.assertEqual(run.get("Mapping.lifecycle_mode"), "prune")
            self.assertTrue(run.get("DeferredCommit.enabled"))


if __name__ == "__main__":
    unittest.main()
