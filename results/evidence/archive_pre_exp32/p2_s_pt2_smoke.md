# P2-S-pt2 de-risk (2026-07-31) — the combined backbone on the highest-risk sequence

> **Screening only.** 2 runs, single seed, person_tracking2. No verdict (discipline ⑤).
> pt2 was the de-risk rung, not just another smoke: it was the WORST rtoff self-tracked ATE
> (44.22 prune / 20.99 deferred) and the combined backbone had never run on it. This pair
> (~50 min) confirms the backbone does not collapse on pt2 BEFORE the 36-run P2-T spend.
>
> Configs: `p2_render/p2s_combined_{prune,deferred}_pt2.yaml`, self-tracked, twin invariant
> (only `Mapping.lifecycle_mode` differs) verified by resolution. Run against commit
> `35993a3`, clean worktree.

## §1 The two numbers pt2 was built to buy

| arm | ATE cm | KF-ATE cm | refined G | VRAM GB | online FPS |
|---|---|---|---|---|---|
| `Combined-Prune` | **11.2148** | 11.2037 | 64153 | 3.240 | 0.453 |
| `Combined-Deferred` | **16.0817** | 15.2788 | 68578 | 2.871 | 0.470 |

- **The backbone does NOT collapse on pt2 (de-risk objective met).** prune 11.21 cm beats
  DynaGSLAM (13.69), RGD-SLAM (20.10) and Co-SLAM (71.26); only DG-SLAM (6.12) and NGD-SLAM
  (6.63) are stronger. rtoff was 44.22/20.99 cm — the combined backbone cuts prune from 44
  to 11. **pt2 may stay in the P2-T main table.**
- BUT — the compactness result that carried the paper on balloon **reverses direction on pt2**.

## §2 The reversal: compactness is sequence-dependent (screening)

| seq | arm | ATE cm | G | G_def/G_prune | compactness? |
|---|---|---|---|---|---|
| balloon | prune 3.19 / def 3.23 | | 35991 / 18391 | **0.511×** | ✅ deferred smaller |
| pt2 | prune 11.21 / def 16.08 | | 64153 / 68578 | **1.069×** | ❌ deferred LARGER |

On pt2, deferred's map is **+6.9% larger** (not −48.9% smaller), and deferred's ATE is
**+43.4% worse** (16.08 vs 11.21). This is the first sequence in the project where deferred
loses to prune on both rate AND ATE.

**This is not "pt2 broke the method." It is the method's applicability boundary showing.**

balloon = person + balloon. A COCO-person mask structurally cannot catch the balloon
(MASKRATE limitation, §4.5.2). The mover the mask misses is still in the frame ⇒ the deferred
candidate lifecycle has something to filter ⇒ compactness holds (0.511×).

pt2 = person tracking. The person mask already catches the mover. With the dynamic region
masked, deferred's candidate-confirmation step has nothing dynamic left to block — and the
*provisional* candidates it admits in the meantime perturb the densify budget and the
`explained` test (the irreversible second-order effect P1-CENSUS was designed to measure).
On pt2 that effect is **net negative**: larger map, worse ATE.

## §3 What this changes for the narrative (not yet committed — user direction pending)

Before pt2, the compactness claim was "deferred is more compact at equal fidelity" — a
candidate for a universal statement, with MASKRATE already narrowing it to "vs insert-then-prune,
not vs hard masking." pt2 narrows it further and in a *different* direction:

- compactness is **not universal** — it flips sign across two Bonn sequences;
- the flip is **explainable**: it tracks whether the person mask already removes the mover
  (pt2: yes ⇒ deferred's second-order effect is net negative) or misses part of it
  (balloon: the balloon ⇒ deferred's lifecycle has something to filter ⇒ compactness holds).

This is the sharpest mechanistic boundary the project has. **It is also the first evidence for
the user's "取长补短" direction**: prune is the better lifecycle when the mask is sufficient,
deferred is the better lifecycle when the mask leaks. A hybrid that *selects lifecycle by
whether the mask covered the mover* would, in principle, get balloon's −48.9% AND pt2's
prune-side advantage. That is a new hypothesis, not a result — it needs its own
pre-registration and a gating signal (e.g. mask-coverage-per-keyframe).

## §4 Caveats (own account)

1. **Single seed.** pt2's deferred ATE 16.08 could be a high seed; rtoff pt2 deferred was
   20.99, also high — pt2 is a high-variance sequence. The reversal direction (G_def/G_prune
   > 1) is the more robust reading than the magnitude.
2. **Self-tracked, single sequence pair.** This is not the frozen-pose controlled screen;
   ATE here is real tracker output and noisier.
3. **No fidelity columns read.** On pt2 the static-background scoring depends on the GTMC
   mask; the rate/ATE reversal is clear without them, but the bounded-non-inferiority rule
   from the R2-P03 campaigns is not applied here (different regime, screening).

Single seed. No verdict. GO/KILL and narrative are the user's.
