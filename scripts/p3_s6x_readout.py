#!/usr/bin/env python3
"""P3-S6X readout: does the S6 knob group still beat arm B when the regime can charge for it?

The rate/fidelity half of this readout is **imported**, not re-implemented: ``DECISION`` (the
1.56 cm / 0.28 dB bounded non-inferiority family), ``RATE``, ``degradation``, ``series`` and
``sd`` all come from ``scripts/r2_p03_sweep_readout.py``, so the rule that judged SWEEP, DECOMP,
S6REPL and MASKRATE judges this campaign byte-identically. The ATE no-harm band is imported from
``scripts/r2_p2_t_readout.py`` for the same reason.

What is new is the **ATE column itself**. Across the 46 runs of R2-P03 ``ate_rmse_cm`` was
2.0618 on every single one — an injected RGD trajectory, identical for every arm by construction.
S6's core knob (``ttl_keyframes=1``) drives the prune arm's ``promoted`` to 0 and collapses its
candidate residue 23927 → 5000; under a frozen trajectory that degradation **cannot** reach the
pose. Self-tracked, it can. So this column is not an extra metric, it is the axis the earlier
verdict was never charged on.

Reference points, pre-declared (``results/evidence/p3_s6x_prereg.md`` §2)
------------------------------------------------------------------------
* **Rate + fidelity → against the `deferred` anchor.** That is the operating point S6 dominated;
  the dominance question is unchanged, only the regime is.
* **ATE → against the `prune` anchor** (PRIMARY). S6 *is* the prune arm with three knobs turned;
  the prune anchor isolates what the knobs cost tracking, with the lifecycle held fixed. Reading
  ATE against `deferred` instead would hand S6 free credit on every sequence where deferred is
  already the worse tracker (P2-T: deferred ATE ≥ prune, 6/6) — so the deferred contrast is
  printed as SECONDARY/descriptive and decides nothing.
* **Per sequence, never averaged.** Discipline ⑨: compactness direction flips between sequences
  (balloon 0.511× vs pt2 1.069×), so a cross-sequence mean would read two opposite directions as
  "no difference". A campaign-level statement requires 6/6 agreement; anything else is
  sequence-dependent and only per-sequence statements may be made.
* **Anchors must be in THIS campaign.** A cell whose anchors are missing is printed as
  NOT-READABLE rather than filled from P2-T (cross-campaign ratios drift ~30%).

Usage: python scripts/p3_s6x_readout.py [--out-dir results/runs/P3/P3-S6X]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# rate axis, decision family + margins, and the signed-degradation helper: byte-identical to the
# four R2-P03 campaigns because they are the same objects, imported.
from scripts.r2_p02_preflight_readout import sd, series  # noqa: E402
from scripts.r2_p03_sweep_readout import DECISION, RATE, degradation  # noqa: E402
from scripts.r2_p2_t_readout import ATE_NOHARM_PCT  # noqa: E402  -- the main table's band
from scripts.p3_s6x import ARM_ORDER, RESULTS, SEQS  # noqa: E402

OUT_DIR = "results/runs/P3/P3-S6X"
ATE = "ate_rmse_cm"
TREAT = "s6"
RATE_ANCHOR = "deferred"   # the operating point S6 dominated
ATE_ANCHOR = "prune"       # S6's own untuned base -- the conservative tracking reference
SEEDS_FOR_VERDICT = 3      # discipline ⑤: fewer seeds => screening, no branch


def load(out_dir: Path) -> dict:
    """{seq: {arm: {seed: record}}} for exit-0 runs of THIS campaign only."""
    path = out_dir / RESULTS
    out: dict = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("exit") != 0:
            continue
        out.setdefault(row["seq"], {}).setdefault(row["arm"], {})[int(row["seed"])] = row
    return out


def _metrics(seq_data):
    return {arm: {seed: row.get("metrics", {}) for seed, row in seeds.items()}
            for arm, seeds in seq_data.items()}


def _fmt(vals, places=4):
    if not vals:
        return "—"
    if len(vals) == 1:
        return f"{vals[0]:.{places}g}"
    return f"{st.mean(vals):.{places}g} ± {sd(vals):.3g}"


def _kfs(seq_data, arm):
    return [r.get("keyframes") for r in seq_data.get(arm, {}).values()
            if r.get("keyframes") is not None]


def _paired(seq_data, treat, ctrl, metric):
    """Same-seed pairs (treat, ctrl) — the campaign never compares across seeds."""
    t, c = seq_data.get(treat, {}), seq_data.get(ctrl, {})
    out = []
    for seed in sorted(set(t) & set(c)):
        tv = t[seed]["metrics"].get(metric)
        cv = c[seed]["metrics"].get(metric)
        if isinstance(tv, (int, float)) and isinstance(cv, (int, float)):
            out.append((float(tv), float(cv)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()
    os.chdir(ROOT)
    out_dir = Path(args.out_dir)
    data = load(out_dir)

    lines: list[str] = []

    def emit(text=""):
        print(text)
        lines.append(text)

    emit("# P3-S6X readout — the S6 knob group in the self-tracked regime")
    emit()
    if not data:
        emit(f"no exit-0 runs at {out_dir / RESULTS}")
        return 1
    emit(f"Rate axis `{RATE}` and the decision family are IMPORTED from "
         "`scripts/r2_p03_sweep_readout.py` (unchanged since SWEEP):")
    for metric, (hib, margin, why) in DECISION.items():
        emit(f"- `{metric}` {'↑' if hib else '↓'} margin **{margin}** ({why})")
    emit(f"- `{ATE}` (↓, full-trajectory, `tracking_raw.csv`) no-harm band "
         f"**{ATE_NOHARM_PCT:.0f}%**, imported from `scripts/r2_p2_t_readout.py`. "
         f"PRIMARY reference = the `{ATE_ANCHOR}` anchor; the `{RATE_ANCHOR}` contrast is "
         "descriptive.")
    emit()
    emit("**This column is the campaign.** In R2-P03's 46 runs ATE was the injected constant "
         "2.0618 on every run, so a baseline that bought rate by degrading the map could not be "
         "charged for it. Here it can.")
    emit()
    n_seeds = {len(seeds) for seq in data.values() for seeds in seq.values()}
    max_seeds = max(n_seeds) if n_seeds else 0
    if max_seeds < SEEDS_FOR_VERDICT:
        emit(f"> ⚠ **SCREENING ONLY — {max_seeds} seed(s) on disk.** Discipline ⑤: a rung on the "
             "decision path needs 3 seeds before a conclusion is written down. Everything below "
             "is a DIRECTION, not a branch. (SWEEP's S6 at n=1 once decided a verdict wrongly in "
             "both directions at once.)")
        emit()

    # ---- inventory -------------------------------------------------------------------
    emit("## Runs")
    emit()
    emit("| seq | arm | seeds | min/run | self-tracked | knobs live | activity | keyframes |")
    emit("|---|---|---|---|---|---|---|---|")
    for seq in SEQS:
        if seq not in data:
            continue
        for arm in ARM_ORDER:
            rows = data[seq].get(arm)
            if not rows:
                continue
            rs = [rows[s] for s in sorted(rows)]
            kfs = _kfs(data[seq], arm)
            emit(f"| {seq} | {arm} | {','.join(str(s) for s in sorted(rows))} | "
                 f"{st.mean([r['minutes'] for r in rs]):.1f} | "
                 f"{'yes' if all(r.get('self_tracked') for r in rs) else '**NO**'} | "
                 f"{'yes' if all(r.get('config_echo_ok') for r in rs) else '**NO**'} | "
                 f"{rs[0].get('activity_verdict')} | "
                 f"{'/'.join(str(k) for k in kfs) if kfs else '-'} |")
    emit()

    # ---- the per-sequence table ------------------------------------------------------
    emit("## Per-sequence table (mean ± own sd over seeds)")
    emit()
    cols = [RATE, ATE] + list(DECISION) + ["online_peak_gpu_memory_gb", "online_fps"]
    emit("| seq | arm | n | KF | " + " | ".join(f"`{c}`" for c in cols) + " |")
    emit("|---" * (len(cols) + 4) + "|")
    for seq in SEQS:
        if seq not in data:
            continue
        mv = _metrics(data[seq])
        for arm in ARM_ORDER:
            if arm not in mv:
                continue
            kfs = _kfs(data[seq], arm)
            cells = [_fmt(series(mv, arm, m)) for m in cols]
            emit(f"| {seq} | {arm} | {len(mv[arm])} | "
                 f"{'/'.join(str(k) for k in kfs) if kfs else '-'} | " + " | ".join(cells) + " |")
    emit()
    emit("`keyframes` is an endogenous covariate, reported and never decided on. Both prior "
         "campaigns measured S6 covering the sequence with FEWER keyframes than the anchors "
         "(16/18/18 and 18/18/16 vs 19/19/19), so part of its rate advantage is less coverage — "
         "and under self-tracking the keyframe schedule is a tracking-relevant quantity too. "
         "Any `rate/B` quoted from this table must be quoted with its KF row.")
    emit()

    # ---- the compactness ratio, re-measured in THIS campaign -------------------------
    emit("## Compactness `G_def/G_prune` re-measured in-campaign (the headline quantity)")
    emit()
    emit("| seq | G_prune | G_deferred | G_def/G_prune | per-seed <1 |")
    emit("|---|---|---|---|---|")
    for seq in SEQS:
        pairs = _paired(data[seq], "deferred", "prune", RATE) if seq in data else []
        if not pairs:
            continue
        gd = [p[0] for p in pairs]
        gp = [p[1] for p in pairs]
        below = sum(1 for d, p in pairs if d < p)
        emit(f"| {seq} | {st.mean(gp):.0f} | {st.mean(gd):.0f} | "
             f"{st.mean(gd) / st.mean(gp):.3f}× | {below}/{len(pairs)} |")
    emit()
    emit("Re-measured here rather than carried over from P2-T: same-config ratios on this stack "
         "have drifted +21% / +29% / −23% between campaigns, so the anchor a comparison uses must "
         "live in the same campaign as the comparison.")
    emit()

    # ---- the verdict, per sequence ---------------------------------------------------
    emit(f"## Does `{TREAT}` still dominate `{RATE_ANCHOR}` — and does its ATE hold?")
    emit()
    emit(f"`rate ≤ {RATE_ANCHOR}` and the two fidelity margins are the SWEEP rule verbatim. "
         f"`ATE deg` is signed so **positive = {TREAT} is worse**, measured against the "
         f"`{ATE_ANCHOR}` anchor, band = {ATE_NOHARM_PCT:.0f}% of that anchor's mean.")
    emit()
    header = ["seq", f"rate/{RATE_ANCHOR}", "rate ok?"]
    header += [f"deg `{m.split('static_')[-1]}` (≤{DECISION[m][1]})" for m in DECISION]
    header += [f"ATE {TREAT}/{ATE_ANCHOR}", "ATE ok?", "per-seed ATE worse", "verdict"]
    emit("| " + " | ".join(header) + " |")
    emit("|---" * len(header) + "|")

    tally = {"dominates_and_holds_ate": [], "dominates_but_ate_breach": [],
             "rate_lost": [], "not_readable": []}
    for seq in SEQS:
        if seq not in data:
            continue
        seq_data = data[seq]
        missing = [a for a in (TREAT, RATE_ANCHOR, ATE_ANCHOR) if a not in seq_data]
        if missing:
            tally["not_readable"].append(seq)
            emit(f"| {seq} | " + " | ".join(["—"] * (len(header) - 2))
                 + f" | **NOT READABLE** (missing in-campaign {'/'.join(missing)}) |")
            continue
        mv = _metrics(seq_data)

        rate_t = series(mv, TREAT, RATE)
        rate_c = series(mv, RATE_ANCHOR, RATE)
        rate_ratio = st.mean(rate_t) / st.mean(rate_c) if rate_c and st.mean(rate_c) else None
        rate_ok = bool(rate_ratio is not None and rate_ratio <= 1.0)

        cells = [seq, f"{rate_ratio:.3f}×" if rate_ratio else "—", "yes" if rate_ok else "no"]
        fidelity_ok = True
        for metric, (hib, margin, _) in DECISION.items():
            t, c = series(mv, TREAT, metric), series(mv, RATE_ANCHOR, metric)
            if not t or not c:
                cells.append("—")
                fidelity_ok = False
                continue
            deg = degradation(t, c, hib)
            ok = deg <= margin
            fidelity_ok &= ok
            cells.append(f"{deg:+.3f} {'✓' if ok else '**✗**'}")

        ate_pairs = _paired(seq_data, TREAT, ATE_ANCHOR, ATE)
        if ate_pairs:
            at = st.mean([p[0] for p in ate_pairs])
            ac = st.mean([p[1] for p in ate_pairs])
            ate_ratio = at / ac if ac else None
            ate_ok = bool(ate_ratio is not None and ate_ratio <= 1 + ATE_NOHARM_PCT / 100.0)
            worse = sum(1 for t, c in ate_pairs if t > c)
            cells += [f"{at:.2f}/{ac:.2f} = {ate_ratio:.3f}×" if ate_ratio else "—",
                      "ok" if ate_ok else "**BREACH**", f"{worse}/{len(ate_pairs)}"]
        else:
            ate_ok = False
            cells += ["—", "—", "—"]

        if rate_ok and fidelity_ok and ate_ok:
            verdict = f"**DOMINATES {RATE_ANCHOR}, ATE HOLDS**"
            tally["dominates_and_holds_ate"].append(seq)
        elif rate_ok and fidelity_ok:
            verdict = "**DOMINATES on rate/fidelity, ATE BREACH**"
            tally["dominates_but_ate_breach"].append(seq)
        elif not rate_ok:
            verdict = f"did not reach {RATE_ANCHOR}'s budget"
            tally["rate_lost"].append(seq)
        else:
            verdict = "**NOT-DOMINATED** (reached the budget, lost fidelity)"
            tally["rate_lost"].append(seq)
        cells.append(verdict)
        emit("| " + " | ".join(cells) + " |")
    emit()

    # ---- secondary/descriptive ATE contrast ------------------------------------------
    emit(f"## SECONDARY (descriptive, decides nothing): `{TREAT}` ATE vs `{RATE_ANCHOR}`")
    emit()
    emit("| seq | ATE s6 | ATE deferred | ratio | per-seed s6 worse |")
    emit("|---|---|---|---|---|")
    for seq in SEQS:
        pairs = _paired(data[seq], TREAT, RATE_ANCHOR, ATE) if seq in data else []
        if not pairs:
            continue
        at = st.mean([p[0] for p in pairs])
        ad = st.mean([p[1] for p in pairs])
        worse = sum(1 for t, c in pairs if t > c)
        emit(f"| {seq} | {at:.2f} | {ad:.2f} | {at / ad:.3f}× | {worse}/{len(pairs)} |")
    emit()
    emit("Printed because it is what a reader asks next, NOT as the decision reference: on every "
         "P2-T sequence deferred was the worse tracker (6/6), so this contrast flatters `s6` by "
         "construction.")
    emit()

    # ---- candidate ledger: is the ttl=1 degeneracy still there? -----------------------
    emit("## Candidate ledger — did `ttl=1` collapse the lifecycle here too?")
    emit()
    emit("| seq | arm | candidate_total | promoted | expired | pending_final |")
    emit("|---|---|---|---|---|---|")
    for seq in SEQS:
        if seq not in data:
            continue
        for arm in ARM_ORDER:
            rows = data[seq].get(arm) or {}
            if not rows:
                continue
            led = [r.get("candidate_ledger") or {} for r in rows.values()]
            cells = []
            for key in ("candidate_total", "promoted", "expired", "pending_final"):
                vals = [x.get(key) for x in led if isinstance(x.get(key), (int, float))]
                cells.append(f"{st.mean(vals):.0f}" if vals else "-")
            emit(f"| {seq} | {arm} | " + " | ".join(cells) + " |")
    emit()
    emit("In both frozen-trajectory campaigns `ttl=1` drove `promoted` to 0 on every seed and "
         "collapsed the residue 23927 → 5000. If that degeneracy reproduces here, the mechanism "
         "is the same one and only the regime changed; if it does not, the migration is not "
         "comparing the same intervention and every reading below needs that caveat.")
    emit()

    # ---- campaign-level summary ------------------------------------------------------
    emit("## Campaign-level count (per-sequence, never averaged — discipline ⑨)")
    emit()
    readable = sum(len(v) for k, v in tally.items() if k != "not_readable")
    for key, label in (("dominates_and_holds_ate",
                        f"dominates {RATE_ANCHOR} AND holds ATE"),
                       ("dominates_but_ate_breach",
                        f"dominates {RATE_ANCHOR} on rate/fidelity but BREACHES the ATE band"),
                       ("rate_lost", f"does not dominate {RATE_ANCHOR}"),
                       ("not_readable", "NOT READABLE (anchor missing in-campaign)")):
        seqs = tally[key]
        emit(f"- **{label}: {len(seqs)}/{readable}** "
             + (f"({', '.join(seqs)})" if seqs else "(none)"))
    emit()
    if max_seeds < SEEDS_FOR_VERDICT:
        emit(f"**No branch is called: {max_seeds} seed(s).** These counts are a direction to "
             "report, not a result to write down (discipline ⑤).")
    else:
        emit("A campaign-level statement requires **6/6 agreement**; anything else is a "
             "sequence-dependent boundary and only per-sequence statements may be made "
             "(discipline ⑨ — compactness direction already flips between balloon and pt2).")
    emit()
    emit("---")
    emit("Pre-declared dispositions: `results/evidence/p3_s6x_prereg.md` §2, committed before the "
         "first run. GO/KILL and narrative remain the user's. This report states measurements and "
         "mechanical verdicts only.")

    report = out_dir / "p3s6x_report.md"
    report.write_text("\n".join(lines) + "\n")
    print(f"\nwritten: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
