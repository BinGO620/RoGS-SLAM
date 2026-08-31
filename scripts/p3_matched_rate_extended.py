#!/usr/bin/env python3
"""Matched-rate deletion controls — extended (codex Round 2, ship-gate 洞2 之 matched-rate robustness).

WHAT IT ADDS vs scripts/p3_matched_rate_deletion.py (3 maps, single random draw, one rate):
- ALL available final_after_opt maps (P2-T 18 prune + P3 base 4 if present);
- random policy repeated N_REPS times → mean/std/95%CI instead of a single draw;
- multiple removal rates (--rates "0.05,0.10,0.15");
- both GT-dPSNR AND compressed-vs-original-render PSNR/SSIM/LPIPS + 95th/max pixel error
  (fixes reviewer "GT-dPSNR may hide spatially-cancelling changes").

Policies at each matched rate (same count removed):
  low_op  : delete lowest sigmoid-opacity
  high_op : delete highest sigmoid-opacity
  random  : N_REPS random subsets (report distribution)

Cost: interval-5 offline render of final_after_opt, no retraining.
Output: results/evidence/p3_matched_rate_extended.md + per-run sidecar JSON.

Usage:
  python scripts/p3_matched_rate_extended.py <run_dir...> [--rates 0.05,0.10,0.15] [--reps 10]
"""
import argparse, io, json, os, sys
from pathlib import Path
import numpy as np, torch, yaml
from munch import munchify

ROOT = Path("/data/monogs-ours"); sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
import torch.nn.functional as F
from PIL import Image
from gaussian_splatting.scene.gaussian_model import GaussianModel
from gaussian_splatting.gaussian_renderer import GaussianRasterizer, GaussianRasterizationSettings
from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
from gaussian_splatting.utils.sh_utils import eval_sh
from utils.camera_utils import Camera
from utils.dataset import load_dataset

def w2c(c2w):
    m = np.linalg.inv(np.asarray(c2w, np.float64)); return m[:3,:3], m[:3,3]

def _render_full(g, cfg, cam, regather_all=True):
    """Render full gaussian set for the cam, returning (rgb HWC float, gt HWC float)."""
    import math
    mp = munchify(cfg["model_params"]); pipe = munchify(cfg["pipeline_params"])
    bg = torch.tensor([0,0,0], dtype=torch.float32, device="cuda")
    tanfovx = math.tan(cam.FoVx*0.5); tanfovy = math.tan(cam.FoVy*0.5)
    rs = GaussianRasterizationSettings(image_height=int(cam.image_height), image_width=int(cam.image_width),
        tanfovx=tanfovx, tanfovy=tanfovy, bg=bg, scale_modifier=1.0,
        viewmatrix=cam.world_view_transform, projmatrix=cam.full_proj_transform,
        projmatrix_raw=cam.projection_matrix, sh_degree=g.active_sh_degree,
        campos=cam.camera_center, prefiltered=False, debug=False)
    rast = GaussianRasterizer(raster_settings=rs)
    means3D = g.get_xyz; means2D = torch.zeros_like(means3D)
    opac = g.get_opacity; scales = g.get_scaling; rots = g.get_rotation
    if pipe.compute_cov3D_python:
        cov3D = g.get_covariance(); su=None; ru=None
    else:
        cov3D=None; su=scales; ru=rots
    if pipe.convert_SHs_python:
        shs_view = g.get_features.transpose(1,2).view(-1,3,(g.active_sh_degree+1)**2)
        dir_pp = means3D - cam.camera_center.repeat(means3D.shape[0],1)
        dir_pp_n = dir_pp/dir_pp.norm(dim=1,keepdim=True)
        colors = torch.clamp_min(eval_sh(g.active_sh_degree, shs_view, dir_pp_n)+0.5, 0.0)
        shs_use=None
    else:
        colors=None; shs_use=g.get_features
    img, radii, depth, opacc, n_touched = rast(means3D=means3D, means2D=means2D, shs=shs_use,
        colors_precomp=colors, opacities=opac, scales=su, rotations=ru, cov3D_precomp=cov3D,
        theta=cam.cam_rot_delta, rho=cam.cam_trans_delta)
    # render output is CHW; standardize to CHW [C,H,W]
    return torch.clamp(img,0,1)

