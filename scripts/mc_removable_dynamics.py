#!/usr/bin/env python3
"""map-compression STEP 1b: correlation between a 'removable' Gaussian signature
(sigmoid opacity < 0.05) and the dynamic vacated region.

WHY THIS EXISTS. The compression narrative must distinguish two things:
(a) if the low-contribution Gaussians cluster in the dynamic vacated region, then
"compaction" is secretly anti-dynamic eviction in disguise (an axis already shown
dead), vs (b) if they are spatially uniform across dynamic and never-dynamic
regions, compaction is an INDEPENDENT axis that can be argued on its own merits.

METHOD (mirrors the stage0 vac_excess disambiguator). Project every gaussian
center at ~20 spread frames of the stored trajectory; count the removable fraction
of projected centers that land ON the union of all frozen dynamic masks vs on a
never-dynamic eroded control. vac_excess = removable-rate(union) - removable-rate(control).
A ~0 or negative excess means no dynamic-region bias -> the removable set is
spatial, not dynamic. (The stage0/forward probes used the same base-rate guard.)

Zero GPU. Writes to stdout.
Usage: python scripts/mc_removable_dynamics.py
"""
import glob
import json
import os

import numpy as np
import yaml
from munch import munchify
from plyfile import PlyData
from scipy import ndimage

from utils.gtmc_mask import frozen_mask_index, load_frozen_mask

SEQS = ["balloon", "mv_no_box", "pt1", "pt2"]
REM_OP_TH = 0.05


def main():
    for seq in SEQS:
        run = f"results/runs/P2/P2-T/{seq}_prune_seed0"
        dirs = glob.glob(run + "/datasets_bonn/*/seed_0/*/")
        d = max(dirs, key=lambda x: os.path.getmtime(x + "/config.yml"))
        cfg = yaml.safe_load(open(d + "/config.yml"))
        cal = cfg["Dataset"]["Calibration"]
        fx, fy, cx, cy = cal["fx"], cal["fy"], cal["cx"], cal["cy"]
        plydata = PlyData.read(d + "/point_cloud/final_after_opt/point_cloud.ply")
        v = plydata["vertex"]
        xyz = np.stack([np.asarray(v["x"]), np.asarray(v["y"]), np.asarray(v["z"])], axis=1)
        op = 1 / (1 + np.exp(-np.asarray(v["opacity"]).reshape(-1)))
        rem_op = op < REM_OP_TH

        trj = json.load(open(d + "/plot/trj_full_final.json"))
        pose_by_id = {int(f): np.asarray(c2w, np.float64) for f, c2w in zip(trj["trj_id"], trj["trj_est"])}
        fids = sorted(pose_by_id.keys())

        subdir = cfg["Results"].get("static_bg_mask_subdir")
        mdir = os.path.join(cfg["Dataset"]["dataset_path"], subdir)
        idx = frozen_mask_index(mdir)
        union = None
        for _s, m in idx.items():
            msk = np.asarray(load_frozen_mask(m), dtype=bool)
            union = msk if union is None else (union | msk)
        control = (~union) & (~ndimage.binary_dilation(union, iterations=4))
        H, W = union.shape
        samp = fids[::max(1, len(fids) // 20)]
        ai, ac = [0, 0], [0, 0]
        for fid in samp:
            c2w = pose_by_id[fid]
            inv = np.linalg.inv(c2w)
            R, t = inv[:3, :3], inv[:3, 3]
            cam = xyz @ R.T + t
            z = cam[:, 2]
            front = z > 0.01
            u = fx * cam[:, 0] / np.maximum(z, 1e-6) + cx
            v = fy * cam[:, 1] / np.maximum(z, 1e-6) + cy
            inside = front & (u >= 0) & (u < W) & (v >= 0) & (v < H)
            ui = np.clip(u[inside].astype(np.int64), 0, W - 1)
            vi = np.clip(v[inside].astype(np.int64), 0, H - 1)
            pu = union[vi, ui]
            pc = control[vi, ui]
            _in = inside.copy()
            _in[inside] = pu
            _ctrl = np.zeros_like(_in)
            _ctrl[inside] = pc
            ai[1] += int(_in.sum())
            ai[0] += int((_in & rem_op).sum())
            ac[1] += int(_ctrl.sum())
            ac[0] += int((_ctrl & rem_op).sum())
        r_in = ai[0] / max(ai[1], 1)
        r_ctrl = ac[0] / max(ac[1], 1)
        excess = r_in - r_ctrl
        print(f"{seq}: N={len(op)} rem_op<{REM_OP_TH}={rem_op.sum():>6d}({rem_op.mean() * 100:5.1f}%)  "
              f"rate_in_union={r_in:.3f} rate_in_ctrl={r_ctrl:.3f}  vac_excess={excess:+.3f}  "
              f"(n_union={ai[1]:,} n_ctrl={ac[1]:,})")


if __name__ == "__main__":
    main()
