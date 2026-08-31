"""E0 contract for WP-A FACTORIAL (CCF-C 整改执行卡 v3, 2026-08-14): the 8-arm full
factorial on the mask-free MRCS backbone must differ ONLY in the three mechanism
booleans K=DynamicKeyframe / R=RobustTracking / L=ReliabilitySignal.

Target (R1 后半): RT & Reliability were never individually ablated on the mask-free
skeleton (historical RT-off was flat because the semantic mask was present and swallowed
the effect; P6 gives the mechanism). The full factorial answers: are the three components
JOINTLY necessary at the full config, or redundant?

Contract asserts (per NEXT_SESSION_PROMPT WP-A):
  * All 8 cells share the SAME mask-free skeleton (SemanticMask.enabled:false) —
    no cell may introduce the semantic mask;
  * ONLY the three booleans (+ the pinned DeferredCommit trim) may differ between cells;
  * The fixed constants are byte-identical across all 8 cells: Mapping.lifecycle_mode=prune,
    TriReliability.enabled=false, window/pose_window, densify/prune knobs, ReliabilitySignal
    non-mode knobs, Training, Optimizer … — inherited verbatim from the mask-free backbone;
  * DeferredCommit is pinned to enabled:true + reliability_confirm:true on ALL cells
    (so the L=0/1 confirmation-path coupling is uniform; E0 dry-run proves behavioral
    parity, machine-checked here only at config level).
  * Every run config = a (seq, arm) overlay: seq dataset + one method arm, nothing else.

Companion runtime gate (not auto-asserted here, must be done on the first dry-run):
G3 activity gate — each enabled mechanism must have console evidence, each disabled one
must not; L=0/1 DeferredCommit confirmation path must behave identically (see prereg §2).
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from utils.config_utils import load_config  # noqa: E402

WPA = "configs/rgbd/experiments/wpa_factorial"
MASKFREE = "configs/rgbd/experiments/active/candidate/method_combined_maskoff_prune.yaml"

# 5 sequences (easy→hard; C3 made 4→5 by adding pt1). mv_no_box = pure-object easy;
# mv_no_box2 = pure-object reproduce easy; pt2 = easy-person medium; balloon = mixed medium;
# pt1 = hard person (known boundary failure).
SEQS = {
    "mv_no_box": "configs/rgbd/bonn/moving_nonobstructing_box.yaml",
    "mv_no_box2": "configs/rgbd/bonn/moving_nonobstructing_box2.yaml",
    "pt2": "configs/rgbd/bonn/person_tracking2.yaml",
    "balloon": "configs/rgbd/bonn/balloon.yaml",
    "pt1": "configs/rgbd/bonn/person_tracking.yaml",
}
ARMS = ["K0R0L0", "K1R1L1", "K0R1L1", "K1R0L1", "K1R1L0", "K0R1L0", "K0R0L1", "K1R0L0"]

# K/R/L booleans per arm, in "DRL" position order → arm→(K,R,L)
ARM_FLAGS = {
    "K0R0L0": (0, 0, 0),
    "K1R1L1": (1, 1, 1),
    "K0R1L1": (0, 1, 1),
    "K1R0L1": (1, 0, 1),
    "K1R1L0": (1, 1, 0),
    "K0R1L0": (0, 1, 0),
    "K0R0L1": (0, 0, 1),
    "K1R0L0": (1, 0, 0),
}

# Config keys the arms are ALLOWED to differ on (the two carrier fields + booleans + the
# pinned DeferredCommit trim which is uniform — so effectively only the booleans + mode).
ALLOWED_DIFF = {
    "DynamicKeyframe.enabled",
    "RobustTracking.enabled",
    "ReliabilitySignal.enabled",
    "ReliabilitySignal.mode",  # reserved for a future cue arm; not used here
}

IGNORED_KEYS = {"inherit_from", "method_from", "method"}

FIXED_CONSTANTS = {
    # these must be IDENTICAL across all 8 cells (the factorial is over K/R/L only)
    "SemanticMask.enabled": False,           # mask-free whole campaign
    "Mapping.lifecycle_mode": "prune",       # prune lifecycle whole campaign
    "TriReliability.enabled": False,         # old V1 signal off whole campaign
    "DeferredCommit.enabled": True,          # pinned uniform (coupling, see prereg)
    "DeferredCommit.reliability_confirm": True,
}


def _flatten(node, prefix=""):
    out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(_flatten(v, f"{prefix}{k}." if prefix else f"{k}."))
        return out
    out[prefix[:-1]] = node
    return out


def resolve_config(path):
    cfg = load_config(path)
    return _flatten(cfg)


def _resolve(path):
    """Module-level flatten (callable by the class without ``self`` ambiguity)."""
    return resolve_config(path)


class WpaFactorialConfigContract(unittest.TestCase):
    def setUp(self):
        self.maskfree = resolve_config(MASKFREE)
        self.arms = {}
        for arm in ARMS:
            self.arms[arm] = resolve_config(
                f"{WPA}/method_mf_{arm}.yaml"
            )

    def _diff(self, arm_flat, base_flat):
        diffs = {}
        for k in sorted(set(arm_flat) | set(base_flat)):
            if k in IGNORED_KEYS:
                continue
            if arm_flat.get(k) != base_flat.get(k):
                diffs[k] = (base_flat.get(k), arm_flat.get(k))
        return diffs

    def _diff_excluding_mechanics(self, arm_flat, base_flat):
        """Diff ignoring the three mechanism booleans + their cue/mode subkeys (we assert
        those separately), used to prove the cells share everything else."""
        return {
            k: v for k, v in self._diff(arm_flat, base_flat).items()
            if k not in ALLOWED_DIFF
        }

    def test_all_arms_share_maskfree_skeleton(self):
        """(1) Every arm resolves the mask-free skeleton: only K/R/L booleans + pinned
        DeferredCommit may deviate from the full mask-free config."""
        for arm in ARMS:
            flat = self.arms[arm]
            diffs = self._diff(flat, self.maskfree)
            # Drop the three booleans from the diff; what is left must be empty.
            unexpected = {
                k: v for k, v in diffs.items()
                if k not in ALLOWED_DIFF
            }
            self.assertEqual(
                unexpected, {},
                f"{arm} must differ from mask-free only in K/R/L booleans; extra: {unexpected}",
            )

    def test_fixed_constants_identical_across_arms(self):
        """(2) SemanticMask off, lifecycle prune, TriReliability off, DeferredCommit
        pinned on across ALL 8 cells."""
        ref = self.arms["K1R1L1"]
        for arm in ARMS:
            flat = self.arms[arm]
            for key, want in FIXED_CONSTANTS.items():
                self.assertEqual(
                    flat.get(key), want,
                    f"{arm}: fixed constant {key} = {flat.get(key)!r}, want {want!r}",
                )
                self.assertEqual(
                    ref.get(key), want,
                    f"K1R1L1: fixed constant {key} leaked: {ref.get(key)!r}",
                )

    def test_each_arm_has_exact_three_boolean_signature(self):
        """(3) Each arm resolves exactly its declared (K,R,L) signature and the mask-free
        skeleton sets mask-free + prune lifecycle."""
        for arm, (k, r, l) in ARM_FLAGS.items():
            flat = self.arms[arm]
            self.assertEqual(bool(flat["DynamicKeyframe.enabled"]), bool(k), arm)
            self.assertEqual(bool(flat["RobustTracking.enabled"]), bool(r), arm)
            self.assertEqual(bool(flat["ReliabilitySignal.enabled"]), bool(l), arm)
            self.assertEqual(flat["SemanticMask.enabled"], False, arm)
            self.assertEqual(flat["Mapping.lifecycle_mode"], "prune", arm)

    def test_hero_arm_equals_maskfree_full(self):
        """K1R1L1 must resolve byte-identical to the mask-free backbone (the complete
        method), other than the inherited carrier fields."""
        self.assertEqual(
            self._diff_excluding_mechanics(self.arms["K1R1L1"], self.maskfree), {},
            "K1R1L1 must be byte-identical to the mask-free backbone",
        )

    def test_2x2_legacy_cells_diff(self):
        """The P-B legacy cells did not exist as method files — verify each arm is a
        DISTINCT config (not a duplicate)."""
        sigs = {
            arm: (self.arms[arm]["DynamicKeyframe.enabled"],
                  self.arms[arm]["RobustTracking.enabled"],
                  self.arms[arm]["ReliabilitySignal.enabled"])
            for arm in ARMS
        }
        self.assertEqual(len(set(sigs.values())), 8, "arms must be 8 distinct cells")

    def test_every_run_config_resolves_seq_and_arm(self):
        """(4) Each of the 40 run configs = one seq + one arm. On a run overlay the seq
        inherit legitimately adds the Bonn Dataset/Calibration/base blocks; what we pin is
        that (a) it points at the intended seq, and (b) its K/R/L booleans + mask-free +
        prune match the declared arm. The invariant that all cells share the seq blocks
        exactly (i.e. only the arm booleans differ) is deferred to test_same_seq_runs_*."""
        ARM_BAD = {
            "K0R0L0": (0, 0, 0), "K1R1L1": (1, 1, 1), "K0R1L1": (0, 1, 1),
            "K1R0L1": (1, 0, 1), "K1R1L0": (1, 1, 0), "K0R1L0": (0, 1, 0),
            "K0R0L1": (0, 0, 1), "K1R0L0": (1, 0, 0),
        }
        for seq, seq_cfg in SEQS.items():
            for arm in ARMS:
                run = resolve_config(f"{WPA}/wpa_{seq}_{arm}.yaml")
                # dataset points at the right sequence
                self.assertIn(
                    seq_cfg.split("/")[-1].replace(".yaml", ""),
                    run["Dataset.dataset_path"],
                    f"{seq}/{arm}: wrong dataset",
                )
                k, r, l = ARM_BAD[arm]
                self.assertEqual(bool(run["DynamicKeyframe.enabled"]), bool(k), f"{seq}/{arm}: K")
                self.assertEqual(bool(run["RobustTracking.enabled"]), bool(r), f"{seq}/{arm}: R")
                self.assertEqual(bool(run["ReliabilitySignal.enabled"]), bool(l), f"{seq}/{arm}: L")
                self.assertFalse(run["SemanticMask.enabled"], f"{seq}/{arm}: must be mask-free")
                self.assertEqual(run["Mapping.lifecycle_mode"], "prune", f"{seq}/{arm}")

    def test_same_seq_runs_differ_only_by_arm(self):
        """(5) Two run overlays on the same seq must differ ONLY in the three booleans
        (plus carrier) — i.e. all cells on a sequence share the seq blocks exactly."""
        import itertools
        for seq in SEQS:
            pairs = list(itertools.combinations(ARMS, 2))
            for a, b in pairs:
                fa = resolve_config(f"{WPA}/wpa_{seq}_{a}.yaml")
                fb = resolve_config(f"{WPA}/wpa_{seq}_{b}.yaml")
                diff = self._diff(fa, fb)
                disallowed = {
                    k: v for k, v in diff.items()
                    if k not in ALLOWED_DIFF and k not in IGNORED_KEYS
                }
                self.assertEqual(
                    disallowed, {},
                    f"{seq}: {a} vs {b} share identical seq blocks but differ in {disallowed}",
                )


if __name__ == "__main__":
    unittest.main()
