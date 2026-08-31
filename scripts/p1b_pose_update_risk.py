#!/usr/bin/env python3
"""P1b: what does removing dynamic pixels do to the POSE UPDATE's bias and variance?

P1 measured ``lambda_min`` of ``H = sum w J^T J`` and found the dynamic region carries
disproportionate NOMINAL LEVERAGE. Leverage is not usefulness: a dynamic pixel can have
large curvature AND a systematically wrong gradient direction, which is an argument for
removing it, not for keeping it. So this script changes the estimand to the thing that
actually matters -- the pose error a Gauss-Newton step injects, in millimetres.

At the GT relative pose, backward pair (t -> t-1):

    r_c(x) = I^{t-1}_c(pi(T p(x))) - I^t_c(x)     (zero for a static, well-measured pixel)
    A_c(x) = grad I^{t-1}_c(warped)^T  J(x)        J = flow_jacobian_se3(depth_t, K, R, t)
    delta  = -H(w)^-1 g(w),  g = sum_x w sum_c A_c^T r_c,  H = sum_x w sum_c A_c^T A_c

``delta`` IS the bias: a perfect pixel policy returns 0 at the true pose. Reported in mm
and mrad, with the sandwich covariance ``sigma^2 H^-1 (sum w^2 A^T A) H^-1``.

Five arms: all / robust (Cauchy IRLS, knows nothing about dynamics -- the baseline we
must beat) / oracle (GT-MC removed) / shift (same mask, random place -- the invalidation
control) / mrcs (our own segmentation-free weight, flow-only variant).

Gates, arms and the apparatus check are PRE-REGISTERED in
``results/evidence/p1b_pose_risk_preregistration.md`` (committed first). This file
computes and applies that rule; it introduces no threshold of its own.

Usage:
  python scripts/p1b_pose_update_risk.py --sequences all --out results/evidence/p1b_pose_risk
  python scripts/p1b_pose_update_risk.py --verdict results/evidence/p1b_pose_risk
"""

import argparse
import csv
import glob
import hashlib
import importlib.util
import json
import os
import sys

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

_SPEC = importlib.util.spec_from_file_location(
    "p1_observability_offline", os.path.join(_HERE, "p1_observability_offline.py")
)
p1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(p1)

from utils.geometry_metrics import load_tum_associations  # noqa: E402
from utils.gtmc_mask import (  # noqa: E402
    CALIB_BONN, DIST_BONN, frozen_mask_index, load_frozen_mask,
    undistort_depths, undistort_images,
)
from utils.reliability_signal import (  # noqa: E402
    _MAD_CONST, cauchy_tracking_weight, flow_anomaly, flow_jacobian_se3,
    relative_pose_target_from_source, rigid_flow,
)

DYN_SEQUENCES = list(p1.SEQUENCES)
STATIC_CONTROL = "rgbd_bonn_static_close_far"      # no independent motion (neg. control)
N_SHIFT = 8            # shift-control draws per frame; the median |delta| is reported
MIN_VALID = 5000
COND_MAX = 1e10
IRLS_ITERS = 4


def _sample(img_chw, grid):
    import torch.nn.functional as F
    return F.grid_sample(img_chw[None], grid, mode="bilinear",
                         padding_mode="border", align_corners=True)[0]


def _grads(img_chw):
    import torch
    gx = torch.zeros_like(img_chw)
    gy = torch.zeros_like(img_chw)
    gx[:, :, 1:-1] = 0.5 * (img_chw[:, :, 2:] - img_chw[:, :, :-2])
    gy[:, 1:-1, :] = 0.5 * (img_chw[:, 2:, :] - img_chw[:, :-2, :])
    return gx, gy


