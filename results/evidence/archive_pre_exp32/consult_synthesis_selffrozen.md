# Synthesis: codex vs hermes on self-frozen pose de-confound (2026-08-02)

> Two independent reviews of the self-frozen design. Both read the same brief. They DISAGREE on B vs C primary.
> Full text: `consult_codex_selffrozen.md`, `consult_hermes_selffrozen.md`.

## The disagreement

| | codex | hermes |
|---|---|---|
| Primary | **B (GT-pose)** — exogenous, neutral, causally cleanest | **C (prune-trajectory)** — preserves regime |
| Sensitivity | C (prune-conditioned) | B (regime-extremity check) |
| Rationale | B's GT is not selected by either arm; C's trajectory is post-treatment (prune-conditioned, selection bias) | B's perfect pose = regime change (PSNR 15 vs 23 measured in R2-P01-E2) that may SUPPRESS the pose-map-feedback effect being tested; C keeps the realistic 11cm regime |
| If only one pair | B | C |

## Where they AGREE (high confidence)

1. **The experiment IS worth running** — as a limitation-SHARPENER, not an H-D rescue. Cannot upgrade H-D (n≤2, map-level, seen data, ceiling = weaken/unchanged). A MAP-EFFECT result lets you write "tracker-orthogonal mapping channel exists; cannot attribute to mask-coverage vs tracking-difficulty, remains stated limitation" — strictly better than "stated-untested."
2. **Sequences: pt1 + balloon2** (NOT pt1 alone, NOT balloon). pt1 = hard-tracking+moderate-cov; balloon2 = easy-tracking+highest-cov → the 2×2 contrast codex wanted. pt2 = later (high variance weakens clarity).
3. **C de-confounds tracking-difficulty.** Both arms share the injected trajectory → tracking is fixed. The trajectory-bias (post-treatment, prune-conditioned) is real but **second-order** (hermes measured 7cm divergence on 11cm base) vs the **first-order** confound being killed (10-14cm ATE differences). Net win.
4. **ATE = construction canary** (both arms share injected pose → ATE identical). Observables = map-level: R_G^F = G_def^F/G_prune^F + vac_depth/vac_psnr (guardrail, not outcome).
5. **Freeze keyframe indices if feasible** (frozen pose ≠ frozen DynamicKeyframe decisions; differing KF schedules = ambiguity trigger).
6. **Paired-seed log(G_def/G_prune)** with prereg equivalence region, NOT 2×own_sd (codex amendment).
7. **Apparatus verified**: trj_full_final.json exists for pt1 (580fr) + balloon2 (469fr), schema matches oracle_pose.py, trj_gt = dataset GT by construction → gate passes at ~0 residual. Oracle.gt_pose supported (R2-P02 alpha used it). No new trajectory acquisition.
8. **No good (D)** — moderate-quality neutral trajectory. External reintroduces the provenance problem that killed RGD; averaging/deferred's-own have worse problems.

## Resolving the B-vs-C disagreement (my read)

hermes's regime-preservation argument is stronger for THIS question, because:
- The effect being tested (does lifecycle perturb the map independently of tracking) is **itself regime-dependent** (R2-P01-E2 proved pose-map feedback exists).
- B (perfect pose) risks SUPPRESSING the very pose-map-feedback channel being tested → a NO-MAP-EFFECT under B would be ambiguous (could be "tracking-coupled" OR "regime-suppressed").
- C (11cm realistic pose) keeps the channel live; its selection bias is bounded (7cm, sign-unpredictable) and labelable.

**BUT codex's point holds**: C's estimand is "lifecycle effect when replaying a prune-generated trajectory" — prune-conditioned, cannot claim "tracking difficulty removed generally."

**Decision: run BOTH, C carries the prereg branch decision, B as regime-extremity sensitivity.** This is exactly hermes's recommendation, and codex explicitly said "a strong result is concordance across B and C; disagreement is informative." Both reviews converge on "run both if affordable" — and it IS affordable (8 runs ~4h: pt1+balloon2 × {B,C} × 2 arms × seed0; expand to 3 seed only if MAP-EFFECT/REVERSED).

Actually — 8 runs is the seed-0 screening. Full would be pt1+balloon2 × {B,C} × 2 arms × 3 seeds = 24 runs ~12h. Start seed-0 (8 runs ~4h), expand only if discriminating.

## Self-frozen prereg (to write, before any GPU)

- **Title**: "self-frozen pose de-confound (prune-conditioned), variant C primary + B sensitivity"
- **Observable**: R_G^F = G_def^F/G_prune^F (paired-seed log-ratio, prereg equivalence region around 0); vac_depth/vac_psnr guardrail (inherited 1.56cm/0.28dB); ATE = canary.
- **Branches** (codex-corrected): CONCORDANT-MAP-EFFECT (ratio<1 OR fidelity effect) / NO-DETECTABLE (ratio + both fidelity in equivalence) / REVERSED (ratio>1) / MIXED-TRADE (compactness & fidelity opposing). Don't require fidelity diff for G-count effect.
- **Selection-bias disclosure** (hermes): injected trajectory is prune's self-tracked output, post-treatment, bounded 7cm divergence, sign-unpredictable.
- **Ceiling**: weaken/unchanged H-D INDETERMINATE only; n=2, map-level, seen data.
- **Sequences**: pt1 + balloon2.
- **KF indices**: freeze if feasible, else ambiguity trigger.

## GO/KILL

This is a new experiment (not in any frozen contract). Per README §2 it needs frozen config + experiment.yaml + prereg committed before GPU. Fits the user's "补实验也可以" autonomy grant — it's a labeled mechanistic control on existing data, not a new headline claim. **Proceed: build apparatus (C+B configs + contract + prereg), run seed-0 (8 runs ~4h), expand to 3 seed only if MAP-EFFECT/REVERSED.**
