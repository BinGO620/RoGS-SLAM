#!/usr/bin/env python3
"""P1c real-data stage: does a pixel policy move the CONVERGED pose the way the oracle does?

The GT-referenced endpoint of the synthetic stage cannot be used on Bonn. Measured, on
``rgbd_bonn_balloon``, before writing this rule (see the pre-registration §4):

    starting at the GT relative pose itself (eps = 0), 8 GN steps walk 10.3 / 15.9 /
    19.4 mm AWAY from it -- and starting 10 mm off converges to the SAME point to 0.01 mm.

So Gauss-Newton converges cleanly, but the photometric optimum sits 10-19 mm from the
Bonn GT pose (mocap/calibration/rolling-shutter offset). Any endpoint measured against GT
is therefore dominated by a nuisance the size of the whole effect -- P1b's failure mode.

This file uses the estimand that cancels it: every arm is run to CONVERGENCE from a common
start, and arms are compared to each other, PAIRWISE, never to GT:

    u_X = log( That_X  That_all^-1 )        (how policy X moves the converged pose)
    pi_X = <u_X, u_oracle> / ||u_oracle||^2  (how much of the ORACLE's move X reproduces)

``pi = 1`` reproduces the oracle exactly, ``0`` does nothing, ``< 0`` moves the opposite
way. This is a projection, not a magnitude: P1b's flag (2) -- coherent component opposite
to magnitude -- is precisely what a magnitude comparison cannot see.

GT is used ONLY to define the common starting point, never as the target.

Nuisance handled identically for every arm: per-frame affine exposure compensation,
exclusion of occlusion boundaries and depth discontinuities.

Gates and the verdict rule are PRE-REGISTERED in
``results/evidence/p1c_recovery_preregistration.md``. This file applies that rule.

Usage:
  python scripts/p1c_recovery_real.py --sequences all --out results/evidence/p1c_recovery/real
  python scripts/p1c_recovery_real.py --verdict results/evidence/p1c_recovery/real
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


def _load(mod):
    spec = importlib.util.spec_from_file_location(mod, os.path.join(_HERE, f"{mod}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


p1 = _load("p1_observability_offline")
p1c = _load("p1c_recovery_synthetic")

from utils.geometry_metrics import load_tum_associations  # noqa: E402
from utils.gtmc_mask import (  # noqa: E402
    CALIB_BONN, DIST_BONN, frozen_mask_index, load_frozen_mask,
    undistort_depths, undistort_images,
)
from utils.reliability_signal import (  # noqa: E402
    cauchy_tracking_weight, flow_anomaly, flow_jacobian_se3,
    relative_pose_target_from_source, rigid_flow,
)

DYN_SEQUENCES = list(p1.SEQUENCES)
STATIC_CONTROL = "rgbd_bonn_static_close_far"
ARMS = ["robust", "oracle", "mrcs"]         # all arms are measured RELATIVE to `all`

EPS_MM = 10.0               # start offsets: two independent draws certify convergence
N_START = 2
GN_STEPS = 8
N_SHIFT = 4                 # shift draws per frame -> the per-frame null
DEPTH_EDGE_M = 0.05
OCCL_DILATE = 3
MIN_VALID = 5000


def _exclusion(D, device):
    """(H,W) bool: pixels to drop -- depth discontinuities and occlusion boundaries."""
    import torch
    import torch.nn.functional as F
    bad = ~torch.isfinite(D) | (D <= 0)
    gx = torch.zeros_like(D)
    gy = torch.zeros_like(D)
    gx[:, 1:-1] = 0.5 * (D[:, 2:] - D[:, :-2]).abs()
    gy[1:-1, :] = 0.5 * (D[2:, :] - D[:-2, :]).abs()
    edge = (torch.maximum(gx, gy) > DEPTH_EDGE_M) & ~bad
    k = 2 * OCCL_DILATE + 1
    return F.max_pool2d((bad | edge).float()[None, None], k, stride=1,
                        padding=OCCL_DILATE)[0, 0] > 0.5


def _affine_exposure(Iw, It, valid):
    """Robust per-frame ``a, b`` with ``a*Iw + b ~= It`` on the valid set (shared by arms)."""
    import torch
    x = Iw.permute(1, 2, 0)[valid].reshape(-1).double()
    y = It.permute(1, 2, 0)[valid].reshape(-1).double()
    if x.numel() < 100:
        return 1.0, 0.0
    xm, ym = x.median(), y.median()
    sx = (x - xm).abs().median().clamp_min(1e-6)
    sy = (y - ym).abs().median().clamp_min(1e-6)
    a = float((sy / sx).clamp(0.5, 2.0))
    return a, float(ym - a * xm)


def linearize(Ip, It, D, K, T, device, drop):
    """Residual/Jacobian at ``T``, with exposure compensation and the exclusion mask."""
    import torch
    fx, fy, cx, cy = K
    R = torch.as_tensor(T[:3, :3], dtype=torch.float32, device=device)
    tv = torch.as_tensor(T[:3, 3], dtype=torch.float32, device=device)
    flow, vflow = rigid_flow(D, fx, fy, cx, cy, R, tv)
    J, vj = flow_jacobian_se3(D, fx, fy, cx, cy, R, tv)
    h, w = D.shape
    grid = p1c._grid_from_flow(flow, h, w, device)
    Iw = p1c._sample(Ip, grid)
    gxp, gyp = p1c._grads(Ip)
    gw = torch.stack([p1c._sample(gxp, grid), p1c._sample(gyp, grid)],
                     dim=-1).permute(1, 2, 0, 3)
    valid = vflow & vj & ~drop
    valid[0, :] = valid[-1, :] = valid[:, 0] = valid[:, -1] = False
    a, b = _affine_exposure(Iw, It, valid)
    r = (a * Iw + b - It).permute(1, 2, 0)
    A = a * torch.einsum("hwca,hwak->hwck", gw, J)
    valid = valid & torch.isfinite(r).all(-1) & torch.isfinite(A).all(-1).all(-1)
    return r, A, valid, (a, b)


def converge(Ip, It, D, K, T_init, device, drop, weight_fn):
    """Run ``GN_STEPS`` Gauss-Newton steps; return the converged 4x4 pose, or None."""
    T = np.asarray(T_init, np.float64).copy()
    for _ in range(GN_STEPS):
        r, A, valid, _ab = linearize(Ip, It, D, K, T, device, drop)
        if int(valid.sum()) < MIN_VALID:
            return None
        w = weight_fn(A, r, valid)
        if w is None or float(w.sum()) < MIN_VALID * 0.05:
            return None
        d = p1c._solve(A, r, w)
        if d is None:
            return None
        T = p1c.se3_exp(d.detach().cpu().numpy()) @ T
    return T


def _u(T_x, T_ref):
    """se(3) displacement of ``T_x`` from ``T_ref``: (translation mm (3,), rotation mrad (3,))."""
    xi = p1c.se3_log(np.asarray(T_x, np.float64) @ np.linalg.inv(np.asarray(T_ref, np.float64)))
    return 1000.0 * xi[:3], 1000.0 * xi[3:]


def _pi(u_x, u_o):
    n2 = float(u_o @ u_o)
    return float(u_x @ u_o) / n2 if n2 > 1e-18 else float("nan")


def process(seq_dir, out_dir, device, seed=0, max_frames=None):
    import torch

    name = os.path.basename(seq_dir.rstrip("/"))
    calib = CALIB_BONN
    K = tuple(float(calib[k]) for k in ("fx", "fy", "cx", "cy"))
    mask_idx = frozen_mask_index(os.path.join(seq_dir, "dynamic_mask_gtmc"))
    flow_dir = os.path.join(seq_dir, "flow_raft")
    frames = load_tum_associations(seq_dir)
    keep = [i for i in range(1, len(frames))
            if p1._stem(frames[i]["depth_path"]) in mask_idx]
    cap = max_frames or p1.MAX_FRAMES
    if len(keep) > cap:
        keep = [keep[i] for i in np.linspace(0, len(keep) - 1, cap).astype(int)]

    rows, skips = [], {"few_valid": 0, "small_mask": 0, "failed": 0}
    for fi in keep:
        f, fprev = frames[fi], frames[fi - 1]
        stem = p1._stem(f["depth_path"])
        rng = np.random.default_rng(
            int(hashlib.sha256(f"p1c|{name}|{stem}|{seed}".encode()).hexdigest()[:8], 16))
        rgb_t = undistort_images([np.asarray(Image.open(f["rgb_path"]).convert("RGB"))],
                                 calib=calib, dist=DIST_BONN)[0]
        rgb_p = undistort_images([np.asarray(Image.open(fprev["rgb_path"]).convert("RGB"))],
                                 calib=calib, dist=DIST_BONN)[0]
        dep = np.asarray(Image.open(f["depth_path"])).astype(np.float32) / float(calib["depth_scale"])
        depth = undistort_depths([dep], calib=calib, dist=DIST_BONN)[0]

        It = torch.as_tensor(rgb_t, dtype=torch.float32, device=device).permute(2, 0, 1) / 255.0
        Ip = torch.as_tensor(rgb_p, dtype=torch.float32, device=device).permute(2, 0, 1) / 255.0
        D = torch.as_tensor(np.ascontiguousarray(depth), dtype=torch.float32, device=device)
        drop = _exclusion(D, device)

        T_t = np.linalg.inv(f["c2w"])
        T_p = np.linalg.inv(fprev["c2w"])
        T_star = T_p @ np.linalg.inv(T_t)                       # T_{t-1 <- t}, start only

        mask = load_frozen_mask(mask_idx[stem])
        if mask.shape != depth.shape:
            continue
        _r0, _A0, valid0, _ab = linearize(Ip, It, D, K, T_star, device, drop)
        if int(valid0.sum()) < MIN_VALID:
            skips["few_valid"] += 1
            continue
        valid_np = valid0.detach().cpu().numpy()
        n_rm = int((mask & valid_np).sum())
        if n_rm < p1.MIN_REMOVED:
            skips["small_mask"] += 1
            continue

        mask_t = torch.as_tensor(mask, device=device)
        shifts = [torch.as_tensor(m, device=device) for m, _c, _o in
                  p1.shifted_masks(mask, valid_np, rng, N_SHIFT, n_rm)]

        s_rel = None
        fpath = os.path.join(flow_dir, f"{stem}.npy")
        if os.path.isfile(fpath):
            Rr, tt = relative_pose_target_from_source(
                torch.as_tensor(T_t, dtype=torch.float32, device=device),
                torch.as_tensor(T_p, dtype=torch.float32, device=device))
            fl, vfl = rigid_flow(D, *K, Rr, tt)
            Jj, _vj = flow_jacobian_se3(D, *K, Rr, tt)
            f_obs = torch.as_tensor(np.load(fpath).astype(np.float32), device=device)
            s_rel = torch.clamp(1.0 - flow_anomaly(f_obs, fl, valid=vfl, ego_jac=Jj), 0.0, 1.0)

        def wf_all(A, r, v):
            return v.double()

        def wf_robust(A, r, v):
            return p1c._robust_w(A, r, v)

        def wf_drop(m):
            return lambda A, r, v: (v & ~m).double()

        def wf_mrcs(A, r, v):
            if s_rel is None:
                return None
            return v.double() * cauchy_tracking_weight(s_rel, v).double()

        fns = {"all": wf_all, "robust": wf_robust, "oracle": wf_drop(mask_t),
               "mrcs": wf_mrcs}
        for j, m in enumerate(shifts):
            fns[f"shift{j}"] = wf_drop(m)

        # Two independent starts per arm: their disagreement IS the apparatus resolution,
        # and it is what every effect below has to clear.
        starts = []
        for _ in range(N_START):
            u3 = rng.normal(size=3)
            u3 /= np.linalg.norm(u3)
            starts.append(p1c.se3_exp(np.concatenate([u3 * EPS_MM / 1000.0, np.zeros(3)])) @ T_star)

        conv, spread = {}, {}
        for arm, fn in fns.items():
            Ts = [converge(Ip, It, D, K, s, device, drop, fn) for s in starts]
            Ts = [t for t in Ts if t is not None]
            conv[arm] = Ts[0] if Ts else None
            if len(Ts) > 1:
                spread[arm] = float(np.linalg.norm(_u(Ts[1], Ts[0])[0]))
        if conv.get("all") is None or conv.get("oracle") is None or not spread:
            skips["failed"] += 1
            continue

        u_o, ur_o = _u(conv["oracle"], conv["all"])
        # The resolution of ``u_oracle`` is set by the reproducibility of the two arms it is
        # built from -- NOT by every arm in the study. `robust` re-fits its own IRLS weights
        # at each start and is the least stable arm; folding its spread into this number
        # would gate the oracle effect on an instability it does not depend on. Every arm's
        # spread is still written out, and each arm is checked against its own below.
        res = max(spread.get("all", np.nan), spread.get("oracle", np.nan))
        row = {"frame": fi, "stem": stem, "n_valid": int(valid0.sum()), "n_removed": n_rm,
               "area_frac": n_rm / max(int(valid0.sum()), 1),
               "resolution_mm": float(res),
               "oracle_mm": float(np.linalg.norm(u_o)),
               "oracle_mrad": float(np.linalg.norm(ur_o))}
        for a in ("all", "robust", "oracle", "mrcs"):
            row[f"res_{a}_mm"] = float(spread.get(a, float("nan")))
        row["res_shift_mm"] = float(np.nanmax(
            [spread.get(f"shift{j}", np.nan) for j in range(len(shifts))] or [np.nan]))
        for i, c in enumerate("xyz"):
            row[f"oracle_{c}"] = float(u_o[i])
        for arm in ("robust", "mrcs"):
            if conv.get(arm) is None:
                row[f"{arm}_mm"] = row[f"{arm}_pi"] = float("nan")
                continue
            u_x, _ = _u(conv[arm], conv["all"])
            row[f"{arm}_mm"] = float(np.linalg.norm(u_x))
            row[f"{arm}_pi"] = _pi(u_x, u_o)
        sh_mm, sh_pi = [], []
        for j in range(len(shifts)):
            if conv.get(f"shift{j}") is None:
                continue
            u_s, _ = _u(conv[f"shift{j}"], conv["all"])
            sh_mm.append(float(np.linalg.norm(u_s)))
            sh_pi.append(_pi(u_s, u_o))
        row["shift_mm"] = float(np.median(sh_mm)) if sh_mm else float("nan")
        row["shift_max_mm"] = float(np.max(sh_mm)) if sh_mm else float("nan")
        row["shift_pi"] = float(np.median(sh_pi)) if sh_pi else float("nan")
        rows.append(row)
        if len(rows) % 25 == 1:
            print(f"  [{name}] {len(rows)} frames  area={row['area_frac']:.3f} "
                  f"res={row['resolution_mm']:.3f} oracle={row['oracle_mm']:.3f}mm "
                  f"shift={row['shift_mm']:.3f} pi_mrcs={row['mrcs_pi']:.3f}", flush=True)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.csv")
    if rows:
        with open(path, "w", newline="") as fh:
            wtr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            wtr.writeheader()
            wtr.writerows(rows)
    return {"sequence": name, "n_rows": len(rows), "skips": skips, "csv": path}


# ------------------------- verdict (pre-registered, see the .md) ----------------------
G1_RES_RATIO = 0.25     # apparatus: resolution must be <=25% of the effect it must resolve
G1_MIN_SEQ = 5
G2_CTL_INFORMATIVE = 0.20   # negative control's informative-frame rate must stay below this
G4_INFORMATIVE = 0.20   # signal existence: informative-frame rate per sequence
G4_MIN_SEQ = 4
MAIN_PI = 0.50
MAIN_MIN_SEQ = 4
FAIL_PI = 0.20
FAIL_MIN_SEQ = 5


def _agg(path):
    R = [{k: (v if k == "stem" else float(v)) for k, v in r.items()}
         for r in csv.DictReader(open(path))]
    if not R:
        return None
    # A frame is INFORMATIVE when the oracle's move clears both the apparatus resolution
    # and the shift null on that same frame. Frames that are not informative carry no
    # evidence either way -- their count is itself the answer to "is there anything here".
    #
    # A frame whose shift draws all failed (p1.shifted_masks cannot place an equal-area
    # rectangle that stays in frame) has NO null, so it cannot be judged either way. Those
    # are UNUSABLE, not "not informative": leaving them in the denominator would quietly
    # push the rate toward the NEGATIVE branch. They are excluded and counted, and the
    # uncorrected rate is reported beside the corrected one so the choice is auditable.
    usable = [r for r in R if np.isfinite(r["shift_max_mm"]) and np.isfinite(r["resolution_mm"])]
    inf = [r for r in usable if np.isfinite(r["oracle_mm"])
           and r["oracle_mm"] > max(r["resolution_mm"], r["shift_max_mm"])]
    out = {
        "n": len(R), "n_usable": len(usable), "n_unusable": len(R) - len(usable),
        "n_informative": len(inf),
        "frac_informative": len(inf) / len(usable) if usable else float("nan"),
        "frac_informative_all_frames": len(inf) / len(R),
        "med_area_frac": float(np.median([r["area_frac"] for r in R])),
        "med_resolution_mm": float(np.median([r["resolution_mm"] for r in R])),
        "med_oracle_mm": float(np.median([r["oracle_mm"] for r in R])),
        "med_shift_mm": float(np.nanmedian([r["shift_mm"] for r in R])),
        "med_robust_mm": float(np.nanmedian([r["robust_mm"] for r in R])),
        "med_mrcs_mm": float(np.nanmedian([r["mrcs_mm"] for r in R])),
    }
    for a in ("all", "robust", "oracle", "mrcs", "shift"):
        k = f"res_{a}_mm"
        out[f"med_{k}"] = (float(np.nanmedian([r[k] for r in R])) if k in R[0]
                           else float("nan"))
    for a in ("robust", "mrcs", "shift"):
        v = np.array([r[f"{a}_pi"] for r in inf], dtype=float) if inf else np.array([])
        v = v[np.isfinite(v)]
        out[f"pi_{a}"] = float(np.median(v)) if v.size else float("nan")
    return out


def verdict(root):
    per = {}
    for path in sorted(glob.glob(os.path.join(root, "*.csv"))):
        a = _agg(path)
        if a:
            per[os.path.splitext(os.path.basename(path))[0]] = a

    dyn = {k: v for k, v in per.items() if k != STATIC_CONTROL}
    ctl = per.get(STATIC_CONTROL)
    gate = []
    n1 = sum(v["med_resolution_mm"] <= G1_RES_RATIO * v["med_oracle_mm"]
             for v in dyn.values())
    if n1 < G1_MIN_SEQ:
        gate.append(f"G1 apparatus resolution is <={G1_RES_RATIO:.0%} of the oracle move on "
                    f"only {n1}/{len(dyn)} (need {G1_MIN_SEQ})")
    if ctl and ctl["frac_informative"] > G2_CTL_INFORMATIVE:
        gate.append(f"G2 negative control is informative on {ctl['frac_informative']:.0%} "
                    f"of frames (need <={G2_CTL_INFORMATIVE:.0%})")
    n4 = sum(v["frac_informative"] >= G4_INFORMATIVE for v in dyn.values())

    if gate:
        v_txt, why = "NO VERDICT (apparatus gate)", "; ".join(gate)
    elif n4 < G4_MIN_SEQ:
        v_txt = "NEGATIVE (no per-frame pose signal)"
        why = (f"the oracle's converged-pose move clears the shift null on >={G4_INFORMATIVE:.0%} "
               f"of frames in only {n4}/{len(dyn)} sequences: at Bonn's dynamic-area scale "
               f"(median {np.median([v['med_area_frac'] for v in dyn.values()]):.1%} of valid "
               f"pixels), removing the true dynamic pixels does not measurably move the "
               f"converged per-frame pose -- so the ATE gain is not produced there")
    else:
        n_pass = sum(v["pi_mrcs"] >= MAIN_PI for v in dyn.values()
                     if np.isfinite(v["pi_mrcs"]))
        n_fail = sum(v["pi_mrcs"] <= FAIL_PI for v in dyn.values()
                     if np.isfinite(v["pi_mrcs"]))
        # A PASS is a positive claim about mrcs, so mrcs's OWN move must be reproducible;
        # a FAIL/NEGATIVE needs no such guard (registered before the run, prereg §6).
        n_repro = sum(v["med_res_mrcs_mm"] <= G1_RES_RATIO * v["med_mrcs_mm"]
                      for v in dyn.values() if np.isfinite(v["med_res_mrcs_mm"]))
        if n_pass >= MAIN_MIN_SEQ and n_repro < MAIN_MIN_SEQ:
            v_txt = "NO VERDICT (apparatus gate)"
            why = (f"pi_mrcs would pass on {n_pass}/{len(dyn)} but mrcs's own converged move "
                   f"is reproducible on only {n_repro}/{len(dyn)}")
        elif n_pass >= MAIN_MIN_SEQ:
            v_txt, why = "PASS", f"pi_mrcs >= {MAIN_PI} on {n_pass}/{len(dyn)}"
        elif n_fail >= FAIL_MIN_SEQ:
            v_txt, why = "FAIL", f"pi_mrcs <= {FAIL_PI} on {n_fail}/{len(dyn)}"
        else:
            v_txt, why = "INDETERMINATE", f"{n_pass} pass / {n_fail} fail"

    hdr = (f"{'sequence':38s} {'n':>5s} {'unus':>5s} {'area':>6s} {'res_mm':>7s} "
           f"{'orc_mm':>7s} {'shf_mm':>7s} {'rob_mm':>7s} {'inf%':>6s} | "
           f"{'pi_rob':>7s} {'pi_mrcs':>8s} {'pi_shf':>7s}")
    print(hdr + "\n" + "-" * len(hdr))
    for k, v in per.items():
        print(f"{k:38s} {v['n']:5d} {v['n_unusable']:5d} {v['med_area_frac']:6.3f} "
              f"{v['med_resolution_mm']:7.3f} "
              f"{v['med_oracle_mm']:7.3f} {v['med_shift_mm']:7.3f} {v['med_robust_mm']:7.3f} "
              f"{100 * v['frac_informative']:5.1f}% | {v['pi_robust']:7.3f} "
              f"{v['pi_mrcs']:8.3f} {v['pi_shift']:7.3f}")
    print("\nmm columns: ||converged pose of ARM - converged pose of `all`||, per frame, median.")
    print("unus = frames with no usable shift null (excluded from inf%; the rate over ALL "
          "frames is\n  in the json as frac_informative_all_frames).")
    print("res_mm = the same quantity between two independent starts of the SAME arm "
          "(the apparatus\n  resolution -- every effect must clear it).")
    print("pi_X = <u_X, u_oracle>/||u_oracle||^2 over informative frames: the fraction of the "
          "ORACLE's\n  pose correction that policy X reproduces. 1 = same move, 0 = none, "
          "<0 = opposite.")
    print(f"\nVERDICT: {v_txt}  --  {why}")
    blob = {"verdict": v_txt, "why": why, "sequences": per}
    with open(os.path.join(root, "p1c_verdict.json"), "w") as fh:
        json.dump(blob, fh, indent=2)
    return blob


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datasets-root", default="/data/Datasets/Bonn")
    ap.add_argument("--sequences", default="all")
    ap.add_argument("--out", default="results/evidence/p1c_recovery/real")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--verdict", default=None)
    args = ap.parse_args()
    if args.verdict:
        verdict(args.verdict)
        return
    import torch
    device = args.device if args.device != "auto" else (
        "cuda" if torch.cuda.is_available() else "cpu")
    seqs = ((DYN_SEQUENCES + [STATIC_CONTROL]) if args.sequences == "all"
            else args.sequences.split(","))
    info = []
    for s in seqs:
        sd = s if os.path.isdir(s) else os.path.join(args.datasets_root, s)
        if not os.path.isdir(sd):
            print(f"[skip] {s} missing")
            continue
        print(f"[run] {s} on {device}", flush=True)
        info.append(process(sd, args.out, device, max_frames=args.max_frames))
        print(f"[done] {info[-1]}", flush=True)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump({"arms": ARMS, "gn_steps": GN_STEPS, "n_start": N_START,
                   "eps_mm": EPS_MM, "n_shift": N_SHIFT,
                   "preregistration": "results/evidence/p1c_recovery_preregistration.md",
                   "runs": info}, fh, indent=2)
    verdict(args.out)


if __name__ == "__main__":
    main()
