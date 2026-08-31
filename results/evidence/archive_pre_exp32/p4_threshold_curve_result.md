# Direction B result — threshold-continuum removal curve, 18 maps (2026-08-09)

> 来源：`scripts/p4_threshold_curve_batch.py`，全 18 P2-T prune maps，离线 interval-5 重渲。
> 目的（candidate-pool #3）：把 "0.01 是最粗安全格"从单点 hack 变成完整结构特征曲线。
> 原始逐图数据：`p4_threshold_curve.md`。

## Aggregate (18 maps, per-threshold mean / min / max)

| op 阈值 | mean rm% | mean dPSNR | min dPSNR | max dPSNR |
|---|---:|---:|---:|---:|
| 0.001 | 0.00% | −0.00000 | −0.00000 | −0.00000 |
| 0.002 | 0.11% | −0.00000 | −0.00000 | −0.00000 |
| 0.005 | 10.70% | −0.00000 | −0.00000 | −0.00000 |
| **0.010** | **11.88%** | **−0.00017** | **−0.00250** | **+0.00010** |
| 0.020 | 13.36% | −0.00063 | −0.00260 | +0.00010 |
| 0.030 | 14.61% | −0.00276 | −0.00820 | −0.00030 |
| 0.050 | 16.82% | −0.01671 | −0.08670 | −0.00020 |
| 0.080 | 19.64% | −0.07511 | −0.24990 | −0.00740 |
| 0.100 | 21.28% | −0.16840 | −0.56250 | −0.02020 |

## Key structure (all 18 maps, consistent)

1. **The cohort is sharply banded near zero-opacity.** Removal is ≈0 below op=0.002
   (0.1% mean) then jumps to **10.7% at op=0.005** — i.e. almost the entire removable cohort
   sits in the tiny opacity band (0.002, 0.005). There is not a gradual ramp; the soft-selected
   population is clustered just below the 0.01 threshold. This is a concrete structural signature
   ("refinement drives opacity toward essentially zero, not just below a cutoff").
2. **Near-zero cost is monotone & threshold-localized.** dPSNR stays ≈0 (mean ≤ −0.00017,
   even the worst single map −0.0025 dB) through op=0.01. The bound degrades smoothly thereafter:
   −0.0028 at 0.03, −0.017 at 0.05, −0.075 at 0.08, −0.168 at 0.10. So 0.01 sits at the **knee**
   of the dPSNR-vs-threshold curve — the coarsest threshold still in the numerically-zero band.
3. **17/18 maps keep |dPSNR| ≤ 0.0003 dB at op=0.01**; the single outlier (−0.0025 dB,
   mv_no_box2 seed0) matches the p4_op001_full18 finding.

## Why this is a characterization contribution, not a hack

- Replaces "0.01 gives ~0 dB" (one operating point) with **a reproducible structural curve**
  common to all 18 maps: cohort sharply banded near zero → cost monotone in threshold → 0.01 is
  the coarsest safe rung before the knee.
- Consistent with the freeze counterfactual mechanism: refinement does not merely nudge opacity
  across a cutoff, it **drives a clustered sub-population to ~0** (band 0.002–0.005 holds ~90% of
  the removable cohort), so deleting that band costs nothing.

## Caveats
- Offline interval-5 rerender at stored poses (same instrument as p4_op001_full18 / step5b).
- rm% at op=0.001 / 0.002 ≈0 means the curve is sampling near the hard floor; cannot resolve below 0.002.
- The monotone trend is descriptive; no seed-level null is claimed (single operating-point dPSNR per map).
