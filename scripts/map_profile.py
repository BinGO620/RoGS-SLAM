#!/usr/bin/env python3
"""Profile the final Gaussian map from a MonoGS run's point_cloud.ply.

Key question: does the reliability weighting change HOW the map is built (what Gaussians
survive, their spatial distribution, their static probability, their opacity distribution)
-- even when the per-frame pose is nearly identical?

This is a zero-GPU analysis: it reads existing PLY files from completed runs. Every
property column is directly reported; thresholds are pre-registered in the header.

Usage:
  python scripts/map_profile.py --ply path/to/final/point_cloud.ply
  python scripts/map_profile.py --dir results/runs/ --out results/evidence/map_profile/
"""

import argparse
import csv
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import numpy as np

# --- PLY reader (no external deps; handles ASCII + binary_little_endian) ---
def _read_ply(path):
    """Return (header_dict, vertex_array). header_dict has 'element vertex N' and all property names."""
    with open(path, "rb") as fh:
        lines = []
        while True:
            l = fh.readline().decode("ascii", "ignore").strip()
            lines.append(l)
            if l == "end_header":
                break
            if not l:
                raise ValueError("truncated PLY header")
        # parse
        fmt = next((l.split()[1] for l in lines if l.startswith("format")), "ascii")
        n_vert = int(next((l.split()[2] for l in lines
                           if l.startswith("element vertex")), 0))
        props = [l.split()[2] for l in lines if l.startswith("property")]
        if fmt == "ascii":
            data = []
            for _ in range(n_vert):
                data.append([float(x) for x in fh.readline().decode("ascii", "ignore").split()])
            return {"n": n_vert, "props": props}, np.array(data, dtype=np.float32)
        else:
            dt = np.dtype([(p, np.float32) for p in props])
            raw = fh.read(n_vert * dt.itemsize)
            return {"n": n_vert, "props": props}, np.frombuffer(raw, dtype=dt)


def profile(ply_path):
    """Compute per-property statistics + a few derived quantities."""
    hdr, verts = _read_ply(ply_path)
    props = hdr["props"]
    n = hdr["n"]
    stats = {"n_gaussians": n, "file": ply_path}

    # per-property summary
    for i, p in enumerate(props):
        col = verts[p] if isinstance(verts, np.ndarray) and verts.dtype.names else verts[:, i]
        fin = col[np.isfinite(col)]
        if fin.size == 0:
            continue
        stats[p] = {
            "mean": float(fin.mean()), "std": float(fin.std()),
            "min": float(fin.min()), "max": float(fin.max()),
            "median": float(np.median(fin)),
            "p10": float(np.percentile(fin, 10)),
            "p90": float(np.percentile(fin, 90)),
        }

    # opacity distribution buckets
    if "opacity" in props:
        op = verts["opacity"] if hasattr(verts, "dtype") and verts.dtype.names else verts[:, props.index("opacity")]
        buckets = [0, 0.01, 0.05, 0.1, 0.3, 0.5, 1.0, float("inf")]
        labels = ["=0", "0-0.01", "0.01-0.05", "0.05-0.1", "0.1-0.3", "0.3-0.5", "0.5-1", ">1"]
        hist = {}
        for i in range(len(buckets) - 1):
            hist[labels[i]] = int(((op >= buckets[i]) & (op < buckets[i + 1])).sum())
        stats["opacity_hist"] = hist

    # spatial distribution (bounding box + extent)
    if all(p in props for p in ("x", "y", "z")):
        xyz = np.stack([verts["x"], verts["y"], verts["z"]], axis=-1)
        bbox_min = xyz.min(axis=0)
        bbox_max = xyz.max(axis=0)
        extent = bbox_max - bbox_min
        stats["bbox_min_xyz"] = [float(x) for x in bbox_min]
        stats["bbox_max_xyz"] = [float(x) for x in bbox_max]
        stats["extent_xyz"] = [float(x) for x in extent]
        stats["extent_max"] = float(extent.max())

    # scale distribution (anisotropy indicator)
    if all(f"scale_{i}" in props for i in range(3)):
        scales = np.stack([verts[f"scale_{i}"] for i in range(3)], axis=-1)
        vol = np.prod(np.exp(scales), axis=-1)   # GS volume ~ exp(sum log_scale)
        stats["log_volume"] = {"mean": float(np.log(vol).mean()),
                               "std": float(np.log(vol).std()),
                               "median": float(np.median(np.log(vol)))}
        ratio = scales.max(axis=1) / (scales.min(axis=1) + 1e-12)
        stats["anisotropy_ratio"] = {"mean": float(ratio.mean()),
                                      "median": float(np.median(ratio)),
                                      "max": float(ratio.max())}

    # static_prob distribution (only for runs with reliability enabled)
    if "static_prob" in props:
        sp = verts["static_prob"]
        fin = sp[np.isfinite(sp)]
        stats["static_prob"] = {"mean": float(fin.mean()), "median": float(np.median(fin)),
                                "std": float(fin.std())}
        below = (fin < 0.5).sum()
        stats["static_prob"]["pct_below_0.5"] = float(below / fin.size * 100) if fin.size else 0

    # static_obs_count distribution
    if "static_obs_count" in props:
        soc = verts["static_obs_count"]
        fin = soc[np.isfinite(soc)]
        stats["static_obs_count"] = {"mean": float(fin.mean()), "median": float(np.median(fin)),
                                      "std": float(fin.std())}

    return stats


