# Hermes consult — frozen-pose pt1 de-confounding control

> Skeptical third-party review of the proposed frozen-pose pt1 pair as a
> de-confound of "mask coverage vs tracking difficulty." Read against:
> hd_coverage_prereg.md, hd_coverage_anchor.md, consult_hermes_p2t.md
> (blind-spot section), oracle_pose.py, r2_p02_preflight_pose_rgd.md,
> registry R2-P01-E2. Web-checked Bonn sequence characteristics.

## Q1 — Does frozen-pose actually de-confound? What is the right observable?

**No — not as proposed. The proposal as written measures nothing, because
frozen-pose ATE is identical across arms by construction.** This is not a
guess; it is a code fact and a measured fact:

- `utils/oracle_pose.py` + `slam_frontend.py:905-987`: under
  `Oracle.pose_file`, the frontend sets `oracle_skip=True` at itr 0 and
  breaks before any Adam step. `viewpoint.R_gt/T_gt` are never touched
  (oracle_pose.py docstring lines 28-30). The end-of-run ATE row measures
  *injected-vs-real-GT* — the injected pose is the SAME file for both arms.
- This was already confirmed empirically in R2-P01-E2 (registry):
  "prune=deferred ATE identical under frozen pose -> injected map-delta is
  pure map-admission." On balloon the frozen-pose ATE was 2.0618 cm to 4
  decimal places on ALL runs, both arms, all seeds (r2_p02_preflight_pose
  G1 canary, ±0.02 fail-fast).

So "does deferred still cost ATE under frozen pose?" has a predetermined
answer: **the ATE difference is exactly zero, always, on every sequence,
by construction.** Running pt1 will not tell you whether deferred's ATE
cost "vanishes" — it vanishes trivially because there is no tracking
channel for either arm to differ through. The proposal conflates two
different questions:

1. "Is deferred's self-tracked ATE cost a tracking-coupling artifact?"
   (the real H-D confound) — **frozen-pose CANNOT answer this**, because
   it removes the only channel through which the artifact would manifest.
   A zero result here is uninformative: it is consistent with both
   "tracking-coupling artifact" AND "map-level effect that is too small
   to move ATE when pose is pinned."
2. "Does deferred perturb the map in a way that WOULD cost ATE if pose
   were free?" — this is a map-level question and the right observables
   are **map-quality / fidelity metrics, NOT ATE**: `refined_num_gaussians`
   (compactness G_def/G_prune), `static_vacated_depth_l1_pen_cm`,
   `static_vacated_psnr`, and the candidate ledger (promoted/expired/
   pruned). These ARE arm-discriminating under frozen pose — R2-P01-E2
   measured deferred fewer Gaussians 13/14 pairs at identical ATE.

**Corrected observable set for the frozen-pose pair:**
- PRIMARY: G_def/G_prune (does the compactness reversal on pt1 reproduce
  when pose is pinned? if pt1 self-tracked was indeterminate but
  frozen-pose flips to clean <1 or >1, that is a map-level signal
  unconfounded by tracking).
- SECONDARY: vac_depth, vac_psnr (does deferred degrade fidelity at
  equal pose? R2-P01-E2 found fidelity co-primary gate NOT met — only
  pt2 cleared 4/4 — so this is a real, arm-discriminating axis).
- ATE: report only as the frozen-pose canary (== injected-tracker ATE
  ±0.02, G1 gate), NOT as an arm-discriminator. State explicitly in the
  prereg: "ATE is identical across arms by construction under
  Oracle.pose_file; it is a canary, not an outcome."

The de-confound that frozen-pose DOES achieve: it isolates the map-level
arm effect (compactness + fidelity) from tracking difficulty. That is
valuable — but only if you measure map-level quantities. Measuring ATE
and calling it a de-confound is a category error.

## Q2 — Is pt1 the right sequence?

**pt1 is defensible but not optimal; the optimal pick does not exist in
Bonn, and pt1 is the best available.** Reasoning:

The confound is "coverage collinear with tracking difficulty." To break
it you want a cell that is high-coverage AND easy-tracking — mask
sufficient + pose easy — and compare to pt1 (high-coverage + hard-
tracking). If deferred's compactness/fidelity cost is similar in both,
tracking difficulty is not the driver; if it appears only in the hard-
tracking cell, tracking difficulty is implicated.

Checking Bonn (web + your own 3090 baseline data):
- pt1/pt2: pure person, fast pedestrian tracking, ATE 10-14cm on your
  backbone = hard tracking. Coverage 30%/19% (moderate, not high).
