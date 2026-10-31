import csv
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np
import open3d as o3d
import pandas as pd
import trimesh
import yaml
from PIL import Image
from plyfile import PlyData
from scipy.spatial import cKDTree


T_BONN_MARKER = np.array(
    [
        [1.0157, 0.1828, -0.2389, 0.0113],
        [0.0009, -0.8431, -0.6413, -0.0098],
        [-0.3009, 0.6147, -0.8085, 0.0111],
        [0.0, 0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)
T_BONN_ROS = np.array(
    [
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)
GEOMETRY_PROTOCOL_VERSION = "mesh-tsdf-v2"


def parse_tum_list(path, skiprows=0):
    return np.loadtxt(path, delimiter=" ", dtype=np.unicode_, skiprows=skiprows)


def associate_frames(tstamp_image, tstamp_depth, tstamp_pose, max_dt=0.08):
    associations = []
    for i, t in enumerate(tstamp_image):
        j = np.argmin(np.abs(tstamp_depth - t))
        k = np.argmin(np.abs(tstamp_pose - t))
        if np.abs(tstamp_depth[j] - t) < max_dt and np.abs(tstamp_pose[k] - t) < max_dt:
            associations.append((i, j, k))
    return associations


def load_tum_associations(dataset_path, frame_rate=32):
    pose_file = "groundtruth.txt"
    if not os.path.isfile(os.path.join(dataset_path, pose_file)):
        pose_file = "pose.txt"
    image_data = parse_tum_list(os.path.join(dataset_path, "rgb.txt"))
    depth_data = parse_tum_list(os.path.join(dataset_path, "depth.txt"))
    pose_data = parse_tum_list(os.path.join(dataset_path, pose_file), skiprows=1)

    tstamp_image = image_data[:, 0].astype(np.float64)
    tstamp_depth = depth_data[:, 0].astype(np.float64)
    tstamp_pose = pose_data[:, 0].astype(np.float64)
    pose_vecs = pose_data[:, 0:].astype(np.float64)
    associations = associate_frames(tstamp_image, tstamp_depth, tstamp_pose)

    indices = [0]
    for i in range(1, len(associations)):
        t0 = tstamp_image[associations[indices[-1]][0]]
        t1 = tstamp_image[associations[i][0]]
        if t1 - t0 > 1.0 / frame_rate:
            indices.append(i)

    frames = []
    for ix in indices:
        i, j, k = associations[ix]
        quat = pose_vecs[k][4:]
        trans = pose_vecs[k][1:4]
        c2w = trimesh.transformations.quaternion_matrix(np.roll(quat, 1))
        c2w[:3, 3] = trans
        frames.append(
            {
                "rgb_path": os.path.join(dataset_path, image_data[i, 1]),
                "depth_path": os.path.join(dataset_path, depth_data[j, 1]),
                "c2w": c2w,
            }
        )
    return frames


def sample_indices(count, target_count, rng):
    if count <= target_count:
        return np.arange(count)
    return rng.choice(count, size=target_count, replace=False)


def read_gaussian_xyz(path, sample_count=None, seed=0):
    ply = PlyData.read(path)
    vertex = ply["vertex"].data
    points = np.column_stack([vertex["x"], vertex["y"], vertex["z"]]).astype(np.float64)
    if sample_count is not None and len(points) > sample_count:
        rng = np.random.default_rng(seed)
        points = points[sample_indices(len(points), sample_count, rng)]
    return points


def read_open3d_points(path, sample_count=None, seed=0):
    pcd = o3d.io.read_point_cloud(path)
    points = np.asarray(pcd.points, dtype=np.float64)
    if sample_count is not None and len(points) > sample_count:
        rng = np.random.default_rng(seed)
        points = points[sample_indices(len(points), sample_count, rng)]
    return points


def read_ply_xyz_sample(path, sample_count=200000, seed=0):
    """Read a deterministic XYZ sample without loading a huge ASCII PLY in memory."""
    with open(path, "rb") as file:
        header = []
        while True:
            line = file.readline()
            if not line:
                raise ValueError(f"invalid PLY header: {path}")
            decoded = line.decode("ascii", errors="strict").strip()
            header.append(decoded)
            if decoded == "end_header":
                break
    format_line = next((line for line in header if line.startswith("format ")), "")
    vertex_line = next(
        (line for line in header if line.startswith("element vertex ")), None
    )
    if vertex_line is None:
        raise ValueError(f"PLY has no vertex element: {path}")
    vertex_count = int(vertex_line.split()[-1])
    if "ascii" not in format_line:
        return read_open3d_points(path, sample_count=sample_count, seed=seed)

    property_names = []
    in_vertex = False
    for line in header:
        if line.startswith("element "):
            in_vertex = line.startswith("element vertex ")
        elif in_vertex and line.startswith("property "):
            property_names.append(line.split()[-1])
    xyz_indices = [property_names.index(axis) for axis in ("x", "y", "z")]
    target_count = min(vertex_count, int(sample_count))
    rng = np.random.default_rng(seed)
    selected = (
        np.arange(vertex_count)
        if target_count == vertex_count
        else np.sort(rng.choice(vertex_count, size=target_count, replace=False))
    )
    points = np.empty((target_count, 3), dtype=np.float64)
    selected_pos = 0
    with open(path, "r", encoding="ascii") as file:
        for line in file:
            if line.strip() == "end_header":
                break
        for vertex_index in range(vertex_count):
            line = file.readline()
            if selected_pos >= target_count:
                break
            if vertex_index != selected[selected_pos]:
                continue
            values = line.split()
            points[selected_pos] = [float(values[index]) for index in xyz_indices]
            selected_pos += 1
    if selected_pos != target_count:
        raise ValueError(f"sampled {selected_pos}/{target_count} vertices from {path}")
    return points


def backproject_depth(depth, fx, fy, cx, cy, stride, max_depth_m):
    ys = np.arange(0, depth.shape[0], stride)
    xs = np.arange(0, depth.shape[1], stride)
    grid_x, grid_y = np.meshgrid(xs, ys)
    z = depth[grid_y, grid_x]
    valid = (z > 0) & (z <= max_depth_m) & np.isfinite(z)
    x = (grid_x[valid] - cx) * z[valid] / fx
    y = (grid_y[valid] - cy) * z[valid] / fy
    return np.column_stack([x, y, z[valid]])


def transform_points(points, transform):
    if len(points) == 0:
        return points
    homo = np.column_stack([points, np.ones(len(points), dtype=np.float64)])
    return (transform @ homo.T).T[:, :3]


def fuse_tum_gt_point_cloud(config, frame_stride=5, pixel_stride=4, max_depth_m=5.0):
    dataset_path = config["Dataset"]["dataset_path"]
    calibration = config["Dataset"]["Calibration"]
    frames = load_tum_associations(dataset_path)
    selected = frames[::frame_stride]

    fx = float(calibration["fx"])
    fy = float(calibration["fy"])
    cx = float(calibration["cx"])
    cy = float(calibration["cy"])
    depth_scale = float(calibration["depth_scale"])
    distorted = bool(calibration.get("distorted", False))
    dist_coeffs = np.array(
        [
            calibration.get("k1", 0.0),
            calibration.get("k2", 0.0),
            calibration.get("p1", 0.0),
            calibration.get("p2", 0.0),
            calibration.get("k3", 0.0),
        ],
        dtype=np.float64,
    )
    camera_matrix = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]])

    fused = []
    for frame in selected:
        depth = (
            np.array(Image.open(frame["depth_path"]), dtype=np.float64) / depth_scale
        )
        if distorted:
            depth = cv2.undistort(depth, camera_matrix, dist_coeffs)
        points_cam = backproject_depth(depth, fx, fy, cx, cy, pixel_stride, max_depth_m)
        fused.append(transform_points(points_cam, frame["c2w"]))
    if not fused:
        return np.empty((0, 3), dtype=np.float64), {
            "num_frames_used": 0,
            "num_gt_points_before_sample": 0,
        }
    points = np.concatenate(fused, axis=0)
    return points, {
        "num_frames_total": len(frames),
        "num_frames_used": len(selected),
        "frame_stride": frame_stride,
        "pixel_stride": pixel_stride,
        "max_depth_m": max_depth_m,
        "depth_scale": depth_scale,
    }


