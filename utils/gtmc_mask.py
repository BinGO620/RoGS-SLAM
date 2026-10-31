"""GT-pose motion-consistency (GTMC) dynamic masks for method-INDEPENDENT eval.

The make-or-break PRIMARY sequence ``moving_obstructing_box`` ships no segmentation
mask, so the hole-safe static-background rendering metric (``utils/static_eval.py``)
has no dynamic region to exclude. This module builds that region OFFLINE from GROUND-
TRUTH poses only -- never from a SLAM estimate or a learned segmenter -- so the mask
is a fixed, hashable, method-independent oracle shared identically by every arm
(doc-11: frozen masks, hashed, no runtime dependence).

A pixel of frame ``t`` is DYNAMIC iff, after back-projecting it to a world point with
the GT pose and reprojecting into temporal neighbours ``s``, the neighbour observes
the surface FARTHER than expected by ``> thresh`` in ``>= persist`` neighbours. The
test is SIGNED (occlusion-robust): a genuinely static surface can only be *occluded*
in a neighbour (observed closer, delta < 0) or consistent -- never revealed farther --
so ``delta = observed - expected > thresh`` means the expected surface has vanished =>
it moved. This is exactly the per-pixel form of ``scripts/analyze_mover_fraction.py``'s
>50% screen; here we KEEP the per-pixel field and GROW it (close small holes + dilate),
because for an EVAL mask RECALL dominates precision -- a missed mover pixel pollutes
the "static" PSNR (the arm that renders the mover better scores higher, confounding
the map-cleanliness claim), whereas an over-masked static pixel only trims the support
set. The signed+persist core is anchored to real motion (not scattered occlusion-edge
FP), so dilating outward from it stays spatially faithful to the mover.

Class-agnostic by construction: it detects ANY surface that moves relative to the
static world, so it covers the box AND any person uniformly, with no object model.
"""

from __future__ import annotations

import hashlib
import os
from glob import glob

import numpy as np
from scipy import ndimage

# Bonn shares one calibration across sequences (configs/rgbd/bonn/base_config.yaml;
# identical to scripts/analyze_mover_fraction.py's CALIB).
CALIB_BONN = dict(
    fx=542.822841, fy=542.576870, cx=315.593520, cy=237.756098,
    depth_scale=5000.0, width=640, height=480,
)
# Bonn lens distortion (configs/rgbd/bonn/base_config.yaml). The dataset loader
# undistorts RGB but NOT depth (utils/dataset.py:264/268); the eval compares
# undistorted renders, so the mask is computed on undistorted depth to (a) live in
# the same pixel space as the eval and (b) kill the grazing-surface reprojection FP
# that raw distorted depth produces under camera motion.
DIST_BONN = np.array([0.039903, -0.099343, -0.000730, -0.000144, 0.0])


def _intrinsic_matrix(calib):
    return np.array(
        [[calib["fx"], 0.0, calib["cx"]], [0.0, calib["fy"], calib["cy"]], [0.0, 0.0, 1.0]]
    )


def undistort_depths(depths, calib=CALIB_BONN, dist=DIST_BONN):
    """Undistort raw depth maps into the pinhole (eval) pixel space.

    INTER_NEAREST (never LINEAR): linear interpolation across a depth discontinuity
    blends foreground/background into spurious mid-depths, which would itself create
    motion-inconsistency false positives at every object silhouette.
    """
    import cv2

    K = _intrinsic_matrix(calib)
    W, H = calib["width"], calib["height"]
    m1, m2 = cv2.initUndistortRectifyMap(K, np.asarray(dist), np.eye(3), K, (W, H), cv2.CV_32FC1)
    return [cv2.remap(np.asarray(d, dtype=np.float32), m1, m2, cv2.INTER_NEAREST) for d in depths]


def undistort_images(images, calib=CALIB_BONN, dist=DIST_BONN):
    """Undistort RGB frames (INTER_LINEAR) to match the loader + eval space."""
    import cv2

    K = _intrinsic_matrix(calib)
    W, H = calib["width"], calib["height"]
    m1, m2 = cv2.initUndistortRectifyMap(K, np.asarray(dist), np.eye(3), K, (W, H), cv2.CV_32FC1)
    return [cv2.remap(np.asarray(im), m1, m2, cv2.INTER_LINEAR) for im in images]


def _disk(radius: int) -> np.ndarray:
    """Boolean disk structuring element of the given pixel radius (>=0)."""
    if radius <= 0:
        return np.ones((1, 1), dtype=bool)
    y, x = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    return (x * x + y * y) <= radius * radius


