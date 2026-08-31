# P3-S6X — does the S6 knob group still beat arm B once the regime can charge for it?

> **Status: §1–§3 are PRE-RUN DECLARATIONS, committed before the first GPU run of this
> campaign. They are not editable afterwards.** §4 holds results and is empty until batch 1
> lands. If a reading here turns out to be badly posed, the honest move is the one
> `r2_p03_s6repl.md` §4.4 already made once in this project: record the limitation in §4 and
> report the branch as it landed, rather than retro-fitting §2.
>
> Campaign ID `P3-S6X` · plan `P3` · results root `results/runs/P3/P3-S6X/` ·
> apparatus: runner `scripts/p3_s6x.py`, readout `scripts/p3_s6x_readout.py`, contract
> `tests/test_p3_s6x_configs.py` (17 tests, E0 green), configs
> `configs/rgbd/experiments/p3_s6x/p3s6x_s6_{6 seqs}.yaml` (the only new configs).
> **Post-hoc + non-preregistered ladder-wise** in the same sense as P0/P0.5/P0.75/R2-P04: it is
> chosen after seeing those campaigns, does not join the pre-declared H1 ladder, and cannot
> alter the R2-P02 H1 three-gate record. What *is* pre-registered is this file's §2.

---

## §1 Why this campaign exists

`S6_maxpress` is the single configuration in this project that ever pressed below arm B's
operating point, and it did so twice:

| campaign | S6 rate vs B | per-seed | degradations (margins 1.56 cm / 0.28 dB) | verdict |
|---|---|---|---|---|
| `R2-P03-SWEEP` (22 run) | **0.63×B** | 3/3 | −0.176 cm / −0.043 dB | DOMINATES B |
| `R2-P03-S6REPL` (9 run) | **0.81×B** | 3/3 | −0.605 cm / +0.110 dB | DOMINATES B |

That is why the compactness headline is dead: a **tuned baseline** reached our budget without
paying for it, and the decision tree in `02-method.md` sits at narrative D as a direct
consequence. `R2-P03-DECOMP` then attributed the rate advantage: the generic densify throttle
alone does nothing (0.98×A0), `gaussian_th` contributes nothing on the rate axis (0.99×,
S6REPL Q1), and the whole effect is `ttl_keyframes=1` **plus** the densify throttle, interacting
super-additively (0.80×).

**And `ttl=1` is not a free knob.** DECOMP and S6REPL both measured what it does to the prune
arm's candidate lifecycle: `promoted` = **0 on every seed**, residue **23927 → 5000**. The
baseline reaches B's budget only by degenerating into insert-everything-then-delete-one-keyframe-
later. Both campaigns already say so in those words.

**The hole.** All 46 runs of R2-P03 ran on **one sequence** (Bonn balloon), at PSNR ≈ 14.5, under
an **injected RGD trajectory** — `Oracle.pose_file` set, camera learning rates zeroed. So
`ate_rmse_cm` was **2.0618 on every one of the 46 runs**, identical for every arm, by
construction. A baseline that buys rate by degrading the map **cannot be charged for it in that
regime**: the degraded map has no channel to the pose. Open defect #9 records the narrower
version of this ("replicated on one sequence, never tested cross-sequence"); the regime point is
sharper than the sequence point.

Self-tracked, the channel exists. `ttl=1` collapses the map the tracker refines against, and the
keyframe schedule is itself covisibility-driven, so a degraded map changes *which* frames become
keyframes. Whether that costs anything is **unmeasured** — and it is the only unmeasured thing
standing between "the compactness headline is dead" and "the compactness headline died in a
regime that could not price the baseline's side of the trade".

**The question, one sentence:** on the combined backbone, self-tracked, across the main table's
6 dynamic sequences — does S6's rate advantage over arm B survive, and does its ATE hold?

Both answers matter and neither is the one being hoped for:
* if the rate advantage survives **and** ATE holds, the headline stays dead and is now dead in
  the operating point a competitor would actually use — which is worth knowing **before** writing,
  and gets written as our own limitation rather than a reviewer's;
