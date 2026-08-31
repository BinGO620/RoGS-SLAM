# R2-P03-SWEEP — matched-budget prune ladder: one rung DOES dominate B (2026-07-30, closed out at 3 seeds)

> **Verdict reversed by the P0-residual top-up.** The 20-run version of this file read
> "0/6 rungs dominate B" while flagging (§3.8) that the one rung which reached B's budget was
> single-seed and was "the campaign's weakest joint". Closing that joint with 2 runs reversed
> it: **1/6 dominates**. The pre-declared decision rule is byte-identical; only the data grew.
> The superseded 20-run text is in git (`6b37845`).
>
> **RETRACTION (2026-07-30, `R2-P03-DECOMP`): §4's densification inference is refuted.**
> This file argued, from S2(1.13×B) vs S6(0.63×B), that "the only channel that separates them
> is densification" and therefore that **"a plain densify throttle on the baseline captures the
> compactness win without the deferred mechanism"**. Measured directly at 3 seeds, the densify
> throttle alone gives **0.98×A0** — no effect on map size at all — and S6 differs from S2 by
> *two* knobs (`gaussian_th` as well), so the premise did not hold arithmetically either.
> **The dominance verdict, the data and the pre-declared rule below are untouched**; what is
> retracted is an inference drawn in prose. Conversely §3.6 ("the baseline only reaches us by
> importing our admission budget") is **upgraded from narrative judgement to measurement**.
> See `results/evidence/r2_p03_decomp.md` §4.3.

22 runs, all exit 0, `ate_rmse_cm` = **2.0618 on every one of the 22** (pose channel frozen
across the whole campaign) · frozen RGD balloon, `cam_rot_delta = cam_trans_delta = 0` ·
2060, ~12.7 min/run, **4.7 h** · commits **`9c5f8a4`** (first 20 runs; apparatus committed
*before* the first run) **+ `6b37845`** (S6 seeds 1/2 — the diff against `9c5f8a4` is docs, one
log-format string in the runner, and the descriptive keyframe column in the readout: **no live
code, no config, no knob value**, so the ladder and both anchors are one live-code state) · raw
`results/runs/R2-P03/R2-P03-SWEEP/sweep_results.jsonl` · report `sweep_report.md` · runner
`scripts/r2_p03_sweep.py` · readout `scripts/r2_p03_sweep_readout.py` · configs
`configs/rgbd/experiments/r2_p03_sweep/` · contract `tests/test_r2_p03_sweep_configs.py`.

**Non-preregistered exploration** (`02-method.md` P0). It answers the review's "under-tuned
pruning baseline" objection and **does not touch the R2-P02 H1 record**.

## 0. The question, and the answer in three lines

Arm A (insert-then-prune) was swept along its own prune/admission knobs to see whether any
setting reaches arm B's map size without paying fidelity.

- **Mechanical verdict: 1 of 6 rungs dominates B** — `S6_maxpress`. The pre-declared rule
  (rate ≤ B's mean AND degradation within margin on both decision metrics) is satisfied by it.
- **S6 reaches 0.63× B's map size with no detectable fidelity cost**: 8110 ± 2715 vs B's
  12947 ± 1975 Gaussians (every S6 seed below every B seed, 3/3), at degradations of
  **−0.176 cm** depth and **−0.043 dB** vacated PSNR — both *nominally better* than B and at
  0.13× / 0.09× the larger own sd, i.e. indistinguishable, and far inside the 1.56 cm / 0.28 dB
  margins. It is also cheaper on VRAM (0.739 vs 0.831 GB, 3/3) and faster (10.25 vs 7.56 FPS, 3/3).
- **The native opacity prune still cannot get there on its own** (§3.1 survives untouched):
  `gaussian_th` 0.8 → 1.62× B and already fails the PSNR margin, 0.9 → 1.43× and stops. S6
  reaches B's budget only by combining that with `ttl_keyframes`=1 — the *deferred mechanism's
  own* admission budget — and a global densify throttle. What that combination licenses is a
  narrative judgement (§3.6), not a measurement, and it is now load-bearing.

**Why the reversal.** The 20-run version named this exact joint as its weakest (§3.8: "the
'reached it and lost fidelity' half of the verdict currently rests on one run"). That one run
was extreme on *both* axes — S6 seed 0 had the smallest map of the campaign (4975) *and* its
worst vacated PSNR (14.13). Seeds 1 and 2 landed at 9699 / 9657 Gaussians with PSNR
14.88 / 14.95, i.e. **above** B. So the single seed was misleading in both directions at once,
and the "compressed below B but lost the headline metric" sentence it supported is now false
and has been deleted, not softened.

Per `02-method.md` §H-C(a) — "若失败（某个 prune 档到达 ~11.3k 高斯且保真不差）⇒ compactness
头条塌" — **the trigger for that branch is met**. GO/KILL and narrative remain the user's (§9).

## 1. What was pre-declared before the first run (commit `9c5f8a4`)

| item | value |
|---|---|
| rate axis | `refined_num_gaussians` (== `online_num_gaussians`; colour refinement does not change the count) |
| decision metric 1 | `static_vacated_depth_l1_pen_cm` ↓, margin **1.56 cm** (1× self-tracked null sd 1.559) |
| decision metric 2 | `static_vacated_psnr` ↑, margin **0.28 dB** (1× null sd 0.278) |
| dominance | rate ≤ B's mean **AND** both degradations ≤ margin |
| seed promotion | **rate only** — proximity of the seed-0 rate to B's mean; the fidelity axis never enters selection |
| reported, not deciding | `static_depth_l1_pen_cm`, `static_psnr`, `static_ssim`, VRAM, FPS, ATE |

Bounded non-inferiority replaces "difference < sd" per the review's instruction: an undetected
difference is not evidence of equivalence, so the claim is "no degradation larger than
~1.5 cm / 0.28 dB was ruled in", not "equal fidelity".

Harness gates, all green on all 20 runs: **G1** ATE == 2.0618 ± 0.02; **G2** the config the run
*dumped* carries the rung's knob values (not the yaml on disk — this is what proves the process
resolved them); **G3** vacated support/frames non-zero; **G4** rate present.

## 2. The ladder

| rung | knob(s) vs arm A default | n | keyframes | Gaussians (mean ± sd) | ×B | vacated depth cm ↓ | vacated PSNR ↑ | peak VRAM GB | FPS |
|---|---|---|---|---|---|---|---|---|---|
| A0_prune | — (anchor) | 3 | 19/19/19 | 28344 ± 3519 | 2.19× | 37.57 ± 0.62 | 14.56 ± 0.10 | 1.026 | 7.26 |
| **B_deferred** | — (anchor) | 3 | **19/19/19** | **12947 ± 1975** | 1.00× | 38.23 ± 1.32 | 14.61 ± 0.23 | 0.831 | 7.56 |
| S1_ttl2 | `ttl_keyframes` 5→2 | 3 | 17/19/17 | 17218 ± 4085 | 1.33× | 38.79 ± 1.71 | 14.51 ± 0.21 | 0.901 | 8.32 |
| S2_ttl1 | `ttl_keyframes` 5→1 | 3 | 17/19/17 | 14648 ± 2914 | **1.13×** | 37.65 ± 1.37 | 14.40 ± 0.30 | 0.828 | 8.45 |
| S3_cap1000 | `max_candidates_per_keyframe` 5000→1000 | 3 | 19/17/19 | 14722 ± 675 | **1.14×** | 39.25 ± 2.26 | 14.53 ± 0.26 | 0.832 | 8.24 |
| S4_gth080 | `gaussian_th` 0.7→0.8 | **1** | 19 | 20918 | 1.62× | 39.66 | 14.20 | 0.969 | 8.04 |
| S5_gth090 | `gaussian_th` 0.7→0.9 | 3 | 17/20/20 | 18502 ± 2401 | 1.43× | 38.34 ± 2.64 | 14.45 ± 0.29 | 0.923 | 8.21 |
| **S6_maxpress** | `ttl` 1 + `gaussian_th` 0.9 + `densify_grad` 5e-4 | **3** | 16/18/18 | **8110 ± 2715** | **0.63×** | 38.05 ± 0.93 | 14.66 ± 0.46 | 0.739 | 10.25 |

S6 per seed: 4975 / 9699 / 9657 Gaussians — own sd 2715 on a mean of 8110 (CV 33%, the widest
on the ladder). Seed 0 ran in the first 20-run block, seeds 1/2 in the top-up; the anchors are
unchanged from the first block.

Degradation vs B (positive = rung worse than B) and the pre-declared margin test:

| rung | rate ≤ B? | Δ vacated depth (margin 1.56) | Δ vacated PSNR (margin 0.28) | verdict |
|---|---|---|---|---|
| S1_ttl2 | no | +0.563 ✓ | +0.101 ✓ | did not reach the budget |
| S2_ttl1 | no | **−0.578** ✓ (better) | +0.217 ✓ | did not reach the budget |
| S3_cap1000 | no | +1.025 ✓ | +0.085 ✓ | did not reach the budget |
| S4_gth080 | no | +1.430 ✓ | **+0.418 ✗** | did not reach the budget |
| S5_gth090 | no | +0.105 ✓ | +0.163 ✓ | did not reach the budget |
| **S6_maxpress** | **yes (0.63×)** | **−0.176** ✓ (better) | **−0.043** ✓ (better) | **DOMINATES B** |

Per-seed fidelity, S6 vs B (the margin test is on the mean; this is the spread behind it):
depth 39.10/37.31/37.76 vs B 39.76/37.49/37.44 (S6 better on 2/3); vacated PSNR
14.13/14.88/14.95 vs B 14.41/14.86/14.58 (S6 better on 2/3). Neither metric separates the two
arms at 3 seeds — which is the point: S6 is not *better*, it is **not worse**, at 0.63× the rate.

## 3. What this licenses, and what it does not

**Licensed (and this is the part that answers the reviewer):**

1. **The native MonoGS prune cannot reach the deferred operating point.** `gaussian_th` is the
   only native prune that fires on this stack (`prune_mode`'s covisibility branch is guarded by
   `self.monocular`, `slam_backend.py:457`, and these runs are RGB-D). Pushed to 0.8 it reaches
   1.62× B's count and already fails the PSNR margin (+0.418 dB); pushed to 0.9 it reaches
   1.43× and stops. **"Just raise your opacity threshold" does not get there.**
2. **~~Going below B's rate costs the headline metric.~~ RETRACTED by the 3-seed closeout.**
   This claim rested entirely on S6 seed 0 (+0.484 dB). At 3 seeds S6 goes below B's rate
   (0.63×) and the PSNR degradation is **−0.043 dB** — nominally better than B. Nothing in this
   campaign now shows that compressing below B's operating point costs fidelity.
3. **The compactness corollary reproduces in-campaign**: B vs A0 = **−54.3%** Gaussians
   (4.37× the larger own sd, 3/3, per-seed ranges non-overlapping: A min 25779 > B max 15227)
   and **−19.0% peak VRAM** (3.67×, 3/3), at fidelity differences of 0.22–0.50× (both inside
   both margins). Against the pre-flight's −55.2% on shifted absolute counts.
4. **B does it at constant coverage; S6 does not.** Both anchors kept **19 keyframes on all
   three seeds**; S6 ran at **16/18/18**, S2 at 17/19/17. Part of S6's smaller map is therefore
   less coverage of the sequence, not better economy at equal coverage. Keyframe count is an
   endogenous covariate and was **not** in the pre-declared rule, so this does **not** rescue
   the dominance verdict — it is a caveat on how to read it, and the honest statement is that
   the campaign cannot separate "S6 is more economical" from "S6 covered less".

**Not licensed — state this plainly in the paper:**

5. **B is not on the frontier.** One rung is strictly below it on rate at indistinguishable
   fidelity (S6, §3.2), and two more — S2 (1.13×) and S3 (1.14×) — sit above B's mean by
   +1701 and +1774 Gaussians, **0.58× and 0.90× the larger own sd**, i.e. inside the noise
   band, at fidelity within both margins. A tuned insert-then-prune arm is
   **statistically indistinguishable from B's map size at indistinguishable fidelity**, and one
   configuration of it is measurably below.
6. **The rungs that reach or approach B are not native prune knobs — they are the candidate
   lifecycle's own admission budget** (`ttl_keyframes`, `max_candidates_per_keyframe`), and in
   S6's case that plus a global densify throttle (`densify_grad_threshold` 2e-4 → 5e-4). Only
   one of S6's three knobs (`gaussian_th`) is a native prune. A competitor reproducing
   "insert-then-prune" from the literature has the prune knob but not the admission budget;
   they exist in this codebase *because* the deferred mechanism does. This framing ("the
   baseline only reaches us by importing our admission budget and detuning densification") is
   now **load-bearing on the dominance verdict itself**, and it is a narrative judgement, not a
   measurement — flagged, not banked. A reviewer is free to answer "then your contribution is
   the admission budget, and you should ablate it against a densify-throttled baseline".
   > **UPDATE 2026-07-30 (`R2-P03-DECOMP`): that ablation was run, and this framing is now a
   > measurement, not a judgement.** Densify-throttled baseline alone = 0.98×A0 (no effect);
   > `ttl`=1 alone = 1.37×B; both = 1.07×B, which reaches B's rate *noise band* but fails the
   > vacated-PSNR margin (+0.359 dB > 0.28) at 17/18/17 keyframes. All movement toward B's
   > operating point requires the admission budget. See `r2_p03_decomp.md` §4.2.
7. **The transient-cost story does not survive at matched rate, and is now inverted at S6.**
   Peak VRAM: B 0.831 / S2 0.828 / S3 0.832 GB, and **S6 0.739 GB (3/3 below B)** at
   **10.25 FPS vs B's 7.56 (3/3 above)**. The VRAM and speed advantages are over the *default*
   prune arm (1.026 GB), not over a tuned one — which beats B on both.
8. **One rung is still single-seed** (S4, `gaussian_th`=0.8) under the pre-declared rate-only
   promotion rule. It is not on the decision path — it never approached B's budget (1.62×) —
   so it is left as is. **S6 is now closed at 3 seeds, and closing it reversed the campaign's
   headline verdict.** The general lesson is banked in §8: on this stack a single seed decided
   a dominance verdict wrongly, in both directions at once, because the extreme seed was
   extreme on the rate axis *and* the fidelity axis simultaneously.

## 4. Mechanism: what the knobs actually did

| arm | candidate_total | promoted | rejected | expired | pruned | pending_peak | pending_final |
|---|---|---|---|---|---|---|---|
| A0_prune | 90000 | 244 | 13490 | 52571 | 66061 | 24779 | 23695 |
| B_deferred | 90000 | 256 | 14682 | 51676 | 0 | 24741 | 23386 |
| S1_ttl2 | 83333 | **0** | 1808 | 71525 | 73333 | 10000 | 10000 |
| S2_ttl1 | 83333 | **0** | 0 | 78333 | 78333 | 5000 | 5000 |
| S3_cap1000 | 17333 | 30 | 2566 | 10076 | 12642 | 4933 | 4661 |
| S4_gth080 | 90000 | 281 | 12578 | 53116 | 65694 | 24812 | 24025 |
| S5_gth090 | 90000 | 188 | 13321 | 53170 | 66491 | 24757 | 23321 |
| S6_maxpress | 81667 | **0** | 0 | 76667 | 76667 | 5000 | 5000 |

Every knob moved exactly the channel it names: TTL drove the end-of-run candidate residue
23695 → 10000 → 5000; the budget cap cut `candidate_total` 90000 → 17333; and the two
`gaussian_th` rungs left the candidate ledger **unchanged** (24025 / 23321), as a
post-insertion prune must.

**The finding that matters for P1.** At `ttl ≤ 2` the prune arm promotes **zero** candidates —
the candidate channel becomes pure insert-then-delete churn, and the residue it carries to the
end drops to 5000 raw (from 23695). Yet S2's final map is still ≈1.13× B's. Whatever remains of
the A-vs-B gap at that point cannot be candidate *residue*; it has to be the second-order
effect of having had those Gaussians in the map transiently (densify budget, `explained`
decisions). That is precisely the mechanism `R2-P03-CENSUS` (P1) was designed to measure, and
this sweep is indirect evidence for it — the effect is at the noise floor here, so P1 must
measure it directly rather than inherit it.

**And the S6 closeout sharpens why P1 is now the load-bearing experiment, not a nice-to-have.**
S6 = S2's `ttl`=1 *plus* a densify throttle, and it drops from S2's 1.13× B to 0.63× B. The
only channel that separates them is densification — the same second-order channel P1 targets.
That is consistent with the reading that the A-vs-B gap is a densify-budget effect rather than
candidate retention; but it also means **a plain densify throttle on the baseline captures the
compactness win without the deferred mechanism**, which is exactly the reviewer's objection.
P1 measuring "where the −54% comes from" no longer just strengthens the story — it decides
whether there is a mechanism claim left to make.

> **⚠ THE PARAGRAPH ABOVE IS RETRACTED (2026-07-30, `R2-P03-DECOMP`, 15 runs).** It is kept,
> not deleted, because it is what the indirect evidence looked like. Two errors: (a) S6 differs
> from S2 by **two** knobs (`gaussian_th` 0.9 *and* `densify_grad`), so "the only channel" never
> followed; (b) measured directly, `densify_grad` 2e-4→5e-4 **alone** yields **0.98×A0**
> (−446 Gaussians, 0.05× own sd, 3 seeds, equal 19/19/19 keyframes) — the densify throttle does
> **not** capture the compactness win on its own. The 2×2 factorial says the knobs are
> super-additive (interaction 0.80×): densify is inert until `ttl` squeezes admission.
> **P1 remains load-bearing — but for the opposite reason**: a deferred-specific component is
> what is left. See `r2_p03_decomp.md` §4.2–§4.3.

## 5. The anchor shift — why in-campaign anchors were not optional

Same config, same commit-equivalent live code, same machine, one day apart:

| arm | R2-P02-PREFLIGHT | R2-P03-SWEEP | shift |
|---|---|---|---|
| A_prune / A0_prune | 25228 ± 1375 | 28344 ± 3519 | **+12.4%** |
| B_deferred | 11296 ± 878 | 12947 ± 1975 | **+14.6%** |
| A_prune seed 0 alone | 26805 | 32356 | +20.7% |
| B_deferred seed 0 alone | 10349 | 15227 | +47.1% |
| `static_vacated_depth_l1_pen_cm`, arm A | 37.64 | 37.57 | −0.07 |
| same, arm A seed 0 | 36.82 | 38.26 | **+1.44 cm** |

The seed-0 depth shift (+1.44 cm) is 92% of the 1.56 cm non-inferiority margin. Comparing the
ladder against the *pre-flight's* B row would have put a phantom offset the size of the margin
inside the verdict. Diagnosis: keyframe count is identical (19), the candidate ledger matches to
~1%, and the entire shift sits in `immediate_insert` — the **certain**-path pixels both arms
share (B: 52645 → 92563). That channel was already the noisy one in the pre-flight (B's three
seeds: 52.6k / 107.7k / 56.7k). It is common-mode to both arms, which is why the *ratio*
(−54.3% vs −55.2%) survives while absolute counts move.

**Durable rule earned here:** the compactness *ratio* is the reportable quantity; absolute
Gaussian counts and fidelity absolutes are campaign-local and must never be compared across
campaigns. Anchors get re-run.

> **AMENDED 2026-07-30 (`R2-P03-DECOMP`): ratios are *more stable* than absolutes, not stable.**
> Re-running the `S2_ttl1` config file verbatim in the next campaign gave **1.37×B vs 1.13×B
> here (+21%)**, and B-vs-A0 compactness read −55.2% / −54.3% / **−46.6%** across the three
> campaigns. The rule (report ratios, re-run anchors) stands; the claim that the ratio itself is
> stable does not. Budget ~15–20% drift on any cross-campaign ratio. See `r2_p03_decomp.md` §4.5.
> **RE-AMENDED 2026-07-31 (`R2-P03-S6REPL`): budget ~30%, not ~15–20%.** Two further verbatim
> config replications measured **+29%** (`S6_maxpress` 0.63×B → 0.81×B) and **−23%**
> (`D2_ttl1_densify` 1.07×B → 0.82×B). The ~15–20% figure above was correct for the data
> available on 2026-07-30 and is kept verbatim for provenance. See `r2_p03_s6repl.md` §4.5.

## 6. Limitations (all of these belong in the paper's Limitations)

1. Non-preregistered, exploratory. One sequence (balloon), one frozen trajectory, PSNR ~14.5
   regime — the same "blurry regime" caveat P2 exists to test.
2. **Asymmetric sweep by design:** only arm A was pressurised. This answers "can a harder-pruned
   A reach B's point"; it does *not* claim B's frontier dominates A's frontier globally. Sweeping
   B too would be needed for that, and was not done.
3. Rate noise is large (own sd 675–4085; CV 5–24%). Rate differences below ~2× sd are not
   resolvable at 3 seeds, and the S2/S3-vs-B gap is inside that.
4. 3-seed sd carries 2 df; the ± intervals in the readout are crude.
5. Keyframe count is an uncontrolled (endogenous) covariate on the pressure rungs, 16–20 vs the
   anchors' fixed 19 — and the dominating rung S6 sits at 16/18/18, so its rate advantage is
   partly a coverage difference (§3.4).
6. S4 is single-seed. S6 was single-seed in the 20-run version and that single seed produced the
   **wrong verdict**; see §8.
7. `static_ssim` again favours the compact arms (B vs A0 +0.0217 at 3.26×, 3/3) and is again
   **not** banked — same metric-shopping guard as before.

## 8. The methodological lesson (worth a paragraph in the paper)

The pre-declared rate-only promotion rule sent only 4 of 6 rungs to 3 seeds, on the grounds
that fidelity must never select the ladder. That rule is still right — but it left the single
rung that reached B's budget resting on one run, and that run was extreme on **both** axes at
once (smallest map of the campaign *and* worst PSNR of the campaign). The result was a verdict
that was wrong in both directions simultaneously: it understated S6's map size by 2× and
invented a fidelity cost that does not exist. Two runs reversed the campaign's headline.

On a stack whose per-seed rate CV runs 5–33%, **any rung on the decision path needs 3 seeds
before it is written down**, regardless of what the promotion rule required. The 20-run version
did flag this joint as its weakest and said so before it was closed — the flag worked; the
sequencing (writing the verdict before closing the joint) is what should not repeat.

## 7. Cost and provenance

22 runs × ~12.7 min = **4.7 h on the 2060** (anchors 6 + pilot 6 + confirm 8 at `9c5f8a4`,
+ S6 seeds 1/2 at `6b37845`), against the plan's 2.5–3 h estimate for 9–12 runs; the overrun is
the 6 in-campaign anchor runs (§5) and the 6-rung seed-0 pilot that guaranteed the ladder
bracketed B. No teardown flakes in 22. Worktree was clean at both launches and the runner
refuses to start otherwise. The readout's keyframe column was added **after** all runs finished
and is marked descriptive; **the pre-declared decision rule is byte-identical to the version
committed before the first run** — the reversal is entirely data, not rule.

The top-up ran at `6b37845` rather than `9c5f8a4`. Diff between the two: docs, one log-format
string in `r2_p03_sweep.py`, and the descriptive keyframe column in the readout. No SLAM live
code, no config, no knob value — so all 22 runs are one live-code state and the same-campaign
rule holds in substance. S6 seed 0 sits hours away from seeds 1/2 within that state; given the
measured drift on the shared `immediate_insert` channel (§5), some of S6's 33% rate CV may be
that drift rather than seed variance, and the campaign cannot separate the two.

GO/KILL and narrative remain the user's (prereg §9, 08-04 date gate). Mechanically this is the
**"P0 被支配"** branch of the `02-method.md` decision tree — one rung reached B's budget at
fidelity inside both margins — with §3.4 and §3.6 as the caveats that keep it from being a
clean baseline win, and §8 as the process lesson.
