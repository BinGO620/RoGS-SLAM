# R2-P02 pre-flight post-hoc note (2026-07-28 evening)

**Context:** Post-hoc rescoring of the 8 R2-P01-E2 balloon runs (prune/deferred × self/injected × seed 0/1) completed with all runs band-faithful (max |Δpsnr| ≤ 0.0005 dB). The rescoring computed the calibrated ghost-excess metrics (`ghost_excess_psnr_db` / `freshvac_ghost_excess_psnr_db` / `ghost_excess_depth_l1_cm`) and the per-regime per-arm seed spread.

## Key findings

### 1. The noise DOES collapse under fixed poses (Q1, the pre-flight's raison d'être)

Injected sd / self sd ratio, per arm, on the two calibrated-usable contrasts (r2_p02_e2.md §8.1/8.2):

| metric | prune ratio | deferred ratio |
|---|---|---|
| `ghost_excess_psnr_db` (unbounded support, 9.9× deficit/noise) | **0.35×** | **0.10×** |
| `freshvac_ghost_excess_psnr_db` (30-frame recency window, 6.6×) | **0.77×** | **0.04×** |

**Both PSNR contrasts collapse under fixed poses,** especially the freshvac one (deferred 0.2266 → 0.0088 sd = 96% collapse). The depth contrasts do NOT collapse; both arms' `ghost_excess_depth_l1_cm` sd actually *grows* under injection (prune 1.08 → 2.14; deferred 0.19 → 2.49), consistent with §8.2's verdict that depth-L1 is unusable for this metric.

### 2. Injected-regime prune-vs-deferred contrast is LARGE and WRONG-SIGN on the calibrated headline

Under the RGD-injected strong trajectory (ATE 2.06 cm, both arms identical):

| metric | prune | deferred | diff | pooled sd | \|d\|/sd | winner |
|---|---|---|---|---|---|---|
| `ghost_excess_psnr_db` | −1.19 | −2.92 | **−1.73** | 0.26 | **6.64** | **prune** |
| `freshvac_ghost_excess_psnr_db` | −2.47 | −2.33 | +0.15 | 0.03 | 5.01 | deferred |

**Prune beats deferred by 1.73 dB (6.6σ) on the unbounded calibrated contrast** — the opposite of the pre-registration's hypothesis direction. The self-tracked regime flips sign (prune −2.67, deferred −3.45, diff −0.78), but at 0.65σ that is noise.

This is the E2 null-replicate calibration's missing half: **on self-tracked balloon the two algorithms were buried in 30 cm of pose noise and the ordering looked like noise-driven coin flips; under a frozen 2 cm trajectory the ordering is stable and large, and it is prune-wins.**

### 3. The nonvacated PSNR (the paired contrast's denominator) moves MORE than the vacated PSNR does

Self-tracked: prune 23.67, deferred 24.40 (deferred +0.73 dB). Injected: prune 15.78, deferred 17.50 (deferred **+1.71 dB**, 6.1σ). The calibrated ghost metric (`ghost_excess = vacated − nonvacated`) is *supposed* to cancel global pose drift because both terms are rendered from the same trajectory. But the nonvacated support is only 16% of the image (38809 px vs 203284 vacated, r2_p02_e2.md §8.2), and under injection that 16% moves *more* than the 84% does:

- vacated PSNR: prune 14.59, deferred 14.57 (−0.02 dB, neutral)
- nonvacated PSNR: prune 15.78, deferred 17.50 (**+1.71 dB**, 6.1σ)

So the injected `ghost_excess_psnr` "winner" (prune) is an artifact of prune being *worse* in the 16% periphery, which drags its contrast down. The metric successfully cancelled *pose* noise but it introduced a *spatial* confound.

### 4. Implication for the pre-flight

The original Q1 was: "does freezing the trajectory collapse enough noise that the instrument can resolve the CHECKPOINT-1 contrast (D vs B, both deferred-based)?"

**Answer: YES for the PSNR metrics (0.10× / 0.04× collapse on deferred), BUT the injected-regime prune-vs-deferred ordering is large, stable, wrong-sign, and contaminated by a spatial confound the paired contrast does not remove.**

The pre-flight is still valid as a **mechanism diagnostic** (Q2 carve arming, Q3 activity gate), and it will correctly answer "does D beat B" under fixed poses — but it will NOT validate the map-admission hypothesis, because the hypothesis claimed "deferred beats prune" and the pose-controlled measurement says the opposite.

### 5. Decision

The pre-flight remains the correct next step for **mechanism validation** (did the fix work, does carve arm, does the activity gate pass), but it is no longer a measurement shortcut to CHECKPOINT-1's GO gate. If D beats B under fixed poses, that validates the mechanism fired and moved the needle; it does NOT validate the core hypothesis until reconciled with the prune-wins finding.

Pre-registration §9 reserves GO/KILL for the user. The numbers above are recorded facts; the call is yours.

## Appendix: full contrast table (injected regime, RGD pose)

| metric | prune | deferred | diff (defer−prune) | pooled sd | \|d\|/sd | winner |
|---|---|---|---|---|---|---|
| `ghost_excess_psnr_db` ↑ | −1.19 | −2.92 | **−1.73** | 0.26 | **6.64** | prune |
| `freshvac_ghost_excess_psnr_db` ↑ | −2.47 | −2.33 | +0.15 | 0.03 | 5.01 | deferred |
| `vacated_depth_l1_pen_cm` ↓ | 36.92 | 38.60 | +1.68 | 1.90 | 0.88 | prune |
| `ghost_excess_depth_l1_cm` ↓ | +2.87 | −1.16 | −4.03 | 2.32 | 1.74 | deferred |
| `freshvac_ghost_excess_depth_l1_cm` ↓ | −0.23 | −0.89 | −0.66 | 0.94 | 0.70 | deferred |
| `nonvacated_psnr` ↑ | 15.78 | 17.50 | **+1.71** | 0.28 | **6.06** | deferred |

Sign convention: ↑ = higher better, ↓ = lower better. "winner" = the arm whose value is in the favored direction.

The two depth contrasts show deferred-better (consistent with the pre-reg hypothesis), but §8.2 already measured both as unusable (deficit/noise 0.1× and 0.2×). The one usable unbounded contrast shows prune-better at 6.6σ.
