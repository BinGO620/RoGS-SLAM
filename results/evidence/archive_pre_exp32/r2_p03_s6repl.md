# R2-P03-S6REPL — does S6's dominance replicate, and what did `gaussian_th` contribute?

> **Status: COMPLETE — 9/9 runs, 2026-07-30 22:38 → 2026-07-31 00:29 (~12.3 min/run).**
> §1–§3 were written and committed BEFORE the first run and have not been edited since.
> §4 holds the measurements. **Landed branches: Q2 = (R1) the dominance REPLICATES;
> Q1 = (b) `gaussian_th` contributed nothing measurable on the rate axis.**
> Nothing in §1–§3 may be edited after the first run; if a reading turned out
> to be badly posed, that is recorded in §4 as a limitation rather than fixed retroactively
> (one such limitation is recorded in §4.4).
>
> **Post-hoc and non-preregistered.** These arms were chosen *after* seeing `R2-P03-SWEEP` and
> `R2-P03-DECOMP`. They are **not** part of the pre-declared ladder, they do **not** enter the
> H1 三门 record, and the paper must label them as post-hoc exploration. "Pre-declared" below
> always refers to *the readings in §2 and the decision rule*, which is inherited unchanged by
> import; the *arms* are post-hoc.

Experiment ID **`R2-P03-S6REPL`** (new ID: adding an arm is a new ID, `README.md` 命名规范 —
nothing here is appended to `R2-P03-SWEEP`'s or `R2-P03-DECOMP`'s results, reports or evidence).
Plan `R2-P03`, stage SCREEN, hardware RTX 2060, sequence Bonn `balloon` under the frozen RGD
trajectory (`Oracle.pose_file`, `cam_rot_delta = cam_trans_delta = 0`), seeds 0/1/2, mode
`--eval`.

Apparatus: runner `scripts/r2_p03_s6repl.py` · readout `scripts/r2_p03_s6repl_readout.py` ·
contract `tests/test_r2_p03_s6repl_configs.py` (9 tests, green at E0) · raw
`results/runs/R2-P03/R2-P03-S6REPL/s6repl_results.jsonl`. **This campaign introduces no config
file**: all three arms reference the frozen configs of the campaigns they replicate, by identity.

## 1. The question

Two closed campaigns leave exactly one load-bearing statement resting on a cross-campaign
comparison, and it is the statement the decision tree hangs from.

- **`R2-P03-SWEEP`** (22 runs, `9c5f8a4`+`6b37845`): **1/6 rungs dominates arm B** —
  `S6_maxpress` at **0.63×B**, degradations −0.176 cm / −0.043 dB, both inside the pre-declared
  1.56 cm / 0.28 dB margins. That single rung is why `02-method.md`'s decision tree sits at
  narrative **D**.
- **`R2-P03-DECOMP`** (15 runs, `5e789a5`): decomposed two of S6's three knobs in-campaign —
  the generic densify throttle **alone** does nothing (`D1` = 0.98×A0), `ttl`=1 alone = 1.37×B,
  both together (`D2`) = 1.07×B while failing the vacated-PSNR margin (+0.359 > 0.28).
  It could **not** test the third knob, `Training.gaussian_th` = 0.9, because S6 lived in the
  previous campaign.

So `r2_p03_decomp.md` §4.5 had to write: "D2 = 1.07×B here vs S6 = 0.63×B there **suggests**
`gaussian_th` carried a large part of S6's dominance … but it is still a cross-campaign
inference. Making it a measurement costs 3 runs / ~40 min and is offered, not assumed."

And the same campaign measured why that class of inference is unsafe: re-running SWEEP's `S2`
config file **verbatim** moved its ratio to the in-campaign B anchor from **1.13×B to 1.37×B
(+21%)**, and B-vs-A0 compactness read **−55.2% / −54.3% / −46.6%** across three campaigns.
Ratios are more stable than absolutes on this stack; they are **not** stable.

This campaign therefore does not buy the 3-run version. It re-runs the anchor and both arms of
the contrast in **one launch**, so neither answer contains a cross-campaign step:

