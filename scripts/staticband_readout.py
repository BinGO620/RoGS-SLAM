#!/usr/bin/env python3
"""Static-band rendering readout for balloon (exp36) -- tests exp35's PSNR-bias hypothesis.

exp35 measured, on balloon, FULL-FRAME PSNR maskfree 19.58 > eboth 17.31 (+2.27 dB) while
SSIM went the other way, and proposed a testable explanation: full-frame PSNR REWARDS
baking the moving person into the map, because on pixels where the GT frame shows a person
a ghost scores better than a hole. That was a hypothesis with two suggested tests; this is
the second one -- re-score on the static band only:

    M_static = (gt depth valid) AND NOT(frozen GTMC dynamic mask)

method-independent, identical support for every arm (utils/eval_utils.py::
eval_static_background_raw, run via scripts/eval_vacated_posthoc.py).

READING RULES (inherited from exp35's rendering readout, which was explicitly descriptive):
  * direction only, never magnitude: the decomposability gate failed 12/12 on the
    full-frame rendering metrics, and nothing here re-earns it;
  * the hypothesis predicts the INVERSION vanishes or flips on the static band. That is a
    sign test over seeds, reported as k/3;
  * ghost_excess_psnr_db (vacated region minus that frame's own untouched background) is
    the column closest to the mechanism -- it is a WITHIN-frame contrast, so it does not
    inherit the global map/pose-quality confound the absolute numbers carry.

APPLICABILITY: only balloon and pt1 have frozen GTMC masks (440 / 582); f3_wk_xyz has 0,
so this whole readout is unavailable on the TUM sequence.
FAITHFULNESS ANCHOR MISSING: these runs were --fast, so no in-run band_metrics.json exists
to align against (band_check is null). Every arm goes through the SAME posthoc path, so
cross-arm comparison is one caliper; "aligned with the online eval to within 0.05 dB" is
NOT claimed for this batch (nor for exp35's 39-run full-frame batch).

Usage: python scripts/staticband_readout.py
"""

import glob
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

# arm -> (root, run-dir glob). Roots are pinned so full-frame and static-band come from the
# SAME physical run for every arm (exp36 found they did not for eboth).
ARMS = {
    "A_eboth":      "results/runs/PBA/eboth_balloon_seed{seed}",
    "B_insoff":     "results/runs/PBA/pba_tracking_only_balloon_seed{seed}",
    "C_mapoff":     "results/runs/PBA/pba_mapping_off_balloon*seed{seed}",
    "E_trackside":  "results/runs/PBA/pba_trackside_only_balloon_seed{seed}",
    "D_maskfree":   "results/runs/T2/T2-QUOTA-3090/control_maskfree_balloon_seed{seed}",
}
SEEDS = (0, 1, 2)


def _load(pattern, leaf, key_path):
    """Newest timestamped dir's <leaf>/<file>, walked by key_path."""
    hits = []
    for outer in sorted(glob.glob(pattern)):
        hits += sorted(glob.glob(os.path.join(outer, "**", leaf), recursive=True))
    if not hits:
        return None
    with open(hits[-1]) as fh:
        d = json.load(fh)
    for k in key_path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def collect():
    rows = {}
    for arm, pat in ARMS.items():
        rows[arm] = {}
        for seed in SEEDS:
            p = pat.format(seed=seed)
            rows[arm][seed] = {
                "ff_psnr": _load(p, "posthoc_fullframe/fullframe_summary.json",
                                 ("fullframe", "psnr")),
                "ff_ssim": _load(p, "posthoc_fullframe/fullframe_summary.json",
                                 ("fullframe", "ssim")),
                "sb_psnr": _load(p, "posthoc_staticband/posthoc_summary.json",
                                 ("static", "psnr")),
                "sb_depth": _load(p, "posthoc_staticband/posthoc_summary.json",
                                  ("static", "depth_l1_pen_cm")),
                "ghost_psnr_db": _load(p, "posthoc_staticband/posthoc_summary.json",
                                       ("ghost_excess", "psnr_db")),
                "freshvac_ghost_db": _load(p, "posthoc_staticband/posthoc_summary.json",
                                           ("freshvac", "ghost_excess_psnr_db")),
                "sb_frames": _load(p, "posthoc_staticband/posthoc_summary.json",
                                   ("static", "frames_scored")),
                "n_gauss": _load(p, "posthoc_staticband/posthoc_summary.json",
                                 ("n_gaussians",)),
                "vac_support": _load(p, "posthoc_staticband/posthoc_summary.json",
                                     ("vacated", "support_px_mean")),
            }
    return rows


def _mean(rows, arm, key):
    vals = [rows[arm][s][key] for s in SEEDS
            if isinstance(rows[arm][s].get(key), (int, float))]
    return float(np.mean(vals)) if vals else None


def main():
    rows = collect()
    print("balloon rendering: full-frame vs static-band (mean over available seeds)\n")
    hdr = (f"{'arm':13s} {'ffPSNR':>8s} {'sbPSNR':>8s} {'ffSSIM':>8s} {'sbDepthL1':>10s} "
           f"{'ghostdB':>8s} {'freshdB':>8s} {'nGauss':>8s} {'n':>3s}")
    print(hdr + "\n" + "-" * len(hdr))
    for arm in ARMS:
        def f(k, w, p=2):
            v = _mean(rows, arm, k)
            return f"{v:{w}.{p}f}" if v is not None else f"{'--':>{w}s}"
        n = sum(1 for s in SEEDS if rows[arm][s]["sb_psnr"] is not None)
        print(f"{arm:13s} {f('ff_psnr',8)} {f('sb_psnr',8)} {f('ff_ssim',8,4)} "
              f"{f('sb_depth',10)} {f('ghost_psnr_db',8)} {f('freshvac_ghost_db',8)} "
              f"{f('n_gauss',8,0)} {n:>3d}")

    # ---- the test: does maskfree still beat eboth once dynamic pixels are excluded? ----
    print("\nexp35's inversion, arm by arm against eboth (paired per seed, direction only):")
    for arm in ("D_maskfree", "C_mapoff", "E_trackside", "B_insoff"):
        for label, key in (("full-frame PSNR", "ff_psnr"), ("static-band PSNR", "sb_psnr")):
            deltas = []
            for s in SEEDS:
                a, b = rows[arm][s][key], rows["A_eboth"][s][key]
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    deltas.append(a - b)
            if not deltas:
                continue
            higher = sum(1 for d in deltas if d > 0)
            print(f"  {arm:13s} {label:18s} delta vs eboth "
                  f"{[round(d, 2) for d in deltas]} -> higher than eboth in {higher}/{len(deltas)}")

    d_ff = _mean(rows, "D_maskfree", "ff_psnr")
    e_ff = _mean(rows, "A_eboth", "ff_psnr")
    d_sb = _mean(rows, "D_maskfree", "sb_psnr")
    e_sb = _mean(rows, "A_eboth", "sb_psnr")
    if None not in (d_ff, e_ff, d_sb, e_sb):
        print(f"\nmaskfree - eboth:  full-frame {d_ff - e_ff:+.2f} dB   "
              f"static-band {d_sb - e_sb:+.2f} dB")
        print("  hypothesis (exp35 §2): the full-frame advantage is created by the dynamic")
        print("  pixels, so it should shrink/flip on the static band. Direction only --")
        print("  the decomposability gate failed 12/12 on these rendering metrics.")

    out = "results/evidence/staticband_readout.json"
    with open(out, "w") as fh:
        json.dump({"balloon": rows}, fh, indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
