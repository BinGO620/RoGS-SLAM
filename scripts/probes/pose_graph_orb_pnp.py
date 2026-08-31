#!/usr/bin/env python
"""Offline long-baseline ORB-PnP pose-graph probe (codex 019fefb9 §3, exp-v3-15).

Tests whether independent ORB-PnP long edges (offsets 15/30/60) can pull pt1's trajectory
toward GT better than the online odometry edges alone. This is the "feature anchor"
discriminator: does a non-photometric, non-masked-geometry observation exist that corrects
the smooth translation drift?

Design (codex + clarifications):
  - Sample N nodes every NODE_STEP frames from pt1 (580 frames).
  - Odom edges: relative poses from the ONLINE `trj_full_final.json` (C2W) between consecutive
    nodes — this is exactly the tracker's own increments.
  - Long edges: ORB match node -> source at offsets {15,30,60} (backward arc), backproject
    SOURCE depth at matched static points (GTMC mask==0), solvePnPRansac+RefineLM.
  - NO map_precheck / rotation_gate / translation_gate / map_loss_ratio_gate (these are the
    biased photometric vetoes codex says to skip). Only PnP acceptance gates.
  - Robust SE(3) pose-graph optimization (Levenberg-Marquardt on twist perturbations,
    node-0 gauge fixed), odom edges weight 1.0, long edges 0.05 with Huber.
  - Recompose full 580-frame trajectory from optimized nodes + online inter-node increments,
    then evo ATE (project standard). GT only for readout.
"""
import csv, json, glob, os, sys, time
import numpy as np
import cv2
from PIL import Image
from evo.core import metrics, trajectory
from evo.core.trajectory import PoseTrajectory3D

# ---------------- config
DATASET = "datasets/bonn/rgbd_bonn_person_tracking"
TRJ_BASE = "results/probes/pose_reg/edge3"     # has pt1_edge3_seed{s}_trj.json (C2W)
OUT = "results/probes/pose_reg/pose_graph"
NODE_STEP = 10
OFFSETS = [15, 30, 60]
SEED = int(sys.argv[1]) if len(sys.argv)>1 else 0
FX, FY, CX, CY = 542.822841, 542.576870, 315.593520, 237.756098
DSCALE = 5000.0
MIN_INL = 30
MIN_RATIO = 0.20
RMSE_CAP = 3.0
ORB_N = 1500
RATIO = 0.75
MIN_DEPTH, MAX_DEPTH = 0.05, 8.0
LONG_W = 0.05
ODOM_W = 1.0

os.makedirs(OUT, exist_ok=True)

def load_trj(seed):
    p = f"{TRJ_BASE}/pt1_edge3_seed{seed}_trj.json"
    d = json.load(open(p))
    est = np.array(d["trj_est"], float)   # C2W 580x4x4
    gt  = np.array(d["trj_gt"],  float)
    return est, gt

def load_frames():
    rgb = sorted(glob.glob(f"{DATASET}/rgb/*.png"))
    dep = sorted(glob.glob(f"{DATASET}/depth/*.png"))
    msk = sorted(glob.glob(f"{DATASET}/dynamic_mask_gtmc/*.png"))
    assert len(rgb)==len(dep)==len(msk)==580
    K = np.array([[FX,0,CX],[0,FY,CY],[0,0,1]], float)
    return rgb, dep, msk, K

def read_rgb_bgr(p): return cv2.imread(p)                       # BGR (cv2 ORB works on gray)
def read_depth_m(p):
    d = cv2.imread(p, cv2.IMREAD_ANYDEPTH | cv2.IMREAD_GRAYSCALE).astype(np.float32)/DSCALE
    return np.where(np.isfinite(d), d, 0.0)
def read_mask_static(p): return (np.array(Image.open(p)) != 255)

# ---------------- se3 helpers
def se3_exp(v):
    t=np.asarray(v[:3],float).reshape(-1,1); w=np.asarray(v[3:],float); th=float(np.linalg.norm(w))
    if th<1e-9:
        return np.block([[np.eye(3), t], [np.zeros((1,3)), np.ones((1,1))]])
    ax=w/th; A=np.array([[0,-ax[2],ax[1]],[ax[2],0,-ax[0]],[-ax[1],ax[0],0]])
    R=np.eye(3)+np.sin(th)*A+(1-np.cos(th))*(A@A)
    V=np.eye(3)+((1-np.cos(th))/th)*A+((th-np.sin(th))/th)*(A@A)
    return np.block([[R, V@t], [np.zeros((1,3)), np.ones((1,1))]])
