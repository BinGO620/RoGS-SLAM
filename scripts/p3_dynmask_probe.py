#!/usr/bin/env python3
"""E1' zero-GPU dynamic-mask-exposure gate (idea B).

Hypothesis (codex #5 / Idea B): dynamic-SLAM final maps contain a cohort of low-contribution
Gaussians whose deletability is better explained by DYNAMIC-REGION exposure than by opacity
alone (i.e. transient-object residues). If the op<0.01 tail is strongly enriched in
dynamic-mask exposure and a dynamic-aware delete beats opacity-only at matched size, this is
an independent, non-MGS-SLAM contribution.

This probe is CPU-only (project stored Gaussian centers into stored frames using the stored
trajectory; count dynamic-mask exposure). NO retraining, NO online instrumentation.

Gate (pre-declared): if the op<0.01 cohort is NOT significantly enriched in dynamic-mask
exposure vs a scale/visibility-matched opacity>0.5 control, KILL idea B (it would only be a
spatial re-label of the tail). If it IS enriched, the next step is a 1-run GPU ablatopn.

USAGE: conda run -n monogs-ours python scripts/p3_dynmask_probe.py \
  --run <run_dir> --dataset-path /data/Datasets/Bonn/rgbd_bonn_balloon
"""
import argparse, json, os, sys
from pathlib import Path
import numpy as np
from PIL import Image

# reuse MonoGS dataset loader for calibration + mask association
ROOT = Path("/data/monogs-ours")
sys.path.insert(0, "/data/monogs-ours")
from utils.dataset import load_dataset  # noqa: E402


def _hdr_len(p):
    with open(p, "rb") as f:
        n = 0
        while True:
            l = f.readline(); n += len(l)
            if l.strip() == b"end_header": return n


