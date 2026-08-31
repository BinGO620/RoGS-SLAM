# Adversarial review: P2-T strongest defensible POSITIVE contribution

> Third-party reviewer, MMM 2027 lens. Skeptical, concrete, blind-spot hunt.
> Read against: hd_coverage_prereg.md, hd_coverage_anchor.md, registry.csv
  P2-T row, 02-method.md decision tree, yolo_backend_decision.md §3-§4.
> Status: 35/36 done, 3-seed means supplied by author. This review treats
  those means as authoritative.

------------------------------------------------------------------------
## Q1 — With H-D INDETERMINATE and deferred not beating prune on ATE 6/6,
##      what is the HARDEST positive contribution? Which is headline?

Short answer: **(b) is the headline, (c) is its load-bearing measurement,
(a) is the floor that makes (b) publishable. Do NOT lead with (a) alone —
it is "we ported a backbone" and reviewers at MMM will read it as
incremental engineering. Do NOT lead with (c) alone — one sequence
(balloon) is a hypothesis-generation point per your own prereg §9, so a
balloon-only compactness claim is post-hoc. The defensible shape is (b)
with (c) as the single sharpest instance and (a) as the no-collapse
scaffold.**

Why (b) is the hardest positive, and why it survives INDETERMINATE:

1. **INDETERMINATE kills the rank-correlation claim, not the boundary
   claim.** Your prereg §4 defines CONFIRMED as needing ≥2 judgable same-
   direction seqs AND no (a)/(b) coverage-rank flip. You got 3 judgable
   same-direction seqs (balloon 0.498, mv_no_box 0.773, pt1 0.798) but
   the (a)/(b) flip on pt1/pt2 fires the INDETERMINATE escape. That
   kills "coverage monotonically orders the ratio." It does NOT kill the
   weaker, more defensible statement: **"compactness direction is not
   universal; it is sequence-dependent, and the direction co-occurs with
   a measurable offline property of the mask-mover relationship."** That
   is a falsifiable applicability-boundary claim, and it is the first
   measured one for 3DGS lifecycle choice. This is a legitimate MMM-
   grade methodological contribution *even at INDETERMINATE* — but only
   if you reframe the headline away from "H-D confirmed" toward
   "lifecycle choice has a measurable applicability boundary, stratified
   by an offline oracle; the simple monotone version of the stratifier
   is not yet supported."

2. **The thing that makes (b) concrete rather than hand-wavy is that you
   pre-registered the stratifier BEFORE the ratios existed and the
   coverage anchor is frozen.** That converts "we noticed a pattern"
   into "we predicted a pattern, froze the prediction, and report the
   pattern's support boundary." Reviewers attack post-hoc pattern
   mining; they cannot attack a pre-registered prospective check that
   reports its own failure mode. The INDETERMINATE result is, para-
   doxically, the asset: it shows the discipline is real (a post-hoc
   paper would have cherry-picked to CONFIRMED). Lead the methodology
   section with the prereg apparatus, not with the ratios.

3. **(c) alone is fragile because balloon is seen data (prereg §9).**
   balloon 0.498 (−50%) is your single biggest compactness effect and
   your only sub-0.6 ratio. It is also the sequence that generated the
   H-D hypothesis. A reviewer who reads prereg §9 will say "the one
   strong effect is on the hypothesis-generating sequence." mv_no_box
   (0.773, unseen) is your strongest *independent* compactness signal —
   smaller magnitude but clean provenance. **Frame (c) as "compactness
   <1 reproduces on unseen low-coverage seqs (mv_no_box, pt1), with
   balloon as the largest-magnitude instance" — never as "balloon shows
   −50%."** Order matters here; provenance matters more than magnitude.

How to avoid the "method didn't win" reading — three concrete moves:

- **Drop "beats prune" framing entirely.** The contribution is not
  "deferred wins." The contribution is "two lifecycle arms are measur-
  ably indistinguishable on ATE (6/6 in-band) but diverge on compactness
  in a sequence-dependent way that tracks an offline mask property."
  That is a *measurement* contribution, not a *victory* contribution.
  MMM accepts measurement contributions if you don't oversell them.

