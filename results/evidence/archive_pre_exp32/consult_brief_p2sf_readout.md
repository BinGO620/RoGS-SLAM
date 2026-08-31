# P2-SF seed-0 readout — shared brief for external review (identical packet to codex + hermes)

Date: 2026-08-02. Repo: MonoGS-Ours, branch `dynamic-slam-dev`. Venue deadline MMM 2027, 08-16 AOE;
narrative gate 08-04; writing hard start 08-06. **GO/KILL + narrative belong to the human user.**

## 1. What this experiment is

Prior main table (P2-T, 36 runs, closed) compared two candidate-lifecycle arms of one SLAM backbone:
- **prune** = insert-then-prune (faithful twin of published competitors)
- **deferred** = provisional-candidate admission (our mechanism)

Headline map-level observable is **compactness** `R_G = G_deferred / G_prune` (`refined_num_gaussians`).
Self-tracked (both arms doing their own tracking), 3 seeds, 6 sequences: the direction was
**not universal** — balloon 0.596/0.431, balloon2 flipped 1.155→0.898, pt2 flipped 1.069 vs 0.467.
A hypothesis "H-D" (choose lifecycle by semantic-mask coverage) landed **INDETERMINATE**.

An external reviewer (hermes) then raised the sharpest open objection:
> **mask-coverage is collinear with tracking-difficulty.** The high-coverage sequences (pt1, pt2) are
> also the hard-tracking ones. So "lifecycle changes the map" and "lifecycle interacts with tracking
> quality" predict the same pattern across n=6 sequences. The mechanism story is unidentified.

**P2-SF is the de-confounding control**: freeze pose identically for both arms, so any surviving
map-level difference cannot come from the arms tracking differently.

A first attempt (freeze onto a *borrowed* RGD-SLAM trajectory) was **abandoned**: 1.11 cm anchor
residual against a 1.0 cm gate, files had no timestamps, 580-vs-583 frames ⇒ frame correspondence
unverifiable. P2-SF instead freezes onto **our own prune arm's** self-tracked trajectory, whose
`trj_gt` is the dataset GT, so correspondence is verifiable by construction.

## 2. Pre-registered constraints (frozen BEFORE any run; `p2sf_selffrozen_prereg.md`)

- **Two variants.** **C (PRIMARY)** = both arms replay the prune arm's own self-tracked trajectory
  (symmetric; only lifecycle differs; keeps the real ~11 cm regime so pose-map feedback survives).
  **B (SENSITIVITY)** = both arms use dataset GT pose (causally cleanest, but GT = 0 cm = perfect
  tracking = regime shift that may *suppress* the very channel under test).
  Adjudication was C-primary / B-sensitivity, over codex's preference for B-primary.
- **PRIMARY observable** `R_G^F = G_def^F/G_prune^F`, paired-seed log-ratio.
- **Guardrails INHERITED, not re-fit**: `static_vacated_depth_l1_pen_cm` ≤ **1.56 cm**,
  `static_vacated_psnr` ≤ **0.28 dB** (imported from the frozen R2-P03 sweep readout).
- **ATE = canary, NOT an outcome** (arms share the injected trajectory ⇒ equal by construction).
- **Four branches**: CONCORDANT MAP-EFFECT / NO-DETECTABLE / REVERSED / MIXED-TRADE.
  G-count alone can constitute a map effect; a fidelity difference is *not* required.
- **§4.2 single seed = SCREENING.** No branch may be called from seed 0.
- **§4.8 ambiguity trigger**: frozen pose does NOT freeze keyframe selection. If the arms end up on
  different keyframe schedules, `R_G^F` measures total lifecycle *mapping-policy* effect, not clean
  admission efficiency.
- **§4.4 CEILING (hard)**: this control may only **weaken or leave unchanged** the H-D INDETERMINATE
  verdict. It can **never upgrade** it. n=2 sequences, map-level only, previously-seen data.
- Estimand for C is **prune-conditioned / post-treatment**: "lifecycle effect when replaying a
  prune-generated trajectory."

## 3. Apparatus facts established during the run

- **Injection gate PASSES exactly.** Variant-C prune replay reproduces its source P2-T run's
  full-trajectory ATE to 4 dp: pt1 11.0087 = 11.0087, balloon2 5.1265 = 5.1265. This is precisely
  the gate the abandoned RGD route could never clear.
- **Variant B verified**: ATE 0.0, std 0.0, RPE 0.0, path-length ratio exactly 100.0.
- **Keyframe budget shifts under exact-pose replay**: pt1 116→76, balloon2 94→60 (≈ −35%). Freezing
  pose does not freeze keyframe selection; map state feeds back into it. So variant C measures the
  contrast at roughly two-thirds of the self-tracked mapping budget.
- **Runner defect (bookkeeping only, no run affected).** `r2_p2_sf.py::_extract` hand-rolled metric
  extraction instead of importing the canonical `parse_run`, and is wrong four ways (globs a
  nonexistent `tables` path; takes the first CSV row instead of the `mask_type=="static"` row; wrong
  column `static_vacated_psnr_db`; wrong keyframe source). Every jsonl record therefore carries
  `exit=0` and no metrics. The runner was deliberately **not** modified mid-campaign; a separate
  readout re-derives everything from run dirs via the canonical importers. GPU work fully recovered.
- **Equivalence band pinned pre-data** (prereg §3 specified the derivation but left the constant
  open). Computed literally from its stated source — pooled within-campaign sd of paired
  log(G_def/G_prune) across three prior frozen-pose campaigns (SWEEP 0.0382, DECOMP 0.0845,
  MASKRATE 0.0572) = **0.0629 (6.29%)** ⇒ ±1sd ratio **[0.9390, 1.0649]**. k=1 is the inherited house
  convention (both fidelity margins are themselves 1× null sd). Written when 1/8 runs were done and
  no deferred arm existed, so `R_G^F` was not yet computable. Caveat: the band comes from a
  *different* regime (rtoff backbone, balloon, RGD pose) — a noise scale, not a null for this setup.

