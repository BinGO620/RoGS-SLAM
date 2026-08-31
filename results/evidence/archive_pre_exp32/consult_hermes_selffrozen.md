# Hermes consult — self-frozen pose de-confound (variant B vs C, and whether to run at all)

> Independent review. Read against: consult_codex_frozenpose.md,
> consult_hermes_frozenpose.md, consult_synthesis_frozenpose.md,
> p2fp_frozenpose_outcome.md, r2_oracle_admission_e2.md, hd_coverage_prereg.md,
> p2t_verdict_final.md. Verified code paths: utils/oracle_pose.py,
> utils/eval_utils.py:311-342, utils/slam_frontend.py:870-987.

## Bottom line

**Run C, not B. C is the cleaner experiment for THIS question. B is a
sensitivity footnote.** The "GT too perfect" concern is real and disqualifying
for B as primary, not merely a caveat. And the experiment is worth running —
but as a scoped limitation-sharpener, not an H-D rescue.

## Q1: Does C actually de-confound? Is there a new trajectory-bias confound?

**Yes, C de-confounds the tracking-difficulty axis. The trajectory-bias concern
is real but bounded, and I measured it.**

The confound to break: "coverage collinear with tracking difficulty" — pt1/pt2
are simultaneously high-coverage-pure-person AND hard-tracking (ATE 10-14cm).
Under self-tracking, the tracker co-adapts with the map: I measured prune-vs-
deferred trajectory divergence on pt1 seed0 at **mean 7.1cm / max 24.0cm
position, 2.1deg rotation**. That divergence IS the tracking-difficulty channel
manifesting — different maps feed back into different poses. Freezing the pose
kills this channel. C does that.

The trajectory-bias concern: injecting prune's trajectory into deferred means
deferred maps on a trajectory co-adapted with prune's map. Is that systematically
unfair to deferred? Two facts bound this:

1. **The tracker is identical across arms** (combined backbone: same mask-both,
   same RobustTracking, same DynamicKeyframe gating). The trajectory divergence
   is the *feedback effect* of map differences on a shared tracker — not a
   tracker asymmetry. Prune's trajectory is "the tracker's output given prune's
   map," not "a trajectory optimized to favor prune's admission policy."

