"""Diagnostic: validate external RGD trajectory files against published ATE.

For every external_trajectories/rgd/<seq>/seed_<n>/**/trj_final.json:
  - file-internal ATE = Umeyama(SE3)-aligned RMSE of trj_est vs trj_gt positions
  - compared against the published RGD-SLAM tracking_raw.csv numbers.

Run:  python scripts/check_rgd_trajectories.py
"""

import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "external_trajectories",
    "rgd",
)

# Published full-trajectory ATE (cm) from
# workspace/dynamic-3dgs-slam/02-baselines/baselines_result/RGD-SLAM/tracking_raw.csv
PUBLISHED = {
    ("bonn_balloon", 0): 2.2571,
    ("bonn_balloon", 1): 2.4019,
    ("bonn_balloon", 2): 2.6852,
    ("bonn_balloon2", 0): 3.2985,
    ("bonn_balloon2", 1): 4.4118,
    ("bonn_balloon2", 2): 5.0644,
    ("bonn_moving_nonobstructing_box", 0): 2.0776,
    ("bonn_moving_nonobstructing_box", 1): 2.5805,
    ("bonn_moving_nonobstructing_box", 2): 2.1964,
    ("bonn_moving_nonobstructing_box2", 0): 4.4456,
    ("bonn_moving_nonobstructing_box2", 1): 4.7426,
    ("bonn_moving_nonobstructing_box2", 2): 4.9149,
    ("bonn_person_tracking", 0): 6.7344,
    ("bonn_person_tracking", 1): 6.2755,
    ("bonn_person_tracking", 2): 8.6201,
    # person_tracking2 updated per the 2026-06-25 RGD rerun (seed fix + prune bug fix)
    ("bonn_person_tracking2", 0): 26.53,
    ("bonn_person_tracking2", 1): 19.22,
    ("bonn_person_tracking2", 2): 23.21,
    ("freiburg1_desk", 0): 2.1971,
    ("freiburg1_desk", 1): 2.3918,
    ("freiburg1_desk", 2): 2.3765,
    ("freiburg2_xyz", 0): 1.7414,
    ("freiburg2_xyz", 1): 1.7546,
    ("freiburg2_xyz", 2): 1.6326,
}


def ate_rmse_cm(est_p, gt_p):
    """evo-style ATE: SE(3) Umeyama alignment, translation RMSE (cm)."""
    mu_e, mu_g = est_p.mean(0), gt_p.mean(0)
    ec, gc = est_p - mu_e, gt_p - mu_g
    cov = gc.T @ ec / len(ec)
    U, _, Vt = np.linalg.svd(cov)
    sgn = np.eye(3)
    sgn[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ sgn @ Vt
    t = mu_g - R @ mu_e
    aligned = (R @ est_p.T).T + t
    return float(np.sqrt(((aligned - gt_p) ** 2).sum(1).mean()) * 100.0)


def main():
    rows = []
    for f in sorted(glob.glob(f"{ROOT}/*/seed_*/**/trj_final.json", recursive=True)):
        rel = os.path.relpath(f, ROOT)
        seq = rel.split(os.sep)[0]
        seed = int(rel.split(os.sep)[1].split("_")[1])
        data = json.load(open(f))
        est = np.asarray(data["trj_est"], dtype=np.float64)[:, :3, 3]
        gt = np.asarray(data["trj_gt"], dtype=np.float64)[:, :3, 3]
        ate = ate_rmse_cm(est, gt)
        pub = PUBLISHED.get((seq, seed))
        if pub is None:
            flag = "--"
        elif abs(ate - pub) < 0.3:
            flag = "OK"
        else:
            flag = f"MISMATCH ({ate / pub:.2f}x)"
        rows.append((seq, seed, len(est), ate, pub, flag))

    print(f"{'seq':36s} {'seed':4s} {'N':5s} {'file-ATE':9s} {'published':9s} match")
    for seq, seed, n, ate, pub, flag in rows:
        pub_s = f"{pub:.3f}" if pub is not None else "--"
        print(f"{seq:36s} {seed:<4d} {n:<5d} {ate:<9.3f} {pub_s:9s} {flag}")
    n_ok = sum(1 for r in rows if r[5] == "OK")
    print(f"\n{n_ok}/{len(rows)} match published within 0.3cm")


if __name__ == "__main__":
    main()