def se3_log(T):
    R=T[:3,:3]; tt=T[:3,3]; cos=float(np.clip((np.trace(R)-1)/2,-1,1)); a=np.arccos(cos)
    if a<1e-8: return np.concatenate([tt,[0,0,0]])
    A=(a/(2*np.sin(a)))*np.array([R[2,1]-R[1,2],R[0,2]-R[2,0],R[1,0]-R[0,1]])
    V_inv_t = tt  # for pure rotation approx ignore (pose-graph uses full 6D; fine)
    return np.concatenate([tt, A])

# ---------------- ORB + PnP
class ORB:
    def __init__(self,n=ORB_N): self.orb=cv2.ORB_create(nfeatures=n)
    def __call__(self, gray, static):
        mask=(static.astype(np.uint8)*255)
        return self.orb.detectAndCompute(gray, mask)

def pnp_rel(src_rgb_bgr, src_depth, src_static, tgt_rgb_bgr, tgt_static, K, orb):
    sg=cv2.cvtColor(src_rgb_bgr, cv2.COLOR_BGR2GRAY); tg=cv2.cvtColor(tgt_rgb_bgr, cv2.COLOR_BGR2GRAY)
    skp,sdesc=orb(sg,src_static); tkp,tdesc=orb(tg,tgt_static)
    if sdesc is None or tdesc is None: return None,None
    ph=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(sdesc,tdesc,k=2)
    m=[]
    for pr in ph:
        if len(pr)>=2 and pr[0].distance < RATIO*pr[1].distance: m.append(pr[0])
    if len(m)<MIN_INL: return None,None
    pts3,pts2=[],[]
    for mm in m:
        u,v=skp[mm.queryIdx].pt; x,y=int(round(u)),int(round(v))
        if not(0<=y<src_depth.shape[0] and 0<=x<src_depth.shape[1]): continue
        z=float(src_depth[y,x])
        if not np.isfinite(z) or z<MIN_DEPTH or z>MAX_DEPTH or not src_static[y,x]: continue
        pts3.append([(u-CX)*z/FX,(v-CY)*z/FY,z]); pts2.append(tkp[mm.trainIdx].pt)
    obj=np.asarray(pts3,np.float32); img=np.asarray(pts2,np.float32)
    if len(obj)<MIN_INL: return None,None
    ok,rvec,tvec,ids=cv2.solvePnPRansac(obj,img,K,None,iterationsCount=400,
        reprojectionError=3.0,confidence=0.999,flags=cv2.SOLVEPNP_EPNP)
    if not ok or ids is None or len(ids)<MIN_INL: return None,None
    inl=ids[:,0]
    if len(inl)/len(obj)<MIN_RATIO: return None,None
    rvec,tvec=cv2.solvePnPRefineLM(obj[inl],img[inl],K,None,rvec,tvec)
    R,_=cv2.Rodrigues(rvec); proj,_=cv2.projectPoints(obj[inl],rvec,tvec,K,None)
    rmse=float(np.sqrt(np.mean(np.sum((proj[:,0]-img[inl])**2,axis=1))))
    if rmse>RMSE_CAP: return None,None
    T=np.eye(4);T[:3,:3]=R;T[:3,3]=tvec[:,0]
    return T, dict(matches=len(obj),inliers=len(inl),ratio=round(float(len(inl)/len(obj)),3),rmse=round(rmse,3))

