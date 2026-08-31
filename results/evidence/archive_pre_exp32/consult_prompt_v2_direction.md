# Consultation: how to convert an exhausted mechanism search into a publishable paper

You are advising on a research-direction decision for a dynamic-scene 3D Gaussian
Splatting SLAM project. The deadline pressure is OFF (the 08-16 DDL was abandoned;
we now target the next submission window). Time is not the binding constraint —
**being right about the direction is.** GPU is 1× RTX 2060 (6GB, sufficient: peak
4.09GB) plus a 3090 available; ~3 hours per live SLAM run.

Answer the QUESTIONS at the bottom. Be concrete and adversarial. If you think the
honest answer is "the current result set cannot carry a paper", say so plainly and
say what the cheapest decisive experiment would be.

---

## 1. The system

- **Scaffold**: MonoGS (public 3DGS SLAM). Not treated as a baseline — it's the carrier.
- **Our backbone ("mask-both")**: mask_mapping + mask_insertion (GT/segmentation dynamic
  masks applied to BOTH the mapping loss and the Gaussian insertion path) + RobustTracking
  + DynamicKeyframe(gap_cap=5) + ReliabilitySignal. RGB-D.
- **Two arms, sole difference = `Mapping.lifecycle_mode`**:
  - `prune` (control) = insert-then-prune: insert candidates immediately, delete by lineage.
    This is a faithful reproduction of competitor "Type-B" lifecycle.
  - `deferred` (candidate) = deferred pre-instantiation: hold candidates out of the map,
    promote only after cross-frame confirmation that they are static.
- **Metrics protocol** (hard-won, do not violate):
  - ATE := `tracking_raw.csv['ate_rmse_cm']`, full-trajectory, evo SE(3)-Umeyama
    alignment (`monocular=False`). NOT keyframe RMSE, NOT KF0-gauge camera-center
    RMSE (that flips the sign of degradations), NOT Sim(3) for RGB-D.
  - Render := offline re-render of the saved `final_after_opt` PLY at the saved
    `trj_full_final` poses, full-frame PSNR/SSIM/LPIPS/depth.
  - Compactness := `refined_num_gaussians` (final map Gaussian count N).
  - Cross-campaign ratio drift is ~30% (measured +21%/+29%/−23%) ⇒ a cross-campaign
    ratio difference under 30% is NOT evidence.
  - Never render a verdict on a single seed (a 1-seed result already flipped a verdict
    in both directions once).
  - Verdicts are per-sequence — the compactness axis flips across sequences
    (balloon 0.511× vs pt2 1.069×).

## 2. Sequences and competitor field

Dynamic sequences in active use: `balloon`, `mv_no_box` (Bonn), `pt1`/`pt2`
(= person_tracking / person_tracking2, the hard pair). Full bench is 18 sequences
(3 static TUM + 7 dynamic TUM + 8 Bonn dynamic).

11 external competitors × 18 seqs × 3 seeds of tracking data are in hand.
**8/11 also have full-frame PSNR and Gaussian count N** (an earlier belief that
"competitors have no rendering data" was verified WRONG).
Competitors: Co-SLAM, DG-SLAM, DynaGSLAM, DynaSLAM, MonoGS, NGD-SLAM, ORB_SLAM3,
RGD-SLAM, RoDyn-SLAM, SplaTAM, WildGS-SLAM.

**ATE tier reality**: ours ≈3cm on walk_xyz-class, ≈10cm on the person pair.
That is "published-tier but not SOTA". RGD-SLAM gets 2.26-2.45cm on balloon and
is the ONLY method that suppresses us on all three axes on most sequences.
The 3→1.5cm gap has been triple-confirmed to be a **BA-backend gap** (we have no
bundle-adjustment backend of that class), not a tuning gap.

## 3. What has been KILLED, with the mechanism (do not propose these again)

Each of these has measurements behind it, mostly zero-GPU offline probes:

