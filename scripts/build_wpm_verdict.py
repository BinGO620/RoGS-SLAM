#!/usr/bin/env python3
"""WP-M readout: mask-only (vanilla + Mask R-CNN) vs combined(mask-ON) vs vanilla.

WHY THIS EXISTS. Every absolute-competitiveness number in the paper comes from
combined(mask-ON). The first reviewer question is therefore "how much of that is just
an off-the-shelf Mask R-CNN bolted onto MonoGS?" -- and until WP-M the repo had no
`vanilla + Mask R-CNN` cell to answer with. This script reads that campaign and applies
the pre-registered decision rule.

**Every criterion here is FROZEN in results/evidence/wpm_maskonly_prereg.md (committed
before any WP-M run started). This script only READS: it never changes the denominator
(fixed 18), never drops a sequence, never truncates ATE, never picks a threshold.**
Failure to complete is evidence, not a reason to shrink the denominator: a sequence that
cannot co-complete 2 seeds is reported in its own M0 row and counted in nothing.

TOP-LEVEL 2x2 this completes:

               |  mask OFF                      |  mask ON
  kernel OFF   |  vanilla (WP-A K0R0L0)         |  mask-only  <- WP-M
  kernel ON    |  Ours-mask-free (main table)   |  Ours-combined (main table)

PROVENANCE. Arms are resolved to the SAME run directories the 18-seq main table quotes,
so the two documents can never disagree about which run a number came from
(see results/evidence/main_table_provenance_audit.md):
  * combined  crowd/crowd2/f3_wk_rpy/f3_wk_xyz/pt1 -> P6/P6-MASON/<seq>_combined_seed<k>
              8 static/low-occlusion seqs           -> P6/P6-MASON-8SEQ/<seq>_combined_seed<k>
              balloon/balloon2/mv_no_box{,2}/pt2    -> P2/P2-T_3090/<seq>_prune_seed<k>
  * mask-only WPM/WPM-MASKONLY/wpm_<seq>_maskonly_seed<k>
  * vanilla   WPA/WPA-FACTORIAL/wpa_<seq>_K0R0L0_seed<k>   (WP-A's 5 sequences ONLY)
Within a run directory a seed that was executed more than once keeps the LATEST run, and
duplicates are listed in the report instead of being averaged away.

Run it where the artifacts live (the 3090 box):
  python scripts/build_wpm_verdict.py --runs-root results/runs
"""

import argparse
import ast
import csv
import glob
import json
import math
import os
import statistics

# ---- frozen constants (prereg SS3/SS4) -----------------------------------------
DELTA = 0.15            # log-scale engineering-equivalence bound (~16% ATE ratio).
                        # NOT a significance threshold -- report sd and per-seed Deltas.
COMPLETION_FRAC = 0.95  # trj_full_final frames / dataset frames
N_SEQ_DENOM = 18        # fixed denominator; post-hoc sequence selection is forbidden

SEQORDER = ["f1_desk", "f2_xyz", "f3_office", "f2_person", "f3_st_hf", "f3_st_rpy",
            "f3_st_xyz", "f3_wk_hf", "f3_wk_rpy", "f3_wk_xyz", "balloon", "balloon2",
            "crowd", "crowd2", "mv_no_box", "mv_no_box2", "pt1", "pt2"]

PTYPE = {
    "f1_desk": "TUM 静态", "f2_xyz": "TUM 静态", "f3_office": "TUM 静态",
    "f2_person": "TUM 动态", "f3_st_hf": "TUM sitting", "f3_st_rpy": "TUM sitting",
    "f3_st_xyz": "TUM sitting", "f3_wk_hf": "TUM walking", "f3_wk_rpy": "TUM walking",
    "f3_wk_xyz": "TUM walking", "balloon": "BONN 混合", "balloon2": "BONN 混合",
    "crowd": "BONN 多人", "crowd2": "BONN 多人", "mv_no_box": "BONN 纯物",
    "mv_no_box2": "BONN 纯物", "pt1": "BONN 纯人", "pt2": "BONN 纯人"}

# combined(mask-ON) source per sequence -- identical to build_18seq_main_table.discover()
P6MASON_COMBINED = {"crowd", "crowd2", "f3_wk_rpy", "f3_wk_xyz", "pt1"}
MASON8_COMBINED = {"f1_desk", "f2_xyz", "f3_office", "f2_person",
                   "f3_st_hf", "f3_st_rpy", "f3_st_xyz", "f3_wk_hf"}
