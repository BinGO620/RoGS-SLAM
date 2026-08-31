# Codex adversarial review — P2-T + H-D (2026-08-02, read-only sandbox)

> Third-party consult via codex MCP (gpt-5.5/high). Brief = `p2t_brief_for_consult.md`.
> Author stance: maximize POSITIVE contribution, NOT honest-negative framing.

## Q1. Hardest positive contribution

Strongest defensible headline = combination of (a) + (b), with (c) as the concrete motivating case:

> The proposed anti-dynamic backbone remains operationally stable across six Bonn dynamic sequences, while lifecycle selection is sequence-dependent: deferred admission can substantially reduce map size in mover-leakage regimes, but this benefit is not universal.

- Do NOT headline H-D as confirmed. Its own evidence says otherwise: Spearman rho=0.257, p=0.62; only 3 ratios judgable; coverage ranks flip between definitions; high-coverage side has one unstable sample. "Applicability boundary" is defensible as an observed sequence-dependent reversal, NOT as a validated coverage law.
- Backbone: frame as "no catastrophic tracking collapse across the six-sequence stress set," NOT "state-of-the-art tracking."
- Lifecycle: deferred produces a large conditional compactness gain (balloon 0.498×), but direction reverses or becomes indeterminate elsewhere.
- Mechanism: the study demonstrates lifecycle behavior depends on whether dynamic content survives the person mask; proposes a falsifiable stratifier, does NOT claim a deployable gate.
- Avoids "method didn't win" because contribution is not a universal winner; it is a controlled demonstration that lifecycle policy is an important, measurable design axis with a conditional operating regime. Include per-sequence table + paired seed-level plots. A single aggregate compactness number would conceal the reversal.
- **MAJOR QUALIFICATION**: the "combined backbone" bundles FOUR mechanisms. Without ablations, reviewers may call it an engineering package, not a scientific contribution. Present the lifecycle comparison as the causal experiment; treat backbone as stabilized experimental substrate; include module ablations if space permits.

## Q2. Add high-coverage sequences?

**Do NOT add sequences merely to rescue CONFIRMED.** The primary H-D test is already frozen; post-result sample selection = optional stopping. "Already-seen Bonn" is also not independent external validation. A failed extension adds uncertainty without repairing the central inferential weakness.

- Use balloon2 as the high-coverage observation, explicitly state high-coverage regime is n=1 and indeterminate, make that limitation part of the contribution boundary.
- An extension is justified ONLY as a separately labeled exploratory experiment, with sequence list / inclusion rule / seeds / metrics / stopping rule frozen BEFORE inspecting outcomes. If run, choose all available pure-person/high-mask-coverage Bonn seqs matching a predeclared dataset rule, NOT the seq believed most likely >1. "Crowd/synchronous likely >1" would itself be outcome-driven.
- Given deadline + 6-seq table, spend GPU budget on stronger analysis, ablations, reproducibility — NOT a rescue sample.

## Q3. Deferred ATE higher on 6/6

Yes, reviewers will notice the same sign. "In-band = indistinguishable" is too strong, especially since the largest difference is +36.9% and the paired ATE ratio is consistently above one. The 50% rule is a prespecified SAFETY bound, not evidence of equality/non-inferiority.

Upgrade to an explicit tradeoff:

> Deferred lifecycle reduces Gaussian count in leakage-prone scenes, with a bounded but consistently non-improving tracking cost on this benchmark.

- Report paired per-seed ATE differences/ratios, CIs or bootstrap intervals, worst case. Replace "deferred has no ATE harm" with "no sequence exceeded the preregistered 50% degradation bound." Then state plainly deferred is NOT an ATE-improving policy and should be selected for compactness, not tracking accuracy.
- Avoid "negligible" unless you define a practically negligible margin and support it statistically. "Within the declared safety band" is accurate; "indistinguishable" is not.

## Additional blind spots

1. Coverage signal is an offline oracle, confounded with sequence composition (pure-person vs person+object). Cannot support an online hybrid controller.
2. Self-tracking couples lifecycle and trajectory errors; a fixed-trajectory or externally-tracked evaluation would substantially strengthen causal interpretation.
3. Three seeds estimate INSTABILITY, not population uncertainty. Use paired seed plots; avoid sequence-level significance claims.
4. Compactness-ratio drift rule: cross-campaign ratio differences < ~30% are not meaningful. All headline comparisons must remain same-campaign + same-commit.
5. Lower Gaussian count must be accompanied by memory, runtime, insertion/promote/prune counts, fidelity. Otherwise reviewers may read compactness as simply under-building the map.
6. H-D was generated from previously-observed balloon/pt2 behavior. Call it a prospective internal check, NEVER independent validation or hypothesis confirmation.