def _solve(A, r, w):
    """(delta(6), H, M) for weights ``w`` (H,W). A:(H,W,3,6) r:(H,W,3)."""
    import torch
    ww = w.double()
    Aw = A.double() * ww[..., None, None]
    g = torch.einsum("hwck,hwc->k", Aw, r.double())
    H = torch.einsum("hwck,hwcl->kl", Aw, A.double())
    M = torch.einsum("hwck,hwcl->kl", A.double() * (ww * ww)[..., None, None], A.double())
    ev = torch.linalg.eigvalsh(0.5 * (H + H.T))
    if float(ev[0]) <= 0 or float(ev[-1]) / max(float(ev[0]), 1e-30) > COND_MAX:
        return None, H, M
    return -torch.linalg.solve(H, g), H, M


def _risk(A, r, w, sigma2):
    import torch
    d, H, M = _solve(A, r, w)
    if d is None:
        return None
    Hi = torch.linalg.inv(H)
    C = sigma2 * (Hi @ M @ Hi)
    out = {
        "dt_mm": 1000.0 * float(torch.linalg.norm(d[:3])),
        "dr_mrad": 1000.0 * float(torch.linalg.norm(d[3:])),
        "sdt_mm": 1000.0 * float(torch.sqrt(torch.clamp(torch.trace(C[:3, :3]), min=0))),
        "sdr_mrad": 1000.0 * float(torch.sqrt(torch.clamp(torch.trace(C[3:, 3:]), min=0))),
    }
    # components kept so the drift-vs-jitter decomposition (prereg 7.1) is computable
    for i, k in enumerate(("tx", "ty", "tz")):
        out[k] = 1000.0 * float(d[i])
    return out


def _robust_w(A, r, valid):
    """Cauchy IRLS on the residual -- knows nothing about dynamics."""
    import torch
    w = valid.double().clone()
    for _ in range(IRLS_ITERS):
        d, _H, _M = _solve(A, r, w)
        if d is None:
            break
        pred = torch.einsum("hwck,k->hwc", A.double(), d)
        e = torch.linalg.norm(r.double() + pred, dim=-1)
        ev = e[valid]
        med = ev.median()
        tau = (_MAD_CONST * (ev - med).abs().median()).clamp_min(1e-6) + 1e-6
        w = valid.double() / (1.0 + (e / tau) ** 2)
    return w


