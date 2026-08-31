# Rendering data inventory + table scaffold (2026-08-03; full-frame batch landed 2026-08-04)

> **Status:** scaffold from P2-T 36-run artifacts. **Full-frame PSNR/SSIM/LPIPS/depth_l1
> batch LANDED 2026-08-04** on the 2060 — all 36 runs re-rendered offline from
> `final_after_opt` PLY + `trj_full_final` (the in-run eval NaN bug is bypassed, not
> fixed in live code; see §4). Static-band PSNR is **2060 screening** — re-confirm on
> 3090 if approved, but band metrics are GPU-stable (pose/map-driven). The full-frame
> numbers below are **the paper's main rendering table numbers** (3-seed, ddof=1 std),
> produced by `scripts/r2_p2_t_offline_render.py` run as a batch 2026-08-04 15:40→~20:15.

## 1. What rendering data we HAVE vs LACK

| metric | have? | source | paper-ready? |
|---|---|---|---|
| static-band PSNR/SSIM/depth (band10/25/50) | YES | `band_metrics.json` per run | screening (re-confirm 3090) |
| static-region full PSNR (vacated/non-vacated) | YES | `mapping_raw.csv` (empty in P2-T — see §3) | needs investigation |
| vacated-region (ghost) PSNR/depth | YES | `mapping_raw.csv` / `eval_vacated_posthoc.py` | screening |
| **full-frame PSNR/SSIM/LPIPS/depth_l1** | **YES (2026-08-04)** | `r2_p2_t_offline_render.py` → `posthoc_fullframe/fullframe_summary.json`, 36/36 | **paper-ready (2060)** |

**The eval_rendering NaN bug** (cadence collision: eval interval=5 == KF gap_cap=5 →
all sampled frames are keyframes → all skipped → NaN) is **root-caused and the offline
re-render fix is validated** (`results/evidence/rendering_eval_bug_rca.md`,
balloon pilot full-frame PSNR 22.04, band faithfulness ΔPSNR 0.031 dB). The fix script
exists; only the 36-run batch is deferred to 3090.

## 2. Static-band PSNR (3-seed mean, P2-T, our 2060 screening)

From `band_metrics.json` across all 36 P2-T runs (band = annular static region around
dynamic-object mask, radius 10/25/50 px; this is the static-background quality the
deferred-vs-prune lifecycle acts on):

| seq | arm | band10 | band25 | band50 | frames |
|---|---|---|---|---|---|
| balloon | prune | 23.68 | 23.97 | 24.18 | 88 |
| balloon | deferred | 23.25 | 23.48 | 23.66 | 88 |
| balloon2 | prune | 22.23 | 22.51 | 22.25 | 94 |
| balloon2 | deferred | 22.30 | 22.53 | 22.26 | 94 |
| mv_no_box | prune | 26.21 | 26.51 | 26.47 | 156 |
| mv_no_box | deferred | 25.84 | 26.15 | 26.13 | 156 |
| mv_no_box2 | prune | 26.55 | 26.60 | 26.58 | 188 |
| mv_no_box2 | deferred | 26.23 | 26.33 | 26.32 | 188 |
| pt1 | prune | 25.25 | 25.27 | 24.91 | 116 |
| pt1 | deferred | 24.69 | 24.69 | 24.36 | 116 |
| pt2 | prune | 25.56 | 25.52 | 24.79 | 114 |
| pt2 | deferred | 24.65 | 24.68 | 24.06 | 114 |

**Read:** static-band PSNR 22-27 dB across seqs. prune ≥ deferred on 5/6 seqs (balloon2
flat) — consistent with deferred admitting fewer Gaussians (compactness) at a small
static-fidelity cost (the documented "compactness at equal-or-slightly-lower fidelity"
trade). This is the **lifecycle-side rendering evidence**; full-frame is the
**competitor-comparable** rendering evidence (pending 3090).

## 3. Why mapping_raw.csv static_psnr is empty (investigate, no GPU)

