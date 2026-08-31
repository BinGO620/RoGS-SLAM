#!/usr/bin/env python3
"""Generate the four paper tables (manuscript.md Table 1-4) from run artifacts.

Every number is read directly from a run's tracking_raw.csv; the provenance of
every cell is recorded in a companion CSV + PROVENANCE.md so any printed value
traces back to exactly one run directory.

Data lives on jiangwenheng; sync the small CSVs first:
  rsync -av --include='*/' --include='tracking_raw.csv' --exclude='*' \
      jiangwenheng@172.16.227.24:/home/jiangwenheng/cron/monogs-ours/results/runs/ \
      results/runs_remote_cache/

Outputs (papers/maskfree_bundle/tables/):
  table1_18seq_ate.{md,csv}        Table 1: ATE across 18 sequences, 3 arms + RGD
  table2_mask_necessity.{md,csv}   Table 2: mask necessity N between our two arms
  table3_attribution.{md,csv}      Table 3: EXP53/54 single-variable attribution
  table4_flow_budget.{md,csv}      Table 4: WP-B controlled flow-budget comparison
  PROVENANCE.md                    per-cell run-directory map for all tables
"""
import csv
import glob
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "papers", "maskfree_bundle", "tables")
RUNS = os.path.join(ROOT, "results", "runs_remote_cache")

# Table 1 row order: dynamic groups where our advantage is largest come first
# (crowd, object-only, mixed-mover, person), then TUM dynamic/sitting/static.
SEQORDER = ["crowd", "crowd2", "mv_no_box", "mv_no_box2", "balloon", "balloon2",
            "pt1", "pt2", "f2_person", "f3_wk_hf", "f3_wk_rpy", "f3_wk_xyz",
            "f3_st_hf", "f3_st_rpy", "f3_st_xyz", "f1_desk", "f2_xyz", "f3_office"]
# v2 (manuscript.md, frozen) keeps the legacy row order; --check is version-aware.
LEGACY_SEQORDER = ["f1_desk", "f2_xyz", "f3_office", "f2_person", "f3_st_hf", "f3_st_rpy",
                   "f3_st_xyz", "f3_wk_hf", "f3_wk_rpy", "f3_wk_xyz", "balloon", "balloon2",
                   "crowd", "crowd2", "mv_no_box", "mv_no_box2", "pt1", "pt2"]
GROUP = {
    "f1_desk": "TUM static", "f2_xyz": "TUM static", "f3_office": "TUM static",
    "f2_person": "TUM dynamic",
    "f3_st_hf": "TUM sitting", "f3_st_rpy": "TUM sitting", "f3_st_xyz": "TUM sitting",
    "f3_wk_hf": "TUM walking", "f3_wk_rpy": "TUM walking", "f3_wk_xyz": "TUM walking",
    "balloon": "BONN mixed", "balloon2": "BONN mixed",
    "crowd": "BONN crowd", "crowd2": "BONN crowd",
    "mv_no_box": "BONN object", "mv_no_box2": "BONN object",
    "pt1": "BONN person", "pt2": "BONN person",
}
# Sequences whose published runs are the post-incident FULLKERN reruns; all others
# read from their original roots.  Mirrors scripts/build_18seq_main_table.py.
FULLKERN_SEQS = {"crowd", "crowd2", "f3_wk_rpy", "f1_desk", "f2_person", "f3_office",
                 "f3_st_hf", "f3_st_rpy", "f3_st_xyz", "f3_wk_hf", "f2_xyz"}
HIGH_CV = {"f3_st_hf", "f3_st_rpy", "crowd", "crowd2", "mv_no_box", "mv_no_box2",
           "pt1", "f3_wk_hf"}
# RGD 3-seed reproduction (same protocol as ours), read from the competitor CSV.
RGD_CSV = os.path.join(ROOT, "resources", "02-baselines", "baselines_result",
                       "RGD-SLAM", "tracking_raw.csv")

# mask-free root for the 7 non-FULLKERN sequences:
#   f3_wk_xyz → P6-18SEQ; the other 6 → P6-MASKOFF(seed0) + P6-MASKOFF-3SEED(seeds1/2)
NONFK_MASKFREE = {"balloon", "balloon2", "mv_no_box", "mv_no_box2", "pt1", "pt2"}
# combined root for the 7 non-FULLKERN sequences:
#   balloon/balloon2/mv_no_box/mv_no_box2/pt2 → P2-T_3090 (*_prune_seed*)
#   f3_wk_xyz → P6-MASON (*_combined_seed*)
P2T_SEQS = {"balloon", "balloon2", "mv_no_box", "mv_no_box2", "pt2"}

provenance = []

# Vanilla 3-seed baseline: one CSV with all 18 sequences × 3 seeds
VANILLA_CSV = os.path.join(ROOT, "resources", "02-baselines", "baselines_result",
                           "MonoGS", "tracking_raw.csv")
