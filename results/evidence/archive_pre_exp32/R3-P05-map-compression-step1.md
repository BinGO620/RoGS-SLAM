# STEP 1 — map-compression offline gate (2026-08-05)

**Question.** Does a genuine prune-style compactness lever exist in our saved final
maps: a "safely deletable" set of Gaussians that can be removed with negligible PSNR
cost, and is it dynamic-agnostic (an independent axis, NOT anti-dynamic eviction)?

Branch: rethink-method. Repo: /data/monogs-ours.
Probes: `scripts/mc_opacity_deletion_curve.py`, `scripts/mc_removable_dynamics.py`
(zero-GPU, offline re-render of saved final_after_opt PLY at saved trj_full_final
est poses — the paper-table render path). No live code changed.

---

## Method

- For each of 4 P2-T dynamic sequences, load the prune-arm seed-0 final map.
- **Curve probe** (`mc_opacity_deletion_curve.py`): re-render full-frame PSNR
  (interval=5, est poses) at the stack reference, then prune everything with
  sigmoid opacity below each threshold q ∈ {0.01,0.02,0.05,0.08,0.10,0.15,0.20}
  and measure dPSNR. Uses `_prune_raw` (optimizer-free slice) so no optimizer needed.
- **Dynamics probe** (`mc_removable_dynamics.py`): project every Gaussian center at
  ~20 spread trajectory frames; count the fraction of `opacity<0.05` Gaussians whose
  projected center lands on the union of all frozen dynamic masks vs on a
  never-dynamic eroded control. vac_excess = removable-rate(union) − removable-rate(control).
  ~0/negative ⇒ no dynamic-region bias ⇒ compaction is spatial, not anti-dynamic.

## Validity anchors

- Reference re-render (my interval-5 loop) matches stored `posthoc_fullframe`
  PSNR to < 0.04 dB everywhere (e.g. balloon 22.0748 vs 22.0407; small residual from
  0×exposure / LPIPS off). The render path is the established one.
- Reference PSNR per sequence: balloon 22.041, mv_no_box 24.443, pt1 22.213, pt2 22.313
  (stored fullframe_summary.json).

## Results

| seq | N | q=0.01 rm | dPSNR | q=0.05 rm | dPSNR | q=0.10 rm | dPSNR | vac_excess(op<0.05) |
|---|---|---|---|---|---|---|---|---|
| balloon     | 32,653 | 12.8% | −0.0001 | 20.4% | −0.0156 | 27.1% | −0.2887 | +0.017 |
| mv_no_box   | 43,598 |  9.9% | +0.0000 | 15.0% | −0.0110 | 19.8% | −0.1496 | +0.024 |
| pt1         | 49,838 |  9.9% | +0.0000 | 12.6% | −0.0059 | 15.7% | −0.0657 | −0.003 |
| pt2         | 92,537 | 18.4% | −0.0000 | 23.6% | −0.0030 | 28.6% | −0.0675 | +0.000 |

Full opacity-*deletion* curve per sequence (removal grows steeply past 0.05):

```
balloon:    op>=0.01 rm12.8% -0.0001 | >=0.02 15.0% -0.0003 | >=0.05 20.4% -0.0156 | >=0.08 24.8% -0.110 | >=0.10 27.1% -0.289
mv_no_box:  op>=0.01  rm9.9% +0.0000 | >=0.02 11.4% -0.0004 | >=0.05 15.0% -0.0110 | >=0.08 18.0% -0.093 | >=0.10 19.8% -0.150
pt1:        op>=0.01  rm9.9% +0.0000 | >=0.02 10.7% -0.0000 | >=0.05 12.6% -0.0059 | >=0.08 14.5% -0.027 | >=0.10 15.7% -0.066
pt2:        op>=0.01 rm18.4% -0.0000 | >=0.02 20.0% -0.0017 | >=0.05 23.6% -0.0030 | >=0.08 26.8% -0.034 | >=0.10 28.6% -0.068
```

## Interpretation (pre-registered death rules vs. what we found)