- balloon/balloon2: person+balloon, slower hand-held motion, ATE 2.6-
  5.9cm = easy tracking. Coverage 48%/59% (the highest in your set).
- crowd/synchronous: multiple persons, jumping/synchronous motion —
  web sources (SGDO-SLAM) describe synchronous as "several people
  repeatedly jumping" = HARD tracking, and your consult_hermes_p2t.md
  already flagged crowd as a tracking-collapse regime (MonoGS ATE 65-
  98cm). Not a clean high-coverage+easy cell.

**The clean high-coverage+easy-tracking cell does not exist in Bonn.**
balloon2 (59.4% coverage, ATE 5.1-5.9cm, easy) is the closest, but it
is person+balloon (class-composition confound, prereg §6.1) and its
self-tracked G ratio is INDETERMINATE (0.910). So you cannot get a
clean two-cell contrast within Bonn.

Given that, pt1 is the right pick for a different reason: it is the
sequence where the self-tracked ATE cost was largest (+13% to +37%
across seeds) AND where MonoGS baseline is near its tracking limit. If
frozen-pose pt1 shows the map-level compactness/fidelity effect is SMALL
there, that is the strongest evidence the self-tracked ATE cost was
tracking-coupled. If it shows a LARGE map-level effect, the H-D
mechanism story survives. **Run pt1; do not run balloon (already
exhaustively frozen-pose'd in R2-P03 four campaigns) and do not run
crowd/synchronous (collapse risk, no baseline).**

## Q3 — Prereg that does not self-trap

Three branches, bound BEFORE the run, observables fixed per Q1:

| branch | condition (frozen-pose pt1, seed 0) | interpretation |
|---|---|---|
| MAP-EFFECT | G_def/G_prune judgable (|r-1| > 2× own sd from R2-P03 balloon frozen-pose CV ~7.8%) AND vac_depth or vac_psnr arm-discriminating (> 1× own sd, same sign) | deferred perturbs the map independently of tracking ⇒ H-D mechanism story survives; the self-tracked ATE cost may be partly tracking-coupled but a map-level channel exists |
| NO-MAP-EFFECT | G ratio indeterminate (in band) AND both fidelity metrics within own-sd | deferred's self-tracked ATE cost on pt1 is plausibly tracking-coupled, not map-level ⇒ H-D mechanism story weakened; report as scoped limitation, do not claim map-level mechanism |
| REVERSED | G_def/G_prune judgable <1 (deferred smaller) on pt1 under frozen pose | directly contradicts the pt1 self-tracked indeterminate/>1 reading ⇒ the self-tracked pt1 compactness was tracking-coupled, not a coverage effect |

Pre-declared guardrails (write these in, do not leave to post-hoc):
1. **ATE is a canary, not an outcome.** State the construction-identity
   fact (oracle_pose.py) in the prereg. Do not report a frozen-pose ATE
   "difference" — there is none. Anyone reading "deferred ATE cost
   vanished under frozen pose" as evidence for H-D is committing the
   category error in Q1.
2. **Single seed is screening only.** Explicitly: "seed 0, no verdict;
   if MAP-EFFECT or REVERSED fires, 3-seed confirmation is required
   before any claim enters the paper." Do not let a single-seed
   frozen-pose result override the 3-seed self-tracked table.
3. **Fidelity margins inherited, not re-fit.** Import the 1.56cm /
   0.28dB bounds from r2_p03_sweep_readout.py (as P2-T does). Do not
   define a new margin on pt1 frozen-pose — that is post-hoc threshold
   fitting.
4. **Do not upgrade H-D status from this experiment alone.** The
   frozen-pose pair can only WEAKEN or LEAVE-UNCHED the self-tracked
   H-D INDETERMINATE verdict. It cannot confirm H-D (n=1, one sequence,
   map-level only). State this ceiling explicitly.
5. **Provenance:** pt1 is already-seen (P2-T ran it). This is a
   mechanistic de-confound on existing data, NOT an independent test.
   Label it "mechanistic control on seen data."

**Bottom line:** the experiment is worth running (~1h, apparatus exists,
RGD pt1 pose file confirmed at external_trajectories/rgd/bonn_person_tracking/
seed_0/.../trj_final.json), but ONLY with map-level observables
(compactness + vac_depth + vac_psnr) as primary, ATE as canary. As
originally proposed — measuring ATE and asking "does deferred still
cost ATE" — it is a null experiment by construction and would produce a
misleading "cost vanished" claim.