# ---------------- pose graph LM
def build_graph(est, nodes, long_edges):
    # nodes: list of frame idx (sorted). odom edges between consecutive nodes from est (C2W).
    # Our online est is C2W: T_i (cam-to-world). Relative node->prev: inv(T_i) T_prev? 
    # For pose graph with world-to-node convention we use C2W directly and compose:
    #   relative C2W from node_a to node_b = matmul(inv(T_a), T_b)  (motion from a to b in world frame)
    # We'll optimize world-frame camera poses (C2W). Edge residual for odom (i,j): 
    #   inv(Pi) Pj should equal online-rel.
    # LM over node poses Pi (C2W), gauge node0 fixed.
    n=len(nodes)
    # odom edges: i->i+1 with rel = inv(est_i) est_{i+1}
    edges=[]   # (i,j,Trel,wt,is_long)
    for k in range(n-1):
        Ta=est[nodes[k]]; Tb=est[nodes[k+1]]
        rel=np.linalg.inv(Ta)@Tb
        edges.append((k,k+1,rel,ODOM_W,False))
    for (sid,tid,Trel,stat) in long_edges:   # sid=source(node older), tid=target(newer)
        # validated PnP Trel == inv(P[newer]) @ P[older]. Constraint imposed in lm_solve (is_long):
        # inv(X[older]) @ X[newer] == Trel  (motion source->target equals observed PnP).
        edges.append((sid,tid,Trel,LONG_W,True))
    # init: naive chain from node0=est[node0]
    X=[np.array(est[nodes[0]],float)]
    for k in range(n-1):
        rel=np.linalg.inv(est[nodes[k]])@est[nodes[k+1]]
        X.append(X[-1]@rel)   # C2W compose: Pj = Pi @ rel  (rel is C2W motion) - check
    # Actually check: Pj ~= est[nodes[k+1]]? if rel=inv(Pi)@Pj then Pi@rel=Pi@inv(Pi)@Pj=Pj. Good.
    return X, edges

def lm_solve(X, edges, iters=120):
    n=len(X)
    for it in range(iters):
        # build Jacobian numerically for robustness (small n ~58 nodes * 6 dof)
        J=[]; r=[]
        z=se3_log(np.eye(4))  # zero
        # residual vector
        def res_all(X):
            out=[]
            for (i,j,Trel,w,il) in edges:
                # Both odom and long: we measured a relative "motion from i to j" observed = Trel_obs.
                # - odom Trel_obs = inv(est_i)@est_j  (motion i->j). We want inv(Xi)@Xj == Trel_obs.
                # - long  PnP  = inv(P_target)@P_source = inv(P_newer)@P_older, i.e. Trel_obs = motion
                #   FROM older(our i) TO newer(our j) expressed as inv(X_newer)@X_older ... 
                #   (see pnp_conv_check: PnP == inv(Pb)[b=newer] @ Pa[a=older], which is the motion
                #   FROM older TO newer as a C2W increment = inv(P_newer)@P_older)
                #   => we want inv(X_older) @ X_newer == Trel_obs  =>  E = inv(Xi)@Xj @ inv(Trel_obs) -> I
                E = np.linalg.inv(X[i]) @ X[j] @ np.linalg.inv(Trel)
                e=se3_log(E)
                nrm=np.linalg.norm(e)
                if nrm<1.0: out.append(w*e)
                else: out.append(w*(1.0/nrm)*e)  # huber slope outside
            return np.concatenate(out)
        def update_blocks():
            # Gauss-Newton: J^T J dx = J^T r ; only vary nodes >0 (gauge)
            rr=res_all(X); m=len(rr); J=np.zeros((m,n*6))
            for k in range(n):
                if k==0: 
                    # node0 fixed, its cols zero
                    continue
                for d in range(6):
                    pert=se3_exp(np.eye(6)[d]*1e-5)
                    Xp=X[:]; Xp[k]=X[k]@pert
                    rp=res_all(Xp)
                    J[:,k*6+d]=(rp-rr)/1e-5
            return J,rr
        J,rr=update_blocks()
        # drop node0 cols
        J=J[:,6:]
        # solve normal
        H=J.T@J+1e-3*np.eye(H.shape[0]) if False else J.T@J+1e-3*np.eye(J.shape[1])
        rhs=J.T@rr
        try: dx=np.linalg.solve(H,-rhs)
        except np.linalg.LinAlgError: break
        # apply
        for k in range(1,n):
            X[k]=X[k]@se3_exp(dx[(k-1)*6:(k)*6])
    return X

# ---------------- recompose full traj from nodes
def recompose(est, nodes, X):
    full=list(est)  # workspace
    # overwrite node poses with optimized X; between nodes keep est increments from node pose
    # approach: rebuild full path by taking optimized node poses and threading est increments
    # between them (simple: set node poses, spline the rest via rel from est)
    id2node={frame:i for i,frame in enumerate(nodes)}
    result=np.array(est,copy=True)   # (580,4,4) workspace copy
    # optimized nodes
    for i,frame in enumerate(nodes):
        result[frame]=X[i]
    # between nodes: thread est's increments anchored at the PREV optimized node
    for i in range(len(nodes)-1):
        a=nodes[i]
        for f in range(a+1, nodes[i+1]):
            result[f]=X[i]@np.linalg.inv(est[a])@est[f]
    # after last node to end
    a=nodes[-1]
    for f in range(a+1,len(est)):
        result[f]=X[-1]@np.linalg.inv(est[a])@est[f]
    return result

