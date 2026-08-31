# R2-P04-MASKRATE — the hard-mask comparator the compactness claim never had

> **§1–§3 are a PRE-RUN declaration, committed before the first GPU run.** §4 is written after.
> A result may not be given its meaning after it has been seen.
>
> Campaign: `R2-P04-MASKRATE` · 3 arms × 3 seeds = **9 runs** (~2 h on the 2060)
> Sequence: `bonn/rgbd_bonn_balloon`, frozen RGD trajectory, ATE pinned 2.0618 cm
> Runner `scripts/r2_p04_maskrate.py` · readout `scripts/r2_p04_maskrate_readout.py`
> Contract `tests/test_r2_p04_maskrate_configs.py` (10 tests, E0 green)
> Status: ✅ **DONE 2026-07-31 — 9/9 exit 0, ~2.0 h, all gates green (G5 both polarities).**
> Verdict = **M2, inside the rate noise band** (M 1.11×B, +0.60× own sd, per-seed 1/3 below,
> **KF 19/19/19 on all three arms**). See §4.
>
> Post-hoc and non-preregistered, like the three P0.x campaigns. It does **not** join the
> pre-declared ladder and does **not** alter the R2-P02 H1 three-gate record. Only the decision
> criteria are inherited, **by import** from `scripts/r2_p03_sweep_readout.py`.
> **GO/KILL and narrative remain the user's** (prereg §9).

## §1 Why this campaign exists

External review raised a structural objection to the project's compactness claim: a hard
semantic mask is a strict **subset** of what the deferred arm admits — a masked pixel never even
becomes a candidate — so a mask-blocking competitor's map should be **no larger** than arm B's,
and plausibly smaller. If that holds, "deferred is more compact" is a statement about
insert-then-prune specifically, not about dynamic-SLAM map admission in general.

**The objection does not touch any existing verdict, and the reason is checkable rather than
rhetorical: no arm in the 46 accounted runs of R2-P03 ever enabled `SemanticMask`.** SWEEP,
DECOMP and S6REPL all descend from `oracle_{prune,deferred}_balloon.yaml`, whose resolved config
carries `SemanticMask.enabled: false` — pinned by
`test_both_anchors_have_the_mask_off`, so this is an apparatus fact under test, not a claim in
prose. The −55% compactness result is therefore a measurement against insert-then-prune, and the
hard-mask comparison is one this project **has never made and never claimed**.

That makes the objection a correct forward-looking warning rather than a refutation, and it is
cheap to convert into a measurement: the mask arm is config-only on this stack (the mechanism
already exists as `SemanticMask.mask_insertion`), the Mask R-CNN weights are cached locally, and
the campaign is ~2 h. Answering it ourselves, before a reviewer raises it, is worth 9 runs.

Two facts about scope, stated up front because they bound what the campaign can be used for:

- **The mask arm is not RGD-SLAM.** It is *this* repo's Mask R-CNN person mask, which is weaker
  than RGD's OneFormer+EKF. What transfers is the mechanism (hard blocking at insertion), not the
  detector quality. So a result here constrains the *class* of mask-blocking methods; it is not a
  head-to-head against a specific published system.
- **Under the frozen trajectory the tracking-side use of the mask is inert** (the oracle pose
  replaces the Adam refine), so what is actually exercised is `mask_mapping` (mapping loss) +
  `mask_insertion` (person depth zeroed → no dynamic Gaussians). That is the correct isolation
  for a *map-admission* question and it is also a limitation: this campaign says nothing about
  what a hard mask does for tracking.

## §2 The one question, and the three readings fixed in advance

**Q — Does `M_mask` reach `B_deferred`'s mean Gaussian count?**

Rate axis `refined_num_gaussians`; decision metrics and margins **imported** from
`scripts/r2_p03_sweep_readout.py` (`static_vacated_depth_l1_pen_cm` ≤ **1.56 cm**,
`static_vacated_psnr` ≤ **0.28 dB**) — byte-for-byte the rule that judged SWEEP, DECOMP and
S6REPL. Both anchors are re-run in-campaign, because ratios on this stack drift up to **~30%**
(measured: +21% / +29% / −23%).