1. **`deferred` does not beat `prune`.** ATE: deferred worse on 6/6 sequences
   (balloon 3.07 vs 3.11, mv_no_box 2.58 vs 2.87, pt2 10.35 vs 16.80 — note mixed).
   Full-frame render: deferred loses or ties on 6/6. Compactness: deferred is smaller,
   but see (2).
2. **The `deferred` compactness is UNDER-SEEDING, not filtering.** Read the 36-run
   ledger (`deferred_commit_summary.json`): the two arms have nearly IDENTICAL
   `rejected`/`expired` counts (same decision engine). The real difference is an
   undeclared third gate, `_dedup_promotion_candidates`, which discards 80-89% of
   promotions (α≥0.8 and depth agrees ⇒ drop). deferred therefore inserts ~1/10 of
   what prune inserts. So "deferred filters dynamics more cleanly" is measurably FALSE.
3. **Admission control is the structurally wrong tool for the dominant failure mode.**
   Candidate composition: `background_reveal` : `foreground_conflict` = 1.7-3.8×
   (balloon 286,579 : 148,421; pt2 447,911 : 117,089). background_reveal means the
   contamination is ALREADY in the map — refusing admission cannot undo what was
   already admitted, and it postpones the only repair.
4. **Mechanism authority is tiny**: `max_candidates_per_keyframe=5000` vs 5.0M-13.0M
   conflict pixels per run ⇒ the mechanism touches only 4-8%; the rest is discarded by
   BOTH arms. Worse, the subsample is `np.linspace` over raster order = spatial
   striping, i.e. biased.
5. **α exit/fill (EMA-alpha carve) is dead as an APPARATUS, not as a class.** Forensic
   console ledger: carve fired **0 times, ever**. With α starting at 0.7 and β=0.9,
   dropping below `τ_carve=0.20` needs n≥12 contradictions (0.7×0.9^11=0.2196>0.20),
   but `obs_max` over the entire sequence only reaches 11, and `a_lt_carve=0` at every
   keyframe. **The gate was mathematically unreachable within sequence length.** The
   same ledger records `geom_front`=1554-5787 per keyframe (i.e. there IS abundant
   geometric front-evidence). The user explicitly ruled on 2026-08-05 that this may be
   **reopened as "swap the gate"** (integer cross-KF contradiction counting +
   reliability gating, replacing EMA-alpha).
6. **observation-contradicted eviction: DEAD (empirical, Stage 0).** Built a
   bias-cancelling discriminant `vac_excess = P(violation | vacated region) −
   P(violation | never-dynamic static control)`. Four sequences, prune seed-0:
   balloon +0.017, mv_no_box −0.236, pt1 +0.281, pt2 −0.176. The one positive (pt1)
   is an artifact — frame-windowed analysis shows it is driven entirely by the last
   ~250 frames where the vacated region swells to cover the screen and eats the
   base-rate control; its twin sequence pt2 is negative on 95/114 frames. Two person
   sequences with opposite signs ⇒ no cross-sequence reproducible swept-ghost signal.
   Also fixed a real rasterizer bug on the way (`forward.cu` depth was un-normalised,
   `D+=depth·α·T` without dividing by Σα·T, making semi-transparent pixels
   artificially shallow); normalising to `D/(1−T)` moved v_ratio only 0.378→0.375,
   so the bug was not the driver.
   ⇒ **Free-space family fully excluded on this backbone, BOTH directions**: the
   reverse direction (post-hoc per-pixel free-space violation ⇒ evict live Gaussians)
   AND the forward direction (add an `L_freespace` term to the mapping loss) both
   measure ≈0 or negative. Note this is a genuine literature gap (MonoGS §3.3.3 states
   rasterisation puts no constraint along the ray direction; NeRF-SLAM has L_fs, 3DGS
   SLAM does not) — but empirically the violation signal is global pose/render bias.
