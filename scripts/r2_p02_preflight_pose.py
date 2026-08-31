#!/usr/bin/env python
"""R2-P02 pre-flight: does freezing the camera trajectory make the ghost metric
able to resolve the arm contrast at all?

Context
-------
R2-P02-E2 is VOID: the alpha exit pass never fired (fixed in ``bd884b8``). Before
paying another ~3.5 h for a 9-run re-run, ``results/evidence/r2_p02_e2.md`` §8
raised a prior question -- *can the instrument resolve anything?* On self-tracked
balloon the pre-registered headline has a **1.559 cm null sd** against a 1.607 cm
claimed effect, and ``ate_rmse_cm`` is **29.97 ± 2.62 cm** -- the pose error is
the same order as the depth errors we call "ghost". The claim under test is map
ADMISSION and is positioned tracker-orthogonal, so measuring it through a 30 cm
trajectory puts the dominant noise inside the one channel the claim disowns.

This pre-flight runs the CHECKPOINT-1 contrast (arm B deferred vs arm D alpha-exit)
on full-length balloon with the trajectory FROZEN, ×3 seeds, and answers three
things at once:

Arm E (``--arms E_exit_fill --phase addon``) appends the 补侧 contrast to a finished
B/D campaign. It became measurable only after this pre-flight showed exit firing on
all three seeds: fill is coupled to the exit delta, so before that it was unreachable
by construction rather than merely inactive. It is also the lever the B/D result calls
for -- F2 found alpha-exit improving the 16% periphery 7x more than the 66% vacated
region, and fill is spatially targeted BY CONSTRUCTION (it seeds only where exit
cleared an occluder that was hiding observed background, i.e. only inside the vacated
region), so unlike an exit threshold it can move the vacated metric alone.

  Q1  how much of the run-to-run noise is the pose channel (per-arm sd over seeds
      vs the measured self-tracked null band);
  Q2  does ``carve`` (mechanism B, needs α < tau_carve = 0.20 **and** obs_count ≥ 3)
      arm over 439 frames -- at 150 frames ``a_min`` was 0.2592 and still falling;
  Q3  does the arm-activity gate pass, i.e. did the treatment treat.

Two regimes (``--pose``):

  ``rgd``  ``Oracle.pose_file`` = RGD's published balloon trajectory, ATE 2.0618 cm.
           **Default.** Pre-registered for E3 (prereg §7), self-validating (the
           injection fail-fast reproduces 2.0618 to 4 dp or the run dies), and its
           control arm was already run on seeds 0/1 in R2-P01-E2 -- so the canary
           has a REAL on-disk reference band instead of a guessed one.
  ``gt``   ``Oracle.gt_pose`` = dataset GT, zero pose error. Maximal isolation,
           no reference anchor, and further from any trajectory a real system has.

Neither can ever be a paper row -- the headline table stays full SLAM (§8.4).

What this script refuses to do
------------------------------
* It does not print GO/KILL. Pre-registration §9 reserves that for the user; this
  prints numbers and mechanical gate verdicts only.
* It aborts the campaign if the seed-0 canary shows an inert treatment arm. That
  is the E2 process failure (§5): an inert arm reached make-or-break because
  "the mechanism did nothing" lived only in a consolelog nobody re-read.
* It never sets ``PYTORCH_CUDA_ALLOC_CONF`` (``expandable_segments:True`` crashes
  MonoGS's frontend/backend CUDA-tensor sharing).

Usage
-----
    python scripts/r2_p02_preflight_pose.py --phase dry               # E0, no GPU
    python scripts/r2_p02_preflight_pose.py --phase canary            # 2 runs, ~46 min
    python scripts/r2_p02_preflight_pose.py --phase rest              # 4 runs, ~92 min
    python scripts/r2_p02_preflight_pose.py --phase report            # no GPU
    # append the 补侧 arm to a finished B/D campaign (no canary re-run):
    python scripts/r2_p02_preflight_pose.py --phase addon --arms E_exit_fill
"""

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import time

