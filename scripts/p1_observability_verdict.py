#!/usr/bin/env python3
"""P1 verdict: apply the PRE-REGISTERED decision rule to the offline observability rows.

The rule is fixed in ``results/evidence/p1_observability_preregistration.md`` (committed
before ``scripts/p1_observability_offline.py`` produced a number). This file only
executes it -- it must not contain a threshold that is not in that document.

Order of operations (also pre-registered):
  0. INVALIDATION CONTROL first. The ``ctrl`` arm is one more draw from the null's own
     distribution, so it must look like the null: ``frac_excess <= 0.10`` and
     ``med_rho in [0.85, 1.18]``. If it does not, the null construction is broken and
     NO verdict is issued (we do not get to re-read the main arm instead).
  1. PRIMARY (lambda_min):   PASS needs >=4/7 sequences with frac_excess >= 0.20 AND
     med_rho <= 0.67.  FAIL needs >=5/7 with frac_excess <= 0.10, or >=5/7 with
     med_rho >= 0.90.  Otherwise INDETERMINATE.
  2. PARAMETERISATION CROSS-CHECK (logdet, invariant to pose reparameterisation):
     if lambda_min PASSes but logdet frac_excess < 0.10, downgrade to INDETERMINATE.
  3. DEPTH-MATCHED null: reported, never gating. If the effect dies under depth
     matching the conclusion must be written as "proximity is the whole story".

Usage:
  python scripts/p1_observability_verdict.py --root results/evidence/p1_observability
"""

import argparse
import csv
import glob
import json
import os

import numpy as np

# ---- every constant below is quoted from the pre-registration, not chosen here ----
FRAC_PASS = 0.20        # frequency gate (4x the 0.05 chance rate)
FRAC_DEAD = 0.10        # frequency "dead" level
RHO_PASS = 0.67         # effect-size gate
RHO_DEAD = 0.90         # effect present but immaterial
N_PASS = 4              # of 7 sequences
N_DEAD = 5              # of 7 sequences
CTRL_FRAC_MAX = 0.10
CTRL_RHO_LO, CTRL_RHO_HI = 0.85, 1.18
LD_CROSSCHECK_MIN = 0.10


def _rows(path):
    with open(path) as fh:
        return [
            {k: (v if k == "stem" else float(v)) for k, v in r.items()}
            for r in csv.DictReader(fh)
        ]