def motion_inconsistency(
    depths,
    c2w,
    calib=CALIB_BONN,
    thresh=0.05,
    neighbors=(-2, -1, 1, 2),
    persist=2,
    dmax=15.0,
    rel_thresh=0.0,
):
    """Per-frame RAW (pre-morphology) dynamic mask via GT-pose motion-consistency.

    ``depths``: list of ``(H, W)`` float depth maps in metres (UNDISTORTED -- see
    ``undistort_depths``). ``c2w``: ``(N, 4, 4)`` ground-truth camera-to-world poses.
    A pixel is flagged when the neighbour observes the surface farther than expected
    by more than ``max(thresh, rel_thresh * expected_depth)`` -- the relative term
    gives far/grazing surfaces proportional slack so residual reprojection error does
    not masquerade as motion, while a real mover (background revealed metres away)
    still clears it. Returns a list of ``(H, W)`` bool arrays, ``True`` where a pixel
    is a persistent (>= ``persist`` neighbours) signed mover.
    """
    fx, fy, cx, cy = calib["fx"], calib["fy"], calib["cx"], calib["cy"]
    H, W = calib["height"], calib["width"]
    c2w = np.asarray(c2w, dtype=np.float64)
    n = len(depths)
    w2c = np.linalg.inv(c2w)
    uu, vv = np.meshgrid(np.arange(W), np.arange(H))
    uu = uu.ravel()
    vv = vv.ravel()

    masks = []
    for t in range(n):
        z = np.asarray(depths[t], dtype=np.float64).ravel()
        valid = np.isfinite(z) & (z > 0.0) & (z <= dmax)
        out = np.zeros(H * W, dtype=bool)
        if not valid.any():
            masks.append(out.reshape(H, W))
            continue
        zt = z[valid]
        xw = c2w[t] @ np.stack(
            [(uu[valid] - cx) * zt / fx, (vv[valid] - cy) * zt / fy, zt, np.ones_like(zt)],
            axis=0,
        )  # 4 x M world points
        inconsistent = np.zeros(int(valid.sum()), dtype=np.int32)
        for dn in neighbors:
            s = t + dn
            if s < 0 or s >= n:
                continue
            xs = w2c[s] @ xw
            zs = xs[2]
            front = zs > 1e-6
            safe = np.where(front, zs, 1.0)
            us = np.rint(fx * xs[0] / safe + cx).astype(np.int64)
            vs = np.rint(fy * xs[1] / safe + cy).astype(np.int64)
            inside = front & (us >= 0) & (us < W) & (vs >= 0) & (vs < H)
            in_idx = np.nonzero(inside)[0]
            if in_idx.size == 0:
                continue
            dobs = np.asarray(depths[s], dtype=np.float64)[vs[inside], us[inside]]
            good = np.isfinite(dobs) & (dobs > 0.0) & (dobs <= dmax)
            g_idx = in_idx[good]
            zexp = zs[inside][good]
            delta = dobs[good] - zexp
            tol = np.maximum(thresh, rel_thresh * zexp)
            inconsistent[g_idx] += (delta > tol).astype(np.int32)
        mover = inconsistent >= persist
        vi = np.nonzero(valid)[0]
        out[vi[mover]] = True
        masks.append(out.reshape(H, W))
    return masks


def grow_mask(mask, close_radius=2, dilate_radius=5, open_radius=0, fill_holes=False):
    """Clean + grow the motion-anchored core into a solid mover region.

    Order is load-bearing (see the moving_obstructing_box overlays): a real mover is
    detected as its SILHOUETTE (where it reveals background), which ENCLOSES the
    object, whereas static depth-discontinuity FP (desk/table front edges under camera
    parallax) are thin OPEN bands. So:
      close      -- seal small gaps in the silhouette into a continuous contour;
      fill_holes -- fill the enclosed object interior (the box), NOT the open edges;
      open       -- erode away the remaining thin non-enclosing FP bands;
      dilate     -- grow outward to cover the object boundary (recall-biased).
    ``fill`` happens BEFORE ``open`` precisely because the silhouette is as thin as the
    FP -- opening first would erode the outline too; filling first turns it solid so
    opening keeps it. Returns a superset of the *filled* core, not necessarily of the
    raw outline.
    """
    m = np.asarray(mask, dtype=bool)
    if close_radius > 0:
        m = ndimage.binary_closing(m, structure=_disk(close_radius))
    if fill_holes:
        m = ndimage.binary_fill_holes(m)
    if open_radius > 0:
        m = ndimage.binary_opening(m, structure=_disk(open_radius))
    if dilate_radius > 0:
        m = ndimage.binary_dilation(m, structure=_disk(dilate_radius))
    return m