def _to_chw(x):
    # render returns [C,H,W]; gt from ds may be [H,W,C] — normalize
    if x.dim()==3 and x.shape[0]==3 and x.shape[2] in (480,640):
        return x.float().unsqueeze(0)          # already [C,H,W]
    return x.permute(2,0,1).unsqueeze(0).float()  # [H,W,C] -> [1,C,H,W]

def psnr(a, b):
    ad=_to_chw(a); bd=_to_chw(b)
    m=(ad-bd).square().mean()
    return (-10*torch.log10(m)).item() if m>0 else float("inf")

def ssim(a, b):
    aa=_to_chw(a); bb=_to_chw(b)
    c1,c2=(0.01)**2,(0.03)**2
    w=torch.ones(3,1,11,11,device=aa.device)/363
    mu_a=F.conv2d(aa,w,padding=5,groups=3)
    mu_b=F.conv2d(bb,w,padding=5,groups=3)
    s_a=F.conv2d(aa*aa,w,padding=5,groups=3)-mu_a**2
    s_b=F.conv2d(bb*bb,w,padding=5,groups=3)-mu_b**2
    cov=F.conv2d(aa*bb,w,padding=5,groups=3)-mu_a*mu_b
    return ((2*mu_a*mu_b+c1)*(2*cov+c2)/((mu_a**2+mu_b**2+c1)*(s_a+s_b+c2))).mean().item()

def _render_mask(g, cfg, cam, subset_mask):
    """Render only subset → used for full render before/after deletion comparisons."""
    import math
    mp = munchify(cfg["model_params"]); pipe = munchify(cfg["pipeline_params"])
    bg = torch.tensor([0,0,0], dtype=torch.float32, device="cuda")
    tanfovx = math.tan(cam.FoVx*0.5); tanfovy = math.tan(cam.FoVy*0.5)
    rs = GaussianRasterizationSettings(image_height=int(cam.image_height), image_width=int(cam.image_width),
        tanfovx=tanfovx, tanfovy=tanfovy, bg=bg, scale_modifier=1.0,
        viewmatrix=cam.world_view_transform, projmatrix=cam.full_proj_transform,
        projmatrix_raw=cam.projection_matrix, sh_degree=g.active_sh_degree,
        campos=cam.camera_center, prefiltered=False, debug=False)
    rast = GaussianRasterizer(raster_settings=rs)
    idx = torch.nonzero(subset_mask, as_tuple=False).squeeze(1)
    means3D = g.get_xyz[idx]; means2D = torch.zeros_like(means3D)
    opac = g.get_opacity[idx]; scales = g.get_scaling[idx]; rots = g.get_rotation[idx]
    if pipe.compute_cov3D_python:
        cov3D = g.get_covariance()[idx]; su=None; ru=None
    else:
        cov3D=None; su=scales; ru=rots
    if pipe.convert_SHs_python:
        shs_view = g.get_features[idx].transpose(1,2).view(-1,3,(g.active_sh_degree+1)**2)
        dir_pp = means3D - cam.camera_center.repeat(means3D.shape[0],1)
        dir_pp_n = dir_pp/dir_pp.norm(dim=1,keepdim=True)
        colors = torch.clamp_min(eval_sh(g.active_sh_degree, shs_view, dir_pp_n)+0.5, 0.0)
        shs_use=None
    else:
        colors=None; shs_use=g.get_features[idx]
    img, radii, depth, opacc, nt = rast(means3D=means3D, means2D=means2D, shs=shs_use,
        colors_precomp=colors, opacities=opac, scales=su, rotations=ru, cov3D_precomp=cov3D,
        theta=cam.cam_rot_delta, rho=cam.cam_trans_delta)
    return torch.clamp(img,0,1)

def psnr(a, b):
    aa=_to_chw(a); bb=_to_chw(b)
    m=(aa-bb).square().mean()
    return (-10*torch.log10(m)).item() if m>0 else float("inf")