ROOT = "/data/monogs-ours"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from scripts.check_arm_activity import check_run  # noqa: E402

PY = "/data/conda_envs/monogs-ours/bin/python"
OUT_ROOT = "results/runs/R2-P02/R2-P02-PREFLIGHT"

R2 = "configs/rgbd/experiments/r2_alpha_lifecycle"
OA = "configs/rgbd/experiments/r2_oracle_admission"

# regime -> arm -> config. Arm B = deferred control, arm D = alpha exit treatment.
# Contract on these five configs is pinned by tests/test_preflight_pose_configs.py.
CFG = {
    "rgd": {
        "B_deferred": f"{OA}/oracle_deferred_balloon.yaml",
        "D_exit": f"{R2}/oracle_alpha_exit_balloon.yaml",
        # Arm E = 补侧. Only measurable once exit fires (fill is coupled to the exit
        # delta), which the B/D pre-flight established on all three seeds. Sole diff
        # vs arm D = AlphaLifecycle.mode, so E-vs-D isolates fill (prereg 4).
        "E_exit_fill": f"{R2}/oracle_alpha_exit_fill_balloon.yaml",
        # Arm A = prune, the original MonoGS insert-then-prune lifecycle. Needed for
        # CHECKPOINT-2 (E vs A = H1's terminal gate, which is otherwise UNRUN rather
        # than failed) and for the compactness corollary, whose load-bearing contrast
        # has always been A-vs-B and has never been pose-controlled. Not reusing
        # R2-P01-E2's on-disk arm A: different campaign and commit, and E2 4 measured
        # a 1.5-2.0 cm cross-campaign shift on this arm with its config unchanged.
        # Sole diff vs arm B = Mapping.lifecycle_mode.
        "A_prune": f"{OA}/oracle_prune_balloon.yaml",
    },
    "gt": {
        "B_deferred": f"{R2}/gtpose_deferred_balloon.yaml",
        "D_exit": f"{R2}/gtpose_alpha_exit_balloon.yaml",
    },
}

# ---------------------------------------------------------------------------
# Reference values. Every number below is measured and on disk -- no guesses.
# The E2 canary failed precisely because its band (15 < vac_depth < 32 cm) was
# invented rather than measured, and admitted a 2 cm miss as PASS (§5).
# ---------------------------------------------------------------------------

# Frozen-trajectory ATE anchor: the injected trajectory is SLAM-seed independent,
# so every rgd run must reproduce this to 4 dp. Source: R2-P01-E2, 12/12 injected
# runs hit their target under the ±0.02 cm fail-fast (evidence/r2_oracle_admission_e2.md).
RGD_ATE_CM, RGD_ATE_TOL_CM = 2.0618, 0.02
# GT poses are injected verbatim, so ATE is numerically zero up to eval rounding.
GT_ATE_MAX_CM = 1.0

# Arm-B (deferred) reference band, balloon, per regime: (seed0, seed1) from
# R2-P01-E2 tables/mapping_raw.csv, mask_type=static. Used only to catch a broken
# harness -- a run landing outside is a red flag to investigate, not a verdict.
REF_B_VAC_DEPTH_CM = {"rgd": (36.043, 41.155), "gt": None}  # gt regime has no prior

# Self-tracked null band, 7 identical-algorithm replicates from the VOID E2 run
# (arm A excluded -- it is a different algorithm). Source: §8.1 of r2_p02_e2.md /
# results/evidence/r2_p02_e2_metric_calibration.txt. Q1 is: how far do the
# per-arm seed sds below fall under these?
SELF_TRACKED_NULL_SD = {
    "static_vacated_depth_l1_pen_cm": 1.559,
    "static_depth_l1_pen_cm": 1.767,
    "static_vacated_psnr": 0.278,
    "static_ghost_excess_psnr_db": 0.327,
    "static_freshvac_ghost_excess_psnr_db": 0.275,
    "static_ghost_excess_depth_l1_cm": 1.941,
    "refined_num_gaussians": 5577.0,
    "ate_rmse_cm": 2.619,
}

