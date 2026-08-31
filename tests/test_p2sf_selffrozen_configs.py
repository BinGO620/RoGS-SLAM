"""E0 contract for the P2-SF self-frozen de-confounding control (config resolution, CPU).

This control (``p2sf_{b,c}_{prune,deferred}_{pt1,balloon2}.yaml``) is NOT a main-table arm.
It is the self-frozen de-confounding control that replaces the failed RGD frozen-pose (which
couldn't verify frame correspondence). See ``results/evidence/consult_synthesis_selffrozen.md``
+ ``p2sf_selffrozen_prereg.md``.

Two variants:
  * **C (primary, prune-trajectory injection)**: both arms frozen on the prune arm's OWN
    self-tracked trajectory (``trj_full_final.json`` from the P2-T prune run). Fully symmetric
    pair, same injected trajectory, only lifecycle differs. Frame correspondence 100%
    verifiable (trj_gt = dataset GT by construction, anchor ~0). Selection-bias: the
    trajectory is post-treatment (prune-conditioned), bounded + sign-unpredictable.
  * **B (sensitivity, GT-pose)**: both arms frozen on dataset GT (``Oracle.gt_pose: true``).
    codex's causally-cleanest option but hermes's regime-shift concern (perfect pose may
    suppress the pose-map-feedback channel being tested) -> B is a sensitivity footnote,
    NOT the branch. C carries the prereg branch decision.

This contract pins, BEFORE any GPU:

  * **variant C base configs carry the sentinel ``__PRUNE_TRAJ__``** (not a real path) —
    direct slam.py invocation must FAIL; only the runner (``scripts/r2_p2_sf.py``) resolves
    it per (seq, seed) to the actual ``trj_full_final.json``;
  * **variant B base configs carry ``Oracle.gt_pose: true`` and NO ``pose_file``** —
    exogenous GT, not seed-specific;
  * **both variants: the only diff vs the self-tracked run config is the trajectory injection
    / pose freeze** — allowed diff EXACTLY {method, Oracle.pose_file OR Oracle.gt_pose,
    Training.lr.cam_rot_delta, Training.lr.cam_trans_delta};
  * **the prune/deferred twin differs ONLY in lifecycle** — allowed diff {method,
    Mapping.lifecycle_mode};
  * **the pose freeze is real** — cam_rot_delta == cam_trans_delta == 0.0 on both arms;
  * **variant C's resolved pose_file source exists** (the P2-T prune run's
    trj_full_final.json, per seed) — checked for all (pt1, balloon2) × seeds 0/1/2 when the
    P2-T prune runs exist.

NOT asserted: that the map-level contrast (R_G^F + vac_depth/vac_psnr) is non-zero. That is
the experiment's question. ATE is a canary (identical across arms by construction under both
variants), NOT an outcome.
"""

import glob
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

P2 = "configs/rgbd/experiments/p2_render"
P2T = "results/runs/P2/P2-T"

SENTINEL = "__PRUNE_TRAJ__"

# (variant, arm, seq) -> base config path
C_CONFIGS = {
    ("c", "prune", "pt1"): f"{P2}/p2sf_c_prune_pt1.yaml",
    ("c", "deferred", "pt1"): f"{P2}/p2sf_c_deferred_pt1.yaml",
    ("c", "prune", "balloon2"): f"{P2}/p2sf_c_prune_balloon2.yaml",
    ("c", "deferred", "balloon2"): f"{P2}/p2sf_c_deferred_balloon2.yaml",
}
B_CONFIGS = {
    ("b", "prune", "pt1"): f"{P2}/p2sf_b_prune_pt1.yaml",
    ("b", "deferred", "pt1"): f"{P2}/p2sf_b_deferred_pt1.yaml",
    ("b", "prune", "balloon2"): f"{P2}/p2sf_b_prune_balloon2.yaml",
    ("b", "deferred", "balloon2"): f"{P2}/p2sf_b_deferred_balloon2.yaml",
}
ST_CONFIGS = {  # self-tracked base for the overlay diff
    ("prune", "pt1"): f"{P2}/p2s_combined_prune_pt1.yaml",
    ("deferred", "pt1"): f"{P2}/p2s_combined_deferred_pt1.yaml",
    ("prune", "balloon2"): f"{P2}/p2s_combined_prune_balloon2.yaml",
    ("deferred", "balloon2"): f"{P2}/p2s_combined_deferred_balloon2.yaml",
}

# allowed overlay diff (frozen vs self-tracked) = injection + pose freeze
FP_VS_ST_ALLOWED = {
    "method",
    "Oracle.pose_file",
    "Oracle.gt_pose",
    "Training.lr.cam_rot_delta",
    "Training.lr.cam_trans_delta",
}
# allowed twin diff (prune vs deferred, same variant) = lifecycle only
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


