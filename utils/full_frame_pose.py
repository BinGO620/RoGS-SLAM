import csv
import json
import os
import time
from dataclasses import asdict, dataclass

import cv2
import numpy as np
import torch

from utils.pose_utils import SE3_exp


def full_frame_pose_enabled(config):
    return bool(config.get("FullFramePose", {}).get("enabled", False))


@dataclass
class FrameCache:
    frame_id: int
    rgb_u8: np.ndarray
    depth: np.ndarray
    reliable_static: np.ndarray
    pose_cw: np.ndarray
    camera_matrix: np.ndarray


@dataclass
class PoseProposal:
    pose_cw: np.ndarray | None
    accepted: bool
    matches: int
    inliers: int
    inlier_ratio: float
    reprojection_rmse_px: float | None
    static_support_ratio: float
    map_loss_ratio: float | None
    fallback_reason: str | None
    elapsed_ms: float
    source_frame: int | None = None
    rotation_jump_deg: float | None = None
    translation_jump_m: float | None = None


def _pose_cw(camera):
    pose = np.eye(4, dtype=np.float64)
    pose[:3, :3] = camera.R.detach().cpu().numpy()
    pose[:3, 3] = camera.T.detach().cpu().numpy()
    return pose


def _rgb_u8(camera):
    image = camera.original_image.detach().cpu().permute(1, 2, 0).numpy()
    return (np.clip(image, 0.0, 1.0) * 255.0).astype(np.uint8)


def _camera_matrix(camera):
    return np.array(
        [[camera.fx, 0.0, camera.cx], [0.0, camera.fy, camera.cy], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def _rotation_deg(rotation):
    cosine = np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosine)))


def pose_prior_loss(viewpoint, target_pose, proposal, iteration, config):
    cfg = config.get("FullFramePose", {})
    iterations = int(cfg.get("prior_iterations", 20))
    base_weight = float(cfg.get("prior_weight", 0.01))
    if (
        target_pose is None
        or iterations <= 0
        or base_weight <= 0
        or iteration >= iterations
    ):
        return None
    tau = torch.cat([viewpoint.cam_trans_delta, viewpoint.cam_rot_delta], dim=0)
    current = torch.eye(4, device=tau.device, dtype=tau.dtype)
    current[:3, :3] = viewpoint.R
    current[:3, 3] = viewpoint.T
    predicted = SE3_exp(tau) @ current
    target = torch.as_tensor(target_pose, device=tau.device, dtype=tau.dtype)
    rotation_error = (predicted[:3, :3] - target[:3, :3]).square().mean()
    translation_error = (predicted[:3, 3] - target[:3, 3]).square().sum()
    confidence = float(proposal.inlier_ratio) if proposal is not None else 1.0
    anneal = 1.0 - float(iteration) / iterations
    return base_weight * confidence * anneal * (rotation_error + translation_error)


