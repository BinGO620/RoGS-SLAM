#!/usr/bin/env python3
"""Collect PBA + insertion-channel rendering results into one record set.

Scans both campaign roots so all four cells of the 2x2 are covered:
  results/runs/PBA/                      eboth / PBA(mapping_off) / tracking_only / maskfree
  results/runs/T2/T2-QUOTA-3090/         balloon's eboth + maskfree live here
"""
import json, os, glob, re

ROOTS = ("results/runs/PBA", "results/runs/T2/T2-QUOTA-3090")


def _arm(run_name):
    # order matters: "tracking_only" must be tested before the looser matches
    if "tracking_only" in run_name:
        return "tracking_only"
    if "mapping_off" in run_name:
        return "PBA"
    if "maskfree" in run_name:
        return "maskfree"
    if "eboth" in run_name:
        return "eboth"
    return run_name


def _seq(run_name):
    # f3_wk_xyz before the shorter tokens; mv_no_box before mv_no_box2 is not an issue here
    for s in ("f3_wk_xyz", "mv_no_box", "balloon", "pt1", "crowd2", "f2_xyz", "f3_st_hf"):
        if s in run_name:
            return s
    return "unknown"


results = []
seen = set()
for root in ROOTS:
    for f in sorted(glob.glob(os.path.join(root, "**", "posthoc_fullframe",
                                           "fullframe_summary.json"), recursive=True)):
        parts = f.split(os.sep)
        # run dir = the component right before datasets_*
        try:
            di = next(i for i, p in enumerate(parts) if p.startswith("datasets_"))
        except StopIteration:
            continue
        run_name = parts[di - 1]
        arm, seq = _arm(run_name), _seq(run_name)
        sm = re.search(r"seed(\d+)", run_name)
        seed = int(sm.group(1)) if sm else -1
        key = (arm, seq, seed)
        if key in seen:          # keep the first (roots are ordered by preference)
            continue
        seen.add(key)

        with open(f) as fh:
            d = json.load(fh)
        ff = d.get("fullframe", {})
        results.append({
            "arm": arm, "seq": seq, "seed": seed,
            "psnr": ff.get("psnr"), "ssim": ff.get("ssim"),
            "lpips": ff.get("lpips"), "depth_l1": ff.get("depth_l1_cm"),
            "frames": ff.get("frames_scored", 0),
            "n_gaussians": d.get("n_gaussians"),
        })

print(f"{'Arm':<15} {'Seq':<12} {'Seed':<5} {'PSNR':>8} {'SSIM':>8} {'LPIPS':>8} {'D-L1':>8} {'Frames':>6}")
print('-' * 78)
for r in sorted(results, key=lambda x: (x['seq'], x['arm'], x['seed'])):
    def _f(v, p):
        return f"{v:.{p}f}" if v is not None else "N/A"
    print(f"{r['arm']:<15} {r['seq']:<12} {r['seed']:<5} {_f(r['psnr'],4):>8} "
          f"{_f(r['ssim'],4):>8} {_f(r['lpips'],4):>8} {_f(r['depth_l1'],4):>8} {r['frames']:>6}")

with open('results/evidence/pba_rendering_metrics.json', 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nSaved {len(results)} records to results/evidence/pba_rendering_metrics.json")