class TestP2SFConfigs(unittest.TestCase):
    def test_c_configs_carry_sentinel_pose_file(self):
        for (v, arm, seq), path in C_CONFIGS.items():
            cfg = load_config(path)
            pf = cfg.get("Oracle", {}).get("pose_file", "")
            self.assertEqual(pf, SENTINEL, f"{v}/{arm}/{seq} pose_file != sentinel: {pf}")
            # variant C must NOT enable gt_pose (default false is fine; true is not)
            self.assertFalse(cfg.get("Oracle", {}).get("gt_pose", False),
                             f"{v}/{arm}/{seq} must not enable gt_pose")

    def test_b_configs_carry_gt_pose_no_pose_file(self):
        for (v, arm, seq), path in B_CONFIGS.items():
            cfg = load_config(path)
            self.assertTrue(cfg.get("Oracle", {}).get("gt_pose", False),
                            f"{v}/{arm}/{seq} gt_pose not true")
            # variant B must NOT set a real pose_file (empty default is fine; a path is not)
            pf = cfg.get("Oracle", {}).get("pose_file", "")
            self.assertFalse(pf, f"{v}/{arm}/{seq} must not set a pose_file (B uses GT): {pf}")

    def test_pose_freeze_real_both_variants(self):
        for configs in (C_CONFIGS, B_CONFIGS):
            for (v, arm, seq), path in configs.items():
                cfg = load_config(path)
                lr = cfg.get("Training", {}).get("lr", {})
                self.assertEqual(float(lr.get("cam_rot_delta", -1)), 0.0,
                                 f"{v}/{arm}/{seq} cam_rot_delta != 0")
                self.assertEqual(float(lr.get("cam_trans_delta", -1)), 0.0,
                                 f"{v}/{arm}/{seq} cam_trans_delta != 0")

    def test_overlay_vs_self_tracked_is_only_injection_and_freeze(self):
        """frozen vs self-tracked base: allowed diff = {method, pose_file/gt_pose, cam_lr}."""
        for (v, arm, seq), path in {**C_CONFIGS, **B_CONFIGS}.items():
            fp = load_config(path)
            st = load_config(ST_CONFIGS[(arm, seq)])
            diff = _diff(fp, st)
            extra = {k for k in diff if k not in FP_VS_ST_ALLOWED and k not in IGNORED}
            self.assertFalse(
                extra,
                f"{v}/{arm}/{seq} diff vs self-tracked outside allowed {FP_VS_ST_ALLOWED}: "
                f"{extra} (full {diff})",
            )

    def test_twin_differs_only_in_lifecycle(self):
        """prune vs deferred twin (same variant, same seq): allowed diff = {method, lifecycle}."""
        for v, configs in [("c", C_CONFIGS), ("b", B_CONFIGS)]:
            for seq in ("pt1", "balloon2"):
                prune = load_config(configs[(v, "prune", seq)])
                deferred = load_config(configs[(v, "deferred", seq)])
                diff = _diff(prune, deferred)
                extra = {k for k in diff if k not in TWIN_ALLOWED and k not in IGNORED}
                self.assertFalse(
                    extra,
                    f"{v}/{seq} twin diff outside allowed {TWIN_ALLOWED}: {extra} (full {diff})",
                )
                self.assertEqual(prune["Mapping"]["lifecycle_mode"], "prune")
                self.assertEqual(deferred["Mapping"]["lifecycle_mode"], "deferred")

    def test_c_prune_trajectory_sources_exist(self):
        """variant C's resolved pose_file source (P2-T prune trj_full_final.json) exists per seed."""
        if not os.path.isdir(P2T):
            self.skipTest("P2-T runs not present on this machine")
        seq_dirname = {"pt1": "p2s_combined_prune_pt1",
                       "balloon2": "p2s_combined_prune_balloon2"}
        for seq, dirname in seq_dirname.items():
            for seed in (0, 1, 2):
                pattern = os.path.join(
                    P2T, f"{seq}_prune_seed{seed}", "datasets_bonn", dirname,
                    f"seed_{seed}", "*", "plot", "trj_full_final.json")
                matches = glob.glob(pattern)
                self.assertTrue(
                    matches,
                    f"C variant needs prune trj_full_final.json for {seq} seed{seed}: "
                    f"none matching {pattern}",
                )
                # validate it is per-frame (not the 116-frame keyframe trj_final.json)
                import json
                with open(matches[0], encoding="utf-8") as f:
                    d = json.load(f)
                self.assertIn("trj_est", d)
                self.assertGreater(len(d["trj_est"]), 400,
                                   f"{seq} seed{seed} trj_full_final not per-frame "
                                   f"(len={len(d['trj_est'])})")


if __name__ == "__main__":
    unittest.main()
