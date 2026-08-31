#!/usr/bin/env python3
"""P1: does removing DYNAMIC pixels specifically damage pose observability?

Offline, data-level, zero-SLAM-run measurement of the 6x6 pose information matrix

    H(S) = sum_{x in S} [ alpha * J(x)^T G(x) J(x) + (1-alpha) * j_d(x)^T j_d(x) ]

on the pixel set ``S`` that survives a dynamic-pixel removal, versus the SAME mask
translated to a random place in the frame (the null). Everything is evaluated at the
GT pose from ``groundtruth.txt``, so no run, no seed and no ATE enters -- which is the
point: the >=6% ATE noise floor (exp32) cannot touch this measurement.

Criterion, null construction, effect-size gate and the invalidation control are
PRE-REGISTERED in ``results/evidence/p1_observability_preregistration.md`` (committed
before this script produced a single number). This file only computes; the verdict is
``scripts/p1_observability_verdict.py``.

    J(x)  = d u / d xi        utils.reliability_signal.flow_jacobian_se3(depth, K, I, 0)
    G(x)  = sum_c grad I_c grad I_c^T          observed RGB in [0,1], 3 channels
    j_d(x)= a_z - grad D^T J,  a_z = [0,0,1, Yc, -Xc, 0]
    alpha = Training.alpha = 0.95              (MonoGS tracking-loss split)

Usage:
  python scripts/p1_observability_offline.py --sequences all \
      --datasets-root /data/Datasets/Bonn --out results/evidence/p1_observability
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
from utils.gtmc_mask import (  # noqa: E402
    CALIB_BONN,
    DIST_BONN,
    frozen_mask_index,
    load_frozen_mask,
    undistort_depths,
    undistort_images,
)
from utils.reliability_signal import flow_jacobian_se3  # noqa: E402

# Pre-registered sequence set (fixed before any number was produced).
SEQUENCES = [
    "rgbd_bonn_balloon",
    "rgbd_bonn_balloon2",
    "rgbd_bonn_moving_nonobstructing_box",
    "rgbd_bonn_moving_nonobstructing_box2",
    "rgbd_bonn_person_tracking",
    "rgbd_bonn_person_tracking2",
    "rgbd_bonn_moving_obstructing_box",
]

ALPHA = 0.95          # Training.alpha -- MonoGS tracking loss rgb/depth split
MIN_REMOVED = 500     # pre-registered frame admission: removed VALID pixels
MAX_FRAMES = 400      # pre-registered per-sequence cap (uniform subsample)
N_NULL = 32           # pre-registered null draws
COUNT_TOL = 0.15      # pre-registered removed-valid-count match tolerance
MIN_NULL = 8          # pre-registered: fewer accepted draws -> null_infeasible
MAX_SHIFT_TRIES = 200
DEPTH_TOL = 0.25      # depth-matched null (robustness arm, non-gating)


def _stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def per_pixel_terms(depth, rgb, calib, device):
    """(J, G, jd, valid) on the full frame. ``rgb`` uint8 HxWx3, ``depth`` metres."""
    import torch

    fx, fy, cx, cy = (float(calib[k]) for k in ("fx", "fy", "cx", "cy"))
    d = torch.as_tensor(np.ascontiguousarray(depth), dtype=torch.float32, device=device)
    eye = torch.eye(3, dtype=torch.float32, device=device)
    zero = torch.zeros(3, dtype=torch.float32, device=device)
    # R=I, t=0 -> J is the derivative of the CURRENT frame's projection under an
    # infinitesimal camera perturbation, i.e. the direct-method pose Jacobian.
    J, jvalid = flow_jacobian_se3(d, fx, fy, cx, cy, eye, zero)   # (H,W,2,6), (H,W)

    img = torch.as_tensor(
        np.ascontiguousarray(rgb), dtype=torch.float32, device=device
    ) / 255.0                                                     # (H,W,3) in [0,1]
    # central differences (interior only); border pixels are dropped from `valid`
    gx = torch.zeros_like(img)
    gy = torch.zeros_like(img)
    gx[:, 1:-1, :] = 0.5 * (img[:, 2:, :] - img[:, :-2, :])
    gy[1:-1, :, :] = 0.5 * (img[2:, :, :] - img[:-2, :, :])
    # G = sum_c [gx,gy][gx,gy]^T   (H,W,2,2)
    G = torch.stack(
        [
            torch.stack([(gx * gx).sum(-1), (gx * gy).sum(-1)], dim=-1),
            torch.stack([(gx * gy).sum(-1), (gy * gy).sum(-1)], dim=-1),
        ],
        dim=-2,
    )

    dx = torch.zeros_like(d)
    dy = torch.zeros_like(d)
    dx[:, 1:-1] = 0.5 * (d[:, 2:] - d[:, :-2])
    dy[1:-1, :] = 0.5 * (d[2:, :] - d[:-2, :])
    h, w = d.shape
    us = torch.arange(w, device=device, dtype=torch.float32).view(1, w).expand(h, w)
    vs = torch.arange(h, device=device, dtype=torch.float32).view(h, 1).expand(h, w)
    Xc = (us - cx) / fx * d
    Yc = (vs - cy) / fy * d
    z0 = torch.zeros_like(d)
    o1 = torch.ones_like(d)
    a_z = torch.stack([z0, z0, o1, Yc, -Xc, z0], dim=-1)          # (H,W,6)
    grad_d = torch.stack([dx, dy], dim=-1)                        # (H,W,2)
    jd = a_z - torch.einsum("hwa,hwab->hwb", grad_d, J)           # (H,W,6)

    border = torch.zeros_like(jvalid)
    border[1:-1, 1:-1] = True
    valid = (
        jvalid
        & border
        & (d > 0.01)
        & torch.isfinite(J).all(-1).all(-1)
        & torch.isfinite(G).all(-1).all(-1)
        & torch.isfinite(jd).all(-1)
    )
    return J, G, jd, valid


def hessian_of(J, G, jd, sel):
    """H = sum over the boolean/index selection ``sel`` of the 6x6 contributions."""
    import torch

    j = J[sel]                       # (n,2,6)
    g = G[sel]                       # (n,2,2)
    q = jd[sel]                      # (n,6)
    if j.numel() == 0:
        return torch.zeros(6, 6, dtype=torch.float64, device=J.device)
    gj = torch.einsum("nac,ncd->nad", g.double(), j.double())
    h_rgb = torch.einsum("nab,nad->bd", j.double(), gj)
    h_dep = torch.einsum("nb,nd->bd", q.double(), q.double())
    return ALPHA * h_rgb + (1.0 - ALPHA) * h_dep


def spectrum(H):
    """(lambda_min, logdet) of a symmetric 6x6; non-PD -> (nan, nan)."""
    import torch

    Hs = 0.5 * (H + H.transpose(0, 1))
    ev = torch.linalg.eigvalsh(Hs)
    lo = float(ev[0])
    if not np.isfinite(lo) or lo <= 0:
        return lo, float("nan")
    return lo, float(torch.log(ev).sum())


def shifted_masks(mask, valid_np, rng, n_draw, target_count, depth=None, depth_med=None):
    """Draws of the SAME mask translated so its bbox stays fully in frame.

    Shape and area are preserved EXACTLY (no clipping, no wrap-around); only the
    location is randomised. A draw is accepted when the number of removed VALID
    pixels is within ``COUNT_TOL`` of ``target_count`` (and, for the depth-matched
    robustness arm, when the masked median depth is within ``DEPTH_TOL``).
    """
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return []
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h, w = mask.shape
    dy_lo, dy_hi = -int(y0), int(h - 1 - y1)
    dx_lo, dx_hi = -int(x0), int(w - 1 - x1)
    if dy_hi < dy_lo or dx_hi < dx_lo:
        return []
    out, tries = [], 0
    while len(out) < n_draw and tries < MAX_SHIFT_TRIES:
        tries += 1
        dy = int(rng.integers(dy_lo, dy_hi + 1))
        dx = int(rng.integers(dx_lo, dx_hi + 1))
        if dy == 0 and dx == 0:
            continue
        m = np.zeros_like(mask)
        m[ys + dy, xs + dx] = True
        sel = m & valid_np
        c = int(sel.sum())
        if abs(c - target_count) > COUNT_TOL * max(target_count, 1):
            continue
        if depth is not None and depth_med is not None:
            dv = depth[sel]
            dv = dv[dv > 0.01]
            if dv.size == 0:
                continue
            if abs(float(np.median(dv)) - depth_med) > DEPTH_TOL * max(depth_med, 1e-6):
                continue
        out.append((m, c, float(np.mean(m & mask)) if mask.any() else 0.0))
    return out


def process_sequence(seq_dir, out_dir, device, seed=0):
    import torch

    name = os.path.basename(seq_dir.rstrip("/"))
    mask_idx = frozen_mask_index(os.path.join(seq_dir, "dynamic_mask_gtmc"))
    if not mask_idx:
        return {"sequence": name, "status": "no_gtmc"}
    frames = load_tum_associations(seq_dir)
    usable = [f for f in frames if _stem(f["depth_path"]) in mask_idx]
    if len(usable) > MAX_FRAMES:
        idx = np.linspace(0, len(usable) - 1, MAX_FRAMES).astype(int)
        usable = [usable[i] for i in idx]
    calib = CALIB_BONN
    rows, skipped = [], {"small_mask": 0, "null_infeasible": 0, "bad_spectrum": 0}
    for fi, f in enumerate(usable):
        stem = _stem(f["depth_path"])
        # deterministic across processes (python's str hash is salted per-process)
        rng = np.random.default_rng(
            int(hashlib.sha256(f"{name}|{stem}|{seed}".encode()).hexdigest()[:8], 16)
        )
        rgb_raw = np.asarray(Image.open(f["rgb_path"]).convert("RGB"))
        d_raw = np.asarray(Image.open(f["depth_path"])).astype(np.float32)
        d_raw /= float(calib["depth_scale"])
        # SAME pinhole space as dynamic_mask_gtmc/ (built on undistorted depth):
        # RGB linear, depth nearest (never linear across a depth discontinuity).
        rgb = undistort_images([rgb_raw], calib=calib, dist=DIST_BONN)[0]
        depth = undistort_depths([d_raw], calib=calib, dist=DIST_BONN)[0]
        mask = load_frozen_mask(mask_idx[stem])
        if mask.shape != depth.shape:
            continue

        J, G, jd, valid = per_pixel_terms(depth, rgb, calib, device)
        valid_np = valid.detach().cpu().numpy()
        gt_sel = mask & valid_np
        n_removed = int(gt_sel.sum())
        if n_removed < MIN_REMOVED:
            skipped["small_mask"] += 1
            continue
        dv = depth[gt_sel]
        dv = dv[dv > 0.01]
        depth_med = float(np.median(dv)) if dv.size else float("nan")

        draws = shifted_masks(mask, valid_np, rng, N_NULL + 1, n_removed)
        if len(draws) < MIN_NULL + 1:
            skipped["null_infeasible"] += 1
            continue
        ctrl = draws[-1]                    # held out from the null (invalidation arm)
        nulls = draws[:-1]
        dmatch = shifted_masks(
            mask, valid_np, rng, N_NULL, n_removed, depth=depth, depth_med=depth_med
        )

        H_all = hessian_of(J, G, jd, valid)
        lam_all, ld_all = spectrum(H_all)

        def kept(m):
            sel = torch.as_tensor(m, device=device) & valid
            return spectrum(H_all - hessian_of(J, G, jd, sel))

        lam_gt, ld_gt = kept(gt_sel)
        lam_null, ld_null = [], []
        for m, _c, _ov in nulls:
            a, b = kept(m & valid_np)
            lam_null.append(a)
            ld_null.append(b)
        lam_ctrl, ld_ctrl = kept(ctrl[0] & valid_np)
        lam_dm, ld_dm = [], []
        for m, _c, _ov in dmatch:
            a, b = kept(m & valid_np)
            lam_dm.append(a)
            ld_dm.append(b)

        lam_null = np.asarray(lam_null, dtype=np.float64)
        ld_null = np.asarray(ld_null, dtype=np.float64)
        if not np.isfinite(lam_gt) or not np.isfinite(lam_null).all():
            skipped["bad_spectrum"] += 1
            continue
        rows.append(
            {
                "frame": fi,
                "stem": stem,
                "n_valid": int(valid_np.sum()),
                "n_removed": n_removed,
                "removed_frac": n_removed / max(int(valid_np.sum()), 1),
                "depth_med_masked": depth_med,
                "n_null": int(lam_null.size),
                "n_dmatch": int(len(lam_dm)),
                "overlap_med": float(np.median([o for _m, _c, o in nulls])),
                "lam_all": lam_all,
                "logdet_all": ld_all,
                "lam_gt": lam_gt,
                "logdet_gt": ld_gt,
                "lam_null_med": float(np.median(lam_null)),
                "lam_null_q05": float(np.quantile(lam_null, 0.05)),
                "logdet_null_med": float(np.median(ld_null)),
                "logdet_null_q05": float(np.quantile(ld_null, 0.05)),
                "lam_ctrl": lam_ctrl,
                "logdet_ctrl": ld_ctrl,
                "lam_dmatch_med": float(np.median(lam_dm)) if lam_dm else float("nan"),
                "lam_dmatch_q05": (
                    float(np.quantile(lam_dm, 0.05)) if len(lam_dm) >= MIN_NULL else float("nan")
                ),
            }
        )
        if fi % 50 == 0:
            print(
                f"  [{name}] {fi}/{len(usable)} removed={n_removed} "
                f"lam_gt={lam_gt:.4g} lam_null_med={np.median(lam_null):.4g}",
                flush=True,
            )
    os.makedirs(out_dir, exist_ok=True)
    import csv

    path = os.path.join(out_dir, f"{name}.csv")
    if rows:
        with open(path, "w", newline="") as fh:
            wtr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            wtr.writeheader()
            wtr.writerows(rows)
    return {
        "sequence": name,
        "status": "ok" if rows else "empty",
        "n_frames_considered": len(usable),
        "n_rows": len(rows),
        "skipped": skipped,
        "csv": path,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datasets-root", default="/data/Datasets/Bonn")
    ap.add_argument("--sequences", default="all")
    ap.add_argument("--out", default="results/evidence/p1_observability")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    import torch

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    seqs = SEQUENCES if args.sequences == "all" else args.sequences.split(",")
    os.makedirs(args.out, exist_ok=True)
    summary = []
    for s in seqs:
        seq_dir = s if os.path.isdir(s) else os.path.join(args.datasets_root, s)
        if not os.path.isdir(seq_dir):
            summary.append({"sequence": s, "status": "missing"})
            print(f"[skip] {s}: not found")
            continue
        print(f"[run] {s} on {device}", flush=True)
        summary.append(process_sequence(seq_dir, args.out, device, seed=args.seed))
        print(f"[done] {summary[-1]}", flush=True)
    meta = {
        "alpha": ALPHA,
        "n_null": N_NULL,
        "count_tol": COUNT_TOL,
        "min_removed": MIN_REMOVED,
        "max_frames": MAX_FRAMES,
        "min_null": MIN_NULL,
        "depth_tol": DEPTH_TOL,
        "device": device,
        "seed": args.seed,
        "preregistration": "results/evidence/p1_observability_preregistration.md",
        "sequences": summary,
    }
    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