# The baseline CSV uses raw dataset names for the BONN person-tracking sequences
VANILLA_ALIAS = {"pt1": "person_t", "pt2": "person_t2"}


def read_ate(path):
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    return float(rows[-1]["ate_rmse_cm"])


def vanilla_ate(seq):
    """Return (mean, sd) for a sequence from the single vanilla tracking_raw.csv."""
    lookup = VANILLA_ALIAS.get(seq, seq)
    with open(VANILLA_CSV) as fh:
        rows = [r for r in csv.DictReader(fh) if r["sequence"] == lookup]
    vals = [float(r["ate_rmse_cm"]) for r in rows if r["status"] == "OK"]
    if not vals:
        return None, None
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mean, sd


def rgd_ate(seq):
    """Return (mean, sd) for a sequence from the RGD 3-seed reproduction CSV."""
    lookup = VANILLA_ALIAS.get(seq, seq)
    with open(RGD_CSV, encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if r["sequence"] == lookup]
    vals = [float(r["ate_rmse_cm"]) for r in rows if r["status"] == "OK"]
    if not vals:
        return None, None
    return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)


def seeds_ate(pattern):
    vals, dirs = [], []
    for d in sorted(glob.glob(pattern)):
        p = os.path.join(d, "tables", "tracking_raw.csv")
        if os.path.isfile(p):
            vals.append(read_ate(p))
            dirs.append(os.path.relpath(p, ROOT))
    if not vals:
        return None, None, [], []
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mean, sd, vals, dirs


def fmt(mean, sd):
    if mean is None:
        return "—"
    return f"{mean:.2f}±{sd:.2f}"


def seeds_ate_multi(parent_dirs, pattern):
    """Union of seeds_ate over multiple parent directories."""
    vals, dirs = [], []
    for parent in parent_dirs:
        m, s, v, d = seeds_ate(os.path.join(parent, pattern))
        vals.extend(v)
        dirs.extend(d)
    if not vals:
        return None, None, [], []
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mean, sd, vals, dirs


def combined_dir(seq):
    if seq in FULLKERN_SEQS:
        return os.path.join(RUNS, "P6", "P6-FULLKERN")
    if seq in P2T_SEQS:
        return os.path.join(RUNS, "P2", "P2-T_3090")
    return os.path.join(RUNS, "P6", "P6-MASON")


def maskfree_dirs(seq):
    """Return a list of glob-able parent dirs for the mask-free arm of `seq`."""
    if seq in FULLKERN_SEQS:
        return [os.path.join(RUNS, "P6", "P6-FULLKERN-MASKFREE")]
    if seq == "f3_wk_xyz":
        return [os.path.join(RUNS, "P6", "P6-18SEQ")]
    if seq in NONFK_MASKFREE:
        return [os.path.join(RUNS, "P6", "P6-MASKOFF"),
                os.path.join(RUNS, "P6", "P6-MASKOFF-3SEED")]
    return [os.path.join(RUNS, "P6", "P6-18SEQ")]


# ---------------------------------------------------------------- Table 1 ----
def combined_pattern(seq):
    """Glob filename pattern for the combined arm of `seq`."""
    if seq in P2T_SEQS:
        return f"{seq}_prune_seed*"
    return f"{seq}_combined_seed*"


def table1():
    lines = ["| Sequence | Group | MonoGS | mask-free | combined | RGD |",
             "|---|---|---|---|---|---|"]
    csv_rows = []
    for seq in SEQORDER:
        vm, vs = vanilla_ate(seq)
        mm, ms, _, mdirs = seeds_ate_multi(maskfree_dirs(seq), f"{seq}_maskoff_seed*")
        cm, cs, _, cdirs = seeds_ate(os.path.join(combined_dir(seq), combined_pattern(seq)))
        rm, rs = rgd_ate(seq)

        for d in mdirs + cdirs:
            provenance.append(("table1", seq, d, ""))

        cells = {"vanilla": fmt(vm, vs), "mask-free": fmt(mm, ms),
                 "combined": fmt(cm, cs), "RGD": fmt(rm, rs)}
        means = {"vanilla": vm, "mask-free": mm, "combined": cm, "RGD": rm}
        best = min((m, k) for k, m in means.items() if m is not None)[1]
        ordered = [cells["vanilla"], cells["mask-free"], cells["combined"], cells["RGD"]]
        ordered[["vanilla", "mask-free", "combined", "RGD"].index(best)] = \
            f"**{cells[best]}**"

        dag = "†" if seq in HIGH_CV else ""
        hf = "‡" if seq == "f3_st_hf" else ""
        lines.append(f"| `{seq}` | {GROUP[seq]} | {ordered[0]}{dag} | {ordered[1]} | "
                     f"{ordered[2]}{hf} | {ordered[3]} |")
        csv_rows.append([seq, GROUP[seq], cells["vanilla"], cells["mask-free"],
                         cells["combined"], cells["RGD"], best])
    return "\n".join(lines) + "\n", csv_rows


