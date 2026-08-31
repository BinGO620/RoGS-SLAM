"""E0 contract for the R2-P01-E2 four-row-table configs (config resolution only, CPU).

Guards the paired-arm discipline before any GPU run:
  * oracle overlay vs its self-tracked base: allowed diff EXACTLY
    {method, Oracle.pose_file, Training.lr.cam_rot_delta, Training.lr.cam_trans_delta}
    (trajectory injection + backend pose freeze; nothing else may move).
  * prune vs deferred twins (dynamic oracle pair, dynamic self-tracked pair, both
    static TUM pairs): allowed diff EXACTLY {method, Mapping.lifecycle_mode}.
  * pose freeze is real: oracle lr == 0.0 while the base lr != 0.
  * every Oracle.pose_file exists on disk (machine-local, gitignored data — the
    existence check is skipped on machines without external_trajectories/).
  * static rows resolve to the intended TUM datasets with RT off and the openset
    Results block intact (band/vacated fields skip at runtime — no GTMC masks on TUM).
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.config_utils import load_config  # noqa: E402

R2DIR = "configs/rgbd/experiments/r2_oracle_admission"
P2DIR = "configs/rgbd/experiments/probe2_reliable_tracking"

DYNAMIC_SEQS = [
    "balloon",
    "balloon2",
    "moving_nonobstructing_box",
    "moving_nonobstructing_box2",
    "person_tracking2",
]

ORACLE_ALLOWED = {
    "method",
    "Oracle.pose_file",
    "Training.lr.cam_rot_delta",
    "Training.lr.cam_trans_delta",
}
PAIR_ALLOWED = {"method", "Mapping.lifecycle_mode"}
# bookkeeping keys injected by the loader / overlay files themselves — not method fields
IGNORED = {"inherit_from", "method_from"}


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
    keys = set(flat_a) | set(flat_b)
    return {
        k
        for k in keys
        if k.split(".")[0] not in IGNORED and flat_a.get(k) != flat_b.get(k)
    }


class R2OracleConfigContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cwd = os.getcwd()
        os.chdir(ROOT)  # inherit_from/method_from strings are repo-root relative
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._cwd)

    @classmethod
    def _cfg(cls, path):
        if path not in cls.cache:
            cls.cache[path] = load_config(path)
        return cls.cache[path]

    def test_oracle_overlay_diff_is_injection_only(self):
        for seq in DYNAMIC_SEQS:
            for arm in ("prune", "deferred"):
                base = self._cfg(f"{P2DIR}/{arm}_rtoff_{seq}.yaml")
                oracle = self._cfg(f"{R2DIR}/oracle_{arm}_{seq}.yaml")
                self.assertEqual(
                    _diff_keys(base, oracle), ORACLE_ALLOWED, f"{arm}/{seq}"
                )

    def test_oracle_pose_freeze_is_real(self):
        for seq in DYNAMIC_SEQS:
            base = self._cfg(f"{P2DIR}/prune_rtoff_{seq}.yaml")
            oracle = self._cfg(f"{R2DIR}/oracle_prune_{seq}.yaml")
            self.assertNotEqual(float(base["Training"]["lr"]["cam_rot_delta"]), 0.0)
            self.assertNotEqual(float(base["Training"]["lr"]["cam_trans_delta"]), 0.0)
            self.assertEqual(float(oracle["Training"]["lr"]["cam_rot_delta"]), 0.0)
            self.assertEqual(float(oracle["Training"]["lr"]["cam_trans_delta"]), 0.0)
            self.assertTrue(oracle["Oracle"]["pose_file"], seq)

    def test_prune_deferred_twins_diff_is_lifecycle_only(self):
        pairs = [
            (f"{R2DIR}/oracle_prune_{seq}.yaml", f"{R2DIR}/oracle_deferred_{seq}.yaml")
            for seq in DYNAMIC_SEQS
        ]
        pairs += [
            (f"{P2DIR}/prune_rtoff_{seq}.yaml", f"{P2DIR}/deferred_rtoff_{seq}.yaml")
            for seq in DYNAMIC_SEQS
        ]
        pairs += [
            (f"{R2DIR}/prune_rtoff_f1_desk.yaml", f"{R2DIR}/deferred_rtoff_f1_desk.yaml"),
            (f"{R2DIR}/prune_rtoff_f2_xyz.yaml", f"{R2DIR}/deferred_rtoff_f2_xyz.yaml"),
        ]
        for prune_path, deferred_path in pairs:
            diff = _diff_keys(self._cfg(prune_path), self._cfg(deferred_path))
            self.assertEqual(diff, PAIR_ALLOWED, prune_path)
            deferred = self._cfg(deferred_path)
            self.assertEqual(deferred["Mapping"]["lifecycle_mode"], "deferred")
            self.assertEqual(
                self._cfg(prune_path)["Mapping"]["lifecycle_mode"], "prune"
            )

    @unittest.skipUnless(
        os.path.isdir(os.path.join(ROOT, "external_trajectories", "rgd")),
        "external trajectories absent on this machine",
    )
    def test_oracle_pose_files_exist(self):
        for seq in DYNAMIC_SEQS:
            for arm in ("prune", "deferred"):
                pose_file = self._cfg(f"{R2DIR}/oracle_{arm}_{seq}.yaml")["Oracle"][
                    "pose_file"
                ]
                self.assertTrue(os.path.isfile(pose_file), pose_file)

    def test_static_rows_resolve_to_tum_with_rt_off(self):
        expected = {
            "f1_desk": "datasets/tum/rgbd_dataset_freiburg1_desk",
            "f2_xyz": "datasets/tum/rgbd_dataset_freiburg2_xyz",
        }
        for stem, dataset_path in expected.items():
            for arm in ("prune", "deferred"):
                cfg = self._cfg(f"{R2DIR}/{arm}_rtoff_{stem}.yaml")
                self.assertEqual(cfg["Dataset"]["dataset_path"], dataset_path)
                self.assertFalse(cfg["ReliableTracking"]["enabled"])
                self.assertTrue(cfg["Results"]["save_raw_metrics"])
                self.assertEqual(
                    cfg["Results"]["static_bg_mask_subdir"], "dynamic_mask_gtmc"
                )
                self.assertTrue(cfg["DeferredCommit"]["enabled"])
                self.assertTrue(cfg["DeferredCommit"]["reliability_confirm"])

    def test_dynamic_rows_share_one_method_base(self):
        """Rows 1-4 on one sequence differ ONLY via the two allowed axes combined."""
        for seq in DYNAMIC_SEQS:
            row1 = self._cfg(f"{P2DIR}/prune_rtoff_{seq}.yaml")
            row4 = self._cfg(f"{R2DIR}/oracle_deferred_{seq}.yaml")
            self.assertEqual(_diff_keys(row1, row4), ORACLE_ALLOWED | PAIR_ALLOWED, seq)


if __name__ == "__main__":
    unittest.main()
