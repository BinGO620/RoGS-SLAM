# R2-P01-E2 — Oracle-admission four-row table (deferred vs prune under weak & strong trajectories)

- **Date:** 2026-07-27 (batch 00:01→13:24 CST, ~13.4h, RTX 2060)
- **Code commit:** a3eaa22
- **Results root (gitignored):** `results/runs/R2-P01/R2-P01-E2/`
- **Design:** approved v2 four-row table. Per sequence: MonoGS-self-tracked×{prune,deferred} (weak-trajectory regime) + RGD-injected×{prune,deferred} (strong-trajectory regime). 28 runs = 5 dyn seq × 4 rows (seed 0) + balloon injected seed 1 (×2) + self balloon seed 1 skipped-for-time → actually: block1 12 injected (10 + balloon s1 ×2), block2 12 self (10 + balloon s1 ×2), block3 4 static.
- **Injection integrity:** all 12 injected runs hit their pre-registered ATE target to 4 dp (balloon 2.0618, balloon2 3.2907, mv_no_box 2.0538, mv_no_box2 4.2138, pt2 26.2966) under the ±0.02cm fail-fast → injection chain exact end-to-end, SLAM-seed independent. Prune and deferred injected rows share an **identical** trajectory (frozen pose), so any injected-regime map delta is **pure map-admission**, not tracking.

## Verdict summary

1. **Phase-0 ghost metric → DEMOTED to auxiliary (pre-registered).** On the R1-P01-E2 self-tracked runs, deferred-better on `vacated_depth_l1_pen_cm` was **0/5** voting seqs (prune won all 5); faithfulness intact (all band-checks pass, all support>0). Below the ≥4/5 bar → per the pre-committed rule the vacated-region ghost drops to auxiliary; fallback co-primary = **geometry F@5cm + all-static depth_l1_pen**.
2. **Fidelity co-primary (F@5cm + static_depth) → gate NOT met.** Mixed/bistable across seq, regime, and seed. Per-seq deferred-better count over {self,injected}×{F,static_depth} (max 4/4): balloon 3/4, balloon2 2/4, mv_no_box 2/4, mv_no_box2 2/4, pt2 4/4. Only pt2 clears 4/4. Balloon (the seed-replicated seq) **flips direction between seeds** (seed0 deferred-better on both; seed1 prune-better on both) → not seed-stable. The two co-primary sub-metrics frequently disagree with each other within a cell. **Deferred does not consistently improve fidelity — but also shows no systematic fidelity harm** (individual cells go both ways; worst regression mv_no_box2 injected static_depth +5.3cm; static f1_desk fidelity improves).
3. **ROBUST, multi-seed, both-regime, tracker-orthogonal win → MAP COMPACTNESS at equal fidelity.** Deferred commits far fewer Gaussians for equal-or-better ATE/F/PSNR, at lower VRAM and equal/higher FPS:
   - **13/14 pairs deferred-fewer Gaussians.** Injected (pose-controlled) mean deferred/prune ratio = **0.426 → −57% Gaussians on the identical trajectory** (balloon −58%, balloon2 −56%, mv_no_box −69%, pt2 −77%).
   - VRAM tracks it (self mv_no_box2 4.04→2.04 GB, halved; injected rows ~1.1→0.85 GB).
   - FPS equal-or-better (injected pt2 6.19→9.71, mv_no_box 6.68→9.38).
   - Holds on **static** too: f1_desk −25% Gaussians (45221→33884) **with F@5cm 65.4→69.4 and ATE 1.52→1.38 — better, not just no-harm**; f2_xyz −22%.
   - Lone exception (self/balloon/seed1) is the same bistable seed that flipped fidelity.
4. **Static no-harm → CLEAN.** f1_desk deferred beats prune on ATE (1.38 vs 1.52), F@5cm (69.4 vs 65.4), PSNR (23.67 vs 23.34). f2_xyz deferred ATE 1.82 vs 1.93. No static regression on either side.
5. **Self-tracked ATE (weak regime, secondary):** deferred less catastrophic on 4/5 (balloon 37.7→29.0, mv_no_box 18.3→5.0, mv_no_box2 10.0→6.2, pt2 44.2→21.0; balloon2 14.9→15.8 ~flat). This is a tracking-feedback effect in a noisy regime (prune ATEs are catastrophic), NOT a map-fidelity claim.

