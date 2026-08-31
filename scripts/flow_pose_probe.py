#!/usr/bin/env python3
"""B-path flow-coarse-pose sanity probe (2060 offline, NO core change).

Question: can the saved RAFT BACKWARD flow on pt1 estimate inter-frame coarse pose well
enough to beat the rejected const_vel random-walk? If the flow-driven pose is close to GT
(and far better than the previous-frame copy), B is worth writing into coarse_pose.py.

We track per-frame whether the pose is a REAL flow-driven estimate or a GT placeholder so
the ATE isn't artificially good from GT fallback.
"""
import numpy as np, cv2, os, glob

SEQ = '/data/Datasets/Bonn/rgbd_bonn_person_tracking'
depth_dir = os.path.join(SEQ, 'depth')
flow_dir = os.path.join(SEQ, 'flow_raft')
FX, FY, CX, CY = 542.822841, 542.576870, 315.593520, 237.756098
SCALE = 5000.0

POSES = {}
for line in open(os.path.join(SEQ, 'groundtruth.txt')):
    s = line.strip()
    if s.startswith('#') or not s:
        continue
    p = s.split()
    ts = float(p[0])
    POSES[ts] = np.array(list(map(float, p[1:4])))

_depth_cache = {}
def load_depth(ts):
    if ts in _depth_cache:
        return _depth_cache[ts]
    key = f'{ts:.6f}'
    cands = glob.glob(os.path.join(depth_dir, '.'))
    # match by nearest timestamp (files use original repr, may be 5 dp)
    allf = glob.glob(os.path.join(depth_dir, '*.png'))
    if not allf:
        return None
    tgt = min(allf, key=lambda x: abs(float(os.path.basename(x).split('.')[0]) - ts))
    cands = [tgt]
    d = cv2.imread(cands[0], cv2.IMREAD_UNCHANGED)
    if d is None:
        return None
    d = d.astype(np.float64) / SCALE
    _depth_cache[ts] = d
    return d

timestamps = []
for f in sorted(os.listdir(flow_dir)):
    if not f.endswith('.npy'):
        continue
    try:
        timestamps.append(float('.'.join(f.split('.')[:2])))
    except ValueError:
        continue
timestamps.sort()


def umeyama(A, B):  # R*a + t = b (columns)
    ma = A.mean(1, keepdims=True); mb = B.mean(1, keepdims=True)
    A0 = A - ma; B0 = B - mb
    H = A0 @ B0.T
    U, _, Vt = np.linalg.svd(H)
    dd = np.sign(np.linalg.det(Vt.T @ U.T))
    S = np.diag([1, 1, dd])
    R = Vt.T @ S @ U.T
    t = mb - R @ ma
    return R, t


est = []            # pose center (real estimate or placeholder)
real_mask = []      # True if real flow estimate
prev_Rwc = None
prev_center = None
prev_depth = None