* if it does not, that is a *scope correction* to a verdict measured elsewhere, not a rescue of
  a claim — and §2 fixes in advance what may and may not be said about it.

---

## §2 Pre-declared readings — WRITTEN BEFORE THE FIRST RUN

### §2.0 The unit of judgement is the sequence, not the campaign

Discipline ⑨ exists because this project already measured compactness pointing in **opposite
directions** on two sequences (balloon 0.511× vs pt2 1.069×). A cross-sequence mean would read
two opposite directions as "no difference". So:

* every reading below is made **per sequence**;
* a **campaign-level** statement requires **6/6 sequences agreeing**;
* anything else is **sequence-dependent** (branch **X4**) and only per-sequence statements may
  be made — including in the paper.

### §2.1 The two axes, and their references

| axis | statistic | reference arm | rule |
|---|---|---|---|
| rate + fidelity | `refined_num_gaussians`, `static_vacated_depth_l1_pen_cm`, `static_vacated_psnr` | **`deferred`** | the SWEEP dominance rule **by import** (`scripts/r2_p03_sweep_readout.DECISION`, margins 1.56 cm / 0.28 dB): dominates iff mean rate ≤ B's mean **and** both signed degradations ≤ margin |
| ATE (**new**) | `ate_rmse_cm` from `tables/tracking_raw.csv`, full trajectory | **`prune`** | no-harm band **50%**, imported from `scripts/r2_p2_t_readout.ATE_NOHARM_PCT` |

**Why ATE is referenced to `prune`, not to `deferred`.** S6 *is* the prune arm with three knobs
turned; the prune anchor holds the lifecycle fixed and isolates what the knobs cost tracking.
Referencing `deferred` instead would hand S6 free credit on every sequence where deferred is
already the worse tracker — and in P2-T deferred was worse on **6/6**. The deferred-referenced
ATE contrast is printed as SECONDARY and **decides nothing**.

**On the 50% band, stated now so it cannot be re-read later:** it is a *catastrophe* threshold,
not an indistinguishability threshold — exactly the reading HANDOFF already fixed for P2-T. A
result inside the band is "no catastrophic tracking loss detected", never "ATE unaffected". The
per-seed sign count and the ATE own-sd are printed next to every ratio so a 1.4× on a noisy
sequence is not read as a 1.4× on a quiet one.

**Headline ATE 口径, fixed:** `tracking_raw.csv` `ate_rmse_cm` (full trajectory). Not the
console's keyframe "RMSE ATE". Not a KF0-gauge or single-anchor camera-centre RMSE — that
口径 cost this project a **sign error** three days ago (`p2_dba_gn_umeyama_prereg.md`: an online
baseline read 85.86 cm of which ~96% was global alignment, turning a +9.6 cm degradation into a
−1.86 cm "improvement").

### §2.2 The four branches, bound to their meanings now

Let **R** = "S6 dominates `deferred` on rate + both fidelity margins" and **A** = "S6's ATE vs
`prune` is inside the 50% band", both evaluated per sequence.