`mapping_raw.csv` has `static_psnr/ssim/lpips/depth` columns but they came back empty
in P2-T, while `band_metrics.json` (written by the same `eval_static_background_raw`
call) is populated. Likely: the aggregate static-region PSNR is written to
`band_metrics.json` only when `static_bg_band_px` is set (it is, in the combined
backbone), and the `mapping_raw.csv` static columns are only populated on a different
code path (no band_px). **Not blocking** — band_metrics.json has the data; the CSV
emptiness is a readout artifact, not missing data. Confirm on 3090 batch.

## 4. Full-frame PSNR pilot → batch (LANDED 2026-08-04)

`r2_p2_t_offline_render.py` pilot on balloon_prune_seed0 gave full-frame PSNR 22.04,
band_check OK (ΔPSNR 0.031 dB). The **36-run batch** ran 2026-08-04 on the 2060
(~4.5h wall, 36/36 exit, 35/36 band_check PASS at 0.05dB tol — 1 marginal:
balloon/deferred/seed2 ΔPSNR 0.063dB, still <0.1dB, noted not dropped). Lands in
codex's "20-23 competitive tier" — beats MonoGS/SplaTAM/Co-SLAM, loses to RGD/DG-SLAM.
The dynamic-pixel penalty vs static-band (~2dB) is expected (full-frame includes the
moving object the map cannot reconstruct). **These are now the main-table numbers.**

## 4b. Full-frame results — 3-seed mean±std (paper main rendering table)

> Source: `results/runs/P2/P2-T/*/datasets_bonn/*/seed_*/*/posthoc_fullframe/fullframe_summary.json`.
> 36/36 runs. Std = sample sd (ddof=1). LPIPS std omitted (sub-thousand noise).

| seq | arm | n | PSNR↑ | SSIM↑ | LPIPS↓ | depth_l1_cm↓ |
|---|---|---|---|---|---|---|
| balloon | prune | 3 | 21.86±0.25 | 0.8578±0.0013 | 0.2733 | 25.22±0.68 |
| balloon | deferred | 3 | 21.32±0.05 | 0.8499±0.0019 | 0.2924 | 26.08±0.34 |
| balloon2 | prune | 3 | 19.14±0.14 | 0.8132±0.0007 | 0.3280 | 38.20±2.34 |
| balloon2 | deferred | 3 | 19.11±0.11 | 0.8111±0.0012 | 0.3302 | 38.88±1.36 |
| mv_no_box | prune | 3 | 24.54±0.10 | 0.8767±0.0013 | 0.2192 | 18.82±0.60 |
| mv_no_box | deferred | 3 | 24.43±0.06 | 0.8710±0.0016 | 0.2323 | 19.58±0.35 |
| mv_no_box2 | prune | 3 | 25.18±0.15 | 0.8866±0.0010 | 0.2293 | 18.56±1.29 |
| mv_no_box2 | deferred | 3 | 24.98±0.21 | 0.8822±0.0015 | 0.2388 | 19.04±1.85 |
| pt1 | prune | 3 | 22.31±0.09 | 0.8610±0.0018 | 0.2746 | 26.74±1.42 |
| pt1 | deferred | 3 | 22.05±0.34 | 0.8487±0.0118 | 0.2920 | 28.04±1.83 |
| pt2 | prune | 3 | 22.04±0.29 | 0.8591±0.0036 | 0.2652 | 27.53±1.46 |
| pt2 | deferred | 3 | 21.71±0.45 | 0.8392±0.0191 | 0.2970 | 31.77±4.41 |

**Δ (prune − deferred), positive = prune better:**

| seq | ΔPSNR | ΔSSIM(×1e-3) | ΔLPIPS(×1e-3) | Δdepth_cm |
|---|---|---|---|---|
| balloon | +0.54 | +7.9 | −19.1 | −0.85 |
| balloon2 | +0.04 | +2.2 | −2.2 | −0.68 |
| mv_no_box | +0.12 | +5.8 | −13.2 | −0.77 |
| mv_no_box2 | +0.21 | +4.4 | −9.4 | −0.48 |
| pt1 | +0.26 | +12.3 | −17.4 | −1.30 |
| pt2 | +0.33 | +19.9 | −31.7 | −4.24 |