# ---------------------------------------------------------------- Table 2 ----
def table2():
    seqs = ["mv_no_box2", "mv_no_box", "pt2", "balloon2", "pt1", "balloon"]
    lines = ["| Sequence | mask-free | combined | ratio | reading |",
             "|---|---:|---:|---:|---|"]
    csv_rows = []
    for seq in seqs:
        mm, ms, _, mdirs = seeds_ate_multi(maskfree_dirs(seq), f"{seq}_maskoff_seed*")
        cm, cs, _, cdirs = seeds_ate(os.path.join(combined_dir(seq), combined_pattern(seq)))
        if mm and cm:
            n = mm / cm
            reading = "mask redundant" if n <= 1.2 else ("mask dominant" if n >= 1.5 else "ambiguous")
            if n < 1.0:
                reading += " (mask-free marginally better)"
            ratio = f"{n:.2f}×"
        else:
            reading, ratio = "", "—"
        for d in mdirs + cdirs:
            provenance.append(("table2", seq, d, ""))
        lines.append(f"| `{seq}` | {fmt(mm, ms)} | {fmt(cm, cs)} | {ratio} | {reading} |")
        csv_rows.append([seq, fmt(mm, ms), fmt(cm, cs), ratio, reading])
    return "\n".join(lines) + "\n", csv_rows


# ---------------------------------------------------------------- Table 3 ----
def table3(with_floor=False):
    """with_floor: legacy v2 keeps the constant floor column; v3 moved the floor
    into the caption (manuscript_v3 §5.3, 2026-08-30). The csv always keeps it."""
    pairs = [("mv_no_box", "mvnobox"), ("crowd2", "crowd2")]
    header = "| Sequence | simpler arm | +coverage | +reliability | full arm |"
    if with_floor:
        header += " floor |"
    lines = [header,
             "|---|---:|---:|---:|---:|" + ("---:|" if with_floor else "")]
    csv_rows = []
    for seq, seqp in pairs:
        s_m, s_s, _, s_dirs = seeds_ate(os.path.join(RUNS, "EXP53", "p11phase2",
                                                      f"{seqp}_P11_seed*"))
        c_m, c_s, _, c_dirs = seeds_ate(os.path.join(RUNS, "EXP54", "component_attribution",
                                                      f"{seqp}_dynkf_seed*"))
        r_m, r_s, _, r_dirs = seeds_ate(os.path.join(RUNS, "EXP54", "component_attribution",
                                                      f"{seqp}_reliability_seed*"))
        f_m, f_s, _, f_dirs = seeds_ate(os.path.join(RUNS, "EXP53", "p11phase2",
                                                      f"{seqp}_C_seed*"))
        floor = max(0.43, 0.06 * max(s_m or 0, f_m or 0))
        for d in s_dirs + c_dirs + r_dirs + f_dirs:
            provenance.append(("table3", seq, d, ""))
        # Bold an intervention arm whose mean lands within the floor of the full
        # arm — i.e. it alone recovers the full configuration (manuscript §5.3).
        c_str, r_str = fmt(c_m, c_s), fmt(r_m, r_s)
        if f_m is not None:
            if c_m is not None and abs(c_m - f_m) < floor:
                c_str = f"**{c_str}**"
            if r_m is not None and abs(r_m - f_m) < floor:
                r_str = f"**{r_str}**"
        row = [f"`{seq}`", fmt(s_m, s_s), c_str, r_str, fmt(f_m, f_s)]
        if with_floor:
            row.append(f"{floor:.2f}")
        lines.append("| " + " | ".join(row) + " |")
        csv_rows.append([seq, fmt(s_m, s_s), fmt(c_m, c_s), fmt(r_m, r_s),
                         fmt(f_m, f_s), f"{floor:.2f}"])
    return "\n".join(lines) + "\n", csv_rows


