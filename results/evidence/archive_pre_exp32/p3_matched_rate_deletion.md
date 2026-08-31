# Matched-Rate Deletion Controls — terminal-cleanup non-triviality (auto-review Round 1, action 1)

> 2026-08-07. Reviewer (codex) required: is deleting the SAME removal fraction non-trivial?
> If random or high-op is equally harmless, terminal-cleanup is trivial (any deletion is cheap).

## Method
Same instrument as mc_terminal_comp (offline interval-5 render at stored est poses), 3 policies at
matched removal fraction (~10% of final_after_opt map):
- `low_op`: delete lowest sigmoid-opacity gaussians (our terminal claim)
- `high_op`: delete highest-opacity gaussians (stress test)
- `random`: delete random subset (any-deletion control)

## Results (dPSNR = PSNR(after deletion) − PSNR(original))
| seq | low_op dPSNR | high_op dPSNR | random dPSNR |
|---|---|---|---|
| balloon | **−0.0000 dB** | −3.822 dB | −0.788 dB |
| balloon2 | **−0.0125 dB** | −2.272 dB | −0.438 dB |
| mv_no_box | **−0.0012 dB** | −3.812 dB | −2.050 dB |

## Verdict
**NON-TRIVIAL (reviewer's criterion met).** At matched removal fraction ~10%:
- deleting the LOW-opacity cohort costs ≈0 dB (|dPSNR| ≤ 0.013 dB, same as the 12/12 op<0.01 result);
- deleting the SAME NUMBER of HIGH-opacity gaussians costs −2.3 to −3.8 dB (one-to-two orders more);
- deleting a RANDOM subset costs −0.4 to −2.1 dB (an order more than low-op).

→ The low-opacity cohort is SPECIFICALLY safe to delete. Random deletion at the same count hurts
substantially; high-op deletion is catastrophic. This is NOT "any deletion is cheap" — it sustains
the terminal-cleanup headline as a non-trivial measurement, and directly answers the reviewer's
"if random is equally harmless, drop the headline" gate (it is not).

This also strengthens the paper vs. the "obvious heuristic" objection: the +10% OPENS up a clean
"why not random / why not high-op" ablation to pre-empt the reviewer.

## Files
- script: `scripts/p3_matched_rate_deletion.py`
- results inline above (offline renders, no new GPU campaign).

## Artifact savings (reviewer action 2, serialized bytes only)
After op<0.01 deletion (bytes saved = gaussian-count fraction, since PLY is uniform-per-row):
| seq | N | rm | bytes before | bytes after | % saved |
|---|---|---|---|---|---|
| balloon | 27648 | 3118 (11.3%) | 2.21 MB | 1.96 MB | 11.3% |
| balloon2 | 70746 | 4560 (6.4%) | 5.66 MB | 5.30 MB | 6.4% |
| mv_no_box | 38678 | 3157 (8.2%) | 3.09 MB | 2.84 MB | 8.2% |

→ storage/transfer reduction ≈ removal fraction (uniform serialization). NOT refinement/runtime
acceleration (framing per reviewer). Op<0.01 removes 6-11% of serialized bytes at ~0 rendering cost.
