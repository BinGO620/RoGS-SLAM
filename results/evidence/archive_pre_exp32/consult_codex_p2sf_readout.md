# codex 审查 — P2-SF seed-0 readout（2026-08-02）

> 输入 = `results/evidence/consult_brief_p2sf_readout.md`（与 hermes 同一份 packet）。
> 模型 = codex MCP 默认（gpt-5.5/high）。sandbox = read-only，未改任何文件。
> thread `019fc0fb-4f84-7403-b687-196fdce5b0cd`。
> **本文件为原样记录**，不是我方结论；综合见 `consult_synthesis_p2sf_readout.md`。

---

## 1. Is the collinearity blind spot addressed?

Only partially, and less than the brief suggests.

The frozen trajectories rule out one narrow explanation: the observed arm difference cannot be caused by the prune and deferred arms following different pose trajectories within that frozen-pose pair. The seed-0 pattern therefore warrants this limited statement:

> Lifecycle choice remains associated with map construction when the two arms receive identical poses.

It does not establish that:

- mask coverage explains the effect;
- tracking difficulty does not moderate the effect;
- the effect is admission efficiency rather than broader mapping-policy feedback;
- the frozen-pose effect explains the self-tracked effect;
- any preregistered branch has been reached.

I disagree with the premise that a tracking-artifact account necessarily predicts attenuation toward 1. That prediction assumes freezing poses changes nothing else relevant. Here it reduced the keyframe budget by about 35%, produced arm-specific keyframe schedules, radically changed pt1 map size, and altered lifecycle activity. Any of these can amplify the ratio through nonlinear map growth.

Plausible alternative amplification accounts include:

- deferred admission responding differently to a sparse mapping schedule;
- endogenous keyframe selection amplifying earlier map-state differences;
- Gaussian growth being nonlinear in keyframe timing or content;
- replayed poses being inconsistent with the map state that would normally co-evolve with them;
- denominator effects, especially C-pt1's unusually large prune map;
- pose-regime-by-lifecycle interaction rather than a tracker-orthogonal admission effect.

I expect to agree with hermes that the original cross-sequence coverage/tracking collinearity remains unresolved. If hermes treats identical poses as resolving it, I disagree: identical within-pair pose input eliminates differential tracking output, but it does not separate mask coverage from sequence difficulty as causal moderators. Settling that requires more sequences that cross coverage and difficulty independently, or a factorial manipulation of pose-error regime and coverage under an identical mapping schedule.

## 2. Does the keyframe trigger invalidate admission efficiency?

Yes. It invalidates `R_G^F` as a clean admission-efficiency measure. It does not invalidate it as a total frozen-pose lifecycle/mapping-policy contrast.

Keyframe selection is downstream of map state and differs in all four pairs. Consequently, the arms differ in both lifecycle behavior and mapping exposure. Fewer final Gaussians can arise from fewer keyframes, different keyframe content or timing, admission behavior, or their interactions.

The per-KF ratio is acceptable only as explicitly post-hoc description. It is not a defensible bound:

- Gaussian accumulation need not be linear in keyframe count.
- Keyframes are not exchangeable units of exposure.
- Their timing and image content differ.
- The denominator is itself post-treatment.
- "KF gap explains X%" implies a decomposition that the normalization does not identify.

That "explains 10% / 7% / 25% / 1%" wording should be removed.

A better pre-committed design would give both arms exactly the same keyframe indices, frame content, ordering, mapping-update count, and stopping point. Report `G` only at matched keyframe budgets. Prefer an arm-independent schedule defined from frame indices or GT motion; replaying the prune schedule is possible but remains explicitly prune-conditioned.

## 3. Does the 35% budget drop sever the bridge to the main table?

It substantially weakens the bridge.

C reproduces the source trajectory ATE, but it does not reproduce the source mapping process: pt1 changes from 116 to 76 keyframes and balloon2 from 94 to 60. Exact ATE replay verifies pose injection, not experimental equivalence. Calling this a control "for" the self-tracked compactness result is therefore too strong.

The defensible relationship is narrower:

> Under a lower-budget, frozen replay of the prune-generated trajectory, seed 0 shows a same-direction lifecycle-associated map-size difference.

That establishes neither persistence at the original budget nor mediation of the self-tracked result. It is a related intervention in a different mapping regime. The frozen result and main table can be compared qualitatively as a sensitivity analysis, but their ratio changes should not be described as strengthening or attenuating the same estimand.

## 4. What does the B/C rank reversal mean?

