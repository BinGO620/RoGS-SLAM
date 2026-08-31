#!/usr/bin/env python3
"""P1c step 0: can a perturbation-recovery apparatus SEE a dynamic object at all?

P1b failed because its estimand ("one GN step at the true pose") buried the dynamic
signal under nuisance: residual sigma was 7/255 AT THE TRUE POSE, and the measured bias
was 100x the sandwich-predicted sd. P1c changes the estimand to RECOVERY:

    start at  T_init = exp(eps) T*  ,  run N Gauss-Newton steps ,
    endpoint  rho = ||log(T_after T*^-1)|| / ||eps||          (0 = perfect, 1 = no move)

Nuisance that is common to every arm now sits in the floor of ``rho`` instead of in its
signal, and ``T*`` is known exactly because THIS FILE SYNTHESIZES THE PAIR.

This is instrument calibration, NOT the experiment. It answers one question before any
real-data threshold is written (criteria (4)/(8): compute the reachable domain, and
condition it on the experiment's actual scale):

    at the dynamic-area fractions Bonn actually has (GT masks cover 1.1-5.8% of valid
    pixels, measured in P1), does removing the dynamic pixels measurably improve
    recovery -- i.e. is ``rho(oracle) < rho(all)`` outside the shift-control's spread?

Construction (exact ground truth, no occlusion, no exposure drift):
  * ``I_p``, ``D`` are a real Bonn frame; ``T*`` is a real consecutive GT relative pose;
  * ``I_t(x) := I_p(x + flow(x; D, T*))``       -> residual is identically 0 at ``T*``;
  * inside a rectangle ``M`` (area fraction ``f``): ``I_t(x) := I_p(x + flow(x) + d)``
    -> an independently moving object with a KNOWN, coherent image displacement ``d``.

Controls, run in the same sweep (criterion (11): positive and negative control travel
with the judgement, else "did not see it" and "cannot see it" are indistinguishable):
  * positive : ``d`` large + ``f`` large  -- the apparatus MUST separate oracle from all;
  * negative : ``d = 0`` (block moves with the scene) -- oracle MUST NOT beat all;
  * shift    : same-size rectangle at a random static place -- the invalidation control.

Usage:
  python scripts/p1c_recovery_synthetic.py --out results/evidence/p1c_recovery/synthetic
"""

import argparse
import csv
import json
import os
import sys

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from utils.geometry_metrics import load_tum_associations  # noqa: E402
from utils.gtmc_mask import (  # noqa: E402
    CALIB_BONN, DIST_BONN, undistort_depths, undistort_images,
)
from utils.reliability_signal import (  # noqa: E402
    _MAD_CONST, relative_pose_target_from_source, rigid_flow, flow_jacobian_se3,
)

# --- apparatus constants (fixed before any reading, see module docstring) -------------
EPS_T_MM = (5.0, 10.0, 20.0)        # translation perturbations
EPS_R_MRAD = (2.0, 5.0)             # rotation perturbations
N_DIR = 4                           # random directions per (eps_t, eps_r) pair
GN_STEPS = 8                        # measured: the clean pair needs ~6 to converge
AREA_FRACS = (0.02, 0.05, 0.10, 0.20, 0.40)   # 0.02/0.05 bracket Bonn's real 1.1-5.8%
DISPLACEMENTS = (0.0, 2.0, 5.0, 10.0)   # px; 0.0 IS the negative control
SIGMA = 7.0 / 255.0                 # P1b measured this residual sd on real Bonn pairs;
#                                     without it the synthetic pair is unrealistically easy
N_SHIFT = 8
MIN_VALID = 5000
COND_MAX = 1e10
IRLS_ITERS = 4


# --------------------------------- se(3) ---------------------------------------------
def _hat(w):
    return np.array([[0, -w[2], w[1]], [w[2], 0, -w[0]], [-w[1], w[0], 0]], dtype=np.float64)


