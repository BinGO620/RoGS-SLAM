#!/usr/bin/env python3
"""T3 semantic-alpha verdict — the "保本试水" gates (exp32, 2026-08-20).

PRE-REGISTERED CRITERIA (method_t3_sem.yaml / REVIEW §7.2, arm-internal only -- never
compared against the trunk):

  1. MECHANISM SELF-EVIDENCE (first, and if it fails the rest is not read):
     `alpha_sem_override_total > 0` in backend_timing.json. If it is 0, the three
     per-conjunct counters in the console log (hit / geom_front / override) say which
     link is empty; ATE is not looked at.
  2. MISFIRE KILL-LINE: of the Gaussians the override fired on, the share whose
     projection lands in a GT-STATIC pixel must be <= 5%. The reference is
     `dynamic_mask_gtmc/` -- a frozen GT-pose motion-consistency mask the method never
     sees. Joined OFFLINE here, so the held-out mask stays held out.
  3. RENDER GUARDRAIL: band-PSNR must not degrade relative to the A-off arm.
  4. ATE is an observation, not a criterion.

The misfire rate is computed from `alpha_semantic/overrides.csv` (written at override
time by slam_backend._log_semantic_overrides) because an overridden Gaussian can be
pruned later -- the final map cannot be re-projected to recover where the overrides
landed.

Two honest caveats, stated before any number is read:
  * A GT-MC mask marks pixels whose OBSERVED motion is inconsistent with ego motion.
    A Gaussian floating in front of a person can project onto a pixel the mask calls
    static (e.g. the seam just outside the silhouette). Such a hit counts as a misfire
    here. The measure is therefore conservative, and that is the intended direction for
    a kill-line.
  * The mask is per-frame at the DEPTH stem; the projection is at the keyframe's uid.
    Frames without a mask file are reported separately, never silently dropped.

Usage:
    python scripts/t3_semalpha_verdict.py --root results/runs/T3/T3-SEMALPHA-3090 \
        --datasets-root /data/Datasets
"""

import argparse
import csv
import glob
import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MISFIRE_KILL = 0.05
SEQ_DIR = {                       # campaign alias -> dataset dir tail
    "balloon": ("Bonn", "rgbd_bonn_balloon"),
    "mv_no_box": ("Bonn", "rgbd_bonn_moving_nonobstructing_box"),
    "pt2": ("Bonn", "rgbd_bonn_person_tracking2"),
}


def stem_index(seq_dir):
    """frame index (viewpoint.uid) -> dynamic_mask_gtmc path, via the depth stem that
    both the dataset loader and the mask builder key on."""
    from utils.geometry_metrics import load_tum_associations
    frames = load_tum_associations(seq_dir)
    masks = {os.path.splitext(os.path.basename(p))[0]: p
             for p in glob.glob(os.path.join(seq_dir, "dynamic_mask_gtmc", "*.png"))}
    out = {}
    for i, f in enumerate(frames):
        stem = os.path.splitext(os.path.basename(f["depth_path"]))[0]
        if stem in masks:
            out[i] = masks[stem]
    return out


def run_dirs(root):
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if os.path.isdir(d):
            yield d


def inner_dir(run_dir):
    hits = glob.glob(os.path.join(run_dir, "datasets_*", "*", "seed_*", "*"))
    return sorted(hits)[-1] if hits else None


def read_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def band_psnr(inner):
    bm = read_json(os.path.join(inner, "band_metrics.json")) if inner else None
    if not bm:
        return None
    bands = bm.get("bands") or {}
    return {k: (v.get("psnr") if isinstance(v, dict) else v) for k, v in bands.items()}


def ate_of(run_dir):
    p = os.path.join(run_dir, "tables", "tracking_raw.csv")
    if not os.path.isfile(p):
        return None
    with open(p, newline="") as fh:
        rows = list(csv.DictReader(fh))
    try:
        return float(rows[0]["ate_rmse_cm"])
    except (IndexError, KeyError, ValueError):
        return None


def console_counts(run_dir):
    """hit / geom_front / override totals off the alpha-sem log lines."""
    tot = {"hit": 0, "geom_front": 0, "override": 0, "lines": 0, "skip_no_mask": 0}
    for p in glob.glob(os.path.join(run_dir, "*.consolelog")) + \
             glob.glob(os.path.join(run_dir, "**", "console.log"), recursive=True):
        with open(p, errors="ignore") as fh:
            for line in fh:
                if "alpha-sem KF" not in line:
                    continue
                if "SKIP" in line:
                    tot["skip_no_mask"] += 1
                    continue
                tot["lines"] += 1
                for key in ("hit", "geom_front", "override"):
                    tag = f"{key}="
                    if tag in line:
                        try:
                            tot[key] += int(line.split(tag)[1].split()[0])
                        except (IndexError, ValueError):
                            pass
    return tot


