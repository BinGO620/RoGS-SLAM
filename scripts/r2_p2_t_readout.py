#!/usr/bin/env python3
"""R2-P02-T (P2-T) readout: the main table + the H-D per-seq ratio + branch.

Decision family IMPORTED from the SWEEP readout (1.56 cm / 0.28 dB), not copied, so the口径
is byte-identical to the four R2-P03 campaigns. What this readout adds:

  * the per-sequence G_def/G_prune ratio (paired, same-seed) with own-sd noise band;
  * the per-seq three-branch call (judgable / indeterminate / reversed) per the H-D prereg
    (a ratio within ~2x the larger own sd is INDETERMINATE);
  * the ATE no-harm band check (deferred ATE >50% worse than prune => flagged);
  * catastrophic-seed flags carried through (never dropped).

It does NOT make the H-D three-branch call (CONFIRMED/INDETERMINATE/FALSIFIED): that is the
user's to read from the prereg, because it involves the cross-seq rank correlation the
prereg reserved. This readout supplies the numbers; the prereg supplies the rule.

Usage: python scripts/r2_p2_t_readout.py [--out-dir results/runs/P2/P2-T]
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

# the decision family + margins, byte-identical to R2-P03 (imported, not copied)
from scripts.r2_p03_sweep_readout import DECISION, RATE  # noqa: E402

OUT_DIR = "results/runs/P2/P2-T"
ANCHOR_DEPTH_MARGIN = DECISION["static_vacated_depth_l1_pen_cm"][1]   # 1.56
ANCHOR_PSNR_MARGIN = DECISION["static_vacated_psnr"][1]                # 0.28
ATE_NOHARM_PCT = 50.0  # prereg §3: deferred ATE >50% worse than prune => flagged
INDET_SD_MULT = 2.0    # prereg §4: |ratio-1| within 2x larger own sd => indeterminate


def load(out_dir: Path) -> dict:
    """{seq: {arm: {seed: row}}} for exit-0 runs."""
    path = out_dir / "p2t_results.jsonl"
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


def _own_sd(vals):
    vals = [v for v in vals if v is not None]
    return st.pstdev(vals) if len(vals) > 1 else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    data = load(out_dir)

    print(f"# P2-T readout — {out_dir}")
    print(f"# decision margins IMPORTED from r2_p03_sweep_readout: "
          f"vac_depth ≤ {ANCHOR_DEPTH_MARGIN}cm, vac_psnr ≤ {ANCHOR_PSNR_MARGIN}dB")
    print(f"# H-D ratio indeterminacy: |G_def/G_prune - 1| ≤ {INDET_SD_MULT}x larger own sd")
    print(f"# ATE no-harm band: deferred ATE > {ATE_NOHARM_PCT}% worse than prune => flagged\n")

    # --- the main table: per (seq, arm): mean ± own sd over seeds ---
    print("## Main table (per-seq, per-arm, 3-seed mean ± own sd)")
    print("| seq | arm | G mean±sd | ATE mean±sd | vac_depth mean | vac_psnr mean | KF |")
    print("|---|---|---|---|---|---|---|")
    for seq in sorted(data):
        for arm in ("prune", "deferred"):
            rows = data[seq].get(arm, {})
            if not rows:
                continue
            gs = [r["metrics"].get(RATE) for r in rows.values()]
            ates = [r["metrics"].get("ate_rmse_cm") for r in rows.values()]
            vds = [r["metrics"].get("static_vacated_depth_l1_pen_cm") for r in rows.values()]
            vps = [r["metrics"].get("static_vacated_psnr") for r in rows.values()]
            kf = [r["metrics"].get("online_num_keyframes") for r in rows.values()]

            def m(xs):
                xs = [x for x in xs if x is not None]
                return st.mean(xs) if xs else None

            def f(x, p=2):
                return f"{x:.{p}f}" if x is not None else "—"
            print(f"| {seq} | {arm} | {f(m(gs),0)}±{f(_own_sd(gs),0)} | "
                  f"{f(m(ates))}±{f(_own_sd(ates))} | {f(m(vds))} | {f(m(vps))} | "
                  f"{[int(k) for k in kf if k is not None]} |")

    # --- the H-D ratio + branch ---
    print("\n## H-D ratio G_def/G_prune (paired, same-seq) + branch")
    print("| seq | G_prune | G_deferred | ratio | own_sd_large | band (2x) | branch | "
          "ATE_def/prune | ATE no-harm |")
    print("|---|---|---|---|---|---|---|---|---|")
    order = []
    for seq in sorted(data):
        pr = data[seq].get("prune", {})
        de = data[seq].get("deferred", {})
        if not pr or not de:
            continue
        # pair by seed
        paired = [(pr[s]["metrics"].get(RATE), de[s]["metrics"].get(RATE))
                  for s in pr if s in de]
        gp = [p[0] for p in paired if p[0] is not None and p[1] is not None]
        gd = [p[1] for p in paired if p[0] is not None and p[1] is not None]
        if not gp:
            continue
        mp, md = st.mean(gp), st.mean(gd)
        sdp, sdd = _own_sd(gp), _own_sd(gd)
        ratio = md / mp if mp else None
        large_sd = max(sdp, sdd)
        band = INDET_SD_MULT * large_sd / mp if mp else None
        # branch
        if ratio is None:
            branch = "—"
        elif abs(ratio - 1) * mp <= INDET_SD_MULT * large_sd:
            branch = "INDETERMINATE"
        elif ratio > 1:
            branch = "judgable (>1, prune better)"
        else:
            branch = "judgable (<1, deferred better)"
        # ATE no-harm
        ates_p = [pr[s]["metrics"].get("ate_rmse_cm") for s in pr]
        ates_d = [de[s]["metrics"].get("ate_rmse_cm") for s in de if s in pr]
        ates_d = [de[s]["metrics"].get("ate_rmse_cm") for s in pr if s in de]
        ap_, ad_ = (st.mean([a for a in ates_p if a is not None]) if any(a is not None for a in ates_p) else None,
                    st.mean([a for a in ates_d if a is not None]) if any(a is not None for a in ates_d) else None)
        ate_ratio = ad_ / ap_ if (ap_ and ap_ > 0.1) else None
        noharm = ("FLAG (>50% worse)" if (ate_ratio and ate_ratio > 1 + ATE_NOHARM_PCT/100)
                  else "ok" if ate_ratio else "—")
        print(f"| {seq} | {mp:.0f} | {md:.0f} | {ratio:.3f} | {large_sd:.0f} | "
              f"{band:.3f} | {branch} | "
              f"{ad_:.2f}/{ap_:.2f} | {noharm} |")
        order.append((seq, ratio))

    print("\n## H-D cross-seq rank correlation (informational; the prereg makes the call)")
    if order:
        print("(match this table's seq order by ratio against "
              "results/evidence/hd_coverage_anchor.md's coverage rank)")
        for seq, r in sorted(order, key=lambda x: x[1] or 0):
            print(f"  {seq}: ratio={r:.3f}")

    print("\n## Decision verdicts will be read from the H-D prereg three-branch rule. "
          "Catastrophic seeds are flagged in the main table, never dropped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
