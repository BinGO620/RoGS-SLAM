Now I have enough context. Here are the answers, adversarial and concrete.

---

## Q1: Can (A+B+C+D) carry a paper?

**No — not on its own, and no amount of framing closes the gap.**

The honest diagnosis:

- **(A) Terminal compression op<0.01** is the only result that is real, replicable, and non-trivial. 9–16% map shrink at |dPSNR| ≤ 0.0001 dB across 12/12 runs is a genuine finding.
- **(B) Deletion-is-free-for-tracking** is a useful negative-cost proof that enables (A).
- **(C) Dynamics-agnostic** is an honest characterization that strengthens (A).
- **(D) Pareto positioning** is the **weakest** claim and the one most likely to collapse under scrutiny (addressed in Q5).

What is missing:

| Missing element | Why it matters |
|---|---|
| No live mechanism | Compactness is terminal post-process. A reviewer will ask "so what's the actual algorithmic contribution?" — the answer is "we found a zero-cost thing you can do on the output." That's thin. |
| Anti-dynamic axis is exhausted | All live anti-dynamic mechanisms are dead. The backbone's core novelty is masked dynamic handling, but (1) deferred lost, (2) admission control was the wrong tool, (3) free-space family is dead. The contribution is "we used GT masks well" — which is a baseline engineering fact, not a paper. |
| ATE ≠ SOTA | 3 cm class on walk_xyz, 10 cm on person pair. RGD-SLAM is 2.26–2.45 cm. The gap is a BA-backend gap, confirmed triple. You are not beating the ceiling. |
| No competitor on N × PSNR Pareto | (addressed in Q5 — we are not actually on the frontier) |

**Minimum additional experiment set to make it defensible:**
1. **Full 18-seq × 3-seed breadth table** for ATE + PSNR + N on the base prune arm. Convert "4 dynamic sequences" into a full comparison against all 11 competitors. This is the single biggest credibility multiplier — without it, a reviewer can always say "the method only works on your hand-picked 4 seqs."
2. **Terminal compression on the full table**: apply op<0.01 to all 18×3 runs and report N and dPSNR. This makes the compactness claim a full-dataset fact rather than a 4-seq anecdote.
3. **Do NOT claim Pareto efficiency** without doing the domination analysis formally (Q5).

The title/claim that is defensible with this set: *"Terminal Opacity Pruning: A Zero-Cost Map Compactor for Dynamic-Scene 3DGS SLAM."* One clean mechanism, reproducible, dynamics-agnostic, free for tracking. That is a paper — a short, honest one. Whether it is a *good* paper depends on the venue.

---

## Q2: Is the item-5 contradiction-counting gate distinct from vac_excess? (THE PIVOTAL TEST)

**Mechanically: NO.** The vac_excess probe killed the *forward claim* of the free-space family (L_freespace penalises vacated and never-dynamic identically — negative or ≈0 on all 4 seqs). Item-5's reopened gate is the *reverse claim* (cross-KF contradicted Gaussians cluster in vacated regions). The two are the same causal hypothesis with opposite polarity. The vac_excess measurement is the discriminating experiment for both.

**Why the circularity matters:** The contradiction counter in `deferred_commit.py` only increments on *pending candidates* — Gaussians that passed warm-up and are awaiting promotion. Map Gaussians that were never candidates in the deferred arm have no recorded contradiction counts. Evicting by contradiction therefore only reaches Gaussians that were already good enough to be candidates — the selection effect means the mechanism is pre-filtered to non-ghosts. To test whether contradiction-counting as an eviction discriminant is distinct from vac_excess, you must count contradictions on ALL map Gaussians, not just the candidate sub-population.

**The discriminating zero-GPU test (reads saved artifacts, ~2 h of CPU time):**

**Artifact:** `final_after_opt.ply` + `trj_full_final/traj_full.csv` from each P2-T prune seed-0 run.

**Computation:**
1. Load PLY Gaussian positions/shapes.
2. For each keyframe camera, project all map Gaussians, compute depth delta vs observed depth, increment a per-Gaussian contradiction counter **for every map Gaussian** (not just candidates), gated by the same depth_abs/rel thresholds as `deferred_commit.py:505`.
3. At sequence end: `vac_excess_gauss = P(contradicted | vacated) − P(contradicted | never-dynamic)`.
4. Also report `contradiction_p50` and `contradiction_p90` of the contradicted sub-population.

