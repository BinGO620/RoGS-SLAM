# Synthesis: codex + hermes adversarial review of P2-T / H-D (2026-08-02)

> Two independent third-party consults (codex MCP gpt-5.5/high; hermes strong model).
> Both read the same brief (35/36 P2-T runs, 3-seed means, H-D prereg, coverage anchor).
> Both told: author wants POSITIVE contribution, NOT honest-negative framing.
> Full text: `consult_codex_p2t.md`, `consult_hermes_p2t.md`.

## Consensus (both agree, high confidence)

### Q1 — headline = (b) applicability boundary, with (c) as load-bearing instance, (a) as scaffold
- **Do NOT headline H-D as CONFIRMED.** Spearman ρ=+0.257 p=0.62, only 3/6 judgable, (a)/(b) rank flip ⇒ INDETERMINATE is the honest verdict.
- **Do NOT lead with (a) alone** = "we ported a backbone" = incremental engineering at MMM.
- **Do NOT lead with (c) alone** = balloon is hypothesis-generating seen data (prereg §9), balloon-only claim is post-hoc.
- **Defensible shape**: (b) "lifecycle choice has a measurable, sequence-dependent applicability boundary" + (c) "compactness <1 reproduces on UNSEEN low-coverage seqs (mv_no_box 0.773, pt1 0.798), balloon −50% is largest-magnitude instance" + (a) "no catastrophic collapse across 6-seq stress set" as the floor.
- Reframe: contribution is a **measurement** (boundary exists, stratified by offline oracle), NOT a **victory** (deferred beats prune). MMM accepts measurement contributions if not oversold.
- Make headline a **2×2** (rows = low/high coverage regime; cols = compactness/ATE), not a 1×6 "deferred vs prune" table — the 2×2 reads "here is the boundary", the 1×6 reads "didn't win".

### Q2 — skip supplementary high-coverage seqs; accept INDETERMINATE as scoped limitation
- Both: **do NOT add crowd/synchronous to rescue CONFIRMED.** Post-result sample selection = optional stopping; "already-seen Bonn" ≠ independent validation; failed extension adds uncertainty.
- codex: spend GPU on ablations/reproducibility, not rescue sample.
- hermes: cost/risk asymmetry bad (14d to ddl, real cost = ~1.5d critical-path incl. geometry+readout+rewrite); **zero sequences ever showed deferred judgably >1** ⇒ high-coverage⇒prune-better half has never fired; crowd is a *trap* (MonoGS 65-98cm = tracking-collapse regime), synchronous only defensible if narrative gate leans H-D-section.
- CONFIRMED vs well-written INDETERMINATE = marginal paper value (one section vs one sentence); not worth catastrophic-seed risk 10d out.

### Q3 — upgrade deferred-ATE to honest "trade", NOT "indistinguishable"
- Both: **do NOT write "in-band = indistinguishable".** 6/6 same-sign: under exchangeability null P(6/6 same-sign)=2/64=0.031 (hermes). 50% band was a *catastrophe* threshold (prereg §3, set above pt2 screening +43.4%), NOT an *indistinguishability* threshold. Worst case +37% (pt2). Conflating = category error reviewers catch.
- **Upgrade to "deferred trades ATE for compactness, conditionally."** The trade is NOT uniform: large where deferred buys NO compactness (pt2 +37%, pt1 +13%, both indeterminate compactness); small where it DOES buy compactness (balloon +1.3%, mv_no_box +11%). **That is a Pareto frontier, not a loss.**
- Report sign test honestly as exploratory (not pre-registered): "6/6 same-sign, P=0.031 under exchangeability, but sign test not preregistered and all per-seq contrasts within 50% band ⇒ directional observation, not significant regression."
- **Do NOT write "deferred systematically worse on ATE"** — "systematically" concedes mechanism-level defect; data supports a *trade/frontier*, not a defect. "Trade" is load-bearing.

## codex-only additional blind spots
1. Combined backbone bundles 4 mechanisms ⇒ without ablations reviewers call it engineering package. Present lifecycle comparison as the causal experiment; backbone = stabilized substrate; include module ablations if space.
2. Coverage signal = offline oracle, confounded w/ sequence composition ⇒ cannot support online hybrid controller.
3. 3 seeds estimate INSTABILITY not population uncertainty ⇒ paired seed plots, no sequence-level significance.
4. Compactness-ratio drift <~30% cross-campaign not meaningful ⇒ all headlines same-campaign+commit.
5. Lower G must carry memory/runtime/insert-promote-prune counts + fidelity ⇒ else "compactness = under-building".

