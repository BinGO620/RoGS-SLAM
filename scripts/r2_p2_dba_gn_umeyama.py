"""DBAphoto step2 metric repair: recompute the GN step test's ATE in the HEADLINE protocol.

Why this exists
---------------
The GN step test (``r2_p2_dba_geo_oracle.py --phase gn``) reported an 85-98 cm
"ATE" that is a KF0-gauge-shared camera-center RMSE. codex 019fc7e1 ruled that
number NOT comparable to the 2.6-3.0 cm headline ATE, so its -1.85 cm drop is
uninterpretable. This script removes the confound: it feeds the saved per-iter KF
poses through the SAME function the headline uses.

Protocol (imported, not reimplemented)
--------------------------------------
``utils.eval_utils._evaluate_trajectories`` -- evo ``align_trajectory`` with
``correct_scale=monocular``. These are RGB-D runs, so ``monocular=False`` =>
**SE(3) Umeyama, NO scale**. (The step2 outcome note said "Sim(3)"; using a scale
d.o.f. here would let a global scale absorb error and produce a number that is
optimistic *and* not comparable to the headline. Same-protocol beats Sim(3).)

Three readouts per GN iteration, all in the headline protocol:

  A) ``kf_ate``    -- KF subset only, aligned on the KF subset. Protocol-matched
                      to the headline but restricted to KFs.
  B) ``full_sub``  -- full trajectory, KF frames replaced by the refined poses and
                      non-KF frames left at their online poses. **This is what
                      ``run_dba_v0`` would actually put in ``tracking_raw.csv``'s
                      ``ate_rmse_cm``** (dba_lite.py:931 writes back KF poses only,
                      and slam.py runs it AFTER ``final_pose_refinement()``), so it
                      is the decision-relevant number.
  C) ``full_prop`` -- full trajectory with each non-KF frame rigidly carried by its
                      reference KF (T_rel preserved). This is the OPTIMISTIC bound:
                      what a KF-only BA could deliver if non-KF poses were also
                      recomposed (cf. the ``kf_propagated_ate_rmse_cm`` column in
                      eval_utils). ref-KF assignment is RECONSTRUCTED here as the
                      nearest preceding KF (the online ``ref_kf_id`` is not on disk)
                      -- labelled as a reconstruction, not the exact online mapping.

Hard gates (a failed gate invalidates the readout, it does not get "interpreted"):
  G0  offline online-pose full-traj ATE == recorded ``tracking_raw.csv`` ate_rmse_cm
      (tol 1e-3 cm). Proves this script reproduces the headline number.
  G1  GN iter-0 KF poses == the run's online KF poses (tol 1e-6). Proves the GN
      trajectory starts at the online poses.

Usage:  python scripts/r2_p2_dba_gn_umeyama.py [--tol-cm 1e-3]
Zero GPU.
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.eval_utils import _evaluate_trajectories  # noqa: E402  (protocol by import)

STASH_ROOT = "results/runs/P2/P2-DBA-STASH"
OUT_JSON = os.path.join(STASH_ROOT, "p2dba_gn_umeyama_report.json")


def _ate_cm(poses_gt, poses_est):
    """Headline ATE in cm: evo SE(3)-Umeyama alignment, translation APE RMSE."""
    _, _, _, ape_stats, _ = _evaluate_trajectories(
        [np.asarray(p, dtype=np.float64) for p in poses_gt],
        [np.asarray(p, dtype=np.float64) for p in poses_est],
        monocular=False,
    )
    return float(ape_stats["rmse"]) * 100.0


def _recorded_ate(run_dir):
    path = os.path.join(run_dir, "tracking_raw.csv")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    try:
        return float(rows[0]["ate_rmse_cm"])
    except (KeyError, TypeError, ValueError):
        return None


def _nearest_preceding_kf(fid, kf_sorted):
    """Reconstructed ref-KF assignment (online ref_kf_id is not persisted)."""
    lo, hi = 0, len(kf_sorted) - 1
    best = kf_sorted[0]
    while lo <= hi:
        mid = (lo + hi) // 2
        if kf_sorted[mid] <= fid:
            best = kf_sorted[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def process_run(pose_path, tol_cm, g1_tol=1e-6):
    data = json.load(open(pose_path))
    run_dir = data["run_dir"]
    kfs = [int(k) for k in data["kfs"]]

    full = json.load(open(os.path.join(run_dir, "plot", "trj_full_final.json")))
    full_ids = [int(i) for i in full["trj_id"]]
    full_est = {i: np.asarray(p, dtype=np.float64) for i, p in zip(full_ids, full["trj_est"])}
    full_gt = {i: np.asarray(p, dtype=np.float64) for i, p in zip(full_ids, full["trj_gt"])}

    kf_trj = json.load(open(os.path.join(run_dir, "plot", "trj_final.json")))
    kf_online = {int(i): np.asarray(p, dtype=np.float64)
                 for i, p in zip(kf_trj["trj_id"], kf_trj["trj_est"])}
    kf_gt = {int(i): np.asarray(p, dtype=np.float64)
             for i, p in zip(kf_trj["trj_id"], kf_trj["trj_gt"])}

    out = {"tag": data["tag"], "seq": data["seq"], "seed": data["seed"],
           "n_kfs": len(kfs), "n_frames": len(full_ids), "gates": {}, "iters": []}

    # ---- G0: reproduce the recorded headline ATE from the online poses ----
    sorted_ids = sorted(full_ids)
    online_full = _ate_cm([full_gt[i] for i in sorted_ids], [full_est[i] for i in sorted_ids])
    rec = _recorded_ate(run_dir)
    g0_ok = rec is not None and abs(online_full - rec) <= tol_cm
    out["gates"]["G0_headline_reproduced"] = {
        "recorded_ate_cm": rec, "offline_ate_cm": round(online_full, 6),
        "delta_cm": None if rec is None else round(online_full - rec, 8), "pass": bool(g0_ok)}

    # ---- G1: GN iter-0 == online KF poses ----
    it0 = np.asarray(data["iters"][0]["poses_c2w"], dtype=np.float64)
    ref0 = np.stack([kf_online[k] for k in kfs])
    max_dev = float(np.abs(it0 - ref0).max())
    g1_ok = max_dev <= g1_tol
    out["gates"]["G1_iter0_is_online"] = {"max_abs_dev": max_dev, "tol": g1_tol,
                                          "pass": bool(g1_ok)}

    if not (g0_ok and g1_ok):
        out["status"] = "GATE_FAIL"
        return out
    out["status"] = "OK"

    # baselines in each of the three readouts (iter 0 == online by G1)
    kf_sorted = sorted(kf_online.keys())
    nonkf = [i for i in sorted_ids if i not in kf_online]
    ref_of = {i: _nearest_preceding_kf(i, kf_sorted) for i in nonkf}
    # T_rel (C2W): X_f = X_ref @ (inv(X_ref_online) @ X_f_online)
    rel_of = {i: np.linalg.inv(full_est[ref_of[i]]) @ full_est[i] for i in nonkf}
    out["nonkf_frames"] = len(nonkf)

    for snap in data["iters"]:
        it = int(snap["iter"])
        poses = {k: np.asarray(p, dtype=np.float64)
                 for k, p in zip(kfs, snap["poses_c2w"])}

        # A) KF subset, aligned on the KF subset
        kf_ate = _ate_cm([kf_gt[k] for k in kfs], [poses[k] for k in kfs])

        # B) full trajectory, KF poses substituted (what run_dba_v0 actually yields)
        est_sub = [poses.get(i, full_est[i]) for i in sorted_ids]
        full_sub = _ate_cm([full_gt[i] for i in sorted_ids], est_sub)

        # C) full trajectory, non-KFs rigidly carried by their (reconstructed) ref KF
        est_prop = []
        for i in sorted_ids:
            if i in poses:
                est_prop.append(poses[i])
            elif i in rel_of and ref_of[i] in poses:
                est_prop.append(poses[ref_of[i]] @ rel_of[i])
            else:
                est_prop.append(full_est[i])
        full_prop = _ate_cm([full_gt[i] for i in sorted_ids], est_prop)

        out["iters"].append({"iter": it,
                             "kf_ate_cm": round(kf_ate, 4),
                             "full_sub_cm": round(full_sub, 4),
                             "full_prop_cm": round(full_prop, 4)})

    base = out["iters"][0]
    last = out["iters"][-1]
    out["deltas_cm"] = {k.replace("_cm", "") + "_delta":
                        round(last[k] - base[k], 4)
                        for k in ("kf_ate_cm", "full_sub_cm", "full_prop_cm")}
    out["best_iter"] = {k: min(out["iters"], key=lambda r, kk=k: r[kk])["iter"]
                        for k in ("kf_ate_cm", "full_sub_cm", "full_prop_cm")}
    out["monotone"] = {k: all(out["iters"][i + 1][k] <= out["iters"][i][k] + 1e-9
                              for i in range(len(out["iters"]) - 1))
                       for k in ("kf_ate_cm", "full_sub_cm", "full_prop_cm")}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--tol-cm", type=float, default=1e-3)
    ap.add_argument("--g1-tol", type=float, default=1e-6,
                    help="PREREGISTERED value is 1e-6. Any other value produces a "
                         "LABELLED SENSITIVITY only -- it may not change a branch verdict.")
    args = ap.parse_args()
    if args.g1_tol != 1e-6:
        print(f"*** LABELLED SENSITIVITY: G1 tol overridden to {args.g1_tol:g} "
              f"(prereg = 1e-6). Diagnostic only; cannot change the branch. ***\n")

    paths = sorted(p for p in
                   (os.path.join(STASH_ROOT, f) for f in os.listdir(STASH_ROOT))
                   if os.path.basename(p).startswith("gn_poses_") and p.endswith(".json"))
    if not paths:
        print(f"no gn_poses_*.json under {STASH_ROOT} — run --phase gn first")
        return 1

    results = [process_run(p, args.tol_cm, args.g1_tol) for p in paths]

    print("=== G0/G1 gates ===")
    for r in results:
        g0 = r["gates"]["G0_headline_reproduced"]
        g1 = r["gates"]["G1_iter0_is_online"]
        print(f"  {r['tag']:<34} G0 {'PASS' if g0['pass'] else 'FAIL'} "
              f"(rec {g0['recorded_ate_cm']} vs offline {g0['offline_ate_cm']:.4f}) "
              f"| G1 {'PASS' if g1['pass'] else 'FAIL'} (dev {g1['max_abs_dev']:.2e})")

    ok = [r for r in results if r["status"] == "OK"]
    if not ok:
        print("\nALL RUNS GATE-FAILED — readout invalid.")
        json.dump(results, open(OUT_JSON, "w"), indent=2)
        return 2

    print("\n=== headline-protocol ATE per GN iteration (cm) ===")
    for r in ok:
        print(f"\n  {r['tag']}  ({r['n_kfs']} KFs / {r['n_frames']} frames)")
        print(f"    {'iter':>4} {'kf_ate':>9} {'full_sub':>9} {'full_prop':>10}")
        for row in r["iters"]:
            print(f"    {row['iter']:>4} {row['kf_ate_cm']:>9.4f} "
                  f"{row['full_sub_cm']:>9.4f} {row['full_prop_cm']:>10.4f}")
        d = r["deltas_cm"]
        print(f"    delta(t5-t0): kf {d['kf_ate_delta']:+.4f}  "
              f"full_sub {d['full_sub_delta']:+.4f}  full_prop {d['full_prop_delta']:+.4f}")
        print(f"    monotone: {r['monotone']}  best_iter: {r['best_iter']}")

    print("\n=== summary (decision metric = full_sub, what run_dba_v0 would report) ===")
    print(f"  {'run':<34} {'online':>8} {'t5':>8} {'delta':>8} {'best':>8} {'mono':>6}")
    for r in ok:
        b, l = r["iters"][0], r["iters"][-1]
        bi = r["best_iter"]["full_sub_cm"]
        bv = min(x["full_sub_cm"] for x in r["iters"])
        print(f"  {r['tag']:<34} {b['full_sub_cm']:>8.4f} {l['full_sub_cm']:>8.4f} "
              f"{r['deltas_cm']['full_sub_delta']:>+8.4f} {bv:>8.4f}@{bi} "
              f"{str(r['monotone']['full_sub_cm']):>6}")

    json.dump(results, open(OUT_JSON, "w"), indent=2)
    print(f"\nwrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