def misfire(inner, seq_alias, datasets_root):
    """Share of overridden Gaussians projecting into GT-STATIC pixels."""
    path = os.path.join(inner, "alpha_semantic", "overrides.csv") if inner else None
    if not path or not os.path.isfile(path):
        return None
    ds, tail = SEQ_DIR[seq_alias]
    seq_dir = os.path.join(datasets_root, ds, tail)
    idx = stem_index(seq_dir)
    cache, n, n_static, n_nomask = {}, 0, 0, 0
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            uid = int(r["kf_uid"])
            mp = idx.get(uid)
            if mp is None:
                n_nomask += 1
                continue
            m = cache.get(mp)
            if m is None:
                m = np.array(Image.open(mp)) > 127
                cache[mp] = m
            h, w = m.shape[:2]
            u = int(round(float(r["u"])))
            v = int(round(float(r["v"])))
            if not (0 <= u < w and 0 <= v < h):
                n_nomask += 1
                continue
            n += 1
            if not m[v, u]:
                n_static += 1
    return {"n_overrides_checked": n, "n_in_gt_static": n_static,
            "misfire_rate": (n_static / n) if n else None,
            "n_unmatched": n_nomask}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results/runs/T3/T3-SEMALPHA-3090")
    ap.add_argument("--datasets-root", default="/data/Datasets")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    rows = {}
    for run in run_dirs(args.root):
        name = os.path.basename(run)
        parts = name.split("_")
        arm = parts[0]
        seq = "_".join(parts[1:-1])
        if seq not in SEQ_DIR:
            continue
        inner = inner_dir(run)
        timing = read_json(os.path.join(inner, "backend_timing.json")) if inner else None
        rows[(seq, arm)] = {
            "run": name,
            "ate_cm": ate_of(run),
            "override_total": (timing or {}).get("alpha_sem_override_total"),
            "carve_total": (timing or {}).get("alpha_carve_total"),
            "reset_total": (timing or {}).get("alpha_exit_reset_total"),
            "counts": console_counts(run),
            "band": band_psnr(inner),
            "misfire": misfire(inner, seq, args.datasets_root) if arm == "sem" else None,
        }

    print("T3 semantic-alpha verdict | arm-internal only (A-sem vs A-off)\n")
    verdicts = {}
    for seq in [s for s in SEQ_DIR if (s, "sem") in rows]:
        sem, off = rows.get((seq, "sem")), rows.get((seq, "off"))
        print(f"=== {seq}")
        c = sem["counts"]
        print(f"  [1 mechanism] override_total={sem['override_total']} "
              f"carve_total={sem['carve_total']} reset_total={sem['reset_total']} | "
              f"console hit={c['hit']} geom_front={c['geom_front']} override={c['override']} "
              f"(kf_lines={c['lines']}, skip_no_mask={c['skip_no_mask']})")
        fired = bool(sem["override_total"])
        mf = sem["misfire"]
        if mf and mf["misfire_rate"] is not None:
            print(f"  [2 misfire  ] {mf['n_in_gt_static']}/{mf['n_overrides_checked']} "
                  f"= {mf['misfire_rate']:.1%} in GT-static (kill-line {MISFIRE_KILL:.0%}) "
                  f"| unmatched={mf['n_unmatched']}")
        else:
            print("  [2 misfire  ] no overrides.csv / nothing to check")
        if sem["band"] and off and off["band"]:
            for k in sorted(set(sem["band"]) & set(off["band"])):
                a, b = sem["band"][k], off["band"][k]
                if a is None or b is None:
                    continue
                print(f"  [3 render   ] band {k:<12} A-sem {a:7.3f} dB  A-off {b:7.3f} dB  "
                      f"delta {a - b:+.3f}")
        else:
            print("  [3 render   ] band_metrics.json missing on one of the arms")
        print(f"  [4 observe  ] ATE A-sem {sem['ate_cm']} cm vs A-off "
              f"{off['ate_cm'] if off else None} cm")
        band_ok = None
        if sem["band"] and off and off["band"]:
            deltas = [sem["band"][k] - off["band"][k]
                      for k in set(sem["band"]) & set(off["band"])
                      if sem["band"][k] is not None and off["band"][k] is not None]
            band_ok = all(d >= 0 for d in deltas) if deltas else None
        verdicts[seq] = {
            "fired": fired,
            "misfire_rate": (mf or {}).get("misfire_rate"),
            "misfire_ok": (None if not mf or mf["misfire_rate"] is None
                           else mf["misfire_rate"] <= MISFIRE_KILL),
            "band_ok": band_ok,
        }
        print()

    print("==== T3 SUMMARY ====")
    for seq, v in verdicts.items():
        print(f"  {seq:<10} fired={v['fired']} misfire="
              f"{'n/a' if v['misfire_rate'] is None else format(v['misfire_rate'], '.1%')} "
              f"({v['misfire_ok']}) band_ok={v['band_ok']}")
    fired_all = all(v["fired"] for v in verdicts.values()) if verdicts else False
    mis_ok = all(v["misfire_ok"] for v in verdicts.values()
                 if v["misfire_ok"] is not None) if verdicts else False
    print(f"\nmechanism fired on every sequence: {fired_all}")
    print(f"misfire kill-line held everywhere : {mis_ok}")
    print("kill-line touched -> stop T3 GPU spend. Both guardrails clean + real "
          "de-ghosting -> apply for the full budget.")

    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"rows": {f"{k[0]}/{k[1]}": v for k, v in rows.items()},
                       "verdicts": verdicts}, fh, indent=2, default=str)
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
