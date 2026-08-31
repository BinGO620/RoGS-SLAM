# WP-C exploratory association (CCF-C 整改执行卡 §4 WP-C)

> **EXPLORATORY — NOT causal** (C5 downgrade: vanilla RPE is a failure OUTPUT shared with ATE,
> so any x1-y correlation is a metric-coupling, never a causal gate). This feeds limitation/discussion,
> does NOT gate anything, does NOT trigger any selector (WP-D already downgraded).

## Data (n=18 seqs)
| seq | y=log(mf/cb) | x1 MonoGS-RPE | family |
|---|---:|---:|---|
| balloon | +1.374 | 2.2314 | bonn_balloon |
| balloon2 | +0.658 | 2.6558 | bonn_balloon |
| crowd | +3.188 | 3.6786 | bonn_crowd |
| crowd2 | +3.307 | 3.6906 | bonn_crowd |
| f1_desk | -0.001 | 0.8158 | tum_static |
| f2_person | -0.042 | 0.5784 | other |
| f2_xyz | -0.094 | 0.2031 | tum_static |
| f3_office | +0.019 | 0.4554 | tum_static |
| f3_st_hf | -0.357 | 1.0962 | tum_sitting |
| f3_st_rpy | -0.426 | 2.4119 | tum_sitting |
| f3_st_xyz | -0.704 | 0.9021 | tum_sitting |
| f3_wk_hf | +2.157 | 3.0135 | tum_walking |
| f3_wk_rpy | +1.586 | 3.0397 | tum_walking |
| f3_wk_xyz | +2.170 | 2.6542 | tum_walking |
| mv_no_box | +0.166 | 2.057 | bonn_mv |
| mv_no_box2 | +0.135 | 1.7866 | bonn_mv |
| pt1 | +1.127 | 3.4882 | bonn_pt |
| pt2 | -0.112 | 2.7625 | bonn_pt |

## Spearman rho
- **y vs x1 (vanilla failure proxy)**: ρ=0.682 over n=18. LOO-family stability: {'bonn_balloon': '0.66', 'bonn_crowd': '0.55', 'bonn_mv': '0.65', 'bonn_pt': '0.77', 'other': '0.70', 'tum_sitting': '0.74', 'tum_static': '0.74', 'tum_walking': '0.56'}
- **y vs x2 (GTMC person-mask coverage, person seqs)**: ρ=0.771 over n=6 (['balloon', 'balloon2', 'mv_no_box', 'mv_no_box2', 'pt1', 'pt2'])
- **per-family y mean**: {'bonn_balloon': '1.02', 'bonn_crowd': '3.25', 'bonn_mv': '0.15', 'bonn_pt': '0.51', 'other': '-0.04', 'tum_sitting': '-0.50', 'tum_static': '-0.03', 'tum_walking': '1.97'}

## Reading (honest)
- Positive y = mask helps. Large positive on **walking / crowd** (y=1.6–3.3), near-zero/negative on
  static & easy person (y≈±0.2), mid (0.7–1.4) on balloon/pt1.
- x1 (vanilla RPE) tracks this (walking/crowd RPE 2.7–3.7 vs static 0.2–0.9) — but this is a failure-output
  coupling, NOT "difficulty caused the gap". **Do not write as intrinsic difficulty.**
- x2 (person-mask coverage) is available only on person/BONN seqs (n=6); any ρ there is single-family,
  under-powered, not bootstrappable at family level per the card.

EXPLORATORY association only; n<=18, single-family seqs cannot bootstrap at family level; x1 is a vanilla-failure proxy NOT intrinsic difficulty; x2 is person-mask coverage (person seqs only)