It is evidence of regime dependence and non-transportability, not evidence of partial mediation.

C and B do not differ by one clean mediator:

- C uses a prune-conditioned, imperfect trajectory.
- B uses an exogenous perfect trajectory.
- Their keyframe schedules differ.
- Their lifecycle activity differs substantially.
- C-pt1 and B-pt1 prune maps differ by 4.3×.

Thus, C and B estimate different controlled-regime contrasts. The rank reversal says the lifecycle contrast is highly sensitive to the pose/mapping regime. It does not identify how much of the self-tracked effect is mediated by tracking.

I disagree with the earlier "disagreement is informative / partial mediation" framing if "partial mediation" is intended as a causal conclusion. The disagreement is informative only as an interaction warning. A mediation interpretation would require matched schedules, repeated seeds, and a design that varies pose error while holding mapping exposure fixed. Ideally, several pre-specified pose-error levels would be crossed with lifecycle under an identical keyframe schedule.

## 5. How should the pt1 depth breach be written?

Use neutral screening language:

> In the seed-0 C-pt1 screening pair, deferred used fewer Gaussians (`R_G^F=0.3618`) but had a `+2.423 cm` vacated-region depth difference relative to prune, exceeding the inherited `1.56 cm` margin. This single-seed compactness/fidelity pattern is provisional and does not support a branch assignment. C-balloon2 did not exceed either inherited fidelity margin at seed 0.

Do not call C-pt1 a "benefit," C-balloon2 a "clean benefit," or either cell a trade verdict. Fewer Gaussians are not beneficial if achieved with unacceptable fidelity loss, and one seed cannot establish that the loss is reproducible.

Also cut:

> "Only one guardrail breach in 8 comparisons."

That denominator makes the breach look rarer by counting metric axes rather than experimental pairs. State directly that one of four paired cells breached a guardrail, and that B-balloon2 PSNR was close to its margin.

## 6. Ranked recommendation

1. **Fix the keyframe-schedule confound first.** Pre-register an identical schedule and matched mapping budget for both arms, rerun seed 0 under that apparatus, and expand only if the corrected screen remains discriminative.

2. **Stop and write the current result as a limitation** if schedules cannot be pinned without changing the method being evaluated. The current data can document that pose freezing alone does not freeze mapping policy and therefore fails to isolate admission efficiency.

3. **Spend 4.3 GPU-hours on seeds 1–2 under the current apparatus.** This is the lowest-value option. More seeds would estimate repeatability of a confounded total-policy contrast; they would not repair its interpretation.

I would not authorize `--phase full` as currently configured. The correct next experiment is not merely two more seeds but a corrected matched-schedule campaign. If that correction is infeasible, stopping is methodologically stronger than accumulating precise evidence about an ambiguous estimand.

## 7. Ceiling audit

The current framing does slide toward an upgrade, despite repeating the formal ceiling. Cut or replace these sentences:

> "P2-SF is the de-confounding control: freeze pose identically for both arms, so any surviving map-level difference cannot come from the arms tracking differently."

Replace with: "P2-SF removes differential pose trajectories within each pair, but does not hold keyframe schedules or mapping exposure fixed."

> "Under frozen pose the contrast strengthens rather than collapsing toward 1."

Cut it. It compares a three-seed self-tracked quantity with a single-seed, lower-budget, different-estimand quantity.

> "A pure 'compactness is a tracking-difficulty artifact' account predicts attenuation."

Cut it. That prediction depends on an invariance assumption directly contradicted by the keyframe-budget and map-size changes.

> "All 4 cells are < 1 and outside the band; all 4 agree in sign with self-tracked."

Either cut it or rewrite it as a seed-0 screening observation, explicitly noting that the imported band is not a null distribution for this regime.

> "KF gap explains 10% / 7% / 25% / 1% of the distance from 1."

Cut it. The post-hoc normalization does not identify an explained fraction.

From the preregistration narrative, also do not use:

> "tracking-difficulty collinearity has been partially ruled out."

The experiment removes differential arm trajectories, not the sequence-level collinearity between coverage and difficulty.

The ceiling-compliant conclusion is:

> The seed-0 screen does not falsify the existence of a lifecycle-associated map-size difference under shared pose input. Because keyframe schedules diverged, mapping budgets changed, one fidelity margin was breached, and only one seed was run, the control does not isolate admission efficiency or resolve the coverage/tracking-difficulty explanation. H-D remains INDETERMINATE.

That leaves H-D unchanged; it does not call any P2-SF branch and does not treat ATE as evidence.
