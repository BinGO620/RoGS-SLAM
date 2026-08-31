# Oracle.pose_file in-pipeline smoke — PASSED (2026-07-26)

**Purpose.** First end-to-end validation of the borrowed-trajectory injection
chain (`Oracle.pose_file`, commit 3edce7a) inside the full SLAM pipeline,
gating the 5-row tracker-orthogonal map-admission table. One run, no arm
comparison — infrastructure validation only.

## Run

- balloon seed 0, deferred arm (`deferred_rtoff_balloon` + overlay), `--fast`, RTX 2060
- overlay: `Oracle.pose_file` = RGD bonn_balloon seed_0 `trj_final.json`
  (full_metrics_v2, 2026-06-25 batch) + `Training.lr.cam_rot_delta/cam_trans_delta: 0.0`
- run dir: `results/runs/ORACLE-SMOKE/datasets_bonn/oracle_smoke_deferred_balloon/seed_0/2026-07-26-18-05-51` (exit 0)

## Gates — all green

| check | result |
|---|---|
| Oracle load line | `frames=439 anchor_rmse=0.336cm rot_max=0.11deg scale=1.00066` (gates <1cm / <3deg / ±0.01) |
| headline `ate_rmse_cm` (tracking_raw) | **2.0618** — equals the offline pure-math prediction to 4 decimals |
| saved trajectory vs injected poses | per-frame diff **0.0000 cm** (mean and max, all 439 frames) — nothing moved the poses |
| backend pose freeze | saved `config.yml` has `cam_rot_delta: 0.0`, `cam_trans_delta: 0.0`; frontend breaks before `pose_optimizer.zero_grad()` (`slam_frontend.py:986`) |
| reliability stash under oracle | 439/439 frames wrote `reliability_signal` rows (itr-0 freeze path live; `DeferredCommit.reliability_confirm` intact) |
| deferred lifecycle | protocol `uncertain-regions-v2` active; promotion health all-zero invalid; immediate_insert 58,738 / explained 417,044 / deferred_front_foreground 38,899 px |
| runtime | online FPS 5.97 (mapping-only), clean backend join |

## The 2.06-vs-2.26 finding (resolves the sanity-anchor number)

Published RGD balloon seed-0 ATE = 2.2571 cm. The smoke read 2.0618. Invariance
decomposition (all SE(3)-Umeyama, positions, same math):

| comparison | ATE (cm) |
|---|---|
| RGD est vs RGD's exported GT (file-internal, their reference) | 2.2571 |
| both est+gt mapped through our anchor `A` | 2.2586 = 2.2571 × s (s=1.00066) |
| mapped est vs **our** dataset GT (TUMParser association) | **2.0618** |

The frame mapping is ATE-preserving (row 2). The entire 0.195 cm gap is a
**GT-reference difference**: RGD's exported `trj_gt` vs our TUMParser GT
association differ by 0.336 cm RMSE (the anchor residual) — a ~15% reference
perturbation on a 2.26 cm signal. Same physical trajectory, two GT samplings.

**Implication for the 5-row table:** score every row against OUR dataset GT
(single consistent reference). Injected-RGD rows on balloon seed 0 read
~2.06, not the published 2.26; quote published numbers only with the
GT-association caveat. `tests/test_oracle_pose.py` now pins both facts
(file-internal 2.2571 ± 0.02; cross-reference 2.0618 ± 0.02, deterministic).

## Expected side effect (not a bug)

KF count 19 vs 26 on the P0-QUAD same-arm same-seed run: KF triggers are
pose-driven and the injected trajectory differs from MonoGS's own tracked
one. Within the injected rows (3/4/5) all arms ride the same trajectory, so
this does not confound arm-vs-arm admission comparisons.

## Provenance

- code: commit 3edce7a (`utils/oracle_pose.py`, frontend wiring, vacated-region metric)
- trajectory data: `external_trajectories/rgd/` (untracked; gitignored) —
  24/24 files match published ATE via `scripts/check_rgd_trajectories.py`
- throwaway smoke config: `/tmp/oracle_smoke_deferred_balloon.yaml` (not committed, per smoke hygiene)

**Next gate (user decision pending): 5-row experiment table design.**
