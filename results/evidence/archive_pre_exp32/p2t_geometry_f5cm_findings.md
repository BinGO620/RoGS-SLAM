# P2-T F@5cm geometry: regime-limitation findings (2026-08-02)

> 36/36 runs post-processed (`scripts/r2_p2_t_geometry.py` → `utils/geometry_metrics.evaluate_run_geometry`).
> CSV: `results/runs/P2/P2-T/p2t_geometry.csv`. Per-run json: each run's `mapping_geometry_metrics_v2.json`.

## The numbers (3-seed mean per seq × arm)

| seq | prune F@5cm | deferred F@5cm | prune acc cm | deferred acc cm |
|---|---|---|---|---|
| balloon | 2.00 | 2.01 | 119.2 | 119.2 |
| balloon2 | 1.90 | 2.05 | 111.2 | 110.5 |
| mv_no_box | 2.23 | 2.42 | 105.2 | 104.0 |
| mv_no_box2 | 2.78 | 2.60 | 68.0 | 67.4 |
| pt1 | 5.14 | 4.27 | 92.2 | 93.0 |
| pt2 | 5.57 | 5.60 | 131.9 | 128.3 |

## Why these are not reportable as absolute geometry

**Bonn F@5cm absolute is regime-broken (~2-6%), not method-driven.** Diagnostic on balloon_prune_seed0 (TSDF mesh vs `rgbd_bonn_groundtruth_1mm_section.ply`, 54.7M pts, full-room extent 5.6×5.3×4.1m):

- Static alignment `T_g = T_ROS^{-1} T_0 T_ROS T_m`: rec→GT nn dist **mean 113cm, median 111cm, p90 224cm**, precision@5cm = 3.0%.
- **Umeyama BEST-FIT rigid transform** rec→GT: **mean 114cm, median 114cm, p90 115cm** (tight spread = systematic offset, not noise).
- Bboxes: rec `x[-3.07,2.8] y[-0.51,2.8] z[-8.13,-3.7]`; GT `x[-2.96,2.63] y[-1.97,3.33] z[-5.12,-1.04]` — rec is ~3m deeper in z, ~1.5m higher in y. NOT closeable by any single rigid transform.

**Conclusion (codex-confirmed):** even the best rigid alignment leaves a 1.14m systematic residual with tight spread. The MonoGS reconstruction world frame (init at frame-0 pose) and the Bonn GT-ply world frame (ROS-body, built from a different trajectory fusion) do not close under any rigid transform recoverable here. The static formula is also imprecise (p90 224 vs Umeyama 115). NOT fixable by re-tuning the static transform.

## Why the directional prune-vs-deferred F@5cm is ALSO contaminated

codex: F@5cm is nonlinear; under a large systematic offset, paired arm differences depend on **accidental overlap and map extent**, not on map quality. Evidence it's contaminated: the direction is **inconsistent** (balloon deferred>prune, pt1 prune>deferred, pt2 deferred>prune) AND **counterintuitive** (pt1/pt2 — higher ATE, worse tracking — have HIGHER F@5cm 4-6% than balloon 2%). The ranking tracks map extent/overlap, not fidelity.

## Decision (codex + diagnostic)

**Option (c): drop the F@5cm column from the main table.** Lead with:
- compactness G_def/G_prune (the actual headline),
- vac_depth / vac_psnr (image-space fidelity, SANE on the same runs: balloon vac_depth ~17cm, vac_psnr ~23dB, normal regime),
- ATE (tracking).

F@5cm data is preserved in `p2t_geometry.csv` + per-run json as an **appendix diagnostic** with an explicit statement that absolute Bonn geometry evaluation is invalid under the unresolved frame registration. NOT reported as a geometry-preservation result.

This matches R2-P01-E2, which used F@5cm only as a directional co-primary and never reported absolute % on Bonn.

## What this does NOT change

- Backbone-holds verdict (ATE is the tracking metric, unaffected).
- H-D INDETERMINATE verdict (compactness ratio, unaffected).
- deferred-ATE trade (unaffected).
- The 2×2 narrative D′ table uses compactness + ATE, NOT F@5cm.
