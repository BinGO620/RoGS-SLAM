"""Correctness of the GT-pose motion-consistency dynamic mask (task #5, P-A).

The mask is the method-INDEPENDENT dynamic oracle the hole-safe static-background
metric excludes, so its correctness must not depend on any SLAM machinery. These
tests run it on a fully synthetic scene with KNOWN ground truth: a static background
plane plus a square object that translates across frames, camera fixed. The signed
motion-consistency test must flag the moving square at its current location and leave
the static background unflagged; the morphological grow must only ADD pixels.
"""

import unittest

import numpy as np

from utils.gtmc_mask import (
    build_dynamic_masks,
    frozen_mask_index,
    grow_mask,
    load_frozen_mask,
    mad_outliers,
    masks_sha256,
    motion_inconsistency,
    region_grow_fill,
    robust_motion_seeds,
)

# Small synthetic pinhole; identity poses = fixed camera (so a pixel reprojects to
# itself and the neighbour's observed depth at that pixel is the comparison).
CALIB = dict(fx=40.0, fy=40.0, cx=20.0, cy=20.0, depth_scale=1.0, width=40, height=40)
D_BG = 3.0   # static background plane depth (m)
D_OBJ = 1.5  # nearer moving object
SIDE = 6
Y0, Y1 = 16, 22          # object row band
STARTS = [2, 12, 22, 32, 42]  # object left-x per frame (frame 4 is off-image)


def _scene():
    """5 frames: background at D_BG everywhere, a SIDE-wide square at D_OBJ that
    jumps 10px/frame (so it fully clears its frame-2 footprint in every neighbour)."""
    depths = []
    for x0 in STARTS:
        d = np.full((CALIB["height"], CALIB["width"]), D_BG, dtype=np.float32)
        x1 = min(x0 + SIDE, CALIB["width"])
        if x0 < CALIB["width"]:
            d[Y0:Y1, x0:x1] = D_OBJ
        depths.append(d)
    c2w = np.stack([np.eye(4) for _ in STARTS])  # fixed camera
    return depths, c2w


class MotionConsistencyMask(unittest.TestCase):
    def test_flags_moving_object_at_current_location(self):
        depths, c2w = _scene()
        raw = motion_inconsistency(depths, c2w, CALIB, thresh=0.05, persist=2)
        m2 = raw[2]  # object occupies cols [22, 28) at frame 2
        # every object pixel at frame 2 is a persistent signed mover...
        self.assertTrue(bool(m2[Y0:Y1, 22:28].all()))
        # ...and the static background is untouched (no false positives).
        bg = m2.copy()
        bg[Y0:Y1, 22:28] = False
        self.assertEqual(int(bg.sum()), 0)

    def test_static_background_where_object_visits_is_not_flagged(self):
        """A background pixel that the object OCCLUDES in a neighbour must stay
        unflagged -- the signed test rejects occlusion (delta < 0)."""
        depths, c2w = _scene()
        raw = motion_inconsistency(depths, c2w, CALIB, thresh=0.05, persist=2)
        # col 12-18 at frame 2 is background, but the object sits there at frame 1.
        self.assertFalse(bool(raw[2][Y0:Y1, 12:18].any()))

    def test_fully_static_scene_has_empty_mask(self):
        H, W = CALIB["height"], CALIB["width"]
        depths = [np.full((H, W), D_BG, dtype=np.float32) for _ in range(5)]
        c2w = np.stack([np.eye(4) for _ in range(5)])
        raw = motion_inconsistency(depths, c2w, CALIB, thresh=0.05, persist=2)
        self.assertEqual(sum(int(m.sum()) for m in raw), 0)

    def test_grow_is_a_superset_and_covers_object(self):
        depths, c2w = _scene()
        raw = motion_inconsistency(depths, c2w, CALIB, thresh=0.05, persist=2)
        grown = grow_mask(raw[2], close_radius=1, dilate_radius=3)
        self.assertTrue(bool((grown | raw[2] == grown).all()))  # grown superset of raw
        self.assertGreater(int(grown.sum()), int(raw[2].sum()))  # strictly larger
        self.assertTrue(bool(grown[Y0:Y1, 22:28].all()))        # still covers object

    def test_persist_rejects_single_neighbour_blips(self):
        """A pixel inconsistent in only ONE neighbour is not a mover at persist=2."""
        depths, c2w = _scene()
        # frame 0's object (cols [2,8)) clears in frames 1,2 -> flagged by both
        # forward neighbours -> persist=2 holds even with no backward neighbours.
        raw = motion_inconsistency(depths, c2w, CALIB, thresh=0.05, persist=2)
        self.assertTrue(bool(raw[0][Y0:Y1, 2:8].all()))
        # but demanding 3 neighbours (impossible at t=0, only s=1,2 exist) -> nothing.
        raw3 = motion_inconsistency(depths, c2w, CALIB, thresh=0.05, persist=3)
        self.assertEqual(int(raw3[0].sum()), 0)

    def test_build_pipeline_and_hash_deterministic(self):
        depths, c2w = _scene()
        a = build_dynamic_masks(depths, c2w, CALIB, close_radius=1, dilate_radius=3)
        b = build_dynamic_masks(depths, c2w, CALIB, close_radius=1, dilate_radius=3)
        self.assertEqual(masks_sha256(a), masks_sha256(b))       # deterministic
        # a different grow radius changes the frozen hash (params are load-bearing).
        c = build_dynamic_masks(depths, c2w, CALIB, close_radius=1, dilate_radius=5)
        self.assertNotEqual(masks_sha256(a), masks_sha256(c))