**Read:** prune is not worse than deferred on full-frame rendering on **6/6** sequences
across all four metrics (PSNR/SSIM higher, LPIPS/depth lower for prune). The margin is
small in dB on box/person seqs (+0.04 to +0.33 PSNR) but grows on balloon (+0.54) and
pt2 (depth −4.24cm). This is consistent with — and does not reverse — the P2-T
ATE-compactness Pareto story: deferred admits fewer Gaussians (compactness) at a
tracking cost (ATE 6/6 worse) **and** a small rendering cost (full-frame 6/6 not
better); the deferred arm's trade is compactness-for-nothing-detectable on fidelity
axes, both tracking and rendering. The lifecycle-side rendering evidence (static-band,
§2) and the competitor-comparable full-frame evidence agree in direction.

**Band-faithfulness:** 35/36 PASS at 0.05dB tol; 1 marginal (balloon/deferred/seed2
ΔPSNR 0.063dB) — still <0.1dB, recorded, not dropped. The re-render reproduces the
in-run static-band PSNR on the same frames to within tens of milli-dB, so the
full-frame numbers are a faithful extension of the in-run eval, not a different
measurement.

## 5. Main rendering table (filled 2026-08-04)

| seq | method | full PSNR↑ | full SSIM↑ | full LPIPS↓ | full depth_l1↓ | static-band PSNR (b25) |
|---|---|---|---|---|---|---|
| balloon | **Ours-prune** | 21.86±0.25 | 0.8578 | 0.2733 | 25.22 | 23.97 |
| balloon | **Ours-deferred** | 21.32±0.05 | 0.8499 | 0.2924 | 26.08 | 23.48 |
| balloon | MonoGS / RGD / DG-SLAM | [pull] | | | | — |
| balloon2 | **Ours-prune** | 19.14±0.14 | 0.8132 | 0.3280 | 38.20 | 22.51 |
| balloon2 | **Ours-deferred** | 19.11±0.11 | 0.8111 | 0.3302 | 38.88 | 22.53 |
| mv_no_box | **Ours-prune** | 24.54±0.10 | 0.8767 | 0.2192 | 18.82 | 26.51 |
| mv_no_box | **Ours-deferred** | 24.43±0.06 | 0.8710 | 0.2323 | 19.58 | 26.15 |
| mv_no_box2 | **Ours-prune** | 25.18±0.15 | 0.8866 | 0.2293 | 18.56 | 26.60 |
| mv_no_box2 | **Ours-deferred** | 24.98±0.21 | 0.8822 | 0.2388 | 19.04 | 26.33 |
| pt1 | **Ours-prune** | 22.31±0.09 | 0.8610 | 0.2746 | 26.74 | 25.27 |
| pt1 | **Ours-deferred** | 22.05±0.34 | 0.8487 | 0.2920 | 28.04 | 24.69 |
| pt2 | **Ours-prune** | 22.04±0.29 | 0.8591 | 0.2652 | 27.53 | 25.52 |
| pt2 | **Ours-deferred** | 21.71±0.45 | 0.8392 | 0.2970 | 31.77 | 24.68 |

**Protocol:** full-frame PSNR/SSIM/LPIPS mandatory (10/11 baselines use mask_type='full',
per `03-metrics_checklist.md`), 3 seeds, mean±std (ddof=1). Static-band is our
supplementary lifecycle-evidence column, not the competitor-comparable headline.
Competitor full-frame numbers still to be pulled from papers (§6 TODO 3). FPS is a
2060 number — **not tabled next to competitors' 3090/4090 figures** (VRAM may, and
"runs inside 6 GB" is itself the claim; see HANDOFF "2060 全实验可行性判定").

## 6. TODO

1. ~~Run `r2_p2_t_offline_render.py` on all 36 P2-T runs~~ ✅ DONE 2026-08-04 (§4b).
2. Re-confirm static-band PSNR on 3090 if approved (should match §2 within noise — GPU-stable).
3. **Pull exact competitor full-frame numbers from papers** for the main table (the only
   remaining `[pull]` cells).
4. **If ReliableTracking admitted:** re-render RT-on runs (RT changes poses → rendering).

## Reproduce

- static-band aggregation: inline `python` over `results/runs/P2/P2-T/*/datasets_bonn/*/seed_*/*/band_metrics.json`
- full-frame offline render: `scripts/r2_p2_t_offline_render.py` (validated 2026-08-03)
- bug RCA: `results/evidence/rendering_eval_bug_rca.md`