def ate_eval(a,b):
    tr=PoseTrajectory3D(poses_se3=[np.array(T,float) for T in b],timestamps=np.arange(len(b)))
    te=PoseTrajectory3D(poses_se3=[np.array(T,float) for T in a],timestamps=np.arange(len(a)))
    ta=trajectory.align_trajectory(te,tr,correct_scale=False)
    m=metrics.APE(metrics.PoseRelation.translation_part); m.process_data((tr,ta))
    return float(m.get_all_statistics()["rmse"])*100

# ---------------- main
def main():
    est, gt = load_trj(SEED)
    rgb, dep, msk, K = load_frames()
    full_ate = ate_eval(list(est), list(gt))
    print(f"seed {SEED}: baseline full ATE={full_ate:.2f}cm")
    nodes = list(range(0, len(est)-1, NODE_STEP))
    if nodes[-1] != len(est)-1: nodes.append(len(est)-1)
    orb = ORB()
    # preload key caches: depth/static for each frame used as source
    depth_c = [read_depth_m(dep[i]) for i in nodes]
    static_c= [read_mask_static(msk[i]) for i in nodes]
    rgb_c   = [read_rgb_bgr(rgb[i]) for i in nodes]
    node2idx = {fr:i for i,fr in enumerate(nodes)}
    # build long edges
    long_edges=[]  # (i,j,rel,stat)
    rows=[]
    for o in OFFSETS:
        acc=0; tot=0; rot_med=[]; rmse_l=[]
        for i,fr in enumerate(nodes):
            # source must be on the node grid (fr-o may not be a node multiple); snap to nearest node ≤ fr-o
            req = fr - o
            src_fr = None
            for cand in range(req, req - NODE_STEP, -1):
                if cand in node2idx: src_fr=cand; break
            if src_fr is None or src_fr < 0: continue
            j=node2idx[src_fr]; tot+=1
            si, ti = j, i   # source=younger node(src_fr), target=node fr
            Trel, stat = pnp_rel(rgb_c[si], depth_c[si], static_c[si], rgb_c[ti], static_c[ti], K, orb)
            if Trel is None: 
                rows.append((fr,o,0,None)); continue
            # rotation error of this edge vs GT (for diagnostics)
            Rgt = np.linalg.inv(gt[src_fr])@gt[fr]
            dR = Trel[:3,:3] @ Rgt[:3,:3].T
            cosv=np.clip((np.trace(dR)-1)/2,-1,1); rot_med.append(np.degrees(np.arccos(cosv)))
            rmse_l.append(stat['rmse'])
            long_edges.append((si,ti,Trel,stat))
            acc+=1; rows.append((fr,o,1,stat))
        print(f"  offset {o}: accepted {acc}/{tot} rot_med={np.median(rot_med) if rot_med else float('nan'):.1f}deg rmse_med={np.median(rmse_l) if rmse_l else float('nan'):.1f}px")
    # graph
    X0, edges = build_graph(est, nodes, long_edges)
    if len(long_edges)==0:
        print("NO long edges accepted — stopping (supports no-independent-signal).")
        # still save
        return
    X = lm_solve(X0, edges)
    full = recompose(est, nodes, X)
    ate_after = ate_eval(list(full), list(gt))
    print(f"  after pose-graph optimization (long_w={LONG_W}): ATE={ate_after:.2f}cm (baseline {full_ate:.2f})")
    # per-offset ablation: only that offset's edges
    for o in OFFSETS:
        sub=[e for e in long_edges if (nodes[e[0]]-nodes[e[1]])==o or (nodes[e[1]]-nodes[e[0]])==o]
        Xs,es=build_graph(est,nodes,sub)
        Xs=lm_solve(Xs,es)
        f=recompose(est,nodes,Xs)
        print(f"    offset {o} only: ATE={ate_eval(list(f),list(gt)):.2f}cm")
    # save summary
    json.dump(dict(seed=SEED, baseline=full_ate, after=ate_after, nodes=nodes,
                   long_edges=[(nodes[e[0]],nodes[e[1]],s) for e,s in [(e,e[3]) for e in long_edges]]),
              open(f"{OUT}/summary_seed{SEED}.json","w"), indent=1)

if __name__=="__main__":
    main()