| arm | config (frozen, by identity) | knobs vs arm A default | role |
|---|---|---|---|
| `B_deferred` | `r2_oracle_admission/oracle_deferred_balloon.yaml` | — | the operating point under test, in-campaign anchor |
| `D2_ttl1_densify` | `r2_p03_decomp/decomp_d2_ttl1_densify_balloon.yaml` | `ttl`=1, `densify_grad`=5e-4 | S6 **minus** the native opacity prune |
| `S6_maxpress` | `r2_p03_sweep/sweep_s6_maxpress_balloon.yaml` | `ttl`=1, `gth`=0.9, `densify_grad`=5e-4 | SWEEP's dominating rung, same file |

**Scale: 3 arms × 3 seeds = 9 runs, ~1.9 h on the 2060**, one campaign, one commit.

Two questions, both answered by within-campaign contrasts:

- **Q1 — what did `gaussian_th` contribute?** `S6_maxpress` ÷ `D2_ttl1_densify`. Those two
  configs differ in **exactly** `Training.gaussian_th` (0.7→0.9) with `ttl_keyframes` and
  `densify_grad_threshold` identical — asserted at E0 by
  `tests/test_r2_p03_s6repl_configs.py::test_s6_minus_d2_is_exactly_the_native_opacity_prune`
  (and previously by `test_r2_p03_decomp_configs.py`). The ratio is that one knob's
  multiplicative effect at that operating point.
- **Q2 — does the dominance replicate?** `S6_maxpress` against an **in-campaign** B anchor under
  the imported dominance rule. S6's verdict currently rests on one campaign, at a rate CV of
  **33%** (the widest in the project), on a stack whose ratios drift ~20%. `r2_p03_sweep.md` §7
  already flagged that S6 seed 0 ran hours away from seeds 1/2 and that the campaign "cannot
  separate" drift from seed variance in its CV.

Q2 is not a bonus. It is the replication of the only measurement that puts the project in
narrative D, and it has never been attempted.

## 2. Pre-declared readings — WRITTEN BEFORE THE FIRST RUN

The judgement criteria are inherited from `R2-P03-SWEEP` **by import, not by copy**
(`scripts/r2_p03_s6repl_readout.py` imports `RATE`, `DECISION`, `DESCRIPTIVE`, `degradation`,
`keyframe_count`, `T95_DF2` from `scripts/r2_p03_sweep_readout.py`; the runner imports gates
G1–G4 from `scripts/r2_p03_sweep.py`), so they are byte-identical to the rule that produced both
prior verdicts:

| item | value |
|---|---|
| rate axis | `refined_num_gaussians` |
| decision metric 1 | `static_vacated_depth_l1_pen_cm` ↓, margin **1.56 cm** |
| decision metric 2 | `static_vacated_psnr` ↑, margin **0.28 dB** |
| dominance | rate ≤ B's mean **AND** both degradations ≤ margin |
| denominator | the **larger** of the two arms' own 3-seed sd (never pooled) |
| per-seed | sign counts reported; a flipped seed puts a contrast inside the band |
| band | `|Δrate| ≤ 1× larger own sd` = "inside B's rate band" (descriptive, as in DECOMP) |
| seeds | **3 on every arm** — no arm gets a written conclusion at n=1 (SWEEP §8) |
| reported, not deciding | keyframes, `static_depth_l1_pen_cm`, `static_psnr`, `static_ssim`, VRAM, FPS, ATE |

### Q1 — `gaussian_th`'s contribution. Three outcomes, bound now.

Statistic: `f_gth` = mean rate(S6) ÷ mean rate(D2), with the gap in units of the larger own sd,
the per-seed sign count, and the every-seed-below check — the same three views DECOMP used for
its decisive cell, so no single one of them carries the reading.

1. **(a) S6 clearly below D2** (gap < −1× larger own sd) ⇒ the **native opacity prune carries a
   measurable share of S6's dominance**. Consequence for what may be written: the sentence "only
   1 of S6's 3 knobs is a native prune" must from then on be **paired with how much that one
   knob did** — it is no longer available as a way of implying the native prune was incidental.
   The `ttl`=1 degeneracy (`promoted`=0) remains a separate and still-valid caveat.
