#!/usr/bin/env python3
"""R2-P03-S6REPL readout: does S6 still dominate B, and what did ``gaussian_th`` contribute?

The decision rule is **imported, not copied**, from ``scripts/r2_p03_sweep_readout.py``
(``RATE``, ``DECISION``, ``DESCRIPTIVE``, ``degradation``, ``keyframe_count``, ``T95_DF2``) and
the statistics helpers from the R2-P02 four-arm readout (``METRICS``, ``series``, ``sd``), so
nothing about how an arm is judged was rewritten for this campaign -- it is byte-identical to
the rule that produced SWEEP's "1/6 dominates" and DECOMP's "0/4 dominates":

  RATE      ``refined_num_gaussians``
  DECISION  ``static_vacated_depth_l1_pen_cm`` (margin 1.56 cm, prereg PRIMARY, down-is-good)
  FAMILY    ``static_vacated_psnr``            (margin 0.28 dB, amendment #01 headline)
  DOMINANCE mean rate <= mean rate(B)  AND  both mean degradations <= their margins.
  DENOM     the larger of the two arms' own 3-seed sd, never pooled.

Two contrasts, both pre-declared in ``results/evidence/r2_p03_s6repl.md`` §2 before the first
run, and both WITHIN this campaign -- which is the whole reason it is 9 runs and not 3:

  Q1  gth's contribution = S6 / D2 on the rate axis. Those two configs differ in EXACTLY
      ``Training.gaussian_th`` (pinned by tests/test_r2_p03_decomp_configs.py and re-pinned by
      tests/test_r2_p03_s6repl_configs.py), so the ratio is that knob's multiplicative effect
      at ttl=1 + densify=5e-4. Reported with the conservative denominator, per-seed sign count
      and the every-seed-below check -- the same three ways DECOMP reported its decisive cell,
      so that no single one of them carries the reading.
  Q2  replication = the imported dominance verdict for S6 against an in-campaign B anchor.

Cross-campaign ratios appear in one clearly-marked section at the end and are never mixed into
the tables: DECOMP measured that a ratio itself drifts ~21% between campaigns, so the point of
that section is to ADD a third datapoint to that drift measurement, not to compare arms.

Usage: python scripts/r2_p03_s6repl_readout.py [--out-dir results/runs/R2-P03/R2-P03-S6REPL]
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
from scripts.r2_p03_s6repl import CELLS  # noqa: E402
from scripts.r2_p03_sweep_readout import (  # noqa: E402  -- the SWEEP rule, verbatim
    DECISION,
    DESCRIPTIVE,
    RATE,
    T95_DF2,
    degradation,
    keyframe_count,
)

ANCHOR = "B_deferred"
TREAT = "S6_maxpress"
BASE = "D2_ttl1_densify"          # == S6 minus Training.gaussian_th
ORDER = [ANCHOR, BASE, TREAT]

# Pre-declared band threshold (descriptive column; identical to DECOMP's).
BAND_SD = 1.0

# Cross-campaign REFERENCE ONLY, each row a ratio to ITS OWN in-campaign B anchor, labelled
# with its campaign. Absolutes from another campaign are banned (README); ratios drift ~15-20%
# (r2_p03_decomp.md §4.5), so these rows are drift datapoints, not comparisons.
PRIOR_RATIOS = [
    ("R2-P03-SWEEP", "9c5f8a4+6b37845", "S6_maxpress", "ttl=1 + gth=0.9 + densify=5e-4",
     "0.63×", "3"),
    ("R2-P03-SWEEP", "9c5f8a4", "S5_gth090", "gaussian_th=0.9 alone", "1.43×", "3"),
    ("R2-P03-SWEEP", "9c5f8a4", "S2_ttl1", "ttl_keyframes=1 alone", "1.13×", "3"),
    ("R2-P03-DECOMP", "5e789a5", "D2_ttl1_densify", "ttl=1 + densify=5e-4", "1.07×", "3"),
    ("R2-P03-DECOMP", "5e789a5", "D0_ttl1", "ttl_keyframes=1 alone (S2's file verbatim)",
     "1.37×", "3"),
]


def load(out_dir: Path) -> dict[str, dict[int, dict]]:
    path = out_dir / "s6repl_results.jsonl"
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
    parser.add_argument("--out-dir", default="results/runs/R2-P03/R2-P03-S6REPL")
    args = parser.parse_args()
    os.chdir(ROOT)
    out_dir = Path(args.out_dir)

    raw = load(out_dir)
    if not raw:
        print(f"no runs at {out_dir}/s6repl_results.jsonl")
        return 1
    data = metrics_view(raw)
    order = [a for a in ORDER if a in data]

    lines: list[str] = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit("# R2-P03-S6REPL readout — does S6's dominance replicate, and what did `gaussian_th` do?")
    emit()
    emit("**Post-hoc, non-preregistered** (arms chosen after seeing `R2-P03-SWEEP` and "
         "`R2-P03-DECOMP`). Does not join the pre-declared ladder and does not alter the "
         "R2-P02 H1 record.")
    emit()
    emit(f"Rate axis = `{RATE}`. The decision rule is **imported** from "
         "`scripts/r2_p03_sweep_readout.py`, i.e. identical to the one that judged both prior "
         "campaigns:")
    for metric, (hib, margin, why) in DECISION.items():
        emit(f"- `{metric}` {'↑' if hib else '↓'} margin **{margin}** ({why})")
    emit()
    emit("Both questions are **within-campaign** contrasts — that is why this campaign is 9 runs "
         "and not 3:")
    emit()
    emit(f"- **Q1 `gaussian_th`'s contribution** = `{TREAT}` ÷ `{BASE}`. Those configs differ in "
         "exactly `Training.gaussian_th` (0.7→0.9), pinned by "
         "`tests/test_r2_p03_s6repl_configs.py`.")
    emit(f"- **Q2 replication** = the imported dominance verdict for `{TREAT}` against an "
         f"**in-campaign** `{ANCHOR}` anchor. SWEEP's verdict rested on one campaign, at 33% "
         "rate CV, on a stack whose ratios drift ~20%.")
    emit()
    emit("Pre-declared readings of every outcome: `results/evidence/r2_p03_s6repl.md` §2 "
         "(committed before the first run).")
    emit()
    emit("GO/KILL and narrative direction are the user's call (pre-registration §9). This "
         "report states measurements and mechanical verdicts.")
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
    emit("`keyframes` is descriptive and **required reading**: in SWEEP the dominating rung ran "
         "**16/18/18** against the anchors' **19/19/19**, so part of its rate advantage was less "
         "coverage of the sequence rather than better economy (`r2_p03_sweep.md` §3.4). Whether "
         "that coverage deficit reproduces here is one of the pre-declared secondary readings.")
    emit()

    emit(f"Per-seed `{RATE}`:")
    emit()
    for arm in order:
        vals = series(data, arm, RATE)
        emit(f"- **{arm}**: " + " / ".join(f"{v:.0f}" for v in vals)
             + (f"   (mean {st.mean(vals):.0f}, own sd {sd(vals):.0f})" if len(vals) > 1 else ""))
    emit()

    # ---- Q2: the dominance verdict ------------------------------------------------------
    if ANCHOR not in data:
        emit("**Arm B anchor missing — no dominance verdict possible.**")
        (out_dir / "s6repl_report.md").write_text("\n".join(lines) + "\n")
        return 0

    anchor_rate = series(data, ANCHOR, RATE)
    target = st.mean(anchor_rate)
    anchor_sd = sd(anchor_rate) if len(anchor_rate) > 1 else 0.0
    emit(f"## Q2 — dominance vs the in-campaign arm-B operating point ({target:.0f} Gaussians, "
         f"n={len(anchor_rate)})")
    emit()
    emit("`degradation` is signed so **positive = the arm is worse than B**. An arm dominates "
         "only if it reached B's mean rate AND both degradations are within margin. The "
         "`rate band` column is descriptive: for an arm that missed B's mean, how far away it is "
         "in units of the larger own sd.")
    emit()
    emit("| arm | rate | rate/B | every seed < every B seed? | rate ≤ B? | rate band | " +
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
    emit(f"**Arms dominating B: {len(dominating)}** "
         + (f"({', '.join(dominating)})" if dominating else "(none)"))
    emit()
    s6_verdict = verdicts.get(TREAT)
    if s6_verdict:
        if "DOMINATES" in s6_verdict:
            reading = ("**pre-declared branch R1** — the SWEEP verdict REPLICATES in an "
                       "independent campaign against a fresh anchor.")
        elif "NOT-DOMINATED" in s6_verdict:
            reading = ("**pre-declared branch R3** — S6 reached B's rate but broke a margin. "
                       "This is the claim `r2_p03_sweep.md` §3.2 retracted as a single-seed "
                       "artifact; per §2 that retraction must now be revisited explicitly, not "
                       "silently reversed.")
        else:
            reading = ("**pre-declared branch R2** — the dominance does NOT replicate. SWEEP's "
                       "in-campaign verdict is not deleted (it was a legitimate measurement); "
                       "the honest statement becomes \"dominated in 1 of 2 campaigns\", and the "
                       "trigger for narrative D rests on a non-replicating result.")
        emit(f"**`{TREAT}` (SWEEP's dominating rung, same config file): {s6_verdict}.** "
             f"{reading} See `results/evidence/r2_p03_s6repl.md` §2.")
        emit()

    # ---- Q1: what gaussian_th contributed -----------------------------------------------
    if BASE in data and TREAT in data:
        s6 = series(data, TREAT, RATE)
        d2 = series(data, BASE, RATE)
        f_gth = st.mean(s6) / st.mean(d2)
        own = max(sd(s6) if len(s6) > 1 else 0.0, sd(d2) if len(d2) > 1 else 0.0)
        gap = (st.mean(s6) - st.mean(d2)) / own if own else float("nan")
        n = min(len(s6), len(d2))
        lower = sum(1 for i in range(n) if s6[i] < d2[i])
        emit("## Q1 — `gaussian_th` 0.7→0.9's contribution, measured in-campaign")
        emit()
        emit(f"`{TREAT}` and `{BASE}` differ in **exactly** `Training.gaussian_th` "
             "(`tests/test_r2_p03_s6repl_configs.py`), both at `ttl_keyframes`=1 and "
             "`densify_grad_threshold`=5e-4, both 3 seeds in this campaign. So this ratio is "
             "that one knob's multiplicative effect at that operating point — no cross-campaign "
             "step anywhere in it.")
        emit()
        emit("| quantity | value |")
        emit("|---|---|")
        emit(f"| rate `{BASE}` (no gth) | {st.mean(d2):.0f} ± {sd(d2):.0f} |")
        emit(f"| rate `{TREAT}` (+ gth 0.9) | {st.mean(s6):.0f} ± {sd(s6):.0f} |")
        emit(f"| **multiplicative effect of `gaussian_th`** | **{f_gth:.2f}×** |")
        emit(f"| gap in units of the larger own sd | {gap:+.2f}×sd |")
        emit(f"| per-seed: S6 lower than D2 | {lower}/{n} |")
        emit(f"| every S6 seed below every D2 seed | "
             f"{'yes' if every_seed_below(s6, d2) else 'no'} |")
        emit(f"| ×B (same campaign) | {BASE} {st.mean(d2) / target:.2f}× · "
             f"{TREAT} {st.mean(s6) / target:.2f}× |")
        emit()
        if gap < -BAND_SD:
            q1 = (f"**pre-declared branch (a)** — S6 is clearly below D2 ({gap:+.2f}×sd): the "
                  f"native opacity prune carries a measurable share of S6's dominance "
                  f"({f_gth:.2f}× on the rate axis). The sentence \"only 1 of S6's 3 knobs is a "
                  f"native prune\" must from now on be paired with how much that one knob did.")
        elif abs(gap) <= BAND_SD:
            q1 = (f"**pre-declared branch (b)** — S6 is indistinguishable from D2 "
                  f"({gap:+.2f}×sd, inside the band): `gaussian_th` contributed **nothing "
                  f"measurable** at this operating point. S6's dominance is then the "
                  f"`ttl`+`densify` combination, i.e. DECOMP's D2 row, and the 0.63×-vs-1.07× "
                  f"gap read across campaigns was **drift, not gth**.")
        else:
            q1 = (f"**pre-declared branch (c)** — S6 is clearly ABOVE D2 ({gap:+.2f}×sd): "
                  f"`gaussian_th`=0.9 raised the rate at this operating point. Reported as "
                  f"measured; note SWEEP had `S5_gth090` (that knob alone) at 1.43×B.")
        emit(q1)
        emit()
        emit("Read the ratio as a direction, not an estimate: 3 seeds carry 2 df and this "
             "stack's rate CV runs 5–37%.")
        emit()

    # ---- descriptive contrasts ----------------------------------------------------------
    for ref in (ANCHOR, BASE):
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
    emit("## Candidate ledger (is the pair `gth`-isolated? did the ttl lifecycle degenerate?)")
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
    for arm in CELLS:
        if arm not in raw:
            continue
        promoted = [(raw[arm][s].get("candidate_ledger") or {}).get("promoted")
                    for s in sorted(raw[arm])]
        emit(f"- `{arm}` `promoted` per seed: "
             + "/".join("-" if p is None else str(int(p)) for p in promoted))
    emit()
    emit("Expected signature: **`gaussian_th` acts after insertion**, so S6's candidate ledger "
         "must match D2's — in SWEEP the two `gth` rungs left the ledger unchanged vs A0. If it "
         "moved here, the pair is not `gth`-isolated on the mechanism side and Q1 carries that "
         "caveat. Both arms run `ttl`=1, where DECOMP measured `promoted` = 0 on every seed; if "
         "that degeneracy does not reproduce, the \"the baseline must degenerate into "
         "insert-everything-then-delete-one-keyframe-later\" statement needs qualifying.")
    emit()

    # ---- cross-campaign drift datapoints --------------------------------------------------
    emit("## Cross-campaign reference — RATIOS ONLY, as drift datapoints")
    emit()
    emit("Absolute Gaussian counts drift +12–15% across campaigns on this stack "
         "(`r2_p03_sweep.md` §5) and **ratios themselves drift ~15–20%** "
         "(`r2_p03_decomp.md` §4.5), so each row below is a ratio to **its own in-campaign B "
         "anchor**, labelled with campaign and commit. These rows are here to extend the drift "
         "measurement, **not** to compare arms — every comparison this campaign makes is "
         "in-campaign by construction.")
    emit()
    emit("| campaign | commit | arm | knobs | rate ÷ that campaign's B | n |")
    emit("|---|---|---|---|---|---|")
    for campaign, commit, arm, knobs, ratio, n in PRIOR_RATIOS:
        emit(f"| {campaign} | `{commit}` | {arm} | {knobs} | {ratio} | {n} |")
    for arm in (BASE, TREAT):
        if arm in data:
            vals = series(data, arm, RATE)
            knobs = raw[arm][sorted(raw[arm])[0]].get("knobs") or {}
            knob_txt = ", ".join(f"{k.split('.')[-1]}={v}" for k, v in knobs.items())
            emit(f"| **R2-P03-S6REPL** | *this run* | **{arm}** | {knob_txt} | "
                 f"**{st.mean(vals) / target:.2f}×** | {len(vals)} |")
    emit()
    for arm, prior, label in ((TREAT, 0.63, "R2-P03-SWEEP"), (BASE, 1.07, "R2-P03-DECOMP")):
        if arm not in data:
            continue
        here = st.mean(series(data, arm, RATE)) / target
        drift = (here - prior) / prior * 100.0
        emit(f"- `{arm}`: **{here:.2f}×B here vs {prior:.2f}×B in {label}** — "
             f"{drift:+.0f}% on the ratio. (`D0`'s S2 replicate measured +21%; "
             f"B-vs-A0 read −55.2% / −54.3% / −46.6% across three campaigns.)")
    emit()

    emit("---")
    emit("Post-hoc, non-preregistered (`02-method.md` P0.5 follow-up). Decision rule imported "
         "verbatim from `scripts/r2_p03_sweep_readout.py`; both configs under test are the "
         "frozen files from the campaigns they are being replicated from, by identity. "
         "GO/KILL and narrative remain the user's (prereg §9).")

    report = out_dir / "s6repl_report.md"
    report.write_text("\n".join(lines) + "\n")
    print(f"\nwritten: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
