#!/usr/bin/env python3
"""Matched-rate deletion controls (reviewer requirement Round 1).

Compares deleting the SAME removal fraction of gaussians by three policies:
  low-op  : delete the lowest-opacity gaussians (our terminal claim)
  high-op : delete the highest-opacity gaussians (stress test: random/high should hurt most)
  random  : delete a random subset (control: is ANY deletion harmless?)

The key question: at matched removal fraction, does ONLY the low-opacity cohort preserve
PSNR/SSIM/LPIPS? If random or high-op is equally harmless, the terminal-cleanup headline
is trivial (any deletion is cheap) and must be dropped.

CPU/offline: loads existing final_after_opt PLY + trajectory, renders interval-5.
Same instrument as mc_terminal_comp_3seed. Runs GPU render (short) but NO retraining.

Usage:
  python scripts/p3_matched_rate_deletion.py --run <run_dir> --frac <fraction e.g. 0.10>
"""
import argparse, json, os, sys
from pathlib import Path
import yaml, torch, numpy as np
from munch import munchify

ROOT = Path("/data/monogs-ours")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from gaussian_splatting.scene.gaussian_model import GaussianModel
from utils.dataset import load_dataset

# The mc_terminal_comp render_psnr is the reliable instrument; reuse its import path.
from scripts.mc_terminal_comp_3seed import render_psnr  # noqa: E402

def load(cfg_path, ply_path, trj_path):
    cfg = yaml.safe_load(open(cfg_path))
    mp = munchify(cfg["model_params"]); mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    ds = load_dataset(mp, mp.source_path, config=cfg)
    from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
    proj = getProjectionMatrix2(znear=0.01, zfar=100.0, cx=ds.cx, cy=ds.cy, fx=ds.fx, fy=ds.fy, W=ds.width, H=ds.height)
    proj = proj.transpose(0, 1).to("cuda")
    trj = json.load(open(trj_path))
    return cfg, mp, ds, proj, trj

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--frac", type=float, default=0.12, help="removal fraction (default 0.12 ~ low-op tail size)")
    args = ap.parse_args()
    run_dir = Path(args.run)
    cfg_path = run_dir/"config.yml"; ply_path = run_dir/"point_cloud"/"final_after_opt"/"point_cloud.ply"; trj_path = run_dir/"plot"/"trj_full_final.json"
    for p in (cfg_path, ply_path, trj_path): assert p.is_file(), p

    cfg, mp, ds, proj, trj = load(cfg_path, ply_path, trj_path)

    def render(g):
        cfg_t = yaml.safe_load(open(cfg_path))
        mp_t = munchify(cfg_t["model_params"]); mp_t.sh_degree = 3 if cfg_t["Training"]["spherical_harmonics"] else 0
        return render_psnr(g, cfg_t, ds, trj, proj)

    g = GaussianModel(mp.sh_degree, config=cfg); g.load_ply(str(ply_path))
    ref = render(g)
    sig = (1/(1+torch.exp(-g._opacity))).reshape(-1).detach().cpu().numpy()
    n = int(g.get_xyz.shape[0])
    n_rm = int(round(n * args.frac))
    rng = np.random.default_rng(0)

    policies = {
        "low_op":  np.argsort(sig)[:n_rm],
        "high_op": np.argsort(sig)[-n_rm:],
        "random":  rng.choice(n, n_rm, replace=False),
    }
    for name, idx in policies.items():
        keep = np.ones(n, bool); keep[idx] = False
        g2 = GaussianModel(mp.sh_degree, config=cfg); g2.load_ply(str(ply_path))
        g2._prune_raw(torch.from_numpy(keep).to(g2.get_xyz.device))
        p = render(g2)
        print(f"{name:8s} n_rm={n_rm:6d} ({args.frac*100:.1f}%)  psnr_ref={ref:.4f}  psnr_del={p:.4f}  dPSNR={p-ref:+.4f}")

if __name__ == "__main__":
    main()