def _depth_edges(depth, edge_abs=0.08, edge_rel=0.03, curv=0.02):
    """Boolean region boundaries: depth-VALUE jumps + CREASES + invalid depth.

    Value jumps (``> max(edge_abs, edge_rel*depth)``) separate a near surface from a
    far one. But a moving object often TOUCHES the static floor (continuous depth), so
    value jumps alone leave them in one region -> add CREASE edges where the depth
    SLOPE changes sharply (second derivative ``> curv``): the box meets the floor at a
    normal discontinuity even where depth is continuous. Invalid/zero depth is always a
    boundary.
    """
    d = np.asarray(depth, dtype=np.float32)
    invalid = ~(np.isfinite(d) & (d > 0.0))
    df = np.where(invalid, 0.0, d)
    gx = np.zeros_like(df)
    gy = np.zeros_like(df)
    gx[:, 1:] = df[:, 1:] - df[:, :-1]
    gy[1:, :] = df[1:, :] - df[:-1, :]
    jump = (np.abs(gx) > np.maximum(edge_abs, edge_rel * np.abs(d))) | (
        np.abs(gy) > np.maximum(edge_abs, edge_rel * np.abs(d))
    )
    cxx = np.zeros_like(df)
    cyy = np.zeros_like(df)
    cxx[:, 1:] = np.abs(gx[:, 1:] - gx[:, :-1])
    cyy[1:, :] = np.abs(gy[1:, :] - gy[:-1, :])
    crease = (cxx > curv) | (cyy > curv)
    return jump | crease | invalid


def region_grow_fill(
    seed_mask,
    depth,
    edge_abs=0.08,
    edge_rel=0.03,
    curv=0.02,
    min_seed_px=8,
    min_seed_frac=0.05,
    seed_open_radius=2,
):
    """Fill each smooth-depth region that motion seeds cover densely enough.

    The signed motion test flags a moving object only at its silhouette / trailing
    edge, not its flat interior. We segment the depth map into regions bounded by depth
    jumps + creases (:func:`_depth_edges`) and mark a region DYNAMIC iff its seeds
    (opened by ``seed_open_radius`` to drop thin static-edge FP) number ``>=
    min_seed_px`` AND cover ``>= min_seed_frac`` of the region's area. The DENSITY test
    is load-bearing: a moving object's region is small and well-covered by seeds, while
    a huge static region (floor/wall) that catches a few stray seeds has near-zero
    density -> left unfilled. Pure GT-geometry: the eval oracle stays method-independent.
    """
    seeds = np.asarray(seed_mask, dtype=bool)
    if seed_open_radius > 0:
        seeds = ndimage.binary_opening(seeds, structure=_disk(seed_open_radius))
    if not seeds.any():
        return np.zeros_like(seeds)
    labels, n = ndimage.label(~_depth_edges(depth, edge_abs, edge_rel, curv))
    if n == 0:
        return np.zeros_like(seeds)
    area = np.bincount(labels.ravel(), minlength=n + 1).astype(np.float64)
    seed_counts = np.bincount(labels[seeds], minlength=n + 1).astype(np.float64)
    seed_counts[0] = 0.0  # label 0 = edge pixels; never a fillable region
    density = seed_counts / np.maximum(area, 1.0)
    dynamic_labels = np.nonzero((seed_counts >= min_seed_px) & (density >= min_seed_frac))[0]
    return np.isin(labels, dynamic_labels)


def build_dynamic_masks(
    depths,
    c2w,
    calib=CALIB_BONN,
    thresh=0.05,
    neighbors=(-2, -1, 1, 2),
    persist=2,
    dmax=15.0,
    close_radius=2,
    dilate_radius=5,
    rel_thresh=0.0,
    open_radius=0,
    fill_holes=False,
):
    """Full pipeline: signed motion-inconsistency core -> morphological grow.

    ``depths`` must already be UNDISTORTED (call :func:`undistort_depths` first).
    """
    raw = motion_inconsistency(depths, c2w, calib, thresh, neighbors, persist, dmax, rel_thresh)
    return [
        grow_mask(m, close_radius, dilate_radius, open_radius, fill_holes) for m in raw
    ]