| branch | condition | what it means, decided now |
|---|---|---|
| **M1** | M's rate ≤ B's mean, per-seed 3/3 | **The review's prediction holds.** The paper must scope the compactness claim explicitly to insert-then-prune and report the hard-mask comparator as **our own measured limitation**. This is the expected outcome. |
| **M2** | \|Δ\| ≤ 2× the larger own sd, or the mean reaches B but per-seed sign splits | **Inside the rate noise band.** The two admission strategies land on the same budget by different routes. Compactness stops being a differentiator vs hard masking; it remains one vs insert-then-prune. |
| **M3** | M's rate > B's mean | **The prediction fails.** Strongest outcome for the project — and precisely because it is surprising, it **may not be written as a win without the keyframe column** (see below). |

**The keyframe guard on M3, pre-committed.** A hard mask changes covisibility, so it can change
how many keyframes the run keeps, and a rate difference across different keyframe counts is not
a same-budget comparison. SWEEP's S6 already cost this project that lesson (KF 18/18/16 <
19/19/19, a caveat that must be co-cited wherever 0.81× appears). So under M3: if M's keyframe
count differs from B's on any seed, the honest statement is "M's map is larger, with coverage
differing by *k* keyframes" — never "the subset argument is wrong" full stop.

**Fidelity is read in every branch.** Reaching B's rate is only interesting if it was not paid
for in fidelity; "reached the budget but broke a margin" is a different result from "reached it
cleanly", and the imported dominance rule prints both. A rate number without its fidelity
columns is not a result here.

**Per-seed sign is a hard requirement** (any seed flipping ⇒ read as inside the band), the
denominator is the larger of the two arms' own sd, and 3-seed sd carries 2 df ⇒ intervals are
crude, not significance claims.

## §3 What this campaign CANNOT say — declared in advance

**It cannot measure recovery.** The original design for this campaign was a 4-arm test including
`mask + deferred`, to ask whether deferred confirmation can restore static background that the
mask blocked by mistake. **The code forbids it, so that arm was removed before any run.** The
trace:

1. `utils/slam_frontend.py:299,309` — `apply_semantic_insertion_gate` sets
   `initial_depth[person_mask] = 0` inside `add_new_keyframe`.
2. `utils/slam_frontend.py:1881-1893` — that same array is passed as `insertion_depth` into
   `DeferredCommitManager.process_keyframe`.
3. `utils/deferred_commit.py:325` — `_classify_new_keyframe` computes
   `valid = isfinite(observed) & (observed > 0.01)`; the zeroed pixels fail it, so they fall
   outside `static_valid` and outside `uncertain` — and `uncertain` is the **only** set that
   `_add_typed_batch` ever turns into a candidate batch (`:347`).
4. `utils/static_evidence.py:137-138` — independently, `static_valid = valid & (~semantic)`, so
   even with depth intact a `dynamic_mask` pixel can never be classified `uncertain`.

Masked pixels are excluded twice over, upstream of candidacy. A `mask + deferred` arm would
therefore report **~0 recovery by construction** — an apparatus artifact masquerading as a null
result, which is exactly the failure mode the S6 single-seed episode already cost this project
once. Making recovery measurable requires a quarantine-instead-of-discard code path (route mask
pixels into the candidate queue instead of zeroing them). That is a **new mechanism**, not a
config overlay, and it needs its own pre-registration.

Consequence for the narrative, fixed now: **"deferred recovers what a hard mask discards" may
not be written from this campaign in any branch.** What may be written is the structural
statement — a hard mask discards masked pixels before candidacy, so recovery is impossible for
it *by construction* — because that is a code fact, plus whatever §4's rate result licenses.