class FullFramePoseManager:
    def __init__(self, config, save_dir=None):
        self.config = config
        self.cfg = config.get("FullFramePose", {})
        self.save_dir = save_dir
        self.cache = []
        self.rows = []

    def cache_frame(self, camera, static_evidence):
        if camera.original_image is None or camera.depth is None:
            return
        item = FrameCache(
            frame_id=int(camera.uid),
            rgb_u8=_rgb_u8(camera),
            depth=np.asarray(camera.depth, dtype=np.float32).copy(),
            reliable_static=static_evidence.reliable_static.detach()
            .cpu()
            .numpy()
            .copy(),
            pose_cw=_pose_cw(camera),
            camera_matrix=_camera_matrix(camera),
        )
        self.cache.append(item)
        offsets = [int(value) for value in self.cfg.get("source_offsets", [1, 2])]
        maximum = max(max(offsets, default=2), 2)
        self.cache = self.cache[-maximum:]

    def propose(self, target, static_evidence, constant_velocity_pose, map_precheck):
        started = time.perf_counter()
        try:
            proposal = self._propose(
                target, static_evidence, constant_velocity_pose, map_precheck
            )
        except cv2.error:
            proposal = self._fallback("opencv_error", static_evidence)
        except (ValueError, FloatingPointError, np.linalg.LinAlgError):
            proposal = self._fallback("invalid_geometry", static_evidence)
        proposal.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return proposal

    def _fallback(self, reason, evidence, **kwargs):
        return PoseProposal(
            pose_cw=None,
            accepted=False,
            matches=int(kwargs.get("matches", 0)),
            inliers=int(kwargs.get("inliers", 0)),
            inlier_ratio=float(kwargs.get("inlier_ratio", 0.0)),
            reprojection_rmse_px=kwargs.get("rmse"),
            static_support_ratio=float(evidence.static_support_ratio),
            map_loss_ratio=kwargs.get("map_ratio"),
            fallback_reason=reason,
            elapsed_ms=0.0,
            source_frame=kwargs.get("source_frame"),
            rotation_jump_deg=kwargs.get("rotation_jump"),
            translation_jump_m=kwargs.get("translation_jump"),
        )

    def _sources(self, target_id):
        offsets = {int(value) for value in self.cfg.get("source_offsets", [1, 2])}
        return [
            item
            for item in reversed(self.cache)
            if target_id - item.frame_id in offsets
        ]

    def _propose(self, target, evidence, constant_pose, map_precheck):
        if target.original_image is None or target.depth is None:
            return self._fallback("missing_rgbd", evidence)
        if evidence.static_support_ratio < float(
            self.cfg.get("min_static_support_ratio", 0.10)
        ):
            return self._fallback("low_static_support", evidence)
        if evidence.conflict_ratio > float(self.cfg.get("max_conflict_ratio", 0.60)):
            return self._fallback("high_conflict", evidence)
        sources = self._sources(int(target.uid))
        if not sources:
            return self._fallback("cache_miss", evidence)

        target_gray = cv2.cvtColor(_rgb_u8(target), cv2.COLOR_RGB2GRAY)
        target_mask = (
            evidence.reliable_static.detach().cpu().numpy().astype(np.uint8) * 255
        )
        orb = cv2.ORB_create(nfeatures=int(self.cfg.get("orb_features", 2000)))
        target_kp, target_desc = orb.detectAndCompute(target_gray, target_mask)
        if target_desc is None:
            return self._fallback("no_target_descriptors", evidence)

        best = None
        for source in sources:
            estimate = self._estimate(
                source,
                target_kp,
                target_desc,
                target.camera_matrix
                if hasattr(target, "camera_matrix")
                else _camera_matrix(target),
                orb,
            )
            if estimate is None:
                continue
            if best is None or (estimate[2], -estimate[4]) > (best[2], -best[4]):
                best = estimate
        if best is None:
            return self._fallback("pnp_rejected", evidence)
        source, matches, inliers, relative, rmse = best
        ratio = inliers / max(matches, 1)
        candidate = relative @ source.pose_cw
        if not np.isfinite(candidate).all():
            return self._fallback(
                "nonfinite_pose",
                evidence,
                matches=matches,
                inliers=inliers,
                inlier_ratio=ratio,
                source_frame=source.frame_id,
            )

        jump = candidate @ np.linalg.inv(np.asarray(constant_pose, dtype=np.float64))
        rotation_jump = _rotation_deg(jump[:3, :3])
        translation_jump = float(np.linalg.norm(jump[:3, 3]))
        common = dict(
            matches=matches,
            inliers=inliers,
            inlier_ratio=ratio,
            rmse=rmse,
            source_frame=source.frame_id,
            rotation_jump=rotation_jump,
            translation_jump=translation_jump,
        )
        if rotation_jump > float(self.cfg.get("max_rotation_deg", 12.0)):
            return self._fallback("rotation_gate", evidence, **common)
        if translation_jump > float(self.cfg.get("max_translation_m", 0.20)):
            return self._fallback("translation_gate", evidence, **common)

        candidate_loss = map_precheck(candidate)
        constant_loss = map_precheck(np.asarray(constant_pose, dtype=np.float64))
        if (
            candidate_loss is None
            or constant_loss is None
            or not np.isfinite([candidate_loss, constant_loss]).all()
        ):
            return self._fallback("map_precheck_invalid", evidence, **common)
        map_ratio = float(candidate_loss / max(float(constant_loss), 1e-12))
        common["map_ratio"] = map_ratio
        if map_ratio > float(self.cfg.get("map_loss_ratio_gate", 1.05)):
            return self._fallback("map_precheck_rejected", evidence, **common)
        return PoseProposal(
            candidate,
            True,
            matches,
            inliers,
            ratio,
            rmse,
            float(evidence.static_support_ratio),
            map_ratio,
            None,
            0.0,
            source.frame_id,
            rotation_jump,
            translation_jump,
        )

    def _estimate(self, source, target_kp, target_desc, target_matrix, orb):
        gray = cv2.cvtColor(source.rgb_u8, cv2.COLOR_RGB2GRAY)
        mask = source.reliable_static.astype(np.uint8) * 255
        source_kp, source_desc = orb.detectAndCompute(gray, mask)
        if source_desc is None:
            return None
        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(source_desc, target_desc, k=2)
        ratio_limit = float(self.cfg.get("ratio_test", 0.75))
        matches = [
            pair[0]
            for pair in pairs
            if len(pair) == 2 and pair[0].distance < ratio_limit * pair[1].distance
        ]
        points_3d, points_2d = [], []
        min_depth = float(self.cfg.get("min_depth", 0.05))
        max_depth = float(self.cfg.get("max_depth", 5.0))
        fx, fy = source.camera_matrix[0, 0], source.camera_matrix[1, 1]
        cx, cy = source.camera_matrix[0, 2], source.camera_matrix[1, 2]
        for match in matches:
            u, v = source_kp[match.queryIdx].pt
            x, y = int(round(u)), int(round(v))
            if not (0 <= y < source.depth.shape[0] and 0 <= x < source.depth.shape[1]):
                continue
            z = float(source.depth[y, x])
            if (
                not np.isfinite(z)
                or z < min_depth
                or z > max_depth
                or not source.reliable_static[y, x]
            ):
                continue
            points_3d.append([(u - cx) * z / fx, (v - cy) * z / fy, z])
            points_2d.append(target_kp[match.trainIdx].pt)
        count = len(points_3d)
        if count < 6:
            return None
        object_points = np.asarray(points_3d, dtype=np.float32)
        image_points = np.asarray(points_2d, dtype=np.float32)
        success, rvec, tvec, ids = cv2.solvePnPRansac(
            object_points,
            image_points,
            target_matrix,
            None,
            iterationsCount=int(self.cfg.get("ransac_iterations", 200)),
            reprojectionError=float(self.cfg.get("reprojection_threshold_px", 3.0)),
            confidence=float(self.cfg.get("confidence", 0.999)),
            flags=cv2.SOLVEPNP_EPNP,
        )
        inliers = 0 if ids is None else int(len(ids))
        if (
            not success
            or inliers < int(self.cfg.get("min_inliers", 100))
            or inliers / count < float(self.cfg.get("min_inlier_ratio", 0.30))
        ):
            return None
        inlier_ids = ids[:, 0]
        rvec, tvec = cv2.solvePnPRefineLM(
            object_points[inlier_ids],
            image_points[inlier_ids],
            target_matrix,
            None,
            rvec,
            tvec,
        )
        rotation, _ = cv2.Rodrigues(rvec)
        projected, _ = cv2.projectPoints(
            object_points[inlier_ids], rvec, tvec, target_matrix, None
        )
        rmse = float(
            np.sqrt(
                np.mean(
                    np.sum((projected[:, 0] - image_points[inlier_ids]) ** 2, axis=1)
                )
            )
        )
        relative = np.eye(4, dtype=np.float64)
        relative[:3, :3] = rotation
        relative[:3, 3] = tvec[:, 0]
        return source, count, inliers, relative, rmse

    def record(self, frame_id, proposal):
        row = asdict(proposal)
        row.pop("pose_cw", None)
        row["frame_id"] = int(frame_id)
        self.rows.append(row)

    def flush(self):
        if not self.save_dir:
            return
        directory = os.path.join(self.save_dir, "full_frame_pose")
        os.makedirs(directory, exist_ok=True)
        fields = ["frame_id"] + [
            key
            for key in asdict(
                self._fallback("", type("E", (), {"static_support_ratio": 0.0})())
            ).keys()
            if key != "pose_cw"
        ]
        with open(
            os.path.join(directory, "proposals.csv"), "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(self.rows)
        accepted = sum(bool(row["accepted"]) for row in self.rows)
        reasons = {}
        for row in self.rows:
            reason = row.get("fallback_reason")
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
        summary = {
            "protocol_version": "full-frame-pose-v1",
            "proposals": len(self.rows),
            "accepted": accepted,
            "acceptance_ratio": accepted / max(len(self.rows), 1),
            "fallback_reasons": reasons,
            "elapsed_ms_total": sum(float(row["elapsed_ms"]) for row in self.rows),
        }
        with open(
            os.path.join(directory, "summary.json"), "w", encoding="utf-8"
        ) as file:
            json.dump(summary, file, indent=2)
