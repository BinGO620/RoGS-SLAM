#!/usr/bin/env python3
"""offline (2060): does the multi-frame flow-consensus anomaly separate dynamic from static pixels?

DE-RISK for the "TRC (Temporal Residual Consensus)" gate idea: if per-pixel |frozen_obs_flow -
static_ego_flow| (the reliability signal's core anomaly) is much higher at GTMC-dynamic pixels than at
static pixels, then a mask-free gate on the TEMPORAL-CONSENSUS (not single-frame) signal is SEPARABLE ->
the TRC gate is well-posed. The reliability signal we ran was K=2 (single anomaly) and did NOT clear 15%,
so the open question is whether a K-window trailing median CONSENSUS (the `kframe_consensus` lower-median
persistence, which the literature/TCR name implies) sharpens the separation.

Pure offline on saved runs, zero training. Renders final PLY at saved poses and recomputes per-frame
flow anomalies from the FROZEN RAFT flow (precomputed) + pose + depth.
"""
import sys, glob, cv2, torch
import numpy as np
sys.path.insert(0, "/data/monogs-ours")
from scripts.probe_hole_ghost import load_run, render_frame
from utils.reliability_signal import relative_pose_target_from_source, rigid_flow, kframe_consensus


def per_frame_anomaly(cfg, dataset, gaussians, pose_by_id, fid, prev_id, flow_files, valid_mask):
    img, op, depr = render_frame(dataset, gaussians, cfg, pose_by_id[fid], fid)
    Tcur = pose_by_id[fid]; Tprev = pose_by_id[prev_id]
    R, t = relative_pose_target_from_source(torch.from_numpy(Tcur).float(),
                                            torch.from_numpy(Tprev).float())
    fst, fst_valid = rigid_flow(depr.float(), dataset.fx, dataset.fy, dataset.cx, dataset.cy, R, t)
    fobs = torch.from_numpy(np.load(flow_files[fid]).astype(np.float32)).to(fst.device)
    if fobs.shape != fst.shape:
        return None
    anom = (fobs - fst).norm(dim=-1)  # (H,W) on gpu
    return anom.unsqueeze(0).cpu(), fst_valid.unsqueeze(0).cpu()


def main():
    src = "/data/Datasets/Bonn/rgbd_bonn_balloon"
    run = ("/data/monogs-ours/results/runs/P2/P2-T_3090/balloon_prune_seed0/"
           "datasets_bonn/p2s_combined_prune_balloon/seed_0/2026-08-08-23-07-31")
    cfg, dataset, gaussians, trj = load_run(run, src)
    pose_by_id = {}
    for f, t in zip(trj["trj_id"], trj["trj_est"]):
        pose_by_id[int(f)] = np.asarray(t)
    mask_files = sorted(glob.glob(src + "/dynamic_mask_gtmc/*.png"))
    flow_files = sorted(glob.glob(src + "/flow_raft/*.npy"))
    fids = sorted(pose_by_id.keys())

    # Precompute per-frame anomaly for all frames (GPU-light: one render each). Cache to list.
    def compute_anom(i):
        fid = fids[i]
        if fid >= len(flow_files):
            return None
        return per_frame_anomaly(cfg, dataset, gaussians, pose_by_id,
                                 fid, fids[max(0, i - 1)], flow_files, None)

    print("computing per-frame anomalies...")
    anoms = []
    for i in range(len(fids)):
        anoms.append(compute_anom(i))
    with torch.no_grad():
        torch.cuda.empty_cache()

    for K in (1, 3, 5, 8):
        dyn, stat = [], []
        with torch.no_grad():
            for i in range(K, len(fids), 25):
                a, v = anoms[i]
                if a is None or i < K:
                    continue
                # gather trailing K anomalies (i-K+1 .. i) at same pixel (no warp; drift screen proxy)
                stack = torch.cat([anoms[j][0] for j in range(i - K + 1, i + 1)], dim=0)  # (K,H,W)
                vstack = torch.cat([anoms[j][1] for j in range(i - K + 1, i + 1)], dim=0)  # (K,H,W)
                e, fv = kframe_consensus(stack, vstack)   # (H,W)
                anom = np.nan_to_num(e.numpy(), nan=0.0)  # lower-median consensus
                fid = fids[i]
                if fid >= len(mask_files):
                    continue
                m0 = cv2.imread(mask_files[fid], cv2.IMREAD_GRAYSCALE) > 0
                m0 = m0[: anom.shape[0], : anom.shape[1]]
                if m0.sum() < 50:
                    continue
                dyn.append(anom[m0].mean()); stat.append(anom[~m0].mean())
        dyn, stat = np.array(dyn), np.array(stat)
        if len(dyn) == 0:
            print(f"K={K}: no frames"); continue
        print(f"K={K}: dyn {dyn.mean():.3f}±{dyn.std():.3f}  stat {stat.mean():.3f}±{stat.std():.3f}  "
              f"separability ratio {dyn.mean()/stat.mean():.2f}  (n {len(dyn)})")


if __name__ == "__main__":
    main()