MAP_FIELDS = [
    "static_vacated_depth_l1_pen_cm",
    "static_depth_l1_pen_cm",
    "static_vacated_psnr",
    "static_nonvacated_psnr",
    "static_ghost_excess_psnr_db",          # the only calibrated-usable contrast (9.9×)
    "static_freshvac_ghost_excess_psnr_db",  # 30-frame recency window (6.6×)
    "static_ghost_excess_depth_l1_cm",       # kept to re-measure: unusable at 0.1× self-tracked
    "static_psnr",
    "static_ssim",
    "static_vacated_support_px_mean",
    "static_vacated_frames_scored",
]
EFF_FIELDS = [
    "refined_num_gaussians",
    "online_num_gaussians",
    "online_peak_gpu_memory_gb",
    "online_fps",
    "alpha_lifecycle_steps",
    "alpha_lifecycle_skips",
    "alpha_exit_reset_total",
    "alpha_carve_total",
    "alpha_fill_inserted_total",
    # Fill attribution (commit 51252fe). For arm E these are what make a zero fill
    # readable: cleared_px == 0 means the post-exit re-render still shows an opaque
    # surface, cleared_px > 0 with vacated_px == 0 means exit cleared coverage that
    # was not hiding observed background, so there is correctly nothing to fill.
    # NB check_arm_activity.py currently reports FAIL for a fill arm whose exit fired
    # and whose fill inserted nothing -- in `addon` phase that is surfaced, not fatal,
    # and these three columns are how it gets attributed rather than guessed.
    "alpha_fill_steps",
    "alpha_fill_cleared_px_total",
    "alpha_fill_vacated_px_total",
]
TRACK_FIELDS = ["ate_rmse_cm"]  # tracking_raw, full-trajectory (NOT the console KF RMSE)

# Q2 lives in the per-keyframe alpha-ledger log line, which no CSV carries.
LEDGER_KEYS = ("a_min", "a_mean", "obs_max", "obs_ge_min", "a_lt_reset", "a_lt_carve",
               "geom_front", "geom_free", "ev_valid_frac", "resets", "grows")