7. **DBAphoto (reliability-weighted photometric BA)**: minimising the objective actively
   pushed the trajectory AWAY from GT (ATE 3.03 → 12.63 cm). Clean NO-GO.
   Sub-note: reliability weights are ALREADY applied online to both RGB and depth loss
   (`static_conf = 1 − strength·d_soft`), so an offline photometric BA reusing the same
   w is a redundant signal. The genuinely non-redundant hole is **weighting the DBA
   GEOMETRIC term by reliability** (the geometric term has never used reliability).
   A "weighted-geometric oracle" was specced but sits at the BOTTOM of the GPU queue.
8. **ReliableTracking (RT)**: on the mask-both backbone it is +1.2% flat (inside P2-T
   standard deviation) — subsumed redundantly by mask_mapping + mask_insertion.
   Main table has RT OFF. Its remaining legitimate use is as a sufficiency ablation.
9. **CoarsePoseInit (const_vel)**: positive-feedback drift on long sequences
   (f2_xyz frame 1546 → 15.4cm). Falsified, default-off. Root cause: a weak photometric
   refiner cannot cancel a re-extrapolated drift velocity, so it becomes an integrator.
   Masked on dynamic sequences (which is why it "looked fine" in V1).
10. **FullFramePose**: f3_wk_xyz +41.3%, f2 timeout. NEGATIVE.
11. **masked_icp**: no stable gain. default-off.
12. **S6_maxpress killed the compactness headline as a standalone claim.** prune arm +
    three knobs (`ttl_keyframes=1` + `gaussian_th=0.9` + `densify_grad=5e-4`) compresses
    to 0.81×B, reproduced 3/3 across two campaigns, with two fidelity metrics in band.
    BUT `ttl=1` makes the prune arm `promoted=0` and residual 23927→5000 = a
    **degenerate lifecycle**; and `gth` contributes 0.99× to the rate (i.e. nothing).
    ⇒ Combined with (2): both compactness channels are fake. S6 wins by degenerate
    lifecycle, deferred wins by dedup under-seeding. NEITHER is "filtering dynamics".
13. **STEP4 online per-window compression: DEAD BY MECHANISM.** Deleting low-opacity
    floaters inside the live loop after `densify_and_prune`. ATE was SAFE (4/4 within
    base band or better — a real, useful negative-cost finding), but compactness did not
    materialise: balloon −17.5%, mv_no_box −18.1%, **pt1 +22.3%, pt2 +44.4%**.
    A mechanism probe then confirmed the root cause directly: the compress runs' FINAL
    map has essentially the SAME low-opacity tail as base (mv/pt1 flat, balloon still
    17.5% low-opacity), even though the online deletion removed 2-12× the final N over
    the run. ⇒ **The ADC (adaptive density control: densify clone/split) REGROWS the
    low-opacity tail.** The terminal floater population is a steady-state of the adaptive
    density process, not a one-time accumulation. Online compression can never outrun
    densify. Closed, no lead retained.
14. **2B (budget-bound online density control)**: the only remaining live-loop compactness
    lever, but both the ledger and the probe say it fights the ADC steady-state ⇒ high
    risk of recreating S6's degenerate lifecycle. Recommended NOT to pursue unless the
    paper specifically requires a *live* compactness mechanism.
15. **P1-CENSUS (lineage accounting)**: the ledger in (2) already answers it in advance.
    Running it would just re-derive the same answer.
16. **H-D hybrid**: landed INDETERMINATE in P2-T; needs a new apparatus (matched KF +
    regime-specific null) and coverage is collinear with tracking-difficulty. Next paper.

Also: `if to_prune is not None and self.monocular` (`slam_backend.py:457`) is verbatim
upstream MonoGS ⇒ **co-visibility eviction NEVER executes under RGB-D**; the only
eviction is opacity culling. And `Training.gaussian_th: 0.7` IS the `min_opacity` of
`densify_and_prune`, run every 150 mapping iterations (original 3DGS uses 0.005);
raising it to 0.9 drops only 1% of Gaussians ⇒ **~99% of Gaussians have opacity ≥ 0.9,
the map is essentially fully opaque.** Consequence: the 1,500-5,800 per-KF Gaussians
standing in front of observations in the α-carve ledger are NOT low-opacity floaters —
they are real, rendering, occluding solids (N≈15k, so 10-35% of the map), and NO
mechanism currently removes them.

