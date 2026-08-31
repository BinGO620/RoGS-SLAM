# Codex review — self-frozen pose de-confound design (2026-08-02, read-only)

> Reviewing the self-frozen pose design BEFORE GPU spend (replaces failed RGD frozen-pose).

## Variant C de-confounds tracking — but estimand is prune-conditioned

C removes tracking variation within the frozen pair (both arms share prune's trajectory). "Prune-favorable" selection = **effect modification / limited external validity**, NOT an internal confound: it may make deferred look worse, but cannot create unequal tracking inputs within the pair.

BUT the trajectory is **post-treatment** (produced under prune). C cannot estimate a neutral lifecycle effect or support "tracking difficulty removed generally." Defensible wording:

> lifecycle effect on mapping when replaying a prune-generated backbone trajectory.

The frozen prune replay is essential. Do NOT compare deferred-frozen directly with the original prune self-tracked map (replay changes keyframe decisions, optimization history, RNG even when poses match).

## C vs B — B is cleaner for causal isolation

- **B (GT-pose)**: GT poses are exogenous, identical, not selected by either arm. For "lifecycle-only effect on map," B is cleaner. PSNR regime shift does NOT invalidate within-regime contrast; only limits transport back to normal SLAM.
- **C (prune-trajectory)**: more operationally relevant (poses on backbone's actual error manifold), but estimand is prune-conditioned.

**codex recommendation:**
- **Primary mechanistic control: B** (both arms on GT).
- **Sensitivity/bridge control: C** (both arms on same prune trajectory).
- If only one pair affordable: **choose B** for causal cleanliness.
- If GT poses unrealistically perfect enough to suppress the phenomenon of interest: choose C but label explicitly as prune-conditioned.
- A strong result = **concordance across B and C**. Disagreement = informative trajectory×lifecycle interaction, NOT grounds to select the preferred result.

Also: freeze or externally prescribe **keyframe indices** if feasible. Else comparison captures total lifecycle-induced mapping-policy effect, not merely admission/pruning efficiency (per consult_synthesis_frozenpose.md).

## Prereg branches — corrected

Current REVERSED branch is stale (final self-tracked pt1 G_def/G_prune=0.794, so under frozen pose):
- **CONCORDANT MAP-EFFECT**: ratio detectably <1, OR a prespecified fidelity effect detectable.
- **NO-DETECTABLE-MAP-EFFECT**: ratio AND both fidelity contrasts inside prespecified equivalence regions.
- **REVERSED MAP-EFFECT**: ratio detectably >1.
- **MIXED/TRADE**: compactness and fidelity move in opposing practical directions.

Do NOT require a fidelity difference for a Gaussian-count effect to count as a map effect. Classify joint outcome as compactness-benefit / fidelity-benefit / harm / trade. ATE = construction canary only (per p2fp_frozenpose_prereg.md).

Avoid "2× own_sd" as final rule unless exact ratio-scale calc fixed beforehand. Prefer paired-seed `log(G_def/G_prune)` with preregistered equivalence region derived from prior frozen-pose variability + inherited fidelity margins.

## Sequence choice

**pt1 + balloon2**, NOT pt1 alone and NOT balloon as the 2nd cell. balloon's 0.498 is a strong compactness demonstration, but balloon2 is the useful high-coverage/easier-tracking countercell. pt2 = later robustness addition (high variance + near-limit tracking weaken diagnostic clarity). Use one independently selected/self-tracked prune trajectory per seed, shared by both frozen arms, analyze seeds as paired observations.