# ---------------------------------------------------------------- Table 4 ----
def table4():
    """WP-B controlled comparison. Reporting convention (caption): mean ± HALF-RANGE,
    not sd; LaTeX $\\pm$ to match the manuscript table formatting."""
    seqs = ["pt1", "pt2", "mv_no_box2", "balloon2"]
    lines = ["| Sequence | vanilla | naive flow-mask | MRCS |",
             "|---|---:|---:|---:|"]
    csv_rows = []

    def fmt_hr(mean, vals):
        if mean is None:
            return "—"
        hr = (max(vals) - min(vals)) / 2.0
        return f"{mean:.2f}$\\pm${hr:.2f}"

    for seq in seqs:
        vm, _, vvals, vdirs = seeds_ate(os.path.join(RUNS, "WPB", "WPB-CONFIRM",
                                                      f"vanilla_{seq}_*"))
        nm, _, nvals, ndirs = seeds_ate(os.path.join(RUNS, "WPB", "WPB-CONFIRM",
                                                      f"flowmask_{seq}_*"))
        mm, _, mvals, mdirs = seeds_ate(os.path.join(RUNS, "WPB", "WPB-CONFIRM",
                                                      f"MRCS_{seq}_*"))
        for d in vdirs + ndirs + mdirs:
            provenance.append(("table4", seq, d, ""))
        cells = {"vanilla": fmt_hr(vm, vvals), "naive": fmt_hr(nm, nvals),
                 "MRCS": fmt_hr(mm, mvals)}
        means = {"vanilla": vm, "naive": nm, "MRCS": mm}
        best = min((m, k) for k, m in means.items() if m is not None)[1]
        cells[best] = f"**{cells[best]}**"
        lines.append(f"| `{seq}` | {cells['vanilla']} | {cells['naive']} | {cells['MRCS']} |")
        csv_rows.append([seq, cells["vanilla"], cells["naive"], cells["MRCS"]])
    return "\n".join(lines) + "\n", csv_rows


# ---------------------------------------------------------------- Table 5 ----
def _eff_one(seed_dir):
    """Read latest efficiency row of one run dir -> (fps, mem_gb, gauss) or None."""
    p = os.path.join(seed_dir, "tables", "efficiency_raw.csv")
    if not os.path.isfile(p):
        return None
    with open(p) as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return None
    r = rows[-1]
    try:
        return (float(r.get("online_fps") or "nan"),
                float(r.get("online_peak_gpu_memory_gb") or "nan"),
                float(r.get("online_num_gaussians") or "nan"))
    except ValueError:
        return None


