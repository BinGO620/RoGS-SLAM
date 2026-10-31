from dataclasses import dataclass
import json
import os

import cv2
import numpy as np


def bootstrap_vo_enabled(config):
    return bool(config.get("BootstrapVO", {}).get("enabled", False))


def _image_numpy(camera):
    image = camera.original_image.detach().cpu().permute(1, 2, 0).numpy()
    return np.clip(image, 0.0, 1.0).astype(np.float32)


def _mask_numpy(mask, shape):
    if mask is None:
        return np.zeros(shape, dtype=bool)
    array = mask.detach().cpu().numpy() if hasattr(mask, "detach") else np.asarray(mask)
    return np.squeeze(array).astype(bool)


def _camera_matrix(camera):
    return np.array(
        [
            [camera.fx, 0.0, camera.cx],
            [0.0, camera.fy, camera.cy],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


@dataclass
class PoseEstimate:
    transform: np.ndarray | None
    matches: int
    inliers: int

    @property
    def inlier_ratio(self):
        return self.inliers / max(self.matches, 1)


@dataclass
class BootstrapResult:
    poses_cw: list[np.ndarray]
    initial_depth: np.ndarray
    fallback: bool
    pose_stats: list[PoseEstimate]
    confirmed_pixels: int
    fallback_reason: str | None = None


def _camera_pose(camera, ground_truth=False):
    pose = np.eye(4, dtype=np.float64)
    if ground_truth:
        pose[:3, :3] = camera.R_gt.detach().cpu().numpy()
        pose[:3, 3] = camera.T_gt.detach().cpu().numpy()
    else:
        pose[:3, :3] = camera.R.detach().cpu().numpy()
        pose[:3, 3] = camera.T.detach().cpu().numpy()
    return pose


def _relative_pose_error(estimate, source, target):
    if estimate.transform is None:
        return None, None
    gt_relative = _camera_pose(target, True) @ np.linalg.inv(_camera_pose(source, True))
    delta = estimate.transform @ np.linalg.inv(gt_relative)
    cosine = np.clip((np.trace(delta[:3, :3]) - 1.0) / 2.0, -1.0, 1.0)
    rotation_error_deg = float(np.degrees(np.arccos(cosine)))
    translation_error_m = float(np.linalg.norm(delta[:3, 3]))
    return rotation_error_deg, translation_error_m


def write_bootstrap_summary(save_dir, result, cameras):
    if not save_dir:
        return
    pose_pairs = []
    for index, estimate in enumerate(result.pose_stats):
        rotation_error, translation_error = _relative_pose_error(
            estimate, cameras[index], cameras[index + 1]
        )
        pose_pairs.append(
            {
                "source_frame": int(cameras[index].uid),
                "target_frame": int(cameras[index + 1].uid),
                "accepted": estimate.transform is not None,
                "matches": int(estimate.matches),
                "inliers": int(estimate.inliers),
                "inlier_ratio": float(estimate.inlier_ratio),
                "rotation_error_deg": rotation_error,
                "translation_error_m": translation_error,
            }
        )
    summary = {
        "fallback": bool(result.fallback),
        "fallback_reason": result.fallback_reason,
        "confirmed_pixels": int(result.confirmed_pixels),
        "initial_depth_pixels": int(np.count_nonzero(result.initial_depth > 0.01)),
        "frame_ids": [int(camera.uid) for camera in cameras],
        "pose_pairs": pose_pairs,
    }
    os.makedirs(save_dir, exist_ok=True)
    with open(
        os.path.join(save_dir, "bootstrap_vo_summary.json"),
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(summary, file, indent=2)


def estimate_relative_pose(config, source, target, source_dynamic_mask=None):
    cfg = config.get("BootstrapVO", {})
    source_rgb = (_image_numpy(source) * 255).astype(np.uint8)
    target_rgb = (_image_numpy(target) * 255).astype(np.uint8)
    source_gray = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2GRAY)
    target_gray = cv2.cvtColor(target_rgb, cv2.COLOR_RGB2GRAY)

    orb = cv2.ORB_create(nfeatures=int(cfg.get("orb_features", 2000)))
    source_kp, source_desc = orb.detectAndCompute(source_gray, None)
    target_kp, target_desc = orb.detectAndCompute(target_gray, None)
    if source_desc is None or target_desc is None:
        return PoseEstimate(None, 0, 0)

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(source_desc, target_desc, k=2)
    ratio = float(cfg.get("ratio_test", 0.75))
    matches = [
        pair[0]
        for pair in pairs
        if len(pair) == 2 and pair[0].distance < ratio * pair[1].distance
    ]

    depth = np.asarray(source.depth, dtype=np.float32)
    dynamic = _mask_numpy(source_dynamic_mask, depth.shape)
    points_3d = []
    points_2d = []
    min_depth = float(cfg.get("min_depth", 0.05))
    max_depth = float(cfg.get("max_depth", 5.0))
    for match in matches:
        u, v = source_kp[match.queryIdx].pt
        x = int(round(u))
        y = int(round(v))
        if x < 0 or y < 0 or x >= depth.shape[1] or y >= depth.shape[0]:
            continue
        z = float(depth[y, x])
        if not np.isfinite(z) or z < min_depth or z > max_depth or dynamic[y, x]:
            continue
        points_3d.append(
            [(u - source.cx) * z / source.fx, (v - source.cy) * z / source.fy, z]
        )
        points_2d.append(target_kp[match.trainIdx].pt)

    if len(points_3d) < 6:
        return PoseEstimate(None, len(points_3d), 0)
    points_3d = np.asarray(points_3d, dtype=np.float32)
    points_2d = np.asarray(points_2d, dtype=np.float32)
    success, rotation_vector, translation, inliers = cv2.solvePnPRansac(
        points_3d,
        points_2d,
        _camera_matrix(target),
        None,
        iterationsCount=int(cfg.get("ransac_iterations", 200)),
        reprojectionError=float(cfg.get("reprojection_threshold_px", 3.0)),
        confidence=float(cfg.get("confidence", 0.999)),
        flags=cv2.SOLVEPNP_EPNP,
    )
    inlier_count = 0 if inliers is None else int(len(inliers))
    min_inliers = int(cfg.get("min_inliers", 100))
    min_ratio = float(cfg.get("min_inlier_ratio", 0.30))
    if not success or inlier_count < min_inliers:
        return PoseEstimate(None, len(points_3d), inlier_count)
    if inlier_count / len(points_3d) < min_ratio:
        return PoseEstimate(None, len(points_3d), inlier_count)

    inlier_ids = inliers[:, 0]
    rotation_vector, translation = cv2.solvePnPRefineLM(
        points_3d[inlier_ids],
        points_2d[inlier_ids],
        _camera_matrix(target),
        None,
        rotation_vector,
        translation,
    )
    rotation, _ = cv2.Rodrigues(rotation_vector)
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = rotation
    transform[:3, 3] = translation[:, 0]
    return PoseEstimate(transform, len(points_3d), inlier_count)


def verify_static_depth(config, source, targets, poses_cw, source_dynamic_mask=None):
    cfg = config.get("DeferredCommit", {})
    source_depth = np.asarray(source.depth, dtype=np.float32)
    source_rgb = _image_numpy(source)
    dynamic = _mask_numpy(source_dynamic_mask, source_depth.shape)
    height, width = source_depth.shape

    valid = np.isfinite(source_depth) & (source_depth > 0.01) & (~dynamic)
    ys, xs = np.nonzero(valid)
    if len(xs) == 0:
        return np.zeros_like(source_depth), 0

    z = source_depth[ys, xs]
    points_source = np.stack(
        [
            (xs - source.cx) * z / source.fx,
            (ys - source.cy) * z / source.fy,
            z,
            np.ones_like(z),
        ],
        axis=1,
    )
    world_points = (np.linalg.inv(poses_cw[0]) @ points_source.T).T
    support = np.zeros(len(xs), dtype=np.int16)
    fast_support = np.zeros(len(xs), dtype=bool)

    depth_abs = float(cfg.get("depth_abs_m", 0.03))
    depth_rel = float(cfg.get("depth_rel", 0.02))
    color_limit = float(cfg.get("color_l1", 0.15))
    fast_depth = float(cfg.get("fast_depth_abs_m", 0.01))
    fast_color = float(cfg.get("fast_color_l1", 0.05))

    source_color = source_rgb[ys, xs]
    for target, pose_cw in zip(targets, poses_cw[1:]):
        camera_points = (pose_cw @ world_points.T).T[:, :3]
        projected_z = camera_points[:, 2]
        safe_z = np.where(np.abs(projected_z) > 1e-8, projected_z, 1.0)
        u = np.rint(target.fx * camera_points[:, 0] / safe_z + target.cx).astype(int)
        v = np.rint(target.fy * camera_points[:, 1] / safe_z + target.cy).astype(int)
        inside = (
            np.isfinite(camera_points).all(axis=1)
            & (projected_z > 0.01)
            & (u >= 0)
            & (u < target.image_width)
            & (v >= 0)
            & (v < target.image_height)
        )
        ids = np.nonzero(inside)[0]
        if len(ids) == 0:
            continue
        target_depth = np.asarray(target.depth, dtype=np.float32)
        observed = target_depth[v[ids], u[ids]]
        threshold = np.maximum(depth_abs, depth_rel * projected_z[ids])
        depth_ok = np.isfinite(observed) & (observed > 0.01)
        target_dynamic = _mask_numpy(
            getattr(target, "dynamic_mask", None), target_depth.shape
        )
        depth_ok &= ~target_dynamic[v[ids], u[ids]]
        depth_ok &= np.abs(observed - projected_z[ids]) <= threshold

        target_rgb = _image_numpy(target)
        color_error = np.abs(target_rgb[v[ids], u[ids]] - source_color[ids]).mean(
            axis=1
        )
        supported = depth_ok & (color_error <= color_limit)
        support[ids[supported]] += 1
        if bool(cfg.get("fast_promotion", False)):
            fast = depth_ok & (np.abs(observed - projected_z[ids]) <= fast_depth)
            fast &= color_error <= fast_color
            fast_support[ids[fast]] = True

    confirming_views = int(cfg.get("confirming_views", 2))
    promoted = (support >= confirming_views) | fast_support
    result = np.zeros_like(source_depth)
    result[ys[promoted], xs[promoted]] = source_depth[ys[promoted], xs[promoted]]
    return result, int(promoted.sum())


class BootstrapVO:
    def __init__(self, config):
        self.config = config

    def run(self, cameras, dynamic_masks):
        if len(cameras) < 3:
            raise ValueError("BootstrapVO requires three RGB-D frames")
        pose0 = np.eye(4, dtype=np.float64)
        pose0[:3, :3] = cameras[0].R.detach().cpu().numpy()
        pose0[:3, 3] = cameras[0].T.detach().cpu().numpy()
        poses = [pose0]
        estimates = []
        for index in range(2):
            estimate = estimate_relative_pose(
                self.config, cameras[index], cameras[index + 1], dynamic_masks[index]
            )
            estimates.append(estimate)
            if estimate.transform is None:
                reason = f"pose_pair_{index}_{index + 1}_rejected"
                return self._fallback(cameras, dynamic_masks, poses, estimates, reason)
            poses.append(estimate.transform @ poses[-1])

        initial_depth, confirmed = verify_static_depth(
            self.config,
            cameras[0],
            cameras[1:],
            poses,
            dynamic_masks[0],
        )
        minimum = int(
            self.config.get("BootstrapVO", {}).get("min_confirmed_pixels", 1000)
        )
        if confirmed < minimum:
            return self._fallback(
                cameras,
                dynamic_masks,
                poses,
                estimates,
                "insufficient_confirmed_pixels",
                confirmed,
            )
        return BootstrapResult(poses, initial_depth, False, estimates, confirmed)

    def _fallback(
        self, cameras, dynamic_masks, poses, estimates, reason, confirmed_pixels=0
    ):
        depth = np.asarray(cameras[0].depth, dtype=np.float32).copy()
        depth[_mask_numpy(dynamic_masks[0], depth.shape)] = 0.0
        while len(poses) < len(cameras):
            poses.append(poses[-1].copy())
        return BootstrapResult(
            poses,
            depth,
            True,
            estimates,
            int(confirmed_pixels),
            reason,
        )
