"""Post-hoc vacated-region (ghost) metrics from a finished run's saved artifacts.

Phase-0 validator for the R2-P01-E2 co-primary decision: the vacated-region metric
(commit 3edce7a) postdates the R1-P01-E2 screening runs, so those runs have band
metrics but no vacated columns. This script reconstructs the exact final-eval state
from what a run saved on disk —

  * ``config.yml``                          resolved config (dataset, intervals, mask subdir)
  * ``point_cloud/final_after_opt/*.ply``   the Gaussians ``eval_static_background_raw`` saw
    (slam.py saves them right AFTER that eval; color refinement never moves poses)
  * ``plot/trj_full_final.json``            raw online per-frame C2W poses — exactly the
    camera poses the in-run eval rendered with (KF-propagated recomposition is only a
    diagnostic column, never written to this file)

— and re-runs ``eval_static_background_raw`` on it, which now also computes the
vacated-region metric.

Faithfulness anchor (the method proves itself before its numbers are used): the same
pass recomputes the band metrics and compares them against the run's stored
``band_metrics.json``. If every band PSNR matches within ``--tol-db`` (default 0.05 dB)
and the scored-frame count is identical, the render path is byte-faithful to the
in-run eval and the vacated columns are trustworthy. A mismatch fails loudly.

Outputs under ``<run-dir>/<out-name>/`` (default ``posthoc_vacated/``):
  ``mapping_raw.csv`` + ``mapping_raw_posthoc.csv``  full recomputed static/band/vacated row
  ``band_metrics.json``                              fresh band metrics
  ``posthoc_summary.json``                           vacated columns + band check verdict

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


def compare_band_metrics(stored, fresh, tol_db=0.05):
    """Faithfulness verdict: fresh in-posthoc band metrics vs the run's stored ones."""
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
            result["per_band"][name] = {
                "psnr_stored": sp,
                "psnr_fresh": fp,
                "pass": same_null,
            }
            if not same_null:
                result["pass"] = False
            continue
        delta = abs(float(fp) - float(sp))
        result["max_abs_dpsnr_db"] = max(result["max_abs_dpsnr_db"], round(delta, 4))
        entry = {
            "psnr_stored": sp,
            "psnr_fresh": fp,
            "abs_dpsnr_db": round(delta, 4),
            "pass": delta <= tol_db,
        }
        sd, fd = sb.get("depth_l1_pen_cm"), fb.get("depth_l1_pen_cm")
        if sd is not None and fd is not None:
            entry["abs_ddepth_cm"] = round(abs(float(fd) - float(sd)), 4)
        result["per_band"][name] = entry
        if delta > tol_db:
            result["pass"] = False
    return result