The offline anchor `scripts/r2_p04_mask_fp_anchor.py` (zero GPU, no SLAM) sizes what such a
mechanism could ever recover, by comparing the mask arm's own detector against the frozen
`dynamic_mask_gtmc` oracle. It is **descriptive and non-preregistered**: it measures the dataset
and the detector, not any arm, and it decides nothing on its own — its purpose is to let the
quarantine mechanism be costed before it is built.

**It has been run (2026-07-31, 438 frames, balloon).** Of the static support set the decision
metrics are scored over, the mask blocks **10.07%** that GTMC calls static; restricted to pixels
where the mover was not flagged within ±15 frames — the part that is plausibly recoverable
rather than a GTMC still-mover under-flag — **2.63%**. That number is window-dependent
(**5.59% / 2.63% / 1.47%** at ±5 / ±15 / ±30) and is reported only with its sensitivity.

Two apparatus notes recorded there, both of which bound how hard this number may be leaned on:
the sequence-wide GTMC union **saturates at 91.3% of the image** on balloon, so the obvious
global discriminator returns ~0% for a geometric reason and must not be quoted as a recovery
ceiling (`utils/eval_utils.py` documents the same saturation for the pre-registered vacated
mask); and pixels are not Gaussians, since insertion downsamples and a blocked pixel adjacent to
an admitted one may cost no coverage. Treat 2.63% as an order of magnitude for a go/no-go, not
as a predicted fidelity delta. Full caveats: `results/evidence/r2_p04_mask_fp_anchor.md`.

**Also deliberately absent:** no R2-P03 pressure knob appears here. `ttl_keyframes`,
`gaussian_th`, `densify_grad_threshold` and the candidate cap all sit at their defaults on every
arm (pinned by `test_the_admission_knobs_are_at_their_defaults_on_every_arm`), so the mask is the
only variable and this campaign does not re-open the S6 attribution that S6REPL closed. And
there is **no cross-sequence arm**: one sequence, one frozen trajectory, PSNR ≈ 14.5 regime.
Whatever §4 finds, it is a balloon result.

## §3.1 Arms and apparatus

| arm | config | role |
|---|---|---|
| `A0_prune` | `oracle_prune_balloon.yaml` (identity) | insert-then-prune control + the mask arm's base |
| `B_deferred` | `oracle_deferred_balloon.yaml` (identity) | the budget under test; in-campaign anchor |
| `M_mask` | `r2_p04_maskrate/maskrate_m_mask_balloon.yaml` (**new**) | hard mask, on arm A's lifecycle |

`M_mask`'s resolved diff vs `A0_prune` is exactly `{method} ∪ SemanticMask.*` — one mechanism.
The `SemanticMask` block is copied verbatim from the repo's existing mask-both setting
(`reference/v1/method.yaml`: maskrcnn / person / dilate 7 / both consumers) so the arm reproduces
how this repo already deploys a hard mask rather than a freshly tuned one. It is **not**
inherited from that file, and neither is `method_combined_maskboth_deferred.yaml` reused:

- `reference/v1/method.yaml` carries `CoarsePoseInit.enabled: true`, the module probe1 falsified
  (15.4 cm → 1.81 cm on removal; HANDOFF "Do Not Do" #1);
- `method_combined_maskboth_deferred.yaml` bundles `RobustTracking` + `DynamicKeyframe` +
  `Training.window_size: 12` / `pose_window: 6`, which would make the diff four mechanisms.

Both exclusions are enforced by `test_no_falsified_or_bundled_module_rides_along`.

**Gates.** G1–G4 are imported from `scripts/r2_p03_sweep.py` (exit 0 · ATE 2.0618 ± 0.02 every
run · knobs echoed by the config the run *dumped* · vacated support non-zero · rate present).
This campaign adds **G5**, which it needs and the others did not: the mask arm's own console log
must show `Semantic insertion gate ... person px zeroed`, and the anchors' must not. Without G5 a
mask arm whose mask silently resolved off is indistinguishable from a legitimate null — and the
campaign's whole question would become a null-vs-null comparison. The evaluation channel is
method-independent by construction: the frozen GTMC masks are loaded at eval time and never
written to `frame.dynamic_mask` (`utils/eval_utils.py:644-648`), so enabling the method's own
semantic mask cannot let the mask arm rescore itself on an easier support set.

Standing discipline, unchanged: new experiment ID · commit before launch and no live-code change
during the campaign (the runner refuses a dirty worktree) · 3 seeds on every arm · seed-major
order so an interrupted campaign never compares a half-finished arm against a complete one ·
compactness as ratios + in-campaign differences, cross-campaign ratios annotated ~30%.

## §4 Results

**Ran 2026-07-31, 9/9 exit 0, ~13.2 min/run (~2.0 h). All gates green.** G1 ATE = 2.0618 on
every run; G2 knobs echoed by each run's own dumped config; G3/G4 support and rate present;
**G5 both polarities** — the mask arm's console shows the insertion gate firing on 17/16/17
keyframes (855,598 person px avg, ~51.3k/kf) and **both anchors show 0 frames / 0 px**.
Full report: `results/runs/R2-P04/R2-P04-MASKRATE/maskrate_report.md`. Readout imported the
decision family from `scripts/r2_p03_sweep_readout.py`; nothing in §1–§3 was edited after launch.

**Keyframes: 19/19/19 on all three arms.** The one column §2 pre-committed as load-bearing came
back with no confound to read — the cleanest keyframe picture of any campaign in this project
(SWEEP's S6 was 18/18/16 vs 19/19/19). Whatever the rate says here, it is a same-coverage
statement.

| arm | rate (mean ± own sd) | per-seed | CV | KF | vac_depth | vac_psnr | VRAM GB | FPS |
|---|---|---|---|---|---|---|---|---|
| `A0_prune` | 26343 ± 1761 | 26829 / 24390 / 27811 | 6.7% | 19/19/19 | 37.79 ± 0.99 | 14.58 ± 0.162 | 1.024 | 7.82 |
| `B_deferred` | **12799 ± 507** | 13357 / 12367 / 12672 | **4.0%** | 19/19/19 | 36.27 ± 1.18 | 14.66 ± 0.239 | 0.828 | 8.23 |
| `M_mask` | **14253 ± 2429** | 16453 / 11646 / 14661 | **17.0%** | 19/19/19 | 35.67 ± 1.73 | 15.04 ± 0.091 | 1.667 | 3.03 |

### §4.1 The pre-declared question falls in **M2 — inside the rate noise band**

`M_mask` 14253 vs B 12799 = **1.11×B**, **+0.60× own sd**, **per-seed 1/3 below B**
(M/B = 1.232 / 0.942 / 1.157 — **the sign splits**). §2 fixed the reading in advance: a mean
that does not clear B *and* a per-seed split is M2, not M3. Per §2's own words, this means

> the two admission strategies land on the same budget by different routes. Compactness stops
> being a differentiator vs hard masking; it remains one vs insert-then-prune.

**Consequence for the paper, per §2:** the compactness claim must be **scoped explicitly to
insert-then-prune**, and the hard-mask comparator reported as **our own measured limitation** —
self-reported before a reviewer raises it. The review's directional prediction (M ≤ B) is
**not** confirmed either; the honest statement is that on this stack, at equal coverage, the two
routes are **not resolvably different on rate**.

**Fidelity was not paid for it.** Under the imported bounded non-inferiority rule, both of M's
decision metrics come back **negative = better than B**, both inside margin:
`vac_depth` **−0.602** (margin 1.56) and `vac_psnr` **−0.380** (margin 0.28). So this is
"same budget, fidelity indistinguishable-or-slightly-better", not "reached the budget by
breaking something". `A0_prune` again did not reach B's budget (2.06×B).

### §4.2 What the campaign found that the objection did not anticipate

At the same map size and same-or-better fidelity, the hard mask pays a large **in-loop** cost
that arm B does not: **FPS 3.03 vs 8.23 (2.7× slower, 24.3× own sd, 0/3)** and
**VRAM 1.667 vs 0.828 GB (2.01×, 46.2× own sd, 0/3)**. Both are the largest-effect,
most-consistent numbers in the campaign.

**The caveat that bounds this, stated with it:** this is the cost of running Mask R-CNN
**inside the loop, per keyframe**. A competitor that precomputes masks offline does not pay it
at run time — and this project's own evaluation masks (`dynamic_mask_gtmc`) are precomputed
exactly that way. So the honest claim is narrow: *a mask-blocking method that segments online
pays this; one that precomputes does not.* It may **not** be written as "hard masking is
inherently slower". Also note the frozen trajectory makes the tracking-side mask inert (§1), so
this is the mapping-side cost only.

### §4.3 B vs A0 compactness — 4th independent measurement

`B_deferred` 12799 vs `A0_prune` 26343 = **−51.4%** (0.49×), **per-seed 3/3**, both arms at
19/19/19 keyframes. Prior three campaigns: **−55.2% / −54.3% / −46.6%**. Reported as its own
in-campaign measurement, not as agreement with those (cross-campaign ratios drift ~30%).
Separately, **M is more compact than A0** (0.54×A0, −12090, 4.98× own sd, 3/3) — the mask does
real work against insert-then-prune; it just does not separate from B.

### §4.4 Mechanism: the subset relation is visible in the ledger

| arm | candidate_total | promoted | rejected | expired | pruned | gate kf / px |
|---|---|---|---|---|---|---|
| `A0_prune` | 90000 | 153 | 13023 | 52819 | 65842 | 0 / 0 |
| `B_deferred` | 90000 | 220 | 14459 | 51827 | 0 | 0 / 0 |
| `M_mask` | 90000 | 238 | **10970** | 54334 | 65304 | **16.7 / 855598** |

The mask removes candidates **upstream** of candidacy, as §3 predicted from the code: M's
`rejected` drops to 10970 vs A0's 13023 because zeroed person pixels fail
`valid = isfinite(observed) & (observed > 0.01)` and never become candidates at all. This is the
same code path that makes **recovery unmeasurable here** — unchanged, and no recovery claim is
made from this campaign in any branch (§3).

### §4.5 What this campaign does **not** resolve (limitations, own account)

1. **The noise band is wide, and that is why M2 rather than M1.** M's CV is **17.0%** against
   B's **4.0%** — the mask arm is ~4× noisier, so the pre-declared band (2× the larger own sd)
   spans ±4858 Gaussians ≈ ±38% of B's budget. **M2 is partly a statement about resolution, not
   only about the mechanisms.** Sharpening M1-vs-M2 needs more seeds *on M specifically*, and
   this is the campaign's own measured reason to expect that.
2. **`balloon` is a person+balloon sequence** (project-verified by frame inspection 2026-07-21),
   and a COCO-person mask **structurally cannot catch the balloon**. M's rate is therefore
   plausibly inflated relative to a person-only sequence, where a hard mask would block a larger
   share of the movers. This is simultaneously the mechanistic explanation for M not landing
   below B *and* the sharpest remaining gap: **the result may be sequence-composition-dependent,
   so it constrains person-mask methods on mixed-mover sequences, not hard masking in general.**
   Cross-sequence was declared out of scope in §3 and remains untested.
3. **The mask is Mask R-CNN, not RGD's OneFormer+EKF** (§1). Detector quality does not transfer.
4. **Single sequence, single frozen trajectory, PSNR ≈ 14.5, 3 seeds at 2 df.** Post-hoc and
   non-preregistered: this does not join the pre-declared ladder and does not alter the R2-P02
   H1 three-gate record.

**GO/KILL and narrative remain the user's** (prereg §9). Nothing above changes a prior verdict:
SWEEP / DECOMP / S6REPL are untouched, and no retraction is triggered by this campaign.
