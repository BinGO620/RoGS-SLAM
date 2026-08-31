#!/usr/bin/env python3
"""P6-MASON terminal-compression generalization probe (2060, offline, zero SLAM).

Question the user pushed back on: is the "op<0.01 softly-suppressed, zero-cost removable
tail" a MonoGS-refinement-specific artifact, or a *general* property of any 3DGS map whose
optimization lets opacity shrink freely (and does not densify/prune afterwards)?

Layering (accepting the pushback, not decreeing):
  L0 (already proven)   our workflow / refinement: tail 9-16% ≤-- auto, zero-cost.
  L1 (hypothesis)       the tail is a property of the *final-map opacity DOF*, not of
                        refinement per se. Any 3DGS end-state (online final map, or a
                        post-opt run) that has a done-optimizing no-prune phase should show
                        a measurable zero-cost removable cohort.
  L2 (PROBE HERE)       measure frac_op_lt_001 on the ONLINE final map (before refinement
                        regrows the tail) of the P3-DENSIFY-TAIL base/hi/lo runs:
                        - base  = default densify opacity threshold (tail source = the
                                  densify/prune+refine end state)
                        - lo    = lower densify thresh (should widen online tail iff
                                  opacity DOF is the driver)
                        - hi    = higher densify thresh (should narrow online tail)
                        If lo>base>hi in frac_op_lt_001 on the ONLINE final map, the
                        "opacity DOF -> removable cohort" thesis holds pre-refinement too,
                        upgrading from "refinement-specific" to "any 3DGS opacity-dof".

We read the ONLINE `final/point_cloud.ply` (not final_after_opt) to separate the
densify-driven tail from the refinement-driven tail.

Data source: results/runs/P3/P3-DENSIFY-TAIL/{balloon,balloon2,mv_no_box,mv_no_box2}_{base,lo,hi}_seed0
Output: results/evidence/terminal_comp_generalization_probe.json + printed table
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "results" / "runs" / "P3" / "P3-DENSIFY-TAIL"
EV = ROOT / "results" / "evidence"
EV.mkdir(exist_ok=True)

# (seq, arm) -> expected config for sh_degree/config echo
CASES = [
    ("balloon", "base"), ("balloon", "lo"), ("balloon", "hi"),
    ("balloon2", "base"), ("balloon2", "lo"), ("balloon2", "hi"),
    ("mv_no_box", "base"), ("mv_no_box", "lo"), ("mv_no_box", "hi"),
    ("mv_no_box2", "base"), ("mv_no_box2", "lo"),
]


def load_cfg(cfg_path: Path):
    import yaml
    return yaml.safe_load(open(cfg_path)) or {}


def find_online_ply(run_root: Path):
    """Online final map = point_cloud/final/point_cloud.ply (NOT final_after_opt)."""
    resolved = _resolve_run_dir(run_root)
    if resolved is None:
        return None
    cand = resolved / "point_cloud" / "final" / "point_cloud.ply"
    return cand if cand.is_file() else None


def _resolve_run_dir(run_root: Path):
    if (run_root / "tables").is_dir():
        # match the P3 layout: <root>/datasets_<ds>/<config>/seed_N/<ts>/
        subs = [p for p in run_root.glob("datasets_*/**/*") if p.is_dir()]
        # find deepest dir containing point_cloud
        best = None
        for p in run_root.rglob("point_cloud"):
            if p.is_dir():
                best = p.parent
        return best
    return run_root


def opacity_stats(ply: Path, cfg: dict):
    from gaussian_splatting.scene.gaussian_model import GaussianModel
    import torch
    sh_degree = 3 if cfg.get("Training", {}).get("spherical_harmonics") else 0
    model = GaussianModel(sh_degree, config=cfg)
    model.load_ply(str(ply))
    sig = torch.sigmoid(model._opacity).reshape(-1).detach().float()
    n = int(sig.shape[0])
    if n == 0:
        return {"n_total": 0, "frac_lt_001": float("nan"), "frac_lt_005": float("nan"),
                "frac_lt_010": float("nan"), "frac_ge_090": float("nan")}
    def frac(th): return float((sig < th).float().mean().item())
    return {"n_total": n, "frac_lt_001": round(frac(0.01), 6),
            "frac_lt_005": round(frac(0.05), 6), "frac_lt_010": round(frac(0.10), 6),
            "frac_ge_090": round(float((sig >= 0.90).float().mean().item()), 6)}


def main():
    cfgs = {}
    for name in ["balloon", "balloon2", "mv_no_box", "mv_no_box2"]:
        c = ROOT / "configs" / "rgbd" / "experiments" / "p3_densify_tail"
        # densify thresh lives in the method/train config the runs used; approximate by
        # the per-seq dataset config (sh_degree is what we actually need, not the knob).
        dcfg = None
        for cand in c.glob(f"{name}*.yaml"):
            pass
        # use the dataset base config for sh_degree
        base = ROOT / "configs" / "rgbd" / "bonn" / f"{'moving_nonobstructing_box' if 'mv_' == name[:3] else name}.yaml"
        if name.startswith("mv"):
            base = ROOT / "configs" / "rgbd" / "bonn" / ("moving_nonobstructing_box2.yaml" if name == "mv_no_box2" else "moving_nonobstructing_box.yaml")
        else:
            base = ROOT / "configs" / "rgbd" / "bonn" / f"{name}.yaml"
        cfgs[name] = load_cfg(base if base.is_file() else ROOT / "configs" / "rgbd" / "bonn" / "base_config.yaml")

    rows = []
    for seq, arm in CASES:
        tag = f"{seq}_{arm}_seed0"
        run_root = OUT_DIR / tag
        ply = find_online_ply(run_root)
        if ply is None:
            rows.append({"seq": seq, "arm": arm, "ply": "MISSING",
                         "frac_lt_001": None, "note": "no online final PLY"})
            continue
        st = opacity_stats(ply, cfgs.get(seq, {}))
        rows.append({"seq": seq, "arm": arm, "ply": str(ply.relative_to(ROOT)), **st})

    # summary: for each seq, check base/lo/hi ordering of frac_lt_001 on ONLINE final map
    print(f"{'seq':<10}{'arm':<6}{'n_total':>9}{'lt_001':>9}{'lt_005':>9}{'lt_010':>9}{'ge_090':>9}")
    with (EV / "terminal_comp_generalization_probe.json").open("w") as f:
        json.dump(rows, f, indent=2)
    for r in rows:
        if r.get("frac_lt_001") is not None:
            print(f"{r['seq']:<10}{r['arm']:<6}{r['n_total']:>9}{r['frac_lt_001']:>9}{r['frac_lt_005']:>9}{r['frac_lt_010']:>9}{r['frac_ge_090']:>9}")
        else:
            print(f"{r['seq']:<10}{r['arm']:<6}  MISSING")

    print("\n-- interpretation --")
    for seq in ["balloon", "balloon2", "mv_no_box"]:
        b = next((r["frac_lt_001"] for r in rows if r["seq"] == seq and r["arm"] == "base"), None)
        lo = next((r["frac_lt_001"] for r in rows if r["seq"] == seq and r["arm"] == "lo"), None)
        hi = next((r["frac_lt_001"] for r in rows if r["seq"] == seq and r["arm"] == "hi"), None)
        if None in (b, lo, hi):
            print(f"{seq}: incomplete (base={b} lo={lo} hi={hi})")
            continue
        pred = (lo > b > hi)
        print(f"{seq}: base={b} lo={lo} hi={hi} -> opacity-DOF ordering holds: {pred}")
    print(f"\nrows -> {EV / 'terminal_comp_generalization_probe.json'}")


if __name__ == "__main__":
    main()
