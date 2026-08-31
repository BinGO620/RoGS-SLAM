#!/usr/bin/env python3
"""P1 POST-HOC diagnostic: is the dynamic region's observability edge just TEXTURE?

**This is a post-hoc diagnostic, declared as such. It cannot overturn the P1 FAIL
verdict (`results/evidence/p1_observability_verdict.md`); it can only tell us WHY the
(small but 7/7 consistent) excess exists, and it is designed so that its likely outcome
WEAKENS our reading rather than rescuing it.**

P1 established: removing the true dynamic region costs 1.6-3.2x the lambda_min a
same-area same-shape blob elsewhere costs, and depth-matching the null changes nothing.
Two explanations survive:

  (a) TEXTURE ARTIFACT -- `dynamic_mask_gtmc` is built from observed-vs-ego motion
      disagreement, and motion is unobservable on textureless surfaces, so the mask is
      structurally biased toward high-gradient pixels. Removing high-gradient pixels
      costs more information for reasons that have nothing to do with dynamics.
  (b) GEOMETRY -- where the mover sits is genuinely special in the pose-information
      geometry.

Two independent controls for texture, both reported:

  1. TEXTURE-MATCHED NULL (rejection sampling): accept only shifts whose masked
     texture mass sum(tr G) is within +-25% of the true mask's.
  2. COVARIATE ADJUSTMENT (all 32 draws, no rejection): regress each null draw's
     lambda_min loss on its texture mass, then compare the true mask's loss against
     the regression's prediction AT THE TRUE MASK'S TEXTURE MASS. Uses every draw, so
     it survives the frames where rejection sampling finds too few matches.

If both say "no excess left", (a) wins and the direction closes.

Usage:
  python scripts/p1_texture_matched_null.py --sequences rgbd_bonn_balloon,... \
      --out results/evidence/p1_observability/texture_diagnostic
"""

import argparse
import csv
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
    CALIB_BONN,
    DIST_BONN,
    frozen_mask_index,
    load_frozen_mask,
    undistort_depths,
    undistort_images,
)

TEX_TOL = 0.25          # texture-mass match tolerance (mirrors the depth arm's +-25%)
N_DRAW = 32


