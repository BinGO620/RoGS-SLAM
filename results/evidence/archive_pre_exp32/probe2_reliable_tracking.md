# PROBE2-RT — RGD adaptive-weight tracking (reliable_tracking) OFF↔ON

> Screening, 2026-07-23, RTX2060, direct `slam.py --fast` (paired arm-vs-arm; NOT a manifest/managed run).
> Purpose: does the already-implemented-but-never-evaluated RGD adaptive-weight tracking
> (`utils/reliable_tracking.py`, committed 762dbee) move ATE on the R1-P01 open-set base?
> **Screening only — not a paper method result. Does not touch the R1-P01 frozen contract.**

## Setup

- Configs: `configs/rgbd/experiments/probe2_reliable_tracking/` (self-contained).
- Base = `method_openset_prune` reused field-for-field (lifecycle=prune, ReliabilitySignal on,
  DeferredCommit on). OFF vs ON **effective config differs by exactly `ReliableTracking.enabled`**
  (verified key-by-key with `utils.config_utils.load_config`).
- ON = opacity per-pixel down-weight + projected-border(bbox) view weight + median-inlier residual
  masks, all at `base_config` defaults (opacity_min 0.95 / rgb_median_scale 8 / depth_median_scale 10
  / border 0.40–0.80).
- Metric = `tracking_raw.csv` `ate_rmse_cm` (full-traj headline) + `rpe_trans_rmse_cm`.
- Mechanism confirmed active (not a no-op): balloon ON seed0 = 28838 calls, opacity support ratio
  mean 0.944 / rgb 0.90 / depth 0.89, 0 fallbacks (median masks never collapsed below min_support 0.10).

## Prune-arm result — seeds 0/1/2 (PROBE2-RT-PRUNE)

ATE RMSE (cm), full-traj:

| seq | arm | seed0 | seed1 | seed2 | mean±std | Δ vs OFF |
|---|---|---|---|---|---|---|
| balloon | OFF (RToff) | 29.82 | 32.23 | 30.43 | 30.83 ± 1.26 | — |
| balloon | ON  (RTon)  | 17.73 | 17.56 | 20.74 | 18.68 ± 1.79 | **−12.15 / −39.4%** |
| moving_nonobstructing_box | OFF | 6.96 | 14.30 | 4.80 | 8.69 ± 4.98 | — |
| moving_nonobstructing_box | ON  | 6.46 | 3.50 | 4.46 | 4.81 ± 1.51 | **−3.88 / −44.7%** |

RPE_trans (cm): balloon OFF 2.59 → ON 2.61 (flat); mv_no_box OFF 2.39 → ON 1.82 (down).

### Read (screening, not a verdict)

- **balloon = decisive**: OFF/ON distributions **do not overlap** across 3 seeds (max ON 20.74 <
  min OFF 29.82); OFF variance tiny (±1.26) → the −39% is separated from run-to-run noise, not luck.
  balloon is intrinsically a high-ATE seq here (E2 prune balloon 25.68, same band) → this is
  "improve our own base", NOT "approach SOTA" (abs 18.7cm still far from ~3cm; front-end pixel-weight
  fix, not the BA backend).
- **mv_no_box = improvement + stabilization**: OFF hit the high basin on seed1 (14.30, the documented
  same-seed bistability); ON stayed in the low basin on all 3 seeds (variance cut 3.3×). Biggest single
  fix = seed1 14.30→3.50. reliable_tracking suppressed the bistable excursion.
- balloon ATE drops hard while RPE stays flat → the gain is on **global drift / trajectory
  consistency**, not frame-to-frame registration.
- Magnitude (−39% / −45%) far exceeds the ≥15% bar PROBE1-X missed — caveat: that bar was defined on
  person-ATE, here it's map-adjacent full-traj ATE on a different seq set (magnitude analogy, not the
  same test). First tracking-side intervention past a variance-clean bar.
- **Positioning**: reliable_tracking is **shared infrastructure** (a tracking gain applying to both
  arms), **orthogonal to deferred-vs-prune lifecycle** → does NOT change the R1-P01 headline.

## Deferred-arm result — seed 0 (PROBE2-RT-DEFERRED)

> Incubation efficiency: single-seed for direction; add seeds only if bistability/high-variance shows.
> Tests whether the prune-base gain reproduces on the deferred 承重臂 (candidates held out of map
> early → fewer Gaussians for opacity weighting → gain not guaranteed to reproduce).

ATE RMSE (cm), full-traj, seed 0:

| seq | arm | Deferred (this step) | Prune (seed0, ref) | Deferred Δ |
|---|---|---|---|---|
| balloon | OFF | 27.41 | 29.82 | — |
| balloon | ON  | 16.18 | 17.73 | **−11.23 / −41.0%** |
| moving_nonobstructing_box | OFF | 9.61 | 6.96 | — |
| moving_nonobstructing_box | ON  | 4.67 | 6.46 | **−4.94 / −51.4%** |

RPE_trans (cm): balloon OFF 2.74 → ON 2.87 (flat/slightly up, matching prune's RPE-flat pattern);
mv_no_box OFF 2.04 → ON 1.42 (down).

### Read

- **Gain reproduces on the 承重臂** — reliable_tracking is a genuine **lifecycle-independent
  shared-infrastructure** tracking improvement, not a prune-specific artifact.
- **balloon = high confidence even at single seed**: deferred −41.0% ≈ prune −40.5%, and balloon OFF
  variance was PROVEN tiny (±1.26 over 3 seeds on prune) with non-overlapping OFF/ON bands; deferred
  OFF (27.41) / ON (16.18) land squarely in those proven bands → the pattern transfers.
- **mv_no_box = strongly positive direction, magnitude bistability-modulated**: deferred OFF (9.61)
  sampled an elevated draw, ON (4.67) sits in the low basin — same "ON pins the low basin" behavior
  proven on prune 3-seed. −51% is a single deferred seed on the known-bistable seq, so its exact
  magnitude is not yet variance-separated, but the direction is corroborated by the prune 3-seed proof.
  Per the incubation rule, mv_no_box seeds 1/2 on the deferred arm are the only top-up worth doing
  before the 3090 final — deferred here did NOT itself exhibit a bistable split (single clean draw), so
  not spent now.
- **Bottom line**: reliable_tracking (RGD adaptive-weight) is a confirmed directional tracking gain on
  BOTH lifecycles, both main-criterion movers. Still a front-end pixel-weight fix (abs ATE far from
  SOTA); still orthogonal to the deferred-vs-prune novelty. Multi-seed GO/KILL reserved for 3090 final.

## Breadth check — deferred arm, remaining 4 E2 movers, seed 0 (PROBE2-RT-BREADTH)

> Does the ~−40% gain (proven on balloon + mv_no_box) generalize across the rest of the E2
> main-criterion set, or is it just those two? Deferred arm, OFF/ON, single seed per incubation rule.
> `noise floor` = |RToff − E2-deferred|/E2 (same OFF-equivalent config, different run) — a per-seq
> single-seed run-to-run variance estimate; these full-length runs are known same-seed non-reproducible.

| seq | OFF (RToff) | ON (RTon) | Δ vs OFF | E2-deferred ref | noise floor | verdict |
|-----|-----|-----|-----|-----|-----|-----|
| balloon2                   | 9.63  | 10.77 | +12%  | 14.67 | 34% | within noise — undecidable |
| moving_nonobstructing_box2 | 5.97  | 31.95 | **+435%** | 5.24  | 14% | **REAL catastrophic regression** |
| moving_obstructing_box (obox) | 34.38 | 31.67 | −8%   | 32.25 | 7%  | within noise — undecidable |
| person_tracking2           | 51.41 | 20.31 | **−60%**  | 42.58 | 21% | **REAL improvement** |

RPE_trans (cm): balloon2 2.40→2.36; mv_no_box2 1.97→2.50 (up, tracks the ATE blowup); obox 2.94→3.18;
pt2 2.61→3.54 (up despite ATE down — pt2 ON gain is global-drift, not frame-to-frame).

### Read (breadth — REVISES the step-2 "clean win" bottom line above)

- **The "−40% universal gain" hypothesis is REFUTED.** Across all 6 movers: 3 real wins
  (balloon −41%, mv_no_box −51%, pt2 −60%), 1 **real catastrophic loss** (mv_no_box2 +435%),
  2 noise-level (balloon2 +12%, obox −8%, both inside their 7–34% single-seed noise floor →
  not distinguishable from run-to-run variance). Direction is NOT consistent; both signs, large.
- **mv_no_box2 is the killer.** Same scene family as the mv_no_box win (−45/−51%), yet ON here is a
  5.4× blowup. Either (a) mv_no_box-family bistability and ON sampled/steered the bad basin, or
  (b) a real mechanism conflict on this take. Single seed cannot separate these.
- **Consequence for promotion:** reliable_tracking in its current form is NOT safe as a global-on
  default — it is a high-payout / occasional-blowup gamble, not a free uniform tracking gain.

### Seed 1/2 top-up — mv_no_box2 + pt2, ON arm (PENDING → PROBE2-RT-BREADTH decision gate)

Per incubation rule (bistability/high-variance → add seeds), running ON seeds 1/2 on the two REAL
effects. OFF is already 2-sample-characterized per seq (seed0 + E2 both agree: mv_no_box2 low ~5–6,
pt2 high ~43–51), so the only unknown is the ON distribution → all 4 runs go to ON.
- If mv_no_box2 ON s1/s2 come back LOW (~5–6): seed0 ON=31.95 was a **bistable bad draw** → conservative
  admission (③): keep reliable_tracking as a per-seq-conditional, not global default.
- If mv_no_box2 ON s1/s2 stay HIGH (~30): **real mechanism conflict** → shelve reliable_tracking (②).

<!-- seed 1/2 numbers to be filled on batch completion -->
| seq | arm | seed0 | seed1 | seed2 | read |
|-----|-----|-----|-----|-----|-----|
| moving_nonobstructing_box2 | ON | 31.95 | 8.18 | 5.91 | **BISTABLE** — s0 blowup NOT reproduced (s1/s2 low ~6–8); +435% was a bad draw, not a stable conflict |
| person_tracking2           | ON | 20.31 | 26.80 | 35.12 | **REAL win** — all 3 ON < both OFF (42.58/51.41); non-overlapping; honest mean −42% (seed0 −60% was the lucky-best draw) |

**pt2 verdict — REAL win, variance-separated.** ON {20.31, 26.80, 35.12} (mean 27.4) vs OFF {51.41,
42.58(E2)} (~47): max ON (35.12) < min OFF (42.58) → non-overlapping distributions, genuine win. The
seed0 −60% was the best of three ON draws; the honest magnitude is **−42% (mean)**. pt2's own ON spread
(20–35) is wide, so it is a real but noisy win.

## FINAL SYNTHESIS — PROBE2-RT breadth verdict (③ conservative admission)

Full deferred-arm picture across all 6 E2 movers (reliable_tracking OFF→ON):

| seq | OFF | ON (best–worst over seeds) | verdict |
|-----|-----|-----|-----|
| balloon                    | 27.41 | 16.18 | REAL win −41% (prune 3-seed clean) |
| moving_nonobstructing_box  | 9.61  | 4.67  | REAL win −45/−51% (prune 3-seed clean) |
| person_tracking2           | ~47   | 20.31 / 26.80 / 35.12 | REAL win −42% (3 ON < both OFF, non-overlapping) |
| balloon2                   | 9.63  | 10.77 | within noise (+12% < 34% floor) — undecidable |
| moving_obstructing_box     | 34.38 | 31.67 | within noise (−8% < 7% floor... borderline) — undecidable |
| moving_nonobstructing_box2 | ~5.6  | 31.95 / 8.18 / 5.91 | BISTABLE — neutral-when-good + non-reproducible blowup tail |

- **Universality REFUTED**, but **no stable regression anywhere**: 3 real wins, 2 noise-neutral, 1
  bistable-neutral. The only catastrophe (mv_no_box2 +435%) did not reproduce over 3 seeds.
- **DECISION = ③ conservative admission.** reliable_tracking is admitted as a **per-seq-conditional
  tracking gain** (real on balloon / mv_no_box / pt2, neutral elsewhere), **NOT promoted to a
  global-default headline** — the mv_no_box2 blowup tail means any headline claim needs per-seq
  multi-seed confirmation first. ② (shelve) rejected: nothing stably regresses.
- Still a front-end pixel-weight fix (abs ATE far from SOTA ~3cm); still orthogonal to the
  deferred-vs-prune novelty (does NOT change the R1-P01 headline). Per-seq multi-seed GO/KILL and any
  headline promotion reserved for 3090 final.

**mv_no_box2 verdict — BISTABLE bad draw → conservative admission (③), NOT shelve (②).**
ON draws {31.95, 8.18, 5.91} (median 8.18) vs OFF {5.97, 5.24(E2)} (~5.6): the seed0 catastrophe did
NOT reproduce → no stable mechanism conflict. BUT ON's low draws (5.9–8.2) only *match* OFF, they do
not beat it, and OFF blew up 0/2 while ON blew up 1/3 — so on mv_no_box2 reliable_tracking is
**neutral-when-good with a blowup tail**, not a win. This is exactly why it must be admitted
conservatively (helps balloon/mv_no_box/pt2, neutral+risky on mv_no_box2) rather than turned on
globally. No STABLE regression anywhere (the one blowup is non-reproducible), so ② (shelve) is not
warranted.

