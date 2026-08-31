# R2-P03-DECOMP — which of S6's three knobs produced the dominance? (pre-registration)

> **Status: CLOSED — 15/15 runs done 2026-07-30, all gates green.** §1–§3 were committed
> *before* the first run (commit `5e789a5`) and are unmodified; §4 holds the measurements.
> **Verdict: 0/4 cells dominate B, and the decisive cell `D1_densifyonly` landed in
> pre-declared branch 3** — the generic densify knob alone gives 0.98×A0, i.e. it does not
> move the map size at all. The compactness win is not reachable by a generic knob.
>
> **Post-hoc and non-preregistered.** These cells were chosen *after* seeing `R2-P03-SWEEP`'s
> data. They are **not** part of the pre-declared ladder, they do **not** enter the H1 三门
> record, and the paper must label them as post-hoc exploration. "Pre-registered" below always
> refers to the *decision rule*, which is inherited unchanged; the *cells* are post-hoc.

Experiment ID **`R2-P03-DECOMP`** (new ID: changed configs ⇒ new ID, `README.md` 命名规范 —
nothing here is appended to `R2-P03-SWEEP`). Plan `R2-P03`, stage SCREEN, hardware RTX 2060,
sequence Bonn `balloon` under the frozen RGD trajectory (`Oracle.pose_file`,
`cam_rot_delta = cam_trans_delta = 0`), seeds 0/1/2, mode `--eval`.

Apparatus: runner `scripts/r2_p03_decomp.py` · readout `scripts/r2_p03_decomp_readout.py` ·
configs `configs/rgbd/experiments/r2_p03_decomp/` · contract `tests/test_r2_p03_decomp_configs.py`
(9 tests, green at E0) · raw `results/runs/R2-P03/R2-P03-DECOMP/decomp_results.jsonl`.

## 1. The question

`R2-P03-SWEEP` closed at 22 runs with **1/6 rungs dominating arm B**: `S6_maxpress` reached
**0.63×B** at degradations −0.176 cm / −0.043 dB, both inside the pre-declared 1.56 cm /
0.28 dB margins and both nominally better than B. Mechanically that is `02-method.md`'s
"P0 被支配" branch.

But S6 moved **three knobs at once**:

| knob | family | exists in this codebase because… |
|---|---|---|
| `DeferredCommit.ttl_keyframes` 5 → 1 | candidate-lifecycle **admission budget** | the deferred mechanism does |
| `Training.gaussian_th` 0.7 → 0.9 | native MonoGS **opacity prune** | stock MonoGS |
| `opt_params.densify_grad_threshold` 2e-4 → 5e-4 | native **densification gate** | stock MonoGS |

so the question that decides whether a mechanism claim survives — **is the −54% compactness
win deferred-specific, or does one generic densify knob capture it?** — is currently
unanswerable. `r2_p03_sweep.md` §3.6 asserts "the baseline only reaches us by importing our
admission budget and detuning densification", and flags itself as a *narrative judgement, not
a measurement*. This campaign turns it into a measurement.

The design is the 2×2 factorial {`ttl_keyframes`=1} × {`densify_grad`=5e-4} on arm A, against
an in-campaign arm-B anchor. `gaussian_th` alone is not re-run: SWEEP already has it at 3 seeds
(`S5_gth090` = 1.43×B) and it is not on the critical path.

