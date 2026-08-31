"""Fixed external-trajectory oracle (``Oracle.pose_file``).

Injects a borrowed trajectory (e.g. RGD-SLAM's published estimate) so a run
becomes MAPPING-ONLY: the frontend skips Adam tracking exactly like the
``Oracle.gt_pose`` diagnostic, but the pose comes from an external per-frame
file instead of dataset GT. This decouples map/admission quality from the
tracker (the "tracker-orthogonal map-admission" experiment axis).

File schema (produced by the baseline campaign's checklist tooling):

    {"trj_id": [0..N-1], "trj_est": [N x 4x4], "trj_gt": [N x 4x4]}

with per-frame CAMERA-TO-WORLD homogeneous matrices in the *source repo's*
world frame (rotation blocks may carry a benign uniform scale from their
export path; they are re-orthonormalized here).

Frame-mapping is self-validating: the file's ``trj_gt`` and the dataset's own
GT describe the SAME physical trajectory, so we fit the frame transform on
GT<->GT and REFUSE to run when it does not close (wrong file / frame drop /
convention drift), instead of silently injecting garbage:

  1. world-side similarity ``A`` (s, R_A, t_A) from position-Umeyama,
  2. camera-side constant rotation ``B`` (axes relabel, e.g. Bonn ROS-body vs
     optical) from the chordal mean of ``R_file^T R_A^T R_ours``,
  3. residual gates: position RMSE, max rotation angle (with B), |s-1|.

``trj_est`` is then mapped through (s, R0, t0) and returned as per-frame W2C
(R, t) — the convention of ``Camera.R/T``. The dataset's ``R_gt/T_gt`` are
NEVER touched, so the end-of-run ATE row measures injected-vs-real-GT: it must
reproduce the borrowed tracker's published ATE (built-in sanity anchor).
"""

import json
import os

import numpy as np


def oracle_pose_file(config):
    """Configured external trajectory path ('' = disabled)."""
    return str(config.get("Oracle", {}).get("pose_file", "") or "")


def _orthonormalize(R):
    """Nearest rotation (SVD projection); strips uniform scale from R blocks."""
    U, _, Vt = np.linalg.svd(R)
    sgn = np.eye(3)
    sgn[2, 2] = np.sign(np.linalg.det(U @ Vt))
    return U @ sgn @ Vt


