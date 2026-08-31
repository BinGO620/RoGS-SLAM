#!/usr/bin/env python3
"""M2 anchor-probe verdict — Design B's make-or-break gate (exp32, 2026-08-20).

PRE-REGISTERED CRITERION (NEXT_SESSION_PROMPT §3.1 / REVIEW §7.5, fixed BEFORE the
anchor columns were read; only the ATE column was seen first, to confirm the campaign
caught a collapse at all):

    In the window f360-f385, `anchor_frac_s90` OR `anchor_ratio_s90` changes by >= 15%,
    AND no equal-length sliding window inside the first 350 frames of the same sequence
    reaches the same amplitude. 2 of 3 seeds must satisfy it, and at least one seed must
    actually have collapsed (otherwise there is nothing to have predicted).

"Change amplitude" is the START-vs-END LEVEL SHIFT, because that is what the reference
quantity is: `flow_valid_frac` in f368-380 went 0.54 -> 0.43, i.e. -20%. Concretely,
for a window of length L, with a third of it at each end:

    amp(W) = | med(x[last L/3]) - med(x[first L/3]) | / | med(x[first L/3]) |

Medians, not means, so one blown frame cannot manufacture a knee.

The within-window PEAK-TO-TROUGH RANGE is also printed, clearly marked SECONDARY. It is
descriptive only: promoting it to the verdict after seeing that the shift failed would
be exactly the HARKing this project pre-registers against.

Collapse threshold: full-trajectory `ate_rmse_cm` >= 10. f3_st_hf is bistable with modes
at ~2-3 cm and ~30-36 cm (exp25/exp26/P9), so 10 cm separates them with an order of
magnitude of headroom on both sides.

Usage:
    python scripts/m2_anchor_verdict.py --root results/runs/M2/M2-ANCHOR-2060
"""

import argparse
import csv
import glob
import json
import os
import statistics as st

WIN_LO, WIN_HI = 360, 385          # inclusive, pre-registered around the P9 collapse f371
NULL_MAX_FRAME = 350               # null windows must lie entirely below this frame
AMP_THRESH = 0.15                  # 15%
COLLAPSE_ATE_CM = 10.0
VARS = ("anchor_frac_s90", "anchor_ratio_s90")
REFERENCE = "flow_valid_frac"      # the -20% yardstick the threshold was calibrated on


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None      # NaN -> None


def load_frames(run_dir):
    hits = glob.glob(os.path.join(run_dir, "**", "reliability_signal", "frames.csv"),
                     recursive=True)
    if not hits:
        return None
    with open(sorted(hits)[0], newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {int(r["frame"]): r for r in rows}


def series(frames, key, lo, hi):
    """(frame, value) pairs in [lo, hi], missing/NaN dropped."""
    out = []
    for i in range(lo, hi + 1):
        r = frames.get(i)
        if r is None:
            continue
        v = _f(r.get(key))
        if v is not None:
            out.append((i, v))
    return out


def amplitude(vals):
    """Start-vs-end level shift, as a fraction of the start level. None if unusable."""
    n = len(vals)
    if n < 6:
        return None
    k = max(2, n // 3)
    a = st.median(v for _, v in vals[:k])
    b = st.median(v for _, v in vals[-k:])
    if a == 0:
        return None
    return abs(b - a) / abs(a)


def window_range(vals):
    """SECONDARY, descriptive only: peak-to-trough over the window, relative to median."""
    if not vals:
        return None
    v = [x for _, x in vals]
    m = st.median(v)
    return (max(v) - min(v)) / abs(m) if m else None


def null_max(frames, key, length):
    """Largest amplitude over every equal-length window ending below NULL_MAX_FRAME."""
    best, best_at = 0.0, None
    lo = min(frames)
    while lo + length - 1 < NULL_MAX_FRAME:
        vals = series(frames, key, lo, lo + length - 1)
        amp = amplitude(vals)
        if amp is not None and amp > best:
            best, best_at = amp, lo
        lo += 1
    return best, best_at


def ate_of(run_dir):
    p = os.path.join(run_dir, "tables", "tracking_raw.csv")
    if not os.path.isfile(p):
        return None
    with open(p, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return _f(rows[0]["ate_rmse_cm"]) if rows else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results/runs/M2/M2-ANCHOR-2060")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    runs = sorted(d for d in glob.glob(os.path.join(args.root, "*")) if os.path.isdir(d))
    length = WIN_HI - WIN_LO + 1
    report = {"window": [WIN_LO, WIN_HI], "amp_thresh": AMP_THRESH,
              "collapse_ate_cm": COLLAPSE_ATE_CM, "runs": []}

    print(f"M2 anchor verdict | window f{WIN_LO}-f{WIN_HI} (L={length}) | "
          f"amp>={AMP_THRESH:.0%} | null windows end < f{NULL_MAX_FRAME}")
    for run in runs:
        frames = load_frames(run)
        if frames is None:
            continue
        ate = ate_of(run)
        collapsed = ate is not None and ate >= COLLAPSE_ATE_CM
        entry = {"run": os.path.basename(run), "ate_rmse_cm": ate,
                 "collapsed": collapsed, "frames": len(frames), "vars": {}}
        print(f"\n=== {os.path.basename(run)} | ATE {ate:.2f} cm | "
              f"collapse={'YES' if collapsed else 'no'} | frames={len(frames)}")
        for key in VARS + (REFERENCE,):
            vals = series(frames, key, WIN_LO, WIN_HI)
            amp = amplitude(vals)
            rng = window_range(vals)
            nmax, nat = null_max(frames, key, length)
            ok = (amp is not None and amp >= AMP_THRESH and nmax < AMP_THRESH)
            tag = "REF " if key == REFERENCE else ("PASS" if ok else "fail")
            lo_lvl = st.median(v for _, v in vals[:max(2, len(vals) // 3)]) if vals else float("nan")
            hi_lvl = st.median(v for _, v in vals[-max(2, len(vals) // 3):]) if vals else float("nan")
            print(f"  [{tag}] {key:<18} {lo_lvl:8.4f} -> {hi_lvl:8.4f}  "
                  f"amp={amp if amp is None else round(amp, 4)}  "
                  f"null_max={nmax:.4f}@f{nat}  (secondary range={rng if rng is None else round(rng, 4)})")
            entry["vars"][key] = {"level_start": lo_lvl, "level_end": hi_lvl, "amp": amp,
                                  "null_max": nmax, "null_at": nat, "range": rng,
                                  "pass": bool(ok)}
        entry["pass"] = any(entry["vars"][k]["pass"] for k in VARS)
        print(f"  --> seed verdict: {'PASS' if entry['pass'] else 'FAIL'}")
        report["runs"].append(entry)

    n_pass = sum(1 for r in report["runs"] if r["pass"])
    any_collapse = any(r["collapsed"] for r in report["runs"])
    verdict = "PASS" if (n_pass >= 2 and any_collapse) else "FAIL"
    report["n_pass"] = n_pass
    report["any_collapse"] = any_collapse
    report["verdict"] = verdict
    print(f"\n==== M2 VERDICT: {verdict} ====")
    print(f"seeds passing = {n_pass}/{len(report['runs'])} (need >= 2); "
          f"a seed collapsed = {any_collapse} (needed)")
    print("PASS -> M3 (anchor-triggered keyframe, 48 run). FAIL -> Design B judged negative, M3 not run.")

    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