| cell | knobs vs arm A default | what it isolates |
|---|---|---|
| `A0_prune` | — | the factorial's "neither" cell / control anchor |
| `D0_ttl1` | `ttl_keyframes` 5→1 | the admission budget alone (SWEEP's `S2` config, verbatim) |
| **`D1_densifyonly`** | `densify_grad` 2e-4→5e-4 | **the decisive cell** — one generic knob, no admission budget touched |
| `D2_ttl1_densify` | both | the interaction = S6 **minus** the native opacity prune |
| `B_deferred` | — | the operating point under test |

**Scale: 5 arms × 3 seeds = 15 runs, ~3.2 h on the 2060**, all in one campaign at one commit.
The full factorial is launched unconditionally, so *which cells exist* is not a data-dependent
choice either — only the six-run core (`B` + `D1`) is strictly needed to decide §2, and the
other three arms are what make the decision *attributable* instead of merely correct.

## 2. Pre-declared readings — WRITTEN BEFORE THE FIRST RUN

The judgement criteria are inherited from `R2-P03-SWEEP` **by import, not by copy**
(`scripts/r2_p03_decomp_readout.py` imports `RATE`, `DECISION`, `degradation` from
`scripts/r2_p03_sweep_readout.py`), so they are byte-identical to the rule that produced the
SWEEP verdict:

| item | value |
|---|---|
| rate axis | `refined_num_gaussians` |
| decision metric 1 | `static_vacated_depth_l1_pen_cm` ↓, margin **1.56 cm** |
| decision metric 2 | `static_vacated_psnr` ↑, margin **0.28 dB** |
| dominance | rate ≤ B's mean **AND** both degradations ≤ margin |
| denominator | the **larger** of the two arms' own 3-seed sd (never pooled) |
| per-seed | sign counts reported; a flipped seed puts a contrast inside the band |
| seeds | **3 on every cell** — no cell gets a written conclusion at n=1 (SWEEP §8) |
| reported, not deciding | keyframes, `static_depth_l1_pen_cm`, `static_psnr`, `static_ssim`, VRAM, FPS, ATE |

**The three outcomes and what each one means.** All three are fixed here, before data:

1. **`D1_densifyonly` DOMINATES B** (rate ≤ B's mean, both degradations within margin)
   ⇒ **compactness is not deferred-specific**: one generic densify knob, available in every
   3DGS system and owing nothing to our mechanism, reaches the operating point. Narrative **D**
   (honest negative result + methodological contribution) hardens. **P1 `R2-P03-CENSUS` most
   likely cannot rescue the mechanism claim** — it would explain, in mechanistic detail, a win
   a competitor obtains by changing one line ⇒ the assistant will **recommend skipping P1**
   and reallocating to P2/writing. (GO/KILL remains the user's.)

2. **`D1_densifyonly` misses B's mean but lands inside B's rate noise band**
   (|Δrate| ≤ 1× the larger own sd, at fidelity within both margins)
   ⇒ **substantively the same conclusion as (1) for the mechanism question**: a tuned generic
   knob is statistically indistinguishable from B's map size, so "deferred is needed for the
   compactness" is not supportable. The *strict* dominance verdict still belongs to S6 alone,
   and the paper must say so. Recommendation: same as (1), stated with the weaker verb
   ("indistinguishable from", not "below").
   *This bin exists because SWEEP produced exactly this situation with S2 (1.13×B, 0.58×sd) and
   S3 (1.14×B, 0.90×sd) and the meaning had to be argued about afterwards. Binding it now is
   the whole point of writing this section before the run.*

3. **`D1_densifyonly` is clearly above B** (Δrate > 1× the larger own sd)
   ⇒ **S6's dominance had to borrow `ttl=1`, the deferred mechanism's own admission budget.**
   `r2_p03_sweep.md` §3.6 is upgraded from narrative judgement to measurement, and **P1 is
   worth running** — there is a mechanism claim left that P1 can substantiate.

Secondary readings (not decision-grade on their own, reported alongside):

- `D2` vs `D0`/`D1` gives the interaction: whether the two knobs are additive, or whether the
  densify throttle only bites once the admission budget is squeezed.
- `D2` vs SWEEP's `S6` (ratio-to-own-B-anchor only, see §3) says whether `gaussian_th`
  contributed anything to S6's dominance at all.
- `D0` re-runs SWEEP's `S2` config **verbatim**, so `D0`'s ratio-to-B here vs 1.13× there is a
  *measured* campaign-to-campaign reproducibility figure for a ratio, on top of §5 of
  `r2_p03_sweep.md` which measured the drift of absolutes.
- **Keyframe count is reported per seed and is required reading.** S6 dominated at 16/18/18
  keyframes against the anchors' 19/19/19, so part of its rate win was less coverage. A cell
  that reaches B's budget at **equal** keyframes is a strictly stronger result; one that does
  it at fewer carries S6's caveat (`r2_p03_sweep.md` §3.4) unchanged.

**What this campaign cannot decide** (stated in advance so it is not claimed later): it is one
sequence, one frozen trajectory, in the PSNR ≈ 14.5 regime; it pressurises arm A only, so it
cannot claim B's frontier dominates A's frontier globally; and 3-seed sd carries 2 df.

## 3. Anchors are re-run in-campaign — no exceptions

`README.md` 跨 campaign 比较禁令, earned in SWEEP §5: same config, same live code, same
machine, one day apart drifted **+12–15%** in mean Gaussian count (single seed up to **+47%**)
and **+1.44 cm** in `static_vacated_depth_l1_pen_cm` — 92% of the 1.56 cm margin. Reusing
SWEEP's B row as this campaign's anchor could manufacture or erase the verdict by itself.

Therefore: arm B is re-run here at 3 seeds, and **the only quantities that cross campaigns are
ratios to each campaign's own B anchor**, each labelled with its campaign. No absolute Gaussian
count and no absolute fidelity value from SWEEP appears in this campaign's tables.

## 4. Results — **0/4 cells dominate B; the decisive cell lands in pre-declared branch 3**

15 runs, all exit 0, `ate_rmse_cm` = **2.0618 on every one of the 15** (pose channel frozen),
~12.7 min/run, **3.2 h**, no teardown flakes. All four harness gates green on all 15 runs
(G1 pose frozen, G2 the dumped config carries each cell's knob values, G3 vacated support
non-zero, G4 rate present). Commit **`5e789a5`** — the frozen apparatus commit, i.e. §1–§3
above were on disk before the first run. Raw
`results/runs/R2-P03/R2-P03-DECOMP/{decomp_results.jsonl,decomp_report.md}`.

| cell | knobs | keyframes | Gaussians (mean ± own sd) | ×B | ×A0 | vacated depth cm ↓ | vacated PSNR ↑ | peak VRAM GB | FPS |
|---|---|---|---|---|---|---|---|---|---|
| A0_prune | — (anchor) | **19/19/19** | 22741 ± 814 | 1.87× | 1.00× | 38.56 ± 1.01 | 14.37 ± 0.26 | 0.999 | 7.85 |
| **B_deferred** | — (anchor) | **19/19/19** | **12140 ± 663** | 1.00× | 0.53× | 37.26 ± 1.18 | 14.76 ± 0.15 | 0.798 | 8.51 |
| D0_ttl1 | `ttl` 5→1 | **19/19/19** | 16580 ± 358 | 1.37× | 0.73× | 36.98 ± 1.96 | 14.81 ± 0.06 | 0.850 | 8.15 |
| **D1_densifyonly** | `densify_grad` 2e-4→5e-4 | **19/19/19** | **22295 ± 8284** | **1.84×** | **0.98×** | 37.81 ± 1.77 | 14.66 ± 0.05 | 0.956 | 8.50 |
| D2_ttl1_densify | both | 17/18/17 | 12983 ± 865 | 1.07× | 0.57× | 37.86 ± 1.64 | 14.41 ± 0.28 | 0.787 | 9.29 |

Per-seed rate: A0 22392/23671/22159 · B 11902/11628/12889 · D0 16946/16230/16564 ·
**D1 19813/31536/15535** · D2 12925/13876/12149.

The pre-declared dominance test (margins 1.56 cm / 0.28 dB, rule imported from the SWEEP
readout):

| cell | rate ≤ B? | rate band | Δ vacated depth | Δ vacated PSNR | verdict |
|---|---|---|---|---|---|
| A0_prune | no | above band (+13.02×sd) | +1.301 ✓ | **+0.399 ✗** | did not reach B's budget |
| D0_ttl1 | no | above band (+6.69×sd) | −0.275 ✓ (better) | −0.042 ✓ (better) | did not reach B's budget |
| **D1_densifyonly** | **no** | **above band (+1.23×sd)** | +0.554 ✓ | +0.109 ✓ | **did not reach B's budget** |
| D2_ttl1_densify | no | **inside B's band (+0.98×sd)** | +0.600 ✓ | **+0.359 ✗** | did not reach B's budget |

### 4.1 The decisive cell: the generic densify knob alone does essentially nothing

`D1_densifyonly` = **1.84×B**, and — the sharper number — **0.98×A0**: −446 Gaussians against
the untouched arm-A default, **0.05× the larger own sd, 2/3 seeds**. Turning
`densify_grad_threshold` from 2e-4 to 5e-4 on this stack, by itself, does not measurably
shrink the map at all.

This is **pre-declared branch 3** (§2): D1 is *clearly* above B, not inside its band. Three
independent ways of saying it, so the conclusion does not rest on the noisy mean:

- **every D1 seed is above every B seed** — D1's *smallest* seed (15535) is still **1.28×B's
  largest** (12889);
- the mean gap is +1.23× the larger own sd — and that denominator is D1's own sd (8284), the
  largest in the project (CV 37%); against B's own sd the gap is 15×;
- D1 did it at **19/19/19 keyframes**, identical to both anchors, so no coverage confound
  (contrast SWEEP's S6 at 16/18/18).

D1 also did **not** trade fidelity for rate: both degradations are inside margin
(+0.554 cm = 0.31×, +0.109 dB = 0.39× of margin). It simply never approached B's rate.

### 4.2 What actually moves the rate: the admission budget, and only in combination

2×2 factorial, multiplicative effects vs A0:

| | `densify` default | `densify` 5e-4 |
|---|---|---|
| **`ttl` 5 (default)** | A0 **1.00×** | D1 **0.98×** |
| **`ttl` 1** | D0 **0.73×** | D2 **0.57×** |

Interaction = 0.57 / (0.73 × 0.98) = **0.80× — super-additive**: the densify throttle is inert
on its own and only bites once the admission budget is squeezed. Read as a direction, not an
estimate (3 seeds, 2 df, and D1's own sd is huge).

Neither cell that touches `ttl` is a configuration a competitor would ship: at `ttl`=1 the
prune arm promotes **zero** candidates on every seed (`promoted` 135 → 0) and its end-of-run
residue collapses 23927 → 5000. "Insert every candidate, then delete it one keyframe later" is
what the baseline has to degenerate into to get within 1.37× of B.

And the one cell that gets into B's rate band pays for it: **D2 fails the PSNR margin**
(+0.359 dB > 0.28) **and** ran 17/18/17 keyframes against the anchors' 19/19/19 — the same
coverage caveat S6 carries.

### 4.3 Consequence: `r2_p03_sweep.md` §4's densification inference is refuted

SWEEP §4 reasoned indirectly — S2(`ttl`1) = 1.13×B, S6 = 0.63×B, "the only channel that
separates them is densification" ⇒ **"a plain densify throttle on the baseline captures the
compactness win without the deferred mechanism."** Two things are now wrong with it:

1. **Measured, that is false.** The densify throttle alone gives 0.98×A0 (§4.1). It cannot
   capture the compactness win, on its own, at all.
2. The premise was also mis-stated: S6 differs from S2 by **two** knobs (`gaussian_th` 0.9 *and*
   `densify_grad`), not one, so "the only channel" never followed from that pair even
   arithmetically.

A retraction note has been added to `r2_p03_sweep.md` §0; its data, its pre-declared rule and
its dominance verdict are untouched — what is retracted is an inference drawn in prose.

**Correspondingly, §3.6's "the baseline only reaches us by importing our admission budget and
detuning densification" is upgraded from narrative judgement to measurement**, in this exact
form: on this sequence, the generic knob contributes nothing alone; all of the movement toward
B's operating point requires `ttl`, the candidate lifecycle's own admission budget, and even
`ttl` + densify only reaches B's *noise band* while failing the vacated-PSNR margin.

Per §2 branch 3, **P1 `R2-P03-CENSUS` is worth running**: there is a deferred-specific
component left for it to attribute. GO/KILL remains the user's.

### 4.4 The compactness corollary, third independent campaign

B vs A0, in-campaign: **−46.6%** Gaussians (13.02× the larger own sd, 3/3, per-seed ranges
non-overlapping: A0 min 22159 > B max 12889), **−20.1%** peak VRAM (10.29×, 3/3), **+8.5%**
FPS (2.87×, 3/3), at **19/19/19 keyframes on both arms**. In this campaign B is also nominally
*better* than A0 on both decision metrics — vacated PSNR **+0.399 dB** (1.54×, 3/3, i.e. beyond
the 0.28 margin in B's favour) and vacated depth **−1.301 cm** (1.10×, 3/3) — which is evidence
against the "under-reconstruction" reading of the smaller map, though one campaign on one
sequence is not enough to bank it as a claim.

### 4.5 Ratios drift too — the README rule needs its magnitude stated

`D0_ttl1` re-ran SWEEP's `S2_ttl1` **config file verbatim**. Its ratio to the in-campaign B
anchor: **1.37×B here vs 1.13×B there — the ratio itself moved 21%.** Same picture on the other
reusable ratios:

| quantity | R2-P02-PREFLIGHT | R2-P03-SWEEP | R2-P03-DECOMP |
|---|---|---|---|
| B vs A(0) compactness | −55.2% | −54.3% | **−46.6%** |
| A0 ÷ B | — | 2.19× | **1.87×** |
| `ttl`=1 rung ÷ B | — | 1.13× | **1.37×** |

So the durable rule earned in SWEEP §5 ("absolutes are campaign-local, report ratios") is
right in its ordering but was stated too strongly: **ratios are more stable than absolutes, not
stable.** On this stack a ratio carries ~15–20% campaign-to-campaign drift, which is why every
cross-campaign statement in this file is labelled and none of them is load-bearing. `README.md`
has been updated with this measurement.

**Practical consequence for the one comparison this campaign could not make in-campaign:**
D2 (`ttl`+densify) = 1.07×B here vs S6 (`ttl`+densify+`gth`) = 0.63×B there suggests
`gaussian_th` carried a large part of S6's dominance — the gap (70%) is well outside the
measured ratio drift (~20%) — but it is still a cross-campaign inference. Making it a
measurement costs **3 runs / ~40 min** (an S6 replicate in this campaign) and is offered, not
assumed.

> **[RETRACTION 2026-07-31 by `R2-P03-S6REPL` §4.2 — the paragraph immediately above is REFUTED
> and is kept verbatim only for provenance.]** That measurement was made (9 runs, S6 and D2 and a
> fresh B anchor, all 3 seeds, all in one campaign): **`gaussian_th` contributed nothing measurable
> to the rate** — S6 ÷ D2 = **0.99×**, −0.07× the larger own sd, per-seed 1/3. The 70% gap read here
> was **drift, not `gth`**, which is exactly what the cross-campaign caveat in this same paragraph
> warned about; the caveat was right and the suggestion it carried was wrong. The ~20% drift
> budget quoted above has itself been widened to ~30% by that campaign's two new datapoints.
> **Everything else in this file — the data, the pre-declared rule, the 0/4 dominance verdict and
> the branch-3 landing — is untouched.** What S6REPL did measure is that at ttl=1 the native
> opacity prune is what keeps the arm inside the *fidelity* margins (`r2_p03_s6repl.md` §4.4),
> a descriptive post-hoc observation, not a verdict.

### 4.6 One flag, and why it is not a defect

The mechanism check reports `D1_densifyonly` as "moved the candidate ledger: NOT
knob-isolated". The move is `pending_final` 23927 → 23308 = **−2.6%**, against a 2% threshold,
and it is disjoint from A0's own seed spread (A0 23728–24148 vs D1 23247–23410). It is real and
it is a **downstream** effect: a differently-densified map changes which pixels count as
already explained, which slightly changes candidate creation. It is not a config leak — G2
confirms only `densify_grad_threshold` differed in the dumped config on all three seeds, and
`tests/test_r2_p03_decomp_configs.py` pins the resolved diff. For scale, the `ttl` cells move
the same quantity by **−79%**. The check is doing its job by being tight; the cell is
knob-isolated in the sense the decomposition needs.

### 4.7 What this campaign does *not* say

- It does **not** overturn SWEEP's verdict. S6 was not re-run here; **S6 still dominates B**,
  and `02-method.md`'s decision tree still sits literally at branch **D**. What changed is what
  the dominance *means*: the dominating configuration needs the deferred arm's own admission
  budget in a degenerate setting (`promoted`=0), plus a native prune, and it covered fewer
  keyframes.
- One sequence, one frozen trajectory, PSNR ≈ 14.5 regime, arm A pressurised only (P2 exists
  to test the regime question). 3-seed sd carries 2 df. D1's own rate CV is 37%.
- Post-hoc and non-preregistered: the cells were chosen after seeing SWEEP. Only the judgement
  rule is inherited, and it is inherited by import.

## 5. Provenance

- Launch commit **`5e789a5`** (the frozen-apparatus commit: §1–§3, configs, runner, readout and
  the 9-test contract were all on disk before the first run); worktree clean — the runner
  refuses to start otherwise. **No live code, config or knob value changed during the 3.2 h.**
- Gates G1–G4 are **imported** from `scripts/r2_p03_sweep.py`, not re-implemented: G1 ATE ==
  2.0618 ± 0.02 on every run, G2 the config the run *dumped* carries the cell's knob values,
  G3 vacated support/frames non-zero, G4 rate present. Gate lines land in the campaign's
  `sweep.log`, which is the intended proof that one harness policed both campaigns.
- GO/KILL and narrative remain the user's (prereg §9, 08-04 date gate).
