"""E0 contract for P7 CUE-SPLIT: ReliabilitySignal cue split (flow-only / geometry-only)
is the ONLY difference from the mask-free backbone.

P7 (method-open, 2026-08-13, transferred from ours-method) reopens the method decision
that the fixed multiplicative fusion ``s=(1-e_flow)(1-v*g)`` in ReliabilitySignal is NOT
a universally-correct kernel. ours-method's cue-split (seed-0 / mask-free / prune / `--fast`)
showed regime dependence: pure-object / pure-person prefer geometry, balloon prefers flow,
and ``both`` genuinely regresses on mv_no_box2 (5.68 -> 12.72 cm). This contract pins that
BOTH arms (flow-only, geometry-only) resolve to the EXACT mask-free backbone, differing only
in ``ReliabilitySignal.mode``, so any ATE difference can be attributed to the cue alone.

It asserts:
  * flow-only resolves to the maskfree backbone + ReliabilitySignal.mode=="flow-only" (and
    SemanticMask stays off — these are mask-free kernel arms, not combined);
  * geometry-only symmetric;
  * the disabled control resolves to ReliabilitySignal.enabled==false on the same backbone;
  * every per-sequence screen config resolves its dataset + one of the four method arms
    (on-default / flow / geo / off) with nothing else deviating from mask-free.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

CAND = "configs/rgbd/experiments/active/candidate"
P7 = "configs/rgbd/experiments/p7_cuesplit"

METHOD_MASKFREE = f"{CAND}/method_combined_maskoff_prune.yaml"
FLOW_ONLY = f"{P7}/reliability_flow_only.yaml"
GEO_ONLY = f"{P7}/reliability_geo_only.yaml"
OFF_BODY = f"{P7}/reliability_screen_off_body.yaml"

SEQS = {
    "balloon": "configs/rgbd/bonn/balloon.yaml",
    "mv_no_box": "configs/rgbd/bonn/moving_nonobstructing_box.yaml",
    "mv_no_box2": "configs/rgbd/bonn/moving_nonobstructing_box2.yaml",
    "pt2": "configs/rgbd/bonn/person_tracking2.yaml",
}
MODE_ARMS = {"on": "", "flow": "flow-only", "geo": "geometry-only", "off": None}

IGNORED = {"inherit_from", "method_from", "method", "ReliabilitySignal.enabled",
           "ReliabilitySignal.mode"}

ALLOWED_REL_DIFFS = {"ReliabilitySignal.enabled", "ReliabilitySignal.mode"}


def _flatten(node, prefix=""):
    out = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}{key}." if prefix else f"{key}."))
        return out
    out[prefix[:-1]] = node
    return out


def _diff_keys(cfg_a, cfg_b):
    flat_a, flat_b = _flatten(cfg_a), _flatten(cfg_b)
    keys_a, keys_b = set(flat_a), set(flat_b)
    diffs = {}
    for key in sorted(keys_a | keys_b):
        if key in IGNORED:
            continue
        if flat_a.get(key) != flat_b.get(key):
            diffs[key] = (flat_a.get(key), flat_b.get(key))
    return diffs


def filter_overlay(cfg):
    """Return the keys this overlay explicitly set (i.e. not default-inherited), for
    the 'both' arm assertion that it must NOT pin mode."""
    out = set()
    def walk(node, prefix=""):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{prefix}{key}." if prefix else f"{key}.")
        else:
            out.add(prefix[:-1])
    walk(cfg)
    return out


class P7CueSplitConfigContract(unittest.TestCase):
    def setUp(self):
        self.base = load_config(METHOD_MASKFREE)

    def test_filter_overlay_returns_dotted_paths(self):
        """Guard the guard. `filter_overlay` returns PREFIXED paths, so asserting on a
        bare leaf name ('mode') is vacuously true no matter what the config says -- the
        default-arm assertion below sat green and inert on that bug. Pin the contract so
        the same class of dead assertion cannot come back silently."""
        keys = filter_overlay({"ReliabilitySignal": {"mode": "flow-only"}})
        self.assertIn("ReliabilitySignal.mode", keys)
        self.assertNotIn("mode", keys)

    def test_flow_only_overlay_is_detected_by_the_guard(self):
        """Positive control: the assertion used by the default arm must FIRE on an
        overlay that does pin the mode."""
        self.assertIn("ReliabilitySignal.mode", filter_overlay(load_config(FLOW_ONLY)))

    def test_maskfree_backbone_no_semantic_mask(self):
        """The mask-free backbone must keep SemanticMask off (these are kernel arms)."""
        self.assertFalse(self.base.get("SemanticMask", {}).get("enabled", True))
        self.assertTrue(self.base.get("ReliabilitySignal", {}).get("enabled", False))

    def _assert_only_reliability_diff(self, cfg, label):
        diff = _diff_keys(cfg, self.base)
        disallowed = {k: v for k, v in diff.items() if k not in ALLOWED_REL_DIFFS}
        self.assertEqual(
            disallowed, {},
            f"{label} must differ only in ReliabilitySignal: {diff}",
        )

    def test_flow_only_isolates_cue(self):
        flow = load_config(FLOW_ONLY)
        self._assert_only_reliability_diff(flow, "flow-only")
        self.assertEqual(flow["ReliabilitySignal"]["enabled"], True)
        self.assertEqual(flow["ReliabilitySignal"]["mode"], "flow-only")

    def test_geometry_only_isolates_cue(self):
        geo = load_config(GEO_ONLY)
        self._assert_only_reliability_diff(geo, "geometry-only")
        self.assertEqual(geo["ReliabilitySignal"]["enabled"], True)
        self.assertEqual(geo["ReliabilitySignal"]["mode"], "geometry-only")

    def test_off_control_disables_reliability(self):
        off = load_config(OFF_BODY)
        self._assert_only_reliability_diff(off, "off body")
        self.assertEqual(off["ReliabilitySignal"]["enabled"], False)

    def test_each_screen_resolves_dataset_and_mode(self):
        for seq, seq_cfg in SEQS.items():
            for mode_name in MODE_ARMS:
                cfg = load_config(f"{P7}/screen_{seq}_{mode_name}.yaml")
                # dataset resolves to the intended sequence (relative path tail)
                self.assertTrue(
                    seq_cfg.split("/")[-1].replace(".yaml", "") in cfg["Dataset"]["dataset_path"],
                    f"{seq}/{mode_name}: dataset mismatch {cfg['Dataset']['dataset_path']}",
                )
                rel = cfg["ReliabilitySignal"]
                want = MODE_ARMS[mode_name]
                if want is None:
                    self.assertFalse(rel.get("enabled", True), f"{seq}/{mode_name}: should be disabled")
                elif want == "":
                    # default 'both'': enabled with no explicit mode (byte-identical historic)
                    self.assertTrue(rel.get("enabled", False), f"{seq}/{mode_name}: should be enabled")
                    self.assertNotIn("ReliabilitySignal.mode", filter_overlay(cfg),
                                     f"{seq}/{mode_name}: default arm must not set mode")
                else:
                    self.assertTrue(rel.get("enabled", False), f"{seq}/{mode_name}: should be enabled")
                    self.assertEqual(rel.get("mode"), want, f"{seq}/{mode_name}: bad mode")
                self.assertFalse(cfg["SemanticMask"]["enabled"],
                                 f"{seq}/{mode_name}: should stay mask-free")


if __name__ == "__main__":
    unittest.main()
