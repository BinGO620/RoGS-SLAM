"""Consolidate the corrected, reproducible pose-reg probe (C2W convention) into ONE script 
that regenerates every headline number, so the conclusion is auditable by codex/hermes."""
import json, numpy as np, glob
from evo.core import metrics, trajectory
from evo.core.trajectory import PoseTrajectory3D

TRJ = "results/probes/pose_reg/edge3/pt1_edge3_seed0_trj.json"
def ate(a,b):
    a=[np.array(T,float) for T in a]; b=[np.array(T,float) for T in b]
    tr=PoseTrajectory3D(poses_se3=b,timestamps=np.arange(len(b)))
    te=PoseTrajectory3D(poses_se3=a,timestamps=np.arange(len(a)))
    ta=trajectory.align_trajectory(te,tr,correct_scale=False)
    m=metrics.APE(metrics.PoseRelation.translation_part); m.process_data((tr,ta))
    return float(m.get_all_statistics()["rmse"])*100

d=json.load(open(TRJ)); est=np.array(d["trj_est"],float); gt=np.array(d["trj_gt"],float)
ce=np.array([T[:3,3] for T in est]); cg=np.array([T[:3,3] for T in gt])  # C2W centers
print("=== CORRECTED (C2W) probe, pt1 edge3 seed0 ===")
print("full ATE:", round(ate(list(est),list(gt)),2))
print("path-length ratio est/gt:", round(float(np.linalg.norm(np.diff(ce,axis=0),axis=1).sum()/np.linalg.norm(np.diff(cg,axis=0),axis=1).sum()),3))
print("raw cam-center dist mean/max(cm):", round(float(np.linalg.norm(ce-cg,axis=1).mean())*100,1), round(float(np.linalg.norm(ce-cg,axis=1).max())*100,1))
# rotation sign
def yaw(R): return np.arctan2(R[1,0],R[0,0])
ey=np.array([yaw(T) for T in est]); gy=np.array([yaw(T) for T in gt])
er=np.diff(np.unwrap(ey))*180/np.pi; gr=np.diff(np.unwrap(gy))*180/np.pi
mov=np.abs(gr)>0.3
print(f"rotation sign: mov_frames={mov.sum()}  opposite_frac={ ((er[mov]*gr[mov])<0).mean():.3f}  corr={np.corrcoef(er[mov],gr[mov])[0,1]:.3f}")
# drive: rotation vs translation
mix_r=[(lambda T: T)(est[i]) for i in range(len(est))]  # placeholder
out2=[]
for i in range(len(est)):
    T4=est[i].copy(); T4[:3,:3]=gt[i][:3,:3]; out2.append(T4)   # gtROT estTRANS
print("gtROT + estTRANS ATE:", round(ate(list(out2),list(gt)),2), "(= full => rotation contrib 0)")
out1=[]
for i in range(len(est)):
    T4=est[i].copy(); T4[:3,3]=gt[i][:3,3]; out1.append(T4)     # estROT gtTRANS
print("estROT + gtTRANS ATE:", round(ate(list(out1),list(gt)),2), "(=0 => translation 100%)")
# length/direction split
de=np.diff(ce,axis=0); dg=np.diff(cg,axis=0)
dir_e=de/(np.linalg.norm(de,axis=1,keepdims=True)+1e-12); le=np.linalg.norm(de,axis=1)
dir_g=dg/(np.linalg.norm(dg,axis=1,keepdims=True)+1e-12); lg=np.linalg.norm(dg,axis=1)
def to_se3(cc): return np.array([[[1,0,0,-c[0]],[0,1,0,-c[1]],[0,0,1,-c[2]],[0,0,0,1]] for c in cc])
def dr(dirv,lenv,base):
    tr=[base]
    for i in range(len(dirv)): tr.append(tr[-1]+dirv[i]*lenv[i])
    return np.array(tr)
print("GTlen+estdir (dir-only):", round(ate(to_se3(dr(dir_e,lg,cg[0])).tolist(),to_se3(cg).tolist()),2))
print("estlen+GTdir (len-only):", round(ate(to_se3(dr(dir_g,le,cg[0])).tolist(),to_se3(cg).tolist()),2))