def run_sequence(seq_dir, out_dir, device, seed=0):
    import torch

    name = os.path.basename(seq_dir.rstrip("/"))
    mask_idx = frozen_mask_index(os.path.join(seq_dir, "dynamic_mask_gtmc"))
    frames = [f for f in load_tum_associations(seq_dir)
              if p1._stem(f["depth_path"]) in mask_idx]
    if len(frames) > p1.MAX_FRAMES:
        frames = [frames[i] for i in
                  np.linspace(0, len(frames) - 1, p1.MAX_FRAMES).astype(int)]
    calib = CALIB_BONN
    rows, n_tex_infeasible = [], 0
    for fi, f in enumerate(frames):
        stem = p1._stem(f["depth_path"])
        rng = np.random.default_rng(
            int(hashlib.sha256(f"tex|{name}|{stem}|{seed}".encode()).hexdigest()[:8], 16)
        )
        rgb = undistort_images(
            [np.asarray(Image.open(f["rgb_path"]).convert("RGB"))], calib=calib, dist=DIST_BONN
        )[0]
        d = np.asarray(Image.open(f["depth_path"])).astype(np.float32) / float(calib["depth_scale"])
        depth = undistort_depths([d], calib=calib, dist=DIST_BONN)[0]
        mask = load_frozen_mask(mask_idx[stem])
        if mask.shape != depth.shape:
            continue
        J, G, jd, valid = p1.per_pixel_terms(depth, rgb, calib, device)
        valid_np = valid.detach().cpu().numpy()
        gt_sel = mask & valid_np
        n_rm = int(gt_sel.sum())
        if n_rm < p1.MIN_REMOVED:
            continue
        # texture mass = sum of tr(G) = sum |grad I|^2 over the removed valid pixels
        trG = (G[..., 0, 0] + G[..., 1, 1]).detach().cpu().numpy()
        tex_gt = float(trG[gt_sel].sum())

        H_all = p1.hessian_of(J, G, jd, valid)
        lam_all, _ = p1.spectrum(H_all)

        def lam_of(m_np):
            sel = torch.as_tensor(m_np, device=device) & valid
            return p1.spectrum(H_all - p1.hessian_of(J, G, jd, sel))[0]

        lam_gt = lam_of(gt_sel)

        # --- arm 1: texture-matched rejection sampling -----------------------------
        ys, xs = np.nonzero(mask)
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        h, w = mask.shape
        dy_lo, dy_hi, dx_lo, dx_hi = -int(y0), int(h - 1 - y1), -int(x0), int(w - 1 - x1)
        tex_draws, plain_draws, tries = [], [], 0
        while tries < 400 and (len(plain_draws) < N_DRAW or len(tex_draws) < N_DRAW):
            tries += 1
            dy = int(rng.integers(dy_lo, dy_hi + 1)) if dy_hi >= dy_lo else 0
            dx = int(rng.integers(dx_lo, dx_hi + 1)) if dx_hi >= dx_lo else 0
            if dy == 0 and dx == 0:
                continue
            m = np.zeros_like(mask)
            m[ys + dy, xs + dx] = True
            sel = m & valid_np
            c = int(sel.sum())
            if abs(c - n_rm) > p1.COUNT_TOL * max(n_rm, 1):
                continue
            tex = float(trG[sel].sum())
            lam = lam_of(sel)
            if len(plain_draws) < N_DRAW:
                plain_draws.append((tex, lam))
            if abs(tex - tex_gt) <= TEX_TOL * max(tex_gt, 1e-12) and len(tex_draws) < N_DRAW:
                tex_draws.append((tex, lam))
        if len(plain_draws) < p1.MIN_NULL:
            continue
        if len(tex_draws) < p1.MIN_NULL:
            n_tex_infeasible += 1

        lam_plain = np.array([l for _t, l in plain_draws], dtype=float)
        tex_plain = np.array([t for t, _l in plain_draws], dtype=float)
        lam_tex = np.array([l for _t, l in tex_draws], dtype=float)

        # --- arm 2: covariate adjustment (uses ALL plain draws, no rejection) -------
        # loss_i = 1 - lam_i/lam_all  regressed on texture mass; predict at tex_gt.
        loss_plain = 1.0 - lam_plain / max(lam_all, 1e-30)
        loss_gt = 1.0 - lam_gt / max(lam_all, 1e-30)
        pred, resid_sd = float("nan"), float("nan")
        if np.ptp(tex_plain) > 0 and lam_plain.size >= 8:
            b, a = np.polyfit(tex_plain, loss_plain, 1)
            pred = float(a + b * tex_gt)
            resid_sd = float(np.std(loss_plain - (a + b * tex_plain), ddof=2))

        rows.append({
            "frame": fi, "stem": stem, "n_removed": n_rm,
            "tex_gt": tex_gt, "tex_null_med": float(np.median(tex_plain)),
            "tex_ratio": tex_gt / max(float(np.median(tex_plain)), 1e-30),
            "lam_all": lam_all, "lam_gt": lam_gt,
            "n_plain": int(lam_plain.size), "n_tex": int(lam_tex.size),
            "lam_plain_med": float(np.median(lam_plain)),
            "lam_plain_q05": float(np.quantile(lam_plain, 0.05)),
            "lam_tex_med": float(np.median(lam_tex)) if lam_tex.size else float("nan"),
            "lam_tex_q05": (float(np.quantile(lam_tex, 0.05))
                            if lam_tex.size >= p1.MIN_NULL else float("nan")),
            "loss_gt": loss_gt, "loss_pred_at_tex_gt": pred, "loss_resid_sd": resid_sd,
        })
        if fi % 100 == 0:
            print(f"  [{name}] {fi}/{len(frames)} texratio={rows[-1]['tex_ratio']:.2f} "
                  f"n_tex={len(tex_draws)}", flush=True)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.csv")
    if rows:
        with open(path, "w", newline="") as fh:
            wtr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            wtr.writeheader()
            wtr.writerows(rows)
    return {"sequence": name, "n_rows": len(rows),
            "n_tex_infeasible": n_tex_infeasible, "csv": path}