1. **Safe deletion set EXISTS.** Removing `opacity<0.01` costs nothing
   (|dPSNR|≤0.0001 everywhere); `opacity<0.05` costs only −0.03 to −0.016 dB at
   12.6–23.6% removal. The semi-transparent tail is disposable floaters, not
   surface-carrying structure. A 15–24% compactness lever at <0.02 dB is real in the
   FINAL map.
2. **Dynamics-agnostic (independent axis).** vac_excess of the `op<0.05` set is
   ≈0 on all 4 (−0.003 to +0.024). The deletable low-opacity population is
   spatially uniform across dynamic-vacated and never-dynamic regions. This is the
   OPPOSITE of the swept-ghost story, and it is GOOD for the compression narrative:
   compaction is its own axis, not a re-run of the dead eviction/free-space work.
3. **pt2 is the most fertile target:** 92,537 N (largest map), 23.6% deletable at
   only −0.003 dB → ~21.9k absolute Gaussians.

## What this does NOT prove (the live-tracking gap)

This offline gate measures RENDERING preservation at the FINAL map with FROZEN
est poses. It does NOT measure live-tracking preservation. Deleting the same
Gaussians mid-run could free memory/iteration budget (help) or remove structure
the tracker's photometric loss leans on (hurt ATE). The only way to answer the
headline ATE question is a live SLAM experiment, where the same prune-style
filter runs during mapping and the tracker self-tracks. That is STEP 4, and it
needs GPU ~hours/run.

STEP 2/3 (zero-GPU, ~10 min each) will tighten the filter: joint
opacity×footprint selection and distance-to-visible-surface ranking, to see if we
can push deletion fraction higher at the same dB cost. STEP 4 is the GPU live test.

## NO-GO / GO gates met
- NO-GO would have been: safe-deletion fraction < ~5%, or PSNR cost > ~0.2 dB at
  10% deletion, OR vac_excess strongly positive (compaction == anti-dynamic).
- Actual: 12.6–23.6% at ≤0.016 dB with vac_excess ≈ 0. **GO to refine the filter
  (STEP 2/3) and, subject to user confirmation, prepare a live-SLAM STEP 4.**

## STEP 3 (2026-08-05) — "far from visible surface" hypothesis refuted; removable set hugs surface

Used the per-run `geometry/tsdf_mesh.ply` (voxel 0.02m) as the visible-surface proxy.
For each Gaussian center, KD-tree distance to the nearest TSDF surface vertex. Compare
the op<0.05 removable subset vs the full population across the 4 sequences:

| seq | dist-to-TSDF all p50/p90 | dist-to-TSDF op<0.05 p50/p90 | mean all | mean rem |
|---|---|---|---|---|
| balloon   | 0.1 / 0.3 cm | 0.1 / 0.2 cm | 0.1 | 0.1 |
| mv_no_box | 0.1 / 0.2 cm | 0.1 / 0.2 cm | 0.1 | 0.1 |
| pt1       | 0.1 / 0.3 cm | 0.1 / 0.3 cm | 0.1 | 0.1 |
| pt2       | 0.1 / 0.3 cm | 0.1 / 0.3 cm | 0.1 | 0.1 |

Distributions are IDENTICAL (median p50 ~0.1cm everywhere). The removable low-opacity
Gaussians are NOT deep-interior / outside zero-crossing filler; they are semi-transparent
fragments embedded in the real surface. distance-to-surface is NOT a separating lever.

**Reframing (important):** this clarifies the identity of the removable set. The low-opacity
axis is a PURE output-contribution axis — independent of the anti-dynamic axis (vac_excess≈0,
STEP1) AND of the depth-fill axis (distance-to-surface is flat, STEP3). So the compression
filter needs NO geometric assumption: no TSDF, no masks. It is just opacity (± joint footprint).
Simple to implement in the live loop.

STEP 4 (GPU, live SLAM) remains the open question: does pruning op<0.05 (or joint)
indoor during mapping change ATE? The offline gate only proves final-map render preservation.
The full STEP-4 experiment spec (filter choice, arms, readout rule, paper axis) is in
CONTEXT.md under "### 下一步" — it is pre-registered and ready-to-approve, but requires a
live-code edit to the prune path that needs user confirmation first.
