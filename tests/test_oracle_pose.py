"""Unit tests for the fixed external-trajectory oracle (utils/oracle_pose.py).

Two layers:
  * Synthetic (always run, CPU): world-frame mapping correctness, scaled-rotation
    normalization, and every self-validation gate (frame mismatch, corrupted GT
    anchor, non-metric scale) — the loader must REFUSE rather than inject wrong
    poses.
  * Real-data (skipped unless the balloon dataset + RGD trajectory exist on
    disk): the GT anchor closes and the injected trajectory's ATE is exact
    under BOTH references — 2.2571 cm vs RGD's own exported GT (published
    number) and 2.0618 cm vs OUR dataset GT (TUMParser association; the two
    GT samplings differ by 0.336 cm RMSE, which fully accounts for the gap;
    the frame mapping itself is ATE-preserving up to s=1.00066). In-pipeline
    smoke 2026-07-26 reproduced 2.0618 end-to-end with 0.0000 cm per-frame
    deviation from the injected poses.
"""

import glob
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.oracle_pose import (  # noqa: E402
    _orthonormalize,
    load_external_trajectory,
    oracle_pose_file,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BALLOON_CFG = os.path.join(ROOT, "configs", "rgbd", "bonn", "balloon.yaml")
BALLOON_TRJ = sorted(
    glob.glob(
        os.path.join(
            ROOT,
            "external_trajectories",
            "rgd",
            "bonn_balloon",
            "seed_0",
            "**",
            "trj_final.json",
        ),
        recursive=True,
    )
)


def _rand_rotation(rng):
    return _orthonormalize(rng.normal(size=(3, 3)))


def _make_synthetic(n=40, seed=7, rot_scale=1.06):
    """Build (file_dict, dataset_w2c, ours_c2w): same physical trajectory with
    ``ours = A @ file @ B`` — a rotated+translated WORLD frame (A) AND a relabeled
    CAMERA frame (B, e.g. ROS-body vs optical axes) — plus scaled R blocks."""
    rng = np.random.default_rng(seed)
    R_A = _rand_rotation(rng)
    t_A = rng.normal(size=3)
    R_B = _rand_rotation(rng)  # camera-axes relabel (zero lever arm)

    file_c2w = []
    ours_c2w = []
    for _ in range(n):
        Rk = _rand_rotation(rng)
        tk = rng.normal(size=3) * 2.0
        Tf = np.eye(4)
        Tf[:3, :3] = rot_scale * Rk  # benign uniform scale on the rotation block
        Tf[:3, 3] = tk
        file_c2w.append(Tf)
        To = np.eye(4)
        To[:3, :3] = R_A @ Rk @ R_B
        To[:3, 3] = R_A @ tk + t_A
        ours_c2w.append(To)
    file_c2w = np.stack(file_c2w)
    ours_c2w = np.stack(ours_c2w)
    data = {
        "trj_id": list(range(n)),
        "trj_est": file_c2w.tolist(),
        "trj_gt": file_c2w.tolist(),  # est == gt -> mapped est must equal our GT
    }
    return data, np.linalg.inv(ours_c2w), ours_c2w


def _write_json(tmpdir, data):
    import json

    path = os.path.join(tmpdir, "trj_final.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class OraclePoseSyntheticTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_maps_into_dataset_world_exactly(self):
        data, ds_w2c, ours_c2w = _make_synthetic()
        path = _write_json(self.tmp.name, data)
        poses, info = load_external_trajectory(path, ds_w2c)
        self.assertEqual(info["frames"], len(ds_w2c))
        self.assertLess(info["anchor_rmse_cm"], 1e-6)
        self.assertLess(abs(info["scale"] - 1.0), 1e-9)
        for k, (R, t) in enumerate(poses):
            # returned W2C must invert to our C2W (est==gt synthetic)
            np.testing.assert_allclose(R, ours_c2w[k][:3, :3].T, atol=1e-9)
            np.testing.assert_allclose(
                t, -ours_c2w[k][:3, :3].T @ ours_c2w[k][:3, 3], atol=1e-9
            )
            # rotations are orthonormal despite the scaled file blocks
            np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-9)

    def test_rejects_frame_count_mismatch(self):
        data, ds_w2c, _ = _make_synthetic()
        path = _write_json(self.tmp.name, data)
        with self.assertRaises(ValueError):
            load_external_trajectory(path, ds_w2c[:-3])

    def test_rejects_corrupted_gt_anchor(self):
        data, ds_w2c, _ = _make_synthetic()
        # shuffle the file's gt -> anchor cannot close -> must refuse
        rng = np.random.default_rng(0)
        order = rng.permutation(len(data["trj_gt"]))
        data["trj_gt"] = [data["trj_gt"][i] for i in order]
        path = _write_json(self.tmp.name, data)
        with self.assertRaises(ValueError):
            load_external_trajectory(path, ds_w2c)

    def test_rejects_non_metric_scale(self):
        data, ds_w2c, _ = _make_synthetic()
        gt = np.asarray(data["trj_gt"])
        gt[:, :3, 3] *= 1.10  # 10% position scale -> depth would not match
        data["trj_gt"] = gt.tolist()
        est = np.asarray(data["trj_est"])
        est[:, :3, 3] *= 1.10
        data["trj_est"] = est.tolist()
        path = _write_json(self.tmp.name, data)
        with self.assertRaises(ValueError):
            load_external_trajectory(path, ds_w2c)

    def test_rejects_missing_key(self):
        data, ds_w2c, _ = _make_synthetic()
        del data["trj_gt"]
        path = _write_json(self.tmp.name, data)
        with self.assertRaises(ValueError):
            load_external_trajectory(path, ds_w2c)

    def test_config_helper(self):
        self.assertEqual(oracle_pose_file({}), "")
        self.assertEqual(oracle_pose_file({"Oracle": {"pose_file": ""}}), "")
        self.assertEqual(oracle_pose_file({"Oracle": {"pose_file": "x.json"}}), "x.json")


def _ate_rmse_cm(est_p, gt_p):
    """evo-style ATE: SE(3) Umeyama alignment, translation RMSE (cm)."""
    mu_e, mu_g = est_p.mean(0), gt_p.mean(0)
    ec, gc = est_p - mu_e, gt_p - mu_g
    cov = gc.T @ ec / len(ec)
    U, _, Vt = np.linalg.svd(cov)
    sgn = np.eye(3)
    sgn[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ sgn @ Vt
    t = mu_g - R @ mu_e
    aligned = (R @ est_p.T).T + t
    return float(np.sqrt(((aligned - gt_p) ** 2).sum(1).mean()) * 100.0)


@unittest.skipUnless(
    os.path.isfile(BALLOON_CFG) and BALLOON_TRJ, "balloon dataset/trajectory absent"
)
class OraclePoseRealDataTests(unittest.TestCase):
    """Sanity anchor, both GT references (see module docstring for the 0.2cm story)."""

    PUBLISHED_ATE_CM = 2.2571  # RGD est vs RGD's exported GT (their reference)
    CROSS_GT_ATE_CM = 2.0618  # mapped RGD est vs OUR dataset GT (our reference)

    @classmethod
    def setUpClass(cls):
        try:
            from utils.config_utils import load_config
            from utils.dataset import TUMParser
        except ImportError as exc:  # heavy deps missing in a stripped env
            raise unittest.SkipTest(f"dataset deps unavailable: {exc}")
        cfg = load_config(BALLOON_CFG)
        parser = TUMParser(cfg["Dataset"]["dataset_path"])
        cls.ds_w2c = np.asarray(parser.poses, dtype=np.float64)
        cls.poses, cls.info = load_external_trajectory(BALLOON_TRJ[0], cls.ds_w2c)

    def test_anchor_closes(self):
        self.assertLess(self.info["anchor_rmse_cm"], 1.0)
        self.assertLess(self.info["anchor_rot_max_deg"], 3.0)
        self.assertLess(abs(self.info["scale"] - 1.0), 0.01)
        self.assertEqual(self.info["frames"], len(self.ds_w2c))

    def test_file_internal_ate_is_published(self):
        """est vs gt straight from the file (no mapping) == RGD's published ATE."""
        import json

        with open(BALLOON_TRJ[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        est = np.asarray(data["trj_est"], dtype=np.float64)[:, :3, 3]
        gt = np.asarray(data["trj_gt"], dtype=np.float64)[:, :3, 3]
        self.assertAlmostEqual(_ate_rmse_cm(est, gt), self.PUBLISHED_ATE_CM, delta=0.02)

    def test_injected_ate_vs_our_gt_is_exact(self):
        """Mapped est vs OUR GT: deterministic (pure math, no seeds) -> tight delta.

        2.0618 != published 2.2571 ONLY because the two GT samplings differ
        (0.336cm RMSE anchor residual); mapping est+gt jointly reproduces
        2.2571*s. The end-of-run ATE row of any injected run must equal THIS
        number — the in-pipeline smoke landed on it to 4 decimals.
        """
        est_c2w_t = np.stack([-(R.T @ t) for R, t in self.poses])
        gt_c2w_t = np.linalg.inv(self.ds_w2c)[:, :3, 3]
        ate = _ate_rmse_cm(est_c2w_t, gt_c2w_t)
        self.assertAlmostEqual(ate, self.CROSS_GT_ATE_CM, delta=0.02)


if __name__ == "__main__":
    unittest.main()
