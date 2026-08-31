#!/usr/bin/env python3
"""offline (2060, zero-training) — Direction B feasibility, part 1.

Does the occluded background (hidden behind a dynamic mover) get RE-EXPOSED at neighboring
frames where the mover has left? If yes (high exposure within a short window), then the
"background hole" left by removing the dynamic object is RECOVERABLE from other frames —
i.e. temporal background-completion is well-posed (a growth/fill gate on "background later
confirmed"), not a hallucination problem.

Runs on mv_no_box (moving non-obstructing box, far wall per P-B's mask-free clean case):
  - anchor = frames where box present (GTMC cov>0.03)
  - for each anchor t, in sliding window [t-W, t+W], mark the box-silhouette pixels whose
    depth at frame u (> box_depth*1.3) shows the far wall behind => background exposed.
  - report mean exposure fraction = how much of the occluded region is re-observed nearby.
"""
import os, glob, cv2
import numpy as np


def main():
    seq = "/data/Datasets/Bonn/rgbd_bonn_moving_nonobstructing_box"
    mask_f = sorted(glob.glob(os.path.join(seq, "dynamic_mask_gtmc", "*.png")))
    dep_f = sorted(glob.glob(os.path.join(seq, "depth", "*.png")))
    covs = np.array([float((cv2.imread(p, cv2.IMREAD_GRAYSCALE) > 0).mean()) for p in mask_f])
    anchor = [i for i in range(len(covs)) if covs[i] > 0.03]
    print(f"anchors (box present, cov>0.03): {len(anchor)}", flush=True)
    for W in (5, 10, 20):
        exp = []
        for t in anchor[:80]:
            m = cv2.imread(mask_f[t], cv2.IMREAD_GRAYSCALE) > 0
            if m.sum() < 500:
                continue
            d_t = cv2.imread(dep_f[t], cv2.IMREAD_UNCHANGED).astype(np.float32) / 1000.0
            bz = d_t[m][(d_t[m] > 0) & (d_t[m] < 20)]
            if bz.size == 0:
                continue
            box_dep = np.median(bz)
            exposed = np.zeros(m.shape, bool)
            lo, hi = max(0, t - W), min(len(dep_f) - 1, t + W)
            for u in range(lo, hi + 1):
                if u == t:
                    continue
                du = cv2.imread(dep_f[u], cv2.IMREAD_UNCHANGED).astype(np.float32) / 1000.0
                exposed |= (du > box_dep * 1.3)
            exp.append(exposed[m].mean())
        exp = np.array(exp)
        if exp.size:
            print(f"  W={W}: mean exposure {exp.mean():.3f}  (n {exp.size})  "
                  f"med {np.median(exp):.3f}  p25 {np.percentile(exp, 25):.3f}  "
                  f"p75 {np.percentile(exp, 75):.3f}  max {exp.max():.3f}", flush=True)


if __name__ == "__main__":
    main()