for i, ts in enumerate(timestamps):
    gt_key = min(POSES, key=lambda x: abs(x - ts))
    gc = POSES[gt_key]
    d = load_depth(ts)
    if d is None or prev_Rwc is None:
        est.append(gc); real_mask.append(False)
        if prev_Rwc is None:
            prev_Rwc = np.eye(3); prev_center = gc; prev_depth = d
        else:
            pass
        continue
    flo_path = os.path.join(flow_dir, f'{ts:.6f}.npy')
    # flow filenames use the original timestamp repr (may be 5 dp), not zero-padded 6 dp
    if not os.path.exists(flo_path):
        cand = glob.glob(os.path.join(flow_dir, f'*{ts:.5f}.npy'))
        flo_path = cand[0] if cand else ''
    if not flo_path or not os.path.exists(flo_path):
        est.append(gc); real_mask.append(False); prev_depth = d; continue
    flo = np.load(flo_path).astype(np.float32)
    H, W = d.shape
    ys, xs = np.mgrid[4:H:4, 4:W:4]
    zc = d[ys.ravel(), xs.ravel()]
    m = zc > 0.05
    ux = (xs.ravel()[m] - CX) / FX; uy = (ys.ravel()[m] - CY) / FY
    Pc = np.stack([ux, uy, np.ones_like(ux)], axis=1) * zc[m][:, None]
    u = flo[ys.ravel(), xs.ravel(), 0][m]; v = flo[ys.ravel(), xs.ravel(), 1][m]
    px = (xs.ravel()[m] + u).clip(0, W - 1).astype(int)
    py = (ys.ravel()[m] + v).clip(0, H - 1).astype(int)
    zp = prev_depth[py, px]
    mm = zp > 0.05
    pxc = (px[mm] - CX) / FX; pyc = (py[mm] - CY) / FY
    Pp = np.stack([pxc, pyc, np.ones_like(pxc)], axis=1) * zp[mm][:, None]
    Pc2 = Pc[mm]
    if len(Pc2) < 50:
        est.append(gc); real_mask.append(False); prev_depth = d; continue
    best_inl = 0; best_R = best_t = None
    rng = np.random.RandomState(i)
    for _ in range(100):
        sel = rng.choice(len(Pc2), 3, replace=False)
        Rm, tm = umeyama(Pp[sel].T, Pc2[sel].T)
        resid = np.linalg.norm(Rm @ Pp.T + tm[:, None] - Pc2.T, axis=0)
        ninl = int(np.sum(resid < 0.05))
        if ninl > best_inl:
            best_inl = ninl; best_R = Rm; best_t = tm
    if best_R is None:
        est.append(gc); real_mask.append(False); prev_depth = d; continue
    Rrel, trel = best_R, best_t
    R_wt = prev_Rwc @ Rrel.T
    t_wt = (prev_center - R_wt @ trel).ravel()  # (3,)
    Rrel, trel = best_R, best_t
    R_wt = prev_Rwc @ Rrel.T
    t_wt = (prev_center - R_wt @ trel).ravel()  # (3,)
    center_t = t_wt
    est.append(center_t); real_mask.append(True)
    prev_Rwc = R_wt; prev_center = center_t; prev_depth = d

est_arr = np.array(est)
gt_arr = np.array([POSES[min(POSES, key=lambda x: abs(x - ts2))] for ts2 in timestamps])
real_arr = np.array(real_mask)

# restrict to real-estimated frames for an honest ATE
idx = np.where(real_arr)[0]
print(f'frames total={len(est)} real_flow_estimates={len(idx)} ({100*len(idx)/len(est):.1f}%)')

# ATE over ALL frames (incl placeholders) and over REAL frames
def ate(e, g):
    def align(src, dst):
        ma = src.mean(0); md = dst.mean(0)
        s0 = src - ma; d0 = dst - md
        H = s0.T @ d0; U, _, Vt = np.linalg.svd(H)
        dd = np.sign(np.linalg.det(Vt.T @ U.T)); S = np.diag([1, 1, dd])
        Rm = Vt.T @ S @ U.T; t = md - Rm @ ma
        return src @ Rm.T + t
    a = align(e, g)
    return np.sqrt(np.mean(np.sum((a - dst) ** 2, axis=1))) * 100  # cm

if len(idx) > 5:
    real_ate = ate(est_arr[idx], gt_arr[idx])
    print(f'REAL flow-driven pose ATE (aligned, cm): {real_ate:.2f} over {len(idx)} frames')
# full (mostly placeholder) ATE for reference
full_ate = ate(est_arr, gt_arr)
print(f'ALL-frames ATE (incl GT placeholders, cm): {full_ate:.2f}')

# How much does per-frame flow estimate drift vs GT pose centers (raw, unaligned)?
raw = np.sqrt(np.mean(np.sum((est_arr[idx] - gt_arr[idx]) ** 2, axis=1))) * 100
print(f'REAL raw drift vs GT (unaligned, cm): {raw:.2f}')

# Baselines for comparison:
# const_vel random-walk would drift; measure average per-frame GT motion as a floor
per_frame = np.linalg.norm(np.diff(gt_arr if False else gt_arr[idx], axis=0), axis=1)
print(f'mean per-frame GT motion (cm): {per_frame.mean()*100:.2f}  (flow estimate should track this)')
