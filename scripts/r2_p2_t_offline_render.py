"""Post-hoc full-frame rendering metrics (PSNR/SSIM/LPIPS/depth_l1) from a finished
run's saved artifacts — the fix for the P2-T eval_rendering NaN bug.

WHY THIS EXISTS. `eval_rendering()` in utils/eval_utils.py samples every `interval=5`
frames and skips keyframes (`if idx in kf_indices: continue`). The combined backbone
uses `DynamicKeyframe.gap_cap=5`, so the keyframe cadence is ALSO every 5 frames
({0,5,10,...}). The two cadences collide: every sampled frame is a keyframe, all are
skipped, `psnr_array` stays empty, and `final_result.json` records `mean_psnr: NaN`.
This script recomputes the full-frame metrics the in-run eval failed to produce,
WITHOUT re-running the SLAM — it reuses the saved final Gaussian point cloud and the
saved full estimated trajectory.

ARTIFACTS READ (per run dir, same as eval_vacated_posthoc.py):
  * ``config.yml``                          resolved config (dataset, intervals, SH)
  * ``point_cloud/final_after_opt/*.ply``   the Gaussians the in-run eval would have seen
    (slam.py saves them right AFTER that eval; color refinement never moves poses)
  * ``plot/trj_full_final.json``            raw online per-frame C2W poses — exactly the
    camera poses the in-run eval rendered with

WHAT IT DOES. For every `interval`-th frame (interval default 5, configurable), it
rebuilds a Camera from the ESTIMATED pose in trj_full_final.json (not GT, not the
cleaned cameras dict), renders the final map, and computes PSNR/SSIM/LPIPS/depth_l1
against the dataset GT — mirroring eval_rendering() but WITHOUT the keyframe skip.

KEY DIFFERENCE from eval_rendering(): no `if idx in kf_indices: continue`. Every
sampled frame is scored. The keyframe/non-keyframe distinction is irrelevant to
rendering quality (we want even spatial coverage of the trajectory).

VALIDATION ANCHOR. The first run processed also recomputes the static-band metrics
(via eval_static_background_raw) when a GTMC mask subdir is configured, and compares
them against the run's stored band_metrics.json — if those match within --tol-db,
the render path is byte-faithful to the in-run eval and the full-frame numbers are
trustworthy. (Inherited faithfulness check from eval_vacated_posthoc.py.)

OUTPUTS (under <run-dir>/posthoc_fullframe/):
  final_result.json         {mean_psnr, mean_ssim, mean_lpips, mean_depth_l1_cm,
                            n_frames_scored, n_nonfinite_dropped}
  fullframe_summary.json    same + run metadata + band_check verdict (if available)

Never writes into the original run's files or the batch tables CSV.
"""

import argparse
import copy
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def w2c_from_c2w(c2w):
    """Invert a C2W 4x4 (list or array) into (R, t) of the W2C transform."""
    mat = np.linalg.inv(np.asarray(c2w, dtype=np.float64))
    return mat[:3, :3], mat[:3, 3]


def _finite_mean(vals):
    arr = np.asarray(vals, dtype=float)
    finite = arr[np.isfinite(arr)]
    return (float(np.mean(finite)) if finite.size else float("nan")), int(
        arr.size - finite.size
    )


def compare_band_metrics(stored, fresh, tol_db=0.05):
    """Faithfulness verdict: fresh in-posthoc band metrics vs the run's stored ones.
    Inherited verbatim from eval_vacated_posthoc.py so the same check applies."""
    result = {
        "tol_db": tol_db,
        "frames_scored_stored": stored.get("frames_scored"),
        "frames_scored_fresh": fresh.get("frames_scored"),
        "max_abs_dpsnr_db": 0.0,
        "per_band": {},
        "pass": True,
    }
    if stored.get("frames_scored") != fresh.get("frames_scored"):
        result["pass"] = False
    for name, sb in (stored.get("bands") or {}).items():
        fb = (fresh.get("bands") or {}).get(name)
        if fb is None:
            result["per_band"][name] = "missing-in-fresh"
            result["pass"] = False
            continue
        sp, fp = sb.get("psnr"), fb.get("psnr")
        if sp is None or fp is None:
            same_null = (sp is None) == (fp is None)
            result["per_band"][name] = {"psnr_stored": sp, "psnr_fresh": fp, "pass": same_null}
            if not same_null:
                result["pass"] = False
            continue
        delta = abs(float(fp) - float(sp))
        result["max_abs_dpsnr_db"] = max(result["max_abs_dpsnr_db"], round(delta, 4))
        entry = {"psnr_stored": sp, "psnr_fresh": fp, "abs_dpsnr_db": round(delta, 4), "pass": delta <= tol_db}
        sd, fd = sb.get("depth_l1_pen_cm"), fb.get("depth_l1_pen_cm")
        if sd is not None and fd is not None:
            entry["abs_ddepth_cm"] = round(abs(float(fd) - float(sd)), 4)
        result["per_band"][name] = entry
        if delta > tol_db:
            result["pass"] = False
    return result