## 4. What SURVIVED — the positive result set

**(A) Terminal compression at op<0.01 is real and replicable.** 12/12 runs
(4 seqs × 3 seeds, base prune), offline zero-training: load `final_after_opt` PLY,
delete sigmoid-opacity < threshold, re-render at saved poses, interval-5 full-frame PSNR.

| seq | op<0.01 removal (3-seed mean) | dPSNR |
|---|---|---|
| balloon   | 16.2% (12.8/18.4/17.3) | ≤ 0.0001 dB, all 3 |
| mv_no_box |  9.4% (9.9/8.4/10.0)   | ≤ 0.0001 dB, all 3 |
| pt1       | 10.1% (9.9/10.1/10.3)  | ≤ 0.0001 dB, all 3 |
| pt2       | 13.4% (18.4/11.2/10.5) | ≤ 0.0001 dB, all 3 |

**op<0.05 is NOT a safe band** — balloon seed-1 breaks at −0.087 dB (the earlier
seed-0-only claim of ≤0.016 dB does not survive across seeds). Paper may use
op<0.01 (or 0.02) only.

**(B) Deletion is NEGATIVE-COST for tracking.** The STEP4 compress runs' ATE landed
inside the base 3-seed band on 3/4 sequences and better on the person pair
(pt1 11.01→10.62, pt2 10.23→9.37). Removing low-opacity floaters does not disturb
the tracking gradient. Render likewise: balloon −0.062, mv_no_box **+0.038**,
pt1 **+0.212** dB (pt1's gain suggests removing floaters lets the optimiser
redistribute capacity onto kept surface — a positive effect).

**(C) The removable set's identity is now pinned down (3 zero-GPU probes).**
- footprint-only deletion is UNSTABLE (`footprint<0.02m`: balloon −0.53, mv_no_box
  **−1.62**, pt1 −0.91, pt2 −1.37 dB) — small-scale Gaussians do carry surface detail
  on some sequences.
- The JOINT gate (op<0.10 ∧ max-axis<0.02m) is uniformly cheap (6-14% / ≤0.01 dB).
- **"Removables are far from the visible surface" is FALSIFIED**: using each run's
  `geometry/tsdf_mesh.ply` (voxel 0.02m) as the visible surface and KD-tree distance,
  the op<0.05 removable subset and the full Gaussian population have COMPLETELY
  OVERLAPPING distance distributions (p50 ≈ 0.1cm, mean ≈ 0.1cm, all 4 seqs).
  ⇒ Removable floaters are semi-transparent fragments EMBEDDED IN real surfaces,
  not a deep-interior / outside-zero-crossing fill layer. distance-to-surface cannot
  separate them.
- **Removables are dynamics-agnostic**: vac_excess ≈ 0 (−0.003 to +0.024) ⇒ removables
  are distributed uniformly across dynamic and never-dynamic regions. The compression
  lever is therefore INDEPENDENT of the anti-dynamic axis (no cross-contamination),
  and the low-opacity axis is a pure output-contribution axis requiring no geometric
  assumption (no TSDF, no masks needed).

**(D) Pareto positioning exists and is favourable on the N × PSNR axis.**
On `mv_no_box` our `deferred` arm sits ON the Pareto frontier: 31.6k Gaussians,
24.4 dB, 2.5 cm ATE — that is ~1/18 the Gaussian count of SplaTAM at HIGHER PSNR
and far lower ATE (SplaTAM 22.5 dB). Frontier members per sequence:
- balloon: RGD (9.6k / 25.1 dB / 2.45cm). ours base 39.8k/21.6/2.9; deferred 19.8k/21.3/3.07
- mv_no_box: RGD (10.6k/24.5/2.28) · **ours deferred (31.6k/24.4/2.5)** · DynaGSLAM (7.4k/13.7/12.1)
- pt1: RGD (17.5k/24.1/8.6). ours base 55.6k/22.3/11.0
- pt2: RGD (13.6k/22.6/23.0). ours base 69.6k/22.0/10.2 — **our ATE is 2.3× better than
  RGD here** (10.2 vs 23.0) at 5× the Gaussians.