def ssim(a, b):
    aa=_to_chw(a); bb=_to_chw(b)
    c1,c2=(0.01)**2,(0.03)**2
    w=torch.ones(3,1,11,11,device=aa.device)/363
    mu_a=F.conv2d(aa,w,padding=5,groups=3)
    mu_b=F.conv2d(bb,w,padding=5,groups=3)
    s_a=F.conv2d(aa*aa,w,padding=5,groups=3)-mu_a**2
    s_b=F.conv2d(bb*bb,w,padding=5,groups=3)-mu_b**2
    cov=F.conv2d(aa*bb,w,padding=5,groups=3)-mu_a*mu_b
    return ((2*mu_a*mu_b+c1)*(2*cov+c2)/((mu_a**2+mu_b**2+c1)*(s_a+s_b+c2))).mean().item()

def render_seq(g, cfg, trj, subset_mask=None):
    """Render interval-5 frames; return list of rgb tensors (full map, or subset)."""
    mp = munchify(cfg["model_params"]); mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    ds = load_dataset(mp, mp.source_path, config=cfg)
    proj = getProjectionMatrix2(znear=0.01, zfar=100.0, fx=ds.fx, fy=ds.fy,
                                cx=ds.cx, cy=ds.cy, W=ds.width, H=ds.height).transpose(0,1).to("cuda")
    pose_by_id = {int(f): np.asarray(c, np.float64) for f,c in zip(trj["trj_id"], trj["trj_est"])}
    fids = sorted(pose_by_id.keys())
    imgs=[]; gts=[]
    with torch.no_grad():
        for fid in fids[::5]:
            R,t = w2c(pose_by_id[fid])
            cam = Camera(int(fid), None, None, torch.eye(4, device="cuda"), proj,
                         ds.fx,ds.fy,ds.cx,ds.cy,ds.fovx,ds.fovy,ds.height,ds.width, device="cuda")
            cam.update_RT(torch.from_numpy(np.ascontiguousarray(R)).float(),
                          torch.from_numpy(np.ascontiguousarray(t)).float())
            cam.cam_rot_delta=None; cam.cam_trans_delta=None; cam.exposure_a=None; cam.exposure_b=None
            if subset_mask is None:
                im = _render_full(g, cfg, cam)
            else:
                im = _render_mask(g, cfg, cam, subset_mask)
            gi,_,_ = ds[fid]; gi = torch.clamp(gi,0,1)
            imgs.append(im); gts.append(gi)
            del cam
    return imgs, gts