def _rotation_angle_deg(R):
    cos = (np.trace(R) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


def _fit_frame_transform(file_gt_c2w, ours_c2w):
    """Fit ``ours[k] ≈ A @ file[k] @ B`` on GT<->GT (both C2W, same physical traj).

    ``A`` = world-frame similarity (s, R_A, t_A); ``B`` = constant CAMERA-frame
    rotation (axes relabel, e.g. Bonn ROS-body vs optical — zero lever arm).
    Positions only see ``A`` (t_B = 0), so A comes from position-Umeyama; then
    ``R_B[k] = R_file[k]^T R_A^T R_ours[k]`` must be constant across frames —
    its chordal mean is B and its spread is the rotation residual gate (a wrong
    world twist in A cannot be absorbed by any constant B, so pos+rot gates
    together pin the transform).
    """
    R_file = np.stack([_orthonormalize(T[:3, :3]) for T in file_gt_c2w])
    R_ours = ours_c2w[:, :3, :3]

    src = file_gt_c2w[:, :3, 3]
    dst = ours_c2w[:, :3, 3]
    mu_s, mu_d = src.mean(0), dst.mean(0)
    sc, dc = src - mu_s, dst - mu_d
    cov = dc.T @ sc / len(src)
    U, S, Vt = np.linalg.svd(cov)
    sgn = np.eye(3)
    sgn[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R_A = U @ sgn @ Vt
    var_s = float((sc**2).sum() / len(src))
    s = float(np.trace(np.diag(S) @ sgn) / var_s) if var_s > 0 else 1.0
    t_A = mu_d - s * R_A @ mu_s

    mapped = (s * (R_A @ src.T)).T + t_A
    pos_rmse_cm = float(np.sqrt(((mapped - dst) ** 2).sum(1).mean()) * 100.0)

    # camera-frame rotation B: per-frame estimate -> chordal mean -> spread gate
    B_k = np.einsum("nji,jk,nkl->nil", R_file, R_A.T, R_ours)  # R_file^T R_A^T R_ours
    R_B = _orthonormalize(B_k.mean(axis=0))
    rot_deg = [
        _rotation_angle_deg(R_ours[k] @ (R_A @ R_file[k] @ R_B).T)
        for k in range(len(R_file))
    ]
    return s, R_A, t_A, R_B, pos_rmse_cm, float(np.max(rot_deg))


def load_external_trajectory(
    pose_file,
    dataset_w2c_poses,
    max_anchor_rmse_cm=1.0,
    max_anchor_rot_deg=3.0,
    max_scale_dev=0.01,
):
    """Parse + GT-anchor an external trajectory; return per-frame W2C ``(R, t)``.

    ``dataset_w2c_poses``: the loader's GT poses (``dataset.poses``, W2C, (N,4,4)).
    Raises ``ValueError`` on schema/frame-count mismatch or when the GT<->GT
    anchor does not close within the gates (self-validation; never inject
    silently-wrong poses). Returns ``(poses_w2c, info)`` with numpy arrays.
    """
    with open(pose_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in ("trj_id", "trj_est", "trj_gt"):
        if key not in data:
            raise ValueError(f"external trajectory missing '{key}': {pose_file}")
    ids = [int(v) for v in data["trj_id"]]
    est = np.asarray(data["trj_est"], dtype=np.float64)
    gt = np.asarray(data["trj_gt"], dtype=np.float64)
    ours_w2c = np.asarray(dataset_w2c_poses, dtype=np.float64)
    if ids != list(range(len(ids))):
        raise ValueError(f"trj_id not contiguous 0..N-1: {pose_file}")
    if not (len(est) == len(gt) == len(ids)):
        raise ValueError(f"trj_id/trj_est/trj_gt length mismatch: {pose_file}")
    if len(est) != len(ours_w2c):
        raise ValueError(
            f"frame-count mismatch: file has {len(est)}, dataset has "
            f"{len(ours_w2c)} ({os.path.basename(pose_file)}); per-frame index "
            "association requires identical frame sets"
        )
    if est.shape[1:] != (4, 4):
        raise ValueError(f"trj_est entries must be 4x4 matrices: {pose_file}")

    ours_c2w = np.linalg.inv(ours_w2c)
    s, R_A, t_A, R_B, pos_rmse_cm, rot_max_deg = _fit_frame_transform(gt, ours_c2w)
    if pos_rmse_cm > max_anchor_rmse_cm:
        raise ValueError(
            f"GT anchor residual {pos_rmse_cm:.3f}cm > {max_anchor_rmse_cm}cm "
            f"({os.path.basename(pose_file)}): wrong file/convention/frames"
        )
    if rot_max_deg > max_anchor_rot_deg:
        raise ValueError(
            f"GT anchor rotation residual {rot_max_deg:.2f}deg > "
            f"{max_anchor_rot_deg}deg ({os.path.basename(pose_file)})"
        )
    if abs(s - 1.0) > max_scale_dev:
        raise ValueError(
            f"GT anchor scale {s:.5f} deviates >{max_scale_dev} from metric "
            f"({os.path.basename(pose_file)}); depth would not match"
        )

    poses_w2c = []
    for k in range(len(est)):
        R_c2w = R_A @ _orthonormalize(est[k][:3, :3]) @ R_B
        t_c2w = s * (R_A @ est[k][:3, 3]) + t_A
        R_w2c = R_c2w.T
        t_w2c = -R_w2c @ t_c2w
        poses_w2c.append((R_w2c, t_w2c))
    info = {
        "frames": len(poses_w2c),
        "anchor_rmse_cm": pos_rmse_cm,
        "anchor_rot_max_deg": rot_max_deg,
        "scale": s,
    }
    return poses_w2c, info
