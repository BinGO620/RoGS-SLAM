"""CUDA integration tests for GaussianModel lineage-ID wiring (method #7).

Exercises the real GaussianModel densify/prune machinery (which hardcodes
device="cuda"), so the whole module is skipped without a GPU. Verifies that the
lineage label mirrors unique_kfIDs: UNTRACKED for normal growth, fresh ids for a
candidate insert, INHERITED through clone/split, and that prune_lineage removes a
candidate's full lineage together with its optimizer state -- the property the
`prune` ablation arm relies on to be a faithful insert-then-remove twin.
"""

import types
import unittest

import numpy as np
import torch

from utils.causal_twin import UNTRACKED

try:
    from gaussian_splatting.scene.gaussian_model import GaussianModel

    _IMPORT_OK = True
except Exception as exc:  # pragma: no cover - env without the CUDA extensions
    _IMPORT_OK = False
    _IMPORT_ERR = repr(exc)

_CUDA = torch.cuda.is_available()


def _opt_params():
    return types.SimpleNamespace(
        percent_dense=0.01,
        position_lr_init=0.0016,
        position_lr_final=0.0000016,
        position_lr_delay_mult=0.01,
        position_lr_max_steps=30000,
        feature_lr=0.0025,
        opacity_lr=0.05,
        scaling_lr=0.005,
        rotation_lr=0.001,
    )


