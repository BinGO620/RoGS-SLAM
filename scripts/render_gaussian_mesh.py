import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import open3d as o3d
import torch
from munch import munchify

from gaussian_splatting.gaussian_renderer import render
from gaussian_splatting.scene.gaussian_model import GaussianModel
from gaussian_splatting.utils.graphics_utils import focal2fov, getProjectionMatrix2
from utils.camera_utils import Camera
from utils.geometry_metrics import load_config_from_run, load_geometry_trajectory


def _make_camera(frame_id, c2w, calibration, projection):
    height = int(calibration["height"])
    width = int(calibration["width"])
    w2c = np.linalg.inv(c2w)
    camera = Camera(
        frame_id,
        None,
        None,
        torch.eye(4, device="cuda"),
        projection,
        float(calibration["fx"]),
        float(calibration["fy"]),
        float(calibration["cx"]),
        float(calibration["cy"]),
        focal2fov(float(calibration["fx"]), width),
        focal2fov(float(calibration["fy"]), height),
        height,
        width,
    )
    camera.update_RT(
        torch.tensor(w2c[:3, :3], dtype=torch.float32, device="cuda"),
        torch.tensor(w2c[:3, 3], dtype=torch.float32, device="cuda"),
    )
    return camera


def extract_mesh(
    run_dir,
    frame_stride=5,
    voxel_length=0.02,
    sdf_trunc=0.08,
    depth_trunc=5.0,
    opacity_threshold=0.5,
    min_triangles=100,
):
    config = load_config_from_run(run_dir)
    calibration = config["Dataset"]["Calibration"]
    ids, poses, pose_source = load_geometry_trajectory(run_dir)
    if pose_source == "keyframe_fallback":
        selected = list(range(len(ids)))
        effective_stride = 1
    else:
        effective_stride = max(int(frame_stride), 1)
        selected = list(range(0, len(ids), effective_stride))
        if selected[-1] != len(ids) - 1:
            selected.append(len(ids) - 1)

    ply_path = os.path.join(
        run_dir, "point_cloud", "final_after_opt", "point_cloud.ply"
    )
    if not os.path.exists(ply_path):
        ply_path = os.path.join(run_dir, "point_cloud", "final", "point_cloud.ply")
    if not os.path.exists(ply_path):
        raise FileNotFoundError(f"missing final Gaussian PLY: {ply_path}")

    sh_degree = int(config.get("model_params", {}).get("sh_degree", 0))
    gaussians = GaussianModel(sh_degree, config=config)
    gaussians.load_ply(ply_path)
    pipeline = munchify(config["pipeline_params"])
    background = torch.zeros(3, dtype=torch.float32, device="cuda")
    width = int(calibration["width"])
    height = int(calibration["height"])
    projection = (
        getProjectionMatrix2(
            znear=0.01,
            zfar=100.0,
            fx=float(calibration["fx"]),
            fy=float(calibration["fy"]),
            cx=float(calibration["cx"]),
            cy=float(calibration["cy"]),
            W=width,
            H=height,
        )
        .transpose(0, 1)
        .cuda()
    )

    volume = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=float(voxel_length),
        sdf_trunc=float(sdf_trunc),
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8,
    )
    intrinsic = o3d.camera.PinholeCameraIntrinsic(
        width,
        height,
        float(calibration["fx"]),
        float(calibration["fy"]),
        float(calibration["cx"]),
        float(calibration["cy"]),
    )
    with torch.no_grad():
        for index in selected:
            camera = _make_camera(ids[index], poses[index], calibration, projection)
            package = render(camera, gaussians, pipeline, background)
            if package is None:
                raise RuntimeError("cannot render an empty Gaussian map")
            color = (
                torch.clamp(package["render"], 0.0, 1.0).permute(1, 2, 0).cpu().numpy()
            )
            depth = package["depth"].squeeze().cpu().numpy().astype(np.float32)
            opacity = package["opacity"].squeeze().cpu().numpy()
            valid = (
                np.isfinite(depth)
                & (depth > 0.01)
                & (depth <= float(depth_trunc))
                & (opacity >= float(opacity_threshold))
            )
            depth = np.where(valid, depth, 0.0).astype(np.float32)
            rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                o3d.geometry.Image(
                    np.ascontiguousarray((color * 255.0).astype(np.uint8))
                ),
                o3d.geometry.Image(np.ascontiguousarray(depth)),
                depth_scale=1.0,
                depth_trunc=float(depth_trunc),
                convert_rgb_to_intensity=False,
            )
            volume.integrate(rgbd, intrinsic, np.linalg.inv(poses[index]))

    mesh = volume.extract_triangle_mesh()
    if len(mesh.triangles) == 0:
        raise RuntimeError("TSDF extraction produced an empty mesh")
    triangle_clusters, counts, _ = mesh.cluster_connected_triangles()
    remove = np.asarray(counts)[np.asarray(triangle_clusters)] < int(min_triangles)
    mesh.remove_triangles_by_mask(remove)
    mesh.remove_unreferenced_vertices()
    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_triangles()
    mesh.remove_duplicated_vertices()
    if len(mesh.triangles) == 0:
        raise RuntimeError("mesh cleanup removed every triangle")
    mesh.compute_vertex_normals()

    geometry_dir = os.path.join(run_dir, "geometry")
    os.makedirs(geometry_dir, exist_ok=True)
    mesh_path = os.path.join(geometry_dir, "tsdf_mesh.ply")
    if not o3d.io.write_triangle_mesh(mesh_path, mesh, write_ascii=False):
        raise RuntimeError(f"failed to write mesh: {mesh_path}")
    metadata = {
        "mesh_protocol_version": "gaussian-render-tsdf-v2",
        "source_gaussians": ply_path,
        "pose_source": pose_source,
        "trajectory_frames": len(ids),
        "integrated_frames": len(selected),
        "frame_stride": effective_stride,
        "voxel_length_m": float(voxel_length),
        "sdf_trunc_m": float(sdf_trunc),
        "depth_trunc_m": float(depth_trunc),
        "opacity_threshold": float(opacity_threshold),
        "min_component_triangles": int(min_triangles),
        "vertices": len(mesh.vertices),
        "faces": len(mesh.triangles),
        "mesh_path": mesh_path,
    }
    with open(
        os.path.join(geometry_dir, "mesh_metadata.json"), "w", encoding="utf-8"
    ) as file:
        json.dump(metadata, file, indent=2)
    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--frame-stride", type=int, default=5)
    parser.add_argument("--voxel-length", type=float, default=0.02)
    parser.add_argument("--sdf-trunc", type=float, default=0.08)
    parser.add_argument("--depth-trunc", type=float, default=5.0)
    parser.add_argument("--opacity-threshold", type=float, default=0.5)
    parser.add_argument("--min-triangles", type=int, default=100)
    args = parser.parse_args()
    metadata = extract_mesh(
        args.run_dir,
        frame_stride=args.frame_stride,
        voxel_length=args.voxel_length,
        sdf_trunc=args.sdf_trunc,
        depth_trunc=args.depth_trunc,
        opacity_threshold=args.opacity_threshold,
        min_triangles=args.min_triangles,
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