**Pass/Fail:**
- `vac_excess_gauss > +0.05` on ≥3/4 sequences AND contradicted Gaussians have `op_p50 ≥ 0.5` → mechanism is real, proceed to online probe.
- `vac_excess_gauss ≈ 0` or negative on ≥3/4 sequences → mechanism is the same signal as vac_excess, **closed without GPU**.

**Expected outcome based on existing evidence:** vac_excess was ≈0 for balloon (+0.017), mv_no_box (−0.236), pt2 (−0.176) at the pixel level. The Gaussian-level test will return the same result — the signal was not hidden at finer granularity; it is simply not there. The one false positive (pt1 +0.281) was driven entirely by the last 250 frames where vacated grew to the whole screen. Any Gaussian-level test on pt1 will reproduce the same collapse when frames are windowed.

**Action: Run the test before spending one minute of GPU. If it returns vac_excess ≈ 0, close item-5 and redirect GPU to Q3 priority (c).**

The probe script would be a variant of `stage0_eviction_probe.py` that adds the per-Gaussian contradiction counter to the existing frame loop.

---

## Q3: GPU allocation ranking

| Priority | Candidate | Justification | Estimated cost |
|---|---|---|---|
| **1 (immediate)** | **(c) Breadth — 18-seq × 3-seed full table** | Converts the existing positive set from "4 seqs" to "full benchmark." No new mechanism risk. The terminal compression finding (A) only becomes a paper claim when it covers the full competitor set. Every other candidate risks GPU with no guaranteed paper payoff. | ~18 seqs × 3 seeds × ~2 h = **108 h on 3090**, or ~270 h on 2060. If 3090 is available, this is the obvious use. |
| **2 (after breadth)** | **(b) Reliability-weighted DBA geometric oracle** | The geometric term of the DBA objective has **never used reliability weights** — this is the genuinely non-redundant signal identified in the document. Photo-only DBA failed (−0.63 → +9.60 cm ATE) because it was redundant with existing online photometric weights. The geometric term is a different signal channel. If it improves ATE on the person pair (the hardest axis), it attacks the gap to RGD. | ~4 seqs × 1 seed for smoke test. |
| **3 (conditional)** | **(e) Final-pass compression pulse** | STEP4's online compress failed (ADC regrows the tail) but its NOT-SETTLED section noted: a *single terminal compression pulse at the last map step* decouples from the densify cadence. This is essentially running `mc_terminal_comp_3seed.py` as an *in-SLAM* final step, not as a post-process. If run live at the very end (after final densify, before photometric refinement), it would be a **live mechanism that doesn't fight the ADC steady-state**. This converts (A) from "post-process" to "terminal live step" — a meaningful distinction for a reviewer who asks "why not just do it offline?" | ~4 seqs × 1 seed. |
| **Dead** | **(a) Swap-the-gate contradiction eviction** | Dead per Q2 analysis. Vac_excess is the discriminating experiment and it returned ≈0. The contradiction counter has circularity (only reaches candidate sub-population). No GPU. | 0 h |
| **Not now** | **(d) 2B live density control** | High risk of S6's degenerate lifecycle. Only pursue if the paper framing specifically requires a *live* (not terminal) compactness contribution and (e) was tried and failed. | — |

**Bottom line:** Put the 3090 on (c). While it runs, write the zero-GPU probe for Q2 and the geometric oracle spec for (b).

---

## Q4: Strongest paper framing

The spine is **terminal compression as a validated, dynamics-agnostic map compactor** — not anti-dynamic, not mechanism, not ATE.

**Why this framing holds:**

1. It is honest: the anti-dynamic search was exhaustive and the live mechanisms are dead. Framing the paper around what *failed* is a non-starter.
2. It is real: 12/12 runs, 3 seeds, 4 seqs. Replicable. Not a single-seed fluke.
3. It is independent: the removal axis is orthogonal to the anti-dynamic axis — a reviewer cannot attack it with "your method only works because you mask dynamics better" because (C) shows the removables are equally distributed across static and dynamic regions.
4. It is new as a claim: terminal low-opacity pruning as a standard post-process for 3DGS-SLAM has not been formalised. You can frame it as "we characterise the opacity→contribution map of a dynamic-scene 3DGS-SLAM and show that op<0.01 is a safe deletion threshold across sequences."
5. It is falsifiable and has been falsified at op<0.05 (balloon seed-1 breaks). That is a strength, not a weakness — it shows you did the boundary finding.

