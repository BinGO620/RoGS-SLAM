import json
import os
import csv
import collections

import cv2
import numpy as np
import torch
from evo.core import metrics, trajectory
from evo.core.trajectory import PosePath3D
from evo.tools import plot as evo_plot
from matplotlib import pyplot as plt
from torchmetrics.image.lpip import LearnedPerceptualImagePatchSimilarity

import wandb
from gaussian_splatting.gaussian_renderer import render
from gaussian_splatting.utils.image_utils import psnr
from gaussian_splatting.utils.loss_utils import ssim
from gaussian_splatting.utils.system_utils import mkdir_p
from utils.logging_utils import Log
from utils.reliable_tracking import reliable_tracking_efficiency_fields
from utils.reliability import reliability_efficiency_fields, reliability_raw_fields
from utils.semantic_mask import semantic_efficiency_fields
from utils.tri_reliability import (
    tri_reliability_efficiency_fields,
    tri_reliability_raw_fields,
)


def _write_csv_row(path, row):
    if path is None:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        fieldnames = list(row.keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerow(row)
        return

    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        existing_rows = []
        for existing_row in reader:
            existing_row.pop(None, None)
            existing_rows.append(existing_row)

    if not fieldnames:
        fieldnames = list(row.keys())
    missing_fields = [key for key in row if key not in fieldnames]
    if missing_fields:
        fieldnames.extend(missing_fields)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing_rows)
            writer.writerow(row)
        os.replace(tmp_path, path)
        return

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writerow(row)


def _common_raw_fields(config, run_id, status="OK", notes=""):
    dataset_path = config["Dataset"]["dataset_path"]
    sequence = config["Dataset"].get("sequence")
    if sequence is None:
        sequence = os.path.basename(dataset_path.rstrip("/"))
    return {
        "method": config.get("method", "MonoGS"),
        "dataset": config["Dataset"]["type"].upper(),
        "sequence": sequence,
        "seed": config.get("seed", 0),
        "run_id": run_id,
        "status": status,
        "notes": notes,
    }


def _pose_path_length(poses):
    if len(poses) < 2:
        return 0.0
    points = np.asarray([pose[:3, 3] for pose in poses])
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _evaluate_trajectories(poses_gt, poses_est, monocular=False):
    traj_ref = PosePath3D(poses_se3=poses_gt)
    traj_est = PosePath3D(poses_se3=poses_est)
    traj_est_aligned = trajectory.align_trajectory(
        traj_est, traj_ref, correct_scale=monocular
    )
    ape_metric = metrics.APE(metrics.PoseRelation.translation_part)
    ape_metric.process_data((traj_ref, traj_est_aligned))
    rpe_metric = metrics.RPE(metrics.PoseRelation.translation_part)
    rpe_metric.process_data((traj_ref, traj_est_aligned))
    return (
        traj_ref,
        traj_est_aligned,
        ape_metric,
        ape_metric.get_all_statistics(),
        rpe_metric.get_all_statistics(),
    )


def _compute_depth_l1_cm(render_depth, gt_depth):
    if gt_depth is None:
        return None
    depth = render_depth.squeeze()
    gt_depth_t = torch.as_tensor(gt_depth, device=depth.device, dtype=depth.dtype)
    valid = (gt_depth_t > 0) & torch.isfinite(gt_depth_t) & torch.isfinite(depth)
    if not valid.any():
        return None
    return torch.mean(torch.abs(depth[valid] - gt_depth_t[valid])).item() * 100.0


def _undistort_depth_like(dataset, depth):
    """Undistort a raw gt depth map into the dataset's undistorted (render) pixel space.

    The loader undistorts RGB but returns RAW depth (``utils/dataset.py``); the frozen
    GTMC mask and the Gaussian render both live in undistorted space, so the P-A static
    support must co-register depth there too. NEAREST (never LINEAR: interpolating across
    a depth discontinuity fabricates mid-depths). No-op when the dataset is undistorted.
    """
    if depth is None:
        return None
    map1x = getattr(dataset, "map1x", None)
    map1y = getattr(dataset, "map1y", None)
    if getattr(dataset, "disorted", False) and map1x is not None and map1y is not None:
        return cv2.remap(
            np.asarray(depth, dtype=np.float32), map1x, map1y, cv2.INTER_NEAREST
        )
    return depth