## hermes-only BLIND SPOT (the sharpest, reviewer-2 would press)
**Coverage stratifier is confounded with TRACKING DIFFICULTY, not just class composition (prereg §6.1).**
- Low-coverage seqs (mv_no_box 23%, balloon 48%): ATE 2.6-3.1cm = tracking EASY, deferred compactness <1, ATE cost small (1-11%).
- High-coverage pure-person seqs (pt1 30%, pt2 19%): ATE 10-14cm = tracking HARD (long fast person motion), deferred compactness indeterminate, ATE cost large (13-37%).
- pt1/pt2 are also the seqs where MonoGS 3090 baseline itself is near tracking limit (person_tracking ATE 6.3-8.6cm). Near tracking limit ⇒ ANY lifecycle perturbation costs ATE regardless of mask coverage.
- **H-D mechanism story ("mask leaks ⇒ deferred has dynamic to block ⇒ compactness") and alternative ("hard-tracking seqs are ATE-fragile to any lifecycle change ⇒ deferred costs ATE there regardless of mask") predict the SAME data pattern at n=6.** Prereg §6.1 does NOT list this confound.
- Implication for Q1: do NOT claim boundary is a *mask-coverage* boundary. Claim it is a *sequence-dependent* boundary; mask coverage is *a candidate stratifier* whose simple per-frame form is unsupported (INDETERMINATE) but whose existence as *some* offline property is suggested by 3/3 judgable same-direction.
- **Cheapest de-confounding experiment ≠ new Bonn seq (Q2) — it is a FROZEN-POSE control on pt1 or pt2.** Apparatus exists (R2-P03 ran balloon frozen-pose; readout imports SWEEP family). Frozen-pose pt1 removes tracking difficulty: if deferred still costs ATE under frozen pose ⇒ map-level effect (consistent w/ H-D "provisional candidates perturb densify"); if deferred ATE cost VANISHES under frozen pose ⇒ 6/6 same-sign is tracking-coupling artifact, H-D mechanism story wrong. **One pair of runs (~1h on 2060), on a seq already run, directly tests the confound.** Higher value than any Q2 seq. Can run in F@5cm post-proc gap.

## Decision synthesized (my read, for user GO/KILL)

**Narrative D′ (positive, both reviewers endorse the shape):**
- Headline = lifecycle applicability boundary (measurement contribution), NOT "deferred wins".
- 2×2 table (regime × {compactness, ATE}) as the central figure.
- compactness <1 reproduces on unseen low-coverage (mv_no_box, pt1); balloon −50% = largest instance, provenance-flagged.
- ATE = conditional trade on a Pareto frontier, NOT no-harm / NOT systematically-worse. Sign test reported exploratory.
- H-D = prospective internal check, INDETERMINATE, stratifier instability (a/b flip) named as part of finding.
- Limitations self-report: class-composition confound (§6.1) + **tracking-difficulty confound (hermes blind spot, NEW)** + n=6 + 3-seed-instability + offline-oracle.

**GPU priority after 36/36 (revised by reviews):**
1. **F@5cm geometry post-proc** (already scripted, GPU-gap, cannot run concurrent w/ SLAM) — needed for the 2×2's compactness column to carry fidelity.
2. **Frozen-pose pt1 pair** (hermes blind-spot test, ~1h) — directly de-confounds the headline. HIGHEST marginal value per GPU-hour. **RUN THIS if anything beyond 36/36.**
3. Module ablation (codex blind spot) — at minimum a vanilla-MonoGS-vs-backbone row on 1-2 seqs; full 4-module ablation if budget.
4. **SKIP crowd/synchronous** (both reviewers).

**What I will NOT do without user GO:** the frozen-pose pt1 pair is a NEW experiment (not in any frozen contract). Per README §2 control must be frozen + experiment.yaml APPROVED. But it's ~1h and directly load-bearing for the headline — I'll prepare the config + contract + prereg note, run it as a clearly-labeled de-confounding control, and report. This fits the user's "补实验也可以" autonomy grant.