**Bottom line:** the *fidelity*-headline for deferred admission is **not supported** at the pre-registered bar (mixed + balloon seed-flip). The clean, large, multi-seed, both-regime, includes-static signal is **map compactness at equal fidelity** (−57% Gaussians pose-controlled, lower VRAM, equal/better FPS), which directly instantiates "reduce dynamic contamination" as *fewer dynamic-object Gaussians admitted*. Narrative pivot (fidelity→compactness headline) and 3090 multi-seed confirmation are **reserved for the user** (GO/KILL is not mine to call).

## Dynamic 4-row table (seed 0)

ATE = tracking_raw ate_rmse_cm (headline). F@5cm & static_depth = fallback co-primary. vac_depth & PSNR = auxiliary.

| seq | regime | arm | ATE cm | F@5cm | static_depth cm | vac_depth cm | static_PSNR | PSNR |
|---|---|---|---|---|---|---|---|---|
| balloon | self | prune | 37.720 | 1.891 | 23.043 | 23.547 | 22.027 | 22.03 |
| balloon | self | deferred | 29.032 | 1.964 | 23.114 | 23.860 | 21.320 | 21.32 |
| balloon | injected | prune | 2.062 | 0.874 | 37.007 | 36.785 | 14.958 | 14.96 |
| balloon | injected | deferred | 2.062 | 1.204 | 36.178 | 36.043 | 15.131 | 15.13 |
| balloon2 | self | prune | 14.919 | 3.074 | 27.104 | 26.382 | 19.165 | 19.16 |
| balloon2 | self | deferred | 15.781 | 2.912 | 24.764 | 24.252 | 19.858 | 19.86 |
| balloon2 | injected | prune | 3.291 | 2.739 | 38.142 | 38.700 | 14.686 | 14.69 |
| balloon2 | injected | deferred | 3.291 | 2.275 | 37.752 | 37.842 | 14.623 | 14.62 |
| mv_no_box | self | prune | 18.331 | 3.002 | 20.327 | 19.973 | 22.904 | 22.90 |
| mv_no_box | self | deferred | 5.024 | 2.459 | 16.906 | 16.425 | 24.601 | 24.60 |
| mv_no_box | injected | prune | 2.054 | 0.006 | 35.048 | 34.775 | 15.559 | 15.56 |
| mv_no_box | injected | deferred | 2.054 | 0.606 | 35.840 | 35.870 | 15.481 | 15.48 |
| mv_no_box2 | self | prune | 9.998 | 3.081 | 20.758 | 21.339 | 24.665 | 24.66 |
| mv_no_box2 | self | deferred | 6.234 | 2.835 | 18.521 | 18.870 | 25.285 | 25.29 |
| mv_no_box2 | injected | prune | 4.214 | 0.641 | 37.798 | 37.615 | 15.601 | 15.60 |
| mv_no_box2 | injected | deferred | 4.214 | 1.000 | 43.084 | 43.001 | 15.488 | 15.49 |
| pt2 | self | prune | 44.215 | 1.823 | 27.268 | 27.403 | 20.936 | 20.94 |
| pt2 | self | deferred | 20.994 | 3.349 | 27.255 | 26.859 | 21.592 | 21.59 |
| pt2 | injected | prune | 26.297 | 0.823 | 39.905 | 39.890 | 14.832 | 14.83 |
| pt2 | injected | deferred | 26.297 | 1.160 | 38.105 | 37.862 | 15.009 | 15.01 |

Note: injected-regime map metrics are globally worse than self-tracked (PSNR ~15 vs ~19-25, static_depth ~35-43 vs ~16-27) despite ~2cm ATE — frozen poses cannot co-adapt with the map → globally blurrier reconstruction. The paired prune-vs-deferred delta remains valid (same frozen poses). mv_no_box injected F is near-zero for both arms (noisy).

## Efficiency / compactness (FPS, VRAM, Gaussian counts)

