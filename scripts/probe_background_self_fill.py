#!/usr/bin/env python3
"""offline (2060, zero-training) — Direction B feasibility, part 2.

Does the map ALREADY reconstruct the background behind the dynamic mover (map self-fills),
or does removing the mover leave a hole the map cannot fill?

Re-render the saved final PLY at saved poses, and for frames where the box is present look at
the box-silhouette region:
  - if render_op @ mask ~ 1.0 AND render_depth@mask ≈ surrounding wall depth (not the near box,
    not a far gap) => background already reconstructed (map self-fills, no hole)
  - if render_op @ mask ~ 0 => a hole (vacancy the map couldn't fill) => temporal completion
    is a real fix.

Runs on the P6 maskoff mv_no_box 3-seed run (mask-free kernel, P-B's clean context)."""
import sys
sys.path.insert(0, "/data/monogs-ours")
import numpy as np, os, glob, cv2, torch
from scripts.probe_hole_ghost import load_run, render_frame

RUN = ("/data/monogs-ours/results/runs/P6/P6-MASKOFF-3SEED/mv_no_box_maskoff_seed1/"
       "datasets_bonn/p6_maskoff_prune_mv_no_box/seed_1/2026-08-09-17-09-03")
SEQ = "/data/Datasets/Bonn/rgbd_bonn_moving_nonobstructing_box"


def main():
    cfg, dataset, gaussians, trj = load_run(RUN, SEQ)
    pose_by_id = {int(f): np.asarray(tr) for f, tr in zip(trj["trj_id"], trj["trj_est"])}
    mask_f = sorted(glob.glob(os.path.join(SEQ, "dynamic_mask_gtmc", "*.png")))
    covs = np.array([float((cv2.imread(p, cv2.IMREAD_GRAYSCALE) > 0).mean()) for p in mask_f])
    present = [i for i in sorted(pose_by_id) if i < len(mask_f) and covs[i] > 0.04]
    print(f"n present (box covering >4%): {len(present)}", flush=True)
    ops, maskdeps, fulldeps = [], [], []
    with torch.no_grad():
        for t in present[:40]:
            if t not in pose_by_id:
                continue
            img, op, depr = render_frame(dataset, gaussians, cfg, pose_by_id[t], t)
            m = cv2.imread(mask_f[t], cv2.IMREAD_GRAYSCALE) > 0
            op = np.asarray(op.cpu()); depr = np.asarray(depr.cpu())
            om = op[m]; dm = depr[m][depr[m] > 0]
            full = depr[depr > 0]
            if dm.size == 0 or full.size == 0:
                continue
            ops.append(om.mean()); maskdeps.append(np.median(dm)); fulldeps.append(np.median(full))
    ops, maskdeps, fulldeps = np.array(ops), np.array(maskdeps), np.array(fulldeps)
    print("mask-region render analysis (final PLY, mask-free bundle):", flush=True)
    print(f"  render_op@mask      : mean {ops.mean():.3f}  "
          f"frac>0.5 {np.mean(ops>0.5):.3f}   -> {'filled' if ops.mean()>0.5 else 'HOLE'}", flush=True)
    print(f"  render_dep@mask med : {np.median(maskdeps):.2f} m", flush=True)
    print(f"  full-render deep med: {np.median(fulldeps):.2f} m  (surrounding wall reference)", flush=True)
    print(f"  -> mask-render depth ~ wall ({np.median(fulldeps):.2f})? "
          f"{'YES (background reconstructed)' if abs(np.median(fulldeps)-np.median(maskdeps)) < 0.6 else 'NO (hole/discrepancy)'}", flush=True)


if __name__ == "__main__":
    main()