- **Make the headline a 2×2, not a 1×N.** Rows = {low-coverage regime,
  high-coverage regime}; columns = {compactness, ATE}. Low-coverage row:
  compactness <1 (3/3 judgable), ATE in-band. High-coverage row:
  compactness indeterminate, ATE in-band. The 2×2 is the contribution.
  A 1×6 "deferred vs prune" table invites the "didn't win" read; the
  2×2 invites the "here is the boundary" read.

- **Carry the no-harm band as a property of the boundary, not of
  deferred.** "ATE no-harm 50% band all pass" reads as a defensive
  caveat. "Across the measured applicability boundary, ATE remains
  within the pre-registered no-harm band on 6/6 sequences" reads as a
  scope statement about where the boundary is *safe to deploy across*.
  Same numbers, different claim shape.

The single biggest risk to (b) as headline: **the (a)/(b) coverage-rank
flip is the weak point.** A reviewer will say "your stratifier isn't
even internally consistent across two reasonable mover definitions, so
the 'measurable offline property' isn't actually well-defined." You
cannot rebut this on n=6. The honest move is to make the stratifier's
*instability* part of the finding: "the boundary exists; the simple
per-frame-coverage stratifier is not yet the right operationalization;
±15-frame union coverage flips ranks on the two highest-coverage pure-
person seqs, indicating the stratifier conflates mask sufficiency with
class composition (stated limitation §6.1)." That turns the weakness
into a scoped future-work pointer. Do NOT hide the (a)/(b) flip.

------------------------------------------------------------------------
## Q2 — Add 1-2 Bonn high-coverage pure-person seqs, or accept
##      INDETERMINATE as limitation?

**Recommendation: skip, accept INDETERMINATE as a scoped limitation. Do
NOT add crowd/synchronous.** Confidence 0.7. Three reasons, any one
sufficient:

1. **Cost/risk asymmetry is bad.** 14 days to ddl, each seq = 6 runs ≈
   3h on the 2060, but the real cost is the F@5cm geometry post-proc
   (HANDOFF: cannot run concurrent with SLAM on 6GB) + the readout +
   the H-D re-adjudication + the writing knock-on. You are not buying 3h,
   you are buying ~1.5 days of critical-path time 10 days from ddl. The
   upside is converting INDETERMINATE → CONFIRMED on a hypothesis your
   own prereg §9 admits is "prospective internal check, not independent
   validation." That is a low ceiling for the cost.

2. **Expected value of a high-coverage seq going >1 is low.** Look at
   your own data: the highest-coverage unseen seq is balloon2 (59.4%)
   and it landed at 0.910 INDETERMINATE — the *wrong* direction and
   in-band. pt1 (29.9%) landed 0.798, also <1. **You have zero sequen-
   ces where deferred is judgably >1.** The "high-coverage ⇒ prune
   better (>1)" half of H-D has never fired on any sequence, seen or
   unseen. Adding crowd (which your 3090 baseline data shows is a
   *hard* sequence — MonoGS ATE 65-98cm, and DG-SLAM 22cm — i.e. a
   tracking-collapse regime, not a clean high-coverage regime) is more
   likely to produce a catastrophic seed or another INDETERMINATE than
   a clean >1. synchronous is more plausible as a clean >1 candidate
   (slower, more mask-saturating) but you have no baseline data on it
   at all and the 2060 has never run it. **If you must spend the GPU,
   synchronous is the only defensible pick; crowd is a trap.**

3. **CONFIRMED doesn't actually change the paper much.** Per prereg
   §8 + yolo_backend_decision §3, CONFIRMED upgrades H-D from "one-
   sentence limitation" to "one section." It does NOT unlock YOLO
   sensitivity (that needs §3(ii) user GO on top) and does NOT unlock
   per-KF hybrid (prereg §0.3, explicitly cut). So even the best case
   buys you one section in a paper whose headline is already (b). The
   marginal paper value of CONFIRMED over a well-written INDETERMINATE
   limitation is small. The marginal risk of a catastrophic seed on an
   unfamiliar sequence 10 days out is non-trivial.

