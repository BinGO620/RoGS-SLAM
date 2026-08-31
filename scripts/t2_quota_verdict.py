#!/usr/bin/env python3
"""T2 adaptive-quota verdict — mechanism self-evidence first, then ATE (exp32).

PRE-REGISTERED CRITERIA (NEXT_SESSION_PROMPT §3.2, fixed before any run started):

  1. MECHANISM SELF-EVIDENCE, ahead of every metric: `mad_excl_applied_frac >= 0.95`
     and `max_mad_zero_frac_after <= 0.45`; E-both additionally `mad_excl_semantic = 1`.
  2. MAIN: E-both (and Q-free) dynamic ATE against their own control.
  3. STATIC GUARDRAIL: no more than 5% ATE degradation on {f3_st_hf, f2_xyz}, and
     `mean_w` must not fall further.
  4. E-flow ~ control is EXPECTED and is not a negative verdict (not run this wave).

ONE CRITERION IS REPORTED IN TWO FORMS, and the reason is arithmetic, not taste.
`max_mad_zero_frac_after <= 0.45` cannot hold frame-wise as written: on a frame whose
zero mass ALREADY exceeds the cap, the closed form yields k <= 0, nothing is excluded,
and `zero_frac_after == zero_frac_before > 0.45` by definition. The invariant the
mechanism actually claims -- and the one pinned in tests/test_mad_exclusion.py before
this campaign ran -- is `after <= max(before, 0.45)`, i.e. the quota never PUSHES a
frame past the cap. So both are printed: the literal run-level number, and the
frame-level bound restricted to frames where the quota fired. The literal one is not
quietly replaced.

Same for `applied_frac >= 0.95`: frames that legitimately forbid exclusion
(`mad_excl_bind == "none"`) count against it, so the bind breakdown is printed next to
it and the shortfall is attributed rather than explained away.

TAU RATIO: prints median(mad_tau_after / mad_tau_before) over frames where the quota
fired. This is the pre-registered DEFINITION of the T2-scale arm's constant (REVIEW
§7.1) -- the arm is dispatched with the measured value.

Usage:
    python scripts/t2_quota_verdict.py --root results/runs/T2/T2-QUOTA-3090
"""

import argparse
import csv
import glob
import json
import os
import statistics as st

ARMS = ("control_maskfree", "control_maskon", "eflow", "eboth", "qfree", "scale")
PAIRS = {"eboth": "control_maskon", "qfree": "control_maskfree",
         "eflow": "control_maskfree", "scale": "control_maskon"}
DYNAMIC = ("balloon", "mv_no_box", "crowd2")
STATIC = ("f3_st_hf", "f2_xyz")
SEQS = DYNAMIC + STATIC
APPLIED_FRAC_MIN = 0.95
ZERO_FRAC_CAP = 0.45
STATIC_TOL = 0.05
# The quota lands EXACTLY on the cap when it binds, and the stats are float32: the
# measured `zero_frac_after` on such frames is 0.45000001788139343, i.e. 1.8e-08 over.
# float32 resolution at 0.45 is ~3e-08, so a tolerance below that reports the
# mechanism's own rounding as a violation. Measured, not guessed -- see the four
# balloon/qfree frames in the exp32 log.
FLOAT32_TOL = 1e-6


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def inner(run_dir):
    hits = glob.glob(os.path.join(run_dir, "datasets_*", "*", "seed_*", "*"))
    return sorted(hits)[-1] if hits else None


