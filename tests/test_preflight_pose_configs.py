"""E0 contract for the R2-P02 pose-controlled pre-flight configs (CPU, no GPU).

The pre-flight asks whether freezing the camera trajectory makes the ghost metric
able to resolve the arm contrast at all (``results/evidence/r2_p02_e2.md`` §8).
That question is only answerable if the *only* thing the pose overlay changes is
the pose channel -- so this test pins the resolved-config diffs before any GPU
time is spent, exactly as ``test_r2_oracle_configs.py`` does for R2-P01.

Two regimes, each with a deferred control (arm B) and an alpha-exit twin (arm D):

  ``rgd``  ``Oracle.pose_file``  RGD's published balloon trajectory (ATE 2.0618 cm).
           Pre-registered for E3 (prereg §7) and already run on both seeds in
           R2-P01-E2, so its control arm has a real on-disk reference band.
  ``gt``   ``Oracle.gt_pose``    dataset GT poses, zero pose error. Maximal
           isolation, no reference anchor.

Asserted, per regime:
  * pose overlay vs its self-tracked base: diff EXACTLY {method, <pose key>,
    Training.lr.cam_rot_delta, Training.lr.cam_trans_delta};
  * arm B vs arm D within a regime: diff EXACTLY {method, AlphaLifecycle.mode};
  * the pose freeze is real (both lrs 0.0 while the base lrs are non-zero) --
    ``Oracle.gt_pose`` alone only skips the *frontend* Adam tracking, the backend
    would still refine the poses off the frozen trajectory;
  * the arms resolve under the same predicate the arm-activity gate uses
    (``alpha_lifecycle_mode``): control ``off``, treatment ``exit``;
  * hard deferred entry is preserved on BOTH arms (Fork B: alpha drives exit/fill
    only), so the pre-flight cannot silently become an entry-side experiment.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.alpha_lifecycle import alpha_lifecycle_mode  # noqa: E402
from utils.config_utils import load_config  # noqa: E402

R2 = "configs/rgbd/experiments/r2_alpha_lifecycle"
P2 = "configs/rgbd/experiments/probe2_reliable_tracking"
OA = "configs/rgbd/experiments/r2_oracle_admission"

FREEZE = {"Training.lr.cam_rot_delta", "Training.lr.cam_trans_delta"}
PAIR_ALLOWED = {"method", "AlphaLifecycle.mode"}
IGNORED = {"inherit_from", "method_from"}

# regime -> (pose key, arm-B config, arm-D config, arm-B base, arm-D base)
REGIMES = {
    "rgd": (
        "Oracle.pose_file",
        f"{OA}/oracle_deferred_balloon.yaml",
        f"{R2}/oracle_alpha_exit_balloon.yaml",
        f"{P2}/deferred_rtoff_balloon.yaml",
        f"{R2}/alpha_exit_balloon.yaml",
    ),
    "gt": (
        "Oracle.gt_pose",
        f"{R2}/gtpose_deferred_balloon.yaml",
        f"{R2}/gtpose_alpha_exit_balloon.yaml",
        f"{P2}/deferred_rtoff_balloon.yaml",
        f"{R2}/alpha_exit_balloon.yaml",
    ),
}


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
    return {
        k
        for k in set(flat_a) | set(flat_b)
        if k.split(".")[0] not in IGNORED and flat_a.get(k) != flat_b.get(k)
    }


class PreflightPoseConfigContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(ROOT)  # inherit_from/method_from are repo-root relative
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    @classmethod
    def _cfg(cls, path):
        if path not in cls.cache:
            cls.cache[path] = load_config(path)
        return cls.cache[path]

    def test_pose_overlay_changes_only_the_pose_channel(self):
        for regime, (pose_key, b_cfg, d_cfg, b_base, d_base) in REGIMES.items():
            allowed = {"method", pose_key} | FREEZE
            for arm, overlay, base in (("B", b_cfg, b_base), ("D", d_cfg, d_base)):
                self.assertEqual(
                    _diff_keys(self._cfg(base), self._cfg(overlay)),
                    allowed,
                    f"{regime}/{arm}",
                )

    def test_arm_twins_differ_only_by_lifecycle_mode(self):
        for regime, (_, b_cfg, d_cfg, _, _) in REGIMES.items():
            self.assertEqual(
                _diff_keys(self._cfg(b_cfg), self._cfg(d_cfg)), PAIR_ALLOWED, regime
            )

    def test_pose_freeze_is_real(self):
        """gt_pose/pose_file skip FRONTEND tracking only -- the backend still
        refines cam_rot/trans_delta unless their lrs are zeroed."""
        for regime, (pose_key, b_cfg, d_cfg, b_base, _) in REGIMES.items():
            base = self._cfg(b_base)
            self.assertNotEqual(float(base["Training"]["lr"]["cam_rot_delta"]), 0.0)
            self.assertNotEqual(float(base["Training"]["lr"]["cam_trans_delta"]), 0.0)
            for overlay in (b_cfg, d_cfg):
                cfg = self._cfg(overlay)
                lr = cfg["Training"]["lr"]
                self.assertEqual(float(lr["cam_rot_delta"]), 0.0, overlay)
                self.assertEqual(float(lr["cam_trans_delta"]), 0.0, overlay)
                if pose_key.endswith("gt_pose"):
                    self.assertTrue(cfg["Oracle"]["gt_pose"], overlay)
                    self.assertFalse(cfg["Oracle"]["pose_file"], overlay)
                else:
                    self.assertTrue(cfg["Oracle"]["pose_file"], overlay)
                    self.assertFalse(cfg["Oracle"]["gt_pose"], overlay)

    def test_arms_resolve_under_the_gate_predicate(self):
        """Same predicate ``scripts/check_arm_activity.py`` polices the run with,
        so a mislabelled arm fails here rather than after 23 GPU-minutes."""
        for regime, (_, b_cfg, d_cfg, _, _) in REGIMES.items():
            self.assertEqual(alpha_lifecycle_mode(self._cfg(b_cfg)), "off", regime)
            self.assertEqual(alpha_lifecycle_mode(self._cfg(d_cfg)), "exit", regime)

    def test_fork_b_hard_entry_preserved_on_both_arms(self):
        """Fork B: alpha drives EXIT/FILL only; candidate entry stays hard-deferred."""
        for regime, (_, b_cfg, d_cfg, _, _) in REGIMES.items():
            for overlay in (b_cfg, d_cfg):
                cfg = self._cfg(overlay)
                self.assertEqual(cfg["Mapping"]["lifecycle_mode"], "deferred", overlay)
                self.assertTrue(cfg["DeferredCommit"]["enabled"], overlay)
                self.assertTrue(cfg["DeferredCommit"]["reliability_confirm"], overlay)
                self.assertEqual(
                    cfg["Results"]["static_bg_mask_subdir"], "dynamic_mask_gtmc", overlay
                )
                self.assertTrue(cfg["Results"]["save_raw_metrics"], overlay)

    def test_rgd_regime_reuses_the_r2_p01_control_verbatim(self):
        """The rgd control arm IS the R2-P01-E2 config, so its on-disk seed-0/1
        numbers are a legitimate reference band for the pre-flight canary."""
        cfg = self._cfg(REGIMES["rgd"][1])
        self.assertEqual(cfg["Dataset"]["dataset_path"], "datasets/bonn/rgbd_bonn_balloon")
        self.assertEqual(cfg["method"], "OracleRGD-Deferred")

    @unittest.skipUnless(
        os.path.isdir(os.path.join(ROOT, "external_trajectories", "rgd")),
        "external trajectories absent on this machine",
    )
    def test_rgd_pose_file_exists_and_is_shared_by_both_arms(self):
        b_file = self._cfg(REGIMES["rgd"][1])["Oracle"]["pose_file"]
        d_file = self._cfg(REGIMES["rgd"][2])["Oracle"]["pose_file"]
        self.assertEqual(b_file, d_file)  # identical frozen trajectory -> pure map delta
        self.assertTrue(os.path.isfile(b_file), b_file)


if __name__ == "__main__":
    unittest.main()