def process(seq_dir, out_dir, device, seed=0):
    import torch

    name = os.path.basename(seq_dir.rstrip("/"))
    calib = CALIB_BONN
    fx, fy, cx, cy = (float(calib[k]) for k in ("fx", "fy", "cx", "cy"))
    mask_idx = frozen_mask_index(os.path.join(seq_dir, "dynamic_mask_gtmc"))
    flow_dir = os.path.join(seq_dir, "flow_raft")
    frames = load_tum_associations(seq_dir)
    keep = [i for i in range(1, len(frames))
            if p1._stem(frames[i]["depth_path"]) in mask_idx]
    if len(keep) > p1.MAX_FRAMES:
        keep = [keep[i] for i in np.linspace(0, len(keep) - 1, p1.MAX_FRAMES).astype(int)]

    rows, skips = [], {"few_valid": 0, "ill_cond": 0, "small_mask": 0}
    for fi in keep:
        f, fprev = frames[fi], frames[fi - 1]
        stem = p1._stem(f["depth_path"])
        rng = np.random.default_rng(
            int(hashlib.sha256(f"p1b|{name}|{stem}|{seed}".encode()).hexdigest()[:8], 16))
        rgb_t = undistort_images([np.asarray(Image.open(f["rgb_path"]).convert("RGB"))],
                                 calib=calib, dist=DIST_BONN)[0]
        rgb_p = undistort_images([np.asarray(Image.open(fprev["rgb_path"]).convert("RGB"))],
                                 calib=calib, dist=DIST_BONN)[0]
        dep = np.asarray(Image.open(f["depth_path"])).astype(np.float32) / float(calib["depth_scale"])
        depth = undistort_depths([dep], calib=calib, dist=DIST_BONN)[0]

        It = torch.as_tensor(rgb_t, dtype=torch.float32, device=device).permute(2, 0, 1) / 255.0
        Ip = torch.as_tensor(rgb_p, dtype=torch.float32, device=device).permute(2, 0, 1) / 255.0
        D = torch.as_tensor(np.ascontiguousarray(depth), dtype=torch.float32, device=device)

        T_t = torch.as_tensor(np.linalg.inv(f["c2w"]), dtype=torch.float32, device=device)
        T_p = torch.as_tensor(np.linalg.inv(fprev["c2w"]), dtype=torch.float32, device=device)
        R, tvec = relative_pose_target_from_source(T_p, T_t)     # T_{t-1 <- t}

        flow, vflow = rigid_flow(D, fx, fy, cx, cy, R, tvec)
        J, vj = flow_jacobian_se3(D, fx, fy, cx, cy, R, tvec)
        h, w_ = D.shape
        us = torch.arange(w_, device=device, dtype=torch.float32).view(1, w_).expand(h, w_)
        vs = torch.arange(h, device=device, dtype=torch.float32).view(h, 1).expand(h, w_)
        u2, v2 = us + flow[..., 0], vs + flow[..., 1]
        grid = torch.stack([2 * u2 / (w_ - 1) - 1, 2 * v2 / (h - 1) - 1], dim=-1)[None]

        Iw = _sample(Ip, grid)                                   # (3,H,W)
        gxp, gyp = _grads(Ip)
        gxw, gyw = _sample(gxp, grid), _sample(gyp, grid)
        r = (Iw - It).permute(1, 2, 0)                           # (H,W,3)
        gw = torch.stack([gxw, gyw], dim=-1).permute(1, 2, 0, 3)  # (H,W,3,2)
        A = torch.einsum("hwca,hwak->hwck", gw, J)               # (H,W,3,6)

        valid = vflow & vj & torch.isfinite(r).all(-1) & torch.isfinite(A).all(-1).all(-1)
        valid[0, :] = valid[-1, :] = valid[:, 0] = valid[:, -1] = False
        if int(valid.sum()) < MIN_VALID:
            skips["few_valid"] += 1
            continue
        rv = torch.linalg.norm(r[valid].double(), dim=-1)
        sigma2 = float((_MAD_CONST * (rv - rv.median()).abs().median()).clamp_min(1e-8) ** 2)

        mask = load_frozen_mask(mask_idx[stem])
        if mask.shape != depth.shape:
            continue
        valid_np = valid.detach().cpu().numpy()
        gt_sel = mask & valid_np
        if int(gt_sel.sum()) < p1.MIN_REMOVED:
            skips["small_mask"] += 1
            continue

        arms = {}
        vf = valid.double()
        arms["all"] = _risk(A, r, vf, sigma2)
        arms["robust"] = _risk(A, r, _robust_w(A, r, valid), sigma2)
        arms["oracle"] = _risk(A, r, vf * (~torch.as_tensor(mask, device=device)).double(), sigma2)

        draws = p1.shifted_masks(mask, valid_np, rng, N_SHIFT, int(gt_sel.sum()))
        sh = [_risk(A, r, vf * (~torch.as_tensor(m, device=device)).double(), sigma2)
              for m, _c, _o in draws]
        sh = [s for s in sh if s]
        arms["shift"] = ({k: float(np.median([s[k] for s in sh])) for k in sh[0]}
                         if len(sh) >= p1.MIN_NULL else None)

        fpath = os.path.join(flow_dir, f"{stem}.npy")
        if os.path.isfile(fpath):
            f_obs = torch.as_tensor(np.load(fpath).astype(np.float32), device=device)
            e_flow = flow_anomaly(f_obs, flow, valid=vflow, ego_jac=J)
            s_rel = torch.clamp(1.0 - e_flow, 0.0, 1.0)
            arms["mrcs"] = _risk(A, r, vf * cauchy_tracking_weight(s_rel, valid).double(), sigma2)
        else:
            arms["mrcs"] = None

        if arms["all"] is None:
            skips["ill_cond"] += 1
            continue
        row = {"frame": fi, "stem": stem, "n_valid": int(valid.sum()),
               "n_removed": int(gt_sel.sum()), "sigma": float(np.sqrt(sigma2))}
        for a, v in arms.items():
            for k in ("dt_mm", "dr_mrad", "sdt_mm", "sdr_mrad", "tx", "ty", "tz"):
                row[f"{a}_{k}"] = v[k] if v else float("nan")
        rows.append(row)
        if len(rows) % 100 == 1:
            print(f"  [{name}] {len(rows)}/{len(keep)} all={row['all_dt_mm']:.2f}mm "
                  f"oracle={row['oracle_dt_mm']:.2f} mrcs={row['mrcs_dt_mm']:.2f}", flush=True)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.csv")
    if rows:
        with open(path, "w", newline="") as fh:
            wtr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            wtr.writeheader()
            wtr.writerows(rows)
    return {"sequence": name, "n_rows": len(rows), "skips": skips, "csv": path}