**(X1) R and A on 6/6 — S6 TRANSFERS.**
The compactness headline stays dead, and is now dead in the self-tracked operating point rather
than only under a frozen trajectory. **Disposition:** the paper reports this as **our own
measured limitation**, in the section that already scopes compactness to insert-then-prune
(R2-P04-MASKRATE's M2 consequence). We write that a tuned insert-then-prune baseline reaches the
deferred arm's map budget at no detectable tracking cost across 6 sequences, and that the
contribution therefore is **not** map compactness. No wording anywhere in the paper may claim
compactness as a differentiator against a tuned prune baseline. This is the branch that costs
the most and it is written exactly as it lands.

**(X2) R on ≥1 seq but A fails there — S6 BUYS RATE WITH TRACKING.**
S6 reaches the budget and the newly-priced axis charges it. **Disposition:** compactness returns
as a **Pareto statement only** — "at matched map size, the tuned baseline is off the frontier on
ATE" — reported per sequence, never as a global claim, and always alongside three things:
(i) SWEEP's and S6REPL's verdicts **stand unretracted** (they were legitimate measurements in
their own regime; this is a *scope* result, and the honest sentence is "S6 dominates under a
frozen trajectory and pays for it under self-tracking", not "S6 was wrong");
(ii) the keyframe column, because part of S6's rate advantage was always less coverage
(16/18/18 and 18/18/16 vs 19/19/19 in the two prior campaigns) and under self-tracking the
keyframe schedule is *also* a tracking-relevant quantity;
(iii) an explicit statement that rate and ATE are **jointly determined** here and this campaign
cannot decompose them (see §3).
**Not licensed by this branch:** "our method tracks better". The deferred arm's ATE is not the
comparison; the comparison is S6 against its own untuned prune base.

**(X3) R fails on ≥1 seq — the rate advantage does not transfer there.**
S6 does not reach `deferred`'s budget on that sequence. **Disposition:** by the same wording
S6REPL fixed for its own branch (R2), **nothing is retracted**: SWEEP and S6REPL measured what
they measured, in-campaign, under a rule imported unchanged. The honest statement becomes
"S6 dominates arm B on balloon under a frozen trajectory, and on *k* of 6 sequences when
self-tracked", with both regimes named every time. It does **not** license "the baseline cannot
reach our budget" — one sequence where it does is enough to forbid that sentence, and balloon
already is that sequence.

**(X4) mixed across sequences — SEQUENCE-DEPENDENT.**
The expected-by-default outcome given discipline ⑨. **Disposition:** report the per-sequence
table, make no campaign-level claim, and fold it into the narrative D′ boundary language the
project already uses ("sequence-dependent boundary"). Specifically, it may **not** be summarised
as "S6 mostly transfers" or "S6 mostly fails"; the count is reported with the sequence names.

### §2.3 Secondary readings — reported alongside, not decision-grade

* **`G_def/G_prune` re-measured in-campaign** on all 6 sequences. This is the headline compactness
  quantity and it is re-measured rather than carried over from P2-T, because same-config ratios on
  this stack have drifted **+21% / +29% / −23%** between campaigns. A P2-T-vs-P3-S6X difference
  below ~30% is **not** evidence of anything (README threshold).
* **Candidate ledger**: does `ttl=1` still drive `promoted` → 0 and collapse the residue? If it
  does, the intervention is mechanically the same one and only the regime changed. **If it does
  not, every reading above carries that caveat** — a differently-behaving knob is not a migration.
* **Keyframe count per run**, for the reason in (X2)(ii).
* **VRAM / FPS**, descriptive. S6 lowers the Gaussian count, so it should sit below the project's
  measured 4.09 GB ceiling; this is a feasibility note, not a result.

### §2.4 Seeds — what this batch may and may not conclude

**Batch 1 = seed 0 only, 18 runs. It is SCREENING and calls no branch.** Discipline ⑤ is not a
formality here: SWEEP's S6 at n=1 decided a dominance verdict **wrongly in both directions at
once** (that seed was simultaneously the smallest map and the worst PSNR). Batch 1 produces a
**direction to report**, and the branch above is called only at 3 seeds (batch 2, 36 runs), which
needs the user's GO. The runner does not chain batch 1 into batch 2.

---

## §3 Scope — what this campaign deliberately cannot say

**Declared in advance so it cannot be claimed later.**

1. **Rate and ATE are jointly determined here; this campaign cannot decompose them.** Under
   self-tracking a degraded map changes the pose, the pose changes the covisibility test, and the
   covisibility test changes which frames become keyframes — which changes the rate. That coupling
   *is* the treatment (it is precisely what the frozen trajectory switched off), but it means a
   rate difference here is not the clean map-admission measurement R2-P03 made. Any sentence of
   the form "S6 admits *k*% fewer Gaussians" must be qualified with "at a different keyframe
   budget and a different trajectory". The clean map-admission numbers remain SWEEP's / S6REPL's.
2. **No frozen-pose arm, so no within-campaign regime contrast.** This campaign measures the
   self-tracked regime only. The comparison against the frozen regime is necessarily
   **cross-campaign** and therefore carries the ~30% ratio-drift note; it may be stated as a
   regime difference in prose, never as a measured effect size.
3. **No A0 / untuned-prune-vs-deferred claim beyond what is re-measured here.** The `G_def/G_prune`
   column is this campaign's own; it does not extend P2-T's numbers and must not be pooled with
   them.
4. **Nothing here touches H-D, P2-T, P2-SF or the DBAphoto closure.** No record in those campaigns
   is re-read, re-run or amended by this one. H-D stays INDETERMINATE.
5. **Nothing here touches the H1 three-gate record** (prereg §6: no headline swapping).
6. **6 dynamic sequences, Bonn only, one backbone, RTX 2060.** No static-sequence row, no
   cross-backbone claim, and FPS is a 2060 number that may not be tabled next to competitors'
   3090/4090 figures (VRAM may, and "runs inside 6 GB" is itself the claim).
7. **This campaign cannot rescue a contribution.** Even in branch (X2) the result is a *scoping*
   of a negative, not a positive claim. The paper's contribution question is not decided here and
   GO/KILL + narrative remain the user's.
8. **3-seed sd carries 2 df.** Every "× own sd" in §4 is a crude interval and is labelled as one.

### §3.1 Apparatus, and the two things it makes impossible

* **Three arms** — `prune` and `deferred` are P2-T's frozen run configs **by identity**
  (`scripts.r2_p2_t.ARMS`); `s6` inherits from the `prune` run config and adds exactly the three
  `S6_maxpress` knobs, whose **values are imported by identity** from
  `scripts.r2_p03_sweep.LEVELS["S6_maxpress"]`. So the campaign cannot migrate a *nearby*
  baseline under S6's name, and the anchors cannot drift from the table they anchor.
* **Both anchors re-run here (12 of the 18 batch-1 runs).** Not borrowed from P2-T. The readout's
  loader is unit-tested to **ignore a P2-T results file** placed in its own out-dir, and the
  runner flags any `s6` cell lacking both in-campaign anchors as NOT READABLE. This is README's
  cross-campaign ban made executable rather than promised.
* **The pose gate is INVERTED relative to R2-P03.** There the harness asserted the trajectory was
  frozen (ATE == 2.0618 ± tol); here G2 asserts every run genuinely self-tracked — empty
  `Oracle.pose_file`, `gt_pose` off, non-zero camera-delta lrs **read from the config the process
  dumped**, and an ATE that is *not* sitting on the injected constant. A run that silently froze
  would answer the old question wearing the new question's label. The E0 contract also pins that
  SWEEP's S6 config resolves *with* an injected trajectory, so the regime difference is a tested
  fact and not a claim in a comment.
* **Harness gates never abort on a result** (G1 exit, G2 self-tracked, G3 knobs live, G4 rate
  present, G5 ATE present, G6 vacated support non-zero, G7 activity). An arm that prunes hard and
  loses fidelity, or that drifts, is the measurement. Catastrophic seeds (ATE > 100 cm or
  G > 3× arm-median) are **flagged and kept, never dropped**.
* **Budget**: batch 1 = 6 seqs × 3 arms × seed 0 = **18 runs ≈ 9.5 h** on the RTX 2060 (P2-T
  measured 25–44 min/run; mv_no_box2 is the long one). Batch 2 = seeds 1,2 = 36 runs ≈ 19 h and
  is **not launched from batch 1**. Memory is not the constraint — P2-T's whole-project ceiling was
  4.09 GB of 6 GB on the prune arm, and S6 lowers the Gaussian count.
* **Live code is frozen for the campaign** and the worktree must be clean before GPU (the runner
  refuses on a dirty tree). No mechanism is added or changed by this campaign: it is three knobs
  in a config.

---

## §4 Results — batch 1 (seed 0, 18 runs, SCREENING ONLY)

> **18/18 exit 0, G1–G7 all green, ANCHOR ok, 0 catastrophic/collapse.** Wall ~10.6 h on the
> RTX 2060 (03:31→14:08), within the ~9.5 h estimate. **Single seed ⇒ DIRECTION, not a branch.**
> Discipline ⑤ and §2.4: SWEEP's S6 at n=1 once decided a dominance verdict wrongly in both
> directions at once. The branch is called only at 3 seeds (batch 2, needs the user's GO).

Readout written to `results/runs/P3/P3-S6X/p3s6x_report.md`; raw `p3s6x_results.jsonl`.

### §4.1 The headline: the regime charged it, on 4 of 6 sequences

In R2-P03's 46 runs `ate_rmse_cm` was 2.0618 on every run — S6 could buy rate by degrading the
map with no channel to the pose. Self-tracked, the channel exists. It was charged:

| seq | KF (all three) | s6 vs deferred | vac_depth deg (≤1.56) | vac_psnr deg (≤0.28) | ATE s6/prune | ATE ok? | verdict (n=1) |
|---|---|---|---|---|---|---|---|
| balloon | 88/88/88 | **0.435×** | −1.966 ✓ | +0.168 ✓ | 1.121× | ok | **DOMINATES, ATE HOLDS** |
| balloon2 | 94/94/94 | **0.455×** | −1.365 ✓ | +0.258 ✓ | 1.032× | ok | **DOMINATES, ATE HOLDS** |
| mv_no_box | 156/156/156 | **0.552×** | **+4.861 ✗** | **+0.470 ✗** | **1.636×** | **BREACH** | NOT-DOMINATED |
| mv_no_box2 | 188/188/188 | **0.173×** | **+3.971 ✗** | **+1.507 ✗** | 1.222× | ok | NOT-DOMINATED |
| pt1 | 116/117/118 | **0.265×** | **+1.626 ✗** | **+0.962 ✗** | 1.087× | ok | NOT-DOMINATED |
| pt2 | 114/114/115 | **0.185×** | **+1.770 ✗** | **+1.732 ✗** | **1.767×** | **BREACH** | NOT-DOMINATED |

Campaign count (n=1, screening): **dominates + ATE holds = 2/6** (balloon, balloon2);
**rate reached but fidelity broken = 4/6** (the four longer/harder sequences); **X2 (rate ok,
ATE breach specifically) = 0/6** — every ATE breach co-occurred with a fidelity breach.

### §4.2 What is NOT like the old regime (read before any branch)

1. **The keyframe caveat that licensed the old verdict's interpretation is GONE here.** SWEEP and
   S6REPL measured S6 covering the sequence with FEWER keyframes than the anchors (16/18/18 and
   18/18/16 vs 19/19/19), so part of S6's rate advantage was always "less coverage". Here **the
   three arms are keyframe-identical on 4/6 sequences** (88/94/156/188), and differ by only
   ±1–2 KF on pt1/pt2 — a tracking-relevant, not a coverage, difference. So on 4/6 this is a
   **same-budget** rate comparison, the cleanest any S6 campaign has produced, and S6 STILL
   reaches B's budget on all 6. The rate advantage is real and not a coverage artifact here.
2. **The fidelity break is the new signal, and it is large.** On the 4 NOT-DOMINATED sequences
   S6 breaks BOTH decision margins, often by multiples (mv_no_box2 vac_psnr +1.51 = 5.4× margin;
   pt1 +0.96 = 3.4×; pt2 +1.73 = 6.2×). Under the frozen trajectory no S6 run ever broke a
   margin — fidelity was "nominally better than B" in both prior campaigns. The self-tracked
   channel that was switched off in R2-P03 is now visibly carrying a fidelity cost.
3. **The ATE axis only charged it on 2/6** (mv_no_box +63.6%, pt2 +76.7%, both beyond the 50%
   band). On the other 4, ATE moved ≤+22% and stayed in band even while fidelity broke. So ATE
   is the **less sensitive** of the two new axes, not the more sensitive — a reader's intuition
   that "degraded map → worse tracking first" is not what these 6 data points show; fidelity
   broke first and more consistently.
4. **The ttl=1 degeneracy reproduced on all 6 sequences, mechanism-intact.** `promoted` = **0**
   on every s6 run, residue collapsed to `pending_final` = **5000** on every s6 run (vs 23k–25k
   on the anchors). The intervention this campaign migrated is mechanically the same one DECOMP
   and S6REPL measured: insert-everything-then-delete-one-keyframe-later. Only the regime
   changed; the knob did not.

### §4.3 The direction this points (NOT a branch — n=1)

The seed-0 picture is **mixed (X4-leaning)**, but with a *structured* mix rather than noise:
S6 dominates cleanly on the two **short/easy** balloon sequences (where P2-T ATE was ~3–5 cm
and the tracker is robust) and breaks fidelity on the four **longer/harder** sequences
(mv_no_box×2 / pt1 / pt2, where P2-T ATE was 5–11 cm or the mover is a person-only track).

Per §2 the unit of judgement is the **sequence**; a campaign-level statement needs 6/6.
Batch 1 gives **2/6 dominate+hold** and **4/6 break fidelity** — neither threshold met, so no
campaign-level claim is licensed. What is licensed is the per-sequence direction above, which
is exactly the kind of sequence-dependent boundary the narrative D′ already uses.

### §4.4 What this does NOT do (held by §3, restated against the data)

* It does **not** retract SWEEP or S6REPL. Those measured what they measured in their own
  regime; this is a scope result. Per §2 (X3 wording), the honest sentence is "S6 dominates arm
  B on balloon under a frozen trajectory, and on *k* of 6 sequences when self-tracked" — and at
  n=1 the *k* here is "2 dominate cleanly, 4 more reach the rate but break fidelity". The 4/6
  break does NOT license "the baseline cannot reach our budget" — all 6 reached it.
* It does **not** license a compactness headline revival. On 4/6 S6 reaches B's budget AND
  breaks fidelity, which is the X2-shaped Pareto statement — but §2 (X2) binds that to
  per-sequence reporting with the keyframe column (clean here: same KF on 4/6) and the
  rate-ATE coupling caveat (§3.1). And the 2/6 where it dominates cleanly (balloon, balloon2)
  are the same two sequences the headline already died on.
* It does **not** decide batch 2. The branch needs 3 seeds; the 4/6 fidelity break is a
  direction strong enough to be worth confirming (4/6 same-direction at n=1, no opposite
  example), but SWEEP's n=1 lesson forbids calling it now. GO/KILL for batch 2 is the user's.

### §4.5 The `G_def/G_prune` column, re-measured in-campaign (screening, n=1)

| seq | G_def/G_prune (this, n=1) | P2-T (3-seed) | note |
|---|---|---|---|
| balloon | 0.748× | 0.498× | lower here but n=1; in-band direction |
| balloon2 | 0.622× | 0.910× (INDET) | flips toward <1 |
| mv_no_box | 0.731× | 0.773× | agrees |
| mv_no_box2 | 1.037× | — (P2-T) | n=1, ~1 |
| pt1 | 0.635× | 0.794× | agrees, lower |
| pt2 | 0.910× | 0.467× (n=1 in P2-T seed0) | flips opposite |

Per §3.3 and README's cross-campaign ban this column is this campaign's own and is **not**
pooled with P2-T's. With one seed the per-seed sign is the only stable quantity; it agrees
with P2-T's 3-seed direction on 3/4 shared judgable sequences and flips on balloon (lower)
and pt2 (higher) — exactly the kind of seed-instability discipline ⑨ and P2-T's own
INDETERMINATE call already warn about.

### §4.6 Next step (GO/KILL = user)

Batch 2 = seeds 1, 2 = 36 runs ≈ 19 h on the 2060. The seed-0 direction is strong enough on the
fidelity axis (4/6 break, same direction, no opposite example) to be worth confirming to a
verdict; the ATE axis is softer (2/6). Whether that confirmation is worth ~19 h of GPU before
the 08-06 writing start — and whether the writing plan changes either way — is the user's call.