| regime | arm | seq | seed | FPS | VRAM GB | G_online | G_refined |
|---|---|---|---|---|---|---|---|
| self | prune | balloon | 0 | 0.63 | 1.29 | 25896 | 25896 |
| self | deferred | balloon | 0 | 0.66 | 1.11 | 20355 | 20355 |
| self | prune | balloon | 1 | 0.62 | 1.18 | 22309 | 22309 |
| self | deferred | balloon | 1 | 0.65 | 1.19 | 24849 | 26222 |
| inj | prune | balloon | 0 | 6.28 | 1.02 | 28404 | 28404 |
| inj | deferred | balloon | 0 | 8.32 | 0.81 | 11863 | 11863 |
| inj | prune | balloon | 1 | 1.85 | 1.28 | 31012 | 31012 |
| inj | deferred | balloon | 1 | 8.05 | 0.80 | 12149 | 12149 |
| self | prune | balloon2 | 0 | 0.56 | 1.80 | 59660 | 59660 |
| self | deferred | balloon2 | 0 | 0.62 | 1.25 | 27021 | 27021 |
| inj | prune | balloon2 | 0 | 6.18 | 1.13 | 29793 | 29793 |
| inj | deferred | balloon2 | 0 | 7.28 | 0.86 | 13155 | 13155 |
| self | prune | mv_no_box | 0 | 0.57 | 1.68 | 34286 | 34286 |
| self | deferred | mv_no_box | 0 | 0.59 | 1.54 | 28705 | 28705 |
| inj | prune | mv_no_box | 0 | 6.68 | 1.16 | 21336 | 26336 |
| inj | deferred | mv_no_box | 0 | 9.38 | 0.89 | 8278 | 8278 |
| self | prune | mv_no_box2 | 0 | 0.45 | 4.04 | 86391 | 86391 |
| self | deferred | mv_no_box2 | 0 | 0.54 | 2.04 | 46973 | 46973 |
| inj | prune | mv_no_box2 | 0 | 6.66 | 1.31 | 12026 | 17026 |
| inj | deferred | mv_no_box2 | 0 | 7.73 | 1.05 | 12930 | 12930 |
| self | prune | pt2 | 0 | 0.51 | 2.79 | 62465 | 62465 |
| self | deferred | pt2 | 0 | 0.49 | 2.29 | 61704 | 61704 |
| inj | prune | pt2 | 0 | 6.19 | 1.17 | 32943 | 32943 |
| inj | deferred | pt2 | 0 | 9.71 | 0.84 | 7604 | 7604 |
| static | prune | f1_desk | 0 | 0.45 | 2.06 | 45221 | 45221 |
| static | deferred | f1_desk | 0 | 0.49 | 1.82 | 33884 | 33884 |
| static | prune | f2_xyz | 0 | 0.73 | 2.17 | 37564 | 37564 |
| static | deferred | f2_xyz | 0 | 0.72 | 2.15 | 29376 | 29376 |

## Static no-harm rows

| seq | arm | ATE cm | F@5cm | PSNR |
|---|---|---|---|---|
| f1_desk | prune | 1.518 | 65.432 | 23.34 |
| f1_desk | deferred | 1.380 | 69.380 | 23.67 |
| f2_xyz | prune | 1.933 | n/a (--fast) | n/a |
| f2_xyz | deferred | 1.824 | n/a (--fast) | n/a |

## Phase-0 ghost detail (pre-registered demotion)

Voting metric `static_vacated_depth_l1_pen_cm` (lower better), R1-P01-E2 self-tracked runs, posthoc byte-faithful (all band_check pass):

| seq | prune | deferred | winner |
|---|---|---|---|
| balloon | 23.58 | 24.50 | prune |
| balloon2 | 25.12 | 25.74 | prune |
| mv_no_box | 15.72 | 19.88 | prune |
| mv_no_box2 | 21.66 | 22.00 | prune |
| pt2 | 28.07 | 29.05 | prune |

deferred-better 0/5 → GHOST → AUXILIARY. (obox, non-voting: deferred 22.03 vs prune 25.49 = deferred-better, but obox is stress-test only.)

## Reproduce

- Batch driver: `/tmp/r2_batch.sh` (throwaway, not committed).
- Assembler: `/tmp/r2_assemble.py`; efficiency dump inline in batch console.
- Phase-0: `scripts/eval_vacated_posthoc.py` + `/tmp/phase0_verdict.py` (committed 9bffb75 / throwaway).
- Configs: `configs/rgbd/experiments/r2_oracle_admission/` (committed 7f34ece, a3eaa22).
