#!/usr/bin/env python3
"""P2-SF self-frozen de-confounding control readout.

Reads the four (variant, seq) contrasts of the P2-SF campaign and applies the
FOUR-BRANCH rule pre-registered in ``results/evidence/p2sf_selffrozen_prereg.md`` §3.
Nothing here invents a decision rule: the fidelity margins are IMPORTED from the SWEEP
readout (byte-identical to the four R2-P03 campaigns) and the branch definitions are a
transcription of prereg §3.

WHY THIS SCRIPT PARSES RUN DIRS INSTEAD OF THE RUNNER'S JSONL
------------------------------------------------------------
``scripts/r2_p2_sf.py::_extract`` hand-rolled its own metric extraction instead of
importing the canonical ``parse_run``, and it is wrong in four independent ways:

  1. it globs ``<run>/datasets_bonn/*/seed_*/*/tables`` -- that directory does not exist;
     the tables live at ``<run>/tables``. The glob returns empty, so ``_extract`` returns
     before reading anything and every record carries exit=0 and NO metrics;
  2. it takes ``next(csv.DictReader(f))`` -- the FIRST mapping row, whose ``mask_type`` is
     ``full``. The pre-registered口径 is the ``mask_type == "static"`` row;
  3. it asks for ``static_vacated_psnr_db``; the column is ``static_vacated_psnr``;
  4. it asks for ``num_keyframes``; keyframe count comes from ``plot/trj_final.json``
     (see ``r2_p03_sweep_readout.keyframe_count``).

None of that touches run integrity -- slam.py wrote every table to disk as usual -- so the
GPU work is fully recoverable and the runner was NOT modified mid-campaign (hard discipline
③: no live-code edits while a campaign is in flight). This readout re-derives every
observable from the run dirs with the canonical importers. Fix the runner AFTER the
campaign closes.

Usage: python scripts/r2_p2_sf_readout.py [--out-dir results/runs/P2/P2-SF]
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# IMPORT, do not copy: same口径 as every R2-P03 campaign.
from scripts.r2_p02_preflight_pose import parse_run  # noqa: E402
from scripts.r2_p03_sweep_readout import DECISION, RATE, keyframe_count  # noqa: E402

OUT_DIR = "results/runs/P2/P2-SF"
SEQS = ["pt1", "balloon2"]
VARIANTS = [("c", "PRIMARY branch"), ("b", "SENSITIVITY (regime-extremity)")]
ARMS = ["prune", "deferred"]

DEPTH = "static_vacated_depth_l1_pen_cm"
PSNR = "static_vacated_psnr"
DEPTH_MARGIN = DECISION[DEPTH][1]   # 1.56 cm, inherited, NOT re-fit
PSNR_MARGIN = DECISION[PSNR][1]     # 0.28 dB, inherited, NOT re-fit

# Prior frozen-pose campaigns carrying a paired (A0_prune, B_deferred) contrast on
# balloon. These supply the equivalence band prereg §3 defers to ("derived from R2-P03
# balloon frozen-pose CV ~7.8%"). S6REPL is deliberately absent: it shipped no A0_prune
# anchor (its own pre-declaration), so it carries no paired ratio.
BAND_SOURCES = {
    "R2-P03-SWEEP": "results/runs/R2-P03/R2-P03-SWEEP/sweep_results.jsonl",
    "R2-P03-DECOMP": "results/runs/R2-P03/R2-P03-DECOMP/decomp_results.jsonl",
    "R2-P04-MASKRATE": "results/runs/R2-P04/R2-P04-MASKRATE/maskrate_results.jsonl",
}
BAND_K = 1.0  # house convention: the inherited fidelity margins are each 1x null sd


def _sd(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def derive_equivalence_band():
    """Seed-to-seed sd of the paired log-ratio log(G_deferred/G_prune) under FROZEN pose.

    This is the null dispersion of exactly the P2-SF primary observable, measured on prior
    frozen-pose campaigns. Pooled within-campaign (df-weighted) so that the large real
    A0-vs-B mean effect never enters -- only its seed-to-seed wobble does.
    """
    per_campaign, logs_by_campaign = [], {}
    for name, path in BAND_SOURCES.items():
        if not os.path.isfile(path):
            continue
        g = {}
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            val = (r.get("metrics") or {}).get(RATE) or r.get(RATE)
            if r.get("arm") in ("A0_prune", "B_deferred") and val:
                g[(r["arm"], r.get("seed"))] = float(val)
        logs = []
        for s in sorted({s for (_, s) in g}):
            a, b = g.get(("A0_prune", s)), g.get(("B_deferred", s))
            if a and b:
                logs.append(math.log(b / a))
        s_ = _sd(logs)
        if s_ is not None:
            per_campaign.append((name, logs, s_))
            logs_by_campaign[name] = logs
    if not per_campaign:
        return None, []
    num = sum((len(l) - 1) * s * s for _, l, s in per_campaign)
    den = sum(len(l) - 1 for _, l, _ in per_campaign)
    return math.sqrt(num / den), per_campaign


def load_runs(out_dir):
    """(variant, arm, seq, seed) -> metrics, parsed from the run dir, not the jsonl."""
    out = {}
    for variant, _ in VARIANTS:
        for arm in ARMS:
            for seq in SEQS:
                for seed in (0, 1, 2):
                    run_root = os.path.join(out_dir, f"{seq}_{variant}_{arm}_seed{seed}")
                    if not os.path.isdir(os.path.join(run_root, "tables")):
                        continue
                    m = parse_run(run_root)
                    if m.get(RATE) is None:
                        continue
                    m["_kf"] = keyframe_count(run_root)
                    m["_run_dir"] = run_root
                    out[(variant, arm, seq, seed)] = m
    return out


def ledger(out_dir, variant, arm, seq, seed):
    """Candidate ledger from the run's deferred_commit_events.csv (prereg §4.8 record)."""
    hits = glob.glob(os.path.join(out_dir, f"{seq}_{variant}_{arm}_seed{seed}",
                                  "**", "deferred_commit_events.csv"), recursive=True)
    if not hits:
        return {}
    import csv as _csv
    counts = {}
    with open(sorted(hits)[-1], newline="", encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            ev = (row.get("event") or row.get("kind") or "").strip()
            if ev:
                counts[ev] = counts.get(ev, 0) + 1
    return counts


def fmt(x, p=4):
    return "n/a" if x is None else f"{x:.{p}f}"


# Variant C injects the P2-T prune arm's own trajectory. If the replay is faithful, the
# C-prune full-trajectory ATE must reproduce its source run EXACTLY -- that is the
# apparatus gate the abandoned RGD frozen-pose attempt could never pass (no timestamps,
# 580-vs-583 frames, 1.11cm anchor residual). Checked here as provenance, NOT as an
# outcome: prereg §2 fixes ATE as a canary.
P2T_SOURCE = {"pt1": "results/runs/P2/P2-T/pt1_prune_seed0",
              "balloon2": "results/runs/P2/P2-T/balloon2_prune_seed0"}


def injection_gate(runs):
    print("## Injection provenance gate (variant C only; ATE is a canary, not an outcome)")
    for seq, src in P2T_SOURCE.items():
        for seed in sorted({s for (_, _, q, s) in runs if q == seq}):
            rep = runs.get(("c", "prune", seq, seed))
            if not rep or not os.path.isdir(os.path.join(src, "tables")):
                continue
            s_m = parse_run(src)
            a_src, a_rep = s_m.get("ate_rmse_cm"), rep.get("ate_rmse_cm")
            ok = (a_src is not None and a_rep is not None
                  and abs(a_src - a_rep) < 1e-4)
            print(f"  {seq} seed{seed}: source {fmt(a_src)} vs C-prune replay {fmt(a_rep)} cm"
                  f" -> {'EXACT replay OK' if ok else 'MISMATCH — injection suspect'}")
            k_src = keyframe_count(src)
            k_rep = rep.get("_kf")
            if k_src is not None and k_rep is not None and k_src != k_rep:
                print(f"    NB keyframe count moved {k_src} -> {k_rep} under an exact-pose "
                      f"replay: map state feeds back into keyframe selection even with poses "
                      f"pinned (prereg §4.8 is live, not hypothetical).")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()
    os.chdir(ROOT)

    band_sd, per_campaign = derive_equivalence_band()
    runs = load_runs(args.out_dir)

    print("# P2-SF self-frozen de-confounding control — readout")
    print(f"# rule = transcription of results/evidence/p2sf_selffrozen_prereg.md §3")
    print(f"# fidelity margins IMPORTED from r2_p03_sweep_readout (NOT re-fit): "
          f"depth {DEPTH_MARGIN} cm / psnr {PSNR_MARGIN} dB")
    print()

    print("## Equivalence band (prereg §3 defers to prior frozen-pose variability)")
    if band_sd is None:
        print("  !! no prior paired frozen-pose campaign found — band undetermined")
    else:
        for name, logs, s_ in per_campaign:
            ratios = ", ".join(f"{math.exp(x):.4f}" for x in logs)
            print(f"  {name:16s} n={len(logs)} ratios [{ratios}] sd_log={s_:.4f}")
        print(f"  POOLED within-campaign sd of log(G_def/G_prune) = {band_sd:.4f} "
              f"({band_sd*100:.2f}% on the ratio scale), df="
              f"{sum(len(l)-1 for _, l, _ in per_campaign)}")
        for k in (1.0, 1.5, 2.0):
            lo, hi = math.exp(-k * band_sd), math.exp(k * band_sd)
            mark = "  <-- BAND_K" if abs(k - BAND_K) < 1e-9 else ""
            print(f"    +/-{k:.1f}*sd -> ratio [{lo:.4f}, {hi:.4f}]{mark}")
        print(f"  NOTE: the band is imported from a DIFFERENT regime (rtoff backbone,")
        print(f"  balloon, RGD-injected pose). It is a noise scale, not a null for this")
        print(f"  backbone/sequence. Prereg §3 governs seed 0 anyway: direction + whether")
        print(f"  the ratio is clearly far from 1. No branch is called from one seed.")
    print()

    seeds_present = sorted({s for (_, _, _, s) in runs})
    print(f"## Runs parsed: {len(runs)} (seeds present: {seeds_present or 'none yet'})")
    print()

    injection_gate(runs)

    any_pair = False
    for variant, role in VARIANTS:
        print(f"## variant {variant.upper()} — {role}")
        for seq in SEQS:
            for seed in seeds_present:
                pr = runs.get((variant, "prune", seq, seed))
                de = runs.get((variant, "deferred", seq, seed))
                if not pr or not de:
                    continue
                any_pair = True
                gp, gd = pr[RATE], de[RATE]
                ratio = gd / gp
                lr = math.log(ratio)
                inband = (band_sd is not None and abs(lr) <= BAND_K * band_sd)
                # POSITIVE = deferred worse than prune (same convention as sweep readout)
                d_depth = de[DEPTH] - pr[DEPTH]
                d_psnr = pr[PSNR] - de[PSNR]
                print(f"  {seq} seed{seed}:")
                print(f"    R_G^F = G_def/G_prune = {gd:.0f}/{gp:.0f} = {ratio:.4f} "
                      f"(log {lr:+.4f}) -> {'INSIDE' if inband else 'OUTSIDE'} "
                      f"+/-{BAND_K}*sd band")
                print(f"    guardrail vac_depth  deferred-prune = {d_depth:+.3f} cm "
                      f"(margin {DEPTH_MARGIN}; {'BREACH' if d_depth > DEPTH_MARGIN else 'within'})")
                print(f"    guardrail vac_psnr   prune-deferred = {d_psnr:+.3f} dB "
                      f"(margin {PSNR_MARGIN}; {'BREACH' if d_psnr > PSNR_MARGIN else 'within'})")
                ate_p, ate_d = pr.get("ate_rmse_cm"), de.get("ate_rmse_cm")
                canary_ok = (ate_p is not None and ate_d is not None
                             and abs(ate_p - ate_d) < 1e-6)
                print(f"    ATE canary (NOT an outcome): prune {fmt(ate_p,4)} / "
                      f"deferred {fmt(ate_d,4)} cm -> "
                      f"{'identical by construction OK' if canary_ok else 'DIFFER — investigate'}")
                kfp, kfd = pr.get("_kf"), de.get("_kf")
                kf_same = (kfp is not None and kfp == kfd)
                print(f"    KF schedule: prune {kfp} / deferred {kfd} -> "
                      f"{'same' if kf_same else 'DIFFERENT => prereg §4.8 AMBIGUITY TRIGGER'}")
                if not kf_same and kfp and kfd:
                    # DESCRIPTIVE / POST-HOC / NOT PRE-REGISTERED. This is a confound
                    # quantifier for the §4.8 trigger, not a decision statistic: it asks
                    # how much of R_G^F survives if the arms are put on a per-keyframe
                    # budget. Same standing as the S6REPL §4.4 observation -- it may be
                    # reported as descriptive, and may NOT be written as a verdict.
                    r_kf = (gd / kfd) / (gp / kfp)
                    print(f"    [DESCRIPTIVE, post-hoc, NOT pre-registered] per-KF budget: "
                          f"prune {gp/kfp:.1f} / deferred {gd/kfd:.1f} gaussians per KF "
                          f"-> ratio {r_kf:.4f} (raw {ratio:.4f}); KF gap explains "
                          f"{abs(r_kf-ratio)/abs(1-ratio)*100:.0f}% of the distance from 1")
                for arm in ARMS:
                    led = ledger(args.out_dir, variant, arm, seq, seed)
                    if led:
                        print(f"      ledger[{arm}]: "
                              + ", ".join(f"{k}={v}" for k, v in sorted(led.items())))
                # direction reporting only — prereg §4.2 forbids a single-seed verdict
                direction = ("deferred SMALLER (<1, same sign as self-tracked)" if ratio < 1
                             else "deferred LARGER (>1, OPPOSITE to pt1 self-tracked)")
                print(f"    direction: {direction}")
                print()
        print()

    if not any_pair:
        print("(no completed prune/deferred pair yet — rerun when runs land)")
        return 0

    print("## Branch assignment")
    print("  WITHHELD BY PREREG §4.2: seed 0 is SCREENING. One seed cannot estimate own_sd,")
    print("  so seed 0 reports direction + distance from 1 only. A branch")
    print("  (CONCORDANT MAP-EFFECT / NO-DETECTABLE / REVERSED / MIXED-TRADE) is called only")
    print("  after seeds 1,2 land via `--phase full`, and only if seed 0 is discriminative.")
    print("  Ceiling (prereg §4.4): this control may only WEAKEN or LEAVE UNCHANGED the H-D")
    print("  INDETERMINATE verdict. It can never upgrade it. n=2 seqs, map-level only, seen data.")
    print("  GO/KILL + narrative remain the user's.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