def summarise(rows):
    lam_gt = np.array([r["lam_gt"] for r in rows])
    lam_med = np.array([r["lam_null_med"] for r in rows])
    lam_q05 = np.array([r["lam_null_q05"] for r in rows])
    lam_ctrl = np.array([r["lam_ctrl"] for r in rows])
    ld_gt = np.array([r["logdet_gt"] for r in rows])
    ld_med = np.array([r["logdet_null_med"] for r in rows])
    ld_q05 = np.array([r["logdet_null_q05"] for r in rows])
    ld_ctrl = np.array([r["logdet_ctrl"] for r in rows])
    lam_dm = np.array([r["lam_dmatch_med"] for r in rows])
    lam_dm_q05 = np.array([r["lam_dmatch_q05"] for r in rows])
    ok = np.isfinite(lam_gt) & np.isfinite(lam_med) & (lam_med > 0)
    dm_ok = ok & np.isfinite(lam_dm) & (lam_dm > 0) & np.isfinite(lam_dm_q05)
    ld_ok = ok & np.isfinite(ld_gt) & np.isfinite(ld_med)
    out = {
        "n_frames": int(ok.sum()),
        # PRIMARY -- lambda_min
        "frac_excess": float(np.mean(lam_gt[ok] < lam_q05[ok])),
        "med_rho": float(np.median(lam_gt[ok] / lam_med[ok])),
        "p10_rho": float(np.quantile(lam_gt[ok] / lam_med[ok], 0.10)),
        # INVALIDATION CONTROL -- one more draw from the null's own distribution
        "ctrl_frac_excess": float(np.mean(lam_ctrl[ok] < lam_q05[ok])),
        "ctrl_med_rho": float(np.median(lam_ctrl[ok] / lam_med[ok])),
        # CROSS-CHECK -- logdet (parameterisation invariant)
        "ld_frac_excess": float(np.mean(ld_gt[ld_ok] < ld_q05[ld_ok])) if ld_ok.any() else float("nan"),
        "ld_med_excess": float(np.median(ld_gt[ld_ok] - ld_med[ld_ok])) if ld_ok.any() else float("nan"),
        "ld_ctrl_frac_excess": float(np.mean(ld_ctrl[ld_ok] < ld_q05[ld_ok])) if ld_ok.any() else float("nan"),
        # ROBUSTNESS -- depth-matched null (never gating)
        "dm_n_frames": int(dm_ok.sum()),
        "dm_frac_excess": float(np.mean(lam_gt[dm_ok] < lam_dm_q05[dm_ok])) if dm_ok.any() else float("nan"),
        "dm_med_rho": float(np.median(lam_gt[dm_ok] / lam_dm[dm_ok])) if dm_ok.any() else float("nan"),
        # descriptive
        "med_removed_frac": float(np.median([r["removed_frac"] for r in rows])),
        "med_overlap": float(np.median([r["overlap_med"] for r in rows])),
        "med_depth_masked": float(np.nanmedian([r["depth_med_masked"] for r in rows])),
    }
    out["pass_seq"] = bool(
        out["frac_excess"] >= FRAC_PASS and out["med_rho"] <= RHO_PASS
    )
    out["dead_frac"] = bool(out["frac_excess"] <= FRAC_DEAD)
    out["dead_rho"] = bool(out["med_rho"] >= RHO_DEAD)
    out["ctrl_ok"] = bool(
        out["ctrl_frac_excess"] <= CTRL_FRAC_MAX
        and CTRL_RHO_LO <= out["ctrl_med_rho"] <= CTRL_RHO_HI
    )
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="results/evidence/p1_observability")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    per_seq = {}
    for path in sorted(glob.glob(os.path.join(args.root, "*.csv"))):
        rows = _rows(path)
        if not rows:
            continue
        per_seq[os.path.splitext(os.path.basename(path))[0]] = summarise(rows)
    if not per_seq:
        raise SystemExit(f"no rows under {args.root}")

    bad_ctrl = [k for k, v in per_seq.items() if not v["ctrl_ok"]]
    n_pass = sum(v["pass_seq"] for v in per_seq.values())
    n_dead = sum(v["dead_frac"] or v["dead_rho"] for v in per_seq.values())
    n_dead_frac = sum(v["dead_frac"] for v in per_seq.values())
    n_dead_rho = sum(v["dead_rho"] for v in per_seq.values())

    if bad_ctrl:
        verdict = "INVALID"
        why = (f"invalidation control failed on {len(bad_ctrl)}/{len(per_seq)} "
               f"sequences ({', '.join(bad_ctrl)}) -> null construction is broken; "
               f"no verdict is issued")
    elif n_pass >= N_PASS:
        verdict, why = "PASS", f"{n_pass}/{len(per_seq)} sequences pass both gates"
        ld = np.array([v["ld_frac_excess"] for v in per_seq.values()], dtype=float)
        if np.nanmedian(ld) < LD_CROSSCHECK_MIN:
            verdict = "INDETERMINATE"
            why = (f"lambda_min passes ({n_pass}/{len(per_seq)}) but the "
                   f"parameterisation-invariant logdet cross-check does not "
                   f"(median frac_excess {np.nanmedian(ld):.3f} < {LD_CROSSCHECK_MIN}) "
                   f"-> conclusion is sensitive to the pose parameterisation")
    elif n_dead_frac >= N_DEAD or n_dead_rho >= N_DEAD:
        verdict = "FAIL"
        why = (f"{n_dead_frac}/{len(per_seq)} sequences at/below chance frequency, "
               f"{n_dead_rho}/{len(per_seq)} with immaterial effect size")
    else:
        verdict = "INDETERMINATE"
        why = (f"{n_pass}/{len(per_seq)} pass both gates (need {N_PASS}); "
               f"{n_dead}/{len(per_seq)} meet a dead condition (need {N_DEAD})")

    hdr = (f"{'sequence':40s} {'n':>5s} {'frac_ex':>8s} {'med_rho':>8s} {'p10_rho':>8s} "
           f"{'ctrl_fr':>8s} {'ctrl_rho':>9s} {'ld_frac':>8s} {'dm_frac':>8s} "
           f"{'dm_rho':>8s} {'rm%':>6s} {'gate':>6s}")
    print(hdr)
    print("-" * len(hdr))
    for k, v in per_seq.items():
        print(f"{k:40s} {v['n_frames']:5d} {v['frac_excess']:8.3f} {v['med_rho']:8.3f} "
              f"{v['p10_rho']:8.3f} {v['ctrl_frac_excess']:8.3f} {v['ctrl_med_rho']:9.3f} "
              f"{v['ld_frac_excess']:8.3f} {v['dm_frac_excess']:8.3f} "
              f"{v['dm_med_rho']:8.3f} {100 * v['med_removed_frac']:6.1f} "
              f"{'PASS' if v['pass_seq'] else ('dead' if (v['dead_frac'] or v['dead_rho']) else '--'):>6s}")
    print()
    print(f"VERDICT: {verdict}  --  {why}")
    print(f"gates (pre-registered): pass = frac_excess>={FRAC_PASS} AND med_rho<={RHO_PASS} "
          f"on >={N_PASS}/7;  fail = frac_excess<={FRAC_DEAD} or med_rho>={RHO_DEAD} on >={N_DEAD}/7")

    blob = {"verdict": verdict, "why": why, "n_pass": n_pass, "n_dead": n_dead,
            "gates": {"FRAC_PASS": FRAC_PASS, "RHO_PASS": RHO_PASS,
                      "FRAC_DEAD": FRAC_DEAD, "RHO_DEAD": RHO_DEAD,
                      "N_PASS": N_PASS, "N_DEAD": N_DEAD},
            "sequences": per_seq}
    out = args.json_out or os.path.join(args.root, "p1_verdict.json")
    with open(out, "w") as fh:
        json.dump(blob, fh, indent=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
