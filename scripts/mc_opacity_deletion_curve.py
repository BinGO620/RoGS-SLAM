#!/usr/bin/env python3
"""map-compression STEP 1a: opacity-quantile deletion -> PSNR curve.

WHY THIS EXISTS. Both free-space directions are dead. The live hypothesis is
map-compression: can we delete Gaussians that contribute little to the rendered
output without degrading tracking/rendering? Before touching live SLAM code we
need to know whether a SAFE DELETION SET even exists in the final maps. This
probe re-renders a saved final PLY at the saved est poses (the paper-table render
path), deletes everything below a sigmoid-opacity threshold, and measures the
PSNR change. It mirrors the stage0/forward probes: zero-GPU training, offline
re-render of saved artifacts, writes nothing to the run.

PRIMARY READOUT. At what deletion fraction does |dPSNR| exceed ~0.05-0.1 dB?
If a large fraction (say 15-20%) can be removed for under 0.05 dB, a genuine
prune-style compactness lever exists in the FINAL map — worth testing whether it
also holds in the LIVE loop (that is a separate, GPU-bound question).

CAVEAT (pre-registered). This measures RENDERING preservation at the FINAL map
with FROZEN est poses. It does NOT measure live-tracking preservation — deleting
the same Gaussians mid-run could (a) free memory/iteration budget and help, or
(b) remove structure the tracker needs and hurt ATE. The offline gate only tells
us the compactness lever has headroom in the map; the ATE question needs a live run.

Usage: python scripts/mc_opacity_deletion_curve.py SEQ  (SEQ in balloon,mv_no_box,pt1,pt2)
Reads run results/runs/P2/P2-T/{SEQ}_prune_seed0. Interval-5 full-frame PSNR at est poses.
"""
import glob
import json
import os
import sys

import numpy as np
import torch
import yaml
from munch import munchify
from plyfile import PlyData

from gaussian_splatting.gaussian_renderer import render
from gaussian_splatting.scene.gaussian_model import GaussianModel
from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
from utils.camera_utils import Camera
from utils.dataset import load_dataset


def w2c(c2w):
    m = np.linalg.inv(np.asarray(c2w, np.float64))
    return m[:3, :3], m[:3, 3]


def main():
    seq = sys.argv[1]
    run = f"results/runs/P2/P2-T/{seq}_prune_seed0"
    dirs = glob.glob(run + "/datasets_bonn/*/seed_0/*/")
    d = max(dirs, key=lambda x: os.path.getmtime(x + "/config.yml"))
    cfg = yaml.safe_load(open(d + "/config.yml"))
    mp = munchify(cfg["model_params"])
    mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    ds = load_dataset(mp, mp.source_path, config=cfg)
    proj = getProjectionMatrix2(znear=0.01, zfar=100.0, fx=ds.fx, fy=ds.fy,
                                cx=ds.cx, cy=ds.cy, W=ds.width, H=ds.height)
    proj = proj.transpose(0, 1).to("cuda")
    trj = json.load(open(d + "/plot/trj_full_final.json"))
    pose_by_id = {int(f): np.asarray(c, np.float64) for f, c in zip(trj["trj_id"], trj["trj_est"])}
    fids = sorted(pose_by_id.keys())
    bg = torch.tensor([0, 0, 0], dtype=torch.float32, device="cuda")

    def psnr(g, interval=5):
        ps = []
        with torch.no_grad():
            for fid in fids[::interval]:
                c2w = pose_by_id[fid]
                R, t = w2c(c2w)
                cam = Camera(int(fid), None, None, torch.eye(4, device="cuda"), proj,
                             ds.fx, ds.fy, ds.cx, ds.cy, ds.fovx, ds.fovy,
                             ds.height, ds.width, device="cuda")
                cam.update_RT(torch.from_numpy(np.ascontiguousarray(R)).float(),
                              torch.from_numpy(np.ascontiguousarray(t)).float())
                cam.cam_rot_delta = None
                cam.cam_trans_delta = None
                cam.exposure_a = None
                cam.exposure_b = None
                gi, gd, _ = ds[fid]
                r = torch.clamp(render(cam, g, munchify(cfg["pipeline_params"]), bg)["render"], 0, 1)
                m = gi > 0
                ps.append(-10 * torch.log10(torch.mean((r[m] - gi[m]) ** 2)).item())
                del cam
        return np.mean(ps)

    g = GaussianModel(mp.sh_degree, config=cfg)
    g.load_ply(d + "/point_cloud/final_after_opt/point_cloud.ply")
    sig = (1 / (1 + torch.exp(-g._opacity))).reshape(-1)
    ref = psnr(g)
    print(f"[{seq}] ref={ref:.4f} N={g.get_xyz.shape[0]}", flush=True)
    for q in [0.01, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20]:
        mask = sig < q
        n = int(mask.sum())
        g2 = GaussianModel(mp.sh_degree, config=cfg)
        g2.load_ply(d + "/point_cloud/final_after_opt/point_cloud.ply")
        g2._prune_raw((~mask).to(g2.get_xyz.device))
        p = psnr(g2)
        print(f"  keep op>={q}: remove {n:>6d}({mask.float().mean() * 100:5.1f}%) -> PSNR {p:.4f} dPSNR {p - ref:+.4f}", flush=True)
        del g2


if __name__ == "__main__":
    main()
