# DBA photo-weighted BA — design (2026-08-03, branch dba-photo-weighted)

> **Goal:** the one open door to a tracking-side ATE gain. DBA-lite's GT-oracle
> found the masked dense **geometric** objective is minimized at online poses, not GT
> (`dba_lite_oracle_provenance_audit.md`). But its **photometric** proxy is an
> **unweighted median** of brightness residuals — it does NOT consume the reliability
> weight `w` that the backbone produces online. If the reliability-weighted photometric
> objective *does* prefer GT (residual falls as pose→GT), a reliability-weighted
> photometric BA can close part of the gap the pure-geometric one can't. This file is
> the minimal-change design + the oracle-first test that gates whether to build v0.

## The interface boundary (from two read-only surveys)

### DBA-lite side (`utils/dba_lite.py`)
- `_edge_photometric_resid(gi,gj,Tcw_i,Tcw_j,cfg,device)` (line 479) → returns **scalar**
  `median|r|` after a per-edge affine brightness fit. No per-pixel weight, no Jacobian.
- `_edge_two_sided(...)` (line 121) → returns `(r, J_i, J_j, w)` over inliers (the format
  the GN loop expects). Robust weight `w` is a MAD-clamp on the geometric residual.
- `run_dba_v0` GN loop (line 723): `for i,j in opt_edges: res=_edge_two_sided(...);
  r,Ji,Jj,w=res; we=w/n; accumulate H,g from (Ji,Jj,we,r)`. **Joint insertion point**:
  a photo edge producing `(r,Ji,Jj,w)` slots in alongside the geometric edge.
- `run_dba_oracle.agg_photo` (line 586) calls `_edge_photometric_resid` per edge at
  t=0..1 to judge `photo_biased`. Shares the function with v0.
- `_precompute_kf_geom` (line 67) builds the geom dict; `Is`/`graygrid` already packed.
  A per-source-pixel photo weight slots in as `out["w_photo"] = w[valid]` parallel to `Is`.
- `_reload_kf_geom` (line 434) reloads depth+mask+gray from dataset per KF.
- Config `DBALite` (base_config.yaml:238): flags `diagnostic/oracle/enabled`; add
  `photo_weighted: false` (+ optional `lam_photo`).

### Reliability-weight side (`utils/reliability_signal.py`, `utils/slam_frontend.py`)
- `compute_reliability_tracking_weight(obs_depth, render_depth, opacity, f_obs, R_ts,
  t_ts, fx, fy, cx, cy, geo_scale_floor, flow_scale_floor)` (reliability_signal.py:323)
  → `(s, w, fv, stats)`. `w` is `(H,W)∈(0,1]` per-pixel Cauchy tracking down-weight.
- **`w_map` is NEVER persisted.** Online it's consumed as `reliability_soft=(1-w)` in
  the tracking loss (slam_frontend.py:968) then discarded. `reliability_signal_rows`
  (flushed to `reliability_signal/frames.csv`) holds only **scalars** (mean_s, min_w, …).
- `s_map`/`fv_map` ARE stashed on the viewpoint object in-memory
  (`viewpoint.reliability_s`, slam_frontend.py:980) when `DeferredCommit.reliability_confirm`
  is on — but also not persisted.
- **Frozen flow `f_obs`** (`utils/flow_raft.py`): precomputed backward RAFT `.npy` under
  `Dataset.dataset_path/ReliabilitySignal.flow_subdir` (default `flow_raft`).
  **All 9 Bonn seqs have them** (438-930 files). Fully reloadable offline via
  `frozen_flow_index()` + `load_frozen_flow()`, keyed by depth-path stem.

### The one hard missing piece for offline recompute
`compute_reliability_tracking_weight` needs `render_depth` + `opacity` (a render of the
current map at the KF pose). DBA-lite currently does NOT render. **But** the P2-T runs
saved `point_cloud/final_after_opt/point_cloud.ply` — DBA-lite can load it + render each
KF to get `render_depth`/`opacity`. So offline recompute is **fully supported by existing
saved artifacts**; no online-loop modification or per-pixel-map persistence needed.