def load_bonn_t0(sequence_path):
    pose_data = parse_tum_list(
        os.path.join(sequence_path, "groundtruth.txt"), skiprows=1
    )
    pose_vec = pose_data[0].astype(np.float64)
    quat = pose_vec[4:]
    trans = pose_vec[1:4]
    t0 = trimesh.transformations.quaternion_matrix(np.roll(quat, 1))
    t0[:3, 3] = trans
    return t0


def align_bonn_reconstruction(points, config):
    dataset_path = config["Dataset"]["dataset_path"]
    t0 = load_bonn_t0(dataset_path)
    t_g = np.linalg.inv(T_BONN_ROS) @ t0 @ T_BONN_ROS @ T_BONN_MARKER
    return transform_points(points, t_g), t_g


def compute_geometry_metrics(
    rec_points, gt_points, sample_count=200000, threshold_m=0.05, seed=0
):
    if len(rec_points) == 0 or len(gt_points) == 0:
        raise ValueError("empty reconstruction or GT point cloud")
    rng = np.random.default_rng(seed)
    rec = rec_points[sample_indices(len(rec_points), sample_count, rng)]
    gt = gt_points[sample_indices(len(gt_points), sample_count, rng)]

    gt_tree = cKDTree(gt)
    rec_to_gt, _ = gt_tree.query(rec, k=1, workers=-1)
    rec_tree = cKDTree(rec)
    gt_to_rec, _ = rec_tree.query(gt, k=1, workers=-1)
    # precision = % reconstruction within threshold of GT (penalizes ghosts/contamination);
    # recall (== completion_ratio) = % GT within threshold of reconstruction (penalizes holes);
    # F-score balances them so neither ghosts nor a sparse map can win one axis alone (codex P-B).
    precision_ratio = float(np.mean(rec_to_gt <= threshold_m) * 100.0)
    recall_ratio = float(np.mean(gt_to_rec <= threshold_m) * 100.0)
    fscore_denom = precision_ratio + recall_ratio
    fscore = 2.0 * precision_ratio * recall_ratio / fscore_denom if fscore_denom > 0 else 0.0
    return {
        "accuracy_cm": round(float(np.mean(rec_to_gt) * 100.0), 4),
        "completion_cm": round(float(np.mean(gt_to_rec) * 100.0), 4),
        "completion_ratio": round(recall_ratio, 4),
        "precision_ratio": round(precision_ratio, 4),
        "fscore": round(fscore, 4),
        "num_rec_points_eval": int(len(rec)),
        "num_gt_points_eval": int(len(gt)),
        "threshold_m": threshold_m,
    }