def rigid_consistency_residuals(
    depths, images, c2w, calib=CALIB_BONN, neighbors=(-2, -1, 1, 2), persist=2, dmax=15.0
):
    """Per-frame GEOMETRIC (signed depth) + PHOTOMETRIC (grayscale warp) residuals from
    GT-pose rigid warping, reduced to the ``persist``-th largest over temporal
    neighbours (so >= ``persist`` neighbours must agree for a high residual).

    ``images``: list of ``(H, W)`` grayscale floats in [0, 1], in the SAME undistorted
    space as ``depths``. Returns ``(geo, photo)``: lists of ``(H, W)`` float32, NaN
    where fewer than ``persist`` neighbours cover the pixel. Both are RAW residuals --
    :func:`mad_outliers` turns them into threshold-free, scene-adaptive masks.
    """
    fx, fy, cx, cy = calib["fx"], calib["fy"], calib["cx"], calib["cy"]
    H, W = calib["height"], calib["width"]
    c2w = np.asarray(c2w, dtype=np.float64)
    n = len(depths)
    w2c = np.linalg.inv(c2w)
    uu, vv = np.meshgrid(np.arange(W), np.arange(H))
    uu = uu.ravel()
    vv = vv.ravel()
    K = len(neighbors)
    geo_out, photo_out = [], []
    for t in range(n):
        z = np.asarray(depths[t], dtype=np.float64).ravel()
        valid = np.isfinite(z) & (z > 0.0) & (z <= dmax)
        geo = np.full(H * W, np.nan, dtype=np.float32)
        photo = np.full(H * W, np.nan, dtype=np.float32)
        vi = np.nonzero(valid)[0]
        if vi.size == 0:
            geo_out.append(geo.reshape(H, W))
            photo_out.append(photo.reshape(H, W))
            continue
        zt = z[valid]
        xw = c2w[t] @ np.stack(
            [(uu[valid] - cx) * zt / fx, (vv[valid] - cy) * zt / fy, zt, np.ones_like(zt)],
            axis=0,
        )
        it = np.asarray(images[t], dtype=np.float32).ravel()[valid]
        dstack = np.full((vi.size, K), np.nan, dtype=np.float32)
        pstack = np.full((vi.size, K), np.nan, dtype=np.float32)
        for j, dn in enumerate(neighbors):
            s = t + dn
            if s < 0 or s >= n:
                continue
            xs = w2c[s] @ xw
            zs = xs[2]
            front = zs > 1e-6
            safe = np.where(front, zs, 1.0)
            us = np.rint(fx * xs[0] / safe + cx).astype(np.int64)
            vs = np.rint(fy * xs[1] / safe + cy).astype(np.int64)
            inside = front & (us >= 0) & (us < W) & (vs >= 0) & (vs < H)
            ii = np.nonzero(inside)[0]
            if ii.size == 0:
                continue
            dobs = np.asarray(depths[s], dtype=np.float64)[vs[inside], us[inside]]
            good = np.isfinite(dobs) & (dobs > 0.0) & (dobs <= dmax)
            gi = ii[good]
            dstack[gi, j] = (dobs[good] - zs[inside][good]).astype(np.float32)
            iw = np.asarray(images[s], dtype=np.float32)[vs[inside], us[inside]]
            pstack[gi, j] = np.abs(it[gi] - iw[good]).astype(np.float32)
        cov = np.sum(~np.isnan(dstack), axis=1)
        ds = np.where(np.isnan(dstack), -np.inf, dstack)
        ps = np.where(np.isnan(pstack), -np.inf, pstack)
        ds.sort(axis=1)
        ps.sort(axis=1)
        gvals = ds[:, -persist].copy()
        pvals = ps[:, -persist].copy()
        bad = cov < persist
        gvals[bad] = np.nan
        pvals[bad] = np.nan
        geo[vi] = gvals
        photo[vi] = pvals
        geo_out.append(geo.reshape(H, W))
        photo_out.append(photo.reshape(H, W))
    return geo_out, photo_out


