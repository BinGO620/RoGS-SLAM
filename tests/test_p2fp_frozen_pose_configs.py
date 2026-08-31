"""E0 contract for the P2-T frozen-pose de-confounding control (config resolution only, CPU).

This control (``p2fp_combined_{prune,deferred}_pt1.yaml``) is NOT a main-table arm. It is the
mechanistic control that tests the hermes blind spot: on P2-T self-tracked pt1, coverage and
tracking-difficulty are collinear (pt1 is both high-coverage AND hard-tracking, near the MonoGS
tracking limit), so a reviewer can attribute deferred's ATE cost to tracking difficulty rather
than to the lifecycle. Freezing the pose (RGD injected trajectory + backend cam-lr=0) removes
tracking as a variable; the only remaining arm-discriminating channel is map admission /
densify / keyframing. See ``results/evidence/consult_synthesis_frozenpose.md``.

This contract pins, BEFORE any GPU:

  * **the only differences vs the self-tracked pt1 run config are the trajectory injection and
    the pose freeze** -- allowed diff EXACTLY {method, Oracle.pose_file,
    Training.lr.cam_rot_delta, Training.lr.cam_trans_delta}. Backbone and lifecycle are the
    self-tracked arm's, unchanged, so any frozen-pose map delta is attributable to the
    lifecycle, not to a tracking/masking/keyframing difference that travelled with it.
  * **the prune/deferred twin differs ONLY in lifecycle** -- allowed diff EXACTLY {method,
    Mapping.lifecycle_mode}. Same injected trajectory, same pose freeze, same backbone.
  * **the pose freeze is real** -- cam_rot_delta == cam_trans_delta == 0.0 on both arms (a
    non-zero cam-lr would let the backend re-optimise pose and re-introduce tracking).
  * **Oracle.pose_file exists on disk** (machine-local, gitignored data -- the existence check
    is skipped on machines without ``external_trajectories/``).
  * **the lifecycle is NOT prune on the deferred config and NOT deferred on the prune config**
    (a twin swap would silently make the "control" a self-comparison).

NOT asserted here: that the frozen-pose map-level contrast (G_def/G_prune + vac_depth/vac_psnr)
is non-zero. That is the experiment's question. This contract only guarantees the pair is
capable of answering it (one injected trajectory, real pose freeze, one lifecycle diff).

Correct-observable reminder (from consult_synthesis_frozenpose.md Q1): under Oracle.pose_file,
ATE is identical across arms BY CONSTRUCTION (oracle_pose.py + slam_frontend.py:905 set
oracle_skip at itr 0 and never touch R_gt/T_gt; R2-P01-E2 measured balloon frozen-pose ATE
2.0618 cm to 4 dp on BOTH arms ALL seeds). ATE here is a CANARY (= injected-tracker ATE +/-
0.02), NOT an outcome. The arm-discriminating observables are MAP-LEVEL: refined_num_gaussians
(G_def/G_prune) and the fidelity pair vac_depth / vac_psnr.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

P2 = "configs/rgbd/experiments/p2_render"

FP_PRUNE = f"{P2}/p2fp_combined_prune_pt1.yaml"
FP_DEFERRED = f"{P2}/p2fp_combined_deferred_pt1.yaml"
ST_PRUNE = f"{P2}/p2s_combined_prune_pt1.yaml"
ST_DEFERRED = f"{P2}/p2s_combined_deferred_pt1.yaml"

POSE_FILE = (
    "/data/monogs-ours/external_trajectories/rgd/bonn_person_tracking/seed_0/"
    "slam_outputs/Datasets_Bonn/2026-06-25-13-11-13/plot/trj_final.json"
)

# allowed diff: frozen-pose overlay vs self-tracked base = injection + pose freeze, nothing else
FP_VS_ST_ALLOWED = {
    "method",
    "Oracle.pose_file",
    "Training.lr.cam_rot_delta",
    "Training.lr.cam_trans_delta",
}
# allowed diff: prune vs deferred twin = lifecycle only
TWIN_ALLOWED = {"method", "Mapping.lifecycle_mode"}
IGNORED = {"inherit_from", "method_from"}


def _flatten(node, prefix=""):
    out = {}
    if isinstance(node, dict):
        for key, value in node.items():
            key_str = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                out.update(_flatten(value, key_str))
            else:
                out[key_str] = value
    else:
        out[prefix] = node
    return out


def _diff(a, b):
    fa, fb = _flatten(a), _flatten(b)
    keys = set(fa) | set(fb)
    return {k: (fa.get(k, "<missing>"), fb.get(k, "<missing>")) for k in keys if fa.get(k) != fb.get(k)}


class TestP2FPFrozenPoseConfigs(unittest.TestCase):
    def setUp(self):
        self.prune = load_config(FP_PRUNE)
        self.deferred = load_config(FP_DEFERRED)
        self.st_prune = load_config(ST_PRUNE)
        self.st_deferred = load_config(ST_DEFERRED)

    def test_overlay_vs_self_tracked_is_only_injection_and_freeze(self):
        """Frozen-pose vs self-tracked base: allowed diff = {method, pose_file, cam_lr}."""
        for fp, st, label in [
            (self.prune, self.st_prune, "prune"),
            (self.deferred, self.st_deferred, "deferred"),
        ]:
            diff = _diff(fp, st)
            extra = {k for k in diff if k not in FP_VS_ST_ALLOWED and k not in IGNORED}
            self.assertFalse(
                extra,
                f"frozen-pose {label} has diff vs self-tracked outside allowed "
                f"{FP_VS_ST_ALLOWED}: {extra} (full diff {diff})",
            )

    def test_twin_differs_only_in_lifecycle(self):
        """prune vs deferred twin (frozen-pose): allowed diff = {method, lifecycle_mode}."""
        diff = _diff(self.prune, self.deferred)
        extra = {k for k in diff if k not in TWIN_ALLOWED and k not in IGNORED}
        self.assertFalse(
            extra,
            f"frozen-pose twin has diff outside allowed {TWIN_ALLOWED}: {extra} (full {diff})",
        )
        self.assertEqual(self.prune["Mapping"]["lifecycle_mode"], "prune")
        self.assertEqual(self.deferred["Mapping"]["lifecycle_mode"], "deferred")

    def test_pose_freeze_is_real(self):
        """cam lr must be 0.0 on both arms (else backend re-optimises pose)."""
        for cfg, label in [(self.prune, "prune"), (self.deferred, "deferred")]:
            lr = cfg.get("Training", {}).get("lr", {})
            self.assertEqual(
                float(lr.get("cam_rot_delta", -1)), 0.0, f"{label} cam_rot_delta != 0"
            )
            self.assertEqual(
                float(lr.get("cam_trans_delta", -1)), 0.0, f"{label} cam_trans_delta != 0"
            )

    def test_pose_file_set_and_exists(self):
        """Oracle.pose_file is the RGD pt1 trajectory and is present on disk."""
        for cfg, label in [(self.prune, "prune"), (self.deferred, "deferred")]:
            pf = cfg.get("Oracle", {}).get("pose_file", "")
            self.assertTrue(pf, f"{label} has no Oracle.pose_file")
            self.assertEqual(pf, POSE_FILE, f"{label} pose_file is not the RGD pt1 trajectory")
            if os.path.isdir("/data/monogs-ours/external_trajectories"):
                self.assertTrue(os.path.isfile(pf), f"{label} pose_file does not exist: {pf}")

    def test_backbone_blocks_equal_between_twin_and_self_tracked(self):
        """Backbone blocks are copied from the self-tracked twin, not re-tuned."""
        blocks = (
            "SemanticMask", "RobustTracking", "DynamicKeyframe", "Training",
            "ReliabilitySignal", "TriReliability", "DeferredCommit",
        )
        for block in blocks:
            # frozen-pose prune backbone == self-tracked prune backbone (modulo the pose lr,
            # which is part of Training.lr and is allowed to differ for cam_*_delta only)
            fp_blk = _flatten(self.prune.get(block, {}))
            st_blk = _flatten(self.st_prune.get(block, {}))
            for k in set(fp_blk) | set(st_blk):
                if k.startswith("lr.cam_"):
                    continue  # pose freeze — allowed
                self.assertEqual(
                    fp_blk.get(k), st_blk.get(k),
                    f"prune backbone block {block}.{k} differs frozen-pose vs self-tracked",
                )
            fp_blk = _flatten(self.deferred.get(block, {}))
            st_blk = _flatten(self.st_deferred.get(block, {}))
            for k in set(fp_blk) | set(st_blk):
                if k.startswith("lr.cam_"):
                    continue
                self.assertEqual(
                    fp_blk.get(k), st_blk.get(k),
                    f"deferred backbone block {block}.{k} differs frozen-pose vs self-tracked",
                )


if __name__ == "__main__":
    unittest.main()
