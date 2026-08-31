#!/usr/bin/env python3
"""STEP 2A — terminal compression, 3-seed replication (zero-GPU offline).

WHY. STEP4's online per-window compress is a mechanism-mismatch: the ledger shows
compress removed 2-12x the final-map count, yet final N is DECIDED BY the insertion
budget (uncapped clone/split + max_candidates_per_keyframe=5000), not by deletion.
So the runtime axis for END-MAP compactness is the TERMINAL pass — exactly what the
offline STEP1 gate measured (12.6-23.6% at <=0.016 dB) but only on seed-0.

THIS SCRIPT: replicates the STEP1 terminal-deletion measurement on ALL 3 seeds of the
base prune runs (4 seqs x 3 seeds = 12 run dirs), at the STEP1-safe thresholds
op<0.01 and op<0.05, re-rendering the post-deletion final_after_opt PLY at the saved
est poses (the paper-table render path). Outputs a 3-seed replication table so a
GO/NO-GO on "terminal compression is a real, replicable compactness result" no longer
rests on a single seed (CONTEXT:156 single-seed rule).

Mechanism probe (part of 2A): also dumps the sigmoid-opacity histogram of each compress
run's final map vs that of the matching base run, to test whether online compress
leaves the low-opacity tail intact (ADC regrowth) or actually shifts the distribution.

Usable for: base prism runs AND the compress runs (the mechanism probe). Not for pt2
compress (--fast, no final_after_opt PLY).

OUTPUTS (PO inside each run dir, never touches the run):
  <run>/posthoc_terminal_comp/{op010,op050}/fullframe_summary.json
  <run>/posthoc_terminal_comp/opacity_histogram.json   (+ base run's, for mechanism)
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import torch
import yaml
from munch import munchify

# ensure repo root is importable when invoked as `python scripts/mc_*.py`
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gaussian_splatting.scene.gaussian_model import GaussianModel
from gaussian_splatting.gaussian_renderer import render
from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
from utils.camera_utils import Camera
from utils.dataset import load_dataset


def w2c(c2w):
    m = np.linalg.inv(np.asarray(c2w, np.float64))
    return m[:3, :3], m[:3, 3]


def _finite_mean(vals):
    vals = [v for v in vals if np.isfinite(v)]
    return mean(vals) if vals else float("nan")


def opacity_hist(g, nbins=64):
    sig = (1 / (1 + torch.exp(-g._opacity))).reshape(-1).detach().cpu().float().numpy()
    hist, edges = np.histogram(sig, bins=nbins, range=(0.0, 1.0))
    return hist.tolist(), edges.tolist(), {
        "n_total": int(len(sig)),
        "frac_op_lt_001": float((sig < 0.01).mean()),
        "frac_op_lt_005": float((sig < 0.05).mean()),
        "frac_op_lt_010": float((sig < 0.10).mean()),
        "frac_op_ge_090": float((sig >= 0.90).mean()),
    }


def render_psnr(g, cfg, ds, trj, proj, interval=5):
    mp = munchify(cfg["pipeline_params"])
    bg = torch.tensor([0, 0, 0], dtype=torch.float32, device="cuda")
    pose_by_id = {int(f): np.asarray(c, np.float64) for f, c in zip(trj["trj_id"], trj["trj_est"])}
    fids = sorted(pose_by_id.keys())
    ps = []
    with torch.no_grad():
        for fid in fids[::interval]:
            R, t = w2c(pose_by_id[fid])
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
            r = torch.clamp(render(cam, g, mp, bg)["render"], 0, 1)
            m = gi > 0
            ps.append(-10 * torch.log10(torch.mean((r[m] - gi[m]) ** 2)).item())
            del cam
    return float(np.mean(ps))


def terminal_pass(run_dir, threshold, out_name="posthoc_terminal_comp"):
    """Delete all sigmoid-opacity < threshold from final_after_opt, re-render, write summary."""
    cfg_path = os.path.join(run_dir, "config.yml")
    ply = os.path.join(run_dir, "point_cloud", "final_after_opt", "point_cloud.ply")
    trj_path = os.path.join(run_dir, "plot", "trj_full_final.json")
    for p in (cfg_path, ply, trj_path):
        if not os.path.isfile(p):
            raise FileNotFoundError(f"missing: {p}")
    cfg = yaml.safe_load(open(cfg_path))
    mp = munchify(cfg["model_params"])
    mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    ds = load_dataset(mp, mp.source_path, config=cfg)
    proj = getProjectionMatrix2(znear=0.01, zfar=100.0, fx=ds.fx, fy=ds.fy,
                                cx=ds.cx, cy=ds.cy, W=ds.width, H=ds.height)
    proj = proj.transpose(0, 1).to("cuda")
    trj = json.load(open(trj_path))

    g = GaussianModel(mp.sh_degree, config=cfg)
    g.load_ply(ply)
    ref = render_psnr(g, cfg, ds, trj, proj)
    sig = (1 / (1 + torch.exp(-g._opacity))).reshape(-1)
    mask = sig < threshold
    n_total = int(g.get_xyz.shape[0])
    n_rm = int(mask.sum())

    g2 = GaussianModel(mp.sh_degree, config=cfg)
    g2.load_ply(ply)
    g2._prune_raw((~mask).to(g2.get_xyz.device))
    p = render_psnr(g2, cfg, ds, trj, proj)

    out_dir = os.path.join(run_dir, out_name, f"op{int(threshold*1000):03d}")
    os.makedirs(out_dir, exist_ok=True)
    summary = {
        "run_dir": run_dir,
        "threshold": threshold,
        "n_total": n_total,
        "n_removed": n_rm,
        "removal_frac": n_rm / max(n_total, 1),
        "psnr_ref": round(ref, 4),
        "psnr_terminal": round(p, 4),
        "dpsnr": round(p - ref, 4),
        "frames_scored": (len(sorted(trj["trj_id"])) + 4) // 5,
    }
    json.dump(summary, open(os.path.join(out_dir, "terminal_summary.json"), "w"), indent=2)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--thresholds", default="0.01,0.05")
    ap.add_argument("--hist-only", action="store_true", help="only dump opacity histogram, skip render")
    ap.add_argument("--skip-render", action="store_true", help="compute deletion counts only, no PSNR")
    args = ap.parse_args()
    ths = [float(t) for t in args.thresholds.split(",")]
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for run_dir in args.run_dirs:
        try:
            # mechanism probe: dump opacity histogram regardless
            cfg = yaml.safe_load(open(os.path.join(run_dir, "config.yml")))
            mp = munchify(cfg["model_params"]); mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
            g = GaussianModel(mp.sh_degree, config=cfg)
            ply = os.path.join(run_dir, "point_cloud", "final_after_opt", "point_cloud.ply")
            if os.path.isfile(ply):
                g.load_ply(ply)
                h, edges, stats = opacity_hist(g)
                os.makedirs(os.path.join(run_dir, "posthoc_terminal_comp"), exist_ok=True)
                json.dump({"hist": h, "edges": edges, "stats": stats},
                          open(os.path.join(run_dir, "posthoc_terminal_comp", "opacity_histogram.json"), "w"), indent=2)
                print(f"HIST {os.path.basename(run_dir)}: {json.dumps(stats)}", flush=True)
        except Exception as exc:
            print(f"HIST-FAIL {run_dir}: {exc}")
        if args.hist_only:
            continue
        for th in ths:
            try:
                s = terminal_pass(run_dir, th)
                print(f"TERM {os.path.basename(run_dir)} op<{th}: "
                      f"rm {s['n_removed']}/{s['n_total']} ({s['removal_frac']*100:.1f}%) "
                      f"dPSNR={s['dpsnr']:+.4f}", flush=True)
            except Exception as exc:
                print(f"TERM-FAIL {os.path.basename(run_dir)} op<{th}: {exc}")

    print("DONE 2A")


if __name__ == "__main__":
    from statistics import mean
    main()