def evaluate_evo(poses_gt, poses_est, plot_dir, label, monocular=False):
    ## Plot
    traj_ref, traj_est_aligned, ape_metric, ape_stats, _ = _evaluate_trajectories(
        poses_gt, poses_est, monocular=monocular
    )

    ## RMSE
    ape_stat = ape_metric.get_statistic(metrics.StatisticsType.rmse)
    Log("RMSE ATE \[m]", ape_stat, tag="Eval")

    with open(
        os.path.join(plot_dir, "stats_{}.json".format(str(label))),
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(ape_stats, f, indent=4)

    plot_mode = evo_plot.PlotMode.xy
    fig = plt.figure()
    ax = evo_plot.prepare_axis(fig, plot_mode)
    ax.set_title(f"ATE RMSE: {ape_stat}")
    evo_plot.traj(ax, plot_mode, traj_ref, "--", "gray", "gt")
    original_colorbar = fig.colorbar

    def colorbar_with_axis(mappable, *args, **kwargs):
        kwargs.setdefault("ax", ax)
        return original_colorbar(mappable, *args, **kwargs)

    fig.colorbar = colorbar_with_axis
    evo_plot.traj_colormap(
        ax,
        traj_est_aligned,
        ape_metric.error,
        plot_mode,
        min_map=ape_stats["min"],
        max_map=ape_stats["max"],
    )
    fig.colorbar = original_colorbar
    ax.legend()
    plt.savefig(os.path.join(plot_dir, "evo_2dplot_{}.png".format(str(label))), dpi=90)
    plt.close(fig)

    return ape_stat


def eval_ate(frames, kf_ids, save_dir, iterations, final=False, monocular=False):
    trj_data = dict()
    latest_frame_idx = kf_ids[-1] + 2 if final else kf_ids[-1] + 1
    trj_id, trj_est, trj_gt = [], [], []
    trj_est_np, trj_gt_np = [], []

    def gen_pose_matrix(R, T):
        pose = np.eye(4)
        pose[0:3, 0:3] = R.cpu().numpy()
        pose[0:3, 3] = T.cpu().numpy()
        return pose

    for kf_id in kf_ids:
        kf = frames[kf_id]
        pose_est = np.linalg.inv(gen_pose_matrix(kf.R, kf.T))
        pose_gt = np.linalg.inv(gen_pose_matrix(kf.R_gt, kf.T_gt))

        trj_id.append(frames[kf_id].uid)
        trj_est.append(pose_est.tolist())
        trj_gt.append(pose_gt.tolist())

        trj_est_np.append(pose_est)
        trj_gt_np.append(pose_gt)

    trj_data["trj_id"] = trj_id
    trj_data["trj_est"] = trj_est
    trj_data["trj_gt"] = trj_gt

    plot_dir = os.path.join(save_dir, "plot")
    mkdir_p(plot_dir)

    label_evo = "final" if final else "{:04}".format(iterations)
    with open(
        os.path.join(plot_dir, f"trj_{label_evo}.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(trj_data, f, indent=4)

    ate = evaluate_evo(
        poses_gt=trj_gt_np,
        poses_est=trj_est_np,
        plot_dir=plot_dir,
        label=label_evo,
        monocular=monocular,
    )
    wandb.log({"frame_idx": latest_frame_idx, "ate": ate})
    return ate


def _save_per_frame_ape(save_dir, sorted_frame_ids, frames, kf_ids, ape_metric):
    """Write per-frame APE with keyframe/dist-to-KF/mask-coverage strata.

    ape_metric.error is the per-frame translation error (m) in the same order as
    sorted_frame_ids (the order poses were fed to _evaluate_trajectories).
    """
    errors = np.asarray(ape_metric.error)
    kf_set = set(kf_ids or [])
    kf_sorted = sorted(kf_set)

    def nearest_kf_dist(fid):
        if not kf_sorted:
            return "MISSING"
        return int(min(abs(fid - k) for k in kf_sorted))

    def mask_coverage(frame):
        # Prefer the per-frame float captured in tracking() (survives clean()); fall
        # back to the cached keyframe mask tensor for older runs / keyframes.
        cov = getattr(frame, "dyn_coverage", None)
        if cov is not None:
            try:
                return round(float(cov), 6)
            except Exception:
                pass
        m = getattr(frame, "dynamic_mask", None)
        if m is None:
            return ""
        try:
            return round(float(m.float().mean().item()), 6)
        except Exception:
            return ""

    out_path = os.path.join(save_dir, "per_frame_ape.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "frame_id",
                "uid",
                "is_keyframe",
                "dist_to_nearest_kf",
                "mask_coverage",
                "ape_cm",
            ]
        )
        for i, fid in enumerate(sorted_frame_ids):
            frame = frames[fid]
            ape_cm = round(float(errors[i]) * 100.0, 4) if i < len(errors) else ""
            writer.writerow(
                [
                    fid,
                    getattr(frame, "uid", fid),
                    int(fid in kf_set),
                    nearest_kf_dist(fid),
                    mask_coverage(frame),
                    ape_cm,
                ]
            )

    # Console summary: the decisive kf-vs-nonkf split + dist-to-KF trend.
    is_kf = np.array([fid in kf_set for fid in sorted_frame_ids])
    n = min(len(errors), len(is_kf))
    err_cm = errors[:n] * 100.0
    is_kf = is_kf[:n]
    kf_rmse = (
        float(np.sqrt(np.mean(err_cm[is_kf] ** 2))) if is_kf.any() else float("nan")
    )
    nk_rmse = (
        float(np.sqrt(np.mean(err_cm[~is_kf] ** 2))) if (~is_kf).any() else float("nan")
    )
    Log(
        f"per-frame APE: KF-RMSE={kf_rmse:.2f}cm ({int(is_kf.sum())} kf) vs "
        f"nonKF-RMSE={nk_rmse:.2f}cm ({int((~is_kf).sum())} nonkf) -> {out_path}",
        tag="Eval",
    )


def save_final_tracking_raw(frames, kf_ids, save_dir, config, monocular=False):
    if not config["Results"].get("save_raw_metrics", False):
        return None

    def gen_pose_matrix(R, T):
        pose = np.eye(4)
        pose[0:3, 0:3] = R.detach().cpu().numpy()
        pose[0:3, 3] = T.detach().cpu().numpy()
        return pose

    sorted_frame_ids = sorted(frames.keys())
    poses_est, poses_gt = [], []
    for frame_id in sorted_frame_ids:
        frame = frames[frame_id]
        poses_est.append(np.linalg.inv(gen_pose_matrix(frame.R, frame.T)))
        poses_gt.append(np.linalg.inv(gen_pose_matrix(frame.R_gt, frame.T_gt)))

    plot_dir = os.path.join(save_dir, "plot")
    mkdir_p(plot_dir)
    with open(
        os.path.join(plot_dir, "trj_full_final.json"), "w", encoding="utf-8"
    ) as file:
        json.dump(
            {
                "trajectory_protocol_version": "full-estimated-v1",
                "trj_id": sorted_frame_ids,
                "trj_est": [pose.tolist() for pose in poses_est],
                "trj_gt": [pose.tolist() for pose in poses_gt],
            },
            file,
            indent=2,
        )

    _, _, ape_metric, ape_stats, rpe_stats = _evaluate_trajectories(
        poses_gt, poses_est, monocular=monocular
    )

    # Diagnostic (default-off): dump per-frame APE stratified by is_keyframe /
    # distance-to-nearest-keyframe / dynamic-mask coverage, to locate whether the
    # kf-vs-full ATE gap is structural non-keyframe drift or mask-gap spikes.
    if config["Results"].get("save_per_frame_ape", False):
        try:
            _save_per_frame_ape(save_dir, sorted_frame_ids, frames, kf_ids, ape_metric)
        except Exception as exc:  # never let a diagnostic break a run
            Log(f"per-frame APE dump failed: {exc}", tag="Eval")
    gt_len = _pose_path_length(poses_gt)
    path_ratio = (
        _pose_path_length(poses_est) / gt_len * 100.0 if gt_len > 0 else "MISSING"
    )

    keyframe_ate = "MISSING"
    if kf_ids:
        kf_est, kf_gt = [], []
        for kf_id in kf_ids:
            frame = frames[kf_id]
            kf_est.append(np.linalg.inv(gen_pose_matrix(frame.R, frame.T)))
            kf_gt.append(np.linalg.inv(gen_pose_matrix(frame.R_gt, frame.T_gt)))
        _, _, _, kf_ape_stats, _ = _evaluate_trajectories(
            kf_gt, kf_est, monocular=monocular
        )
        keyframe_ate = kf_ape_stats["rmse"] * 100.0

    # ORB/DynaSLAM-style full-trajectory recomposition (default-off): recompose each
    # non-KF pose as T_rel @ Tcw_refkf_optimized so it inherits the reference keyframe's
    # backend BA correction. This is the standard full-traj export (CameraTrajectory.txt),
    # NOT an online number -- it stays comparable to competitors' reported ATE.
    kf_prop_ate = "MISSING"
    kf_set = set(kf_ids or [])
    if config.get("FinalTrajectory", {}).get("kf_propagate", False):
        est_prop, n_recomposed = [], 0
        for frame_id in sorted_frame_ids:
            frame = frames[frame_id]
            Tcw = gen_pose_matrix(frame.R, frame.T)  # online pose
            ref_id = getattr(frame, "ref_kf_id", None)
            T_rel = getattr(frame, "T_rel_to_refkf", None)
            if frame_id not in kf_set and ref_id is not None and T_rel is not None:
                ref = frames.get(ref_id)
                if ref is not None:
                    Tcw = np.asarray(T_rel) @ gen_pose_matrix(ref.R, ref.T)
                    n_recomposed += 1
            est_prop.append(np.linalg.inv(Tcw))
        try:
            _, _, _, prop_ape_stats, _ = _evaluate_trajectories(
                poses_gt, est_prop, monocular=monocular
            )
            kf_prop_ate = prop_ape_stats["rmse"] * 100.0
            Log(
                f"KF-propagated full ATE={kf_prop_ate:.2f}cm (recomposed "
                f"{n_recomposed}/{len(sorted_frame_ids)} non-KFs) vs online "
                f"{ape_stats['rmse'] * 100.0:.2f}cm",
                tag="Eval",
            )
        except Exception as exc:
            Log(f"KF-propagated ATE failed: {exc}", tag="Eval")

    success_threshold_cm = config["Results"].get("success_threshold_cm", 5.0)
    ate_cm = ape_stats["rmse"] * 100.0
    row = {
        **_common_raw_fields(
            config,
            os.path.basename(save_dir),
            notes="final trajectory from MonoGS run",
        ),
        "ate_rmse_cm": round(ate_cm, 4),
        "ate_error_std_cm": round(ape_stats["std"] * 100.0, 4),
        "rpe_trans_rmse_cm": round(rpe_stats["rmse"] * 100.0, 4),
        "path_length_ratio": round(path_ratio, 4)
        if isinstance(path_ratio, float)
        else path_ratio,
        "success_by_threshold": int(ate_cm <= success_threshold_cm),
        "success_threshold_cm": success_threshold_cm,
        "keyframe_ate_rmse_cm": round(keyframe_ate, 4)
        if isinstance(keyframe_ate, float)
        else keyframe_ate,
        "kf_propagated_ate_rmse_cm": round(kf_prop_ate, 4)
        if isinstance(kf_prop_ate, float)
        else kf_prop_ate,
        **reliability_raw_fields(save_dir, "tracking"),
        **tri_reliability_raw_fields(save_dir, "tracking"),
        "source_dir": save_dir,
    }
    _write_csv_row(config["Results"].get("tracking_raw_path"), row)
    _write_csv_row(os.path.join(save_dir, "tracking_raw.csv"), row)
    return row


def eval_rendering(
    frames,
    gaussians,
    dataset,
    save_dir,
    pipe,
    background,
    kf_indices,
    iteration="final",
):
    interval = 5
    img_pred, img_gt, saved_frame_idx = [], [], []
    end_idx = len(frames) - 1 if iteration == "final" or "before_opt" else iteration
    psnr_array, ssim_array, lpips_array, depth_l1_array = [], [], [], []
    cal_lpips = LearnedPerceptualImagePatchSimilarity(
        net_type="alex", normalize=True
    ).to("cuda")
    for idx in range(0, end_idx, interval):
        if idx in kf_indices:
            continue
        saved_frame_idx.append(idx)
        frame = frames[idx]
        gt_image, gt_depth, _ = dataset[idx]

        render_pkg = render(frame, gaussians, pipe, background)
        rendering = render_pkg["render"]
        image = torch.clamp(rendering, 0.0, 1.0)

        gt = (gt_image.cpu().numpy().transpose((1, 2, 0)) * 255).astype(np.uint8)
        pred = (image.detach().cpu().numpy().transpose((1, 2, 0)) * 255).astype(
            np.uint8
        )
        gt = cv2.cvtColor(gt, cv2.COLOR_BGR2RGB)
        pred = cv2.cvtColor(pred, cv2.COLOR_BGR2RGB)
        img_pred.append(pred)
        img_gt.append(gt)

        mask = gt_image > 0

        psnr_score = psnr((image[mask]).unsqueeze(0), (gt_image[mask]).unsqueeze(0))
        ssim_score = ssim((image).unsqueeze(0), (gt_image).unsqueeze(0))
        lpips_score = cal_lpips((image).unsqueeze(0), (gt_image).unsqueeze(0))
        depth_l1_cm = _compute_depth_l1_cm(render_pkg["depth"], gt_depth)

        psnr_array.append(psnr_score.item())
        ssim_array.append(ssim_score.item())
        lpips_array.append(lpips_score.item())
        if depth_l1_cm is not None:
            depth_l1_array.append(depth_l1_cm)

    output = dict()

    def _finite_mean(vals):
        arr = np.asarray(vals, dtype=float)
        finite = arr[np.isfinite(arr)]
        return (float(np.mean(finite)) if finite.size else float("nan")), int(
            arr.size - finite.size
        )

    # Robust aggregation: a single non-finite frame (e.g. from a residual Inf-scale
    # Gaussian) would otherwise poison np.mean -> NaN for the whole run.
    output["mean_psnr"], n_drop = _finite_mean(psnr_array)
    output["mean_ssim"], _ = _finite_mean(ssim_array)
    output["mean_lpips"], _ = _finite_mean(lpips_array)
    output["mean_depth_l1_cm"] = (
        float(np.mean(depth_l1_array)) if depth_l1_array else None
    )
    if n_drop:
        Log(
            f"dropped {n_drop}/{len(psnr_array)} non-finite eval frames "
            "(residual Inf/NaN Gaussians)",
            tag="Eval",
        )

    Log(
        f"mean psnr: {output['mean_psnr']}, ssim: {output['mean_ssim']}, "
        f"lpips: {output['mean_lpips']}, depth_l1_cm: {output['mean_depth_l1_cm']}",
        tag="Eval",
    )

    psnr_save_dir = os.path.join(save_dir, "psnr", str(iteration))
    mkdir_p(psnr_save_dir)

    json.dump(
        output,
        open(os.path.join(psnr_save_dir, "final_result.json"), "w", encoding="utf-8"),
        indent=4,
    )
    return output


def save_mapping_raw_from_official_eval(
    config,
    save_dir,
    before_result,
    after_result,
    mask_type="full",
):
    if not config["Results"].get("save_raw_metrics", False):
        return None
    notes = (
        "MonoGS official eval_rendering + color_refinement; main mapping fields use "
        "after_opt values; before_opt values are preserved in method_raw_* columns; "
        "geometry metrics are filled by eval_mapping_geometry after final_after_opt "
        "Gaussian point cloud is saved"
    )
    row = {
        **_common_raw_fields(config, os.path.basename(save_dir), notes=notes),
        "psnr": round(float(after_result["mean_psnr"]), 4),
        "ssim": round(float(after_result["mean_ssim"]), 4),
        "lpips": round(float(after_result["mean_lpips"]), 4),
        "depth_l1_cm": round(float(after_result["mean_depth_l1_cm"]), 4)
        if after_result.get("mean_depth_l1_cm") is not None
        else "MISSING",
        "accuracy_cm": "MISSING",
        "mask_type": mask_type,
        "completion_cm": "MISSING",
        "completion_ratio": "MISSING",
        "method_raw_psnr_before_opt": round(float(before_result["mean_psnr"]), 4),
        "method_raw_ssim_before_opt": round(float(before_result["mean_ssim"]), 4),
        "method_raw_lpips_before_opt": round(float(before_result["mean_lpips"]), 4),
        "method_raw_depth_l1_before_opt": round(
            float(before_result["mean_depth_l1_cm"]), 4
        )
        if before_result.get("mean_depth_l1_cm") is not None
        else "MISSING",
        "method_raw_psnr_after_opt": round(float(after_result["mean_psnr"]), 4),
        "method_raw_ssim_after_opt": round(float(after_result["mean_ssim"]), 4),
        "method_raw_lpips_after_opt": round(float(after_result["mean_lpips"]), 4),
        "method_raw_depth_l1_after_opt": round(
            float(after_result["mean_depth_l1_cm"]), 4
        )
        if after_result.get("mean_depth_l1_cm") is not None
        else "MISSING",
        **reliability_raw_fields(save_dir, "mapping"),
        **tri_reliability_raw_fields(save_dir, "mapping"),
        "source_dir": save_dir,
    }
    _write_csv_row(config["Results"].get("mapping_raw_path"), row)
    _write_csv_row(os.path.join(save_dir, "mapping_raw.csv"), row)
    return row


def eval_final_mapping_raw(
    frames, gaussians, dataset, save_dir, pipe, background, config
):
    if not config["Results"].get("save_raw_metrics", False):
        return None
    frame_ids = sorted(frames.keys())
    interval = config["Results"].get("eval_rendering_interval", 5)
    psnr_array, ssim_array, lpips_array, depth_l1_array = [], [], [], []
    cal_lpips = LearnedPerceptualImagePatchSimilarity(
        net_type="alex", normalize=True
    ).to("cuda")
    for idx in frame_ids[::interval]:
        frame = frames[idx]
        gt_image, gt_depth, _ = dataset[idx]
        render_pkg = render(frame, gaussians, pipe, background)
        image = torch.clamp(render_pkg["render"], 0.0, 1.0)
        depth = render_pkg["depth"].squeeze()
        mask = gt_image > 0
        psnr_array.append(
            psnr((image[mask]).unsqueeze(0), (gt_image[mask]).unsqueeze(0)).item()
        )
        ssim_array.append(ssim(image.unsqueeze(0), gt_image.unsqueeze(0)).item())
        lpips_array.append(cal_lpips(image.unsqueeze(0), gt_image.unsqueeze(0)).item())
        depth_l1_cm = _compute_depth_l1_cm(depth, gt_depth)
        if depth_l1_cm is not None:
            depth_l1_array.append(depth_l1_cm)

    row = {
        **_common_raw_fields(
            config,
            os.path.basename(save_dir),
            notes=(
                f"RGB/depth metrics rendered every {interval} frames along estimated "
                "trajectory; accuracy MISSING until GT point-cloud fusion/alignment is run"
            ),
        ),
        "psnr": round(float(np.mean(psnr_array)), 4) if psnr_array else "MISSING",
        "ssim": round(float(np.mean(ssim_array)), 4) if ssim_array else "MISSING",
        "lpips": round(float(np.mean(lpips_array)), 4) if lpips_array else "MISSING",
        "depth_l1_cm": round(float(np.mean(depth_l1_array)), 4)
        if depth_l1_array
        else "MISSING",
        "accuracy_cm": "MISSING",
        "mask_type": "full",
        "completion_cm": "MISSING",
        "completion_ratio": "MISSING",
        **reliability_raw_fields(save_dir, "mapping"),
        **tri_reliability_raw_fields(save_dir, "mapping"),
        "source_dir": save_dir,
    }
    _write_csv_row(config["Results"].get("mapping_raw_path"), row)
    _write_csv_row(os.path.join(save_dir, "mapping_raw.csv"), row)
    return row


def eval_static_background_raw(
    frames, gaussians, dataset, save_dir, pipe, background, config
):
    """P-A: hole-safe STATIC-BACKGROUND rendering metrics against the frozen, method-
    INDEPENDENT GTMC dynamic mask -> a ``mask_type='static'`` row in ``mapping_raw.csv``.

    DORMANT unless ``config["Results"]["static_bg_mask_subdir"]`` is set (existing runs
    and the other arms are unaffected). When set, the frozen mask for each eval frame is
    read from ``<Dataset.dataset_path>/<subdir>/<depth-stem>.png`` (built offline by
    ``scripts/build_static_eval_mask.py``). The mask is loaded ONLY here, at eval time,
    and is NEVER written to ``frame.dynamic_mask`` -- that field belongs to the SLAM
    method (the learned semantic person mask used for tracking/mapping down-weighting).
    Keeping the two channels separate is what makes the support set
    ``M_static = (gt-depth valid) AND NOT(frozen dynamic)`` method-independent and
    identical for every arm (spec 03-knowledges/11 §0/§5).

    Same frame set + interval as :func:`eval_final_mapping_raw`, rendering the FINAL map
    (post color-refinement, per ``slam.py``). gt depth is undistorted (NEAREST) into the
    render+mask pixel space first, so validity, the dynamic mask, and the render share one
    frame. A frame whose mask is missing is skipped and COUNTED -- never silently scored
    as full-frame 'static'.
    """
    if not config["Results"].get("save_raw_metrics", False):
        return None
    subdir = config["Results"].get("static_bg_mask_subdir")
    if not subdir:
        return None

    from utils.gtmc_mask import frozen_mask_index, load_frozen_mask
    from utils.static_eval import (
        dynamic_band_metrics,
        static_background_metrics,
        vacated_contrast_metrics,
        vacated_region_metrics,
    )

    dataset_path = config["Dataset"].get("dataset_path", "")
    mask_dir = os.path.join(dataset_path, subdir)
    index = frozen_mask_index(mask_dir)
    depth_paths = getattr(dataset, "depth_paths", None)
    if not index or depth_paths is None:
        Log(
            f"P-A static-bg eval skipped: masks@{mask_dir}={len(index)}, "
            f"depth_paths={'none' if depth_paths is None else len(depth_paths)}",
            tag="Eval",
        )
        return None

    frame_ids = sorted(frames.keys())
    interval = config["Results"].get("eval_rendering_interval", 5)
    d_max_cm = float(config["Results"].get("static_bg_d_max_cm", 50.0))
    a_eval = float(config["Results"].get("static_bg_a_eval", 0.5))
    # Recency window for the FRESH-vacated region, in FRAMES. The pre-registered
    # vacated mask unions every earlier dynamic mask with no decay, so on a
    # 439-frame sequence where the mover roams (Bonn balloon) it grows to 84% of
    # the static support / 66% of the image -- "where the mover has EVER been" is
    # the whole scene, which is why static_vacated_depth_l1_pen_cm tracked global
    # map quality instead of ghost. The windowed union is "where the mover was in
    # the last K frames and is not now" = the fresh scar, which is where a ghost
    # actually lives before the map heals over it. 0 disables.
    vac_window = int(config["Results"].get("static_bg_vacated_window_frames", 30))
    cal_lpips = LearnedPerceptualImagePatchSimilarity(
        net_type="alex", normalize=True
    ).to("cuda")

    psnr_a, ssim_a, lpips_a, depth_a, cov_a, support_a = [], [], [], [], [], []
    n_missing, n_empty = 0, 0
    # Additive, dormant unless Results.static_bg_band_px is set: dynamic-adjacent band
    # (discriminating region for the lifecycle ablation). No effect on the static row.
    band_radii = config["Results"].get("static_bg_band_px") or []
    band_acc = {int(r): {"psnr": [], "ssim": [], "depth": [], "support": []} for r in band_radii}
    # Vacated-region (ghost-contamination) metric: union of frozen dynamic masks over
    # ALL frames strictly before the current eval frame ("was dynamic earlier"), scored
    # where the current frozen mask says static. Walks every frame's mask exactly once
    # (not just the eval stride), so the union is exact. Additive: rows without masks
    # or without any vacated pixels are simply not scored (support gating below).
    vac_psnr_a, vac_ssim_a, vac_depth_a, vac_support_a = [], [], [], []
    nonvac_depth_a, nonvac_psnr_a = [], []
    excess_depth_a, excess_psnr_a = [], []
    fresh_psnr_a, fresh_ssim_a, fresh_depth_a, fresh_support_a = [], [], [], []
    fresh_excess_depth_a, fresh_excess_psnr_a = [], []
    recent_masks = collections.deque(maxlen=vac_window) if vac_window > 0 else None
    past_union = None
    union_ptr = 0
    eval_indices = frame_ids[::interval]
    n_eval = len(eval_indices)
    # Heartbeat: this loop renders + LPIPS every Nth frame with no per-frame stdout, so on
    # full-length sequences it can run quiet for >300s and trip the batch runner's log-stall
    # watchdog mid-eval (killing the run before band metrics / final_after_opt / efficiency
    # are saved). Emit a periodic progress line so the watchdog sees liveness. Instrumentation
    # only -- does not touch any metric value and is identical for every arm.
    for i, idx in enumerate(eval_indices):
        if i % 15 == 0:
            Log(f"P-A static-bg eval progress: {i}/{n_eval} frames", tag="Eval")
        if idx >= len(depth_paths):
            n_missing += 1
            continue
        stem = os.path.splitext(os.path.basename(depth_paths[idx]))[0]
        mpath = index.get(stem)
        if mpath is None:
            n_missing += 1
            continue
        frame = frames[idx]
        gt_image, gt_depth, _ = dataset[idx]
        gt_depth_u = _undistort_depth_like(dataset, gt_depth)
        dyn = load_frozen_mask(mpath)
        # Fold every frame strictly BEFORE this eval frame into the past-union
        # (mask load only — no render), then score the vacated region on it.
        while union_ptr < len(frame_ids) and frame_ids[union_ptr] < idx:
            j = frame_ids[union_ptr]
            union_ptr += 1
            if j >= len(depth_paths):
                continue
            jstem = os.path.splitext(os.path.basename(depth_paths[j]))[0]
            jpath = index.get(jstem)
            if jpath is None:
                continue
            jmask = torch.from_numpy(np.asarray(load_frozen_mask(jpath), dtype=bool))
            past_union = jmask if past_union is None else (past_union | jmask)
            if recent_masks is not None:
                recent_masks.append(jmask)
        render_pkg = render(frame, gaussians, pipe, background)
        image = torch.clamp(render_pkg["render"], 0.0, 1.0)
        depth = render_pkg["depth"].squeeze()
        m = static_background_metrics(
            image,
            gt_image,
            depth,
            gt_depth_u,
            dynamic_mask=dyn,
            render_opacity=render_pkg.get("opacity"),
            d_max_cm=d_max_cm,
            a_eval=a_eval,
            lpips_fn=cal_lpips,
        )
        if int(m["static_support_px"]) <= 0:
            n_empty += 1
            continue
        psnr_a.append(m["static_psnr"])
        ssim_a.append(m["static_ssim"])
        lpips_a.append(m.get("static_lpips", float("nan")))
        depth_a.append(m["static_depth_l1_pen_cm"])
        cov_a.append(m["static_coverage"])
        support_a.append(int(m["static_support_px"]))

        if band_radii:
            bm = dynamic_band_metrics(
                image, gt_image, depth, gt_depth_u, dyn, band_radii, d_max_cm=d_max_cm
            )
            for r in band_radii:
                b = bm[f"band{int(r)}"]
                if int(b["support_px"]) <= 0:
                    continue
                band_acc[int(r)]["psnr"].append(b["psnr"])
                band_acc[int(r)]["ssim"].append(b["ssim"])
                band_acc[int(r)]["depth"].append(b["depth_l1_pen_cm"])
                band_acc[int(r)]["support"].append(int(b["support_px"]))

        if past_union is not None:
            vm = vacated_region_metrics(
                image, gt_image, depth, gt_depth_u, dyn, past_union, d_max_cm=d_max_cm
            )
            if int(vm["vacated_support_px"]) > 0:
                vac_psnr_a.append(vm["vacated_psnr"])
                vac_ssim_a.append(vm["vacated_ssim"])
                vac_depth_a.append(vm["vacated_depth_l1_pen_cm"])
                vac_support_a.append(int(vm["vacated_support_px"]))
                # Paired within-frame contrast against this frame's OWN
                # untouched static background. The absolute vacated number is
                # dominated by global map/pose quality (see
                # static_eval.vacated_contrast_metrics); this difference cancels
                # it and isolates the ghost claim.
                cm_ = vacated_contrast_metrics(
                    image,
                    gt_image,
                    depth,
                    gt_depth_u,
                    dyn,
                    past_union,
                    d_max_cm=d_max_cm,
                )
                nonvac_depth_a.append(cm_["nonvacated_depth_l1_pen_cm"])
                nonvac_psnr_a.append(cm_["nonvacated_psnr"])
                excess_depth_a.append(cm_["ghost_excess_depth_l1_cm"])
                excess_psnr_a.append(cm_["ghost_excess_psnr_db"])

        # FRESH-vacated: same construction, but the union only spans the last
        # `vac_window` frames -- the scar the mover just left, before the map
        # heals over it. Scored independently of the unbounded column above so
        # both can be reported side by side.
        if recent_masks:
            recent_union = recent_masks[0]
            for jm in list(recent_masks)[1:]:
                recent_union = recent_union | jm
            fm = vacated_region_metrics(
                image, gt_image, depth, gt_depth_u, dyn, recent_union, d_max_cm=d_max_cm
            )
            if int(fm["vacated_support_px"]) > 0:
                fresh_psnr_a.append(fm["vacated_psnr"])
                fresh_ssim_a.append(fm["vacated_ssim"])
                fresh_depth_a.append(fm["vacated_depth_l1_pen_cm"])
                fresh_support_a.append(int(fm["vacated_support_px"]))
                fc_ = vacated_contrast_metrics(
                    image,
                    gt_image,
                    depth,
                    gt_depth_u,
                    dyn,
                    recent_union,
                    d_max_cm=d_max_cm,
                )
                fresh_excess_depth_a.append(fc_["ghost_excess_depth_l1_cm"])
                fresh_excess_psnr_a.append(fc_["ghost_excess_psnr_db"])

    def _fmean(vals):
        arr = np.asarray(vals, dtype=float)
        fin = arr[np.isfinite(arr)]
        return float(np.mean(fin)) if fin.size else float("nan")

    n_scored = len(support_a)

    def _r(vals):
        return round(_fmean(vals), 4) if n_scored else "MISSING"

    row = {
        **_common_raw_fields(
            config,
            os.path.basename(save_dir),
            notes=(
                f"P-A hole-safe static-background (frozen GTMC mask '{subdir}'); scored "
                f"{n_scored} frames @every {interval}, missing-mask={n_missing}, "
                f"empty-support={n_empty}; gt depth undistorted (NEAREST) to render space"
            ),
        ),
        "psnr": _r(psnr_a),
        "ssim": _r(ssim_a),
        "lpips": _r(lpips_a),
        "depth_l1_cm": _r(depth_a),
        "accuracy_cm": "MISSING",
        "mask_type": "static",
        "completion_cm": "MISSING",
        "completion_ratio": "MISSING",
        "static_psnr": _r(psnr_a),
        "static_ssim": _r(ssim_a),
        "static_lpips": _r(lpips_a),
        "static_depth_l1_pen_cm": _r(depth_a),
        "static_coverage": _r(cov_a),
        "static_support_px_mean": int(np.mean(support_a)) if n_scored else 0,
        "static_frames_scored": n_scored,
        "static_frames_missing_mask": n_missing,
        "static_frames_empty_support": n_empty,
        "static_d_max_cm": d_max_cm,
        "static_opacity_a_eval": a_eval,
        "static_mask_subdir": subdir,
        # Vacated-region (ghost-contamination): rendered quality where the mover WAS
        # but is no longer (frozen-mask past-union ∧ ¬current-dynamic ∧ valid GT).
        "static_vacated_psnr": round(_fmean(vac_psnr_a), 4) if vac_support_a else "MISSING",
        "static_vacated_ssim": round(_fmean(vac_ssim_a), 4) if vac_support_a else "MISSING",
        "static_vacated_depth_l1_pen_cm": (
            round(_fmean(vac_depth_a), 4) if vac_support_a else "MISSING"
        ),
        "static_vacated_support_px_mean": (
            int(np.mean(vac_support_a)) if vac_support_a else 0
        ),
        "static_vacated_frames_scored": len(vac_support_a),
        # Paired ghost contrast: vacated MINUS this frame's own non-vacated static
        # background, averaged per frame. The absolute vacated column above is
        # ~95% global map/pose quality on Bonn balloon (21-27 cm base vs a
        # 0.1-1.3 cm vacated-minus-static gap and a 1.0-3.3 cm run-to-run noise
        # band), so it cannot resolve the ghost claim on its own. POSITIVE
        # ghost_excess_depth = the vacated region is worse than its surroundings
        # = residual ghost. LOWER is better; ~0 means the mover left no scar.
        "static_nonvacated_depth_l1_pen_cm": (
            round(_fmean(nonvac_depth_a), 4) if vac_support_a else "MISSING"
        ),
        "static_nonvacated_psnr": (
            round(_fmean(nonvac_psnr_a), 4) if vac_support_a else "MISSING"
        ),
        "static_ghost_excess_depth_l1_cm": (
            round(_fmean(excess_depth_a), 4) if vac_support_a else "MISSING"
        ),
        "static_ghost_excess_psnr_db": (
            round(_fmean(excess_psnr_a), 4) if vac_support_a else "MISSING"
        ),
        # FRESH-vacated (recency-windowed): the scar the mover left within the
        # last `static_bg_vacated_window_frames` frames. This is the localized
        # ghost region the unbounded column above stopped being once its union
        # swallowed the scene -- report support_px_mean alongside it, since a
        # window that grows to the whole image has the same defect.
        "static_vacated_window_frames": vac_window,
        "static_freshvac_psnr": (
            round(_fmean(fresh_psnr_a), 4) if fresh_support_a else "MISSING"
        ),
        "static_freshvac_ssim": (
            round(_fmean(fresh_ssim_a), 4) if fresh_support_a else "MISSING"
        ),
        "static_freshvac_depth_l1_pen_cm": (
            round(_fmean(fresh_depth_a), 4) if fresh_support_a else "MISSING"
        ),
        "static_freshvac_support_px_mean": (
            int(np.mean(fresh_support_a)) if fresh_support_a else 0
        ),
        "static_freshvac_frames_scored": len(fresh_support_a),
        "static_freshvac_ghost_excess_depth_l1_cm": (
            round(_fmean(fresh_excess_depth_a), 4) if fresh_support_a else "MISSING"
        ),
        "static_freshvac_ghost_excess_psnr_db": (
            round(_fmean(fresh_excess_psnr_a), 4) if fresh_support_a else "MISSING"
        ),
        **reliability_raw_fields(save_dir, "mapping"),
        **tri_reliability_raw_fields(save_dir, "mapping"),
        "source_dir": save_dir,
    }
    _write_csv_row(config["Results"].get("mapping_raw_path"), row)
    _write_csv_row(os.path.join(save_dir, "mapping_raw.csv"), row)
    if band_radii:
        band_out = {"mask_subdir": subdir, "frames_scored": n_scored, "bands": {}}
        for r in band_radii:
            acc = band_acc[int(r)]
            band_out["bands"][f"band{int(r)}"] = {
                "radius_px": int(r),
                "psnr": round(_fmean(acc["psnr"]), 4) if acc["psnr"] else None,
                "ssim": round(_fmean(acc["ssim"]), 4) if acc["ssim"] else None,
                "depth_l1_pen_cm": round(_fmean(acc["depth"]), 4) if acc["depth"] else None,
                "support_px_mean": int(np.mean(acc["support"])) if acc["support"] else 0,
                "frames_with_support": len(acc["support"]),
            }
        with open(os.path.join(save_dir, "band_metrics.json"), "w", encoding="utf-8") as f:
            json.dump(band_out, f, indent=1)
        Log(
            "band PSNR "
            + " ".join(
                f"r{int(r)}={band_out['bands'][f'band{int(r)}']['psnr']}"
                f"(n{band_out['bands'][f'band{int(r)}']['support_px_mean']})"
                for r in band_radii
            ),
            tag="Eval",
        )
    Log(
        f"P-A static-bg: psnr={row['static_psnr']} ssim={row['static_ssim']} "
        f"lpips={row['static_lpips']} depthL1pen={row['static_depth_l1_pen_cm']}cm "
        f"cov={row['static_coverage']} (scored {n_scored}, missing {n_missing}, "
        f"empty {n_empty}); vacated psnr={row['static_vacated_psnr']} "
        f"depthL1pen={row['static_vacated_depth_l1_pen_cm']}cm "
        f"(n={row['static_vacated_frames_scored']} frames, "
        f"px~{row['static_vacated_support_px_mean']}); "
        f"GHOST EXCESS depthL1={row['static_ghost_excess_depth_l1_cm']}cm "
        f"psnr={row['static_ghost_excess_psnr_db']}dB "
        f"(vs nonvacated {row['static_nonvacated_depth_l1_pen_cm']}cm); "
        f"FRESH-VAC(w={vac_window}) psnr={row['static_freshvac_psnr']} "
        f"depthL1pen={row['static_freshvac_depth_l1_pen_cm']}cm "
        f"excess={row['static_freshvac_ghost_excess_psnr_db']}dB/"
        f"{row['static_freshvac_ghost_excess_depth_l1_cm']}cm "
        f"(px~{row['static_freshvac_support_px_mean']}, "
        f"n={row['static_freshvac_frames_scored']})",
        tag="Eval",
    )
    return row


def save_gaussians(gaussians, name, iteration, final=False):
    if name is None:
        return
    if final:
        point_cloud_path = os.path.join(name, "point_cloud", str(iteration))
    else:
        point_cloud_path = os.path.join(
            name, "point_cloud/iteration_{}".format(str(iteration))
        )
    mkdir_p(point_cloud_path)
    gaussians.save_ply(os.path.join(point_cloud_path, "point_cloud.ply"))


def _load_backend_timing(save_dir):
    timing_path = os.path.join(save_dir, "backend_timing.json")
    if not os.path.exists(timing_path):
        return {}
    with open(timing_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_efficiency_raw(
    config,
    save_dir,
    fps,
    total_time_s,
    num_frames,
    gaussians=None,
    tracking_time_s=None,
    tracking_frames=None,
    online_time_s=None,
    online_peak_gpu_memory_gb="MISSING",
    online_num_gaussians=None,
    refinement_wall_time_s=None,
    refinement_peak_gpu_memory_gb="N/A",
    refined_num_gaussians=None,
    memory_monitor_error="",
):
    if not config["Results"].get("save_raw_metrics", False):
        return None
    legacy_gpu_memory_gb = "N/A"
    if torch.cuda.is_available():
        legacy_gpu_memory_gb = torch.cuda.max_memory_allocated() / (1024**3)
    current_gaussians = (
        int(gaussians.get_xyz.shape[0]) if gaussians is not None else "MISSING"
    )
    online_time_s = float(online_time_s if online_time_s is not None else total_time_s)
    online_fps = num_frames / online_time_s
    online_num_gaussians = (
        current_gaussians if online_num_gaussians is None else online_num_gaussians
    )
    refined_num_gaussians = (
        current_gaussians if refined_num_gaussians is None else refined_num_gaussians
    )
    backend_timing = _load_backend_timing(save_dir)
    tracking_time_ms = "N/A"
    tracking_fps = "N/A"
    if tracking_time_s and tracking_frames:
        tracking_time_ms = tracking_time_s / tracking_frames * 1000.0
        tracking_fps = tracking_frames / tracking_time_s
    mapping_time_s = backend_timing.get("mapping_time_s")
    mapping_iterations = backend_timing.get("mapping_iterations")
    mapping_time_ms = "N/A"
    mapping_fps = "N/A"
    if mapping_time_s and mapping_iterations:
        mapping_time_ms = mapping_time_s / mapping_iterations * 1000.0
        mapping_fps = mapping_iterations / mapping_time_s
    row = {
        **_common_raw_fields(
            config,
            os.path.basename(save_dir),
            notes=(
                "online_fps includes segmentation and online tracking/mapping, but "
                "excludes offline refinement/rendering/geometry; tracking timing wraps "
                "frontend tracking() per frame; mapping timing wraps backend map() "
                "and initialize_map() iterations"
                + (
                    f"; memory monitor: {memory_monitor_error}"
                    if memory_monitor_error
                    else ""
                )
            ),
        ),
        "efficiency_protocol_version": "online-phases-v2",
        "online_fps": round(float(online_fps), 4),
        "online_time_s": round(online_time_s, 4),
        "online_peak_gpu_memory_gb": online_peak_gpu_memory_gb,
        "online_num_gaussians": online_num_gaussians,
        "refinement_wall_time_s": round(float(refinement_wall_time_s), 4)
        if refinement_wall_time_s is not None
        else "N/A",
        "refinement_backend_time_s": round(
            float(backend_timing.get("color_refinement_time_s")), 4
        )
        if isinstance(backend_timing.get("color_refinement_time_s"), float)
        else "N/A",
        "refinement_peak_gpu_memory_gb": refinement_peak_gpu_memory_gb,
        "refined_num_gaussians": refined_num_gaussians,
        "geometry_eval_time_s": "MISSING",
        "geometry_eval_peak_gpu_memory_gb": "MISSING",
        "fps_end_to_end": round(float(online_fps), 4),
        "tracking_fps": round(float(tracking_fps), 4)
        if isinstance(tracking_fps, float)
        else tracking_fps,
        "mapping_fps": round(float(mapping_fps), 4)
        if isinstance(mapping_fps, float)
        else mapping_fps,
        "tracking_time_ms": round(float(tracking_time_ms), 4)
        if isinstance(tracking_time_ms, float)
        else tracking_time_ms,
        "mapping_time_ms": round(float(mapping_time_ms), 4)
        if isinstance(mapping_time_ms, float)
        else mapping_time_ms,
        "gpu_memory_gb": online_peak_gpu_memory_gb
        if online_peak_gpu_memory_gb != "MISSING"
        else round(float(legacy_gpu_memory_gb), 4)
        if isinstance(legacy_gpu_memory_gb, float)
        else legacy_gpu_memory_gb,
        "num_gaussians": online_num_gaussians,
        "total_time_s": round(float(online_time_s), 4),
        "num_frames": num_frames,
        "tracking_time_s": round(float(tracking_time_s), 4)
        if isinstance(tracking_time_s, float)
        else "N/A",
        "tracking_frames": tracking_frames if tracking_frames is not None else "N/A",
        "mapping_time_s": round(float(mapping_time_s), 4)
        if isinstance(mapping_time_s, float)
        else "N/A",
        "mapping_iterations": mapping_iterations
        if mapping_iterations is not None
        else "N/A",
        "mapping_calls": backend_timing.get("mapping_calls", "N/A"),
        # Arm-activity ledger. These are ZERO for every lifecycle-free arm by
        # design; a *treatment* arm reporting zero here did not run its
        # treatment, and its metrics are a replicate of the control -- see
        # scripts/check_arm_activity.py, which fails such a run.
        "alpha_lifecycle_steps": backend_timing.get("alpha_lifecycle_steps", "N/A"),
        "alpha_lifecycle_skips": backend_timing.get("alpha_lifecycle_skips", "N/A"),
        "alpha_exit_reset_total": backend_timing.get("alpha_exit_reset_total", "N/A"),
        "alpha_carve_total": backend_timing.get("alpha_carve_total", "N/A"),
        "alpha_fill_inserted_total": backend_timing.get(
            "alpha_fill_inserted_total", "N/A"
        ),
        # Fill-side attribution: splits a zero `alpha_fill_inserted_total` into
        # "the post-exit re-render still shows an opaque surface"
        # (cleared_px == 0) versus "exit cleared coverage that was not hiding
        # observed background, so there is correctly nothing to fill"
        # (cleared_px > 0, vacated_px == 0). Without these a legitimately-zero
        # fill and a broken fill are the same number in the results table.
        "alpha_fill_steps": backend_timing.get("alpha_fill_steps", "N/A"),
        "alpha_fill_cleared_px_total": backend_timing.get(
            "alpha_fill_cleared_px_total", "N/A"
        ),
        "alpha_fill_vacated_px_total": backend_timing.get(
            "alpha_fill_vacated_px_total", "N/A"
        ),
        "color_refinement_time_s": round(
            float(backend_timing.get("color_refinement_time_s")), 4
        )
        if isinstance(backend_timing.get("color_refinement_time_s"), float)
        else "N/A",
        **reliability_efficiency_fields(save_dir),
        **tri_reliability_efficiency_fields(save_dir),
        **reliable_tracking_efficiency_fields(save_dir),
        **semantic_efficiency_fields(save_dir),
        "source_dir": save_dir,
    }
    _write_csv_row(config["Results"].get("efficiency_raw_path"), row)
    _write_csv_row(os.path.join(save_dir, "efficiency_raw.csv"), row)
    return row
