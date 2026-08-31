#!/usr/bin/env python3
"""R2-P03-SWEEP readout: the rate-distortion table, and one mechanical dominance verdict.

Same measurement 口径 as the R2-P02 four-arm readout (``METRICS``, ``series`` and ``sd`` are
imported from it, not re-implemented): per-arm 3-seed mean ± own sd, contrasts reported
against the LARGER of the two arms' own sd, per-seed sign counts, and no single-seed claims.

What is new here is the **decision rule**, and it is pre-declared in this file before any run
existed (see the commit that introduced it):

  RATE          ``refined_num_gaussians``. On this stack colour refinement does not change the
                count (``online_num_gaussians == refined_num_gaussians`` on all 12 pre-flight
                runs), so this is the final map size.

  DECISION      ``static_vacated_depth_l1_pen_cm``  (prereg PRIMARY, ↓)  margin **1.56 cm**
  FAMILY        ``static_vacated_psnr``             (amendment #01 headline, ↑) margin **0.28 dB**
                Margins = one self-tracked null sd each (1.559 / 0.278, measured on 7
                identical-algorithm replicates: ``r2_p02_e2_metric_calibration.txt``).

  REPORTED, NOT DECIDING: ``static_depth_l1_pen_cm``, ``static_psnr``, ``static_ssim``, peak
                VRAM, FPS, ATE. Ten metrics were examined in the pre-flight; letting any of
                them arbitrate here would be the metric-shopping amendment #01 §A forbids.

  DOMINANCE     A rung L dominates the arm-B operating point iff
                  (i)  mean rate(L) ≤ mean rate(B)                                 -- and
                  (ii) on BOTH decision metrics, L's mean degradation vs B ≤ its margin.
                Degradation is signed so that positive = L worse. The verdict is printed
                three-valued: DOMINATES / NOT-DOMINATED / (rate-only) so a rung that never
                reached B's budget is never silently read as a fidelity result.

Why bounded non-inferiority rather than "the difference is smaller than the sd": external
review was explicit that an undetected difference is not evidence of equivalence. A margin
declared in advance, with the observed difference and its spread printed next to it, states
what was ruled out ("no depth degradation larger than ~1.5 cm") instead of asserting equality.
With 3 seeds the sd carries 2 df, so the CI column is a crude interval and is labelled as one.

Usage: python scripts/r2_p03_sweep_readout.py [--out-dir results/runs/R2-P03/R2-P03-SWEEP]
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics as st
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.r2_p02_preflight_readout import METRICS, sd, series  # noqa: E402
from scripts.r2_p03_sweep import LEVELS  # noqa: E402

RATE = "refined_num_gaussians"
ANCHOR = "B_deferred"
CONTROL = "A0_prune"

# metric -> (higher_is_better, pre-declared non-inferiority margin, source of the margin)
DECISION = {
    "static_vacated_depth_l1_pen_cm": (False, 1.56, "prereg PRIMARY; 1x self-tracked null sd 1.559"),
    "static_vacated_psnr": (True, 0.28, "amendment #01 headline; 1x self-tracked null sd 0.278"),
}
DESCRIPTIVE = [
    ("static_depth_l1_pen_cm", False),
    ("static_psnr", True),
    ("static_ssim", True),
    ("online_peak_gpu_memory_gb", False),
    ("online_fps", True),
    ("ate_rmse_cm", False),
]
# 95% two-sided t for 2 df (3 seeds). Used only for the crude interval column.
T95_DF2 = 4.303


def load(out_dir: Path) -> dict[str, dict[int, dict]]:
    path = out_dir / "sweep_results.jsonl"
    out: dict[str, dict[int, dict]] = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("exit") != 0:
            continue
        out.setdefault(row["arm"], {})[int(row["seed"])] = row
    return out


def metrics_view(raw):
    return {arm: {seed: row.get("metrics", {}) for seed, row in seeds.items()}
            for arm, seeds in raw.items()}


def keyframe_count(run_root):
    """Number of keyframes the run actually kept (descriptive column, added after the runs).

    ``plot/trj_final.json`` carries one entry per keyframe; it agrees exactly with the
    independent count of keyframes that opened a candidate batch (kf_traj = that + 1, the
    init keyframe having no map to classify against) on all 20 runs of this campaign.

    Why it is in the table: the rate axis is only a like-for-like budget comparison between
    arms that covered the sequence with the same number of keyframes. Both anchors sit at 19
    on every seed; the pressure rungs range 16-20, because a perturbed map changes the
    covisibility test the keyframe selector uses. This column is DESCRIPTIVE -- it entered
    after the runs finished and is not part of the pre-declared decision rule.
    """
    hits = glob.glob(os.path.join(run_root, "**", "plot", "trj_final.json"), recursive=True)
    if not hits:
        return None
    try:
        return len(json.load(open(sorted(hits)[-1], encoding="utf-8"))["trj_id"])
    except (KeyError, ValueError, OSError):
        return None


def keyframes(raw, arm):
    return [k for k in (keyframe_count(raw[arm][s]["run_dir"]) for s in sorted(raw[arm]))
            if k is not None]


def degradation(treat_vals, ctrl_vals, higher_is_better):
    """Signed so that POSITIVE = treat is worse than ctrl."""
    diff = st.mean(treat_vals) - st.mean(ctrl_vals)
    return -diff if higher_is_better else diff


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="results/runs/R2-P03/R2-P03-SWEEP")
    args = parser.parse_args()
    os.chdir(ROOT)
    out_dir = Path(args.out_dir)

    raw = load(out_dir)
    if not raw:
        print(f"no runs at {out_dir}/sweep_results.jsonl")
        return 1
    data = metrics_view(raw)
    order = [a for a in (CONTROL, ANCHOR, *LEVELS) if a in data]

    lines: list[str] = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit("# R2-P03-SWEEP readout -- matched-budget prune ladder vs the arm-B operating point")
    emit()
    emit(f"Rate axis = `{RATE}`. Decision family + margins are pre-declared in "
         "`scripts/r2_p03_sweep_readout.py` (committed before the first run):")
    for metric, (hib, margin, why) in DECISION.items():
        emit(f"- `{metric}` {'↑' if hib else '↓'} margin **{margin}** ({why})")
    emit()
    emit("GO/KILL and narrative direction are the user's call (pre-registration §9). This "
         "report states measurements and one mechanical verdict.")
    emit()

    # ---- inventory -------------------------------------------------------------------
    emit("## Runs")
    emit()
    emit("| arm | knobs | seeds | min/run | ATE cm | keyframes | pose frozen | knobs live | activity |")
    emit("|---|---|---|---|---|---|---|---|---|")
    for arm in order:
        rows = [raw[arm][s] for s in sorted(raw[arm])]
        knobs = rows[0].get("knobs") or {}
        knob_txt = ", ".join(f"`{k.split('.')[-1]}`={v}" for k, v in knobs.items()) or "— (anchor)"
        ates = {round(r["metrics"].get("ate_rmse_cm") or -1, 4) for r in rows}
        kfs = keyframes(raw, arm)
        emit(f"| {arm} | {knob_txt} | {','.join(str(s) for s in sorted(raw[arm]))} | "
             f"{st.mean([r['minutes'] for r in rows]):.1f} | "
             f"{'/'.join(f'{a:.4f}' for a in sorted(ates))} | "
             f"{'/'.join(str(k) for k in kfs) if kfs else '-'} | "
             f"{'yes' if all(r['pose_frozen'] for r in rows) else '**NO**'} | "
             f"{'yes' if all(r['config_echo_ok'] for r in rows) else '**NO**'} | "
             f"{rows[0]['activity_verdict']} |")
    emit()

    # ---- rate-distortion table -------------------------------------------------------
    emit("## Rate–distortion ladder (mean ± own sd over seeds)")
    emit()
    cols = [RATE] + list(DECISION) + [m for m, _ in DESCRIPTIVE]
    emit("| arm | n | keyframes | " + " | ".join(f"`{c}`" for c in cols) + " |")
    emit("|---" * (len(cols) + 3) + "|")
    for arm in order:
        cells = []
        for metric in cols:
            vals = series(data, arm, metric)
            cells.append(f"{st.mean(vals):.4g} ± {sd(vals):.3g}" if len(vals) > 1
                         else (f"{vals[0]:.4g}" if vals else "-"))
        kfs = keyframes(raw, arm)
        kf_txt = (f"{st.mean(kfs):.1f}" + (f" ± {sd(kfs):.2g}" if len(kfs) > 1 else "")
                  if kfs else "-")
        emit(f"| {arm} | {len(data[arm])} | {kf_txt} | " + " | ".join(cells) + " |")
    emit()
    emit("`keyframes` is descriptive and post-hoc (not in the pre-declared rule): the rate axis "
         "is a like-for-like budget comparison only between arms that covered the sequence with "
         "the same number of keyframes. **Both anchors sit at 19 on every seed**; the pressure "
         "rungs vary, because a perturbed map changes the covisibility test the keyframe "
         "selector uses.")
    emit()

    emit(f"Per-seed `{RATE}`:")
    emit()
    for arm in order:
        vals = series(data, arm, RATE)
        emit(f"- **{arm}**: " + " / ".join(f"{v:.0f}" for v in vals)
             + (f"   (mean {st.mean(vals):.0f}, own sd {sd(vals):.0f})" if len(vals) > 1 else ""))
    emit()

    # ---- the verdict -----------------------------------------------------------------
    if ANCHOR not in data:
        emit("**Arm B anchor missing -- no dominance verdict possible.**")
        (out_dir / "sweep_report.md").write_text("\n".join(lines) + "\n")
        return 0

    anchor_rate = series(data, ANCHOR, RATE)
    target = st.mean(anchor_rate)
    emit(f"## Dominance vs the arm-B operating point ({target:.0f} Gaussians)")
    emit()
    emit("`rate ≤ B` = the rung reached B's budget. `degradation` is signed so **positive = the "
         "rung is worse than B**; `within margin` is the pre-declared bounded non-inferiority "
         "test. A rung dominates only if it did BOTH.")
    emit()
    emit("| rung | rate | rate/B | rate ≤ B? | " +
         " | ".join(f"deg. `{m.split('static_')[-1]}` (margin {DECISION[m][1]})" for m in DECISION)
         + " | verdict |")
    emit("|---" * (5 + len(DECISION)) + "|")
    verdicts = {}
    for arm in order:
        if arm == ANCHOR:
            continue
        rate_vals = series(data, arm, RATE)
        if not rate_vals:
            continue
        rate_mean = st.mean(rate_vals)
        rate_ok = rate_mean <= target
        cells, fidelity_ok = [], True
        for metric, (hib, margin, _) in DECISION.items():
            t, c = series(data, arm, metric), series(data, ANCHOR, metric)
            if not t or not c:
                cells.append("-")
                fidelity_ok = False
                continue
            deg = degradation(t, c, hib)
            spread = max(sd(t) if len(t) > 1 else 0.0, sd(c) if len(c) > 1 else 0.0)
            half = T95_DF2 * spread * math.sqrt(2.0 / max(len(t), 1)) if spread else 0.0
            ok = deg <= margin
            fidelity_ok &= ok
            cells.append(f"{deg:+.3f} (±{half:.2f}) {'✓' if ok else '**✗**'}")
        if rate_ok and fidelity_ok:
            verdict = "**DOMINATES B**"
        elif not rate_ok:
            verdict = "did not reach B's budget"
        else:
            verdict = "**NOT-DOMINATED** (reached the budget, lost fidelity)"
        verdicts[arm] = verdict
        emit(f"| {arm} | {rate_mean:.0f} | {rate_mean / target:.2f}× | "
             f"{'yes' if rate_ok else 'no'} | " + " | ".join(cells) + f" | {verdict} |")
    emit()
    emit("The ± column is a crude 95% interval from 3 seeds (2 df) and is shown so the margin "
         "test is read against its own uncertainty, not as a significance claim.")
    emit()

    dominating = [a for a, v in verdicts.items() if "DOMINATES" in v]
    emit(f"**Rungs dominating B: {len(dominating)}** "
         + (f"({', '.join(dominating)})" if dominating else "(none)"))
    emit()

    # ---- descriptive contrasts vs both anchors ---------------------------------------
    for ref in (ANCHOR, CONTROL):
        if ref not in data:
            continue
        emit(f"## Every metric vs `{ref}` (descriptive; the campaign's conservative denominator)")
        emit()
        emit("| arm | " + " | ".join(f"`{m}`" for m, _ in METRICS) + " |")
        emit("|---" * (len(METRICS) + 1) + "|")
        for arm in order:
            if arm == ref:
                continue
            cells = []
            for metric, hib in METRICS:
                t, c = series(data, arm, metric), series(data, ref, metric)
                if not t or not c:
                    cells.append("-")
                    continue
                diff = st.mean(t) - st.mean(c)
                denom = max(sd(t) if len(t) > 1 else 0.0, sd(c) if len(c) > 1 else 0.0)
                ratio = abs(diff) / denom if denom else float("nan")
                n = min(len(t), len(c))
                better = sum(1 for i in range(n)
                             if ((t[i] - c[i]) > 0) == hib)
                cells.append(f"{diff:+.4g} ({ratio:.2f}×, {better}/{n})")
            emit(f"| {arm} | " + " | ".join(cells) + " |")
        emit()

    # ---- mechanism -------------------------------------------------------------------
    emit("## Candidate ledger (did the knob move the mechanism it names?)")
    emit()
    keys = ["candidate_total", "promoted", "rejected", "expired", "pruned",
            "pending_peak", "pending_final"]
    emit("| arm | " + " | ".join(f"`{k}`" for k in keys) + " |")
    emit("|---" * (len(keys) + 1) + "|")
    for arm in order:
        rows = [raw[arm][s].get("candidate_ledger") or {} for s in sorted(raw[arm])]
        cells = []
        for key in keys:
            vals = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
            cells.append(f"{st.mean(vals):.0f}" if vals else "-")
        emit(f"| {arm} | " + " | ".join(cells) + " |")
    emit()
    emit("Arm A instantiates every candidate immediately and deletes the rejected/expired "
         "lineages; arm B instantiates only the promoted ones. `pending_final` is therefore the "
         "candidate residue arm A still carries at the end of the run -- the quantity the "
         "TTL/budget rungs attack directly.")
    emit()
    emit("---")
    emit("Non-preregistered exploration (`02-method.md` P0). It does not alter the R2-P02 H1 "
         "record. GO/KILL and narrative remain the user's (prereg §9).")

    report = out_dir / "sweep_report.md"
    report.write_text("\n".join(lines) + "\n")
    print(f"\nwritten: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