def se3_exp(xi):
    """``xi = (nu, omega)`` -> 4x4. Same left-perturbation convention as flow_jacobian_se3."""
    nu, w = np.asarray(xi[:3], np.float64), np.asarray(xi[3:], np.float64)
    th = float(np.linalg.norm(w))
    W = _hat(w)
    if th < 1e-12:
        R, V = np.eye(3) + W, np.eye(3) + 0.5 * W
    else:
        R = np.eye(3) + np.sin(th) / th * W + (1 - np.cos(th)) / th**2 * (W @ W)
        V = np.eye(3) + (1 - np.cos(th)) / th**2 * W + (th - np.sin(th)) / th**3 * (W @ W)
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, V @ nu
    return T


def se3_log(T):
    R, t = np.asarray(T[:3, :3], np.float64), np.asarray(T[:3, 3], np.float64)
    c = (np.trace(R) - 1.0) / 2.0
    th = float(np.arccos(np.clip(c, -1.0, 1.0)))
    if th < 1e-12:
        w = 0.5 * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
        Vi = np.eye(3) - 0.5 * _hat(w)
    else:
        w = th / (2 * np.sin(th)) * np.array(
            [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
        W = _hat(w)
        Vi = (np.eye(3) - 0.5 * W
              + (1 / th**2) * (1 - th * np.sin(th) / (2 * (1 - np.cos(th)))) * (W @ W))
    return np.concatenate([Vi @ t, w])


def pose_err(T, T_star):
    """(translation mm, rotation mrad) of ``T`` relative to ``T_star``."""
    xi = se3_log(np.asarray(T, np.float64) @ np.linalg.inv(np.asarray(T_star, np.float64)))
    return 1000.0 * float(np.linalg.norm(xi[:3])), 1000.0 * float(np.linalg.norm(xi[3:]))


# ------------------------------- photometric GN ---------------------------------------
def _sample(img_chw, grid):
    import torch.nn.functional as F
    return F.grid_sample(img_chw[None], grid, mode="bilinear",
                         padding_mode="border", align_corners=True)[0]


def _grads(img_chw):
    import torch
    gx, gy = torch.zeros_like(img_chw), torch.zeros_like(img_chw)
    gx[:, :, 1:-1] = 0.5 * (img_chw[:, :, 2:] - img_chw[:, :, :-2])
    gy[:, 1:-1, :] = 0.5 * (img_chw[:, 2:, :] - img_chw[:, :-2, :])
    return gx, gy


def _grid_from_flow(flow, h, w, device, extra=None):
    import torch
    us = torch.arange(w, device=device, dtype=torch.float32).view(1, w).expand(h, w)
    vs = torch.arange(h, device=device, dtype=torch.float32).view(h, 1).expand(h, w)
    u2, v2 = us + flow[..., 0], vs + flow[..., 1]
    if extra is not None:
        u2, v2 = u2 + extra[..., 0], v2 + extra[..., 1]
    return torch.stack([2 * u2 / (w - 1) - 1, 2 * v2 / (h - 1) - 1], dim=-1)[None]


def linearize(Ip, It, D, K, T, device):
    """Residual/Jacobian of ``I_p(warp(x; T)) - I_t(x)`` at pose ``T`` (target<-source)."""
    import torch
    fx, fy, cx, cy = K
    R = torch.as_tensor(T[:3, :3], dtype=torch.float32, device=device)
    tv = torch.as_tensor(T[:3, 3], dtype=torch.float32, device=device)
    flow, vflow = rigid_flow(D, fx, fy, cx, cy, R, tv)
    J, vj = flow_jacobian_se3(D, fx, fy, cx, cy, R, tv)
    h, w = D.shape
    grid = _grid_from_flow(flow, h, w, device)
    Iw = _sample(Ip, grid)
    gxp, gyp = _grads(Ip)
    gw = torch.stack([_sample(gxp, grid), _sample(gyp, grid)], dim=-1).permute(1, 2, 0, 3)
    r = (Iw - It).permute(1, 2, 0)
    A = torch.einsum("hwca,hwak->hwck", gw, J)
    valid = vflow & vj & torch.isfinite(r).all(-1) & torch.isfinite(A).all(-1).all(-1)
    valid[0, :] = valid[-1, :] = valid[:, 0] = valid[:, -1] = False
    return r, A, valid


def _solve(A, r, w):
    import torch
    ww = w.double()
    Aw = A.double() * ww[..., None, None]
    g = torch.einsum("hwck,hwc->k", Aw, r.double())
    H = torch.einsum("hwck,hwcl->kl", Aw, A.double())
    ev = torch.linalg.eigvalsh(0.5 * (H + H.T))
    if float(ev[0]) <= 0 or float(ev[-1]) / max(float(ev[0]), 1e-30) > COND_MAX:
        return None
    return -torch.linalg.solve(H, g)


def _robust_w(A, r, valid):
    import torch
    w = valid.double().clone()
    for _ in range(IRLS_ITERS):
        d = _solve(A, r, w)
        if d is None:
            break
        e = torch.linalg.norm(r.double() + torch.einsum("hwck,k->hwc", A.double(), d), dim=-1)
        ev = e[valid]
        tau = (_MAD_CONST * (ev - ev.median()).abs().median()).clamp_min(1e-6) + 1e-6
        w = valid.double() / (1.0 + (e / tau) ** 2)
    return w


def recover(Ip, It, D, K, T_init, T_star, device, arm, block=None, steps=GN_STEPS):
    """Run ``steps`` GN iterations from ``T_init``; return (dt_mm, dr_mrad) after."""
    import torch
    T = np.asarray(T_init, np.float64).copy()
    for _ in range(steps):
        r, A, valid = linearize(Ip, It, D, K, T, device)
        if int(valid.sum()) < MIN_VALID:
            return None
        if arm == "robust":
            w = _robust_w(A, r, valid)
        elif arm in ("oracle", "shift"):
            keep = valid & ~torch.as_tensor(block, device=device)
            if int(keep.sum()) < MIN_VALID:
                return None
            w = keep.double()
        else:
            w = valid.double()
        d = _solve(A, r, w)
        if d is None:
            return None
        T = se3_exp(d.detach().cpu().numpy()) @ T
    return pose_err(T, T_star)


# ------------------------------- synthetic pair ---------------------------------------
def make_block(h, w, frac, rng, avoid_border=16):
    """Axis-aligned rectangle of area fraction ``frac``, aspect ~ 0.6 (person-like)."""
    area = frac * h * w
    bh = int(round(np.sqrt(area / 0.6)))
    bw = max(1, int(round(0.6 * bh)))
    bh, bw = min(bh, h - 2 * avoid_border), min(bw, w - 2 * avoid_border)
    y0 = int(rng.integers(avoid_border, h - avoid_border - bh + 1))
    x0 = int(rng.integers(avoid_border, w - avoid_border - bw + 1))
    m = np.zeros((h, w), dtype=bool)
    m[y0:y0 + bh, x0:x0 + bw] = True
    return m


def synth_pair(seq_dir, frame_idx, device):
    """Real ``I_p``/``D``/``T*``; ``I_t`` is generated so the residual is 0 at ``T*``."""
    import torch
    calib = CALIB_BONN
    K = tuple(float(calib[k]) for k in ("fx", "fy", "cx", "cy"))
    frames = load_tum_associations(seq_dir)
    f, fp = frames[frame_idx], frames[frame_idx - 1]
    rgb_p = undistort_images([np.asarray(Image.open(fp["rgb_path"]).convert("RGB"))],
                             calib=calib, dist=DIST_BONN)[0]
    dep = np.asarray(Image.open(f["depth_path"])).astype(np.float32) / float(calib["depth_scale"])
    depth = undistort_depths([dep], calib=calib, dist=DIST_BONN)[0]
    Ip = torch.as_tensor(rgb_p, dtype=torch.float32, device=device).permute(2, 0, 1) / 255.0
    D = torch.as_tensor(np.ascontiguousarray(depth), dtype=torch.float32, device=device)
    T_t = np.linalg.inv(f["c2w"])
    T_p = np.linalg.inv(fp["c2w"])
    T_star = T_p @ np.linalg.inv(T_t)                      # T_{t-1 <- t}, 4x4
    return Ip, D, K, T_star


def render_It(Ip, D, K, T_star, device, block=None, disp=(0.0, 0.0), sigma=0.0, seed=0):
    import torch
    fx, fy, cx, cy = K
    R = torch.as_tensor(T_star[:3, :3], dtype=torch.float32, device=device)
    tv = torch.as_tensor(T_star[:3, 3], dtype=torch.float32, device=device)
    flow, vflow = rigid_flow(D, fx, fy, cx, cy, R, tv)
    h, w = D.shape
    It = _sample(Ip, _grid_from_flow(flow, h, w, device))
    if block is not None and (disp[0] or disp[1]):
        extra = torch.zeros((h, w, 2), device=device)
        bm = torch.as_tensor(block, device=device)
        z = torch.zeros((), device=device)
        extra[..., 0] = torch.where(bm, torch.tensor(float(disp[0]), device=device), z)
        extra[..., 1] = torch.where(bm, torch.tensor(float(disp[1]), device=device), z)
        Id = _sample(Ip, _grid_from_flow(flow, h, w, device, extra=extra))
        It = torch.where(bm[None], Id, It)
    if sigma > 0:
        g = torch.Generator(device=device)
        g.manual_seed(int(seed))
        It = It + sigma * torch.randn(It.shape, device=device, generator=g)
    return It, vflow


# ---------------------------------- sweep ---------------------------------------------
def run(seq_dir, out_dir, device, n_frames=4, seed=0, sigma=SIGMA):
    rng_top = np.random.default_rng(seed)
    frames = load_tum_associations(seq_dir)
    idxs = np.linspace(30, len(frames) - 5, n_frames).astype(int)
    rows = []
    for fi in idxs:
        Ip, D, K, T_star = synth_pair(seq_dir, int(fi), device)
        h, w = D.shape
        for frac in AREA_FRACS:
            rng = np.random.default_rng(abs(hash((int(fi), frac, seed))) % (2**32))
            block = make_block(h, w, frac, rng)
            shifts = [make_block(h, w, frac, rng) for _ in range(N_SHIFT)]
            for disp_mag in DISPLACEMENTS:
                ang = float(rng.uniform(0, 2 * np.pi))
                disp = (disp_mag * np.cos(ang), disp_mag * np.sin(ang))
                It, _ = render_It(Ip, D, K, T_star, device, block=block, disp=disp,
                                  sigma=sigma, seed=int(fi))
                for eps_t in EPS_T_MM:
                    for eps_r in EPS_R_MRAD:
                        for k in range(N_DIR):
                            v = rng_top.normal(size=3); v /= np.linalg.norm(v)
                            o = rng_top.normal(size=3); o /= np.linalg.norm(o)
                            eps = np.concatenate([v * eps_t / 1000.0, o * eps_r / 1000.0])
                            T_init = se3_exp(eps) @ T_star
                            e0 = pose_err(T_init, T_star)
                            row = {"frame": int(fi), "frac": frac, "disp": disp_mag,
                                   "eps_t_mm": eps_t, "eps_r_mrad": eps_r, "dir": k,
                                   "e0_t_mm": e0[0], "e0_r_mrad": e0[1]}
                            ok = True
                            for arm in ("all", "robust", "oracle", "shift"):
                                blk = block if arm == "oracle" else (
                                    shifts[k % N_SHIFT] if arm == "shift" else None)
                                res = recover(Ip, It, D, K, T_init, T_star, device, arm, blk)
                                if res is None:
                                    ok = False
                                    break
                                row[f"{arm}_t_mm"], row[f"{arm}_r_mrad"] = res
                                row[f"{arm}_rho_t"] = res[0] / max(e0[0], 1e-9)
                                row[f"{arm}_rho_r"] = res[1] / max(e0[1], 1e-9)
                            if ok:
                                rows.append(row)
            print(f"  [f{fi} frac={frac}] rows={len(rows)}", flush=True)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "synthetic_sweep.csv")
    with open(path, "w", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wtr.writeheader()
        wtr.writerows(rows)
    return path, rows


def summarize(rows, out_dir):
    """Per (frac, disp): median rho_t per arm + the separation the apparatus achieves."""
    keys = sorted({(r["frac"], r["disp"]) for r in rows})
    tab = []
    for frac, disp in keys:
        sub = [r for r in rows if r["frac"] == frac and r["disp"] == disp]
        med = {a: float(np.median([r[f"{a}_rho_t"] for r in sub]))
               for a in ("all", "robust", "oracle", "shift")}
        # separation: how much of ``all``'s residual error oracle removes, relative to
        # what the shift control removes by chance at the same removed-area.
        gain_orc = med["all"] - med["oracle"]
        gain_shf = med["all"] - med["shift"]
        tab.append({"frac": frac, "disp": disp, "n": len(sub), **med,
                    "gain_oracle": gain_orc, "gain_shift": gain_shf,
                    "sep": gain_orc - gain_shf})
    hdr = (f"{'frac':>6s} {'disp_px':>8s} {'n':>5s} {'all':>8s} {'robust':>8s} "
           f"{'oracle':>8s} {'shift':>8s} | {'g_orc':>8s} {'g_shf':>8s} {'sep':>8s}")
    print(hdr + "\n" + "-" * len(hdr))
    for t in tab:
        print(f"{t['frac']:6.2f} {t['disp']:8.1f} {t['n']:5d} {t['all']:8.4f} "
              f"{t['robust']:8.4f} {t['oracle']:8.4f} {t['shift']:8.4f} | "
              f"{t['gain_oracle']:8.4f} {t['gain_shift']:8.4f} {t['sep']:8.4f}")
    print("\nrho_t = ||t error after 3 GN steps|| / ||t error injected||  (0 perfect, 1 inert)")
    print("sep   = (all-oracle) - (all-shift): the part of oracle's gain that removing "
          "THAT area\n        specifically buys, over removing an equal static area.")
    with open(os.path.join(out_dir, "synthetic_summary.json"), "w") as fh:
        json.dump(tab, fh, indent=2)
    return tab


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sequence", default="/data/Datasets/Bonn/rgbd_bonn_static_close_far",
                    help="source of I_p/D/T* -- a STATIC sequence, so the only motion "
                         "in the synthesized pair is the one we inject")
    ap.add_argument("--out", default="results/evidence/p1c_recovery/synthetic")
    ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--sigma", type=float, default=SIGMA,
                    help="photometric noise added to I_t (default = P1b's measured 7/255)")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--summarize", default=None, help="summarize an existing sweep csv dir")
    args = ap.parse_args()
    if args.summarize:
        rows = [{k: (float(v) if k != "stem" else v) for k, v in r.items()}
                for r in csv.DictReader(open(os.path.join(args.summarize, "synthetic_sweep.csv")))]
        summarize(rows, args.summarize)
        return
    import torch
    device = args.device if args.device != "auto" else (
        "cuda" if torch.cuda.is_available() else "cpu")
    print(f"[p1c-synth] {args.sequence} on {device} sigma={args.sigma * 255:.1f}/255", flush=True)
    path, rows = run(args.sequence, args.out, device, n_frames=args.frames, sigma=args.sigma)
    print(f"[done] {len(rows)} rows -> {path}")
    summarize(rows, args.out)


if __name__ == "__main__":
    main()