@unittest.skipUnless(_CUDA and _IMPORT_OK, "requires CUDA + gaussian_splatting extensions")
class GaussianLineageIntegrationTests(unittest.TestCase):
    def _new_model(self, point_size=None):
        dataset = {"sensor_type": "rgbd"}
        if point_size is not None:
            dataset["point_size"] = point_size
        gm = GaussianModel(0, config={"Dataset": dataset})
        gm.init_lr(6.0)
        gm.training_setup(_opt_params())
        return gm

    def _cam(self):
        """Identity-pose pinhole camera: world == camera coords, so a pixel (cx, cy, z)
        backprojects to [0, 0, z] -- an analytic target for the builder."""
        return types.SimpleNamespace(
            R=torch.eye(3, device="cuda"),
            T=torch.zeros(3, device="cuda"),
            fx=100.0, fy=100.0, cx=64.0, cy=48.0,
        )

    def _extend_untracked(self, gm, n, kf_id=0):
        """Append n normal (UNTRACKED) Gaussians via the real extend_from_pcd path."""
        xyz = torch.randn(n, 3, device="cuda")
        features = torch.zeros(n, 3, 1, device="cuda")
        scales = torch.full((n, 3), float(torch.log(torch.tensor(0.01))), device="cuda")
        rots = torch.zeros(n, 4, device="cuda")
        rots[:, 0] = 1.0
        opacities = torch.zeros(n, 1, device="cuda")
        gm.extend_from_pcd(xyz, features, scales, rots, opacities, kf_id)

    def _insert_candidates(self, gm, k, scale=0.01):
        """Insert k candidate Gaussians carrying fresh lineage ids; return the ids."""
        ids = gm.allocate_lineage_ids(k)
        xyz = torch.randn(k, 3, device="cuda")
        f_dc = torch.zeros(k, 1, 3, device="cuda")
        f_rest = torch.zeros(k, 0, 3, device="cuda")
        opacity = torch.zeros(k, 1, device="cuda")
        scaling = torch.full((k, 3), float(torch.log(torch.tensor(scale))), device="cuda")
        rotation = torch.zeros(k, 4, device="cuda")
        rotation[:, 0] = 1.0
        gm.densification_postfix(
            xyz, f_dc, f_rest, opacity, scaling, rotation,
            new_kf_ids=torch.full((k,), 9, dtype=torch.int32),
            new_n_obs=torch.zeros(k, dtype=torch.int32),
            new_lineage_id=ids,
        )
        return ids

    def _assert_invariants(self, gm):
        n = gm.get_xyz.shape[0]
        self.assertEqual(gm.lineage_id.shape[0], n)
        self.assertEqual(gm.unique_kfIDs.shape[0], n)
        for group in gm.optimizer.param_groups:
            self.assertEqual(group["params"][0].shape[0], n)

    def test_normal_growth_is_untracked(self):
        gm = self._new_model()
        self._extend_untracked(gm, 5)
        self.assertEqual(gm.get_xyz.shape[0], 5)
        self.assertTrue(bool((gm.lineage_id == UNTRACKED).all()))
        self._assert_invariants(gm)

    def test_candidate_insert_stamps_fresh_ids(self):
        gm = self._new_model()
        self._extend_untracked(gm, 4)
        ids = self._insert_candidates(gm, 3)
        self.assertTrue(bool(torch.equal(ids, torch.tensor([0, 1, 2], dtype=torch.int32))))
        # first 4 UNTRACKED, last 3 are the candidate ids
        self.assertTrue(bool((gm.lineage_id[:4] == UNTRACKED).all()))
        self.assertTrue(bool(torch.equal(gm.lineage_id[4:], ids)))
        self._assert_invariants(gm)

    def test_clone_inherits_lineage(self):
        gm = self._new_model()
        self._extend_untracked(gm, 2)  # scale 0.01 -> eligible for clone
        ids = self._insert_candidates(gm, 1, scale=0.01)  # candidate id 0, at index 2
        n_before = gm.get_xyz.shape[0]
        grads = torch.zeros(n_before, 1, device="cuda")
        grads[2, 0] = 1.0  # only the candidate exceeds the gradient threshold
        gm.densify_and_clone(grads, 0.5, 6.0)
        self.assertEqual(gm.get_xyz.shape[0], n_before + 1)
        self.assertEqual(int(gm.lineage_id[-1]), int(ids[0]))  # clone carries parent id
        self.assertEqual(int((gm.lineage_id == ids[0]).sum()), 2)  # parent + clone
        self._assert_invariants(gm)

    def test_split_inherits_lineage_and_prunes_parent(self):
        gm = self._new_model()
        self._extend_untracked(gm, 2)  # scale 0.01 -> NOT split-eligible
        ids = self._insert_candidates(gm, 1, scale=0.1)  # scale 0.1 > 0.06 -> splittable
        n_before = gm.get_xyz.shape[0]
        grads = torch.zeros(n_before, 1, device="cuda")
        grads[2, 0] = 1.0
        gm.densify_and_split(grads, 0.5, 6.0, N=2)
        # parent (1) removed, 2 children added -> net +1; both children carry id 0
        self.assertEqual(int((gm.lineage_id == ids[0]).sum()), 2)
        self.assertEqual(int((gm.lineage_id == UNTRACKED).sum()), 2)  # originals intact
        self._assert_invariants(gm)

    def test_prune_lineage_removes_full_lineage_and_optimizer_state(self):
        gm = self._new_model()
        self._extend_untracked(gm, 3)
        self._insert_candidates(gm, 2)  # fresh allocator -> candidate ids 0, 1 at indices 3, 4
        # split candidate id 1 (index 4) so it spawns descendants sharing id 1
        n_before = gm.get_xyz.shape[0]
        grads = torch.zeros(n_before, 1, device="cuda")
        grads[4, 0] = 1.0
        # give index 4 a splittable scale
        with torch.no_grad():
            gm._scaling[4] = float(torch.log(torch.tensor(0.1)))
        gm.densify_and_split(grads, 0.5, 6.0, N=2)
        self.assertGreaterEqual(int((gm.lineage_id == 1).sum()), 2)  # lineage 1 grew

        n_id0 = int((gm.lineage_id == 0).sum())
        n_untracked = int((gm.lineage_id == UNTRACKED).sum())
        gm.prune_lineage([1])  # remove candidate 1 and every descendant
        self.assertEqual(int((gm.lineage_id == 1).sum()), 0)  # lineage 1 fully gone
        self.assertEqual(int((gm.lineage_id == 0).sum()), n_id0)  # lineage 0 untouched
        self.assertEqual(int((gm.lineage_id == UNTRACKED).sum()), n_untracked)
        self._assert_invariants(gm)  # optimizer state sliced consistently

    def test_prune_lineage_empty_is_noop(self):
        gm = self._new_model()
        self._extend_untracked(gm, 3)
        self._insert_candidates(gm, 1)
        n = gm.get_xyz.shape[0]
        gm.prune_lineage([])
        self.assertEqual(gm.get_xyz.shape[0], n)
        self._assert_invariants(gm)

    def test_prune_raw_maintains_lineage(self):
        # optimizer-free fallback (prune_nonfinite_points path) must slice lineage too
        gm = self._new_model()
        self._extend_untracked(gm, 3)
        self._insert_candidates(gm, 2)  # candidate ids 0, 1 at indices 3, 4
        keep = torch.ones(gm.get_xyz.shape[0], dtype=torch.bool, device="cuda")
        keep[0] = False  # drop one UNTRACKED
        keep[3] = False  # drop candidate id 0
        gm._prune_raw(keep)
        self.assertEqual(gm.lineage_id.shape[0], gm.get_xyz.shape[0])
        self.assertEqual(int((gm.lineage_id == 0).sum()), 0)  # candidate 0 gone
        self.assertEqual(int((gm.lineage_id == 1).sum()), 1)  # candidate 1 survives
        self.assertEqual(int((gm.lineage_id == UNTRACKED).sum()), 2)  # 3 - 1 untracked

    def test_densification_postfix_rejects_wrong_length_lineage(self):
        gm = self._new_model()
        self._extend_untracked(gm, 2)
        k = 3
        xyz = torch.randn(k, 3, device="cuda")
        f_dc = torch.zeros(k, 1, 3, device="cuda")
        f_rest = torch.zeros(k, 0, 3, device="cuda")
        opacity = torch.zeros(k, 1, device="cuda")
        scaling = torch.zeros(k, 3, device="cuda")
        rotation = torch.zeros(k, 4, device="cuda")
        rotation[:, 0] = 1.0
        with self.assertRaises(ValueError):
            gm.densification_postfix(
                xyz, f_dc, f_rest, opacity, scaling, rotation,
                new_lineage_id=torch.tensor([0], dtype=torch.int32),  # len 1 != 3
            )

    def test_validate_runtime_state_flags_lineage_desync(self):
        gm = self._new_model()
        self._extend_untracked(gm, 3)
        gm.validate_runtime_state()  # healthy -> no raise
        gm.lineage_id = gm.lineage_id[:2]  # force a desync
        with self.assertRaises(RuntimeError):
            gm.validate_runtime_state()

    def test_prune_lineage_slices_adam_state(self):
        # the "removes optimizer state" claim, exercised with a real optimizer step
        gm = self._new_model()
        self._extend_untracked(gm, 3)
        self._insert_candidates(gm, 2)  # candidate ids 0, 1
        loss = (
            gm._xyz.sum() + gm._opacity.sum() + gm._scaling.sum()
            + gm._rotation.sum() + gm._features_dc.sum() + gm._features_rest.sum()
        )
        loss.backward()
        gm.optimizer.step()  # creates Adam exp_avg / exp_avg_sq
        n_before = gm.get_xyz.shape[0]

        def _xyz_state():
            for grp in gm.optimizer.param_groups:
                if grp["name"] == "xyz":
                    return gm.optimizer.state[grp["params"][0]]
            raise AssertionError("no xyz group")

        self.assertEqual(_xyz_state()["exp_avg"].shape[0], n_before)
        gm.prune_lineage([0])  # remove candidate 0
        self.assertEqual(_xyz_state()["exp_avg"].shape[0], n_before - 1)
        self.assertEqual(_xyz_state()["exp_avg_sq"].shape[0], n_before - 1)
        self._assert_invariants(gm)

    # --- lifecycle direct-from-arrays builder (method #9, Step 2b) --------------
    def test_extend_from_pcd_stamps_explicit_lineage(self):
        gm = self._new_model()
        self._extend_untracked(gm, 2)
        k = 3
        xyz = torch.randn(k, 3, device="cuda")
        features = torch.zeros(k, 3, 1, device="cuda")
        scales = torch.zeros(k, 3, device="cuda")
        rots = torch.zeros(k, 4, device="cuda")
        rots[:, 0] = 1.0
        opac = torch.zeros(k, 1, device="cuda")
        ids = torch.tensor([7, 8, 9], dtype=torch.int32)
        gm.extend_from_pcd(xyz, features, scales, rots, opac, kf_id=1, lineage_ids=ids)
        self.assertTrue(bool(torch.equal(gm.lineage_id[-3:], ids)))
        self.assertTrue(bool((gm.lineage_id[:2] == UNTRACKED).all()))
        self._assert_invariants(gm)

    def test_insert_candidate_gaussians_backprojects_and_stamps(self):
        gm = self._new_model(point_size=0.01)
        self._extend_untracked(gm, 3)
        cam = self._cam()
        xs = np.array([64, 164, 64, 164], dtype=np.int32)  # cx, cx+fx
        ys = np.array([48, 48, 148, 148], dtype=np.int32)  # cy, cy+fy
        depth = np.full(4, 2.0, dtype=np.float32)
        color = np.full((4, 3), 0.5, dtype=np.float32)
        ids = gm.allocate_lineage_ids(4)
        n0 = gm.get_xyz.shape[0]
        inserted = gm.insert_candidate_gaussians(
            cam, xs, ys, depth, color, kf_id=5, lineage_ids=ids
        )
        self.assertEqual(inserted, 4)
        self.assertEqual(gm.get_xyz.shape[0], n0 + 4)
        self.assertTrue(bool(torch.equal(gm.lineage_id[-4:], ids)))  # order-aligned
        # identity pose: (cx,cy,2) -> [0,0,2]; (cx+fx,cy,2) -> [2,0,2]
        world0 = gm.get_xyz[-4].detach().cpu()
        world1 = gm.get_xyz[-3].detach().cpu()
        self.assertTrue(torch.allclose(world0, torch.tensor([0.0, 0.0, 2.0]), atol=1e-4))
        self.assertTrue(torch.allclose(world1, torch.tensor([2.0, 0.0, 2.0]), atol=1e-4))
        self._assert_invariants(gm)

    def test_insert_candidate_then_prune_roundtrip(self):
        gm = self._new_model(point_size=0.01)
        self._extend_untracked(gm, 2)
        cam = self._cam()
        xs = np.array([64, 164, 64], dtype=np.int32)
        ys = np.array([48, 48, 148], dtype=np.int32)
        depth = np.full(3, 2.0, dtype=np.float32)
        color = np.full((3, 3), 0.5, dtype=np.float32)
        ids = gm.allocate_lineage_ids(3)  # [0, 1, 2]
        gm.insert_candidate_gaussians(cam, xs, ys, depth, color, kf_id=5, lineage_ids=ids)
        self.assertEqual(gm.get_xyz.shape[0], 5)
        gm.prune_lineage([int(ids[1])])  # prune arm deletes exactly candidate 1
        self.assertEqual(gm.get_xyz.shape[0], 4)
        self.assertEqual(int((gm.lineage_id == 1).sum()), 0)
        self.assertEqual(int((gm.lineage_id == 0).sum()), 1)
        self.assertEqual(int((gm.lineage_id == 2).sum()), 1)
        self.assertEqual(int((gm.lineage_id == UNTRACKED).sum()), 2)
        self._assert_invariants(gm)

    def test_insert_candidate_empty_is_noop(self):
        gm = self._new_model(point_size=0.01)
        self._extend_untracked(gm, 3)
        empty_i = np.array([], dtype=np.int32)
        out = gm.insert_candidate_gaussians(
            self._cam(), empty_i, empty_i, np.array([], np.float32),
            np.zeros((0, 3), np.float32), kf_id=5, lineage_ids=empty_i,
        )
        self.assertEqual(out, 0)
        self.assertEqual(gm.get_xyz.shape[0], 3)
        self._assert_invariants(gm)


if __name__ == "__main__":
    if not (_CUDA and _IMPORT_OK):
        print(f"SKIP: cuda={_CUDA} import_ok={_IMPORT_OK}"
              + (f" err={_IMPORT_ERR}" if not _IMPORT_OK else ""))
    unittest.main()