def write_point_cloud(path, points):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)
    o3d.io.write_point_cloud(path, pcd)


def load_config_from_run(run_dir):
    with open(os.path.join(run_dir, "config.yml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_geometry_trajectory(run_dir):
    full_path = os.path.join(run_dir, "plot", "trj_full_final.json")
    pose_source = "full_estimated_trajectory"
    path = full_path
    if not os.path.exists(path):
        path = os.path.join(run_dir, "plot", "trj_final.json")
        pose_source = "keyframe_fallback"
    if not os.path.exists(path):
        raise FileNotFoundError("missing full and keyframe trajectory JSON")
    with open(path, "r", encoding="utf-8") as file:
        trajectory = json.load(file)
    ids = [int(value) for value in trajectory.get("trj_id", [])]
    poses = [
        np.asarray(value, dtype=np.float64) for value in trajectory.get("trj_est", [])
    ]
    if not ids or len(ids) != len(poses):
        raise ValueError(f"invalid trajectory artifact: {path}")
    return ids, poses, pose_source


def ensure_tsdf_mesh(
    run_dir,
    frame_stride=5,
    voxel_length=0.02,
    sdf_trunc=0.08,
    depth_trunc=5.0,
    opacity_threshold=0.5,
    min_triangles=100,
):
    metadata_path = os.path.join(run_dir, "geometry", "mesh_metadata.json")
    mesh_path = os.path.join(run_dir, "geometry", "tsdf_mesh.ply")
    if os.path.exists(metadata_path) and os.path.exists(mesh_path):
        with open(metadata_path, "r", encoding="utf-8") as file:
            metadata = json.load(file)
        if metadata.get("mesh_protocol_version") == "gaussian-render-tsdf-v2":
            return metadata
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts",
        "render_gaussian_mesh.py",
    )
    command = [
        sys.executable,
        script_path,
        "--run-dir",
        run_dir,
        "--frame-stride",
        str(frame_stride),
        "--voxel-length",
        str(voxel_length),
        "--sdf-trunc",
        str(sdf_trunc),
        "--depth-trunc",
        str(depth_trunc),
        "--opacity-threshold",
        str(opacity_threshold),
        "--min-triangles",
        str(min_triangles),
    ]
    subprocess.run(command, check=True)
    with open(metadata_path, "r", encoding="utf-8") as file:
        return json.load(file)


def sample_mesh_surface(path, sample_count=200000, seed=0):
    mesh = trimesh.load(path, process=False)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError(f"not a non-empty triangle mesh: {path}")
    points, _ = trimesh.sample.sample_surface(mesh, sample_count, seed=seed)
    return np.asarray(points, dtype=np.float64), {
        "mesh_vertices": int(len(mesh.vertices)),
        "mesh_faces": int(len(mesh.faces)),
    }


def evaluate_run_geometry(
    run_dir,
    sample_count=200000,
    seed=0,
    frame_stride=5,
    pixel_stride=4,
    voxel_length=0.02,
    sdf_trunc=0.08,
    depth_trunc=5.0,
    opacity_threshold=0.5,
    min_triangles=100,
):
    started_at = time.perf_counter()
    config = load_config_from_run(run_dir)
    point_cloud_path = os.path.join(
        run_dir, "point_cloud", "final_after_opt", "point_cloud.ply"
    )
    if not os.path.exists(point_cloud_path):
        point_cloud_path = os.path.join(
            run_dir, "point_cloud", "final", "point_cloud.ply"
        )
    gaussian_points = read_gaussian_xyz(
        point_cloud_path, sample_count=sample_count, seed=seed
    )
    mesh_metadata = ensure_tsdf_mesh(
        run_dir,
        frame_stride=frame_stride,
        voxel_length=voxel_length,
        sdf_trunc=sdf_trunc,
        depth_trunc=depth_trunc,
        opacity_threshold=opacity_threshold,
        min_triangles=min_triangles,
    )
    rec_points, mesh_stats = sample_mesh_surface(
        mesh_metadata["mesh_path"], sample_count=sample_count, seed=seed
    )
    dataset_type = config["Dataset"]["type"].lower()

    gt_cache_dir = os.path.join(run_dir, "gt_point_cloud")
    if dataset_type == "tum":
        gt_points, info = fuse_tum_gt_point_cloud(
            config, frame_stride=frame_stride, pixel_stride=pixel_stride
        )
        info["num_gt_points_before_sample"] = int(len(gt_points))
        gt_path = os.path.join(gt_cache_dir, "tum_fused_gt.ply")
        if len(gt_points) > sample_count:
            rng = np.random.default_rng(seed)
            write_points = gt_points[sample_indices(len(gt_points), sample_count, rng)]
        else:
            write_points = gt_points
        write_point_cloud(gt_path, write_points)
        notes = (
            "TUM has no official GT point cloud; GT point cloud is fused from GT poses "
            "and GT depth. Main geometry uses the TSDF mesh surface."
        )
        source_gt = gt_path
    elif dataset_type == "bonn":
        # WARNING (2026-08-02, codex+hermes dual review): the Bonn official GT ply
        # `rgbd_bonn_groundtruth_1mm_section.ply` is NOT in the same world frame as
        # the `groundtruth.txt` poses the SLAM initialises from (it is a
        # CloudCompare/TELECOM-EDF post-processed export, not a pose-fused cloud).
        # A best-fit Umeyama rigid transform leaves a 1.14m systematic residual
        # (tight spread) → F@5cm absolute is ~2-6% (acc ~115cm) = regime-broken.
        # The directional prune-vs-deferred F@5cm is also contaminated (nonlinear,
        # accidental-overlap-dependent). Numbers emitted here are DIAGNOSTIC-ONLY,
        # NOT reportable. The paper leads with vac_depth/vac_psnr (image-space,
        # frame-invariant) + compactness G_def/G_prune + ATE. See
        # results/evidence/p2t_geometry_f5cm_findings.md.
        bonn_root = os.path.dirname(config["Dataset"]["dataset_path"].rstrip("/"))
        gt_path = os.path.join(bonn_root, "rgbd_bonn_groundtruth_1mm_section.ply")
        gt_points = read_ply_xyz_sample(gt_path, sample_count=sample_count, seed=seed)
        rec_points, t_g = align_bonn_reconstruction(rec_points, config)
        gaussian_points, _ = align_bonn_reconstruction(gaussian_points, config)
        info = {
            "bonn_alignment_formula": "T_g = T_ROS^{-1} T_0 T_ROS T_m",
            "bonn_t_g": t_g.tolist(),
        }
        notes = (
            "BONN official GT point cloud; reconstruction aligned with "
            "T_g = T_ROS^{-1} T_0 T_ROS T_m. Main geometry uses the TSDF mesh surface."
        )
        source_gt = gt_path
    else:
        raise ValueError(
            f"unsupported dataset type for geometry metrics: {dataset_type}"
        )

    metrics = compute_geometry_metrics(
        rec_points, gt_points, sample_count=sample_count, threshold_m=0.05, seed=seed
    )
    diagnostic = compute_geometry_metrics(
        gaussian_points,
        gt_points,
        sample_count=sample_count,
        threshold_m=0.05,
        seed=seed,
    )
    metrics.update(info)
    metrics.update(mesh_stats)
    metrics["geometry_protocol_version"] = GEOMETRY_PROTOCOL_VERSION
    metrics["representation"] = "tsdf_mesh_surface"
    metrics["protocol_eligible"] = mesh_metadata["pose_source"] != "keyframe_fallback"
    metrics["pose_source"] = mesh_metadata["pose_source"]
    metrics["source_rec_mesh"] = os.path.abspath(mesh_metadata["mesh_path"])
    metrics["mesh_metadata"] = mesh_metadata
    metrics["diagnostic_gaussian_center_accuracy_cm"] = diagnostic["accuracy_cm"]
    metrics["diagnostic_gaussian_center_completion_cm"] = diagnostic["completion_cm"]
    metrics["diagnostic_gaussian_center_completion_ratio"] = diagnostic[
        "completion_ratio"
    ]
    metrics["source_gt_point_cloud"] = source_gt
    metrics["source_rec_point_cloud"] = point_cloud_path
    metrics["notes_suffix"] = notes
    metrics["geometry_eval_time_s"] = round(time.perf_counter() - started_at, 4)
    if not metrics["protocol_eligible"]:
        metrics["notes_suffix"] += (
            " Full trajectory was unavailable; keyframe trajectory fallback is "
            "diagnostic-only and excluded from formal tables."
        )
    with open(
        os.path.join(run_dir, "mapping_geometry_metrics_v2.json"),
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(metrics, f, indent=4)
    return metrics


def update_csv_row(csv_path, source_dir, updates, append_notes=None):
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    changed = False
    for key in updates:
        if key not in fieldnames:
            fieldnames.append(key)
    for row in rows:
        if os.path.normpath(row.get("source_dir", "")) == os.path.normpath(source_dir):
            for key, value in updates.items():
                row[key] = value
            if append_notes:
                notes = row.get("notes", "")
                if append_notes not in notes:
                    row["notes"] = (notes + "; " + append_notes).strip("; ")
            changed = True
    if changed:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    return changed


def update_mapping_raw_for_run(
    run_dir, metrics, tables_dir="results/tables", source_dir=None
):
    source_dir = os.path.normpath(source_dir or run_dir)
    updates = {
        "accuracy_cm": metrics["accuracy_cm"]
        if metrics["protocol_eligible"]
        else "MISSING",
        "completion_cm": metrics["completion_cm"]
        if metrics["protocol_eligible"]
        else "MISSING",
        "completion_ratio": metrics["completion_ratio"]
        if metrics["protocol_eligible"]
        else "MISSING",
        "precision_ratio": metrics.get("precision_ratio", "MISSING")
        if metrics["protocol_eligible"]
        else "MISSING",
        "fscore_5cm": metrics.get("fscore", "MISSING")
        if metrics["protocol_eligible"]
        else "MISSING",
        "method_raw_geometry_sample_points": metrics["num_rec_points_eval"],
        "method_raw_geometry_gt_points": metrics["num_gt_points_eval"],
        "method_raw_geometry_threshold_m": metrics["threshold_m"],
        "method_raw_geometry_source_gt": metrics["source_gt_point_cloud"],
        "method_raw_geometry_protocol_version": metrics["geometry_protocol_version"],
        "method_raw_geometry_representation": metrics["representation"],
        "method_raw_geometry_pose_source": metrics["pose_source"],
        "method_raw_geometry_protocol_eligible": metrics["protocol_eligible"],
        "method_raw_geometry_mesh_path": metrics["source_rec_mesh"],
        "method_raw_geometry_mesh_vertices": metrics["mesh_vertices"],
        "method_raw_geometry_mesh_faces": metrics["mesh_faces"],
        "method_raw_gaussian_center_accuracy_cm": metrics[
            "diagnostic_gaussian_center_accuracy_cm"
        ],
        "method_raw_gaussian_center_completion_cm": metrics[
            "diagnostic_gaussian_center_completion_cm"
        ],
        "method_raw_gaussian_center_completion_ratio": metrics[
            "diagnostic_gaussian_center_completion_ratio"
        ],
    }
    changed_global = update_csv_row(
        os.path.join(tables_dir, "mapping_raw.csv"),
        source_dir,
        updates,
        append_notes=metrics["notes_suffix"],
    )
    changed_run = update_csv_row(
        os.path.join(run_dir, "mapping_raw.csv"),
        source_dir,
        updates,
        append_notes=metrics["notes_suffix"],
    )
    return changed_global or changed_run


def mapping_geometry_artifacts_complete(run_dir):
    geometry_json = os.path.join(run_dir, "mapping_geometry_metrics_v2.json")
    if not os.path.exists(geometry_json):
        return False
    try:
        with open(geometry_json, "r", encoding="utf-8") as f:
            metrics = json.load(f)
    except Exception:
        return False
    required = ("accuracy_cm", "completion_cm", "completion_ratio")
    mesh_path = metrics.get("source_rec_mesh")
    if mesh_path and not os.path.isabs(mesh_path):
        mesh_path = os.path.join(run_dir, mesh_path)
    return (
        metrics.get("geometry_protocol_version") == GEOMETRY_PROTOCOL_VERSION
        and metrics.get("representation") == "tsdf_mesh_surface"
        and metrics.get("protocol_eligible") is True
        and bool(mesh_path)
        and os.path.exists(mesh_path)
        and int(metrics.get("mesh_faces", 0)) > 0
        and all(metrics.get(key) not in (None, "", "MISSING") for key in required)
    )


def discover_run_dirs(root):
    run_dirs = []
    for dirpath, _, filenames in os.walk(root):
        if "mapping_raw.csv" in filenames and "config.yml" in filenames:
            run_dirs.append(dirpath)
    return sorted(run_dirs)


def rewrite_table_with_existing_schema(raw_path):
    if not os.path.exists(raw_path):
        return
    df = pd.read_csv(raw_path, dtype=str)
    df.to_csv(raw_path, index=False, quoting=csv.QUOTE_MINIMAL)
