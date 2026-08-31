#!/usr/bin/env python3
"""p4_threshold_curve_batch.py — Direction B: threshold-continuum removal curve on ALL 18 maps.

Extends mc_opacity_deletion_curve.py to the full 18 P2-T prune maps (6 seq × 3 seeds) over a
dense threshold grid, measuring removal-% and dPSNR at each threshold. Turns "0.01 is the
coarsest safe rung" from a single operating point into a characterized structural curve.

Reads the bak P2-T prune final_after_opt maps (identical to step5b / p4_op001_full18).
Run dir = dir containing config.yml (grandparent of point_cloud/final_after_opt).
Zero training: offline interval-5 full-frame rerender at stored est poses.

Usage: python scripts/p4_threshold_curve_batch.py [--out results/evidence/p4_threshold_curve.md]
"""
import argparse, glob, json, os, sys
import numpy as np, torch, yaml
from munch import munchify

ROOT = "/data/monogs-ours"
sys.path.insert(0, ROOT); os.chdir(ROOT)
from gaussian_splatting.scene.gaussian_model import GaussianModel
from gaussian_splatting.gaussian_renderer import render
from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
from utils.camera_utils import Camera
from utils.dataset import load_dataset

# thresholds in the spirit of theory.md monotonic bound
THRESHOLDS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10]

def w2c(c2w):
    m = np.linalg.inv(np.asarray(c2w, np.float64)); return m[:3,:3], m[:3,3]

def build(index, cfg_path):
    cfg = yaml.safe_load(open(cfg_path))
    mp = munchify(cfg["model_params"]); mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    ds = load_dataset(mp, mp.source_path, config=cfg)
    return cfg, ds

def _render(cfg, ds, trj):
    mp = munchify(cfg["model_params"]); mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    proj = getProjectionMatrix2(znear=0.01, zfar=100.0, fx=ds.fx, fy=ds.fy, cx=ds.cx, cy=ds.cy, W=ds.width, H=ds.height)
    proj = proj.transpose(0,1).to("cuda")
    pose_by_id = {int(f): np.asarray(c,np.float64) for f,c in zip(trj["trj_id"], trj["trj_est"])}
    fids = sorted(pose_by_id.keys())
    bg = torch.tensor([0,0,0],dtype=torch.float32,device="cuda")
    views = []
    for fid in fids[::5]:
        R,t = w2c(pose_by_id[fid])
        cam = Camera(int(fid), None, None, torch.eye(4,device="cuda"), proj, ds.fx,ds.fy,ds.cx,ds.cy,
                     ds.fovx,ds.fovy,ds.height,ds.width, device="cuda")
        cam.update_RT(torch.from_numpy(np.ascontiguousarray(R)).float(), torch.from_numpy(np.ascontiguousarray(t)).float())
        cam.cam_rot_delta=None; cam.cam_trans_delta=None; cam.exposure_a=None; cam.exposure_b=None
        gi,_,_ = ds[fid]; gi = torch.clamp(gi,0,1).float()
        views.append((cam, gi)); del cam
    return views

def psnr(rendered, gt):
    m = gt > 0
    return -10*torch.log10(torch.mean((rendered[m]-gt[m])**2)).item()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/evidence/p4_threshold_curve.md")
    args = ap.parse_args()
    # all 18 bak prune maps
    dirs = []
    for seq in ["balloon","balloon2","mv_no_box","mv_no_box2","pt1","pt2"]:
        for seed in [0,1,2]:
            dirs.append(find_run_dir(seq, seed))
    lines = ["# Threshold-continuum removal curve (Direction B, 18 maps)\n",
             "> 2026-08-09 orbit-D. Extends mc_opacity_deletion_curve.py to all 18 P2-T prune maps. "
             "dPSNR at each sigmoid-opacity threshold; offline interval-5 full-frame rerender at stored poses, zero training.\n",
             f"Threshold grid: {THRESHOLDS}\n"]
    for d in dirs:
        try:
            cfg = yaml.safe_load(open(os.path.join(d, "config.yml")))
            g = GaussianModel(mp_sh(cfg), config=cfg); g.load_ply(os.path.join(d,"point_cloud/final_after_opt/point_cloud.ply"))
            sig = torch.sigmoid(g._opacity).reshape(-1).detach()
            trj = json.load(open(os.path.join(d,"plot/trj_full_final.json")))
            ds = load_dataset(munchify(cfg["model_params"]), munchify(cfg["model_params"]).source_path, config=cfg)
            views = _render(cfg, ds, trj)
            pipe = munchify(cfg["pipeline_params"]); bg = torch.zeros(3, device="cuda")
            # ref full-map render
            imgs0 = []
            for cam,_ in views:
                with torch.no_grad():
                    imgs0.append(torch.clamp(render(cam,g,pipe,bg)["render"],0,1))
            ref = np.mean([psnr(im,gt) for im,(_,gt) in zip(imgs0,views)])
            vals = []
            for th in THRESHOLDS:
                mask = sig < th
                g2 = GaussianModel(mp_sh(cfg), config=cfg); g2.load_ply(os.path.join(d,"point_cloud/final_after_opt/point_cloud.ply"))
                g2._prune_raw((~mask).to(g2.get_xyz.device))
                ims=[]
                for cam,_ in views:
                    with torch.no_grad():
                        ims.append(torch.clamp(render(cam,g2,pipe,bg)["render"],0,1))
                dp = np.mean([psnr(im,gt) for im,(_,gt) in zip(ims,views)]) - ref
                vals.append((th, mask.float().mean().item()*100, dp))
                del g2
            # map run dir back to seq+seed: the timestamps in print are ugly; pull seq from the run root
            # (path .../P2-T/<seq>_prune_seed<s>/...)
            segs = d.split("/")
            seq=None; sd=None
            for seg in segs:
                if ("_prune_seed" in seg) and seg.endswith(("0","1","2")):
                    seq = seg.split("_prune_seed")[0]; sd = seg.split("_prune_seed")[1]; break
            if seq is None: seq = os.path.basename(d)
            fstr = "; ".join(f"th={th:.3f} rm%={rm:.1f} dPSNR={dp:+.4f}" for th,rm,dp in vals)
            lines.append(f"- `{seq}` seed={sd}: ref {ref:.2f} dB | {fstr}")
            print(f"[OK] {seq} seed{sd} ref={ref:.2f} dB", flush=True)
        except Exception as e:
            lines.append(f"- `{os.path.basename(d)}`: FAIL {e}")
            print(f"[FAIL] {os.path.basename(d)}: {e}", flush=True)
    open(args.out,"w").write("\n".join(lines)+"\n")
    print("wrote", args.out)

def find_run_dir(seq, seed):
    base = f"/data/monogs-ours-bak/results/runs/P2/P2-T/{seq}_prune_seed{seed}"
    opt = glob.glob(base+"/**/point_cloud/final_after_opt/point_cloud.ply", recursive=True)
    if not opt: raise FileNotFoundError(f"no final_after_opt for {seq} seed{seed}")
    # strip the trailing /point_cloud/final_after_opt/point_cloud.ply → run dir (has config.yml)
    return os.path.dirname(os.path.dirname(os.path.dirname(opt[0])))

def seed(d): return d.split("_prune_seed")[1][0] if "_prune_seed" in d else "?"

def mp_sh(cfg):
    from munch import munchify
    mp = munchify(cfg["model_params"]); mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    return 3 if cfg["Training"]["spherical_harmonics"] else 0

if __name__ == "__main__":
    main()