# FULLKERN rerun (silent-no-op incident): these 11 sequences' ORIGINAL combined runs had
# no precomputed flow_raft/, so ReliabilitySignal silently no-op'd -- they were K1R1L0
# wearing the combined label. Reran 3-seed after the runtime gate landed (7b89ff81).
# Routed FIRST, ahead of P6MASON_COMBINED/MASON8_COMBINED, so the tainted originals are
# unreachable from this script. Kept byte-identical to build_18seq_main_table.FULLKERN_SEQS
# (asserted at startup) -- the two documents must never disagree about the source.
# See results/evidence/reliability_signal_silent_noop_incident.md.
FULLKERN_COMBINED = {"crowd", "crowd2", "f3_wk_rpy", "f1_desk", "f2_person", "f3_office",
                     "f3_st_hf", "f3_st_rpy", "f3_st_xyz", "f3_wk_hf", "f2_xyz"}
# vanilla exists ONLY for WP-A's 5 sequences. The main table's MonoGS row for the other
# 13 is an EXTERNAL self-test (different protocol/hardware) and must never be paired here.
VANILLA_SEQS = {"balloon", "mv_no_box", "mv_no_box2", "pt1", "pt2"}

SEEDS = (0, 1, 2)


def run_dir(runs_root, arm, seq, seed):
    if arm == "maskonly":
        return os.path.join(runs_root, "WPM", "WPM-MASKONLY", f"wpm_{seq}_maskonly_seed{seed}")
    if arm == "vanilla":
        return os.path.join(runs_root, "WPA", "WPA-FACTORIAL", f"wpa_{seq}_K0R0L0_seed{seed}")
    if arm == "combined":
        if seq in FULLKERN_COMBINED:
            return os.path.join(runs_root, "P6", "P6-FULLKERN", f"{seq}_combined_seed{seed}")
        if seq in P6MASON_COMBINED:
            return os.path.join(runs_root, "P6", "P6-MASON", f"{seq}_combined_seed{seed}")
        if seq in MASON8_COMBINED:
            return os.path.join(runs_root, "P6", "P6-MASON-8SEQ", f"{seq}_combined_seed{seed}")
        return os.path.join(runs_root, "P2", "P2-T_3090", f"{seq}_prune_seed{seed}")
    raise ValueError(arm)


def pick_timestamp(rd):
    """(chosen_ts, [all completed ts]) -- LATEST wins, duplicates are reported not averaged.

    A timestamp counts as completed when it has config.yml + tracking_raw.csv. If any
    candidate was also offline re-rendered (posthoc_fullframe), the choice is restricted
    to those, which is exactly build_18seq_main_table's rule -- so the combined ATE quoted
    here is the ATE of the very run whose rendering the main table quotes.
    """
    cands = []
    for ts in glob.glob(os.path.join(rd, "datasets_*", "*", "seed_*", "*") + os.sep):
        ts = ts.rstrip(os.sep)
        if not os.path.isfile(os.path.join(ts, "config.yml")):
            continue
        if not os.path.isfile(os.path.join(ts, "tracking_raw.csv")):
            continue
        cands.append(ts)
    if not cands:
        return None, []
    rendered = [t for t in cands
                if os.path.isfile(os.path.join(t, "posthoc_fullframe", "fullframe_summary.json"))]
    pool = rendered or cands
    return max(pool), sorted(cands)


def _num(row, key):
    if not row:
        return None
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


