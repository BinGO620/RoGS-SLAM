#!/usr/bin/env python3
"""p4_cohort_spatial.py — Direction A: spatial/geometric structure of the op<0.01 cohort.

For a run dir, load final_after_opt PLY. Compute:
  - cohort frac (op<0.01)
  - mean NN distance of cohort members to each other (aggregation within cohort)
  - mean distance of cohort members to the 'surface' = nearest high-opacity (>0.9) gaussian
  - fraction of cohort with a high-op neighbor within log-scale radii r (attached vs isolated floater)
Zero GPU. Uses sklearn KDTree on xyz.
"""
import argparse, glob, os, sys
import numpy as np, torch
from plyfile import PlyData
from scipy.spatial import cKDTree

TH = 0.01; HIGH = 0.9
def expit(x): return 1/(1+np.exp(-x))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--max-cohort-sample", type=int, default=20000)
    args=ap.parse_args()
    d=args.run_dir
    ply=PlyData.read(os.path.join(d,"point_cloud/final_after_opt/point_cloud.ply"))
    dat=ply.elements[0].data
    xyz=np.stack([np.asarray(dat["x"],float),np.asarray(dat["y"],float),np.asarray(dat["z"],float)],axis=1)
    op=expit(np.asarray(dat["opacity"],float))
    n=len(xyz)
    cohort = op < TH
    high  = op >= HIGH
    k=cohort.sum(); h=high.sum()
    print(f"run {os.path.basename(d)}: N={n} cohort={k} ({k/n*100:.2f}%) high-op={h} ({h/n*100:.2f}%)", flush=True)
    res={"n":int(n),"cohort_frac":float(k/n),"high_frac":float(h/n)}
    if k==0 or h==0:
        print("  (no cohort or no high-op; skip geometry)"); return res
    # subsample cohort for NN (hard aggregations)
    idx=np.where(cohort)[0]
    if len(idx)>args.max_cohort_sample:
        idx=np.random.default_rng(int(np.random.get_state()[1][0])%2**32).choice(idx,args.max_cohort_sample,replace=False)
    xc=xyz[idx]; hidx=np.where(high)[0]
    xh=xyz[hidx]
    # (1) intra-cohort NN distance
    tree_c=cKDTree(xc)
    if len(xc)>1:
        nn,_=tree_c.query(xc,k=2)
        mean_intra=nn[:,1].mean()
    else:
        mean_intra=float("nan")
    # (2) cohort -> high-op surface distance
    tree_h=cKDTree(xh)
    dh,_=tree_h.query(xc,k=3)   # to 3 nearest high-op
    mean_surf=dh.mean(axis=0)   # dist to nearest/2nd/3rd high-op
    # (3) fraction of cohort with a high-op neighbor within radii
    radii=[0.01,0.02,0.05,0.1,0.2,0.5]
    attach={}
    d0,_=tree_h.query(xc,k=1)
    for r in radii:
        attach[r]=float((d0<r).mean())
    res["intra_nn_mean"]=float(mean_intra)
    res["to_surface_nn12"]=[float(mean_surf[0]),float(mean_surf[1])]
    res["frac_with_highop_neighbor"]=attach
    print(f"  intra-cohort mean NN = {mean_intra:.4f} m", flush=True)
    print(f"  cohort->high-op dist nearest/2nd = {mean_surf[0]:.4f}/{mean_surf[1]:.4f} m", flush=True)
    print(f"  frac cohort w/ high-op neighbor: { {r:round(v,3) for r,v in attach.items()} }", flush=True)
    return res

if __name__=="__main__":
    main()