class RegionGrowFill(unittest.TestCase):
    """Depth-region-grow fills a mover's interior from silhouette seeds, while the
    density gate keeps a huge static region (that catches sparse FP) unfilled."""

    def _square_depth(self):
        H, W = 40, 40
        d = np.full((H, W), 3.0, dtype=np.float32)  # background plane
        d[15:25, 15:25] = 1.5  # a nearer square object (depth jump -> its own region)
        return d

    def test_fills_object_interior_from_sparse_seeds(self):
        depth = self._square_depth()
        seeds = np.zeros((40, 40), dtype=bool)
        seeds[17:21, 17:21] = True  # a small seed cluster INSIDE the object region
        out = region_grow_fill(seeds, depth, min_seed_px=8, min_seed_frac=0.05, seed_open_radius=0)
        self.assertTrue(bool(out[seeds].all()))          # fill covers the seed cluster
        self.assertGreaterEqual(int(out.sum()), 49)      # grew to fill most of the object
        outside = out.copy()
        outside[15:25, 15:25] = False
        self.assertEqual(int(outside.sum()), 0)          # no leak into the background

    def test_density_gate_rejects_sparse_seeds_in_huge_region(self):
        depth = np.full((40, 40), 3.0, dtype=np.float32)  # one big region
        seeds = np.zeros((40, 40), dtype=bool)
        seeds[5, 5] = seeds[20, 20] = seeds[35, 35] = True  # 3 stray seeds / 1600 px
        out = region_grow_fill(seeds, depth, min_seed_px=8, min_seed_frac=0.05, seed_open_radius=0)
        self.assertEqual(int(out.sum()), 0)  # density 0.002 << 0.05 -> nothing filled

    def test_no_seeds_is_empty(self):
        depth = self._square_depth()
        out = region_grow_fill(np.zeros((40, 40), dtype=bool), depth)
        self.assertEqual(int(out.sum()), 0)


class MadOutliers(unittest.TestCase):
    def test_flags_only_the_tail(self):
        r = np.array([0.01, 0.0, 0.02, -0.01, 0.0, 2.0], dtype=np.float32)
        out = mad_outliers(r, k=2.5, floor=0.05)
        self.assertTrue(bool(out[-1]))                 # the 2.0 outlier
        self.assertEqual(int(out[:-1].sum()), 0)       # the near-zero bulk is not

    def test_is_scene_adaptive(self):
        # same absolute residual (0.3) is an outlier in a calm frame but NOT in a
        # high-spread (fast-motion) frame -> threshold-free adaptation.
        calm = np.concatenate([np.zeros(100, np.float32), [0.3]])
        rough = np.concatenate([np.random.RandomState(0).uniform(0, 0.5, 100).astype(np.float32), [0.3]])
        self.assertTrue(bool(mad_outliers(calm, k=2.5, floor=0.0)[-1]))
        self.assertFalse(bool(mad_outliers(rough, k=2.5, floor=0.0)[-1]))

    def test_nan_is_false_and_floor_guards_flat_frame(self):
        self.assertFalse(bool(mad_outliers(np.array([np.nan], np.float32))[0]))
        flat = np.zeros(50, dtype=np.float32)
        flat[0] = 0.03
        # near-zero spread: floor keeps a 3cm blip from being called an outlier
        self.assertEqual(int(mad_outliers(flat, k=2.5, floor=0.05).sum()), 0)