def table5():
    """Efficiency summary (mean±sd across sequences). Online FPS excludes offline
    RAFT/refinement/rendering; GPU peak memory is cross-hardware comparable."""
    combined_fps, combined_mem, combined_gau = [], [], []
    mf_fps, mf_mem, mf_gau = [], [], []

    for seq in SEQORDER:
        # combined arm: ALL seeds with efficiency data (matches ATE tables' 3-seed rule)
        for sd in sorted(glob.glob(os.path.join(combined_dir(seq), combined_pattern(seq)))):
            e = _eff_one(sd)
            if e and e[0] == e[0]:  # not NaN
                combined_fps.append(e[0]); combined_mem.append(e[1]); combined_gau.append(e[2])
        # mask-free arm: ALL seeds across both roots
        for d in maskfree_dirs(seq):
            for sd in sorted(glob.glob(os.path.join(d, f"{seq}_maskoff_seed*"))):
                e = _eff_one(sd)
                if e and e[0] == e[0]:
                    mf_fps.append(e[0]); mf_mem.append(e[1]); mf_gau.append(e[2])

    # RGD from resources (fps_end_to_end and gpu_memory_gb; same 3090)
    rgd_eff = os.path.join(ROOT, "resources", "02-baselines", "baselines_result",
                           "RGD-SLAM", "efficiency_raw.csv")
    rgd_fps, rgd_mem = [], []
    with open(rgd_eff, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r.get("status") != "OK":
                continue
            try:
                rgd_fps.append(float(r.get("fps_end_to_end") or "nan"))
                rgd_mem.append(float(r.get("gpu_memory_gb") or "nan"))
            except ValueError:
                pass
    rgd_fps = [v for v in rgd_fps if v == v]
    rgd_mem = [v for v in rgd_mem if v == v]

    def mstd(v, fmt="{:.2f}"):
        if not v:
            return "—"
        s = statistics.stdev(v) if len(v) > 1 else 0.0
        return (fmt + "±{:.2f}").format(statistics.mean(v), s)

    def mgau(v):
        return f"{statistics.mean(v):,.0f}" if v else "—"

    lines = ["| arm | online FPS | GPU (GB) | Gaussians | n runs |",
             "|---|---:|---:|---:|---:|"]
    lines.append(f"| combined | {mstd(combined_fps)} | {mstd(combined_mem)} | "
                 f"{mgau(combined_gau)} | {len(combined_fps)} |")
    lines.append(f"| mask-free | {mstd(mf_fps)} | {mstd(mf_mem)} | "
                 f"{mgau(mf_gau)} | {len(mf_fps)} |")
    lines.append(f"| RGD-SLAM | {mstd(rgd_fps)} | {mstd(rgd_mem)} | — | {len(rgd_fps)} |")

    csv_rows = [
        ["combined", mstd(combined_fps), mstd(combined_mem), mgau(combined_gau), str(len(combined_fps))],
        ["mask-free", mstd(mf_fps), mstd(mf_mem), mgau(mf_gau), str(len(mf_fps))],
        ["RGD-SLAM", mstd(rgd_fps), mstd(rgd_mem), "—", str(len(rgd_fps))],
    ]
    return "\n".join(lines) + "\n", csv_rows


def table_multimethod():
    """ATE on the two hardest crowd scenes across every method reproduced under the
    same protocol (18 sequences x 3 seeds each, from resources/02-baselines plus our
    combined arm). ATE is hardware-independent; peak GPU memory is the one
    cross-hardware-comparable efficiency metric and is shown per method where it
    exists (CPU methods: no GPU). Rows are grouped by method class."""
    import statistics

    def per_seq(csv_path, seq_alias, field="ate_rmse_cm"):
        with open(csv_path, encoding="utf-8-sig") as fh:
            vals = [float(r[field]) for r in csv.DictReader(fh)
                    if r["sequence"] == seq_alias]
        m = statistics.mean(vals)
        s = statistics.stdev(vals) if len(vals) > 1 else 0.0
        return m, s

    def gpu_of(method):
        p = os.path.join(ROOT, "resources", "02-baselines", "baselines_result",
                         method, "efficiency_raw.csv")
        if not os.path.isfile(p):
            return None
        vals = []
        with open(p, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r.get("status") != "OK":
                    continue
                try:
                    vals.append(float(r["gpu_memory_gb"]))
                except (ValueError, TypeError):
                    pass
        if not vals:
            return None
        return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)

    def our_combined(seq):
        mean, sd, _v, _d = seeds_ate(os.path.join(combined_dir(seq), combined_pattern(seq)))
        return mean, sd

    BASE = os.path.join(ROOT, "resources", "02-baselines", "baselines_result")

    def cell(method, seq, alias=None, bold=False, second=False):
        if method == "OURS":
            m, s = our_combined(seq)
        else:
            m, s = per_seq(os.path.join(BASE, method, "tracking_raw.csv"),
                           alias or seq)
        txt = f"{m:.2f}±{s:.2f}"
        if m > 1000:
            txt = "div."
        if bold:
            txt = "**" + txt + "**"
        elif second:
            txt = "_" + txt + "_"
        return txt

    def gpu_cell(method, ours=False):
        if method == "OURS":
            g = (4.02, 1.01)  # from table5(); cross-checked below by assert
            md5, _ = table5()
            assert "4.02±1.01" in md5, "GPU memory drifted vs table5"
            return "**4.02±1.01**"
        g = gpu_of(method)
        if g is None:
            return "—"
        return f"{g[0]:.2f}±{g[1]:.2f}"

    spec = [
        ("**MRCS combined (ours)**", "OURS", {}),
        ("RGD-SLAM", "RGD-SLAM", {}),
        ("DG-SLAM", "DG-SLAM", {}),
        ("SplaTAM", "SplaTAM", {}),
        ("Co-SLAM", "Co-SLAM", {}),
        ("WildGS-SLAM (monocular)", "WildGS-SLAM", {"bold_crowd": True, "bold_crowd2": True}),
        ("DynaSLAM", "DynaSLAM", {"second_crowd": True}),
        ("NGD-SLAM", "NGD-SLAM", {"second_crowd2": True}),
        ("RoDyn-SLAM", "RoDyn-SLAM", {}),
        ("DynaGSLAM", "DynaGSLAM", {}),
        ("MonoGS (unmodified backbone)", "MonoGS", {}),
        ("ORB-SLAM3", "ORB_SLAM3", {"alias": {"crowd": "crowd", "crowd2": "crowd2"}}),
    ]
    lines = ["| Method | crowd | crowd2 | peak GPU (GB) |",
             "|---|---:|---:|---:|"]
    for name, method, flags in spec:
        alias = flags.get("alias")
        c1 = cell(method, "crowd", alias and alias.get("crowd"),
                  bold=flags.get("bold_crowd", False), second=flags.get("second_crowd", False))
        c2 = cell(method, "crowd2", alias and alias.get("crowd2"),
                  bold=flags.get("bold_crowd2", False), second=flags.get("second_crowd2", False))
        lines.append(f"| {name} | {c1} | {c2} | {gpu_cell(method)} |")
    return "\n".join(lines) + "\n"


def table_master():
    """Gassidy-style master comparison: methods grouped by class (rows) x five
    BONN dynamic sequences (columns) + class-average + peak GPU memory. All
    numbers from canonical run sources (3 seeds, mean+-sd). The five columns are
    the BONN dynamic scenes; the three BONN sequences not shown here (pt1,
    mv_no_box2, balloon2) and all 10 TUM sequences are in the SI full table, and
    pt1 - where our mask-free configuration fails - is disclosed in Sec. 6."""
    import statistics

    seqs = ["crowd", "crowd2", "mv_no_box", "pt2"]
    alias = {"pt1": "person_t", "pt2": "person_t2"}

    def base_row(method):
        p = os.path.join(ROOT, "resources", "02-baselines", "baselines_result",
                         method, "tracking_raw.csv")
        with open(p, encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        cells, means = [], []
        for s in seqs:
            v = [float(r["ate_rmse_cm"]) for r in rows
                 if r["sequence"] == alias.get(s, s)]
            m = statistics.mean(v)
            sd = statistics.stdev(v) if len(v) > 1 else 0.0
            cells.append((m, sd))
            means.append(m if m <= 1000 else None)  # div. excluded from averages
        return cells, means

    def our_row(kind):
        cells, means = [], []
        for s in seqs:
            if kind == "combined":
                m, sd, _v, _d = seeds_ate(
                    os.path.join(combined_dir(s), combined_pattern(s)))
            else:
                m, sd, _v, _d = seeds_ate_multi(maskfree_dirs(s),
                                                f"{s}_maskoff_seed*")
            cells.append((m, sd))
            means.append(m)
        return cells, means

    def gpu(method, ours=False, kind=None):
        if ours:
            # EXACTLY the same aggregation as table5(): _eff_one over the
            # canonical per-sequence directories, latest row per run dir
            vals = []
            for seq in SEQORDER:
                if kind == "combined":
                    dirs = sorted(glob.glob(os.path.join(
                        combined_dir(seq), combined_pattern(seq))))
                else:
                    dirs = []
                    for d in maskfree_dirs(seq):
                        dirs += sorted(glob.glob(os.path.join(
                            d, f"{seq}_maskoff_seed*")))
                for sd_dir in dirs:
                    e = _eff_one(sd_dir)
                    if e and e[1] == e[1]:
                        vals.append(e[1])
            m = statistics.mean(vals)
            sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
            # consistency guard with Table 4
            ref = 4.02 if kind == "combined" else 3.43
            assert abs(m - ref) < 0.005, f"GPU drifted vs Table 4: {m:.3f}"
            return m, sd
        p = os.path.join(ROOT, "resources", "02-baselines", "baselines_result",
                         method, "efficiency_raw.csv")
        if not os.path.isfile(p):
            return None
        vals = []
        with open(p, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r.get("status") != "OK":
                    continue
                try:
                    v = float(r["gpu_memory_gb"])
                except (ValueError, TypeError):
                    continue
                vals.append(v)
        if not vals:
            return None
        return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)

    def fmt_cell(c, bold=False):
        m, sd = c
        if m > 1000:
            t = "div."
        else:
            t = f"{m:.1f}±{sd:.1f}"   # 0.1 cm: keeps the table inside the text block
        return f"**{t}**" if bold else t

    spec = [
        ("block", "RGB-D 3DGS SLAM"),
        ("row", "RoGS-SLAM combined (ours)", ("OURS", "combined"),
         {"gpu": ("OURS", True, "combined")}),
        ("row", "RoGS-SLAM mask-free (ours)", ("OURS", "maskfree"),
         {"gpu": ("OURS", True, "maskfree")}),
        ("row", "RGD-SLAM", ("RGD-SLAM", None), {}),
        ("row", "DG-SLAM", ("DG-SLAM", None), {}),
        ("row", "SplaTAM", ("SplaTAM", None), {}),
        ("row", "Co-SLAM", ("Co-SLAM", None), {}),
        ("block", "Monocular 3DGS SLAM"),
        ("row", "WildGS-SLAM", ("WildGS-SLAM", None), {}),
        ("block", "Other dynamic SLAM"),
        ("row", "DynaSLAM (CPU)", ("DynaSLAM", None), {}),
        ("row", "NGD-SLAM (no GPU)", ("NGD-SLAM", None), {}),
        ("row", "RoDyn-SLAM (NeRF)", ("RoDyn-SLAM", None), {}),
        ("row", "DynaGSLAM", ("DynaGSLAM", None), {}),
        ("block", "Backbone / classical"),
        ("row", "MonoGS (unmodified)", ("MonoGS", None), {}),
        ("row", "ORB-SLAM3 (CPU)", ("ORB_SLAM3", None),
         {"alias": {"pt2": "person_t2"}}),
    ]

    # pre-compute all rows: best-per-column bolding over real rows only
    allrows = []
    for item in spec:
        if item[0] == "block":
            continue
        _, name, payload, flags = item
        method, k = payload
        if method == "OURS":
            cells, means = our_row(k)
        else:
            cells, means = base_row(method)
        allrows.append((name, method, cells, means, flags))

    best = {s: min(r[3][i] for r in allrows
                   if r[3][i] is not None) for i, s in enumerate(seqs)}

    lines = ["| Method | crowd | crowd2 | mv_no_box | pt2 | Avg. | GPU (GB) |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for item in spec:
        if item[0] == "block":
            lines.append(f"| _{item[1]}_ | | | | | | | |")
            continue
        name = item[1]; flags = item[3]
        for rname, method, cells, means, flags in allrows:
            if rname != name:
                continue
            row_cells = []
            for i, s in enumerate(seqs):
                is_best = means[i] is not None and abs(means[i] - best[s]) < 1e-9
                row_cells.append(fmt_cell(cells[i], bold=is_best))
            avg = statistics.mean([m for m in means if m is not None])
            gpu_spec = flags.get("gpu"); gpu_m = gpu(*gpu_spec) if gpu_spec else gpu(method)
            gpu_txt = "—" if gpu_m is None else f"{gpu_m[0]:.1f}±{gpu_m[1]:.1f}"
            lines.append(f"| {name} | " + " | ".join(row_cells) +
                         f" | {avg:.1f} | {gpu_txt} |")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------- --check ------
TABLE_MARKERS = {
    "table1": ("| Sequence | Group | MonoGS", 4),
    "table2": ("| Sequence | mask-free | combined | ratio | reading |", None),
    "table3": ("| Sequence | simpler arm | +coverage | +reliability | full arm |", None),
    # table4 (WP-B controlled comparison): v3 moved it out of the body (values on
    # Fig. 4, full table in SI), so --check skips it when the header is absent.
    # v2 (manuscript.md) still carries it and is still checked when present.
    "table4": ("| Sequence | vanilla | naive flow-mask | MRCS |", None),
    # v3: master comparison table (Sec. 5.1) and efficiency table (Sec. 5.7);
    # the legacy table1 (18-seq, 4 arms) lives in supplementary S12 for v3.
    "table_master": ("| Method | crowd | crowd2 | mv_no_box | pt2 | Avg. | GPU (GB) |", None),
    "table5": ("| arm | online FPS | GPU (GB) |", None),
}


def extract_manuscript_rows(md_text, header_prefix):
    """Return the data-row lines that follow a table header in manuscript.md."""
    lines = md_text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith(header_prefix):
            rows = []
            for ln2 in lines[i + 2:]:          # skip header + separator
                if ln2.strip().startswith("| `"):
                    rows.append(ln2.strip())
                else:
                    break
            return rows
    return None


def check_against_manuscript(md_path):
    """Compare generated table rows cell-by-cell against manuscript.md.
    Returns list of (table, seq, generated_cell, manuscript_cell) diffs."""
    with open(md_path) as fh:
        md_text = fh.read()
    # version-aware row order: v3 uses the advantage-first order, frozen v2 the legacy one
    global SEQORDER
    if "manuscript_v3" not in md_path:
        SEQORDER = LEGACY_SEQORDER
    gen = {
        "table1": table1()[0].splitlines(),
        "table2": table2()[0].splitlines(),
        "table3": table3(with_floor="manuscript_v3" not in md_path)[0].splitlines(),
        "table4": table4()[0].splitlines(),
        "table_mm": table_multimethod().splitlines(),
        "table_master": table_master().splitlines(),
        "table5": table5()[0].splitlines(),
    }
    diffs = []
    for key, (header_prefix, _) in TABLE_MARKERS.items():
        if key in ("table_mm", "table5", "table_master") and "manuscript_v3" not in md_path:
            continue  # v3-only tables
        if key in ("table_mm", "table5", "table_master"):
            # header-based tables (method names / arm names, not backtick sequences):
            # extract data rows directly and compare normalised text
            def norm(ln):
                return ln.replace("**", "").replace("_", "").strip()
            lines = md_text.splitlines()
            ms_all, found = [], False
            for i, ln in enumerate(lines):
                if ln.strip().startswith(header_prefix):
                    found = True
                    for ln2 in lines[i + 2:]:
                        if ln2.strip().startswith("|") and "---" not in ln2:
                            ms_all.append(norm(ln2))
                        else:
                            break
                    break
            if not found:
                diffs.append((key, "HEADER", f"header '{header_prefix}' not found", ""))
                continue
            g_all = [norm(x) for x in gen[key]
                     if x.strip().startswith("|") and "---" not in x][1:]
            if len(g_all) != len(ms_all):
                diffs.append((key, "ROWCOUNT", f"manuscript {len(ms_all)}, generated {len(g_all)}", ""))
            else:
                for a, b_ in zip(g_all, ms_all):
                    if a != b_:
                        diffs.append((key, "CELL", a, b_))
            continue
        ms_rows = extract_manuscript_rows(md_text, header_prefix)
        g_rows = [ln for ln in gen[key] if ln.strip().startswith("| `")]
        if ms_rows is None:
            if "manuscript_v3" in md_path and key in ("table1", "table2", "table4"):
                # v3: Table 1 replaced by the master comparison (18-seq table moved
                # to S12); old Table 2 in prose + S3; Table 4 on Fig. 4 + SI.
                continue
            if "manuscript_v3" not in md_path and key == "table_master":
                continue  # v2 predates the master table
            diffs.append((key, "HEADER", f"header '{header_prefix}' not found", ""))
            continue
        if key in ("table_mm", "table5"):
            # header-based tables: compare data rows line-by-line, skipping the
            # separator; bold/underline markers are stripped on both sides
            def norm(ln):
                return ln.replace("**", "").replace("_", "").strip()
            g_rows = [norm(x) for x in gen[key]
                      if x.strip().startswith("|") and "---" not in x][1:]
            m_rows = [norm(x) for x in ms_rows
                      if x.strip().startswith("|") and "---" not in x][1:]
            if len(g_rows) != len(m_rows):
                diffs.append((key, "ROWCOUNT", f"manuscript {len(m_rows)}, generated {len(g_rows)}", ""))
            else:
                for a, b_ in zip(g_rows, m_rows):
                    if a != b_:
                        diffs.append((key, "CELL", a, b_))
            continue
        if len(ms_rows) != len(g_rows):
            diffs.append((key, "ROWCOUNT", f"manuscript {len(ms_rows)} rows, "
                          f"generated {len(g_rows)}", ""))
            continue
        for ms_ln, g_ln in zip(ms_rows, g_rows):
            ms_cells = [c.strip() for c in ms_ln.strip("|").split("|")]
            g_cells = [c.strip() for c in g_ln.strip("|").split("|")]
            seq = ms_cells[0]
            for j, (a, b) in enumerate(zip(ms_cells, g_cells)):
                if a != b:
                    diffs.append((key, f"{seq} col{j}", b, a))
    return diffs

# ------------------------------------------------------------------ main ----
def write_pair(stem, md, csv_rows, csv_header):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, stem + ".md"), "w") as fh:
        fh.write(md)
    with open(os.path.join(OUT, stem + ".csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(csv_header)
        w.writerows(csv_rows)
    print(f"  wrote {stem}.md + .csv")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", metavar="MANUSCRIPT", nargs="?", const="auto",
                    help="verify manuscript.md tables match generated output; "
                         "exit 1 on any mismatch")
    args = ap.parse_args()
    if args.check:
        md_path = args.check
        if md_path == "auto":
            md_path = os.path.join(ROOT, "papers", "maskfree_bundle", "manuscript.md")
        diffs = check_against_manuscript(md_path)
        if not diffs:
            print("CHECK OK: manuscript tables match generated values cell-for-cell")
            return
        print(f"CHECK FAILED: {len(diffs)} cell(s) differ between manuscript and "
              f"run-data-derived values:")
        for t, cell, gen, ms in diffs:
            print(f"  {t} {cell}: manuscript='{ms}'  generated='{gen}'")
        raise SystemExit(1)

    print("building paper tables …")
    md, rows = table1()
    write_pair("table1_18seq_ate", md, rows,
               ["seq", "group", "vanilla", "maskfree", "combined", "rgd"])
    md, rows = table2()
    write_pair("table2_mask_necessity", md, rows,
               ["seq", "maskfree", "combined", "ratio", "reading"])
    md, rows = table3()
    write_pair("table3_attribution", md, rows,
               ["seq", "simpler", "coverage", "reliability", "full", "floor"])
    md, rows = table4()
    write_pair("table4_flow_budget", md, rows,
               ["seq", "vanilla", "naive", "mrcs"])
    md, rows = table5()
    write_pair("table5_efficiency", md, rows,
               ["arm", "online_fps", "gpu_gb", "gaussians", "nseq"])

    with open(os.path.join(OUT, "PROVENANCE.md"), "w") as fh:
        fh.write("# Table cell provenance\n\n"
                 "Every row maps one table cell to the run directories its "
                 "mean±sd was computed from.\n\n"
                 "## Per-sequence data-source map (our arms)\n\n"
                 "| sequence | mask-free root | combined root |\n"
                 "|---|---|---|\n")
        for seq in SEQORDER:
            mf = " + ".join(os.path.relpath(d, RUNS) for d in maskfree_dirs(seq))
            cm = os.path.relpath(combined_dir(seq), RUNS)
            fh.write(f"| `{seq}` | `{mf}` | `{cm}` |\n")
        fh.write("\nBaseline columns (not run dirs): `resources/02-baselines/baselines_result/"
                 "MonoGS/tracking_raw.csv` (vanilla, alias pt1→person_t / pt2→person_t2) and "
                 "`resources/02-baselines/baselines_result/RGD-SLAM/tracking_raw.csv` (RGD, "
                 "same aliases). Table 4 arms live under `results/runs_remote_cache/WPB/"
                 "WPB-CONFIRM/` (vanilla_/flowmask_/MRCS_ per sequence); Table 3 arms under "
                 "`EXP53/p11phase2/` (P11_/C_) and `EXP54/component_attribution/` "
                 "(dynkf_/reliability_).\n\n"
                 "## Cell-level run map\n\n"
                 "| table | cell | run dir (relative to repo root) |\n"
                 "|---|---|---|\n")
        for t, cell, d, _ in provenance:
            fh.write(f"| {t} | {cell} | `{d}` |\n")
    print(f"  wrote PROVENANCE.md ({len(provenance)} cells)")


if __name__ == "__main__":
    main()
