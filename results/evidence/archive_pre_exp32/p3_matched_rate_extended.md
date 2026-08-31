# Matched-rate deletion — extended controls (codex Round 2, 18 maps 3-seed aggregate)

18 P2-T prune maps × {low/high/random} at rates 5% & 10%; random=10 draws. Values = 3-seed mean.
low = lowest-opacity deletion (our claim), high = highest-opacity, random = random subset at matched count.
GTdPSNR = PSNR(after)−PSNR(orig). bvSSIM = compressed-vs-original-render SSIM. maxPxErr = max per-pixel error.

| seq | rate | low GTdPSNR | high GTdPSNR | random GTdPSNR (3seed mean±sd) | random [min,max] | bvSSIM low/high | maxPxErr low/high |
|---|---|---|---|---|---|---|---|
| balloon | 5% | +0.0000 | -4.22 | -0.48±0.32 | [-1.97,-0.17] | 1.0000/0.9598 | 0.00000/0.718 |
| balloon | 10% | +0.0000 | -5.05 | -0.90±0.35 | [-1.95,-0.42] | 1.0000/0.9491 | 0.00006/0.768 |
| balloon2 | 5% | +0.0000 | -2.07 | -0.20±0.09 | [-0.50,-0.06] | 1.0000/0.9713 | 0.00000/0.681 |
| balloon2 | 10% | -0.0001 | -3.65 | -0.47±0.14 | [-0.75,-0.18] | 1.0000/0.9440 | 0.00927/0.823 |
| mv_no_box | 5% | +0.0000 | -1.61 | -0.42±0.13 | [-0.88,-0.22] | 1.0000/0.9937 | 0.00000/0.475 |
| mv_no_box | 10% | -0.0002 | -4.34 | -0.87±0.20 | [-1.50,-0.57] | 1.0000/0.9764 | 0.01438/0.663 |
| mv_no_box2 | 5% | +0.0000 | -2.98 | -0.53±0.21 | [-1.19,-0.27] | 1.0000/0.9869 | 0.00000/0.542 |
| mv_no_box2 | 10% | -0.0007 | -4.30 | -1.04±0.38 | [-2.02,-0.60] | 1.0000/0.9767 | 0.00390/0.629 |
| pt1 | 5% | +0.0000 | -1.82 | -0.45±0.12 | [-0.72,-0.26] | 1.0000/0.9884 | 0.00000/0.692 |
| pt1 | 10% | +0.0000 | -3.96 | -0.87±0.16 | [-1.35,-0.65] | 1.0000/0.9721 | 0.00506/0.771 |
| pt2 | 5% | +0.0000 | -2.84 | -0.56±0.19 | [-1.04,-0.21] | 1.0000/0.9823 | 0.00000/0.715 |
| pt2 | 10% | +0.0000 | -4.38 | -1.00±0.24 | [-1.43,-0.55] | 1.0000/0.9690 | 0.00156/0.792 |

**Aggregate (all 36 rate-map cells):**
- low GTdPSNR: mean -0.00008, max |.| 0.00210
- high GTdPSNR: mean -3.43, min -5.68 (all <0)
- random GTdPSNR: mean -0.65±0.27 (all <0)
