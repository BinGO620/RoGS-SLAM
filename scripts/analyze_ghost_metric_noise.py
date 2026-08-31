"""R2-P02 instrument calibration: which ghost headline can actually resolve its claim?

E2 accidentally produced the cleanest thing we have ever had for this question: seven
runs of ONE identical map-mutating algorithm (arms B/C/D/E, whose alpha exit pass never
fired). Their spread is the metric's run-to-run noise floor, measured -- not assumed.

Arm A (prune) is EXCLUDED from every null-band estimate below: it is a genuinely
different algorithm, so including it would fold a real effect into the noise estimate.
It is printed separately for reference only.

An experiment can only resolve an effect larger than this floor. Run after
scripts/eval_vacated_posthoc.py has produced posthoc summaries under both
--out-name posthoc_ghost_excess (unbounded past-union) and --out-name posthoc_freshvac
(recency-windowed).
"""

import glob
import json
import os
import statistics as st
import sys

os.chdir("/data/monogs-ours")
ROOT = "results/runs/R2-P02/R2-P02-E2"


def load(out_name):
    rows = {}
    for p in sorted(glob.glob(f"{ROOT}/*/*/*/*/*/{out_name}/posthoc_summary.json")):
        arm = p.split("R2-P02-E2/")[1].split("/")[0]
        rows[arm] = json.load(open(p))
    return rows


unb = load("posthoc_ghost_excess")
fre = load("posthoc_freshvac")
if not unb or not fre:
    print(f"missing summaries: unbounded={len(unb)} windowed={len(fre)}")
    sys.exit(1)

arms = sorted(set(unb) & set(fre))
NULL = [a for a in arms if not a.startswith("A_")]  # same algorithm, 7 replicates


def col(rows, arm, path):
    node = rows[arm]
    for k in path:
        node = node.get(k) if isinstance(node, dict) else None
        if node is None:
            return float("nan")
    return float(node)


# name -> (source rows, json path, unit, "effect ceiling" description)
METRICS = {
    "vacated_depth_l1 (PRE-REG)": (unb, ("vacated", "depth_l1_pen_cm"), "cm"),
    "vacated_psnr": (unb, ("vacated", "psnr"), "dB"),
    "ghost_excess_depth": (unb, ("ghost_excess", "depth_l1_cm"), "cm"),
    "ghost_excess_psnr": (unb, ("ghost_excess", "psnr_db"), "dB"),
    "freshvac_depth_l1": (fre, ("freshvac", "depth_l1_pen_cm"), "cm"),
    "freshvac_psnr": (fre, ("freshvac", "psnr"), "dB"),
    "freshvac_ssim": (fre, ("freshvac", "ssim"), ""),
    "freshvac_excess_depth": (fre, ("freshvac", "ghost_excess_depth_l1_cm"), "cm"),
    "freshvac_excess_psnr": (fre, ("freshvac", "ghost_excess_psnr_db"), "dB"),
}

print("=" * 96)
print("SUPPORT SIZE -- a 'ghost region' that covers the scene is not a ghost region")
print("=" * 96)
a0 = arms[0]
vac_px = col(unb, a0, ("vacated", "support_px_mean"))
fresh_px = col(fre, a0, ("freshvac", "support_px_mean"))
win = col(fre, a0, ("freshvac", "window_frames"))
print("  image                640x480 = 307200 px")
print(f"  unbounded past-union {vac_px:.0f} px = {vac_px / 307200:.1%} of image")
print(f"  window={win:.0f} frames    {fresh_px:.0f} px = {fresh_px / 307200:.1%} of image")

print()
print("=" * 96)
print(f"NULL BAND over {len(NULL)} replicates of ONE identical algorithm (arm A excluded)")
print("=" * 96)
hdr = f"{'metric':30s} {'mean':>9s} {'sd':>7s} {'spread':>8s}   {'per-run values'}"
print(hdr)
print("-" * len(hdr))
bands = {}
for name, (src, path, unit) in METRICS.items():
    vals = [col(src, a, path) for a in NULL]
    vals = [v for v in vals if v == v]
    if len(vals) < 2:
        continue
    sd, spread = st.stdev(vals), max(vals) - min(vals)
    bands[name] = (st.mean(vals), sd, spread)
    print(f"{name:30s} {st.mean(vals):9.3f} {sd:7.3f} {spread:8.3f} {unit:2s} "
          + " ".join(f"{v:.2f}" for v in sorted(vals)))

print()
print("=" * 96)
print("GHOST DEFICIT vs NOISE -- can the experiment see its own effect?")
print("=" * 96)
print("  The deficit is how much worse the vacated region already renders than its own")
print("  surrounding background: the ceiling on what perfect ghost removal could recover.")
print("  A metric is USABLE only when |deficit| is several times the null sd.")
print()
for name, path, src, unit in (
    ("unbounded  ghost_excess_psnr", ("ghost_excess", "psnr_db"), unb, "dB"),
    ("unbounded  ghost_excess_depth", ("ghost_excess", "depth_l1_cm"), unb, "cm"),
    ("windowed   freshvac_excess_psnr", ("freshvac", "ghost_excess_psnr_db"), fre, "dB"),
    ("windowed   freshvac_excess_depth", ("freshvac", "ghost_excess_depth_l1_cm"), fre, "cm"),
):
    vals = [col(src, a, path) for a in NULL]
    vals = [v for v in vals if v == v]
    if len(vals) < 2:
        continue
    deficit, sd = abs(st.mean(vals)), st.stdev(vals)
    ratio = deficit / sd if sd else float("inf")
    verdict = "USABLE" if ratio >= 3 else ("MARGINAL" if ratio >= 1.5 else "UNUSABLE")
    print(f"  {name:34s} deficit={deficit:6.3f}{unit}  null_sd={sd:5.3f}  "
          f"ratio={ratio:5.1f}x  -> {verdict}")

print()
print("=" * 96)
print("PER-ARM VALUES (arm A shown for reference; B/C/D/E are replicates, not a contrast)")
print("=" * 96)
hdr = (f"{'arm':18s} {'vac_d':>7s} {'vac_p':>7s} {'exc_p':>7s} | "
       f"{'fresh_d':>8s} {'fresh_p':>8s} {'fresh_ssim':>10s} {'fexc_p':>7s}")
print(hdr)
print("-" * len(hdr))
for a in arms:
    print(f"{a:18s} {col(unb, a, ('vacated', 'depth_l1_pen_cm')):7.3f} "
          f"{col(unb, a, ('vacated', 'psnr')):7.3f} "
          f"{col(unb, a, ('ghost_excess', 'psnr_db')):7.3f} | "
          f"{col(fre, a, ('freshvac', 'depth_l1_pen_cm')):8.3f} "
          f"{col(fre, a, ('freshvac', 'psnr')):8.3f} "
          f"{col(fre, a, ('freshvac', 'ssim')):10.4f} "
          f"{col(fre, a, ('freshvac', 'ghost_excess_psnr_db')):7.3f}")

print()
bad = [n for n, (_, sd, _) in bands.items() if "depth" in n]
print("Band-faithfulness of every post-hoc render vs the in-run eval: ",
      all(r["band_check"]["pass"] for r in list(unb.values()) + list(fre.values())))