def summarise(path):
    R = [{k: (v if k == "stem" else float(v)) for k, v in r.items()}
         for r in csv.DictReader(open(path))]
    lg = np.array([r["lam_gt"] for r in R])
    lp = np.array([r["lam_plain_med"] for r in R])
    lpq = np.array([r["lam_plain_q05"] for r in R])
    lt = np.array([r["lam_tex_med"] for r in R])
    ltq = np.array([r["lam_tex_q05"] for r in R])
    tr = np.array([r["tex_ratio"] for r in R])
    lo = np.array([r["loss_gt"] for r in R])
    pr = np.array([r["loss_pred_at_tex_gt"] for r in R])
    sd = np.array([r["loss_resid_sd"] for r in R])
    ok = np.isfinite(lg) & np.isfinite(lp) & (lp > 0)
    tok = ok & np.isfinite(lt) & (lt > 0) & np.isfinite(ltq)
    rok = ok & np.isfinite(pr) & np.isfinite(sd) & (sd > 0)
    return {
        "n": int(ok.sum()),
        "tex_ratio_med": float(np.median(tr[ok])),
        "rho_plain": float(np.median(lg[ok] / lp[ok])),
        "frac_ex_plain": float(np.mean(lg[ok] < lpq[ok])),
        "n_texmatched": int(tok.sum()),
        "rho_tex": float(np.median(lg[tok] / lt[tok])) if tok.any() else float("nan"),
        "frac_ex_tex": float(np.mean(lg[tok] < ltq[tok])) if tok.any() else float("nan"),
        "loss_gt_med": float(np.median(lo[rok])) if rok.any() else float("nan"),
        "loss_pred_med": float(np.median(pr[rok])) if rok.any() else float("nan"),
        "excess_over_reg_med": float(np.median(lo[rok] - pr[rok])) if rok.any() else float("nan"),
        "frac_reg_excess_2sd": (float(np.mean((lo[rok] - pr[rok]) > 2 * sd[rok]))
                                if rok.any() else float("nan")),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datasets-root", default="/data/Datasets/Bonn")
    ap.add_argument("--sequences", default=",".join(p1.SEQUENCES))
    ap.add_argument("--out", default="results/evidence/p1_observability/texture_diagnostic")
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()

    import torch
    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    info = []
    for s in args.sequences.split(","):
        sd = s if os.path.isdir(s) else os.path.join(args.datasets_root, s)
        if not os.path.isdir(sd):
            continue
        print(f"[run] {s}", flush=True)
        info.append(run_sequence(sd, args.out, device))
        print(f"[done] {info[-1]}", flush=True)

    hdr = (f"{'sequence':38s} {'n':>5s} {'texGT/null':>10s} {'rho_plain':>9s} "
           f"{'frac_plain':>10s} {'n_tex':>6s} {'rho_TEX':>8s} {'frac_TEX':>9s} "
           f"{'loss_gt':>8s} {'loss_pred':>9s} {'excess':>8s} {'fr>2sd':>7s}")
    print("\n" + hdr)
    print("-" * len(hdr))
    out = {}
    for i in info:
        if not i["n_rows"]:
            continue
        s = summarise(i["csv"])
        out[i["sequence"]] = s
        print(f"{i['sequence']:38s} {s['n']:5d} {s['tex_ratio_med']:10.2f} "
              f"{s['rho_plain']:9.3f} {s['frac_ex_plain']:10.3f} {s['n_texmatched']:6d} "
              f"{s['rho_tex']:8.3f} {s['frac_ex_tex']:9.3f} {100*s['loss_gt_med']:8.2f} "
              f"{100*s['loss_pred_med']:9.2f} {100*s['excess_over_reg_med']:8.2f} "
              f"{s['frac_reg_excess_2sd']:7.3f}")
    with open(os.path.join(args.out, "texture_diagnostic.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    print("\nread: rho_TEX -> 1.0 and frac_TEX -> 0.05 means TEXTURE explains the P1 excess;")
    print("      excess (loss_gt - regression prediction at the true texture mass) -> 0 says the same.")


if __name__ == "__main__":
    main()