**The one scenario where I flip this recommendation:** if the author's
08-04 narrative gate is leaning toward making H-D a *section* rather
than a *sentence* (i.e. the boundary framing in Q1 is the chosen head-
line), THEN one clean synchronous run adds an independent high-coverage
sample and the paper-level value rises. In that case: run synchronous
seed-0 only first (2 runs, ~1h), check it doesn't collapse, and only
then commit to 3 seeds. Do NOT run crowd.

------------------------------------------------------------------------
## Q3 — deferred ATE ≥ prune on 6/6 (in-band): "systematically worse"
##      or "indistinguishable"? Upgrade or hold?

**Upgrade to the honest boundary, but frame positively. Confidence 0.8.**

Why upgrade (do NOT hold "in-band = indistinguishable"):

1. **6/6 same-sign is not indistinguishable in the way "in-band"
   implies.** "In-band" means each pairwise contrast is within the
   pre-registered 50% no-harm band. That is a *per-sequence* state-
   ment. 6/6 same-sign is a *cross-sequence* statement, and it is a
   different statistical object: under a null of "deferred and prune
   ATE are exchangeable," the probability of 6/6 same-sign is 2/64 =
   0.031. Your prereg did not pre-register this sign test, so you
   cannot call it a significant result — but a reviewer *will* notice
   6/6 same-sign and if you have written "indistinguishable" they will
   read it as spin. **Holding "in-band = indistinguishable" in the face
   of 6/6 same-sign is the single most attackable sentence in the
   paper.** Do not write it.

2. **The magnitudes are not all tiny.** pt2 deferred ATE 13.66 vs prune
   9.98 = +36.8%. mv_no_box2 deferred 5.61 vs prune 4.68 = +19.9%.
   pt1 deferred 12.35 vs prune 10.97 = +12.6%. These are real directional
   ATE costs even though none crosses the 50% flag. "In-band" is tech-
   nically true but rhetorically misleading when the worst case is
   +37%. The 50% band was set (prereg §3) to leave headroom above the
   pt2 screening +43.4%; it was a *catastrophe* threshold, not an
   *indistinguishability* threshold. Conflating the two is a category
   error a reviewer will catch.

How to write the upgrade positively — the key is to make the ATE cost
a *feature of the boundary*, not a *defect of deferred*:

- **"Deferred trades ATE for compactness, conditionally."** The trade
  is real but it is *not uniform*: it is largest on the high-coverage
  pure-person seqs (pt2 +37%, pt1 +13%) where compactness is also
  indeterminate — i.e. where deferred has *no compactness upside to
  buy*. On the low-coverage seqs where deferred *does* buy compactness
  (balloon −50% G, mv_no_box −23% G), the ATE cost is 1.3% and 11%
  respectively. **That is a Pareto frontier, not a loss.** Frame it
  as: "deferred is on the compactness-favoring side of an ATE-
  compactness frontier; the frontier is sequence-dependent and the
  sequence-dependence is what H-D attempts to stratify." This converts
  the 6/6 same-sign from "deferred is worse" into "the trade is real
  and we measured which side each sequence is on."

- **Report the sign test honestly as exploratory.** "6/6 sequences
  show deferred ATE ≥ prune; under an exchangeability null the proba-
  bility of 6/6 same-sign is 0.031, but this sign test was not pre-
  registered and the per-sequence contrasts are all within the 50%
  no-harm band, so we report this as a directional observation, not a
  significant ATE regression." This is unattackable: it states the
  thing a reviewer would raise, scopes it correctly, and moves on.

- **Do NOT write "deferred systematically worse on ATE."** That phrase
  concedes the wrong frame. "Systematically" implies a mechanism-level
  ATE defect. Your data does not support mechanism-level ATE defect —
  it supports a *trade*: where deferred buys compactness the ATE cost
  is small; where it doesn't buy compactness the ATE cost is larger.
  That is a frontier, not a defect. The word "trade" is load-bearing;
  use it.

