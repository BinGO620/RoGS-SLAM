#!/usr/bin/env python3
"""Extract posthoc_fullframe metrics from all runs on jiangwenheng, compute 3-seed means."""
import json, re, sys, os
from collections import defaultdict
import subprocess

# Find all posthoc_fullframe directories
result = subprocess.run(
    ["ssh", "jiangwenheng@172.16.227.24",
     "find /home/jiangwenheng/cron/monogs-ours/results/runs -name 'fullframe_summary.json' -path '*/posthoc_fullframe/*' | sort"],
    capture_output=True, text=True, timeout=30
)

files = result.stdout.strip().split('\n')
print(f"Found {len(files)} posthoc files")

# Parse all
records = []
for fpath in files:
    if not fpath.strip():
        continue
    # Read JSON from remote
    r = subprocess.run(
        ["ssh", "jiangwenheng@172.16.227.24", f"cat {fpath}"],
        capture_output=True, text=True, timeout=15
    )
    try:
        d = json.loads(r.stdout)
    except:
        continue

    # Extract method, sequence, seed from run_dir
    run_dir = d.get("run_dir", "")
    method_raw = d.get("method", "")

    # Parse: .../METHOD_SEED/datasets_*/SEQ/seed_N/TIMESTAMP
    m = re.search(r'/([^/]+)/datasets_', run_dir)
    run_name = m.group(1) if m else ""

    # Determine method category
    if "maskoff" in run_name or "maskfree" in run_name:
        method = "mask-free"
    elif "mason_combined" in run_name or "maskonly" in run_name or "combined" in run_name:
        method = "combined"
    elif "vanilla" in run_name or "prune_seed" in run_name:
        method = "vanilla"
    else:
        method = method_raw

    # Extract seed
    sm = re.search(r'seed(\d+)', run_name)
    seed = int(sm.group(1)) if sm else -1

    # Extract sequence name (human-readable)
    seq = d.get("sequence", "")
    # Clean: p2s_combined_prune_balloon -> balloon, p6_maskoff_prune_f1_desk -> f1_desk, etc.
    seq_clean = seq
    for prefix in ["p2s_combined_prune_", "p6_maskoff_prune_", "p6_mason_combined_",
                    "p5_vanilla_prune_", "wpm_", "p11_maskonly_", "p10_async"]:
        if seq_clean.startswith(prefix):
            seq_clean = seq_clean[len(prefix):]
            break

    ff = d.get("fullframe", {})
    records.append({
        "method": method,
        "seq": seq_clean,
        "seed": seed,
        "psnr": ff.get("psnr"),
        "ssim": ff.get("ssim"),
        "lpips": ff.get("lpips"),
        "depth_l1_cm": ff.get("depth_l1_cm"),
        "frames": ff.get("frames_scored", 0),
    })

# Group by method+seq, compute mean
groups = defaultdict(list)
for r in records:
    key = (r["method"], r["seq"])
    groups[key].append(r)

print(f"\n{'Method':<12} {'Sequence':<20} {'PSNR':>8} {'SSIM':>8} {'LPIPS':>8} {'D-L1':>8} {'n_seeds':>8}")
print("-" * 90)

rows = []
for (method, seq), runs in sorted(groups.items()):
    psnrs = [r["psnr"] for r in runs if r["psnr"] is not None]
    ssims = [r["ssim"] for r in runs if r["ssim"] is not None]
    lpips = [r["lpips"] for r in runs if r["lpips"] is not None]
    dl1s = [r["depth_l1_cm"] for r in runs if r["depth_l1_cm"] is not None]

    mean_psnr = sum(psnrs)/len(psnrs) if psnrs else None
    mean_ssim = sum(ssims)/len(ssims) if ssims else None
    mean_lpips = sum(lpips)/len(lpips) if lpips else None
    mean_dl1 = sum(dl1s)/len(dl1s) if dl1s else None

    rows.append((method, seq, mean_psnr, mean_ssim, mean_lpips, mean_dl1, len(runs)))

    print(f"{method:<12} {seq:<20} {mean_psnr:>8.4f} {mean_ssim:>8.4f} {mean_lpips:>8.4f} {mean_dl1:>8.2f} {len(runs):>8}")

# Save as JSON for later use
output = {"records": records, "summary": [
    {"method": r[0], "seq": r[1], "psnr": r[2], "ssim": r[3], "lpips": r[4], "depth_l1_cm": r[5], "n_seeds": r[6]}
    for r in rows
]}
with open("/data/monogs-ours/results/render_metrics_summary.json", "w") as f:
    json.dump(output, f, indent=2)
print(f"\nSaved to results/render_metrics_summary.json")