def mad_outliers(residual, k=2.5, floor=0.0):
    """Per-frame robust-outlier mask: ``residual > median + max(k*1.4826*MAD, floor)``.

    THRESHOLD-FREE and scene-adaptive: the cut is set by the frame's OWN residual
    spread (median + k robust-sigma), so it rises automatically when fast camera motion
    lifts the whole frame's residual level -- a static grazing surface stops being an
    outlier while a real mover (residual far in the tail) still clears it. ``floor`` is
    a physical, scene-INDEPENDENT noise floor (sensor cm / small photometric delta) that
    only guards the degenerate near-zero-spread frame; it is NOT a tuned decision
    threshold. NaN residuals -> False.
    """
    r = np.asarray(residual, dtype=np.float32)
    finite = np.isfinite(r)
    out = np.zeros(r.shape, dtype=bool)
    if not finite.any():
        return out
    vals = r[finite]
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med))) * 1.4826
    thr = med + max(k * mad, float(floor))
    out[finite] = r[finite] > thr
    return out


def robust_motion_seeds(
    depths,
    images,
    c2w,
    calib=CALIB_BONN,
    neighbors=(-2, -1, 1, 2),
    persist=2,
    dmax=15.0,
    k_geo=2.5,
    k_photo=2.5,
    geo_floor=0.05,
    photo_floor=0.02,
):
    """Motion seeds = GEOMETRIC-outlier AND PHOTOMETRIC-outlier (both MAD-robust).

    The AND is the generalisation key: a static grazing surface under camera motion is a
    GEOMETRIC outlier (depth reprojection FP) but NOT a photometric one (it warps to
    itself -> ~0 RGB residual), so it is rejected; a real mover is BOTH (reveals
    background AND its texture fails the static warp), so it is kept. No per-scene
    threshold -- only universal robustness constants (k) + physical noise floors.
    """
    geo, photo = rigid_consistency_residuals(depths, images, c2w, calib, neighbors, persist, dmax)
    return [
        mad_outliers(g, k_geo, geo_floor) & mad_outliers(p, k_photo, photo_floor)
        for g, p in zip(geo, photo)
    ]


def build_dynamic_masks_robust(
    depths,
    images,
    c2w,
    calib=CALIB_BONN,
    neighbors=(-2, -1, 1, 2),
    persist=2,
    dmax=15.0,
    k_geo=2.5,
    k_photo=2.5,
    geo_floor=0.05,
    photo_floor=0.02,
    edge_abs=0.08,
    edge_rel=0.03,
    curv=0.02,
    min_seed_px=8,
    min_seed_frac=0.05,
    seed_open_radius=2,
    close_radius=2,
    dilate_radius=4,
):
    """Full GENERALISING pipeline: MAD-robust geo&photo seeds -> depth region-grow fill
    -> light morphological grow. All parameters are scene-INDEPENDENT (camera intrinsics,
    universal robustness constants, physical noise floors), so ONE set is meant to hold
    across sequences -- validated on box + person + static.
    """
    seeds = robust_motion_seeds(
        depths, images, c2w, calib, neighbors, persist, dmax,
        k_geo, k_photo, geo_floor, photo_floor,
    )
    out = []
    for sd, d in zip(seeds, depths):
        filled = region_grow_fill(sd, d, edge_abs, edge_rel, curv, min_seed_px, min_seed_frac, seed_open_radius)
        out.append(grow_mask(filled, close_radius=close_radius, dilate_radius=dilate_radius))
    return out


def masks_sha256(masks) -> str:
    """Deterministic hash of a mask stack (frozen-mask provenance, doc-11)."""
    h = hashlib.sha256()
    for m in masks:
        h.update(np.ascontiguousarray(np.asarray(m, dtype=np.uint8)).tobytes())
    return h.hexdigest()


def load_frozen_mask(path) -> np.ndarray:
    """Load a frozen ``(H, W)`` bool mask PNG (``True`` = dynamic) for eval."""
    from PIL import Image

    return np.asarray(Image.open(path).convert("L")) > 127


def frozen_mask_index(mask_dir) -> dict:
    """Map ``depth-file stem -> absolute mask PNG path`` for a frozen mask directory.

    Keys are the timestamp stems written by ``scripts/build_static_eval_mask.py`` (one
    PNG per depth file). The P-A eval associates a rendered frame to its mask by the
    frame's DEPTH-file stem, NOT by frame index, so the lookup survives any drift
    between the run's frame selection and the mask builder's association. The
    ``manifest.json`` (not ``*.png``) and the ``_overlay/`` subdir (non-recursive glob)
    are ignored. Returns ``{}`` when ``mask_dir`` is missing or empty.
    """
    out: dict = {}
    if not mask_dir or not os.path.isdir(mask_dir):
        return out
    for p in sorted(glob(os.path.join(mask_dir, "*.png"))):
        out[os.path.splitext(os.path.basename(p))[0]] = os.path.abspath(p)
    return out

