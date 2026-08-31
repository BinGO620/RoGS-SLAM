#!/usr/bin/env python3
"""offline — Direction B 3D recovery, diagnostic 2-gauge version.

Gauge 1 (SANITY): a static background point NOT behind the dynamic — how often does the map have
  content at it (op>0.3) at a later frame? Should be high; if low => pose/convention broken.
Gauge 2 (TARGET): an occluded-bg 3D point (behind balloon at t) — how often does the map have
  content there (op>0.3) at a later frame, and does that depth match the true bg depth?
Split "map has content there" vs "map depth matches bg" to distinguish HOLE vs content-substitution.
"""
import sys, os, glob
sys.path.insert(0, "/data/monogs-ours")
import numpy as np, cv2, torch
from scripts.probe_hole_ghost import load_run, render_frame

SEQ = "/data/Datasets/Bonn/rgbd_bonn_balloon"
RUN = ("/data/monogs-ours/results/runs/P6/P6-MASKOFF-3SEED/balloon_maskoff_seed1/"
       "datasets_bonn/p6_maskoff_prune_balloon/seed_1/2026-08-09-17-09-04")

def main():
    cfg, dataset, gaussians, trj = load_run(RUN, SEQ)
    pose_by_id = {int(f): np.asarray(tr) for f, tr in zip(trj["trj_id"], trj["trj_est"])}
    mask_f = sorted(glob.glob(os.path.join(SEQ, "dynamic_mask_gtmc", "*.png")))
    dep_f = sorted(glob.glob(os.path.join(SEQ, "depth", "*.png")))
    covs = np.array([float((cv2.imread(p, cv2.IMREAD_GRAYSCALE) > 0).mean()) for p in mask_f])
    present = [i for i in sorted(pose_by_id) if i < len(mask_f) and covs[i] > 0.10]
    fx,fy,cx,cy = dataset.fx, dataset.fy, dataset.cx, dataset.cy
    W = 10
    cache = {}
    def render_at(t2):
        if t2 not in cache:
            _, op, depr = render_frame(dataset, gaussians, cfg, pose_by_id[t2], t2)
            cache[t2] = (np.asarray(op.cpu()), np.asarray(depr.cpu()))
        return cache[t2]
    # Gauge1: static bg (mask==0, far) points reconstruct?
    stat_total, stat_ok, stat_depok = 0,0,0
    # Gauge2: occluded-bg points
    occ_total, occ_any, occ_depok = 0,0,0
    with torch.no_grad():
        for t in present[:15]:
            if t not in pose_by_id: continue
            m = cv2.imread(mask_f[t], cv2.IMREAD_GRAYSCALE) > 0
            if m.sum() < 300: continue
            lo, hi = max(0, t-W), min(len(dep_f)-1, t+W)
            bg_dep = np.full((dataset.height,dataset.width), np.inf, np.float32)
            for u in range(lo,hi+1):
                if u==t: continue
                du = cv2.imread(dep_f[u], cv2.IMREAD_UNCHANGED).astype(np.float32)/1000.0
                bg_dep = np.minimum(bg_dep, np.where((du>1.5)&(du<30), du, np.inf))
            # static bg points: far and NOT in mask
            stat_sel = (~m) & np.isfinite(bg_dep) & (bg_dep<20)
            rows,cols = np.where(stat_sel)
            if rows.size:
                idx = np.random.default_rng(t).choice(len(rows), min(40, len(rows)), replace=False)
                Rc,tc_ = pose_by_id[t][:3,:3], pose_by_id[t][:3,3]
                for k in idx:
                    r,c = rows[k],cols[k]
                    z = float(bg_dep[r,c]); Xc=np.array([(c-cx)/fx*z,(r-cy)/fy*z,z]); Xw=Rc@Xc+tc_
                    for t2 in range(min(len(dep_f)-1,t+1), hi+1):
                        if t2 not in pose_by_id: continue
                        T2=pose_by_id[t2]; Xc2=T2[:3,:3].T@(Xw-T2[:3,3])
                        if Xc2[2]<=0: continue
                        px=int(fx*Xc2[0]/Xc2[2]+cx); py=int(fy*Xc2[1]/Xc2[2]+cy)
                        if not(0<=px<dataset.width and 0<=py<dataset.height): continue
                        op1,depr=render_at(t2)
                        stat_total+=1
                        if op1[py,px]>0.3:
                            stat_ok+=1
                            if abs(float(depr[py,px])-z)<(0.5*z+0.4): stat_depok+=1
                        break
            # occluded-bg points: in mask, far bg behind
            occ_sel = m & np.isfinite(bg_dep) & (bg_dep<20)
            rows,cols = np.where(occ_sel)
            if rows.size:
                idx = np.random.default_rng(t+1).choice(len(rows), min(60,len(rows)), replace=False)
                Rc,tc_ = pose_by_id[t][:3,:3], pose_by_id[t][:3,3]
                for k in idx:
                    r,c=rows[k],cols[k]
                    z=float(bg_dep[r,c]); Xc=np.array([(c-cx)/fx*z,(r-cy)/fy*z,z]); Xw=Rc@Xc+tc_
                    for t2 in range(min(len(dep_f)-1,t+1),hi+1):
                        if t2 not in pose_by_id: continue
                        T2=pose_by_id[t2]; Xc2=T2[:3,:3].T@(Xw-T2[:3,3])
                        if Xc2[2]<=0: continue
                        px=int(fx*Xc2[0]/Xc2[2]+cx); py=int(fy*Xc2[1]/Xc2[2]+cy)
                        if not(0<=px<dataset.width and 0<=py<dataset.height): continue
                        op1,depr=render_at(t2)
                        occ_total+=1
                        if op1[py,px]>0.3:
                            occ_any+=1
                            if abs(float(depr[py,px])-z)<(0.5*z+0.4): occ_depok+=1
                        break
    print("=== Gauge1 STATIC bg (control) ===", flush=True)
    print(f"  map content at later frame: {stat_ok}/{stat_total} = {stat_ok/stat_total:.3f}", flush=True)
    print(f"  depth matches bg:          {stat_depok}/{stat_total} = {stat_depok/stat_total:.3f}", flush=True)
    print("=== Gauge2 OCCLUDED bg (behind balloon) ===", flush=True)
    print(f"  map content at later frame: {occ_any}/{occ_total} = {occ_any/occ_total:.3f}", flush=True)
    print(f"  depth matches bg:          {occ_depok}/{occ_total} = {occ_depok/occ_total:.3f}", flush=True)

if __name__ == "__main__":
    main()
