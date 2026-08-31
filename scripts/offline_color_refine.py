#!/usr/bin/env python3
"""Offline re-run of the terminal color-refinement pass on a finished run's final PLY,
producing a `final_after_opt/point_cloud.ply` — the paper-grade map the in-run eval
would have rendered — WITHOUT re-running SLAM (trajectory/poses are untouched).

WHY. `slam.py` only saves `final_after_opt` when `Results.eval_rendering` is true (the
`color_refinement` pass lives inside that gate, line ~465/565). The P6 / P2-T / P6-MASON
run configs all have `eval_rendering: false`, so they saved only `point_cloud/final/`.
We already have the full tracked trajectory (`plot/trj_full_final.json`, C2W) and the
final map. The color-refinement pass is a pure photometric (L1+SSIM) refinement of the
Gaussians — it never touches poses — so it can be replayed offline from the saved PLY:
load map → rebuild cameras from the saved poses → run the same 26000-iteration photometric
Adam pass → save under `final_after_opt/`.

This mirrors the exact code path in `utils/slam_backend.py::color_refinement()` for the
default config (TriReliability static-guard OFF, freeze_opacity OFF — our configs are all
default). The one protocol difference from the in-run pass: viewpoints are built from the
FULL trajectory (every frame in trj_full_final) rather than the runtime keyframe set —
the KF indices are not persisted, so an exact bit-identical replay is impossible. Both
are valid "color-refined map" protocols; the offline one is documented here so the reader
knows the supervised view set differs (and is denser). Poses are untouched in either case.

USAGE:
  python offline_color_refine.py <run-timestamp-dir> [--interval N] [--seed N]
    run-timestamp-dir = .../datasets_{tum,bonn}/<cfg>/seed_N/<2026-...>/
    outputs: <run-timestamp-dir>/point_cloud/final_after_opt/point_cloud.ply
"""
import argparse
import json
import os
import sys
import time
import warnings

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def w2c_from_c2w(c2w):
    mat = np.linalg.inv(np.asarray(c2w, dtype=np.float64))
    return mat[:3, :3], mat[:3, 3]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("run_dir")
    parser.add_argument("--interval", type=int, default=None,
                        help="use every N-th frame of trj_full_final as a viewpoint "
                             "(default: all, matching the in-run full-trajectory view)")
    parser.add_argument("--no-prune-nonfinite", action="store_true",
                        help="skip prune_nonfinite_points before refining")
    parser.add_argument("--out-subdir", default="final_after_opt")
    args = parser.parse_args()

    import torch
    import yaml
    from munch import munchify
    from torchmetrics.functional import structural_similarity_index_measure as ssim_fn
    from torchmetrics.image.lpip import LearnedPerceptualImagePatchSimilarity

    from gaussian_splatting.scene.gaussian_model import GaussianModel
    from gaussian_splatting.gaussian_renderer import render
    from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
    from utils.camera_utils import Camera
    from utils.dataset import load_dataset

    run_dir = os.path.normpath(args.run_dir)
    cfg_path = os.path.join(run_dir, "config.yml")
    ply_path = os.path.join(run_dir, "point_cloud", "final", "point_cloud.ply")
    trj_path = os.path.join(run_dir, "plot", "trj_full_final.json")
    for p in (cfg_path, ply_path, trj_path):
        if not os.path.isfile(p):
            raise FileNotFoundError(f"required run artifact missing: {p}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    model_params = munchify(config["model_params"])
    model_params.sh_degree = 3 if config["Training"]["spherical_harmonics"] else 0
    opt_params = munchify(config["opt_params"])
    pipeline_params = munchify(config["pipeline_params"])
    iterations = int(config["Training"].get("color_refinement_iterations", 26000))
    lambda_dssim = float(opt_params.lambda_dssim)

    dataset = load_dataset(model_params, model_params.source_path, config=config)
    gaussians = GaussianModel(model_params.sh_degree, config=config)
    gaussians.load_ply(ply_path)   # must come BEFORE training_setup: load_ply REPLACES
    gaussians.init_lr(6.0)          # the _xyz/opacity/etc Parameter objects, so the
    gaussians.training_setup(opt_params)  # optimizer must be built AFTER to steer them

    if not args.no_prune_nonfinite:
        n_bad = gaussians.prune_nonfinite_points()
        print(f"prune_nonfinite: removed {n_bad}", flush=True)

    with open(trj_path, "r", encoding="utf-8") as f:
        trj = json.load(f)
    pose_by_id = {
        int(fid): np.asarray(c2w, dtype=np.float64)
        for fid, c2w in zip(trj["trj_id"], trj["trj_est"])
    }
    frame_ids = sorted(pose_by_id.keys())
    if args.interval is not None:
        frame_ids = frame_ids[:: args.interval]

    projection_matrix = (
        getProjectionMatrix2(
            znear=0.01, zfar=100.0, fx=dataset.fx, fy=dataset.fy,
            cx=dataset.cx, cy=dataset.cy, W=dataset.width, H=dataset.height,
        )
        .transpose(0, 1)
        .to(device=dataset.device)
    )
    background = torch.tensor([0, 0, 0], dtype=torch.float32, device="cuda")

    # Build viewpoints from the FULL saved trajectory (not the runtime KF set — those
    # indices are not persisted). Each viewpoint carries original_image = GT RGB so the
    # photometric loss is against ground truth, exactly like the in-run pass.
    viewpoints = {}
    for fid in frame_ids:
        c2w = pose_by_id[fid]
        rotation, translation = w2c_from_c2w(c2w)
        cam = Camera(
            int(fid), None, None,
            torch.eye(4, device=dataset.device), projection_matrix,
            dataset.fx, dataset.fy, dataset.cx, dataset.cy,
            dataset.fovx, dataset.fovy, dataset.height, dataset.width,
            device=dataset.device,
        )
        cam.update_RT(
            torch.from_numpy(np.ascontiguousarray(rotation)).float(),
            torch.from_numpy(np.ascontiguousarray(translation)).float(),
        )
        cam.cam_rot_delta = None
        cam.cam_trans_delta = None
        cam.exposure_a = None
        cam.exposure_b = None
        gt_image, _, _ = dataset[fid]
        cam.original_image = gt_image
        viewpoints[int(fid)] = cam
    print(f"built {len(viewpoints)} viewpoints from trj_full_final", flush=True)

    # Replicate color_refinement's photometric Adam loop (default static-guard OFF).
    t0 = time.perf_counter()
    for it in range(1, iterations + 1):
        # keyed RNG for reproducibility independent of python global seed
        pick = int(np.random.default_rng(it * 7919).choice(len(frame_ids)))
        cam = viewpoints[frame_ids[pick]]
        render_pkg = render(cam, gaussians, pipeline_params, background)
        image = render_pkg["render"]
        visibility_filter = render_pkg["visibility_filter"]
        radii = render_pkg["radii"]
        gt_image = cam.original_image.to(device=image.device, dtype=image.dtype)
        Ll1 = torch.abs(image - gt_image).mean()
        loss = (1.0 - lambda_dssim) * Ll1 + lambda_dssim * (
            1.0 - ssim_fn(
                image[None].clamp(0, 1), gt_image[None].clamp(0, 1)
            ).mean()
        )
        loss.backward()
        with torch.no_grad():
            gaussians.max_radii2D[visibility_filter] = torch.max(
                gaussians.max_radii2D[visibility_filter], radii[visibility_filter]
            )
            gaussians.optimizer.step()
            gaussians.optimizer.zero_grad(set_to_none=True)
            gaussians.update_learning_rate(it)
        if it % 5000 == 0:
            print(f"refine iter {it}/{iterations} loss {loss.item():.4f} t={time.perf_counter()-t0:.1f}s", flush=True)
    print(f"color refinement done in {time.perf_counter()-t0:.1f}s", flush=True)

    out_dir = os.path.join(run_dir, "point_cloud", args.out_subdir)
    # The offline render batch previously placed a symlink final_after_opt -> final for
    # r2_p2_t_offline_render (which hardcodes final_after_opt). We must WRITE a real
    # dir here, so drop any prior adapter symlink (a stale one breaks makedirs/exists).
    if os.path.islink(out_dir):
        os.unlink(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    gaussians.save_ply(os.path.join(out_dir, "point_cloud.ply"))
    print("wrote", os.path.join(out_dir, "point_cloud.ply"), "n_gaussians",
          int(gaussians.get_xyz.shape[0]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