The honest claim is "competitive full-frame PSNR at 1/18 the Gaussian count of
SplaTAM/DynaGSLAM", NOT "beats RGD on N". RGD-SLAM remains the method to beat and
the only one that dominates us broadly.

## 5. The strategic situation

- The anti-dynamic mechanism search is **exhausted on this backbone**: admission control
  is the wrong tool (item 3), the free-space family is excluded (item 6), the candidate
  engine's design space is used up (items 2/4), and the mask-both backbone is saturated
  such that almost every online gain mechanism gets absorbed (item 8).
- The compactness axis has exactly ONE surviving real result, and it is a **terminal
  post-process** (item A), not a live mechanism. Both "live compactness" channels are
  either fake (item 12) or mechanically dead (items 13/14).
- We cannot win the ATE headline: the gap to SOTA is a BA-backend gap (triple-confirmed),
  and we have no BA backend of that class.
- Remaining explicitly-reopenable lead: **item 5's "swap the gate"** (integer cross-KF
  contradiction counting + reliability gating replacing the unreachable EMA-alpha gate),
  with the note from item 5 that `geom_front` evidence is abundant (1554-5787/KF) and the
  note from §3-end that those front-standing Gaussians are opaque solids nothing removes.
- Note the tension to resolve: item 6 killed *free-space-violation-driven* eviction using
  a per-pixel violation discriminant. Item 5's reopened gate is *observation-contradiction
  counting* on Gaussians standing in front of observations. Are these the same claim
  wearing different clothes, or genuinely different signals? A sharp answer here decides
  whether the last lead is real or already refuted.

## QUESTIONS

1. **Is the surviving result set (A+B+C+D) enough for a paper on its own?** Be blunt.
   A 9-16% terminal shrink at ~0 dB, plus deletion-is-free-for-tracking, plus a Pareto
   position that is "1/18 of SplaTAM's N at competitive PSNR" but does not beat RGD.
   If yes, what is the honest title/claim and what is the minimum additional experiment
   set to make it defensible to a reviewer? If no, what specifically is missing?

2. **Resolve the §5 tension.** Is "integer cross-KF contradiction counting + reliability
   gating" (item 5, reopened) genuinely distinct from the free-space eviction that item 6
   killed, or is it the same signal that vac_excess already refuted? Give the discriminating
   test — ideally a zero-GPU offline probe on already-saved artifacts — that settles it
   BEFORE any GPU is spent. If it is the same claim, say so and close it.

3. **Where should the next GPU cycles go?** Rank the candidates and justify:
   (a) swap-the-gate contradiction eviction (item 5);
   (b) reliability-weighted DBA *geometric* term oracle (item 7's non-redundant hole);
   (c) breadth — take the existing frozen method to the full 18-sequence × 3-seed table
       to convert "4 dynamic sequences" into a complete competitor comparison;
   (d) 2B live density control (currently advised against);
   (e) something we have not considered.
   Consider that (c) buys no new mechanism but may be exactly what converts the existing
   positive set into a submittable paper.

4. **What is the strongest paper framing available given all constraints?** Specifically:
   can "mask-both backbone + terminal compression + Pareto efficiency" carry a venue
   submission when the ATE is published-tier-but-not-SOTA and the compactness mechanism
   is a post-process rather than a live contribution? If the framing needs a different
   spine, propose it.

5. **What are we fooling ourselves about?** Name the weakest link in the surviving
   positive set — the claim most likely to collapse under a reviewer's or a skeptic's
   scrutiny — and the cheapest experiment that would either break it now or harden it.
