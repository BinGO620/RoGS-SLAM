#!/usr/bin/env python3
"""Cohort-level cumulative compositing-weight certificate (codex Round 2, ship-gate 洞1).

WHY. The paper's "zero-cost" claim currently rests on a single-gaussian bound (theory.md 上界 A:
op<0.01 ⇒ weight alpha_k*T_k < 1%) that a reviewer correctly attacked: the BOUND is per-gaussian,
it does NOT bound the CUMULATIVE contribution of m low-opacity gaussians on ONE ray (m=100 ⇒
cumulative opacity ≈ 1-(1-0.01)^m ≈ 63%). To make "near-zero CONTRIBUTION COHORT" a real
cohort-level statement we directly measure the per-pixel cumulative compositing weight of the
removed cohort.

Method (upper-bound certificate, choice by occlusion logic):
  W_removed(p) = sum_{k in R, ray p}  T_k^full(p) * alpha_k(p)
is the true removed cohort contribution, where T_k^full uses ALL gaussians in front.
The rasterizer's `opacity` output accumulated front-to-back over ONLY the passed gaussians, so
rendering the REMOVED COHORT ALONE (mask = removed) gives
  W_alone(p) = sum_{k in R} T_k^R(p) alpha_k(p),  T_k^R = transmittance within removed subset only.
Since T_k^R >= T_k^full (fewer blockers ⇒ higher transmittance), we have W_alone(p) >= W_removed(p).
So W_alone is a sound UPPER BOUND on the true removed-cohort contribution. If even the upper bound
is small at the mean/99th-percentile/max, the cohort is genuinely near-zero-contribution.

This avoids depending on the (wrong) batch theorem while needing NO retraining and NO new GPU
campaign — only interval-5 rendering of the existing final_after_opt PLYs (and deletion count =
the op<0.01 set).

Usage:
  python scripts/p3_cohort_weight_cert.py <run_dir> [--frac 0.10]
Writes results/evidence/p3_cohort_weight_cert.md (append) + per-run json sidecar in run dir.
"""
import argparse, json, os, sys
from pathlib import Path
import numpy as np, torch, yaml
from munch import munchify

ROOT = Path("/data/monogs-ours"); sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
from gaussian_splatting.scene.gaussian_model import GaussianModel
from gaussian_splatting.gaussian_renderer import render as gs_render
from gaussian_splatting.gaussian_renderer import GaussianRasterizer, GaussianRasterizationSettings
from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
from gaussian_splatting.utils.sh_utils import eval_sh
from utils.camera_utils import Camera
from utils.dataset import load_dataset

def w2c(c2w):
    m = np.linalg.inv(np.asarray(c2w, np.float64)); return m[:3,:3], m[:3,3]

def render_subset_opacity(g, cfg, cam, subset_mask, scaling_modifier=1.0):
    """Render only `subset_mask` gaussians, return the per-pixel accumulated front-to-back opacity.
    `render()`'s mask branch is arity-broken in this repo (unpacks 4 but CUDA returns 5) — call the
    rasterizer directly with the subset tensors, exactly as `render()` does for its non-mask path."""
    import math
    mp = munchify(cfg["model_params"])
    pipe = munchify(cfg["pipeline_params"])
    bg = torch.tensor([0,0,0], dtype=torch.float32, device="cuda")
    tanfovx = math.tan(cam.FoVx*0.5); tanfovy = math.tan(cam.FoVy*0.5)
    rs = GaussianRasterizationSettings(
        image_height=int(cam.image_height), image_width=int(cam.image_width),
        tanfovx=tanfovx, tanfovy=tanfovy, bg=bg, scale_modifier=scaling_modifier,
        viewmatrix=cam.world_view_transform, projmatrix=cam.full_proj_transform,
        projmatrix_raw=cam.projection_matrix, sh_degree=g.active_sh_degree,
        campos=cam.camera_center, prefiltered=False, debug=False)
    rast = GaussianRasterizer(raster_settings=rs)
    idx = torch.nonzero(subset_mask, as_tuple=False).squeeze(1)
    means3D = g.get_xyz[idx]; means2D = torch.zeros_like(means3D)
    shs = g.get_features[idx].transpose(1,2).view(-1,3,(g.active_sh_degree+1)**2) if not pipe.convert_SHs_python else None
    opac = g.get_opacity[idx]
    scales = g.get_scaling[idx]; rots = g.get_rotation[idx]
    colors = None
    if shs is not None:
        dir_pp = means3D - cam.camera_center.repeat(means3D.shape[0],1)
        dir_pp_n = dir_pp / dir_pp.norm(dim=1, keepdim=True)
        colors = torch.clamp_min(eval_sh(g.active_sh_degree, shs, dir_pp_n) + 0.5, 0.0)
        shs_use = None
    elif pipe.convert_SHs_python:
        shs_use = None; colors = None
        shs_view = shs
        dir_pp = means3D - cam.camera_center.repeat(means3D.shape[0],1)
        dir_pp_n = dir_pp / dir_pp.norm(dim=1, keepdim=True)
        sh2rgb = eval_sh(g.active_sh_degree, shs_view, dir_pp_n)
        colors = torch.clamp_min(sh2rgb + 0.5, 0.0)
        shs_use = None
    else:
        shs_use = g.get_features[idx]; colors = None
    cov3D = g.get_covariance(scaling_modifier)[idx] if pipe.compute_cov3D_python else None
    if cov3D is not None:
        scales_use = None; rots_use = None
    else:
        scales_use = scales; rots_use = rots
    img, radii, depth, opacc, n_touched = rast(
        means3D=means3D, means2D=means2D, shs=shs_use, colors_precomp=colors,
        opacities=opac, scales=scales_use, rotations=rots_use,
        cov3D_precomp=cov3D, theta=cam.cam_rot_delta, rho=cam.cam_trans_delta)
    return opacc.flatten()

