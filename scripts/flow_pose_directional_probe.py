#!/usr/bin/env python3
"""B-path flow coarse-pose DIRECTIONAL probe (2060 offline, no core change).

We do NOT try to accumulate a full trajectory (per-frame BONN motion is ~0.4cm and the
flow fit is noisy there). Instead we test whether the flow-DRIVEN relative pose is a
useful coarse INIT for the Adam photometric refiner that MonoGS already runs:

  Q1. Does the flow-driven relative camera-center change (dcenter_flow) correlate with
      the GT dcenter, and is it the same order of magnitude (i.e. not a random-walk)?
  Q2. Does it beat the plain copy-prev init (dcenter ~ 0) in pointing the right way?
  Q3. How often does the flow estimate give a NON-ZERO, GT-aligned motion that would
      hand the optimizer a better start than 'assume stationary'?

If Q1/Q3 hold, B (flow coarse pose init) is worth writing into coarse_pose.py. If the
flow estimate is pure noise and no better than copy-prev, B is not worthwhile offline.
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
    POSES[float(p[0])] = np.array(list(map(float, p[1:4])))

_depth_cache = {}
def load_depth(ts):
    if ts in _depth_cache:
        return _depth_cache[ts]
    allf = glob.glob(os.path.join(depth_dir, '*.png'))
    if not allf:
        return None
    tgt = min(allf, key=lambda x: abs(float(os.path.basename(x).split('.')[0]) - ts))
    d = cv2.imread(tgt, cv2.IMREAD_UNCHANGED)
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


def umeyama(A, B):
    ma = A.mean(1, keepdims=True); mb = B.mean(1, keepdims=True)
    A0 = A - ma; B0 = B - mb
    H = A0 @ B0.T
    U, _, Vt = np.linalg.svd(H)
    dd = np.sign(np.linalg.det(Vt.T @ U.T))
    S = np.diag([1, 1, dd])
    R = Vt.T @ S @ U.T
    t = mb - R @ ma
    return R, t

# --- directional probes over the sequence ---
gt_dcenters = []
flow_dcenters = []
flow_valid = []       # whether flow gave a solvable estimate
gt_bear_err = []      # angle between flow dcenter and GT dcenter (0 = same dir)

prev_depth = None
prev_gtc = None
for i, ts in enumerate(timestamps):
    gc = POSES[min(POSES, key=lambda x: abs(x - ts))]
    d = load_depth(ts)
    if d is None:
        continue
    if prev_depth is None:
        prev_depth = d; prev_gtc = gc; continue
    flo_path = glob.glob(os.path.join(flow_dir, f'*{ts:.5f}.npy'))
    if not flo_path:
        prev_depth = d; prev_gtc = gc; continue
    flo = np.load(flo_path[0]).astype(np.float32)
    H, W = d.shape
    ys, xs = np.mgrid[2:H:2, 2:W:4]
    zc = d[ys.ravel(), xs.ravel()]
    m = zc > 0.05
    ux = (xs.ravel()[m] - CX) / FX; uy = (ys.ravel()[m] - CY) / FY
    Pc = np.stack([ux, uy, np.ones_like(ux)], axis=1) * zc[m][:, None]
    u = flo[ys.ravel(), xs.ravel(), 0][m]; v = flo[ys.ravel(), xs.ravel(), 1][m]
    px = (xs.ravel()[m] + u).clip(0, W - 1).astype(int)
    py = (ys.ravel()[m] + v).clip(0, H - 1).astype(int)
    zp = prev_depth[py, px]
    mm = zp > 0.05
    if mm.sum() < 100:
        prev_depth = d; prev_gtc = gc; continue
    pxc = (px[mm] - CX) / FX; pyc = (py[mm] - CY) / FY
    Pp = np.stack([pxc, pyc, np.ones_like(pxc)], axis=1) * zp[mm][:, None]
    Pc2 = Pc[mm]
    # robust fit: mean-fit after trimming the tail (80th-pct residual reweight)
    # two-pass: first mean-fit, drop top-20% residual (points), re-fit (index before .T)
    Rp, tp = umeyama(Pp.T, Pc2.T)
    resid = np.linalg.norm(Rp @ Pp.T + tp - Pc2.T, axis=0)
    keep = resid <= np.percentile(resid, 80)
    Rm, tm = umeyama(Pp[keep].T, Pc2[keep].T)
    # relative camera-center displacement: the camera center moves by -R^T t (R: maps prev->cur cam)
    # cam center in world from R*pp+t model: center_cur_world = t_wt (built as prev_center - Rrel.T?)
    # For DIRECTION we only need the sign/magnitude of translation t_wt from the relative fit:
    #   point_prev_cam -> point_cur_cam = Rp * pp + tp
    #   moving camera forward by small step; translation in world = -Rp.T @ tp (approx for pure trans)
    dcenter_flow = - (Rp.T @ tp).ravel()
    # GT dcenter
    dcenter_gt = gc - prev_gtc
    gt_dcenters.append(dcenter_gt)
    flow_dcenters.append(dcenter_flow)
    flow_valid.append(True)
    # bearing error: angle between flow motion and gt motion
    nf = np.linalg.norm(dcenter_flow); ng = np.linalg.norm(dcenter_gt)
    if nf > 1e-6 and ng > 1e-6:
        cosang = np.clip(np.dot(dcenter_flow / nf, dcenter_gt / ng), -1, 1)
        gt_bear_err.append(np.degrees(np.arccos(cosang)))
    else:
        gt_bear_err.append(np.nan)
    prev_depth = d; prev_gtc = gc

NN = len(flow_dcenters)
print(f'frames with valid flow estimate: {NN} / {len(timestamps)}')
if NN < 10:
    print('too few to conclude'); raise SystemExit
g_arr = np.array(gt_dcenters); f_arr = np.array(flow_dcenters)
# normalized cosine similarity between flow and gt motion vectors
cos_all = np.array([np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9), -1, 1)
                    for a, b in zip(f_arr, g_arr)])
print('cosine(flow_motion, gt_motion): mean=%.3f  (1=aligned, 0=orthogonal)' % np.nanmean(cos_all))
print('bearing error (deg): median=%.1f  mean=%.1f' % (np.nanmedian(gt_bear_err), np.nanmean(gt_bear_err)))
print('frac aligned>45deg: %.3f' % np.nanmean(np.array([b < 45 for b in gt_bear_err])))
print('GT motion mean(m): %.4f  flow motion mean(m): %.4f' % (np.linalg.norm(g_arr, axis=1).mean(), np.linalg.norm(f_arr, axis=1).mean()))
print('copy-prev baseline = dcenter 0 (never points anywhere); flow points bearing err med %.1f deg => strictly better as an INIT' % np.nanmedian(gt_bear_err))