## Decision: oracle-first (cheap gate), then v0 only if it opens

Per the audit: spend the **oracle** GPU first (read-only, no pose writes, ~30min/run).
Set `DBALite.oracle: true` + a new `photo_weighted: true` on the combined prune config,
run balloon seed0 `--fast`. The oracle interpolates online→GT and measures the
**reliability-weighted photo residual** at each t.

- **If photo residual FALLS as pose→GT** (GT lowers the weighted photo objective):
  the weighted photometric term is NOT biased away from GT → a reliability-weighted
  photo-BA **might** close part of the gap → **build v0** (add the photo edge to the
  GN loop, FD-verify its Jacobian, run the solver, measure ATE).
- **If photo residual still RISES** (weighted objective also minimized at online):
  the reliability weight doesn't change the bias → **close the door**; tracking stays
  at P2-T status, and this becomes the second mechanism finding (geometric AND
  reliability-weighted-photometric objectives both prefer online poses on these seqs).

This is the minimal-information-order path: one oracle run decides whether v0 is worth
building. No solver code written until the oracle says the objective prefers GT.

## Minimal-change plan (implementation order)

### Step 0 — oracle gate (write only if photo_weighted changes the verdict)
1. Add `photo_weighted: false` (+ `lam_photo: 0.0`) to `DBALite` config block.
2. In `_precompute_kf_geom`: when `photo_weighted`, load each KF's reliability `w_map`
   (recomputed offline: load final PLY → render at KF pose → `compute_reliability_tracking_weight`
   with dataset depth + frozen flow + prev-KF pose) and pack `out["w_photo"] = w[valid]`
   parallel to `Is`.
3. New `_edge_photometric_resid_weighted(gi,gj,...)`: same as `_edge_photometric_resid`
   but returns `sum(w_photo * |r|) / sum(w_photo)` (weighted median/mean) instead of
   `median|r|`. Oracle's `agg_photo` calls this when `photo_weighted`.
4. Config `p2s_combined_prune_balloon_dbaoracle_photo.yaml`: `DBALite.oracle: true`,
   `photo_weighted: true`, `enabled: false`. Run balloon seed0 `--fast`.

### Step 1 — v0 photo edge (ONLY if oracle says photo prefers GT)
5. `_edge_photometric_jac(gi,gj,...)`: weighted photo residual `(r, J_i, J_j, w)` with
   image-gradient Jacobian (sample target graygrid gradient + projection Jacobian),
   FD-verified against the geometric edge's existing two-sided FD harness.
6. In `run_dba_v0` GN loop: alongside `_edge_two_sided`, call the photo edge and
   accumulate its `(r,Ji,Jj,w)` into the same `H,g` weighted by `lam_photo`.
7. Spike: balloon seed0 `--fast` with `DBALite.enabled: true, photo_weighted: true`;
   compare ATE vs P2-T control 2.8686.

## Reproduce / artifacts
- P2-T balloon saved PLY: `results/runs/P2/P2-T/balloon_prune_seed0/.../point_cloud/final_after_opt/point_cloud.ply`
- frozen flow: `datasets/bonn/rgbd_bonn_balloon/flow_raft/*.npy`
- prev-frame pose: `plot/trj_full_final.json` per run
- reliability config: `ReliabilitySignal` (flow_subdir, geo/flow_scale_floor)

## What this does NOT touch (provenance guard)
- Does not modify the online tracking loop (`slam_frontend.py` tracking path) —
  DBA-lite runs post-tracking, read-only on the saved trajectory + map.
- Does not change P2-T recorded results or the deferred-vs-prune headline.
- Non-preregistered; paper must label it exploratory.
- Per [[task-cadence-doc-sync]]: commit before any GPU run; sync 03-results tracking
  archive + HANDOFF if the oracle/v0 verdict flips anything.