## 4. THE DATA (seed 0, 8/8 runs exit 0, ~16 min/run)

All four contrasts, `R_G^F = G_def/G_prune`. Guardrail signs: **positive = deferred worse**.

| variant | seq | G_prune | G_def | **R_G^F** | per-KF ratio* | vac_depth Δ (≤1.56) | vac_psnr Δ (≤0.28) | KF p/d | ATE p/d |
|---|---|---|---|---|---|---|---|---|---|
| **C** primary | pt1 | 56915 | 20592 | **0.3618** | 0.4230 | **+2.423 BREACH** | +0.083 ok | 76/65 | 11.0087 / 11.0087 |
| **C** primary | balloon2 | 24381 | 13833 | **0.5674** | 0.5972 | +0.188 ok | +0.185 ok | 60/57 | 5.1265 / 5.1265 |
| **B** sens. | pt1 | 13258 | 9766 | **0.7366** | 0.8024 | −1.317 ok | −0.135 ok | 61/56 | 0.0 / 0.0 |
| **B** sens. | balloon2 | 26427 | 7440 | **0.2815** | 0.2920 | +0.063 ok | +0.252 ok | 56/54 | 0.0 / 0.0 |

\* per-KF ratio = (G_def/KF_def)/(G_prune/KF_prune). **DESCRIPTIVE, post-hoc, NOT pre-registered** —
added only to bound the §4.8 confound. KF gap explains 10% / 7% / 25% / 1% of the distance from 1.

Self-tracked comparators (3-seed main table): pt1 **R_G = 0.794**; balloon2 **R_G = 0.910
(INDETERMINATE)**. Sequence properties: pt1 = hard-tracking, mask coverage 29.9%;
balloon2 = easy-tracking, mask coverage 59.4%.

Candidate ledger (`promoted` / `commit_queued`):
- C-pt1 prune 203 / — ; C-pt1 deferred 171 / 168
- C-balloon2 prune 163 / — ; C-balloon2 deferred 155 / 153
- B-pt1 prune 53 / — ; B-pt1 deferred 43 / 30
- B-balloon2 prune 71 / — ; B-balloon2 deferred 54 / 41

Salient structure we can see but have deliberately not interpreted:
1. **All 4 cells are < 1 and outside the band**; all 4 agree in sign with self-tracked.
2. Under frozen pose the contrast **strengthens** rather than collapsing toward 1
   (pt1 0.794→0.362 under C; balloon2 0.910→0.567 under C, →0.282 under B).
3. **The variant ordering flips between sequences.** C says pt1 is the more extreme sequence
   (0.362 < 0.567); B says balloon2 is (0.282 < 0.737). Rank reversal across variants.
4. **Absolute map sizes differ hugely between variants on pt1**: C-prune 56915 vs B-prune 13258
   (4.3×), while balloon2 is comparable (24381 vs 26427).
5. B arms show far less lifecycle activity (`promoted` 43–71 vs 155–203; `commit_queued` 30/41 vs
   168/153).
6. Only one guardrail breach in 8 comparisons: C-pt1 depth +2.423. B-balloon2 psnr +0.252 is near
   the 0.28 margin.
7. §4.8 ambiguity trigger fires on **all four** pairs; deferred always has fewer keyframes.

## 5. Questions for review (please answer each explicitly, and say when you disagree with the framing)

1. **Is the collinearity blind spot actually addressed?** Under frozen pose both sequences move
   *away* from 1, not toward it. A pure "compactness is a tracking-difficulty artifact" account
   predicts attenuation. What does the observed amplification license, and what does it NOT license?
   Is there an alternative account that also predicts amplification?
2. **Does the §4.8 trigger firing on 4/4 pairs invalidate `R_G^F` as an admission-efficiency
   measure?** Is the per-KF normalization a defensible descriptive bound, or is it itself a
   post-hoc analytic choice we should not lean on? Is there a better pre-committable way to handle
   unequal keyframe schedules?
3. **Does the ≈35% keyframe-budget drop under exact-pose replay sever the bridge back to the
   self-tracked main table?** If C measures at ⅔ the mapping budget, in what sense is it a control
   *for* the self-tracked result rather than a different experiment?
4. **Observation 3, the rank reversal between variants** — C and B disagree about which sequence
   shows the bigger effect, and pt1's absolute map size differs 4.3× between them. Is this the
   "disagreement is informative / partial mediation" case codex anticipated, or is it evidence that
   one of the two variants is measuring something else entirely?
5. **How should the pt1 depth breach (+2.423 vs 1.56) be written?** C-pt1 is trade-shaped
   (compactness benefit + fidelity harm) while C-balloon2 is clean-benefit-shaped. Two sequences,
   two shapes, n=1 seed each.
6. **Is `--phase full` (seeds 1,2 = 16 runs, ≈4.3 h on a 2060) worth spending?** If the keyframe
   confound undermines the estimand, more seeds will not repair it. Rank: fix apparatus first
   (pin keyframe schedules?) vs add seeds vs stop here and write it as a limitation.
7. **Ceiling audit.** Prereg §4.4 caps this at weaken-or-leave-unchanged for H-D. Given data this
   directionally consistent, is any part of our framing above sliding toward an upgrade? Name any
   sentence that should be cut.

Please be adversarial. We would rather kill a result now than defend it in review.