2. **The bias direction is ambiguous, not one-sided.** If prune's trajectory is
   "easier" for prune's map, it could be either easier OR harder for deferred's
   map — there is no theorem saying co-adapted-with-prune = hostile-to-deferred.
   The bias exists but its sign is not predictable, which is what you need for a
   paired comparison (you need the bias to not systematically manufacture the
   effect you're looking for).

**The residual confound in C**: the injected trajectory is selected by prune's
run (a post-treatment variable — prune's map influenced it). This is the
selection bias codex flagged. It is real. But it is a *second-order* confound
(map→trajectory→map feedback, ~7cm on a 11cm base) sitting on top of the
*first-order* confound you are killing (tracking difficulty, which produces
10-14cm ATE differences and is the entire reason H-D is INDETERMINATE). Killing
the first-order confound while introducing a bounded second-order one is a net
win for interpretability.

## Q2: C vs B — which is cleaner for "lifecycle pure effect"?

**C is cleaner for the question you are actually asking. B is cleaner for a
different question you are not asking.**

B (GT-pose) is causally cleaner in the IV sense: GT is exogenous, not selected
by either arm. But B introduces a **regime-change problem** that is worse than
C's selection bias:

- R2-P01-E2 already measured this: frozen-pose (RGD injected, 2-26cm ATE) gave
  PSNR ~15 vs self-tracked ~19-25. The map regime under frozen pose is
  *globally different* — frozen poses cannot co-adapt with the map, producing
  globally blurrier reconstruction. The paired arm-delta is still valid, but
  you are now measuring "lifecycle effect in a blurrier-than-realistic regime."
- B pushes this to the extreme: GT pose = 0cm ATE = *perfect* tracking. The
  mapping regime under perfect poses is further from the self-tracked regime
  than C (11cm, which is the actual self-tracked regime). codex's own caveat
  — "GT poses may be unrealistically perfect enough to suppress the phenomenon
  of interest" — is not a footnote; it is a **validity threat**. If the
  compactness effect is partly mediated by pose-map feedback (which is exactly
  what you're testing), perfect poses can suppress it by construction, producing
  a NO-MAP-EFFECT that is an artifact of the regime, not evidence of tracking-
  coupling.

C keeps the injected trajectory in the *same regime* as self-tracking (11cm
ATE = the actual pt1 tracking quality). The regime is realistic. The only cost
is the selection bias (prune-conditioned), which is bounded and labelable.

**Rule: when choosing between a clean instrument that changes the regime and a
slightly-biased instrument that preserves the regime, preserve the regime. The
effect you are measuring is regime-dependent (R2-P01-E2 proved this). A clean
instrument in the wrong regime measures nothing generalizable.**

## Q3: Is there a (D) — moderate-quality neutral trajectory?

**No good (D) exists in your apparatus, and fabricating one creates worse
problems than it solves.**

Options for "moderate-quality neutral trajectory":
- **Deferred's own trajectory**: symmetric to C with opposite bias — same
  problem, mirrored. Running both C and C′ (deferred-frozen) would bracket the
  bias, but doubles the runs for 2 seqs × 2 injection-sources × 2 arms × 3
  seeds = 24 runs. Not worth it for a limitation-sharpener.
- **Average of prune+deferred trajectories**: not a real trajectory (poses
  averaged mid-sequence produce inconsistent camera paths, breaks depth
  alignment).
- **External moderate tracker (e.g. ORB-SLAM3)**: you tried RGD — gate failed
  on correspondence. Any external trajectory reintroduces the exact provenance
  problem that killed pt1 frozen-pose. The whole point of self-frozen is that
  trj_full_final.json has trj_gt = dataset GT by construction, so the gate
  passes at residual ~0.

(D) is a trap. C is the best available.

## Q4: Is this de-confound worth running at all?

**Yes, but scope the claim honestly.** Three reasons:

1. **It sharpens the limitation, not resolves it.** H-D is INDETERMINATE and
   will stay INDETERMINATE — this experiment cannot upgrade it (n≤2, map-level
   only, seen data, ceiling = weaken/unchanged per both prior reviews). But a
   MAP-EFFECT result on C lets you write: "under frozen pose (prune-trajectory,
   pt1+balloon2), the compactness contrast survives (R_G^F < 1, same sign as
   self-tracked), indicating a tracker-orthogonal mapping channel exists; we
   cannot attribute it to mask coverage vs tracking difficulty, which remains
   a stated limitation." That is strictly better than "stated-untested."

2. **Cost is low.** trj_full_final.json already exists for all P2-T runs (I
   verified: pt1 580 frames, balloon2 469 frames, schema matches oracle_pose.py
   exactly, gate will pass at ~0 residual). No new trajectory acquisition. Seed-
   0 screening = 4 runs (~2h on 2060). Only expand to 3 seeds if MAP-EFFECT or
   REVERSED fires.

3. **It unblocks the frozen-pose apparatus.** The RGD gate failure left the
   control as "future-work pointer." C makes it runnable now, with 100%
   verifiable frame correspondence — the exact thing RGD lacked.

**Do NOT run if**: you need this to confirm H-D (it can't), or if 2h of 2060
time blocks a higher-priority task. Given MMM ddl 08-16 and the writing window,
2h for a limitation-sharpener is cheap.

## Q5: Prereg — same three branches, with adjustments

Same structure as prior frozen-pose prereg (MAP-EFFECT / NO-MAP-EFFECT /
REVERSED on R_G^F), with these changes:

1. **Observable = R_G^F = G_def^F / G_prune^F** (both arms frozen on prune
   trajectory). ATE = canary (identical by construction, both share injected
   trj_est). Fidelity = vac_depth / vac_psnr as guardrail, NOT outcome.
2. **Label C as "prune-conditioned"** in the prereg title. State the selection
   bias explicitly: "injected trajectory is prune's self-tracked output, which
   is post-treatment (map-coupled); the bias is bounded (measured 7cm divergence
   on pt1) but its sign is not predictable."
3. **Run B as a sensitivity footnote**, not a branch: "GT-pose (B) run as
   regime-extremity check; if B suppresses the effect while C shows it, this
   is consistent with pose-map feedback mediating part of the compactness
   contrast — reported as evidence, not as a separate branch decision."
4. **Sequences: pt1 + balloon2** (codex recommendation, I agree). pt1 = hard-
   tracking + moderate-coverage; balloon2 = easy-tracking + highest-coverage.
   This gives the 2×2 contrast codex asked for (hard/easy × the frozen-pose
   delta), which pt1-alone could not.
5. **Freeze keyframe indices if feasible** (codex caveat from prior review:
   frozen pose does not freeze DynamicKeyframe decisions). If KF schedules
   differ across arms, preregister as ambiguity trigger.
6. **Paired-seed log(G_def/G_prune)** with prereg equivalence region, NOT 2×
   own_sd (codex amendment). The 2×own_sd rule was the H-D prereg's; for this
   control, use the paired-seed log-ratio with a preregistered equivalence
   band around 0.
7. **Ceiling**: "This experiment can only WEAKEN or LEAVE-UNCHANGED the H-D
   INDETERMINATE verdict. It cannot confirm H-D. n=2 sequences, map-level
   observables only, seen data."

## Disagreement with codex

codex recommends B primary, C sensitivity. I recommend the reverse: **C primary,
B sensitivity.** The reason is the regime-change problem (Q2): B's causal
cleanliness comes at the cost of measuring in a regime (perfect pose) where the
phenomenon may not live. C's selection bias is bounded and labelable; B's
regime-suppression is unbounded and silent. For a phenomenon already proven to
be regime-dependent (R2-P01-E2: PSNR 15 vs 23), preserving the regime is more
important than exogeneity. If B and C disagree, the disagreement itself is
informative (pose-map feedback mediation), so run both — but C carries the
preregistered branch decision.
