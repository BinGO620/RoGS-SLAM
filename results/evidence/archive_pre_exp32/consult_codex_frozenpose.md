# Codex review — frozen-pose pt1 de-confounding control DESIGN (2026-08-02, read-only)

> Third-party consult via codex MCP (gpt-5.5/high). Reviewing the EXPERIMENT DESIGN before any GPU spent.

## Verdict: do NOT run the proposed pair as written
- Cannot test an ATE difference (ATE identical by construction under frozen pose).
- pt1 does not break the coverage-vs-difficulty confound.
- One seed cannot support the proposed branches.

## 1. Correct Observable

With identical injected poses + zero camera learning rates, ΔATE_frozen = ATE_def − ATE_prune = 0 **by construction**. A nonzero value = apparatus failure, not a scientific result. Repo already confirms this: R2-P01-E2 injected prune/deferred rows reproduce identical ATE while map differences remain (`r2_oracle_admission_e2.md`).

**Valid primary observable = compactness ratio under frozen trajectory:**
- R_G^F = G_def^F / G_prune^F (common frozen traj)
- Compare vs self-tracked R_G^S, preferably log scale: I_G = log R_G^S − log R_G^F
- This is a **pose-regime × lifecycle interaction**: does the compactness contrast survive when pose-map feedback is disabled?

**Fidelity = preregistered guardrail, NOT outcome selected afterward.** Use F@5cm + all-static penalized depth as principal fidelity pair. Repo previously demoted vacated depth to auxiliary because it failed its gate. Report vac_depth/vac_psnr but don't make them sole fidelity evidence.

Also record: keyframe count + exact KF indices, VRAM/FPS, inserted/promoted/expired/pruned counts, static PSNR, injected trajectory's audited ATE.

**Frozen pose does NOT necessarily freeze DynamicKeyframe decisions.** If KF schedules differ, R_G^F measures total lifecycle-induced mapping-policy effect (incl. altered coverage), NOT pure admission efficiency. Freeze KF indices if feasible; else preregister differing schedules as ambiguity trigger.

**What a surviving R_G^F tells you is LIMITED**: lifecycle directly changes mapping under the chosen trajectory. Does NOT show mask coverage causes the effect, says nothing about WHY self-tracked deferred ATE is higher.

**Prior evidence already exists**: earlier frozen-pose campaign found deferred fewer Gaussians in 13/14 pairs, injected mean ratio 0.426 (`r2_oracle_admission_e2.md`). A pt1 repeat = incremental backbone-specific replication, NOT a new de-confounding principle.

## 2. Sequence Choice

**pt1 is the WRONG single sequence** for breaking coverage-vs-difficulty collinearity. Freezing pt1 removes within-run tracking feedback but does NOT supply the missing high-coverage/easy cell.

Plan's labels are stale:
- pt1 coverage 29.9%, pt2 18.8%, balloon 48.2%, balloon2 59.4% (highest).
- Current 35/36 readout: pt1 R_G≈0.794, judgably <1, NOT compactness-indeterminate.

Existing data already contain a better contrast:
| Cell | Candidate | Coverage | Prune ATE |
|---|---|---|---|
| High coverage, easier tracking | balloon2 | 59.4% | 5.22cm |
| Low coverage, hard tracking | pt2 | 18.8% | 9.98cm |
| Moderate coverage, hard tracking | pt1 | 29.9% | 10.97cm |

Claimed diagonal is not clean even before another experiment. If GPU spent, run a **matched frozen-pose SET** — at minimum balloon2 AND pt1/pt2, not pt1 alone. Better: preregister full 2×2 inclusion rule using coverage measured WITHOUT SLAM outcomes + difficulty defined by arm-independent baseline.

Do NOT select synchronous/crowd merely because expected to fill a desired cell. First compute coverage + independent difficulty anchor for all eligible Bonn seqs, then freeze inclusion rule.

## 3. Executable Preregistration

**Use three paired seeds immediately.** "Seed 0, add seeds if discriminating" = outcome-dependent stopping, cannot estimate the existing 2×own-sd rule. Prior frozen experiments showed seed-dependent fidelity reversals.

Define branches on R_G^F, fidelity as gate:
- **Map contrast remains**: R_G^F outside preregistered rate-noise/equivalence band, same sign as R_G^S, fidelity within frozen non-inferiority limits. Conclusion: a tracker-orthogonal mapping effect exists on this seq. NO claim coverage caused it or that it explains ATE.
- **Map contrast vanishes**: R_G^S judgable, R_G^F falls inside genuine equivalence interval around 1. "Indeterminate by noisy 3-seed SD" is NOT equivalence. Conclusion: self-tracked compactness contrast depends materially on pose-map feedback. Still NO proof tracking difficulty caused the 6/6 ATE sign.
- **Ambiguous**: opposite sign; CI spans both equivalence and meaningful effect; fidelity violates guardrail; KF schedules differ unless frozen; catastrophic seed; or injected trajectory places mapping in clearly different regime.

**Audit the pt1 RGD trajectory before launch.** Cited template is for pt2 (injected ATE 26.30cm). A poor fixed trajectory changes the mapping regime rather than cleanly representing "tracking difficulty removed."
