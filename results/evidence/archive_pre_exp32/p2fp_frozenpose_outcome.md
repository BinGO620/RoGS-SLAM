# P2-FP frozen-pose pt1 de-confounding control: OUTCOME (2026-08-02)

> Status: **INVALIDATED — not run.** Per codex review (consult on the gate failure).
> The control could not establish verifiable frame correspondence; abandoned per
> prereg §4 guardrail #6 (audit trajectory) rather than relax the self-validation gate.

## What happened

Both frozen-pose arms (`p2fp_combined_{prune,deferred}_pt1.yaml`, seed 0) FAILED
the oracle self-validation gate at `utils/oracle_pose.py:136`:

```
ValueError: GT anchor residual 1.111cm > 1.0cm (trj_final.json): wrong file/convention/frames
```

## Diagnosis

- The RGD pt1 `trj_final.json` has 580 frames (trj_est + trj_gt); our raw
  `groundtruth.txt` has 583 frames. The MonoGS associator (max_dt=0.08) drops 3
  → `dataset.poses` = 580, so the frame-COUNT check (oracle_pose.py:124) passes.
- BUT the best-fit Umeyama rigid transform between the file's `trj_gt` and our
  dataset GT leaves a **1.111cm** residual — just over the 1.0cm gate.
- The pt2 RGD file (used successfully in R2-P01) anchored at 0.899cm; pt1 is 1.111cm.
- The RGD `trj_final.json` carries only indices `0..579` — **NO timestamps**.
  Original frame provenance is lost. The RGD `slam_outputs/` dir contains only
  `plot/`, no association files. ⇒ frame correspondence CANNOT be independently
  verified as index-drift vs GT-source diff.

## Decision (codex, option 2)

**Abandon the pt1 frozen-pose control. Do NOT relax the gate threshold.**

codex: equal length does not establish that row k = same image in both
trajectories. A shared but image-misaligned trajectory could alter mapping and
fidelity in both arms, undermining the control even if the arm comparison
remains paired. Raising the threshold 1.0→1.5cm would knowingly bypass exactly
the "frame drop / convention drift" condition the gate documents. The 1.5cm
override is defensible ONLY as an explicitly labeled sensitivity run AFTER
correspondence is independently verified — not for the MAP-EFFECT/NO-MAP-EFFECT
preregistered branch decision.

Timestamp/frame-ID recovery (codex option 3) is NOT possible: the file has no
timestamps and the RGD run dir has no association files.

## What this means for the paper

**hermes's tracking-difficulty confound (the sharpest blind spot) is now a
STATED-UNTESTED limitation**, not a de-confounded measurement. Per
`consult_synthesis_p2t.md` + `p2fp_frozenpose_prereg.md` §5:

- The H-D mechanism story ("mask leaks ⇒ deferred has dynamic to block ⇒
  compactness") and the alternative ("hard-tracking seqs are ATE-fragile to any
  lifecycle change ⇒ deferred costs ATE there regardless of mask") predict the
  SAME pattern at n=6. This confound is **named in limitations, not resolved**.
- The narrative D′ headline is DOWNGRADED accordingly: claim "sequence-dependent
  boundary" (defensible), NOT "mask-coverage boundary" (requires the confound
  resolved). Mask coverage is "a candidate stratifier whose simple per-frame form
  is unsupported (INDETERMINATE); tracking-difficulty collinearity is a stated,
  untested confound."
- The frozen-pose apparatus (configs + contract + prereg) is PRESERVED as a
  future-work pointer; the gate failure is documented so a future run with a
  timestamped RGD trajectory (or a self-frozen pose from our own run) can pick it
  up. **A self-frozen pose** (freeze our OWN prune arm's trajectory, re-inject for
  deferred) would sidestep the RGD-correspondence problem entirely — flagged as
  the clean future route.

## No headline change

- Backbone-holds (ATE): unaffected.
- H-D INDETERMINATE: unaffected (was already the verdict).
- deferred-ATE trade: unaffected.
- 2×2 narrative D′ table (compactness + ATE): unaffected.
- F@5cm already dropped (separate finding, `p2t_geometry_f5cm_findings.md`).