def evaluate_run(run_dir, tol_db=0.05, out_name="posthoc_vacated"):
    import torch
    import yaml
    from munch import munchify

    from gaussian_splatting.scene.gaussian_model import GaussianModel
    from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
    from utils.camera_utils import Camera
    from utils.dataset import load_dataset
    from utils.eval_utils import eval_static_background_raw

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
    frames = {}
    for fid, c2w in zip(trj["trj_id"], trj["trj_est"]):
        rotation, translation = w2c_from_c2w(c2w)
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
        # mirror the in-run eval state exactly: frontend cameras were clean()ed,
        # so the rasterizer received theta/rho/exposure = None (not zero tensors)
        cam.cam_rot_delta = None
        cam.cam_trans_delta = None
        cam.exposure_a = None
        cam.exposure_b = None
        frames[int(fid)] = cam

    out_dir = os.path.join(run_dir, out_name)
    os.makedirs(out_dir, exist_ok=True)
    cfg = copy.deepcopy(config)
    cfg["Results"]["save_raw_metrics"] = True
    # never append to the original batch tables — redirect the aggregate CSV locally
    cfg["Results"]["mapping_raw_path"] = os.path.join(out_dir, "mapping_raw_posthoc.csv")

    background = torch.tensor([0, 0, 0], dtype=torch.float32, device="cuda")
    with torch.no_grad():
        row = eval_static_background_raw(
            frames,
            gaussians,
            dataset,
            out_dir,
            munchify(config["pipeline_params"]),
            background,
            cfg,
        )
    if row is None:
        raise RuntimeError(
            "eval_static_background_raw produced no row (mask subdir/index missing?)"
        )

    band_check = None
    fresh_band_path = os.path.join(out_dir, "band_metrics.json")
    if os.path.isfile(stored_band_path) and os.path.isfile(fresh_band_path):
        with open(stored_band_path, "r", encoding="utf-8") as f:
            stored = json.load(f)
        with open(fresh_band_path, "r", encoding="utf-8") as f:
            fresh = json.load(f)
        band_check = compare_band_metrics(stored, fresh, tol_db=tol_db)

    summary = {
        "run_dir": run_dir,
        "method": config.get("method", "MonoGS"),
        "sequence": config.get("Dataset", {}).get("sequence", ""),
        "n_frames": len(frames),
        "n_gaussians": int(gaussians.get_xyz.shape[0]),
        "vacated": {
            "psnr": row.get("static_vacated_psnr"),
            "ssim": row.get("static_vacated_ssim"),
            "depth_l1_pen_cm": row.get("static_vacated_depth_l1_pen_cm"),
            "support_px_mean": row.get("static_vacated_support_px_mean"),
            "frames_scored": row.get("static_vacated_frames_scored"),
        },
        "static": {
            "psnr": row.get("static_psnr"),
            "depth_l1_pen_cm": row.get("static_depth_l1_pen_cm"),
            "frames_scored": row.get("static_frames_scored"),
        },
        # Paired within-frame ghost contrast (utils.static_eval.vacated_contrast_metrics):
        # vacated minus this frame's own non-vacated static background. The absolute
        # vacated number above is ~95% global map/pose quality, so this is the column
        # that actually tracks the ghost claim.
        "ghost_excess": {
            "depth_l1_cm": row.get("static_ghost_excess_depth_l1_cm"),
            "psnr_db": row.get("static_ghost_excess_psnr_db"),
            "nonvacated_depth_l1_pen_cm": row.get("static_nonvacated_depth_l1_pen_cm"),
            "nonvacated_psnr": row.get("static_nonvacated_psnr"),
        },
        # Recency-windowed "fresh scar" variant -- the localized ghost region the
        # unbounded past-union stopped being once it swallowed the scene.
        "freshvac": {
            "window_frames": row.get("static_vacated_window_frames"),
            "psnr": row.get("static_freshvac_psnr"),
            "ssim": row.get("static_freshvac_ssim"),
            "depth_l1_pen_cm": row.get("static_freshvac_depth_l1_pen_cm"),
            "support_px_mean": row.get("static_freshvac_support_px_mean"),
            "frames_scored": row.get("static_freshvac_frames_scored"),
            "ghost_excess_depth_l1_cm": row.get(
                "static_freshvac_ghost_excess_depth_l1_cm"
            ),
            "ghost_excess_psnr_db": row.get("static_freshvac_ghost_excess_psnr_db"),
        },
        "band_check": band_check,
    }
    with open(os.path.join(out_dir, "posthoc_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    del frames, gaussians, dataset
    torch.cuda.empty_cache()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("run_dirs", nargs="+")
    parser.add_argument("--tol-db", type=float, default=0.05)
    parser.add_argument("--out-name", default="posthoc_vacated")
    args = parser.parse_args()

    os.chdir(ROOT)  # saved configs use repo-root-relative dataset paths
    failures = 0
    for run_dir in args.run_dirs:
        try:
            summary = evaluate_run(run_dir, tol_db=args.tol_db, out_name=args.out_name)
        except Exception as exc:  # keep sweeping the remaining runs, fail at exit
            failures += 1
            print(f"POSTHOC-FAIL {run_dir}: {exc}", flush=True)
            continue
        check = summary["band_check"]
        verdict = "no-stored-band" if check is None else ("OK" if check["pass"] else "MISMATCH")
        if check is not None and not check["pass"]:
            failures += 1
        print(
            "POSTHOC "
            + json.dumps(
                {
                    "seq": summary["sequence"],
                    "method": summary["method"],
                    "vacated_depth_l1_pen_cm": summary["vacated"]["depth_l1_pen_cm"],
                    "vacated_psnr": summary["vacated"]["psnr"],
                    "vacated_frames": summary["vacated"]["frames_scored"],
                    "vacated_px": summary["vacated"]["support_px_mean"],
                    "band_check": verdict,
                    "max_abs_dpsnr_db": None if check is None else check["max_abs_dpsnr_db"],
                    "run_dir": summary["run_dir"],
                }
            ),
            flush=True,
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