def render_opacity_header(g, cfg, trj, mask_pts):
    """Return per-pixel accumulated-opacity of the given gaussian subset (mask_pts bool tensor = the
    removed cohort), rendered ALONE ⇒ upper bound on their removed contribution (fewer blockers ⇒
    higher transmittance ⇒ overestimates true weight). Aggregated over interval-5 frames → flat
    per-pixel opacity values."""
    mp = munchify(cfg["model_params"]); mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    ds = load_dataset(mp, mp.source_path, config=cfg)
    proj = getProjectionMatrix2(znear=0.01, zfar=100.0, fx=ds.fx, fy=ds.fy,
                                cx=ds.cx, cy=ds.cy, W=ds.width, H=ds.height).transpose(0,1).to("cuda")
    pipe = munchify(cfg["pipeline_params"]); bg = torch.tensor([0,0,0], dtype=torch.float32, device="cuda")
    pose_by_id = {int(f): np.asarray(c, np.float64) for f, c in zip(trj["trj_id"], trj["trj_est"])}
    fids = sorted(pose_by_id.keys())
    opvals = []
    with torch.no_grad():
        for fid in fids[::5]:
            R, t = w2c(pose_by_id[fid])
            cam = Camera(int(fid), None, None, torch.eye(4, device="cuda"), proj,
                         ds.fx, ds.fy, ds.cx, ds.cy, ds.fovx, ds.fovy,
                         ds.height, ds.width, device="cuda")
            cam.update_RT(torch.from_numpy(np.ascontiguousarray(R)).float(),
                          torch.from_numpy(np.ascontiguousarray(t)).float())
            cam.cam_rot_delta = None; cam.cam_trans_delta = None
            cam.exposure_a = None; cam.exposure_b = None
            opvals.append(render_subset_opacity(g, cfg, cam, mask_pts).cpu().float())
            del cam
    return torch.cat(opvals).numpy()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--frac", type=float, default=None,
                    help="matched removal fraction (default: actual op<0.01 count)")
    args = ap.parse_args()

    # collect rows for markdown
    rows = []

    for run_dir in args.run_dirs:
        rd = Path(run_dir)
        cfg = yaml.safe_load(open(rd/"config.yml"))
        ply = rd/"point_cloud"/"final_after_opt"/"point_cloud.ply"
        trj = json.load(open(rd/"plot"/"trj_full_final.json"))
        assert ply.is_file() and trj is not None, run_dir

        mp = munchify(cfg["model_params"]); mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
        g = GaussianModel(mp.sh_degree, config=cfg); g.load_ply(str(ply))
        sig = (1/(1+torch.exp(-g._opacity))).reshape(-1)
        if args.frac is not None:
            n = int(g.get_xyz.shape[0]); n_rm = int(round(n*args.frac))
            idx = torch.argsort(sig)[:n_rm]        # lowest-opacity cohort (matched frac)
            mask_pts = torch.zeros(n, dtype=torch.bool, device="cuda"); mask_pts[idx] = True
            removed_n = n_rm
        else:
            mask_pts = sig < 0.01                   # actual op<0.01 cohort
            removed_n = int(mask_pts.sum().item())
        removed_frac = removed_n / int(g.get_xyz.shape[0])

        opvals = render_opacity_header(g, cfg, trj, mask_pts.to("cuda"))
        row = {
            "run": rd.name, "n_removed": removed_n, "removed_frac": round(removed_frac,4),
            "mean": float(np.mean(opvals)), "p99": float(np.percentile(opvals,99)),
            "max": float(np.max(opvals)),
        }
        rows.append(row)
        print(f"{rd.name:24s} rm={removed_n:6d} ({removed_frac*100:.1f}%)  "
              f"W_mean={row['mean']:.4f}  W_p99={row['p99']:.4f}  W_max={row['max']:.4f}", flush=True)
        # sidecar
        out = rd/"posthoc_terminal_comp"/"cohort_weight.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(row, open(out,"w"), indent=2)

    print("DONE cohort cert")

if __name__ == "__main__":
    main()
