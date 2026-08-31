# P2-T readout — results/runs/P2/P2-T
# decision margins IMPORTED from r2_p03_sweep_readout: vac_depth ≤ 1.56cm, vac_psnr ≤ 0.28dB
# H-D ratio indeterminacy: |G_def/G_prune - 1| ≤ 2.0x larger own sd
# ATE no-harm band: deferred ATE > 50.0% worse than prune => flagged

## Main table (per-seq, per-arm, 3-seed mean ± own sd)
| seq | arm | G mean±sd | ATE mean±sd | vac_depth mean | vac_psnr mean | KF |
|---|---|---|---|---|---|---|
| balloon | prune | 39784±5511 | 3.07±0.14 | 16.90 | 23.47 | [] |
| balloon | deferred | 19803±267 | 3.11±0.16 | 17.60 | 22.80 | [] |
| balloon2 | prune | 33524±2631 | 5.22±0.15 | 23.03 | 21.45 | [] |
| balloon2 | deferred | 30519±4236 | 5.84±0.16 | 23.03 | 21.42 | [] |
| mv_no_box | prune | 40806±4228 | 2.58±0.05 | 14.95 | 26.34 | [] |
| mv_no_box | deferred | 31561±2529 | 2.87±0.27 | 15.66 | 26.06 | [] |
| mv_no_box2 | prune | 65343±7680 | 4.68±0.02 | 16.98 | 26.50 | [] |
| mv_no_box2 | deferred | 50655±16848 | 5.61±0.14 | 17.26 | 26.24 | [] |
| pt1 | prune | 55596±4072 | 10.97±0.03 | 20.89 | 25.74 | [] |
| pt1 | deferred | 44154±1313 | 11.51±2.18 | 21.77 | 25.24 | [] |
| pt2 | prune | 69609±16219 | 10.35±0.56 | 22.03 | 24.01 | [] |
| pt2 | deferred | 44196±1961 | 16.80±4.44 | 25.17 | 23.45 | [] |

## H-D ratio G_def/G_prune (paired, same-seq) + branch
| seq | G_prune | G_deferred | ratio | own_sd_large | band (2x) | branch | ATE_def/prune | ATE no-harm |
|---|---|---|---|---|---|---|---|---|
| balloon | 39784 | 19803 | 0.498 | 5511 | 0.277 | judgable (<1, deferred better) | 3.11/3.07 | ok |
| balloon2 | 33524 | 30519 | 0.910 | 4236 | 0.253 | INDETERMINATE | 5.84/5.22 | ok |
| mv_no_box | 40806 | 31561 | 0.773 | 4228 | 0.207 | judgable (<1, deferred better) | 2.87/2.58 | ok |
| mv_no_box2 | 65343 | 50655 | 0.775 | 16848 | 0.516 | INDETERMINATE | 5.61/4.68 | ok |
| pt1 | 55596 | 44154 | 0.794 | 4072 | 0.147 | judgable (<1, deferred better) | 11.51/10.97 | ok |
| pt2 | 69609 | 44196 | 0.635 | 16219 | 0.466 | INDETERMINATE | 16.80/10.35 | FLAG (>50% worse) |

## H-D cross-seq rank correlation (informational; the prereg makes the call)
(match this table's seq order by ratio against results/evidence/hd_coverage_anchor.md's coverage rank)
  balloon: ratio=0.498
  pt2: ratio=0.635
  mv_no_box: ratio=0.773
  mv_no_box2: ratio=0.775
  pt1: ratio=0.794
  balloon2: ratio=0.910

## Decision verdicts will be read from the H-D prereg three-branch rule. Catastrophic seeds are flagged in the main table, never dropped.