def _last_row(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return None
    return rows[-1] if rows else None


def keyframe_count(ts):
    """Distinct keyframes the backend processed (one source_kf id per keyframe)."""
    path = os.path.join(ts, "deferred_commit_events.csv")
    if not os.path.isfile(path):
        return None
    kfs = set()
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                v = (row.get("source_kf") or "").strip()
                if v:
                    kfs.add(v)
    except Exception:
        return None
    return len(kfs)


def trajectory_frames(ts):
    path = os.path.join(ts, "plot", "trj_full_final.json")
    if not os.path.isfile(path):
        return None
    try:
        ids = json.load(open(path)).get("trj_id")
    except Exception:
        return None
    return len(ids) if isinstance(ids, list) else None


def read_run(rd):
    """One (seq, arm, seed) cell -> measurements, or None when the run does not exist."""
    ts, all_ts = pick_timestamp(rd)
    if ts is None:
        return None
    trk = _last_row(os.path.join(ts, "tracking_raw.csv"))
    eff = _last_row(os.path.join(ts, "efficiency_raw.csv"))
    ate = _num(trk, "ate_rmse_cm")
    if ate is not None and (not math.isfinite(ate) or ate <= 0):
        ate = None  # non-finite/<=0 ATE cannot pair (same rule as wpa_factorial_readout)
    return {
        "ts": ts,
        "n_runs": len(all_ts),
        "all_ts": [os.path.basename(t) for t in all_ts],
        "status": (trk or {}).get("status", ""),
        "ate": ate,
        "rpe": _num(trk, "rpe_trans_rmse_cm"),
        "n_traj": trajectory_frames(ts),
        "n_frames": _num(eff, "num_frames"),
        "kf": keyframe_count(ts),
        "fps": _num(eff, "online_fps"),
        "vram": _num(eff, "online_peak_gpu_memory_gb"),
        "gauss": _num(eff, "online_num_gaussians"),
        "time_s": _num(eff, "online_time_s"),
    }


def collect(runs_root, arms):
    cells, dup = {}, []
    missing_dirs = []
    for seq in SEQORDER:
        for arm in arms:
            if arm == "vanilla" and seq not in VANILLA_SEQS:
                continue
            for seed in SEEDS:
                rd = run_dir(runs_root, arm, seq, seed)
                # INFRASTRUCTURE vs EVIDENCE. The prereg says a run that fails to complete
                # is reported as M0 and counted in nothing -- that is about EXPERIMENTS.
                # A run directory that does not exist AT ALL is a different animal: it
                # means this script is looking where the artifacts aren't (wrong box, un-
                # synced rerun). Left alone every cell degrades to M0 and the script still
                # emits a readout that reads like a legitimate campaign failure.
                # (Observed 2026-08-17: run on cb, where WPM-MASKONLY lives only on the
                # 3090 box -> "18/18 M0-UNRESOLVED", which is a wrong-box error wearing
                # the costume of a result. An earlier version of this guard covered only
                # the combined arm and let that through.)
                # So: absent directory -> hard error; present-but-incomplete -> M0 as prereg.
                if not os.path.isdir(rd):
                    missing_dirs.append(rd)
                    continue
                rec = read_run(rd)
                if rec is None:
                    continue
                cells[(seq, arm, seed)] = rec
                if rec["n_runs"] > 1:
                    dup.append((seq, arm, seed, rec["all_ts"], os.path.basename(rec["ts"])))
    if missing_dirs:
        shown = missing_dirs[:12]
        raise SystemExit(
            f"{len(missing_dirs)} run director(ies) absent -- refusing to emit a readout "
            "(this is a wrong-box/unsynced error, NOT an M0 result):\n    "
            + "\n    ".join(shown)
            + (f"\n    ... and {len(missing_dirs)-len(shown)} more" if len(missing_dirs) > len(shown) else "")
            + "\n  Run this where the artifacts live (the 3090 box).")
    return cells, dup


def seq_total_frames(cells, seq):
    """Dataset length as the loader saw it (efficiency_raw.num_frames == len(trj_id) on a
    fully completed run). Taken as the MAX over every arm/seed of this sequence so a run
    that died early cannot shrink its own completion denominator. Disagreements are
    reported, never silently resolved."""
    vals = [int(r["n_frames"]) for (s, _, _), r in cells.items()
            if s == seq and r["n_frames"]]
    if not vals:
        return None, []
    return max(vals), sorted(set(vals))


def completed(rec, total):
    return (rec is not None and rec["ate"] is not None and rec["n_traj"] is not None
            and total and rec["n_traj"] >= COMPLETION_FRAC * total)


def paired(cells, seq, num_arm, den_arm, total):
    """Per-seed log(ATE_num / ATE_den) over CO-COMPLETED seeds only."""
    out = {}
    for seed in SEEDS:
        a = cells.get((seq, num_arm, seed))
        b = cells.get((seq, den_arm, seed))
        if completed(a, total) and completed(b, total):
            out[seed] = math.log(a["ate"] / b["ate"])
    return out


def classify(deltas):
    """Frozen per-sequence rule (prereg SS4).

    Delta = log(ATE_maskonly / ATE_combined); + = combined better.
      k < 2                      -> M0-UNRESOLVED (counted in nothing, denominator stays 18)
      sd(Delta) > delta          -> INDETERMINATE (neither ">=delta" nor "<delta"; noise is
                                    not read as redundancy)
      mean > +delta              -> combined-better-by-delta
      mean < -delta              -> maskonly-better-by-delta
      |mean| <= delta            -> no-difference
    The |mean| == delta boundary is assigned to no-difference: it makes M2 (the branch that
    shrinks our claim) marginally easier, i.e. the conservative direction. It cannot occur
    in floating point practice; recorded here so the rule is total.
    """
    k = len(deltas)
    if k < 2:
        return {"k": k, "cls": "M0-UNRESOLVED", "mean": None, "sd": None,
                "same_sign": None, "deltas": deltas}
    vals = [deltas[s] for s in sorted(deltas)]
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    same_sign = all(v > 0 for v in vals) or all(v < 0 for v in vals)
    if sd > DELTA:
        cls = "INDETERMINATE"
    elif mean > DELTA:
        cls = "combined-better"
    elif mean < -DELTA:
        cls = "maskonly-better"
    else:
        cls = "no-difference"
    return {"k": k, "cls": cls, "mean": mean, "sd": sd, "same_sign": same_sign,
            "deltas": deltas}


def verdict(rows):
    """Branch selection in the frozen order M0 -> M3 -> M1 -> M2 -> M4 (prereg SS4)."""
    unresolved = [s for s, r in rows.items() if r["cls"] == "M0-UNRESOLVED"]
    indet = [s for s, r in rows.items() if r["cls"] == "INDETERMINATE"]
    comb = [s for s, r in rows.items() if r["cls"] == "combined-better"]
    mask = [s for s, r in rows.items() if r["cls"] == "maskonly-better"]
    same = [s for s, r in rows.items() if r["cls"] == "no-difference"]
    # M3 additionally demands all 3 seeds agree in sign (k == 3 -> "3/3 seed 同号").
    m3 = [s for s in mask if rows[s]["k"] == 3 and rows[s]["same_sign"]]
    # k == 2 cases that would qualify if the rule had said "k/k same sign": reported as a
    # sensitivity line only. The frozen rule says 3/3, so they do NOT enter the count.
    m3_k2 = [s for s in mask if rows[s]["k"] == 2 and rows[s]["same_sign"]]

    # M0 comes FIRST in the frozen order. It is written per-sequence, but if no sequence
    # co-completes 2 seeds there is nothing to branch on -- emitting "M4 heterogeneous"
    # there would report a stratification we never measured. Fail closed instead.
    if not (comb or mask or same or indet):
        branch = "M0-CAMPAIGN-UNRESOLVED"
    elif len(m3) >= 2:
        branch = "M3-kernel-harmful-under-mask"
    elif len(comb) >= 6 and len(mask) <= 1:
        branch = "M1-kernel-adds-on-top-of-mask"
    elif len(same) >= 12:
        branch = "M2-mask-dominates-kernel-redundant"
    else:
        branch = "M4-heterogeneous-stratified"
    return {
        "branch": branch,
        "n_resolved": len(comb) + len(mask) + len(same) + len(indet),
        "counts": {"combined-better": len(comb), "maskonly-better": len(mask),
                   "no-difference": len(same), "INDETERMINATE": len(indet),
                   "M0-UNRESOLVED": len(unresolved), "denominator": N_SEQ_DENOM},
        "seqs": {"combined-better": comb, "maskonly-better": mask, "no-difference": same,
                 "INDETERMINATE": indet, "M0-UNRESOLVED": unresolved,
                 "M3-qualifying": m3, "M3-would-qualify-if-k2-allowed": m3_k2},
    }


def agg(vals, nd=2):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "—"
    m = statistics.mean(vals)
    if len(vals) == 1:
        return f"{m:.{nd}f}"
    return f"{m:.{nd}f}±{statistics.stdev(vals):.{nd}f}"


def assert_fullkern_agrees_with_main_table():
    """The WP-M combined arm and the 18-seq main table must quote the SAME runs.

    Both files carry their own copy of the tainted-sequence list (they are standalone
    scripts, run on different boxes). If the two ever drift, this readout would silently
    compare mask-only against a MIX of reran and tainted combined runs -- the exact
    cross-document disagreement the provenance audit exists to prevent. So: read the
    main table's list and refuse to run on mismatch.

    Read STATICALLY (ast), not by import: build_18seq_main_table loads the competitor
    xlsx at module level, and importing it here would make this readout depend on
    openpyxl + that workbook being present on whatever box runs it.
    """
    mt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_18seq_main_table.py")
    mt_seqs = None
    try:
        with open(mt, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=mt)
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(isinstance(t, ast.Name) and t.id == "FULLKERN_SEQS" for t in node.targets):
                mt_seqs = set(ast.literal_eval(node.value))
    except Exception as exc:
        raise SystemExit(f"cannot cross-check FULLKERN list against the main table: {exc}")
    if mt_seqs is None:
        raise SystemExit(f"FULLKERN_SEQS not found in {mt} -- cannot cross-check.")
    if mt_seqs != FULLKERN_COMBINED:
        raise SystemExit(
            "FULLKERN sequence list DIVERGED between build_wpm_verdict.py and "
            "build_18seq_main_table.py -- refusing to emit a readout.\n"
            f"  only here : {sorted(FULLKERN_COMBINED - mt_seqs)}\n"
            f"  only table: {sorted(mt_seqs - FULLKERN_COMBINED)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs-root", default="results/runs")
    ap.add_argument("--json", default="results/evidence/wpm_maskonly_readout.json")
    ap.add_argument("--md", default="results/evidence/wpm_maskonly_readout.md")
    args = ap.parse_args()

    assert_fullkern_agrees_with_main_table()

    arms = ["maskonly", "combined", "vanilla"]
    cells, dup = collect(args.runs_root, arms)

    totals, total_conflicts = {}, {}
    for seq in SEQORDER:
        t, seen = seq_total_frames(cells, seq)
        totals[seq] = t
        if len(seen) > 1:
            total_conflicts[seq] = seen

    # ---- primary: log(ATE_maskonly / ATE_combined) --------------------------------
    rows = {}
    for seq in SEQORDER:
        rows[seq] = classify(paired(cells, seq, "maskonly", "combined", totals[seq]))
    vd = verdict(rows)

    # ---- secondary: log(ATE_maskonly / ATE_vanilla) + context combined/vanilla ------
    sec, ctx = {}, {}
    for seq in sorted(VANILLA_SEQS):
        sec[seq] = classify(paired(cells, seq, "maskonly", "vanilla", totals[seq]))
        ctx[seq] = classify(paired(cells, seq, "combined", "vanilla", totals[seq]))

    out = {
        "prereg_ref": "results/evidence/wpm_maskonly_prereg.md",
        "delta_log": DELTA, "completion_frac": COMPLETION_FRAC,
        "denominator_sequences": N_SEQ_DENOM,
        "dataset_total_frames": totals,
        "dataset_total_frame_conflicts": total_conflicts,
        "n_runs_found": len(cells),
        "duplicate_seed_runs": dup,
        "primary": {s: rows[s] for s in SEQORDER},
        "verdict": vd,
        "secondary_maskonly_vs_vanilla": sec,
        "context_combined_vs_vanilla": ctx,
        "cells": {f"{s}|{a}|{k}": {kk: vv for kk, vv in r.items() if kk != "all_ts"}
                  for (s, a, k), r in cells.items()},
    }
    os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # ---- markdown report -----------------------------------------------------------
    L = []
    L.append("# WP-M readout —— mask-only(vanilla + Mask R-CNN) vs combined(mask-ON)\n")
    L.append("> 自动生成：`scripts/build_wpm_verdict.py`。判据**跑前冻结**于 "
             "`results/evidence/wpm_maskonly_prereg.md`，本脚本只读不改：分母恒为 18、"
             "不删序列、不截断 ATE。\n")
    L.append(f"> δ = **{DELTA}** log（≈{math.expm1(DELTA)*100:.0f}% ATE 比），"
             f"completion 闸 = `trj_full_final` 帧数 ≥ **{COMPLETION_FRAC:.0%}** × 数据集帧数。"
             "δ 是工程等效界，**不是显著性阈值**。\n")
    L.append(f"> 找到 run：**{len(cells)}**（mask-only 期望 54、combined 54、vanilla 15）。\n")

    L.append(f"\n## 判决：**{vd['branch']}**\n")
    c = vd["counts"]
    L.append(f"- combined 优于 mask-only 达 δ：**{c['combined-better']}/18** "
             f"{vd['seqs']['combined-better'] or ''}")
    L.append(f"- mask-only 优于 combined 达 δ：**{c['maskonly-better']}/18** "
             f"{vd['seqs']['maskonly-better'] or ''}")
    L.append(f"- |Δ| ≤ δ（无差异）：**{c['no-difference']}/18** "
             f"{vd['seqs']['no-difference'] or ''}")
    L.append(f"- INDETERMINATE（seed sd > δ）：**{c['INDETERMINATE']}/18** "
             f"{vd['seqs']['INDETERMINATE'] or ''}")
    L.append(f"- M0 UNRESOLVED（共同完成 seed < 2）：**{c['M0-UNRESOLVED']}/18** "
             f"{vd['seqs']['M0-UNRESOLVED'] or ''}")
    L.append(f"- M3 合格序列（mask-only 更好达 δ **且 3/3 seed 同号**）："
             f"{vd['seqs']['M3-qualifying'] or '无'}"
             + (f"；若允许 k=2 同号则另有 {vd['seqs']['M3-would-qualify-if-k2-allowed']}"
                "（**冻结规则写的是 3/3，故不计入**，仅作敏感性说明）"
                if vd["seqs"]["M3-would-qualify-if-k2-allowed"] else ""))
    L.append("\n判定顺序（冻结）：M0 → M3(≥2 且 3/3 同号) → M1(combined≥6 且 maskonly≤1) "
             "→ M2(无差异≥12) → M4(其余=分层)。\n")

    L.append("\n## 表 1 —— 逐序列 ATE(cm)，3-seed mean±sd\n")
    L.append("| 序列 | 类型 | mask-only | combined(mask-ON) | vanilla | 完成 seed (mo/co/va) |")
    L.append("|---|---|---:|---:|---:|---|")
    for seq in SEQORDER:
        t = totals[seq]
        def cellvals(arm):
            return [cells[(seq, arm, s)]["ate"] for s in SEEDS
                    if (seq, arm, s) in cells and completed(cells[(seq, arm, s)], t)]
        mo, co, va = cellvals("maskonly"), cellvals("combined"), cellvals("vanilla")
        L.append(f"| {seq} | {PTYPE[seq]} | {agg(mo)} | {agg(co)} | "
                 f"{agg(va) if seq in VANILLA_SEQS else 'N/A'} | "
                 f"{len(mo)}/{len(co)}/{len(va) if seq in VANILLA_SEQS else '—'} |")
    L.append("\n> vanilla 只有 WP-A 的 5 个序列（K0R0L0，同 campaign 同协议）。"
             "其余 13 序列主表里的 MonoGS 行是**外部自测值，口径不同，不参与本表配对**。\n")

    L.append("\n## 表 2 —— 主判据：逐序列配对 Δ = log(ATE_mask-only / ATE_combined)\n")
    L.append("> **正 = combined 更好**。逐 seed Δ 全列，均值/sd/同号/判类全列。\n")
    L.append("| 序列 | Δ seed0 | Δ seed1 | Δ seed2 | mean | sd | 比值 | k | 同号 | 判类 |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|:-:|---|")
    for seq in SEQORDER:
        r = rows[seq]
        d = r["deltas"]
        cols = [f"{d[s]:+.3f}" if s in d else "—" for s in SEEDS]
        mean = f"{r['mean']:+.3f}" if r["mean"] is not None else "—"
        sd = f"{r['sd']:.3f}" if r["sd"] is not None else "—"
        ratio = f"{math.exp(r['mean']):.2f}×" if r["mean"] is not None else "—"
        ss = "—" if r["same_sign"] is None else ("是" if r["same_sign"] else "否")
        L.append(f"| {seq} | {cols[0]} | {cols[1]} | {cols[2]} | {mean} | {sd} | "
                 f"{ratio} | {r['k']} | {ss} | {r['cls']} |")

    L.append("\n## 表 3 —— 次判据：单靠 mask 相对 MonoGS 买到多少\n")
    L.append("> `log(ATE_mask-only / ATE_vanilla)`，**负 = mask-only 更好**。"
             "仅 WP-A 的 5 个受控序列（vanilla = 同 campaign 的 K0R0L0）。"
             "右侧 combined/vanilla 列是**非预注册的上下文**，用于把归因拆成两半。\n")
    L.append("| 序列 | mask-only/vanilla mean | 比值 | k | 同号 | ‖ combined/vanilla mean | 比值 | k |")
    L.append("|---|---:|---:|---:|:-:|---|---:|---:|---:|")
    for seq in sorted(VANILLA_SEQS):
        a, b = sec[seq], ctx[seq]
        am = f"{a['mean']:+.3f}" if a["mean"] is not None else "—"
        ar = f"{math.exp(a['mean']):.2f}×" if a["mean"] is not None else "—"
        bm = f"{b['mean']:+.3f}" if b["mean"] is not None else "—"
        br = f"{math.exp(b['mean']):.2f}×" if b["mean"] is not None else "—"
        ss = "—" if a["same_sign"] is None else ("是" if a["same_sign"] else "否")
        L.append(f"| {seq} | {am} | {ar} | {a['k']} | {ss} | ‖ | {bm} | {br} | {b['k']} |")

    L.append("\n## 表 4 —— 预算混淆（预注册要求明报，不得隐藏）\n")
    L.append("> 关掉 K/R/L 同时改变**关键帧预算**，因而改变插入/prune 机会与计算量。"
             "任何 ATE 差异都必须与这张表同读；**定预算对照 = future work，不在本 campaign**。"
             "同一混淆也存在于 WP-A 的 Δ_K。\n")
    L.append("| 序列 | 臂 | 关键帧数 | KF/帧 | 高斯数 | online FPS | peak VRAM(GB) | n |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for seq in SEQORDER:
        for arm, label in (("maskonly", "mask-only"), ("combined", "combined"),
                           ("vanilla", "vanilla")):
            recs = [cells[(seq, arm, s)] for s in SEEDS if (seq, arm, s) in cells]
            if not recs:
                continue
            kfs = [r["kf"] for r in recs if r["kf"]]
            cov = [r["kf"] / r["n_traj"] for r in recs if r["kf"] and r["n_traj"]]
            L.append(f"| {seq} | {label} | {agg(kfs, 0)} | {agg(cov, 3)} | "
                     f"{agg([r['gauss'] for r in recs], 0)} | "
                     f"{agg([r['fps'] for r in recs], 3)} | "
                     f"{agg([r['vram'] for r in recs], 2)} | {len(recs)} |")

    L.append("\n## Provenance / 完整性自检\n")
    no_denom = [s for s in SEQORDER if not totals[s]]
    if no_denom:
        L.append(f"⚠ **{len(no_denom)} 个序列拿不到数据集帧数**（`efficiency_raw.csv` 缺 "
                 "`num_frames`）⇒ completion 闸无分母。按**fail-closed**处理：这些序列的 run "
                 "一律不算完成，落 M0 UNRESOLVED，**不允许**用观测到的最长轨迹当分母"
                 "（若全部 run 都截断，那样会把截断当完成）：")
        L.append(f"  - {', '.join(no_denom)}")
    if total_conflicts:
        L.append("⚠ 以下序列各 run 报告的数据集帧数不一致（取 max 作 completion 分母，"
                 "并在此明列，不静默）：")
        for seq, seen in sorted(total_conflicts.items()):
            L.append(f"  - `{seq}`：{seen}")
    else:
        L.append("✅ 每个序列的数据集帧数在全部 run 上一致，completion 分母无歧义。")
    if dup:
        L.append(f"\n⚠ **{len(dup)} 个 (序列,臂,seed) 目录含一个以上已完成 run**，"
                 "本表**只取最新那次**（与主表同规则），旧次不并入均值：")
        for seq, arm, seed, stamps, chosen in sorted(dup):
            L.append(f"  - `{seq}/{arm}/seed{seed}`：{len(stamps)} 次 —— "
                     f"{', '.join(stamps)}（取 `{chosen}`）")
        L.append("  同 seed 重复运行之间的差异是**运行间非确定性**，"
                 "见 `main_table_provenance_audit.md`。")
    else:
        L.append("\n✅ 每个 (序列, 臂, seed) 恰好一个已完成 run。")
    L.append("")

    with open(args.md, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"branch={vd['branch']}  counts={vd['counts']}")
    print(f"wrote {args.json} + {args.md}")


if __name__ == "__main__":
    main()