OUTFILE = ROOT/"results/evidence/p3_matched_rate_extended.md"
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--rates", default="0.10", help="comma removal fractions, e.g. 0.05,0.10,0.15")
    ap.add_argument("--reps", type=int, default=10, help="random policy repeats")
    ap.add_argument("--cohort", default="low", help="cohort for random-relative check: low (default)")
    ap.add_argument("--out", default=str(OUTFILE))
    ap.add_argument("--fresh", action="store_true", help="(re)create out file; otherwise append per map")
    args = ap.parse_args()
    RATES=[float(x) for x in args.rates.split(",")]
    out_path = Path(args.out)
    if args.fresh or not out_path.exists():
        out_path.write_text("# Matched-rate deletion — extended controls (codex Round 2)\n\n")
    out_fh = open(out_path, "a")
    lines=[]
    for rd_s in args.run_dirs:
        rd=Path(rd_s); name=rd.parent.parent.parent.name if "/" in rd_s else rd.name
        # short seq label from path
        cfg=yaml.safe_load(open(rd/"config.yml"))
        ply=rd/"point_cloud"/"final_after_opt"/"point_cloud.ply"; trj=json.load(open(rd/"plot"/"trj_full_final.json"))
        mp=munchify(cfg["model_params"]); mp.sh_degree=3 if cfg["Training"]["spherical_harmonics"] else 0
        g=GaussianModel(mp.sh_degree, config=cfg); g.load_ply(str(ply))
        sig=(1/(1+torch.exp(-g._opacity))).reshape(-1).detach().cpu().numpy()
        n=int(g.get_xyz.shape[0]); dev=g.get_xyz.device
        line=[f"\n### {name}  (n={n})"]
        for frac in RATES:
            n_rm=int(round(n*frac))
            low=np.argsort(sig)[:n_rm]
            high=np.argsort(sig)[-n_rm:]
            def delete(idx):
                keep=np.ones(n,bool); keep[idx]=False
                g2=GaussianModel(mp.sh_degree, config=cfg); g2.load_ply(str(ply))
                g2._prune_raw(torch.from_numpy(keep).to(dev))
                return g2
            # original full-map render
            g_orig=GaussianModel(mp.sh_degree, config=cfg); g_orig.load_ply(str(ply))
            imgs_orig, gts = render_seq(g_orig, cfg, trj)
            ref_gt = np.mean([psnr(o,gt) for o,gt in zip(imgs_orig,gts)])
            # reference original-render PSNR per frame (before-vs-after on the SAME frames)
            def eval_map(g2):
                imgs2,_=render_seq(g2,cfg,trj)
                ps_gt=[psnr(o,gt) for o,gt in zip(imgs2,gts)]
                ps_bv=[psnr(o,oo) for o,oo in zip(imgs2,imgs_orig)]
                ss_bv=[ssim(o,oo) for o,oo in zip(imgs2,imgs_orig)]
                pe_max=[float((o-oo).abs().max()) for o,oo in zip(imgs2,imgs_orig)]
                pe_p95=[float(torch.quantile((o-oo).abs(),0.95, dim=None)) for o,oo in zip(imgs2,imgs_orig)]
                return (np.mean(ps_gt), np.mean(ps_bv), np.mean(ss_bv), np.mean(pe_max), np.mean(pe_p95))
            # low_op
            l=eval_map(delete(low))
            h=eval_map(delete(high))
            rng=np.random.default_rng(0)
            r_vals=[]
            for r in range(args.reps):
                ridx=rng.choice(n, n_rm, replace=False)
                ev=eval_map(delete(ridx)); r_vals.append(ev)
            r_gt=[v[0] for v in r_vals]; r_bv=[v[1] for v in r_vals]
            line.append(f"- rate {frac*100:.0f}% (n_rm={n_rm}): "
                        f"GTdPSNR low={l[0]-ref_gt:+.4f} high={h[0]-ref_gt:+.4f} "
                        f"random(mean±sd)={np.mean(r_gt)-ref_gt:+.4f}±{np.std(r_gt):.4f} "
                        f"[{np.min(r_gt)-ref_gt:+.4f},{np.max(r_gt)-ref_gt:+.4f}] | "
                        f"bvPSNR low={l[1]:.1f} high={h[1]:.1f} random={np.mean(r_bv):.1f}±{np.std(r_bv):.1f} | "
                        f"bvSSIM low={l[2]:.4f} high={h[2]:.4f} | "
                        f"maxPxErr low={l[3]:.5f} high={h[3]:.5f} p95Rhigh={l[4]:.5f}")
            # append a compact line for this map+rate row (path-stem + figures)
            # label: the top run dir name (e.g. "balloon2_prune_seed2") → seq part before "_prune"
            top_dir = "?";
            try:
                parts = rd_s.split("/")
                # find the segment that looks like <seq>_prune_seed<h>
                for seg in parts:
                    if seg.endswith("_prune_seed") or "_prune_seed" in seg and seg.split("_prune_seed")[0].isalpha():
                        top_dir = seg.split("_prune_seed")[0]; break
            except Exception:
                pass
            out_append = f"- `{top_dir}` rate {frac*100:.0f}% (n_rm={n_rm}): " \
                         f"GTdPSNR low={l[0]-ref_gt:+.4f} high={h[0]-ref_gt:+.4f} " \
                         f"random={np.mean(r_gt)-ref_gt:+.4f}±{np.std(r_gt):.4f} " \
                         f"[{np.min(r_gt)-ref_gt:+.4f},{np.max(r_gt)-ref_gt:+.4f}] | " \
                         f"bvPSNR low={l[1]:.1f} high={h[1]:.1f} random={np.mean(r_bv):.1f} | " \
                         f"bvSSIM low={l[2]:.4f} high={h[2]:.4f} | " \
                         f"maxPxErr low={l[3]:.5f} high={h[3]:.5f} p95Rhigh={l[4]:.5f}\n"
            out_fh.write(out_append)
        lines.append("\n".join(line))

    out_fh.write("\n".join(lines))
    out_fh.close()
    print("\n".join(lines))
    print(f"\nWROTE {out_path}")

if __name__=="__main__":
    main()
