#!/usr/bin/env python3
"""offline (2060): on pt1 (weak) vs pt2 (strong) person seqs, does the flow-anomaly signal
|f_obs - f_rigid| -- the SAME anomaly the reliability signal consumes -- separate dynamic from
static pixels?

MOTIVATION: our 6-seq maskoff plus the scene bracket found BOTH pt1 and pt2 have near-identical
scene macro (camera motion / dyn-area / mover count / depth) AND near-identical RAW |flow| dyn/bg
ratio (~0.76-0.79, i.e. weak). Yet pt1 mask-free splits 24-41cm (3-seed, non-convergent) while
pt2 is a stable 9cm. The question this probe answers:

  pt1_maskfree_fail = (A) the raw flow anomaly is genuinely weak/unseparable on pt1, vs
                      (B) the anomaly IS separable (like balloon's 1.70) but the reliability
                          K=2 aggregation / MAP admission drops it.

If (A) -> pt1 flow signal is intrinsically weak; mask-free is near-ceilinged there -> limitation.
If (B) -> there is headroom: a better aggregation gate could rescue pt1 -> actionable iteration.

Pure offline. Renders final PLY at saved poses, recomputes per-frame anomaly (fobs - rigid-flow)
and contrasts GTMC-dynamic vs static pixels. Reuses machinery from probe_flow_separability.py.
"""
import sys, glob, os, torch
import numpy as np
sys.path.insert(0, "/data/monogs-ours")
from scripts.probe_hole_ghost import load_run, render_frame
from utils.reliability_signal import relative_pose_target_from_source, rigid_flow

SEQ_CFG = {
    # seq: (cfg-path, src-data-root, run-root)
    "pt1": ("configs/rgbd/bonn/person_tracking.yaml",
            "/data/Datasets/Bonn/rgbd_bonn_person_tracking",
            "/data/monogs-ours/results/runs/P2/P2-T_3090/pt1_prune_seed0/"),
    "pt2": ("configs/rgbd/bonn/person_tracking2.yaml",
            "/data/Datasets/Bonn/rgbd_bonn_person_tracking2",
            "/data/monogs-ours/results/runs/P2/P2-T_3090/pt2_prune_seed0/"),
}

def per_frame_anomaly(cfg, dataset, gaussians, pose_by_id, fid, prev_id, flow_files, valid_mask):
    img, op, depr = render_frame(dataset, gaussians, cfg, pose_by_id[fid], fid)
    Tcur = pose_by_id[fid]; Tprev = pose_by_id[prev_id]
    R, t = relative_pose_target_from_source(torch.from_numpy(Tcur).float(),
                                            torch.from_numpy(Tprev).float())
    fst, fst_valid = rigid_flow(depr.float(), dataset.fx, dataset.fy, dataset.cx, dataset.cy, R, t)
    fobs = torch.from_numpy(np.load(flow_files[fid]).astype(np.float32)).to(fst.device)
    if fobs.shape != fst.shape:
        return None
    anom = (fobs - fst).norm(dim=-1)
    return anom.unsqueeze(0).cpu(), fst_valid.unsqueeze(0).cpu()

def analyse(seq):
    cfg_path, src, run_root = SEQ_CFG[seq]
    from pathlib import Path
    # glob to the exact seed_0 timestamp subdir that contains config.yml/point_cloud/plot
    cands = sorted(Path(run_root).glob("**/seed_0/*/config.yml"))
    if not cands:
        print(f"[{seq}] cannot find run timestamp subdir under {run_root}")
        return
    sub = cands[0].parent
    cfg, dataset, gaussians, trj = load_run(str(sub), src)
    pose_by_id = {}
    for f, t in zip(trj["trj_id"], trj["trj_est"]):
        pose_by_id[int(f)] = np.asarray(t)
    # ground-truth dynamic masks (GTMC), if present
    mask_files = sorted(glob.glob(src + "/seg_mask/*.png"))
    flow_files = sorted(glob.glob(src + "/flow_raft/*.npy"))
    fids = sorted(pose_by_id.keys())
    if not mask_files:
        print(f"[{seq}] NO seg_mask, cannot separate -> skip")
        return

    # Build id->mask (fid is a depth/rgb timestamp that should match mask ts within tolerance)
    id_to_mask = {}
    for mf in mask_files:
        ts = os.path.basename(mf).replace(".png", "")
        id_to_mask.setdefault(float(ts), mf)
    mask_key = sorted(id_to_mask.keys())

    # iterate a subset (e.g. every 30th) frame, render anomaly, then compare dyn vs static median
    anom_dyn = []; anom_sta = []
    n = 0
    for i in range(1, len(fids), 30):
        fid = fids[i]; prev = fids[max(0, i - 1)]
        if fid >= len(flow_files):
            continue
        out = per_frame_anomaly(cfg, dataset, gaussians, pose_by_id, fid, prev, flow_files, None)
        if out is None:
            continue
        anom_map, fst_valid = out
        anom_map = anom_map.squeeze(0).numpy()
        fst_valid = fst_valid.squeeze(0).numpy()
        # ground-truth dynamic mask for this fid (nearest ts)
        near_ts = min(id_to_mask, key=lambda k: abs(k - fid))
        m = np.array(__import__("PIL.Image").Image.open(id_to_mask[near_ts]).convert("L")) > 0
        if m.shape != anom_map.shape:
            continue
        dyn = anom_map[m & fst_valid]
        sta = anom_map[(~m) & fst_valid]
        if dyn.size and sta.size:
            anom_dyn.append(np.median(dyn))
            anom_sta.append(np.median(sta))
        n += 1
    if anom_dyn:
        ratio = float(np.mean(anom_dyn) / np.mean(anom_sta))
        print(f"[{seq}] anomaly-sep (|flow-rigid|) dyn={np.mean(anom_dyn):.2f} static={np.mean(anom_sta):.2f} "
              f"ratio={ratio:.3f}  (frames={n})")
    else:
        print(f"[{seq}] no valid frames sampled")
    del gaussians, dataset
    torch.cuda.empty_cache()

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("seq", choices=["pt1", "pt2", "both"])
    a = ap.parse_args()
    if a.seq == "both":
        analyse("pt1"); analyse("pt2")
    else:
        analyse(a.seq)