def load_run(run_dir):
    out = {"run": os.path.basename(run_dir)}
    p = os.path.join(run_dir, "tables", "tracking_raw.csv")
    if not os.path.isfile(p):
        return None
    with open(p, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return None
    out["ate"] = _f(rows[0]["ate_rmse_cm"])
    out["status"] = rows[0].get("status")
    ind = inner(run_dir)
    if ind:
        sp = os.path.join(ind, "reliability_signal", "summary.json")
        if os.path.isfile(sp):
            with open(sp, encoding="utf-8") as fh:
                out["summary"] = json.load(fh)
        fp = os.path.join(ind, "reliability_signal", "frames.csv")
        if os.path.isfile(fp):
            with open(fp, newline="") as fh:
                out["frames"] = list(csv.DictReader(fh))
    return out


def frame_stats(run):
    """Frame-level mechanism facts the run-level summary cannot express."""
    rows = run.get("frames") or []
    if not rows:
        return {}
    applied = [r for r in rows if int(r.get("mad_excl_applied", 0) or 0) == 1]
    ratios = []
    after_applied = []
    for r in applied:
        a, b = _f(r.get("mad_tau_after")), _f(r.get("mad_tau_before"))
        if a is not None and b not in (None, 0.0):
            ratios.append(a / b)
        za = _f(r.get("mad_zero_frac_after"))
        if za is not None:
            after_applied.append(za)
    viol = [r for r in rows
            if (_f(r.get("mad_zero_frac_after")) or 0) >
               max(_f(r.get("mad_zero_frac_before")) or 0, ZERO_FRAC_CAP) + FLOAT32_TOL]
    return {
        "n_frames": len(rows),
        "n_applied": len(applied),
        "tau_ratio_median": st.median(ratios) if ratios else None,
        "tau_ratio_p10": (sorted(ratios)[len(ratios) // 10] if len(ratios) >= 10 else None),
        "tau_ratio_p90": (sorted(ratios)[-max(1, len(ratios) // 10)] if len(ratios) >= 10 else None),
        "max_zero_after_applied": max(after_applied) if after_applied else None,
        "n_invariant_violations": len(viol),
        "semantic": max((int(r.get("mad_excl_semantic", 0) or 0) for r in rows), default=0),
        "tau_scale_declared": max((_f(r.get("tau_scale")) or 1.0 for r in rows), default=None),
        "mean_w": st.mean([_f(r.get("mean_w")) for r in rows
                           if _f(r.get("mean_w")) is not None]),
    }


def collect(root):
    data = {}
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.isdir(d):
            continue
        name = os.path.basename(d)
        arm = next((a for a in sorted(ARMS, key=len, reverse=True)
                    if name.startswith(a + "_")), None)
        if arm is None:
            continue
        rest = name[len(arm) + 1:]
        seq, _, seedtag = rest.rpartition("_seed")
        if seq not in SEQS:
            continue
        run = load_run(d)
        if run is None:
            continue
        run.update(frame_stats(run))
        data.setdefault((arm, seq), {})[int(seedtag)] = run
    return data


def mean_or_none(vals):
    vals = [v for v in vals if v is not None]
    return st.mean(vals) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results/runs/T2/T2-QUOTA-3090")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    data = collect(args.root)
    arms_present = sorted({a for a, _ in data}, key=lambda a: ARMS.index(a))

    print("=" * 100)
    print("T2 CRITERION 1 — MECHANISM SELF-EVIDENCE (read before any ATE)")
    print("=" * 100)
    print(f"{'arm/seq':<32}{'n':>3} {'applied_frac':>13} {'bind(none/quota/cand)':>24} "
          f"{'max_zero_after':>15} {'max_zero(applied)':>18} {'viol':>5} {'sem':>4} "
          f"{'tau_after/before':>17}")
    mech = {}
    for arm in arms_present:
        for seq in SEQS:
            runs = data.get((arm, seq))
            if not runs:
                continue
            sums = [r.get("summary", {}) for r in runs.values()]
            af = mean_or_none([s.get("mad_excl_applied_frac") for s in sums])
            mz = max([s.get("max_mad_zero_frac_after") for s in sums
                      if s.get("max_mad_zero_frac_after") is not None] or [None])
            binds = {"none": 0, "quota": 0, "candidates": 0, "min_keep": 0}
            for s in sums:
                for k, v in (s.get("mad_excl_bind_counts") or {}).items():
                    binds[k] = binds.get(k, 0) + v
            mza = max([r.get("max_zero_after_applied") for r in runs.values()
                       if r.get("max_zero_after_applied") is not None] or [None])
            viol = sum(r.get("n_invariant_violations", 0) for r in runs.values())
            sem = max((r.get("semantic", 0) for r in runs.values()), default=0)
            tr = mean_or_none([r.get("tau_ratio_median") for r in runs.values()])
            mech[(arm, seq)] = {"applied_frac": af, "max_zero_after": mz,
                                "max_zero_after_applied": mza, "violations": viol,
                                "semantic": sem, "tau_ratio": tr, "binds": binds}
            fmt = lambda x, n=4: ("n/a" if x is None else f"{x:.{n}f}")
            print(f"{arm + '/' + seq:<32}{len(runs):>3} {fmt(af):>13} "
                  f"{str(binds['none']) + '/' + str(binds['quota']) + '/' + str(binds['candidates']):>24} "
                  f"{fmt(mz):>15} {fmt(mza):>18} {viol:>5} {sem:>4} {fmt(tr):>17}")

    treat = [a for a in arms_present if a in PAIRS]
    if treat:
        print("\nPre-registered gate, literal form:")
        for arm in treat:
            if arm == "scale":
                continue
            bad = [f"{seq}({mech[(arm, seq)]['applied_frac']:.3f})" for seq in SEQS
                   if (arm, seq) in mech and (mech[(arm, seq)]['applied_frac'] or 0) < APPLIED_FRAC_MIN]
            bad2 = [f"{seq}({mech[(arm, seq)]['max_zero_after']:.4f})" for seq in SEQS
                    if (arm, seq) in mech and (mech[(arm, seq)]['max_zero_after'] or 0) > ZERO_FRAC_CAP]
            print(f"  {arm:<18} applied_frac>=0.95 fails on: {bad or 'none'}")
            print(f"  {'':<18} max_zero_after<=0.45 fails on: {bad2 or 'none'}")
        print("Invariant form (quota may never PUSH a frame past the cap):")
        for arm in treat:
            if arm == "scale":
                continue
            v = sum(mech[(arm, seq)]["violations"] for seq in SEQS if (arm, seq) in mech)
            print(f"  {arm:<18} frames violating after<=max(before,0.45): {v}")

    print("\n" + "=" * 100)
    print("T2 CRITERION 2/3 — ATE (cm), 3-seed mean +- spread, and per-arm deltas")
    print("=" * 100)
    hdr = f"{'seq':<12}" + "".join(f"{a:>22}" for a in arms_present)
    print(hdr)
    table = {}
    for seq in SEQS:
        line = f"{seq:<12}"
        for arm in arms_present:
            runs = data.get((arm, seq)) or {}
            ates = [r["ate"] for r in runs.values() if r.get("ate") is not None]
            if ates:
                m = st.mean(ates)
                table[(arm, seq)] = {"mean": m, "n": len(ates), "seeds": sorted(ates)}
                spread = f"{min(ates):.1f}-{max(ates):.1f}" if len(ates) > 1 else ""
                line += f"{m:>10.2f}{('[' + str(len(ates)) + ']' + spread):>12}"
            else:
                line += f"{'-':>22}"
        print(line)

    print("\ndelta vs own control  (negative = better than control)")
    for arm in [a for a in arms_present if a in PAIRS]:
        ctrl = PAIRS[arm]
        print(f"  {arm} vs {ctrl}")
        for seq in SEQS:
            t, c = table.get((arm, seq)), table.get((ctrl, seq))
            if not t or not c:
                continue
            d = t["mean"] - c["mean"]
            pct = d / c["mean"] * 100 if c["mean"] else float("nan")
            flag = ""
            if seq in STATIC:
                flag = "  <-- STATIC GUARDRAIL " + ("OK" if pct <= STATIC_TOL * 100 else "BREACH")
            print(f"    {seq:<12} {t['mean']:8.2f} vs {c['mean']:8.2f}  "
                  f"delta {d:+8.2f} cm ({pct:+6.1f}%){flag}")

    print("\nmean_w (guardrail 3: exclusion must not push it further down)")
    for seq in SEQS:
        line = f"  {seq:<12}"
        for arm in arms_present:
            runs = data.get((arm, seq)) or {}
            mw = mean_or_none([r.get("mean_w") for r in runs.values()])
            line += f"{arm}={'n/a' if mw is None else format(mw, '.4f')}  "
        print(line)

    ratios = [m["tau_ratio"] for (a, s), m in mech.items()
              if a == "eboth" and m["tau_ratio"] is not None]
    if ratios:
        print(f"\nT2-scale constant (pre-registered definition = median tau_after/tau_before "
              f"on E-both): per-seq {[round(r, 3) for r in ratios]} -> median "
              f"{st.median(ratios):.3f}")

    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
        payload = {"mech": {f"{a}/{s}": v for (a, s), v in mech.items()},
                   "ate": {f"{a}/{s}": v for (a, s), v in table.items()}}
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