def compare(stats_list):
    """Print a side-by-side comparison table."""
    if not stats_list:
        return
    names = [os.path.basename(os.path.dirname(os.path.dirname(s["file"])))[:35]
             for s in stats_list]
    # header
    print(f"{'metric':40s} " + " ".join(f"{n:>18s}" for n in names))
    print("-" * (42 + 19 * len(names)))
    rows = [
        ("n_gaussians", None),
        ("opacity.mean", ("opacity", "mean")),
        ("opacity.median", ("opacity", "median")),
        ("opacity.pct_0", ("opacity_hist", "=0")),
        ("opacity.pct_0.05_0.1", ("opacity_hist", "0.05-0.1")),
        ("extent_max", None),
        ("log_volume.mean", ("log_volume", "mean")),
        ("anisotropy_ratio.mean", ("anisotropy_ratio", "mean")),
        ("static_prob.mean", ("static_prob", "mean")),
        ("static_prob.pct_below_0.5", ("static_prob", "pct_below_0.5")),
        ("static_obs_count.mean", ("static_obs_count", "mean")),
    ]
    for key, sub in rows:
        vals = []
        for s in stats_list:
            if sub is None:
                v = s.get(key, float("nan"))
            else:
                d = s.get(sub[0], {})
                v = d.get(sub[1], float("nan"))
            if isinstance(v, float):
                vals.append(f"{v:18.4f}")
            elif isinstance(v, int):
                vals.append(f"{v:18d}")
            else:
                vals.append(f"{str(v):>18s}")
        print(f"{key:40s} " + " ".join(vals))


def scan_dir(root, out_dir):
    """Find all point_cloud.ply and profile them."""
    plies = sorted(glob.glob(os.path.join(root, "**/final/point_cloud.ply"), recursive=True))
    if not plies:
        print(f"no PLY files found under {root}")
        return

    results = []
    for p in plies:
        try:
            s = profile(p)
            results.append(s)
        except Exception as e:
            print(f"SKIP {p}: {e}", file=sys.stderr)

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "profiles.json"), "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"{len(results)} PLY profiled -> {out_dir}/profiles.json")
    compare(results)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ply", default=None, help="single PLY file")
    ap.add_argument("--dir", default=None, help="root to scan for final/point_cloud.ply")
    ap.add_argument("--out", default="results/evidence/map_profile")
    args = ap.parse_args()
    if args.ply:
        s = profile(args.ply)
        print(json.dumps(s, indent=2))
    elif args.dir:
        scan_dir(args.dir, args.out)
    else:
        ap.error("pass --ply or --dir")


if __name__ == "__main__":
    main()
