#!/usr/bin/env python3
"""offline (2060) — Direction B, balloon edition.

mv_no_box probe said the bundle already self-fills (op 0.99, depth=wall) => in that low-texture
clean context, background completion is already-solved, not needed. The real hole is the
FAR-dynamic / busy-background / mixed-mover case (balloon). Here we quantify on balloon:
  1. how much of the dynamic-mask region is self-filled in the map (map self-fill),
  2. how observable that occluded background is in neighboring frames (recoverability).
This decides whether "temporal background completion" is a needed + well-posed fix on balloon."""
import sys
sys.path.insert(0, "/data/monogs-ours")
import numpy as np, os, glob, cv2, torch
from scripts.probe_hole_ghost import load_run, render_frame


def main():
    seq = "/data/Datasets/Bonn/rgbd_bonn_balloon"
    run = ("/data/monogs-ours/results/runs/P6/P6-MASKOFF-3SEED/balloon_maskoff_seed1/"
           "datasets_bonn/p6_maskoff_prune_balloon/seed_1/2026-08-09-17-09-04")
    cfg, dataset, gaussians, trj = load_run(run, seq)
    pose_by_id = {int(f): np.asarray(tr) for f, tr in zip(trj["trj_id"], trj["trj_est"])}
    mask_f = sorted(glob.glob(os.path.join(seq, "dynamic_mask_gtmc", "*.png")))
    dep_f = sorted(glob.glob(os.path.join(seq, "depth", "*.png")))
    covs = np.array([float((cv2.imread(p, cv2.IMREAD_GRAYSCALE) > 0).mean()) for p in mask_f])
    present = [i for i in sorted(pose_by_id) if i < len(mask_f) and covs[i] > 0.05]
    print(f"balloon present frames (cov>0.05, n pose): {len(present)}", flush=True)
    # Part A: map self-fill in mask region
    ops, maskdeps, fulldeps, boxdeps = [], [], [], []
    with torch.no_grad():
        for t in present[:40]:
            if t not in pose_by_id: continue
            img, op, depr = render_frame(dataset, gaussians, cfg, pose_by_id[t], t)
            m = cv2.imread(mask_f[t], cv2.IMREAD_GRAYSCALE) > 0
            if m.sum() < 300: continue
            opm = np.asarray(op.cpu())[m]; dm = np.asarray(depr.cpu())[m]
            dm = dm[dm > 0]; full = np.asarray(depr.cpu())[np.asarray(depr.cpu()) > 0]
            gt = cv2.imread(dep_f[t], cv2.IMREAD_UNCHANGED).astype(np.float32) / 1000.0
            gtm = gt[m][(gt[m] > 0) & (gt[m] < 30)]
            if dm.size and full.size:
                ops.append(opm.mean()); maskdeps.append(np.median(dm)); fulldeps.append(np.median(full))
            if gtm.size: boxdeps.append(np.median(gtm))
    ops, maskdeps, fulldeps = np.array(ops), np.array(maskdeps), np.array(fulldeps)
    print("=== balloon map self-fill (mask-free bundle final PLY) ===", flush=True)
    print(f"  render_op@mask mean={ops.mean():.3f}  frac>0.5={np.mean(ops>0.5):.3f}", flush=True)
    print(f"  render_dep@mask med={np.median(maskdeps):.2f}  full-render med={np.median(fulldeps):.2f}", flush=True)
    print(f"  (balloon dynamic contains far objects; if render_dep@mask > full by a lot => FOGGY HOLE)",
          flush=True)

    # Part B: occluded-background recoverability in window (depth-exceeds-dynamic threshold)
    anchor = [i for i in range(len(covs)) if covs[i] > 0.05]
    print(f"=== balloon occluded-bg recoverability ({len(anchor)} present anchors) ===", flush=True)
    for W in (5, 10, 20):
        exp = []
        for t in anchor[:60]:
            m = cv2.imread(mask_f[t], cv2.IMREAD_GRAYSCALE) > 0
            if m.sum() < 300: continue
            gt = cv2.imread(dep_f[t], cv2.IMREAD_UNCHANGED).astype(np.float32) / 1000.0
            gtm = gt[m][(gt[m] > 0) & (gt[m] < 30)]
            if gtm.size == 0: continue
            thr = np.median(gtm) * 1.3
            exposed = np.zeros(m.shape, bool)
            lo, hi = max(0, t - W), min(len(dep_f) - 1, t + W)
            for u in range(lo, hi + 1):
                if u == t: continue
                du = cv2.imread(dep_f[u], cv2.IMREAD_UNCHANGED).astype(np.float32) / 1000.0
                exposed |= (du > thr)
            exp.append(exposed[m].mean())
        exp = np.array(exp)
        if exp.size:
            print(f"  W={W}: exposure mean={exp.mean():.3f} med={np.median(exp):.3f} "
                  f"p25={np.percentile(exp,25):.3f} p75={np.percentile(exp,75):.3f} max={exp.max():.3f} (n {exp.size})", flush=True)


if __name__ == "__main__":
    main()