**What to drop from the framing:**
- Do not claim "live compactness mechanism" — it is false.
- Do not claim Pareto efficiency without formal domination analysis (see Q5).
- Do not claim deferred is better than prune — deferred lost on 6/6 sequences for ATE and render.

**What the paper actually contributes:**
1. A methodology for characterising the safe deletion frontier of a 3DGS-SLAM map (opacity thresholds + PSNR degradation curves + dynamics agnosticity probe).
2. A reproducible finding: op<0.01 removes 9–16% of Gaussians with ≤0.0001 dB PSNR cost across seeds and sequences.
3. Proof that deletion is tracking-safe (ATE within base band on 4/4 seqs).
4. A full-benchmark table (after (c) runs) positioning the method among 11 competitors.

This is a **characterisation paper with a validated finding** — honest, reproducible, narrow. Whether it clears a venue threshold depends on the venue. If the target is a mid-tier conference, it may pass. If the target is CVPR/ICRA spotlight, it is thin.

---

## Q5: The weakest link and the cheapest breaking/hardening experiment

**The weakest link is the Pareto efficiency claim (D).**

The document says "our deferred arm sits ON the Pareto frontier" and gives mv_no_box as the example: 31.6k / 24.4 dB / 2.5 cm ATE vs SplaTAM 558k / 23.0 / 37.4. The implied claim is that no other method simultaneously dominates us on all three axes.

**But on balloon, pt1, and pt2, RGD-SLAM dominates us on all three axes.** Let me check the pareto_data.json numbers:

| seq | RGD N | RGD PSNR | RGD ATE | Ours N | Ours PSNR | Ours ATE |
|---|---|---|---|---|---|---|
| balloon | 9.6k | 25.14 | 2.45 | 39.8k | 21.6 | 2.87 |
| pt1 | 17.9k | 24.11 | 7.21 | 49.8k | 22.2 | 11.0 |
| pt2 | 15.5k | 22.76 | 20.1 | 69.6k | 22.0 | 10.2 |
| mv_no_box | 10.6k | 24.45 | 2.28 | 31.6k | 24.4 | 2.50 |

On balloon: RGD has 4× fewer Gaussians, +3.5 dB PSNR, and better ATE. **We are strictly dominated.**

On pt1: RGD has 2.8× fewer Gaussians, +1.9 dB PSNR, and 1.5× better ATE. **We are strictly dominated.**

On pt2: RGD has 4.5× fewer Gaussians, +0.8 dB PSNR, and 2× worse ATE. **Here we are better on ATE but worse on N and PSNR.** Neither dominates — but we are not *Pareto efficient* either; we are just worse on two axes.

The "1/18 SplaTAM's N at competitive PSNR" claim is factually correct but strategically weak: SplaTAM is 37 cm ATE on mv_no_box and 133 cm on pt2 — it is essentially broken on dynamic sequences. Beating a method that fails on ATE is not a competitive proof.

**The cheapest hardening experiment — formalise the Pareto claim or abandon it:**

**Artifact:** `final_after_opt.ply` for deferred arm (mv_no_box, balloon), `pareto_data.json`.

**Computation:** For each sequence, compute the convex Pareto frontier over all methods that have all three metrics (N, PSNR, ATE). Check whether any method strictly dominates ours or whether ours strictly dominates any method.

**Pass:** Ours is on the Pareto frontier and no method strictly dominates us on ≥2 seqs → keep the Pareto framing.
**Fail:** A method strictly dominates us on ≥2 seqs (RGD dominates on balloon and pt1) → drop the Pareto efficiency claim, replace with: "competitive full-frame PSNR at significantly lower Gaussian count than SplaTAM/DynaGSLAM, with ATE competitive with DG-SLAM and NGD-SLAM on dynamic sequences."

**This is a 30-minute offline computation, zero GPU, that either hardens or removes the most vulnerable claim in the paper.**

The second-weakest link is the **dynamics-agnostic claim** (C): vac_excess ≈ 0 was measured on the op<0.05 set across 4 sequences. The op<0.01 safe set has a different opacity distribution — a reviewer could ask "did you measure vac_excess specifically on the op<0.01 removable set?" You did not; the 3-seed probe (STEP1) reported vac_excess for op<0.05. The op<0.01 set is a subset. Re-run the vac_excess computation specifically on the op<0.01 removable subset (using `mc_terminal_comp_3seed.py`'s per-run output directories that already exist) and confirm vac_excess_01 < 0.05 band — if it holds, the claim is hardened. If it does not, the dynamics-agnostic framing needs qualification.