2. **(b) S6 indistinguishable from D2** (|gap| ≤ 1× larger own sd) ⇒ `gaussian_th` contributed
   **nothing measurable** at this operating point. Then S6's dominance *is* the `ttl`+`densify`
   combination — DECOMP's `D2` row — and the 0.63×-vs-1.07× gap read across campaigns was
   **drift, not `gth`**. Note this outcome is in tension with SWEEP's `S5_gth090` (that knob
   alone = 1.43×B, i.e. it did something at `ttl`=5); if (b) lands, the honest statement is that
   `gth`'s effect is conditional on the admission budget, not that it never has one.
3. **(c) S6 clearly above D2** (gap > +1× larger own sd) ⇒ `gaussian_th`=0.9 *raised* the rate
   at this operating point. Reported as measured, with the S5 comparison above; no narrative
   consequence is pre-claimed for this branch because none is currently foreseeable.

### Q2 — does the dominance replicate? Three outcomes, bound now.

4. **(R1) S6 dominates B again** (rate ≤ B's mean AND both degradations within margin)
   ⇒ **the SWEEP verdict replicates** across independent campaigns against a fresh anchor.
   Narrative **D**'s trigger is robust rather than a one-campaign artifact, and the caveats
   travel with it as re-measured here (keyframe coverage, ledger degeneracy). This is the
   outcome that makes the honest-negative-result framing *stronger*, not weaker.
5. **(R2) S6 misses B's mean rate** ⇒ **the dominance does not replicate.** Pre-declared
   handling, so it cannot be argued afterwards:
   - SWEEP's verdict is **not deleted and not retracted** — it was a legitimate in-campaign
     measurement under a byte-identical rule. Two campaigns disagreeing is a fact about the
     stack, not an error in either.
   - The honest statement becomes **"S6 dominated B in 1 of 2 campaigns"**, with the rate-band
     column saying how far it missed here, and with both campaigns' ratios quoted.
   - The trigger for narrative D then rests on a **non-replicating** result. The assistant will
     say so plainly and will **not** re-derive a narrative from it: GO/KILL and narrative remain
     the user's (prereg §9, 08-04 date gate).
6. **(R3) S6 reaches B's rate but breaks a margin** ⇒ this is exactly the claim
   `r2_p03_sweep.md` §3.2 **retracted** as a single-seed artifact ("going below B's rate costs
   the headline metric"). If it returns at 3 seeds against a fresh anchor, that retraction must
   be **revisited explicitly in `r2_p03_sweep.md` §3.2 and every place that cites it** — written
   up as "campaign-dependent", never silently reversed. The retraction itself was correct *for
   SWEEP's data* and stays on the record either way.

### Secondary readings (reported alongside; not decision-grade on their own)

- **Keyframes per seed are required reading.** S6 dominated at **16/18/18** against the anchors'
  19/19/19 (`r2_p03_sweep.md` §3.4), so part of its rate win was less coverage. If S6 runs
  19/19/19 here, that caveat weakens; if it runs fewer again, the caveat **replicates** and is
  no longer a one-campaign observation. D2 ran 17/18/17 in DECOMP.
- **Mechanism, `gth` isolation**: `gaussian_th` prunes *after* insertion, so S6's candidate
  ledger must match D2's (in SWEEP the two `gth` rungs left the ledger unchanged vs A0). If it
  moved, the pair is not `gth`-isolated on the mechanism side and Q1 carries that caveat.
- **Mechanism, `ttl` degeneracy**: both arms run `ttl`=1, where DECOMP measured `promoted` = 0
  on **every** seed and residue 23927→5000. If that does not reproduce, the statement "the
  baseline must degenerate into insert-everything-then-delete-one-keyframe-later" needs
  qualifying.
- **Two new ratio-drift datapoints**: S6 ÷ B here vs 0.63× in SWEEP, and D2 ÷ B here vs 1.07× in
  DECOMP. These extend the drift series that currently reads +21% (`D0`'s S2 replicate) and
  −55.2/−54.3/−46.6% (B-vs-A0). They are drift measurements, **not** arm comparisons.

## 3. Scope — anchors in-campaign, and what 9 runs deliberately cannot say

`README.md` 跨 campaign 比较禁令 (earned in SWEEP §5, sharpened in DECOMP §4.5): absolutes drift
+12–15% in mean Gaussian count (single seed up to +47%) and +1.44 cm in
`static_vacated_depth_l1_pen_cm` — 92% of the 1.56 cm margin — and **ratios themselves drift
~15–20%**. Reusing either prior campaign's B row as this campaign's anchor could manufacture or
erase both answers by itself. Therefore arm B is re-run here at 3 seeds, and **the only
quantities that cross campaigns are ratios to each campaign's own B anchor**, each labelled with
campaign and commit, confined to one clearly-marked section of the readout.

Deliberately out of scope at this scale (stated in advance so it is not claimed later):

- **No `A0_prune` anchor in this campaign.** Nothing here extends the B-vs-A0 compactness series
  to a fourth campaign, and no rate in §4 may be expressed × A0 — the multiplicative frame used
  by DECOMP's 2×2 table is unavailable, which is why Q1 is stated as S6 ÷ D2 rather than × A0.
  Adding it would be +3 runs / ~40 min and was scoped out by the user.
- One sequence (`balloon`), one frozen trajectory, PSNR ≈ 14.5 regime — the same "blurry regime"
  caveat `P2 R2-P03-RENDER3090` exists to test.
- Arm A is pressurised only; nothing here claims B's frontier dominates A's frontier globally.
- 3-seed sd carries 2 df; the ± intervals in the readout are crude.
- Post-hoc, non-preregistered; only the judgement rule is inherited, and it is inherited by
  import.

Harness gates, imported from `scripts/r2_p03_sweep.py` and required green on every run:
**G1** `ate_rmse_cm` == 2.0618 ± 0.02; **G2** the config the run *dumped* carries the arm's knob
values (not the yaml on disk — this is what proves the process resolved them); **G3** vacated
support/frames non-zero; **G4** rate present. Worktree must be clean at launch; the runner
refuses to start otherwise, and live code is frozen for the duration.

GO/KILL and narrative remain the user's (prereg §9, 08-04 date gate).

## 4. Measurements — 9/9 runs, all four gates green

Provenance: apparatus frozen at commit `48b6b44` (runner, readout, contract test, pre-registration
§1–§3). Launch HEAD was `5154241`; the only difference between the two is two unrelated
pre-existing user files that had to be tracked because the runner refuses to start on a dirty
worktree. **No live code, no config and no apparatus change sits between the frozen commit and the
campaign.** Gates on every one of the 9 runs: **G1** `ate_rmse_cm` = 2.0618 exactly (pose channel
provably frozen), **G2** the dumped config echoed each arm's knobs, **G3** vacated support
non-zero, **G4** rate present.

| arm | knobs | rate (mean ± own sd) | per-seed rate | keyframes | `vacated_depth_l1_pen_cm` | `vacated_psnr` |
|---|---|---|---|---|---|---|
| `B_deferred` (anchor) | — | **12117 ± 332** (CV 2.7%) | 12023 / 11843 / 12486 | 19/19/19 | 37.99 ± 1.10 | 14.68 ± 0.166 |
| `D2_ttl1_densify` | ttl=1, densify=5e-4 | **9994 ± 1874** (CV 19%) | 8716 / 9121 / 12146 | 17/18/17 | 40.85 ± 1.30 | 14.20 ± 0.534 |
| `S6_maxpress` | ttl=1, **gth=0.9**, densify=5e-4 | **9857 ± 353** (CV 3.6%) | 9672 / 9634 / 10264 | 18/18/16 | 37.38 ± 1.86 | 14.57 ± 0.254 |

The anchor is the tightest B this project has measured (CV 2.7%; DECOMP's B was 12140 ± 663).
Its mean is within 0.2% of DECOMP's — which is a coincidence worth naming rather than a general
result, because §4.5 shows the *ratios* moved a lot more than the anchor did.

### 4.1 Q2 — the dominance replicates. Pre-declared branch **(R1)**.

`S6_maxpress`, from SWEEP's frozen config file by identity, judged against a fresh in-campaign
anchor by the rule imported byte-identically from `scripts/r2_p03_sweep_readout.py`:

| check | value | verdict |
|---|---|---|
| rate ≤ B's mean | 9857 vs 12117 = **0.81×**, −6.40× larger own sd | ✅ |
| every S6 seed below every B seed | max(S6) 10264 < min(B) 11843 → **3/3** | ✅ |
| degradation `static_vacated_depth_l1_pen_cm` (margin 1.56) | **−0.605** (S6 *better* than B) | ✅ |
| degradation `static_vacated_psnr` (margin 0.28) | **+0.110** | ✅ |

⇒ **`S6_maxpress` DOMINATES B again.** Under §2 branch (R1): the SWEEP verdict **replicates**
across an independent campaign against a fresh anchor, so narrative **D**'s trigger is robust
rather than a one-campaign artifact — and, as §2 said in advance, this makes the
honest-negative-result framing *stronger*, not weaker.

Both fidelity contrasts sit inside the noise band as well as inside the margin (depth 0.33×sd
with 2/3 seeds; PSNR 0.43×sd with 1/3 seeds), so the correct reading is "fidelity indistinguishable
from B at 19% less rate", not "slightly better depth". Note the PSNR degradation flipped sign vs
SWEEP (−0.043 there, +0.110 here) while staying far inside the 0.28 margin — an illustration of why
the margin, not the sign, is the decision object.

**Branch (R3) did not fire.** S6 went below B's rate with **both** margins intact, so
`r2_p03_sweep.md` §3.2's retraction of "going below B's rate costs the headline metric" is
untouched and is now supported by a second independent campaign. No revisit is owed.

`D2_ttl1_densify` **reached** B's mean rate here (0.82×) but broke **both** margins
(+2.861 cm > 1.56, +0.474 dB > 0.28) ⇒ **NOT-DOMINATED**. In DECOMP the same config missed the
rate (1.07×) and broke PSNR only (+0.359). The *verdict* is therefore stable across both
campaigns even though the *ratio* moved 23% — a useful demonstration that the dominance rule is
more robust than the quantity it is applied to.

**Arms dominating B in this campaign: 1 of 2.** Across all three campaigns the tally is now
**S6 dominating in 2 of 2 campaigns it was run in**, and every other rung/cell tested (6 SWEEP
rungs, 4 DECOMP cells, D2 here) failing.

### 4.2 Q1 — `gaussian_th` contributed nothing on the rate axis. Pre-declared branch **(b)**.

The two arms differ in **exactly** `Training.gaussian_th` (0.7→0.9), pinned by
`tests/test_r2_p03_s6repl_configs.py::test_s6_minus_d2_is_exactly_the_native_opacity_prune`, both
at ttl=1 and densify=5e-4, both 3 seeds, both in this campaign — no cross-campaign step anywhere
in this ratio.

| quantity | value |
|---|---|
| `f_gth` = rate(S6) ÷ rate(D2) | **0.99×** |
| gap in units of the larger own sd (1874) | **−0.07×sd** |
| per-seed: S6 below D2 | **1/3** |
| every S6 seed below every D2 seed | no |

⇒ **branch (b)**: `gaussian_th` is indistinguishable from doing nothing to the map size at this
operating point. Per §2, the consequences that follow — and they were bound in advance:

- S6's **rate** advantage *is* the `ttl`+`densify` combination, i.e. DECOMP's D2 row.
- The **0.63×-vs-1.07× gap read across campaigns was drift, not `gth`.** This is precisely the
  cross-campaign inference this campaign was built to replace with a measurement, and the
  measurement contradicts it.
- As §2 required: this is **in tension with SWEEP's `S5_gth090`** (that knob alone = 1.43×B at
  ttl=5, i.e. it did do something there). The honest statement is that **`gth`'s effect on rate is
  conditional on the admission budget**, not that it never has one. At ttl=1 the candidate
  lifecycle has already collapsed (§4.3), leaving the opacity prune little to remove.

### 4.3 Secondary readings — all three pre-declared checks reproduce

- **Keyframe coverage caveat REPLICATES.** S6 ran **18/18/16** against the anchor's 19/19/19
  (SWEEP: 16/18/18). So part of S6's rate win is again less coverage of the sequence rather than
  better economy, and this is no longer a one-campaign observation. D2 ran 17/18/17, matching
  DECOMP's 17/18/17 exactly. **This caveat travels with the replicated dominance and must be
  quoted wherever the 0.81× is quoted.**
- **`gth` isolation confirmed on the mechanism side.** S6's candidate ledger is *identical* to
  D2's (candidate_total 81667, promoted 0, rejected 0, expired 76667, pruned 76667, pending_final
  5000). `gaussian_th` acts after insertion, exactly as expected, so **Q1 carries no isolation
  caveat**.
- **`ttl`=1 lifecycle degeneracy REPLICATES.** `promoted` = **0/0/0 per seed on both arms**, with
  residue collapsed to pending_final 5000 (B: promoted 215, pending_final 23296). DECOMP measured
  the same. So "the baseline reaches this rate only by degenerating into
  insert-everything-then-delete-one-keyframe-later" needs **no qualification** — it now holds in
  two campaigns.

### 4.4 An unanticipated observation, and the limitation it exposes in §2's framing

Q1's statistic was pre-declared as a **rate** ratio only. On rate, branch (b) is unambiguous. But
the two arms are *not* interchangeable, and the readout's descriptive tables show where:

| S6 − D2 (same campaign, 3 seeds) | Δ | in larger own sd | per-seed |
|---|---|---|---|
| `static_vacated_depth_l1_pen_cm` ↓ | **−3.466** | 1.86×sd | **3/3** |
| `static_vacated_psnr` ↑ | **+0.364** | 0.68×sd | 2/3 |

At equal rate (0.99×), adding `gaussian_th`=0.9 moved the depth error by more than the 1.56 cm
decision margin and by 1.86 own-sd with unanimous per-seed sign. **This — not rate — is what
separates DOMINATES from NOT-DOMINATED in §4.1**: both arms reached B's budget, and only the one
carrying the native opacity prune stayed inside both fidelity margins.

The limitation this exposes: **§2 posed Q1 as if `gth`'s contribution were a single scalar on the
rate axis, and it is not.** Branch (b) is reported as it landed, because it is what was
pre-declared and it is true as stated. The fidelity contrast above is **descriptive and
post-hoc** — it was not a pre-declared statistic, it has 2 df, and it must not be written up as a
verdict. It is a **hypothesis for a future pre-registered test**, and the sentence "only 1 of S6's
3 knobs is a native prune" must from now on be paired with "and at ttl=1 that one knob is what
keeps the arm inside the fidelity margins", which is the opposite of implying it was incidental.

### 4.5 Two new ratio-drift datapoints — the drift is larger than previously measured

Ratios to each campaign's **own** B anchor, each labelled with campaign and commit. These extend
the drift series; they are **not** arm comparisons.

| arm | this campaign | prior campaign | drift on the ratio |
|---|---|---|---|
| `S6_maxpress` | **0.81×B** | 0.63×B (SWEEP, `9c5f8a4+6b37845`) | **+29%** |
| `D2_ttl1_densify` | **0.82×B** | 1.07×B (DECOMP, `5e789a5`) | **−23%** |

The series now reads **+21% / +29% / −23%** on same-config ratio replication (plus B-vs-A0 at
−55.2 / −54.3 / −46.6% across three campaigns). So `README.md`'s current threshold — cross-campaign
ratio differences below ~20% are not evidence — is **too permissive by this campaign's data**;
the honest bound is **~30%**. Both new datapoints were produced with the anchor re-run in the same
campaign, which is the only reason the underlying verdicts survived the drift.

### 4.6 What this campaign does **not** say

Everything scoped out in §3 stands: **no `A0_prune` anchor**, so nothing here extends the B-vs-A0
compactness series and no rate above is expressed × A0. One sequence, one frozen trajectory,
PSNR ≈ 14.5 regime. Arm A is pressurised only. 3-seed sd carries 2 df. Post-hoc and
non-preregistered — these arms do not enter the pre-declared ladder and do not touch the R2-P02
H1 三门 record; only the judgement rule is inherited, and it is inherited by import.

GO/KILL and narrative remain the user's (prereg §9, 08-04 date gate).