------------------------------------------------------------------------
## Blind spot — the one I would press hardest if I were reviewer 2

**The confound you cannot escape at n=6, and it is worse than the
stated §6.1 class-composition collinearity: the coverage stratifier and
the ATE-cost magnitude are confounded through *tracking difficulty*, not
through mask sufficiency.**

Look at the structure of your own data:
- Low-coverage seqs (mv_no_box 23.1%, balloon 48.2%): ATE 2.58-3.07cm,
  tracking is *easy*, mask leaks mover, deferred compactness <1, ATE
  cost small (1-11%).
- High-coverage pure-person seqs (pt1 29.9%, pt2 18.8%): ATE 9.98-
  13.66cm, tracking is *hard* (long fast person motion), deferred
  compactness indeterminate, ATE cost large (13-37%).

The §6.1 stated limitation says coverage is collinear with class
composition (person-only vs person+object). That is true but it is the
*less* dangerous confound. **The more dangerous one: coverage is also
collinear with tracking difficulty, and tracking difficulty is the
dominant driver of ATE on these sequences.** pt1/pt2 are not just "high
coverage" — they are the sequences where MonoGS itself (your 3090 base-
line) has ATE 6.27-8.62cm on person_tracking, i.e. the backbone is
already near its tracking limit. When the backbone is near its tracking
limit, *any* lifecycle perturbation (deferred's provisional candidates
disturbing densify, or just the map being smaller and thus fewer
constraints) will cost ATE — regardless of mask coverage.

**So the H-D mechanism story ("mask leaks mover ⇒ deferred has dynamic
to block ⇒ compactness") and the alternative story ("hard-tracking
seqs are ATE-fragile to any lifecycle change ⇒ deferred costs ATE there
regardless of mask") predict the SAME data pattern on n=6.** Your
prereg §6.1 does not list this; it lists class composition. A reviewer
who notices that pt1/pt2 are also your two hardest-tracking seqs will
raise this, and "stated limitation" will not cover it because it is not
stated.

This is the blind spot, and it has a sharp implication for Q1's
headline: **the (b) "applicability boundary" claim is only as strong as
your ability to show the boundary is driven by mask coverage and not by
tracking difficulty.** At n=6 you cannot separate them (they are col-
linear). Two things follow:

1. **Do not claim the boundary is a *mask-coverage* boundary.** Claim
   it is a *sequence-dependent* boundary and that mask coverage is *a
   candidate stratifier* whose simple per-frame form is not yet sup-
   ported (INDETERMINATE) but whose existence as *some* offline prop-
   erty is suggested by 3/3 judgable same-direction seqs. That is
   defensible. "Mask coverage stratifies the boundary" is not, at n=6,
   with tracking difficulty collinear.

2. **The cheapest experiment that would actually de-confound this is
   NOT a new Bonn sequence (Q2) — it is a frozen-pose control on pt1
   or pt2.** You already have the apparatus (R2-P03 ran balloon frozen-
   pose; r2_p2_t_readout imports the SWEEP decision family). A frozen-
   pose pt1 run removes tracking difficulty as a variable: if deferred
   still costs ATE under frozen pose, it is a map-level effect (con-
   sistent with H-D's "provisional candidates perturb densify"); if
   deferred ATE cost *vanishes* under frozen pose, the 6/6 same-sign
   is a tracking-coupling artifact, not a lifecycle property, and H-D's
   mechanism story is wrong. **This is one pair of runs (~1h on 2060),
   it is on a sequence you have already run, and it directly tests the
   confound.** It is higher-value than any Q2 high-coverage sequence
   addition. If the GPU budget allows *anything* beyond finishing 36/36,
   this is what it should be — and it can run in the F@5cm post-proc
   gap if you sequence it right. If you cannot run it, name the con-
   found explicitly in limitations: "at n=6, mask coverage is collinear
   with tracking difficulty; the boundary may be driven by either, and
   disambiguating requires frozen-pose controls reserved for future
   work."

That is the blind spot I would press. The Q2 high-coverage-seq question
is a distraction from it; the frozen-pose control is the real test.