def log(msg, out_dir):
    line = f"[{time.strftime('%F %T')}] {msg}"
    print(line, flush=True)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "preflight.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_csv_row(path, match=None):
    if not os.path.isfile(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if match:
        rows = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    return rows[-1] if rows else {}


def parse_run(run_root):
    """Metrics from the three raw tables the run wrote under ``<root>/tables/``."""
    tables = os.path.join(run_root, "tables")
    out = {}
    mapping = _read_csv_row(os.path.join(tables, "mapping_raw.csv"),
                            {"mask_type": "static"})
    for key in MAP_FIELDS:
        out[key] = _num(mapping.get(key))
    efficiency = _read_csv_row(os.path.join(tables, "efficiency_raw.csv"))
    for key in EFF_FIELDS:
        out[key] = _num(efficiency.get(key))
    tracking = _read_csv_row(os.path.join(tables, "tracking_raw.csv"))
    for key in TRACK_FIELDS:
        out[key] = _num(tracking.get(key))
    return out


def parse_ledger(console_path):
    """Last ``alpha-ledger`` line -> Q2. Absent for control arms (no lifecycle)."""
    if not os.path.isfile(console_path):
        return {}
    last = None
    with open(console_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if "alpha-ledger" in line:
                last = line
    if last is None:
        return {}
    out = {}
    for key in LEDGER_KEYS:
        hit = re.search(rf"\b{key}=([-\d.eE+]+)", last)
        if hit:
            out[key] = _num(hit.group(1))
    return out


def run_one(arm, seed, pose, out_dir, dry_run=False):
    run_root = os.path.join(out_dir, f"{arm}_seed{seed}")
    console = os.path.join(out_dir, f"{arm}_seed{seed}.consolelog")
    cmd = [PY, "slam.py", "--config", CFG[pose][arm], "--eval",
           "--seed", str(seed), "--results-root", run_root]
    if dry_run:
        print(f"  {' '.join(cmd)}")
        return {"arm": arm, "seed": seed, "cmd": cmd, "dry_run": True}

    log(f"START {arm} seed{seed} pose={pose} -> {run_root}", out_dir)
    env = dict(os.environ)
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    env.pop("PYTORCH_CUDA_ALLOC_CONF", None)  # crashes MonoGS multiprocess CUDA sharing
    started = time.time()
    with open(console, "w", encoding="utf-8") as log_file:
        code = subprocess.call(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=env)
    minutes = (time.time() - started) / 60.0

    metrics = parse_run(run_root)
    verdict, detail = check_run(run_root)
    record = {
        "arm": arm, "seed": seed, "pose": pose, "exit": code,
        "minutes": round(minutes, 1), "run_dir": run_root,
        "activity_verdict": verdict, "activity_detail": detail,
        "metrics": metrics, "ledger": parse_ledger(console),
    }
    log(f"END   {arm} seed{seed} exit={code} {minutes:.1f}min "
        f"ate={metrics.get('ate_rmse_cm')} "
        f"vac_depth={metrics.get('static_vacated_depth_l1_pen_cm')} "
        f"ghost_excess_psnr={metrics.get('static_ghost_excess_psnr_db')} "
        f"activity={verdict}", out_dir)
    with open(os.path.join(out_dir, "preflight_results.jsonl"), "a",
              encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


# ---------------------------------------------------------------------------
# Canary. Every gate here is a HARNESS assertion (did the run do what the config
# says), never a hypothesis assertion -- a treatment that acts and loses is a
# result, and must not be aborted.
# ---------------------------------------------------------------------------

def canary_gates(records, pose, out_dir):
    ok = True

    for record in records:
        if record["exit"] != 0:
            log(f"CANARY FAIL {record['arm']}: exit={record['exit']}", out_dir)
            ok = False

    # G1 -- the pose really is frozen. Without this the whole pre-flight is moot:
    # a silently-refined trajectory reproduces the self-tracked noise regime.
    for record in records:
        ate = record["metrics"].get("ate_rmse_cm")
        if ate is None:
            log(f"CANARY FAIL {record['arm']}: no ate_rmse_cm", out_dir)
            ok = False
        elif pose == "rgd" and abs(ate - RGD_ATE_CM) > RGD_ATE_TOL_CM:
            log(f"CANARY FAIL {record['arm']}: injected ATE {ate:.4f} != "
                f"{RGD_ATE_CM} ±{RGD_ATE_TOL_CM} -- trajectory NOT frozen", out_dir)
            ok = False
        elif pose == "gt" and ate > GT_ATE_MAX_CM:
            log(f"CANARY FAIL {record['arm']}: gt-pose ATE {ate:.4f} > "
                f"{GT_ATE_MAX_CM} cm -- backend refined poses off GT", out_dir)
            ok = False
        else:
            log(f"CANARY ok   {record['arm']}: ATE {ate:.4f} cm (pose frozen)", out_dir)

    # G2 -- THE E2 FIX. The treatment arm must have treated; the control must not.
    for record in records:
        verdict, detail = record["activity_verdict"], record["activity_detail"]
        if record["arm"].startswith("D") and verdict != "PASS":
            log(f"CANARY FAIL {record['arm']}: arm-activity {verdict} -- {detail}",
                out_dir)
            ok = False
        elif record["arm"].startswith("B"):
            acted = sum(record["metrics"].get(k) or 0 for k in
                        ("alpha_exit_reset_total", "alpha_carve_total",
                         "alpha_fill_inserted_total"))
            if verdict != "SKIP" or acted:
                log(f"CANARY FAIL {record['arm']}: control acted "
                    f"({verdict}, {acted} events) -- arms are not isolated", out_dir)
                ok = False
            else:
                log(f"CANARY ok   {record['arm']}: control inert as designed", out_dir)
        else:
            log(f"CANARY ok   {record['arm']}: arm-activity PASS -- {detail}", out_dir)

    # G3 -- support is non-empty, else the headline is scored on nothing.
    for record in records:
        support = record["metrics"].get("static_vacated_support_px_mean")
        frames = record["metrics"].get("static_vacated_frames_scored")
        if not support or not frames:
            log(f"CANARY FAIL {record['arm']}: vacated support={support} "
                f"frames={frames}", out_dir)
            ok = False

    # G4 -- REPORT ONLY (never aborts). The control landing outside its measured
    # R2-P01-E2 band means the harness changed under us; the numbers stay valid
    # as a contrast, so this is a flag for a human, not a stop.
    band = REF_B_VAC_DEPTH_CM.get(pose)
    control = next((r for r in records if r["arm"].startswith("B")), None)
    if band and control:
        value = control["metrics"].get("static_vacated_depth_l1_pen_cm")
        low, high = min(band), max(band)
        span = high - low
        inside = value is not None and (low - span) <= value <= (high + span)
        log(f"CANARY {'ok  ' if inside else 'WARN'} control vac_depth {value} vs "
            f"R2-P01-E2 reference {band} (widened ±{span:.2f}) -- "
            f"{'in band' if inside else 'OUT OF BAND: investigate before trusting'}",
            out_dir)
    return ok


# ---------------------------------------------------------------------------
# Report. Numbers and mechanical verdicts only -- GO/KILL is the user's (§9).
# ---------------------------------------------------------------------------

def report(out_dir):
    path = os.path.join(out_dir, "preflight_results.jsonl")
    if not os.path.isfile(path):
        print(f"no results at {path}")
        return 1
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    if not records:
        print("results file is empty")
        return 1

    arms = sorted({r["arm"] for r in records})
    lines = []

    def emit(text=""):
        print(text)
        lines.append(text)

    pose = records[0].get("pose", "?")
    emit(f"# R2-P02 pre-flight report -- pose={pose}, {len(records)} run(s)")
    emit()

    emit("## Runs")
    emit("| arm | seed | exit | min | activity | ATE cm | vac_depth | ghost_exc_psnr | G_refined |")
    emit("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(records, key=lambda r: (r["arm"], r["seed"])):
        m = r["metrics"]
        emit(f"| {r['arm']} | {r['seed']} | {r['exit']} | {r['minutes']} | "
             f"{r['activity_verdict']} | {m.get('ate_rmse_cm')} | "
             f"{m.get('static_vacated_depth_l1_pen_cm')} | "
             f"{m.get('static_ghost_excess_psnr_db')} | "
             f"{m.get('refined_num_gaussians')} |")
    emit()

    # Q3 first: an inert arm invalidates everything below it.
    inert = [r for r in records
             if r["arm"].startswith("D") and r["activity_verdict"] != "PASS"]
    emit("## Q3 -- did the treatment treat?")
    if inert:
        emit(f"**NO.** {len(inert)} treatment run(s) inert: "
             + "; ".join(f"{r['arm']}/s{r['seed']} {r['activity_detail']}" for r in inert))
        emit("Every D-vs-B contrast below is a replicate comparison, not a contrast.")
    else:
        for r in records:
            if r["arm"].startswith("D"):
                emit(f"- {r['arm']}/s{r['seed']}: {r['activity_detail']}")
    emit()

    # Q1 -- the whole point. Per-arm sd across seeds vs the measured self-tracked null.
    emit("## Q1 -- noise collapse (per-arm sd across seeds vs self-tracked null)")
    emit("Self-tracked null sd = 7 identical-algorithm replicates from the VOID E2 run")
    emit("(r2_p02_e2.md §8.1). A ratio < 1 means the pose channel was carrying that noise.")
    emit()
    emit("| metric | arm | n | mean | sd | self-tracked null sd | ratio |")
    emit("|---|---|---|---|---|---|---|")
    for metric, null_sd in SELF_TRACKED_NULL_SD.items():
        for arm in arms:
            values = [r["metrics"].get(metric) for r in records if r["arm"] == arm]
            values = [v for v in values if v is not None]
            if len(values) < 2:
                continue
            sd = statistics.stdev(values)
            ratio = sd / null_sd if null_sd else float("nan")
            emit(f"| `{metric}` | {arm} | {len(values)} | {statistics.mean(values):.4f} | "
                 f"{sd:.4f} | {null_sd:.4f} | {ratio:.2f}× |")
    emit()
    emit("Caveat: an sd from 3 seeds has 2 df -- it is a crude estimate and a single")
    emit("divergent run moves it a lot. Read order-of-magnitude, not decimals.")
    emit()

    # Effect vs its own noise, on the two metrics calibration found usable.
    #
    # `static_vacated_psnr` leads the list deliberately. The paired contrast
    # (`ghost_excess = vacated - nonvacated`) exists to cancel pose drift, and under a
    # frozen trajectory shared by both arms there is no drift left to cancel -- while its
    # confound stays live: the non-vacated reference is 16% of the support and, in the
    # R2-P01-E2 posthoc rescoring, moved MORE than the vacated signal did (+1.71 dB vs
    # -0.02 dB), flipping the contrast's sign on a neutral vacated region
    # (evidence/r2_p02_preflight_posthoc_note.md §3). In this regime the RAW vacated
    # number is the uncontaminated readout; the contrast is kept only as a cross-check,
    # and `static_nonvacated_psnr` is reported so a repeat of that confound is visible
    # rather than silently folded into the headline.
    emit("## Contrast D vs B, against the pre-flight's own noise")
    emit("| metric | B mean | D mean | diff | pooled sd | \\|d\\|/sd |")
    emit("|---|---|---|---|---|---|")
    for metric in ("static_vacated_psnr", "static_nonvacated_psnr",
                   "static_vacated_depth_l1_pen_cm", "static_ghost_excess_psnr_db",
                   "static_freshvac_ghost_excess_psnr_db", "static_depth_l1_pen_cm",
                   "refined_num_gaussians"):
        b = [r["metrics"].get(metric) for r in records if r["arm"].startswith("B")]
        d = [r["metrics"].get(metric) for r in records if r["arm"].startswith("D")]
        b = [v for v in b if v is not None]
        d = [v for v in d if v is not None]
        if len(b) < 2 or len(d) < 2:
            continue
        pooled = statistics.mean([statistics.stdev(b), statistics.stdev(d)])
        diff = statistics.mean(d) - statistics.mean(b)
        ratio = abs(diff) / pooled if pooled else float("inf")
        emit(f"| `{metric}` | {statistics.mean(b):.4f} | {statistics.mean(d):.4f} | "
             f"{diff:+.4f} | {pooled:.4f} | {ratio:.2f} |")
    emit()

    # Q2 -- carve arming over the full sequence.
    emit("## Q2 -- does carve arm over 439 frames?")
    emit("At 150 frames `a_min` was 0.2592 and still descending; carve needs")
    emit("α < tau_carve = 0.20 **and** obs_count ≥ 3 (r2_p02_e2.md §6).")
    emit()
    emit("| arm | seed | carve_total | reset_total | a_min | a_lt_carve | obs_max | obs_ge_min |")
    emit("|---|---|---|---|---|---|---|---|")
    for r in sorted(records, key=lambda r: (r["arm"], r["seed"])):
        led, m = r["ledger"], r["metrics"]
        if not led and not m.get("alpha_lifecycle_steps"):
            continue
        emit(f"| {r['arm']} | {r['seed']} | {m.get('alpha_carve_total')} | "
             f"{m.get('alpha_exit_reset_total')} | {led.get('a_min')} | "
             f"{led.get('a_lt_carve')} | {led.get('obs_max')} | {led.get('obs_ge_min')} |")
    emit()
    emit("---")
    emit("GO/KILL and narrative direction are the user's call (pre-registration §9).")
    emit("This report states measurements and mechanical gate verdicts only.")

    summary = os.path.join(out_dir, "preflight_report.md")
    with open(summary, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nwritten: {summary}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pose", choices=["rgd", "gt"], default="rgd",
                        help="frozen-trajectory source (default: rgd, the "
                             "pre-registered + anchored one)")
    parser.add_argument(
        "--phase",
        choices=["dry", "canary", "rest", "all", "addon", "report"],
        required=True,
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument(
        "--arms", nargs="+", default=["B_deferred", "D_exit"],
        help="arms to run (default: the CHECKPOINT-1 pair). Use "
             "`--arms E_exit_fill --phase addon` to append the 补侧 arm to a "
             "finished B/D campaign without re-running it.",
    )
    parser.add_argument("--out-dir", default=None,
                        help=f"default: {OUT_ROOT}-<pose>")
    args = parser.parse_args()

    unknown = [a for a in args.arms if a not in CFG[args.pose]]
    if unknown:
        parser.error(f"no {args.pose} config for arm(s) {unknown}; "
                     f"have {sorted(CFG[args.pose])}")

    out_dir = args.out_dir or f"{OUT_ROOT}-{args.pose}"
    if args.phase == "report":
        return report(out_dir)

    canary_plan = [(args.arms[0], args.seeds[0])]
    if len(args.arms) > 1:
        canary_plan.append((args.arms[1], args.seeds[0]))
    rest_plan = [(arm, seed) for seed in args.seeds[1:] for arm in args.arms]
    # `addon` runs every (arm, seed) with NO canary gate re-run: the gates are a
    # property of the harness (pose frozen, support non-zero, control inert), and
    # a finished campaign in this out_dir has already cleared them. Re-running the
    # control seed just to re-clear them would burn GPU and add a replicate that
    # is not part of the pre-registered contrast.
    if args.phase == "addon":
        canary_plan = []
        rest_plan = [(arm, seed) for seed in args.seeds for arm in args.arms]

    if args.phase == "dry":
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        print(f"# DRY RUN -- pose={args.pose} seeds={args.seeds} commit={commit}")
        print(f"# out_dir={out_dir}")
        print(f"# est. {23 * (len(canary_plan) + len(rest_plan))} min "
              f"({len(canary_plan) + len(rest_plan)} runs × ~23 min, balloon 439 frames, 2060)")
        print("\n## canary (aborts the campaign on failure)")
        for arm, seed in canary_plan:
            run_one(arm, seed, args.pose, out_dir, dry_run=True)
        print("\n## rest")
        for arm, seed in rest_plan:
            run_one(arm, seed, args.pose, out_dir, dry_run=True)
        print("\n## canary gates")
        print("  G1 pose frozen : "
              + (f"ate_rmse_cm == {RGD_ATE_CM} ± {RGD_ATE_TOL_CM}"
                 if args.pose == "rgd" else f"ate_rmse_cm < {GT_ATE_MAX_CM}"))
        print("  G2 activity    : D arm-activity PASS; B inert (the E2 fix)")
        print("  G3 support     : vacated support/frames non-zero")
        print(f"  G4 reference   : control vac_depth vs {REF_B_VAC_DEPTH_CM[args.pose]}"
              " (WARN only, never aborts)")
        return 0

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    log(f"==== PREFLIGHT phase={args.phase} pose={args.pose} seeds={args.seeds} "
        f"commit={commit} GPU={os.environ.get('CUDA_VISIBLE_DEVICES', '0')} ====",
        out_dir)

    if args.phase in ("canary", "all"):
        records = [run_one(arm, seed, args.pose, out_dir) for arm, seed in canary_plan]
        if not canary_gates(records, args.pose, out_dir):
            log("==== ABORT: canary failed -> NOT running the remaining seeds. "
                "A pre-flight on a harness that did not do what the config says "
                "answers nothing. ====", out_dir)
            return 2
        log("==== CANARY PASS ====", out_dir)
        if args.phase == "canary":
            return 0

    for arm, seed in rest_plan:
        run_one(arm, seed, args.pose, out_dir)
    log("==== PREFLIGHT RUNS DONE ====", out_dir)
    return report(out_dir)


if __name__ == "__main__":
    sys.exit(main())
