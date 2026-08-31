#!/usr/bin/env python3
"""Freeze the backward RAFT optical-flow field ``f_obs`` for an RGB-D sequence (method #8).

Precomputes the OBSERVED dense flow ``f_{t->t-1}`` for every frame into a frozen, hashed
artifact (``flow_raft/`` under the sequence dir), the observed-flow half of the
reliability signal ``s`` (``utils/reliability_signal.py``; ``utils/flow_raft.py`` explains
why offline+frozen and why BACKWARD). Frames are taken in the SAME timestamp-association
order the loader tracks in, RGB is undistorted IDENTICALLY to
``utils/dataset.py::MonocularDataset.__getitem__`` (so ``f_obs`` shares the online
``f_static`` pixel space), and each ``f_{t->t-1}`` is written as ``<frame-t-depth-stem>.npy``
(float16, ``(H, W, 2)`` px) -- the SAME stem key as ``dynamic_mask_gtmc/`` so the two
frozen artifacts co-index by frame. Backward (not forward) so the disagreement is
current-frame anchored (a mover's anomaly lands on frame ``t``'s grid without a warp);
frame 0 has no predecessor and no file.

Usage:
  python scripts/build_flow_raft.py \
      --sequence-dir /data/Datasets/Bonn/rgbd_bonn_moving_obstructing_box \
      --variant small --overlays 6 [--max-frames 80] [--no-undistort]
"""

import argparse
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.geometry_metrics import load_tum_associations  # noqa: E402
from utils.gtmc_mask import CALIB_BONN, DIST_BONN, undistort_images  # noqa: E402
from utils.flow_raft import (  # noqa: E402
    PROTOCOL_VERSION,
    compute_flow,
    load_raft_model,
    weights_file_sha256,
)


import glob as _glob  # avoid shadowing at module level