def evaluate_run(run_dir, tol_db=0.05, out_name="posthoc_fullframe", interval=None, do_band_check=True):
    import torch
    import yaml
    from munch import munchify
    from torchmetrics.functional import (
        structural_similarity_index_measure as ssim_fn,
        peak_signal_noise_ratio as psnr_fn,
    )
    from torchmetrics.image.lpip import LearnedPerceptualImagePatchSimilarity

    from gaussian_splatting.scene.gaussian_model import GaussianModel
    from gaussian_splatting.gaussian_renderer import render
    from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
    from utils.camera_utils import Camera
    from utils.dataset import load_dataset
    from utils.eval_utils import _compute_depth_l1_cm

    run_dir = os.path.normpath(run_dir)
    cfg_path = os.path.join(run_dir, "config.yml")
    ply_path = os.path.join(run_dir, "point_cloud", "final_after_opt", "point_cloud.ply")
    trj_path = os.path.join(run_dir, "plot", "trj_full_final.json")
    stored_band_path = os.path.join(run_dir, "band_metrics.json")
    for path in (cfg_path, ply_path, trj_path):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"required run artifact missing: {path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if interval is None:
        interval = config.get("Results", {}).get("eval_rendering_interval", 5)

    model_params = munchify(config["model_params"])
    model_params.sh_degree = 3 if config["Training"]["spherical_harmonics"] else 0
    dataset = load_dataset(model_params, model_params.source_path, config=config)

    gaussians = GaussianModel(model_params.sh_degree, config=config)
    gaussians.load_ply(ply_path)

    with open(trj_path, "r", encoding="utf-8") as f:
        trj = json.load(f)

    projection_matrix = (
        getProjectionMatrix2(
            znear=0.01,
            zfar=100.0,
            fx=dataset.fx,
            fy=dataset.fy,
            cx=dataset.cx,
            cy=dataset.cy,
            W=dataset.width,
            H=dataset.height,
        )
        .transpose(0, 1)
        .to(device=dataset.device)
    )

    # Rebuild one Camera per frame id in the saved trajectory, injecting the ESTIMATED
    # pose as R/T (the in-run eval rendered with these same online poses). Mirrors
    # eval_vacated_posthoc.py:144-172 exactly so the band check is apples-to-apples.
    pose_by_id = {int(fid): np.asarray(c2w, dtype=np.float64) for fid, c2w in zip(trj["trj_id"], trj["trj_est"])}
    frame_ids = sorted(pose_by_id.keys())

    background = torch.tensor([0, 0, 0], dtype=torch.float32, device="cuda")
    cal_lpips = LearnedPerceptualImagePatchSimilarity(net_type="alex", normalize=True).to("cuda")

    psnr_array, ssim_array, lpips_array, depth_l1_array = [], [], [], []

    with torch.no_grad():
        for fid in frame_ids[::interval]:
            c2w = pose_by_id[fid]
            rotation, translation = w2c_from_c2w(c2w)
            # Camera() with gt_T=eye and original_image/depth=None; we only need it as
            # a viewpoint carrying R/T for the rasterizer. original_image must be set
            # because Camera.__init__ assigns it directly (None is fine — render() does
            # not read original_image, only R/T/FoV/intrinsics).
            cam = Camera(
                int(fid),
                None,
                None,
                torch.eye(4, device=dataset.device),
                projection_matrix,
                dataset.fx,
                dataset.fy,
                dataset.cx,
                dataset.cy,
                dataset.fovx,
                dataset.fovy,
                dataset.height,
                dataset.width,
                device=dataset.device,
            )
            cam.update_RT(
                torch.from_numpy(np.ascontiguousarray(rotation)).float(),
                torch.from_numpy(np.ascontiguousarray(translation)).float(),
            )
            # mirror the in-run eval state: frontend cameras were clean()ed, so the
            # rasterizer received theta/rho/exposure = None (not zero tensors)
            cam.cam_rot_delta = None
            cam.cam_trans_delta = None
            cam.exposure_a = None
            cam.exposure_b = None

            gt_image, gt_depth, _ = dataset[fid]
            render_pkg = render(cam, gaussians, munchify(config["pipeline_params"]), background)
            image = torch.clamp(render_pkg["render"], 0.0, 1.0)
            depth = render_pkg["depth"].squeeze()

            mask = gt_image > 0
            psnr_array.append(psnr_fn((image[mask]).unsqueeze(0), (gt_image[mask]).unsqueeze(0)).item())
            ssim_array.append(ssim_fn(image.unsqueeze(0), gt_image.unsqueeze(0)).item())
            lpips_array.append(cal_lpips(image.unsqueeze(0), gt_image.unsqueeze(0)).item())
            depth_l1_cm = _compute_depth_l1_cm(depth, gt_depth)
            if depth_l1_cm is not None:
                depth_l1_array.append(depth_l1_cm)

            del cam

    mean_psnr, n_drop_psnr = _finite_mean(psnr_array)
    mean_ssim, _ = _finite_mean(ssim_array)
    mean_lpips, _ = _finite_mean(lpips_array)
    mean_depth_l1 = float(np.mean(depth_l1_array)) if depth_l1_array else None

    output = {
        "mean_psnr": round(mean_psnr, 4) if not np.isnan(mean_psnr) else None,
        "mean_ssim": round(mean_ssim, 4) if not np.isnan(mean_ssim) else None,
        "mean_lpips": round(mean_lpips, 4) if not np.isnan(mean_lpips) else None,
        "mean_depth_l1_cm": round(mean_depth_l1, 4) if mean_depth_l1 is not None else None,
        "n_frames_scored": len(psnr_array),
        "n_nonfinite_dropped": n_drop_psnr,
        "interval": interval,
        "mask_type": "full",
        "note": (
            "Post-hoc full-frame re-render from saved final_after_opt PLY + trj_full_final "
            "estimated poses. Fixes the eval_rendering() NaN bug (sample cadence==KF cadence "
            "collision). No keyframe skip; every interval-th frame scored."
        ),
    }

    out_dir = os.path.join(run_dir, out_name)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "final_result.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4)

    # ---- Faithfulness band check (inherited from eval_vacated_posthoc) ----
    band_check = None
    if do_band_check and os.path.isfile(stored_band_path):
        try:
            from utils.eval_utils import eval_static_background_raw

            cfg = copy.deepcopy(config)
            cfg["Results"]["save_raw_metrics"] = True
            cfg["Results"]["mapping_raw_path"] = os.path.join(out_dir, "mapping_raw_posthoc.csv")

            # Rebuild frames dict for the static-bg path (same Camera construction)
            frames = {}
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
                frames[int(fid)] = cam

            with torch.no_grad():
                eval_static_background_raw(
                    frames, gaussians, dataset, out_dir,
                    munchify(config["pipeline_params"]), background, cfg,
                )
            del frames
            fresh_band_path = os.path.join(out_dir, "band_metrics.json")
            if os.path.isfile(fresh_band_path):
                with open(stored_band_path) as f:
                    stored = json.load(f)
                with open(fresh_band_path) as f:
                    fresh = json.load(f)
                band_check = compare_band_metrics(stored, fresh, tol_db=tol_db)
        except Exception as exc:
            band_check = {"error": f"band check skipped: {exc}", "pass": False}

    summary = {
        "run_dir": run_dir,
        "method": config.get("method", "MonoGS"),
        "sequence": config.get("Dataset", {}).get("sequence", ""),
        "n_frames_in_trajectory": len(frame_ids),
        "n_gaussians": int(gaussians.get_xyz.shape[0]),
        "fullframe": {
            "psnr": output["mean_psnr"],
            "ssim": output["mean_ssim"],
            "lpips": output["mean_lpips"],
            "depth_l1_cm": output["mean_depth_l1_cm"],
            "frames_scored": output["n_frames_scored"],
            "nonfinite_dropped": output["n_nonfinite_dropped"],
        },
        "band_check": band_check,
    }
    with open(os.path.join(out_dir, "fullframe_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    del gaussians, dataset
    torch.cuda.empty_cache()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("run_dirs", nargs="+")
    parser.add_argument("--tol-db", type=float, default=0.05)
    parser.add_argument("--out-name", default="posthoc_fullframe")
    parser.add_argument("--interval", type=int, default=None, help="eval frame interval (default: from config, 5)")
    parser.add_argument("--no-band-check", action="store_true", help="skip the faithfulness band comparison")
    args = parser.parse_args()

    os.chdir(ROOT)
    failures = 0
    for run_dir in args.run_dirs:
        try:
            summary = evaluate_run(
                run_dir, tol_db=args.tol_db, out_name=args.out_name,
                interval=args.interval, do_band_check=not args.no_band_check,
            )
        except Exception as exc:
            failures += 1
            print(f"FULLFRAME-FAIL {run_dir}: {exc}", flush=True)
            import traceback
            traceback.print_exc()
            continue
        ff = summary["fullframe"]
        check = summary.get("band_check")
        verdict = "no-stored-band" if check is None else ("OK" if check.get("pass") else "MISMATCH")
        print(
            "FULLFRAME "
            + json.dumps(
                {
                    "seq": summary["sequence"],
                    "method": summary["method"],
                    "psnr": ff["psnr"],
                    "ssim": ff["ssim"],
                    "lpips": ff["lpips"],
                    "depth_l1_cm": ff["depth_l1_cm"],
                    "frames_scored": ff["frames_scored"],
                    "band_check": verdict,
                    "run_dir": summary["run_dir"],
                }
            ),
            flush=True,
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
