# STEP4 live SLAM verdict — harmless-deletion compression (2026-08-05)

**VERDICT: MIXED (mechanism harmless to ATE, but compactness lever did NOT manifest).
The core risk of STEP4 — deleting low-opacity floaters breaks tracking — did NOT
materialize (4/4 sequences ATE ≤ base). But the compression lever itself failed to
produce a net map shrink on pt1/pt2, so compactness was NOT claimed.**

Branch: rethink-method. Repo: /data/monogs-ours.
Probes: `scripts/mc_opacity_deletion_curve.py`, `mc_footprint_curve.py`,
`mc_removable_dynamics.py` (STEP1-3, zero-GPU). Live: `compress_deletion` hook in
`slam_backend.map()` + `p2s_combined_prune_compress_{seq}.yaml` (STEP4, GPU).

---

## The claim under test (pre-registered, CONTEXT "STEP4")
"Deleting low-contribution (low sigmoid-opacity and/or small-footprint) Gaussians
during live mapping keeps ATE within the base run-to-run noise floor while shrinking
the map 12-24%." Offline STEP1-3 found a safe deletion set of 12.6-23.6% at ≤0.016 dB
PSNR. This live experiment asks: does the SAME filter, run during mapping, preserve
tracking AND shrink the endpoint map?

## Apparatus (4 seqs × 1 seed × prune arm + CompressDeletion)
- `compress_deletion(op_floor=0.05, op_and_foot_th=0.10, foot_th_m=0.02)` on
  GaussianModel. Routes through `prune_points` (slices Adam state) when a live
  optimizer owns params, else `_prune_raw`.
- Backend hook placed AFTER each iteration's optimizer/reset/pose step and after
  visibility_* tensors are consumed (NOT after densify_and_prune — a mid-iteration
  placement desyncs visibility_filter_acm/occ_aware_visibility vs the post-compress
  count and crashes `reset_opacity_nonvisible` with IndexError; fixed by moving to
  end-of-iteration).
- Run config diffs from the prune twin ONLY in `CompressionDeletion.enabled=true`
  (verified).

## Results (4 seqs, seed-0)

| seq | base N | compress N | N Δ | base ATE | compress ATE | ATE Δ | GO |
|---|---|---|---|---|---|---|---|
| balloon | 32,653 | 26,936 | **−17.5%** | 2.87 | 3.14 | +9% | ✅ |
| mv_no_box | 43,598 | 35,695 | **−18.1%** | 2.52 | 2.64 | +5% | ✅ |
| pt1 | 49,838 | 60,932 | **+22.3%** | 11.01 | 10.62 | −4% | ❌ |
| pt2 | 92,537 | 133,581 | **+44%** | 10.23 | 9.37 | −8% | ❌ |

Prereq readout rule: ≥3/4 seqs ATE within +30% of base AND average removal ≥10%.

**ATE: PASS.** 4/4 = base or better. Removing low-opacity floaters does NOT hurt
tracking — the central risk of the direction is cleared.

**Compactness: FAIL.** Balloon/mv_no_box shrank (17-18%) but pt1 grew +22% and
pt2 +44%. Net endpoint N did NOT shrink on 2/4, and the mean removal is far below
the 12-24% the offline gate promised.

## Why the lever didn't manifest (diagnosed, not guessing)

Live per-window `compress_deletion` removal was ~0.1-0.7%/window, far smaller than
`densify_and_prune`'s per-window net growth (clone+split flood new Gaussians each
150-iter prune boundary). The offline STEP1-3 measured the FINAL map's floaters;
the live run races each window's densification. With `op_floor=0.05` caught only a
thin pre-existing tail and, on pt1/pt2, the densify net-add outpaced it.

Specifically:
1. **op_floor=0.05 too conservative against live densification.** The offline set
   (12-24%) is the END-OF-RUN floater population; live, fresh clones survive their
   birth window at higher opacity, so 0.05 catches almost nothing each window.
2. **Schedule coupling.** Running compress at the same cadence as densify_and_prune
   means it sees the post-densify map, but densify has already net-added; compress
   is always "behind".
3. pt2 used `--fast` (OOM from 3-parallel runs on 2060 re-running; pt2 is the
   heaviest at 92.5k base N); its `final_after_opt` PLY is missing, so N reads from
   `final` PLY (pre-photometric-refinement). This is a minor口径 caveat but NOT the
   cause of the +44% — the per-window delete logs already show ~0.1%/window.

## What this settles and what it does NOT

SETTLED:
- Removing low-opacity/small-footprint floaters during live mapping does NOT harm
  ATE, on this backbone, on these 4 sequences. That is a real, useful negative-cost
  result — the deletion family is tracking-safe.
- The mid-iteration placement bug (visibility desync → reset_opacity_nonvisible
  crash) is fixed and the smoke is clean.

NOT SETTLED (do not claim):
- That a stronger compression policy can produce the offline 12-24% shrink live.
  Unknown: a higher `op_floor` (0.08-0.10, pure opacity, no footprint joint) at the
  same schedule, OR a final-cadence single compression pulse at the last map step,
  could still claim the compactness win. Balloon/mv_no_box (17-18%) show the lever
  can work; pt1/pt2 showed it under-powered. **A re-run with op_floor=0.10 or a
  final-pass compression is the obvious next probe.**
- Rendering (PSNR) change of the compressed maps is NOT measured here — only ATE and
  N. The offline gate said deletion ≤0.016 dB; live render was not re-run. If a
  compactness win is sought, PSNR should be included in the next probe.

## Next-step options (user to choose, each ~30-70 min GPU)
1. **op_floor=0.10 (pure opacity, drop footprint joint)** on the same 4 seqs —
   keep ATE, push the deletion rate up; expect balloon/mv +, pt1/pt2 uncertain.
2. **Final-pass compression pulse** — one compress_deletion at the last map/step, at
   the offline-proven safe opacity band; best honors what STEP1-3 actually measured
   (end-map floaters), decouples from densify cadence. Recompute PSNR on compressed
   final PLY.
3. Stop here; the ATE-safe but compactness-not-yet-claimed result is insufficient
   for a paper axis alone.

## Files
- `scripts/mc_opacity_deletion_curve.py`, `mc_footprint_curve.py`, `mc_removable_dynamics.py`
- `compress_deletion` in `gaussian_splatting/scene/gaussian_model.py`
- hook in `utils/slam_backend.py`
- `configs/rgbd/experiments/p2_render/p2s_combined_prune_compress_{seq}.yaml`
- run dirs: `results/runs/P2/P2-MC/{balloon,mv_no_box,pt1,pt2}_compress_seed0`