def _stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def _load_replica_associations(dataset_dir, max_frames=0):
    """Auto-detect Replica format (results/frame%06d.jpg + depth%06d.png, no associations.txt).

    Replica is pinhole-rectified (distorted=False in config), so no undistortion needed.
    traj.txt = one 4x4 C2W matrix per line, 16 floats row-major.
    """
    results_dir = os.path.join(dataset_dir, "results")
    depth_files = sorted(_glob.glob(os.path.join(results_dir, "depth*.png")))
    if not depth_files:
        return None
    frames = []
    for dp in depth_files:
        stem = os.path.splitext(os.path.basename(dp))[0]
        rgb_path = os.path.join(results_dir, f"frame{stem[5:]}.jpg")
        if not os.path.isfile(rgb_path):
            rgb_path = os.path.join(results_dir, f"{stem.replace('depth','frame')}.png")
        if not os.path.isfile(rgb_path):
            raise FileNotFoundError(f"No matching RGB for {dp}")
        frames.append({"rgb_path": rgb_path, "depth_path": dp})
    if max_frames > 0:
        frames = frames[:max_frames]
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sequence-dir", required=True)
    ap.add_argument("--out-subdir", default="flow_raft")
    ap.add_argument(
        "--config",
        default=None,
        help="dataset config for Calibration (undistort ANY dataset in the loader's "
        "pinhole space); omit -> Bonn default (back-compat, byte-identical)",
    )
    ap.add_argument("--variant", default="small", choices=["small", "large"])
    ap.add_argument("--iters", type=int, default=12, help="RAFT refinement iterations")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-frames", type=int, default=0, help="0 = all associated frames")
    ap.add_argument(
        "--no-undistort",
        action="store_true",
        help="skip undistortion (only for already-pinhole datasets)",
    )
    ap.add_argument("--overlays", type=int, default=0, help="save N flow-magnitude PNGs")
    args = ap.parse_args()

    import torch

    # Auto-detect: TUM (associations.txt) or Replica (results/ dir with depth*.png)
    assoc_path = os.path.join(args.sequence_dir, "associations.txt")
    results_dir = os.path.join(args.sequence_dir, "results")
    if os.path.isfile(assoc_path):
        frames = load_tum_associations(args.sequence_dir)
        dataset_type = "tum"
    elif os.path.isdir(results_dir):
        replica_frames = _load_replica_associations(args.sequence_dir)
        if replica_frames:
            frames = replica_frames
            dataset_type = "replica"
        else:
            raise SystemExit(f"results/ exists but no depth*.png in {results_dir}")
    else:
        raise SystemExit(f"Cannot detect dataset format in {args.sequence_dir}")

    if dataset_type == "tum" and args.max_frames > 0:
        frames = frames[: args.max_frames]
    n = len(frames)
    if n < 2:
        raise SystemExit(f"need >=2 associated frames, got {n}")

    # Load raw RGB (association order) + undistort into the loader's pinhole space.
    # Calibration is config-driven (any dataset -> matches MonocularDataset's
    # initUndistortRectifyMap(K, [k1,k2,p1,p2,k3], I, K) exactly) or the Bonn default.
    if args.config:
        from utils.config_utils import load_config  # noqa: PLC0415

        c = load_config(args.config)["Dataset"]["Calibration"]
        calib = {k: float(c[k]) for k in ("fx", "fy", "cx", "cy")}
        calib.update(width=int(c["width"]), height=int(c["height"]))
        dist = np.array(
            [c["k1"], c["k2"], c["p1"], c["p2"], c["k3"]], dtype=np.float64
        )
        distorted = bool(c.get("distorted", True))
    else:
        calib, dist, distorted = CALIB_BONN, DIST_BONN, True

    rgb_raw = [np.asarray(Image.open(f["rgb_path"]).convert("RGB")) for f in frames]
    stems = [_stem(f["depth_path"]) for f in frames]  # same key as dynamic_mask_gtmc
    do_undistort = distorted and not args.no_undistort
    if do_undistort:
        rgb = undistort_images(rgb_raw, calib=calib, dist=dist)  # cv2 INTER_LINEAR
    else:
        rgb = rgb_raw
    H, W = rgb[0].shape[:2]
    if H % 8 or W % 8:
        raise SystemExit(f"RAFT needs H,W divisible by 8; got {H}x{W}")
    print(f"loaded {n} frames ({W}x{H}) from {args.sequence_dir}"
          f" (no undistort)" if not do_undistort else f" (undistorted)"
          f" [format={dataset_type}]")

    def to_u8_chw(a):
        return torch.from_numpy(np.ascontiguousarray(a)).permute(2, 0, 1).to(torch.uint8)

    model, transforms, wmeta = load_raft_model(args.variant, args.device)
    torch.cuda.reset_peak_memory_stats() if args.device.startswith("cuda") else None

    out_dir = os.path.join(args.sequence_dir, args.out_subdir)
    os.makedirs(out_dir, exist_ok=True)

    hasher = hashlib.sha256()  # incremental (matches flow_raft.flow_sha256 byte order)
    mags = []
    overlay_at = set(
        int(i) for i in np.linspace(1, n - 1, min(args.overlays, n - 1), dtype=int)
    ) if args.overlays > 0 else set()
    ov_dir = os.path.join(out_dir, "_overlay")
    if overlay_at:
        os.makedirs(ov_dir, exist_ok=True)

    for t in range(1, n):  # backward flow f_{t->t-1}; frame 0 has no predecessor
        flow = compute_flow(
            model, transforms, to_u8_chw(rgb[t]), to_u8_chw(rgb[t - 1]),
            device=args.device, iters=args.iters,
        )  # (H, W, 2) float32 px, current-frame (t) anchored
        f16 = np.asarray(flow, dtype=np.float16)
        np.save(os.path.join(out_dir, f"{stems[t]}.npy"), f16, allow_pickle=False)
        hasher.update(np.ascontiguousarray(f16).tobytes())
        mag = np.sqrt((flow[..., 0] ** 2 + flow[..., 1] ** 2))
        mags.append((float(np.median(mag)), float(mag.mean()), float(mag.max())))
        if t in overlay_at:
            m = mag / max(mag.max(), 1e-6)
            Image.fromarray((m * 255).astype(np.uint8), mode="L").save(
                os.path.join(ov_dir, f"{stems[t]}.png")
            )
        if t % 50 == 1:
            print(f"  flow {t:4d}/{n - 1}  med|f|={mags[-1][0]:.2f}px max={mags[-1][2]:.1f}px")

    mags = np.asarray(mags)  # (n-1, 3): median, mean, max per pair
    peak_gb = (
        float(torch.cuda.max_memory_allocated() / 1e9)
        if args.device.startswith("cuda") else 0.0
    )
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "sequence_dir": os.path.abspath(args.sequence_dir),
        "n_frames": n,
        "n_pairs": n - 1,
        "direction": "backward (f_{t->t-1})",
        "key": "frame depth-file stem (later frame; co-indexes with dynamic_mask_gtmc)",
        "stored_dtype": "float16",
        "undistorted": (not args.no_undistort),
        "calib": CALIB_BONN if not args.no_undistort else None,
        "raft": {
            "variant": wmeta["variant"],
            "weights_url": wmeta["weights_url"],
            "weights_sha256": weights_file_sha256(wmeta["weights_url"]),
            "iters": args.iters,
        },
        "sha256": hasher.hexdigest(),
        "flow_magnitude_px": {
            "median_of_median": float(np.median(mags[:, 0])),
            "mean_of_mean": float(mags[:, 1].mean()),
            "max": float(mags[:, 2].max()),
        },
        "peak_vram_gb": peak_gb,
        "frame_stems": stems,  # association order; frame 0 has no flow file
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    print(
        f"wrote {n - 1} backward-flow fields -> {out_dir}\n"
        f"  flow |f| px: median-of-median={np.median(mags[:, 0]):.2f} "
        f"mean={mags[:, 1].mean():.2f} max={mags[:, 2].max():.1f}\n"
        f"  peak VRAM={peak_gb:.3f} GB  sha256={manifest['sha256'][:16]}...  "
        f"weights_sha={manifest['raft']['weights_sha256'][:12]}..."
    )


if __name__ == "__main__":
    main()