def read_ply(path):
    props = [] ; n = None
    with open(path, "rb") as f:
        while True:
            l = f.readline().decode().strip()
            if l.startswith("element vertex"): n = int(l.split()[-1])
            elif l.startswith("property"): props.append(l.split()[-1])
            elif l == "end_header": break
    nc = len(props); h = _hdr_len(path)
    with open(path, "rb") as f:
        f.seek(h); raw = f.read(nc * 4 * n)
    a = np.frombuffer(raw, dtype="<f4").reshape(n, nc)
    cols = {k: i for i, k in enumerate(props)}
    xyz = a[:, [cols['x'], cols['y'], cols['z']]]
    opacity = a[:, cols['opacity']]
    scale0 = a[:, cols['scale_0']]
    return xyz.astype(np.float64), opacity.astype(np.float64), scale0.astype(np.float64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="path to run dir containing point_cloud/final_after_opt + plot/trj_full_final.json")
    ap.add_argument("--dataset-path", required=True)
    ap.add_argument("--mask-subdir", default="dynamic_mask_gtmc")
    ap.add_argument("--subsample", type=int, default=6000, help="max gaussians to score per cohort")
    args = ap.parse_args()

    run_dir = Path(args.run)
    ply = run_dir / "point_cloud" / "final_after_opt" / "point_cloud.ply"
    trj_path = run_dir / "plot" / "trj_full_final.json"
    assert ply.is_file(), ply
    assert trj_path.is_file(), trj_path

    # Resolve the source data path. Runs stored 'datasets/bonn/...' relative to the repo root.
    import yaml
    cfg = yaml.safe_load(open(run_dir / "config.yml"))
    dpath_cfg = cfg["Dataset"]["dataset_path"]
    src = Path(args.dataset_path) if Path(args.dataset_path).is_absolute() else (ROOT / dpath_cfg)
    if not src.is_dir():
        print(f"FATAL: source path not found: {src}")
        return 2
    args.dataset_path = str(src)
    # also copy current calibration into cfg for loader reuse
    cfg["Dataset"]["Calibration"] = cfg["Dataset"].get("Calibration", {})

    # trajectory (w2c SE3 per frame index = dataset frame order 0..N-1)
    trj = json.load(open(trj_path))
    poses = np.asarray(trj["trj_est"], dtype=np.float64)   # (N,4,4) w2c

    # dataset provides Camera intrinsics + mask association; mask file per color timestamp
    from utils.dataset import load_dataset  # reuse
    # Load the dataset so frame index -> depth stem is authoritative (masks keyed by depth stem,
    # from frozen_mask_index; NOT by rgb timestamp).
    from utils.gtmc_mask import frozen_mask_index
    from utils.dataset import load_dataset as _ld
    from munch import munchify
    mp2 = munchify(cfg["model_params"]) if "model_params" in cfg else munchify(cfg["Dataset"])
    mp2.sh_degree = cfg["Training"].get("spherical_harmonics", False)
    ds = _ld(mp2, mp2.source_path, cfg)
    # calibrations come from ds (authoritative), not cfg
    fx, fy, cx, cy = ds.fx, ds.fy, ds.cx, ds.cy
    height, width = ds.height, ds.width
    depth_stems = [Path(p).stem for p in ds.depth_paths]
    mask_dir = Path(args.dataset_path) / args.mask_subdir
    index = frozen_mask_index(mask_dir)   # depth-stem -> mask png path
    # per frame-index, its mask path (if the dataset depth stem has a mask)
    frame_mask = [index.get(s) for s in depth_stems]  # None where absent

    xyz, opacity, scale0 = read_ply(ply)
    sig = 1 / (1 + np.exp(-opacity))
    n = len(xyz)
    lo_idx = np.flatnonzero(sig < 0.01)
    hi_idx = np.flatnonzero(sig >= 0.5)     # control: reasonably opaque
    rng = np.random.default_rng(0)
    lo = rng.choice(lo_idx, size=min(len(lo_idx), args.subsample), replace=False)
    hi = rng.choice(hi_idx, size=min(len(hi_idx), args.subsample), replace=False)

    # mask files indexed by depth-file stem (frame index i -> ds.depth_paths[i].stem)
    mask_names = {s: v for s, v in zip(depth_stems, frame_mask)}

    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)

    # For a subsample of frames, project all gaussian centers, check in-mask
    n_frames = min(len(poses), 60)   # score on up to 60 frames (runtime guard)
    frame_step = max(1, len(poses)//n_frames)
    fids = list(range(0, len(poses), frame_step))[:n_frames]
    # only frames that HAVE a frozen mask (skip missing)
    fids = [i for i in fids if (i < len(frame_mask) and frame_mask[i] is not None)][:40]

    def dynamic_exposure(idx):
        """For gaussians idx: fraction of (frame, gaussian) projections falling in dynamic mask."""
        hits = np.zeros(len(idx), dtype=float)
        cnt = np.zeros(len(idx), dtype=float)
        for i in fids:
            mask_path = frame_mask[i]
            m = np.asarray(Image.open(mask_path).convert("L"), dtype=np.float32) / 255.0
            m = m[:height, :width]
            P = poses[i]  # w2c
            cam_pts = (P[:3, :3] @ xyz[idx].T + P[:3, 3:4]).T   # (k,3) in cam
            z = cam_pts[:, 2]
            inside = np.isfinite(cam_pts).all(axis=1) & (z > 0.01)
            if not inside.any():
                continue
            uv = K @ cam_pts[inside].T                       # 3 x k
            u = uv[0] / uv[2]; v = uv[1] / uv[2]
            px = ((u >= 0) & (u < width-1) & (v >= 0) & (v < height-1))
            k_idx = np.flatnonzero(inside)[px]
            uu = u[px].astype(int); vv = v[px].astype(int)
            cnt[k_idx] += 1
            hits[k_idx] += (m[vv, uu] > 0.5)
        good = cnt > 0
        return (hits[good] / cnt[good]).mean() if good.any() else float("nan"), good.sum()

    exp_lo, vis_lo = dynamic_exposure(lo)
    exp_hi, vis_hi = dynamic_exposure(hi)
    print(f"n_frames_scored={len(fids)} (of {len(poses)})")
    print(f"exposure ratio among visible:  op<0.01 cohort = {exp_lo:.3f} (visible {vis_lo}) | op>=0.5 control = {exp_hi:.3f} (visible {vis_hi})")
    if exp_lo != exp_lo or exp_hi != exp_hi:
        print("INSIDE: not enough visible projections -> INCONCLUSIVE")
        return 2
    enrichment = exp_lo / max(exp_hi, 1e-6)
    print(f"dynamic-exposure enrichment (low/high) = {enrichment:.2f}x")
    if enrichment > 1.8:
        print("GATE: ENRICHED (>=1.8x) -> idea B survives to the 1-run GPU ablation")
        return 0
    else:
        print("GATE: NOT ENRICHED (<1.8x) -> idea B is a spatial re-label; KILL direction")
        return 1


if __name__ == "__main__":
    sys.exit(main())