class RobustSeeds(unittest.TestCase):
    def _scene_with_images(self):
        depths, c2w = _scene()
        H, W = CALIB["height"], CALIB["width"]
        images = []
        for x0 in STARTS:
            im = np.full((H, W), 0.8, dtype=np.float32)  # bright static background
            x1 = min(x0 + SIDE, W)
            if x0 < W:
                im[Y0:Y1, x0:x1] = 0.2  # dark moving square (photometric contrast)
            images.append(im)
        return depths, images, c2w

    def test_geo_and_photo_seeds_flag_only_the_mover(self):
        depths, images, c2w = self._scene_with_images()
        seeds = robust_motion_seeds(
            depths, images, c2w, CALIB, persist=2, geo_floor=0.05, photo_floor=0.02
        )
        s2 = seeds[2]  # square at cols [22, 28)
        self.assertTrue(bool(s2[Y0:Y1, 22:28].all()))   # mover flagged (geo AND photo)
        bg = s2.copy()
        bg[Y0:Y1, 22:28] = False
        self.assertEqual(int(bg.sum()), 0)              # nothing else (incl. occluded bg)

    def test_static_scene_seeds_are_empty(self):
        H, W = CALIB["height"], CALIB["width"]
        depths = [np.full((H, W), D_BG, dtype=np.float32) for _ in range(5)]
        images = [np.full((H, W), 0.6, dtype=np.float32) for _ in range(5)]
        c2w = np.stack([np.eye(4) for _ in range(5)])
        seeds = robust_motion_seeds(depths, images, c2w, CALIB, geo_floor=0.05, photo_floor=0.02)
        self.assertEqual(sum(int(s.sum()) for s in seeds), 0)


class FrozenMaskIO(unittest.TestCase):
    """The timestamp-keyed frozen-mask index + PNG round-trip the P-A eval uses to
    associate a rendered frame to its method-independent mask by DEPTH-file stem
    (utils/eval_utils.py::eval_static_background_raw). Pure I/O -- no SLAM machinery."""

    @staticmethod
    def _write_mask_png(path, mask):
        from PIL import Image

        Image.fromarray((np.asarray(mask, dtype=np.uint8) * 255), mode="L").save(path)

    def test_index_keys_by_stem_and_ignores_overlay_and_manifest(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            stems = ["1548339348.69468", "1548339352.59872"]
            for s in stems:
                self._write_mask_png(os.path.join(d, f"{s}.png"), np.zeros((4, 4), bool))
            # decoys the index must ignore: manifest.json (not *.png) + the _overlay subdir
            with open(os.path.join(d, "manifest.json"), "w") as fh:
                fh.write("{}")
            os.makedirs(os.path.join(d, "_overlay"))
            self._write_mask_png(
                os.path.join(d, "_overlay", f"{stems[0]}.png"), np.zeros((4, 4), bool)
            )

            index = frozen_mask_index(d)
            self.assertEqual(set(index), set(stems))  # keyed by depth stem, decoys ignored
            for s in stems:
                self.assertTrue(os.path.isabs(index[s]))
                self.assertTrue(index[s].endswith(f"{s}.png"))

    def test_missing_or_none_dir_is_empty_index(self):
        self.assertEqual(frozen_mask_index("/no/such/frozen/dir"), {})
        self.assertEqual(frozen_mask_index(None), {})

    def test_png_roundtrip_is_boolean_lossless(self):
        import os
        import tempfile

        m = np.zeros((6, 8), dtype=bool)
        m[1:4, 2:5] = True
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "123.456.png")
            self._write_mask_png(p, m)
            back = load_frozen_mask(p)
            self.assertEqual(back.dtype, np.bool_)
            np.testing.assert_array_equal(back, m)

    def test_frame_to_mask_resolution_by_depth_stem(self):
        """The exact lookup the eval performs: depth_paths[idx] -> stem -> mask path, a
        missing stem -> None (that frame is skipped, never scored as full-frame static)."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            present = "1548339348.69468"
            self._write_mask_png(os.path.join(d, f"{present}.png"), np.ones((4, 4), bool))
            index = frozen_mask_index(d)
            depth_paths = [
                f"/data/seq/depth/{present}.png",       # idx 0: has a mask
                "/data/seq/depth/9999999.00000.png",    # idx 1: no mask -> None
            ]
            got = [
                index.get(os.path.splitext(os.path.basename(p))[0]) for p in depth_paths
            ]
            self.assertTrue(got[0] and got[0].endswith(f"{present}.png"))
            self.assertIsNone(got[1])


if __name__ == "__main__":
    unittest.main()