# ----------------------------- verdict (pre-registered) -----------------------------
ARMS = ["all", "robust", "oracle", "shift", "mrcs"]


def verdict(root):
    per = {}
    for path in sorted(glob.glob(os.path.join(root, "*.csv"))):
        R = [{k: (v if k == "stem" else float(v)) for k, v in r.items()}
             for r in csv.DictReader(open(path))]
        if not R:
            continue
        med = {}
        for a in ARMS:
            v = np.array([r[f"{a}_dt_mm"] for r in R], dtype=float)
            v = v[np.isfinite(v)]
            med[a] = float(np.median(v)) if v.size else float("nan")
        sd = {a: float(np.nanmedian([r[f"{a}_sdt_mm"] for r in R])) for a in ARMS}
        # prereg 7.1 (declared before aggregates, DESCRIPTIVE, not gating):
        # coherent = ||mean delta over a 10-frame window|| / mean ||delta||.
        # -> 1 means the pose error accumulates in one direction (drift, hurts ATE);
        # -> 0 means it cancels frame to frame (jitter, largely harmless).
        coh = {}
        for a in ARMS:
            V = np.array([[r[f"{a}_{c}"] for c in ("tx", "ty", "tz")] for r in R], dtype=float)
            good = np.isfinite(V).all(axis=1)
            vals = []
            for i in range(0, len(V) - 10 + 1, 10):
                blk = V[i:i + 10][good[i:i + 10]]
                if len(blk) < 5:
                    continue
                mn = np.linalg.norm(blk.mean(axis=0))
                mm = np.linalg.norm(blk, axis=1).mean()
                if mm > 0:
                    vals.append(mn / mm)
            coh[a] = float(np.median(vals)) if vals else float("nan")
        base = med["all"]
        red = {a: (1.0 - med[a] / base) if (base and np.isfinite(med[a])) else float("nan")
               for a in ARMS}
        per[os.path.splitext(os.path.basename(path))[0]] = {
            "n": len(R), "med_dt_mm": med, "med_sdt_mm": sd, "red": red, "coherent": coh,
            "mrcs_beats_robust": bool(np.isfinite(med["mrcs"]) and med["mrcs"] < med["robust"]),
        }

    dyn = {k: v for k, v in per.items() if k != STATIC_CONTROL}
    ctl = per.get(STATIC_CONTROL)
    n_oracle = sum(v["red"]["oracle"] >= 0.30 for v in dyn.values())
    n_shift = sum(v["red"]["shift"] <= 0.10 for v in dyn.values()
                  if np.isfinite(v["red"]["shift"]))
    gate = []
    if n_oracle < 4:
        gate.append(f"oracle reduces bias >=30% on only {n_oracle}/7 (need 4)")
    if n_shift < 5:
        gate.append(f"shift control stays <=10% on only {n_shift}/7 (need 5)")
    if ctl and ctl["red"]["oracle"] > 0.15:
        gate.append(f"static control shows {ctl['red']['oracle']:.2f} oracle reduction (need <=0.15)")
    if any(v["med_dt_mm"]["all"] < 0.05 for v in dyn.values()):
        gate.append("some sequence has med|delta(all)| < 0.05 mm (below interpolation noise)")

    n_pass = sum(
        np.isfinite(v["red"]["mrcs"]) and v["red"]["mrcs"] >= 0.50 * v["red"]["oracle"]
        for v in dyn.values())
    n_fail = sum(
        np.isfinite(v["red"]["mrcs"]) and v["red"]["mrcs"] <= 0.20 * v["red"]["oracle"]
        for v in dyn.values())
    if gate:
        v_txt, why = "NO VERDICT (apparatus gate)", "; ".join(gate)
    elif n_pass >= 4:
        v_txt, why = "PASS", f"mrcs recovers >=50% of oracle's reduction on {n_pass}/7"
    elif n_fail >= 5:
        v_txt, why = "FAIL", f"mrcs recovers <=20% of oracle's reduction on {n_fail}/7"
    else:
        v_txt, why = "INDETERMINATE", f"{n_pass}/7 pass, {n_fail}/7 fail"

    hdr = (f"{'sequence':38s} {'n':>4s} " + " ".join(f"{a:>9s}" for a in ARMS)
           + f" | {'red_orc':>7s} {'red_shf':>7s} {'red_mrc':>7s} {'m<rob':>6s}")
    print(hdr + "\n" + "-" * len(hdr))
    for k, v in per.items():
        print(f"{k:38s} {v['n']:4d} " + " ".join(f"{v['med_dt_mm'][a]:9.3f}" for a in ARMS)
              + f" | {v['red']['oracle']:7.3f} {v['red']['shift']:7.3f} "
                f"{v['red']['mrcs']:7.3f} {str(v['mrcs_beats_robust']):>6s}")
    print("\n(median |delta_translation| per frame, mm; red_X = 1 - med_X/med_all)")
    print("\ncoherence (prereg 7.1, DESCRIPTIVE): ||mean delta|| / mean||delta|| over 10-frame "
          "windows;\n  ->1 = drift (accumulates, hurts ATE), ->0 = jitter (cancels)")
    ch = f"{'sequence':38s} " + " ".join(f"{a:>9s}" for a in ARMS)
    print(ch + "\n" + "-" * len(ch))
    for k, v in per.items():
        print(f"{k:38s} " + " ".join(f"{v['coherent'][a]:9.3f}" for a in ARMS))
    print(f"\nVERDICT: {v_txt}  --  {why}")
    blob = {"verdict": v_txt, "why": why, "sequences": per}
    with open(os.path.join(root, "p1b_verdict.json"), "w") as fh:
        json.dump(blob, fh, indent=2)
    return blob


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datasets-root", default="/data/Datasets/Bonn")
    ap.add_argument("--sequences", default="all")
    ap.add_argument("--out", default="results/evidence/p1b_pose_risk")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--verdict", default=None, help="verdict-only on an existing dir")
    args = ap.parse_args()
    if args.verdict:
        verdict(args.verdict)
        return
    import torch
    device = args.device if args.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu")
    seqs = (DYN_SEQUENCES + [STATIC_CONTROL]) if args.sequences == "all" else args.sequences.split(",")
    info = []
    for s in seqs:
        sd = s if os.path.isdir(s) else os.path.join(args.datasets_root, s)
        if not os.path.isdir(sd):
            print(f"[skip] {s} missing")
            continue
        print(f"[run] {s} on {device}", flush=True)
        info.append(process(sd, args.out, device))
        print(f"[done] {info[-1]}", flush=True)
    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump({"arms": ARMS, "n_shift": N_SHIFT,
                   "preregistration": "results/evidence/p1b_pose_risk_preregistration.md",
                   "runs": info}, fh, indent=2)
    verdict(args.out)


if __name__ == "__main__":
    main()
