#!/usr/bin/env python3
"""map-compression STEP 1b/2: footprint and joint opacity×footprint selection curves.

Companion to mc_opacity_deletion_curve.py. Tests whether footprint-based and
opacity×footprint JOINT selection outperform pure opacity deletion (fewer Gaussians
removed for the same PSNR budget, or more removed at zero cost). Pattern on the 
opacity curve: offline re-render at est poses, _prune_raw, measure dPSNR.

Key finding (P2-T, 4 seqs): the JOINT filter "op<0.10 & max-axis<0.02m" removes
6-14% at only -0.002 to -0.009 dB (vs op<0.10 alone at 15-29% / -0.07 to -0.29 dB).
The joint gate confines deletion to small low-opacity fragments, avoiding the
surface-carrying small-scaled population that footprint-only deletion hits hard
(footprint<0.02m alone costs -0.5 to -1.6 dB on some seqs).

Usage: python scripts/mc_footprint_curve.py SEQ
"""
import glob, os, sys, json, numpy as np, yaml, torch
from munch import munchify
from gaussian_splatting.scene.gaussian_model import GaussianModel
from gaussian_splatting.gaussian_renderer import render
from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
from utils.camera_utils import Camera
from utils.dataset import load_dataset
def w2c(c2w):
    m=np.linalg.inv(np.asarray(c2w,np.float64)); return m[:3,:3],m[:3,3]
seq=sys.argv[1]
run=f"results/runs/P2/P2-T/{seq}_prune_seed0"
dirs=glob.glob(run+"/datasets_bonn/*/seed_0/*/"); d=max(dirs,key=lambda x:os.path.getmtime(x+"/config.yml"))
cfg=yaml.safe_load(open(d+"/config.yml")); mp=munchify(cfg["model_params"]); mp.sh_degree=3 if cfg["Training"]["spherical_harmonics"] else 0
ds=load_dataset(mp,mp.source_path,config=cfg)
proj=getProjectionMatrix2(znear=0.01,zfar=100.0,fx=ds.fx,fy=ds.fy,cx=ds.cx,cy=ds.cy,W=ds.width,H=ds.height).transpose(0,1).to("cuda")
trj=json.load(open(d+"/plot/trj_full_final.json")); pose_by_id={int(f):np.asarray(c,np.float64) for f,c in zip(trj["trj_id"],trj["trj_est"])}; fids=sorted(pose_by_id.keys())
bg=torch.tensor([0,0,0],dtype=torch.float32,device="cuda")
def psnr(g,interval=5):
    ps=[]
    with torch.no_grad():
        for fid in fids[::interval]:
            c2w=pose_by_id[fid];R,t=w2c(c2w)
            cam=Camera(int(fid),None,None,torch.eye(4,device="cuda"),proj,ds.fx,ds.fy,ds.cx,ds.cy,ds.fovx,ds.fovy,ds.height,ds.width,device="cuda")
            cam.update_RT(torch.from_numpy(np.ascontiguousarray(R)).float(),torch.from_numpy(np.ascontiguousarray(t)).float())
            cam.cam_rot_delta=None;cam.cam_trans_delta=None;cam.exposure_a=None;cam.exposure_b=None
            gi,gd,_=ds[fid]; r=torch.clamp(render(cam,g,munchify(cfg["pipeline_params"]),bg)["render"],0,1); m=gi>0
            ps.append(-10*torch.log10(torch.mean((r[m]-gi[m])**2)).item()); del cam
    return np.mean(ps)
g=GaussianModel(mp.sh_degree,config=cfg); g.load_ply(d+"/point_cloud/final_after_opt/point_cloud.ply")
sig=(1/(1+torch.exp(-g._opacity))).reshape(-1); foot=g.get_scaling.max(dim=1).values.reshape(-1)
ref=psnr(g); print(f"[{seq}] ref={ref:.4f} N={g.get_xyz.shape[0]}",flush=True)
# selection masks to test
sel = {
    "foot<0.005m": foot<0.005,
    "foot<0.01m": foot<0.01,
    "foot<0.02m": foot<0.02,
    "op<0.05 & foot<0.01": (sig<0.05)&(foot<0.01),
    "op<0.10 & foot<0.02": (sig<0.10)&(foot<0.02),
    "op<0.05|foot<0.01": (sig<0.05)|(foot<0.01),
    "op<0.10|foot<0.02": (sig<0.10)|(foot<0.02),
}
for name, mask in sel.items():
    mask=mask.cpu().numpy(); n=int(mask.sum())
    g2=GaussianModel(mp.sh_degree,config=cfg); g2.load_ply(d+"/point_cloud/final_after_opt/point_cloud.ply")
    g2._prune_raw(((torch.from_numpy(~mask))).to(g2.get_xyz.device))
    p=psnr(g2)
    print(f"  {name:22s} remove {n:>6d}({mask.mean()*100:5.1f}%) -> PSNR {p:.4f} dPSNR {p-ref:+.4f}",flush=True)
    del g2
