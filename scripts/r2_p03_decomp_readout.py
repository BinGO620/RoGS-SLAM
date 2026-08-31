#!/usr/bin/env python3
"""R2-P03-DECOMP readout: which knob of S6 produced the dominance over arm B?

The decision rule is **imported, not copied**, from ``scripts/r2_p03_sweep_readout.py``
(``RATE``, ``DECISION``, ``degradation``, ``keyframe_count``) and the statistics helpers from
the R2-P02 four-arm readout (``METRICS``, ``series``, ``sd``). Nothing about how a cell is
judged was rewritten for this campaign:

  RATE      ``refined_num_gaussians``
  DECISION  ``static_vacated_depth_l1_pen_cm`` (margin 1.56 cm, prereg PRIMARY, down-is-good)
  FAMILY    ``static_vacated_psnr``            (margin 0.28 dB, amendment #01 headline)
  DOMINANCE mean rate <= mean rate(B)  AND  both mean degradations <= their margins.

ONE addition, declared here before the first DECOMP run and descriptive only -- it cannot
change a dominance verdict:

  RATE BAND  For a cell that does NOT reach B's mean, where does it sit relative to B's rate
             NOISE? Reported as |rate - rate(B)| / max(own sd of the two arms), the campaign's
             standard conservative denominator, with <= 1.0x labelled "inside B's rate band".

Why that column exists at all: R2-P03-SWEEP produced exactly this situation and it was argued
about afterwards -- S2 (1.13xB) and S3 (1.14xB) formally "did not reach the budget" while
sitting 0.58x/0.90x of the noise away from B, which is a materially different statement from
"the baseline cannot get close". The pre-declared readings in
``results/evidence/r2_p03_decomp.md`` §2 bind all three outcomes to a meaning in advance, and
this column is what makes the middle one machine-decidable rather than rhetorical.

Also reported: keyframe count per cell (**required** -- SWEEP's dominating rung ran 16/18/18
keyframes against the anchors' 19/19/19, so part of its rate win was less coverage; a cell
whose rate win comes with equal keyframes is a strictly stronger result), the 2x2 factorial
decomposition of the two knobs, and the candidate ledger.

Usage: python scripts/r2_p03_decomp_readout.py [--out-dir results/runs/R2-P03/R2-P03-DECOMP]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics as st
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.r2_p02_preflight_readout import METRICS, sd, series  # noqa: E402
from scripts.r2_p03_decomp import CELLS  # noqa: E402
from scripts.r2_p03_sweep_readout import (  # noqa: E402  -- the SWEEP rule, verbatim
    DECISION,
    DESCRIPTIVE,
    RATE,
    T95_DF2,
    degradation,
    keyframe_count,
)

ANCHOR = "B_deferred"
CONTROL = "A0_prune"
ORDER = [CONTROL, ANCHOR, *CELLS]

# Pre-declared band threshold (descriptive column only, see module docstring).
BAND_SD = 1.0

# Cross-campaign REFERENCE ONLY: R2-P03-SWEEP ratios to ITS OWN in-campaign B anchor.
# Absolute counts from another campaign are banned (README); ratios to the same-campaign
# anchor are the one form the README allows for trend statements, and every row here is
# labelled with its campaign for that reason.
SWEEP_RATIOS = [
    ("S2_ttl1", "ttl_keyframes=1", "1.13x", "3"),
    ("S5_gth090", "gaussian_th=0.9", "1.43x", "3"),
    ("S6_maxpress", "ttl=1 + gth=0.9 + densify=5e-4", "0.63x", "3"),
    ("A0_prune", "-- (arm A default)", "2.19x", "3"),
]


def load(out_dir: Path) -> dict[str, dict[int, dict]]:
    path = out_dir / "decomp_results.jsonl"
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


def keyframes(raw, arm):
    return [k for k in (keyframe_count(raw[arm][s]["run_dir"]) for s in sorted(raw[arm]))
            if k is not None]


def every_seed_below(treat, ctrl):
    """3/3-style statement: is every treat seed below every ctrl seed on the rate axis?"""
    if not treat or not ctrl:
        return None
    return max(treat) < min(ctrl)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="results/runs/R2-P03/R2-P03-DECOMP")
    args = parser.parse_args()
    os.chdir(ROOT)
    out_dir = Path(args.out_dir)

    raw = load(out_dir)
    if not raw:
        print(f"no runs at {out_dir}/decomp_results.jsonl")
        return 1
    data = metrics_view(raw)
    order = [a for a in ORDER if a in data]

    lines: list[str] = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit("# R2-P03-DECOMP readout -- decomposing S6's dominance over the arm-B operating point")
    emit()
    emit("**Post-hoc, non-preregistered** (cells chosen after seeing `R2-P03-SWEEP`). Does not "
         "join the pre-declared ladder and does not alter the R2-P02 H1 record.")
    emit()
    emit(f"Rate axis = `{RATE}`. The decision rule is **imported** from "
         "`scripts/r2_p03_sweep_readout.py`, i.e. identical to the one that judged SWEEP:")
    for metric, (hib, margin, why) in DECISION.items():
        emit(f"- `{metric}` {'↑' if hib else '↓'} margin **{margin}** ({why})")
    emit()
    emit("Pre-declared readings of the three possible outcomes: "
         "`results/evidence/r2_p03_decomp.md` §2 (committed before the first run).")
    emit()
    emit("GO/KILL and narrative direction are the user's call (pre-registration §9). This "
         "report states measurements and one mechanical verdict.")
    emit()

    # ---- inventory -------------------------------------------------------------------
    emit("## Runs")
    emit()
    emit("| arm | knobs | seeds | min/run | ATE cm | keyframes | pose frozen | knobs live | "
         "activity |")
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

    # ---- rate-distortion table ---------------------------------------------------------
    emit("## Rate–distortion table (mean ± own sd over seeds)")
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
        kf_txt = "/".join(str(k) for k in kfs) if kfs else "-"
        emit(f"| {arm} | {len(data[arm])} | {kf_txt} | " + " | ".join(cells) + " |")
    emit()
    emit("`keyframes` is descriptive, and it is reported per seed on purpose: SWEEP's "
         "dominating rung ran **16/18/18** against the anchors' **19/19/19**, so part of its "
         "rate advantage was less coverage of the sequence rather than better economy. A cell "
         "that reaches B's budget at equal keyframe count is a strictly stronger result than "
         "S6 was; one that does it at fewer keyframes carries the same caveat (`r2_p03_sweep.md` "
         "§3.4).")
    emit()

    emit(f"Per-seed `{RATE}`:")
    emit()
    for arm in order:
        vals = series(data, arm, RATE)
        emit(f"- **{arm}**: " + " / ".join(f"{v:.0f}" for v in vals)
             + (f"   (mean {st.mean(vals):.0f}, own sd {sd(vals):.0f})" if len(vals) > 1 else ""))
    emit()

    if ANCHOR not in data:
        emit("**Arm B anchor missing -- no dominance verdict possible.**")
        (out_dir / "decomp_report.md").write_text("\n".join(lines) + "\n")
        return 0

    # ---- the verdict -------------------------------------------------------------------
    anchor_rate = series(data, ANCHOR, RATE)
    target = st.mean(anchor_rate)
    anchor_sd = sd(anchor_rate) if len(anchor_rate) > 1 else 0.0
    emit(f"## Dominance vs the arm-B operating point ({target:.0f} Gaussians, "
         f"n={len(anchor_rate)})")
    emit()
    emit("`degradation` is signed so **positive = the cell is worse than B**. A cell dominates "
         "only if it reached B's mean rate AND both degradations are within margin. The "
         "`rate band` column is descriptive (pre-declared, see the readout docstring): for a "
         "cell that missed B's mean, how far away it is in units of the larger own sd.")
    emit()
    emit("| cell | rate | rate/B | every seed < every B seed? | rate ≤ B? | rate band | " +
         " | ".join(f"deg. `{m.split('static_')[-1]}` (margin {DECISION[m][1]})" for m in DECISION)
         + " | verdict |")
    emit("|---" * (7 + len(DECISION)) + "|")
    verdicts = {}
    for arm in order:
        if arm == ANCHOR:
            continue
        rate_vals = series(data, arm, RATE)
        if not rate_vals:
            continue
        rate_mean = st.mean(rate_vals)
        rate_ok = rate_mean <= target
        own_sd = sd(rate_vals) if len(rate_vals) > 1 else 0.0
        denom = max(own_sd, anchor_sd)
        gap = (rate_mean - target) / denom if denom else float("nan")
        if rate_ok:
            band = f"— (reached, {gap:+.2f}×sd)"
        elif abs(gap) <= BAND_SD:
            band = f"**inside B's band** ({gap:+.2f}×sd)"
        else:
            band = f"above band ({gap:+.2f}×sd)"
        strict = every_seed_below(rate_vals, anchor_rate)
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
             f"{'yes' if strict else 'no'} | {'yes' if rate_ok else 'no'} | {band} | "
             + " | ".join(cells) + f" | {verdict} |")
    emit()
    emit("The ± column is a crude 95% interval from 3 seeds (2 df).")
    emit()
    dominating = [a for a, v in verdicts.items() if "DOMINATES" in v]
    emit(f"**Cells dominating B: {len(dominating)}** "
         + (f"({', '.join(dominating)})" if dominating else "(none)"))
    emit()
    decisive = verdicts.get("D1_densifyonly")
    if decisive:
        emit(f"**The decisive cell, `D1_densifyonly` (one generic densify knob, no admission "
             f"budget touched): {decisive}.** Its pre-declared reading is in "
             f"`results/evidence/r2_p03_decomp.md` §2.")
        emit()

    # ---- 2x2 factorial -----------------------------------------------------------------
    if CONTROL in data:
        base_rate = st.mean(series(data, CONTROL, RATE))
        emit("## 2×2 factorial on the rate axis (arm A + {ttl=1} × {densify 5e-4})")
        emit()
        emit("| cell | knobs | rate | ×A0 | ×B |")
        emit("|---|---|---|---|---|")
        for arm in [CONTROL, *CELLS, ANCHOR]:
            if arm not in data:
                continue
            vals = series(data, arm, RATE)
            if not vals:
                continue
            knobs = raw[arm][sorted(raw[arm])[0]].get("knobs") or {}
            knob_txt = ", ".join(f"`{k.split('.')[-1]}`={v}" for k, v in knobs.items()) or "—"
            emit(f"| {arm} | {knob_txt} | {st.mean(vals):.0f} | "
                 f"{st.mean(vals) / base_rate:.2f}× | {st.mean(vals) / target:.2f}× |")
        emit()
        have = [c for c in ("D0_ttl1", "D1_densifyonly", "D2_ttl1_densify") if c in data]
        if len(have) == 3:
            f_ttl = st.mean(series(data, "D0_ttl1", RATE)) / base_rate
            f_den = st.mean(series(data, "D1_densifyonly", RATE)) / base_rate
            f_both = st.mean(series(data, "D2_ttl1_densify", RATE)) / base_rate
            inter = f_both / (f_ttl * f_den) if f_ttl and f_den else float("nan")
            emit(f"Multiplicative main effects vs A0: ttl **{f_ttl:.2f}×**, densify "
                 f"**{f_den:.2f}×**, both **{f_both:.2f}×**; interaction "
                 f"= both/(ttl·densify) = **{inter:.2f}×** "
                 f"({'sub-additive — the knobs overlap' if inter > 1.05 else 'super-additive — the knobs compound' if inter < 0.95 else '≈ additive in log-rate'}).")
            emit()
            emit("Interaction is reported on 3-seed means whose own sd is large on this stack "
                 "(SWEEP: rate CV 5–33%); read it as a direction, not an estimate.")
            emit()

    # ---- descriptive contrasts ----------------------------------------------------------
    for ref in (ANCHOR, CONTROL):
        if ref not in data:
            continue
        emit(f"## Every metric vs `{ref}` (descriptive; conservative denominator)")
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
                better = sum(1 for i in range(n) if ((t[i] - c[i]) > 0) == hib)
                cells.append(f"{diff:+.4g} ({ratio:.2f}×, {better}/{n})")
            emit(f"| {arm} | " + " | ".join(cells) + " |")
        emit()

    # ---- mechanism -----------------------------------------------------------------------
    emit("## Candidate ledger (did each knob move the channel it names?)")
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
    emit("Expected signature: the `ttl` cells collapse `pending_final` and drive `promoted` to "
         "zero (SWEEP §4); the densify-only cell leaves the candidate ledger **unchanged**, "
         "because it acts downstream of admission. A densify-only cell that moved the ledger "
         "would not be knob-isolated and its row could not be read as declared.")
    emit()

    # ---- cross-campaign reference ---------------------------------------------------------
    emit("## Cross-campaign reference — RATIOS ONLY (R2-P03-SWEEP, commit `9c5f8a4`+`6b37845`)")
    emit()
    emit("Absolute Gaussian counts drift +12–15% across campaigns on this stack "
         "(`r2_p03_sweep.md` §5), so only each rung's ratio to **its own in-campaign B anchor** "
         "is quoted, and only as trend context — never mixed into the table above.")
    emit()
    emit("| SWEEP rung | knobs | rate ÷ SWEEP's B | n |")
    emit("|---|---|---|---|")
    for name, knobs, ratio, n in SWEEP_RATIOS:
        emit(f"| {name} | {knobs} | {ratio} | {n} |")
    emit()
    if "D0_ttl1" in data:
        d0 = st.mean(series(data, "D0_ttl1", RATE)) / target
        emit(f"`D0_ttl1` re-runs SWEEP's `S2_ttl1` config **verbatim** in this campaign: "
             f"{d0:.2f}×B here vs 1.13×B there — the gap between those two numbers is this "
             f"stack's campaign-to-campaign reproducibility on a ratio, measured rather than "
             f"assumed.")
        emit()

    emit("---")
    emit("Post-hoc, non-preregistered (`02-method.md` P0 follow-up). Decision rule imported "
         "verbatim from `scripts/r2_p03_sweep_readout.py`. GO/KILL and narrative remain the "
         "user's (prereg §9).")

    report = out_dir / "decomp_report.md"
    report.write_text("\n".join(lines) + "\n")
    print(f"\nwritten: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
