#!/usr/bin/env python3
"""R2-P04-MASKRATE readout: does the hard-mask arm reach arm B's Gaussian budget?

The decision rule is **imported** from ``scripts/r2_p03_sweep_readout.py`` -- ``RATE``,
``DECISION`` (the two pre-declared margins 1.56 cm / 0.28 dB), ``degradation`` and
``keyframe_count`` are the same objects that judged SWEEP, DECOMP and S6REPL. Nothing about the
criteria is re-implemented here, so a difference in this table cannot come from a difference in
how it was scored.

What this readout adds over the R2-P03 ones, because the question is different:

* **the contrast is signed both ways.** SWEEP asked "can a pressure rung reach B's budget?", so
  its table only cared whether a rung got *under* B. Here the pre-declared question is
  directional in the opposite sense -- external review predicted the MASK arm should be no
  larger than B -- so ``M ÷ B`` is printed with its per-seed sign count and read against the
  three pre-declared branches (§2: M1 rate <= B / M2 inside the band / M3 rate > B).
* **the keyframe column is load-bearing, not descriptive.** A hard mask that over-fires changes
  covisibility and therefore how many keyframes the run keeps; a rate advantage bought with less
  coverage is not a rate advantage (SWEEP's S6 caveat, KF 18/18/16 < 19/19/19). Branch M3 in
  particular may not be written as a win without this column, and the readout says so inline.
* **the insertion-gate column (G5).** ``mask_gate_frames`` / ``mask_gate_px`` come from the run's
  own console log. A mask arm with zero gate frames silently degenerated into arm A, and the
  resulting "the mask changed nothing" row would be pure apparatus. It is printed next to the
  rate so the two are never read apart.

Dominance is still evaluated and printed under the imported rule, for one reason: the mask arm
reaching B's rate is only interesting if it did not pay fidelity for it, and "reached the budget
but broke a margin" is a different result from "reached the budget cleanly". Both anchors are
in-campaign (ratios on this stack drift up to ~30%), so every number here is a within-campaign
contrast.

Usage: python scripts/r2_p04_maskrate_readout.py [--out-dir results/runs/R2-P04/R2-P04-MASKRATE]
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
from scripts.r2_p03_sweep_readout import (  # noqa: E402  -- the criteria, by import
    DECISION,
    DESCRIPTIVE,
    RATE,
    T95_DF2,
    degradation,
    keyframe_count,
)
from scripts.r2_p04_maskrate import CELLS, MASK_SIDE  # noqa: E402

ANCHOR = "B_deferred"   # the budget under test
CONTROL = "A0_prune"    # insert-then-prune control = the mask arm's base
RESULTS = "maskrate_results.jsonl"


def load(out_dir: Path) -> dict[str, dict[int, dict]]:
    path = out_dir / RESULTS
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


def per_seed_sign(treat, ctrl, lower_is_better=True):
    """How many seeds moved in the claimed direction (the campaign's hard requirement)."""
    n = min(len(treat), len(ctrl))
    if not n:
        return 0, 0
    hits = sum(1 for i in range(n)
               if (treat[i] < ctrl[i] if lower_is_better else treat[i] > ctrl[i]))
    return hits, n


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="results/runs/R2-P04/R2-P04-MASKRATE")
    args = parser.parse_args()
    os.chdir(ROOT)
    out_dir = Path(args.out_dir)

    raw = load(out_dir)
    if not raw:
        print(f"no runs at {out_dir}/{RESULTS}")
        return 1
    data = metrics_view(raw)
    order = [a for a in (CONTROL, ANCHOR, *CELLS) if a in data]

    lines: list[str] = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit("# R2-P04-MASKRATE readout -- the hard-mask comparator the compactness claim "
         "never had")
    emit()
    emit(f"Rate axis = `{RATE}`. Decision family + margins are **imported** from "
         "`scripts/r2_p03_sweep_readout.py`, the same objects that judged SWEEP, DECOMP and "
         "S6REPL:")
    for metric, (hib, margin, why) in DECISION.items():
        emit(f"- `{metric}` {'↑' if hib else '↓'} margin **{margin}** ({why})")
    emit()
    emit("Pre-declared question (`results/evidence/r2_p04_maskrate.md` §2, committed before the "
         "first run): **does `M_mask` reach `B_deferred`'s mean Gaussian count?** External "
         "review's argument is that a hard mask is a strict SUBSET of what deferred admits, so "
         "M should be ≤ B. Branches: **M1** M ≤ B (prediction holds), **M2** inside the rate "
         "noise band, **M3** M > B (prediction fails — and per §2 may NOT be written as a win "
         "without the keyframe column).")
    emit()
    emit("**Not measurable in this campaign** (§3): recovery of mask false positives. Masked "
         "pixels are zeroed in `add_new_keyframe` upstream of candidate formation, so a "
         "mask+deferred arm would report ~0 recovery by construction. Offline sizing: "
         "`scripts/r2_p04_mask_fp_anchor.py`.")
    emit()
    emit("GO/KILL and narrative direction are the user's call (pre-registration §9). This "
         "report states measurements and mechanical verdicts.")
    emit()

    # ---- inventory -------------------------------------------------------------------
    emit("## Runs")
    emit()
    emit("| arm | knobs | seeds | min/run | ATE cm | keyframes | pose frozen | knobs live | "
         "insertion gate (G5) | activity |")
    emit("|---|---|---|---|---|---|---|---|---|---|")
    for arm in order:
        rows = [raw[arm][s] for s in sorted(raw[arm])]
        knobs = rows[0].get("knobs") or {}
        knob_txt = ", ".join(f"`{k.split('.')[-1]}`={v}" for k, v in knobs.items()) or "— (anchor)"
        ates = {round(r["metrics"].get("ate_rmse_cm") or -1, 4) for r in rows}
        kfs = keyframes(raw, arm)
        gate_f = [r.get("mask_gate_frames", 0) for r in rows]
        gate_p = [r.get("mask_gate_px", 0) for r in rows]
        if arm in MASK_SIDE:
            fired = all(f > 0 for f in gate_f)
            gate_txt = (f"{'/'.join(str(f) for f in gate_f)} kf, "
                        f"{st.mean(gate_p):.0f} px avg" if fired
                        else "**NEVER FIRED — arm degenerated into arm A**")
        else:
            gate_txt = "off ✓" if all(f == 0 for f in gate_f) else "**LEAKED**"
        emit(f"| {arm} | {knob_txt} | {','.join(str(s) for s in sorted(raw[arm]))} | "
             f"{st.mean([r['minutes'] for r in rows]):.1f} | "
             f"{'/'.join(f'{a:.4f}' for a in sorted(ates))} | "
             f"{'/'.join(str(k) for k in kfs) if kfs else '-'} | "
             f"{'yes' if all(r['pose_frozen'] for r in rows) else '**NO**'} | "
             f"{'yes' if all(r['config_echo_ok'] for r in rows) else '**NO**'} | "
             f"{gate_txt} | {rows[0]['activity_verdict']} |")
    emit()
    emit("`insertion gate` is **G5**, read from each run's own console log: the mask arm must "
         "show `Semantic insertion gate ... person px zeroed` and the anchors must not. A mask "
         "arm with zero gate frames is a duplicate of arm A, and its rate row would be "
         "apparatus rather than measurement.")
    emit()

    # ---- rate / fidelity table -------------------------------------------------------
    emit("## Rate and fidelity (mean ± own sd over seeds)")
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
    emit("**The keyframe column is load-bearing in this campaign**, not descriptive as it was "
         "in SWEEP: a hard mask changes covisibility, so it can change how many keyframes the "
         "run keeps, and a rate difference across different keyframe counts is not a "
         "same-budget comparison.")
    emit()

    emit(f"Per-seed `{RATE}`:")
    emit()
    for arm in order:
        vals = series(data, arm, RATE)
        emit(f"- **{arm}**: " + " / ".join(f"{v:.0f}" for v in vals)
             + (f"   (mean {st.mean(vals):.0f}, own sd {sd(vals):.0f})" if len(vals) > 1 else ""))
    emit()

    # ---- the pre-declared question ---------------------------------------------------
    if ANCHOR not in data:
        emit("**Arm B anchor missing -- the pre-declared question cannot be answered.**")
        (out_dir / "maskrate_report.md").write_text("\n".join(lines) + "\n")
        return 0

    b_rate = series(data, ANCHOR, RATE)
    target = st.mean(b_rate)
    emit(f"## The pre-declared question: does the mask arm reach B's budget "
         f"({target:.0f} Gaussians)?")
    emit()
    for arm in CELLS:
        if arm not in data:
            continue
        m_rate = series(data, arm, RATE)
        if not m_rate:
            continue
        m_mean = st.mean(m_rate)
        ratio = m_mean / target
        spread = max(sd(m_rate) if len(m_rate) > 1 else 0.0,
                     sd(b_rate) if len(b_rate) > 1 else 0.0)
        in_sd = (m_mean - target) / spread if spread else float("nan")
        hits, n = per_seed_sign(m_rate, b_rate, lower_is_better=True)
        if m_mean <= target and hits == n and n:
            branch = ("**M1 — the prediction HOLDS**: the hard mask reaches B's budget on every "
                      "seed. The compactness claim must be scoped to insert-then-prune, with "
                      "the hard-mask comparator reported as our own measured limitation.")
        elif abs(in_sd) <= 2.0:
            branch = ("**M2 — inside the rate noise band** (|Δ| ≤ 2× the larger own sd, the "
                      "campaign-wide resolution limit): the two admission strategies land on "
                      "the same budget by different routes. Compactness is not a "
                      "differentiator vs hard masking; it remains one vs insert-then-prune.")
        elif m_mean > target:
            branch = ("**M3 — the prediction FAILS**: the mask arm's map is LARGER than B's. "
                      "Per §2 this may not be written as a win until the keyframe column is "
                      "read: check whether the mask changed coverage before crediting the "
                      "difference to admission.")
        else:
            branch = ("**M1 (mean) with a per-seed split** — the mean reaches B's budget but "
                      f"only {hits}/{n} seeds agree in sign; per the campaign-wide rule a "
                      "split-sign contrast is read as inside the band (M2).")
        emit(f"- **{arm}** {m_mean:.0f} vs B {target:.0f} = **{ratio:.2f}×B** "
             f"({in_sd:+.2f}× own sd, per-seed {hits}/{n} below B)")
        emit()
        emit(f"  {branch}")
        emit()

    # ---- fidelity under the imported rule --------------------------------------------
    emit("## Fidelity under the imported dominance rule")
    emit()
    emit("Reaching B's rate is only interesting if it was not paid for in fidelity. "
         "`degradation` is signed so **positive = the arm is worse than B**; `within margin` is "
         "the same pre-declared bounded non-inferiority test used by all three R2-P03 "
         "campaigns.")
    emit()
    emit("| arm | rate | rate/B | rate ≤ B? | " +
         " | ".join(f"deg. `{m.split('static_')[-1]}` (margin {DECISION[m][1]})" for m in DECISION)
         + " | verdict |")
    emit("|---" * (5 + len(DECISION)) + "|")
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
        emit(f"| {arm} | {rate_mean:.0f} | {rate_mean / target:.2f}× | "
             f"{'yes' if rate_ok else 'no'} | " + " | ".join(cells) + f" | {verdict} |")
    emit()
    emit("The ± column is a crude 95% interval from 3 seeds (2 df), shown so the margin test is "
         "read against its own uncertainty, not as a significance claim.")
    emit()

    # ---- in-campaign compactness re-measurement --------------------------------------
    if CONTROL in data:
        a_rate = series(data, CONTROL, RATE)
        if a_rate and b_rate:
            a_mean = st.mean(a_rate)
            hits, n = per_seed_sign(b_rate, a_rate, lower_is_better=True)
            emit("## B vs A compactness, re-measured in this campaign (4th independent "
                 "measurement)")
            emit()
            emit(f"- `{ANCHOR}` {target:.0f} vs `{CONTROL}` {a_mean:.0f} = "
                 f"**{100 * (target / a_mean - 1):+.1f}%** ({target / a_mean:.2f}×), "
                 f"per-seed {hits}/{n}")
            emit()
            emit("Prior three campaigns: **−55.2% / −54.3% / −46.6%**. Cross-campaign ratios on "
                 "this stack drift up to ~30% (README), so this row is reported as its own "
                 "in-campaign measurement, not as agreement or disagreement with those.")
            emit()

    # ---- descriptive contrasts -------------------------------------------------------
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
                better = sum(1 for i in range(n) if ((t[i] - c[i]) > 0) == hib)
                cells.append(f"{diff:+.4g} ({ratio:.2f}×, {better}/{n})")
            emit(f"| {arm} | " + " | ".join(cells) + " |")
        emit()

    # ---- mechanism -------------------------------------------------------------------
    emit("## Candidate ledger + what the mask actually removed")
    emit()
    keys = ["candidate_total", "promoted", "rejected", "expired", "pruned",
            "pending_peak", "pending_final"]
    emit("| arm | " + " | ".join(f"`{k}`" for k in keys) + " | gate kf | gate px |")
    emit("|---" * (len(keys) + 3) + "|")
    for arm in order:
        rows = [raw[arm][s] for s in sorted(raw[arm])]
        ledgers = [r.get("candidate_ledger") or {} for r in rows]
        cells = []
        for key in keys:
            vals = [r.get(key) for r in ledgers if isinstance(r.get(key), (int, float))]
            cells.append(f"{st.mean(vals):.0f}" if vals else "-")
        gate_f = [r.get("mask_gate_frames", 0) for r in rows]
        gate_p = [r.get("mask_gate_px", 0) for r in rows]
        emit(f"| {arm} | " + " | ".join(cells)
             + f" | {st.mean(gate_f):.1f} | {st.mean(gate_p):.0f} |")
    emit()
    emit("The mask removes candidates **upstream**: a zeroed person pixel fails the "
         "`observed > 0.01` validity test in `_classify_new_keyframe`, so it never becomes a "
         "candidate at all. `candidate_total` vs `A0_prune` is that subset relation made "
         "visible rather than argued — and it is also why this campaign cannot measure "
         "recovery (§3).")
    emit()
    emit("---")
    emit("Non-preregistered exploration (post-hoc, chosen after three campaigns and an external "
         "review). It does not join the pre-declared ladder and does not alter the R2-P02 H1 "
         "record. GO/KILL and narrative remain the user's (prereg §9).")

    report = out_dir / "maskrate_report.md"
    report.write_text("\n".join(lines) + "\n")
    print(f"\nwritten: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
