# P0-QUAD — deferred{OFF/ON} × reliable_tracking{OFF/ON} full four-quadrant ATE (multi-seed)

## Setup

Single batch, one `tracking_raw.csv`, so all four arms share run conditions (no stale-mix confound).
Four arms = the two orthogonal switches in ONE config:
`Mapping.lifecycle_mode ∈ {prune, deferred}` × `ReliableTracking.enabled ∈ {false, true}`.
load_config-verified: across 287 resolved keys the four arms differ in EXACTLY two functional keys
(`Mapping.lifecycle_mode`, `ReliableTracking.enabled`) plus label-only `method`/`method_from`.

- **Baseline reference = `Prune-RToff`** = original MonoGS insert-then-prune lifecycle, no RT.
- Configs: `configs/rgbd/experiments/probe2_reliable_tracking/{prune,deferred}_{rtoff,rton}_<seq>.yaml`.
- 2060, full-length `--fast` (headline ATE == --eval ATE), **NO ate-abort** (so the mv_no_box2 blowup
  tail shows honestly). Driver `/tmp/p0_quad.sh` (iterate seq→seed→4 arms; each cell completes a full
  quad ASAP). Results `results/runs/P0-QUAD/tables/tracking_raw.csv`.
- **52/52 runs rc=0, all status=OK.** Seed tiering (per user): balloon×1 (var proven ±1.26);
  mv_no_box + mv_no_box2 ×3 (bistable); balloon2 + obox + pt2 ×2.
- Purpose: test the three claims (a) deferred alone hurts ATE, (b) RT patches it, (c) deferred+RT joint
  ≥ baseline — that the single-seed E2+PROBE2 read had treated as "story closed".

## Result — median ATE (cm), Δ% vs Prune-RToff baseline median

| seq | baseline (Prune-RToff) | Prune-RTon | Deferred-RToff | Deferred-RTon (joint) | stability |
|-----|-----|-----|-----|-----|-----|
| balloon                    | 32.5 | 19.4 (−40%) | 29.4 (−10%) | **15.4 (−53%)** | stable ✓ |
| moving_nonobstructing_box  | 4.7  | 5.5 (+16%)  | 17.2 (+265%)| **4.9 (+3%)**   | BISTABLE |
| moving_nonobstructing_box2 | 7.0  | 7.3 (+4%)   | 7.7 (+11%)  | **6.7 (−4%)**   | BISTABLE |
| balloon2                   | 12.1 | 15.9 (+32%) | 13.9 (+16%) | **12.9 (+7%)**  | stable |
| moving_obstructing_box     | 29.2 | 31.2 (+7%)  | 42.1 (+44%) | **27.4 (−6%)**  | semi-stable |
| person_tracking2           | 40.8 | 28.5 (−30%) | 24.5 (−40%) | **40.0 (−2%)**  | noisy |

## Seed-level ATE (cm) — raw, bistable cells flagged

| seq | arm | seeds | flag |
|-----|-----|-----|-----|
| balloon | Prune-RToff | s0=32.5 | |
| balloon | Prune-RTon | s0=19.4 | |
| balloon | Deferred-RToff | s0=29.4 | |
| balloon | Deferred-RTon | s0=15.4 | |
| moving_nonobstructing_box | Prune-RToff | s0=4.7 s1=6.0 s2=4.1 | stable |
| moving_nonobstructing_box | Prune-RTon | s0=3.2 s1=17.8 s2=5.5 | BISTABLE |
| moving_nonobstructing_box | Deferred-RToff | s0=30.0 s1=3.3 s2=17.2 | BISTABLE |
| moving_nonobstructing_box | Deferred-RTon | s0=4.9 s1=4.4 s2=24.1 | BISTABLE (new tail) |
| moving_nonobstructing_box2 | Prune-RToff | s0=7.8 s1=7.0 s2=6.1 | stable |
| moving_nonobstructing_box2 | Prune-RTon | s0=7.9 s1=6.3 s2=7.3 | stable |
| moving_nonobstructing_box2 | Deferred-RToff | s0=6.4 s1=7.7 s2=7.9 | stable |
| moving_nonobstructing_box2 | Deferred-RTon | s0=6.0 s1=31.3 s2=6.7 | BISTABLE (new tail) |
| balloon2 | Prune-RToff | s0=12.5 s1=11.6 | |
| balloon2 | Prune-RTon | s0=15.9 s1=15.9 | |
| balloon2 | Deferred-RToff | s0=14.2 s1=13.6 | |
| balloon2 | Deferred-RTon | s0=13.0 s1=12.7 | |
| moving_obstructing_box | Prune-RToff | s0=27.3 s1=31.1 | |
| moving_obstructing_box | Prune-RTon | s0=31.8 s1=30.5 | |
| moving_obstructing_box | Deferred-RToff | s0=53.3 s1=31.0 | |
| moving_obstructing_box | Deferred-RTon | s0=26.3 s1=28.4 | |
| person_tracking2 | Prune-RToff | s0=41.7 s1=40.0 | |
| person_tracking2 | Prune-RTon | s0=35.1 s1=21.8 | |
| person_tracking2 | Deferred-RToff | s0=27.7 s1=21.3 | |
| person_tracking2 | Deferred-RTon | s0=50.2 s1=29.8 | |

## RPE_trans median (cm) — for reference

| seq | base | Prune-RTon | Def-RToff | Def-RTon |
|-----|-----|-----|-----|-----|
| balloon | 2.52 | 2.45 | 2.68 | 2.29 |
| moving_nonobstructing_box | 1.89 | 1.88 | 2.02 | 1.48 |
| moving_nonobstructing_box2 | 2.13 | 2.11 | 1.83 | 1.62 |
| balloon2 | 2.83 | 3.03 | 2.73 | 2.43 |
| moving_obstructing_box | 2.67 | 2.37 | 3.02 | 2.83 |
| person_tracking2 | 2.44 | 3.36 | 3.91 | 3.18 |

## Blowup count (seed-run > 2× that seq's baseline median)

| arm | blowups |
|-----|-----|
| Prune-RToff (baseline) | 0/13 |
| Prune-RTon | 1/13 |
| Deferred-RToff | 2/13 |
| Deferred-RTon (joint) | 2/13 |

## Read (factual; narrative direction reserved for user)

Multi-seed P0 does **not** support the single-seed E2+PROBE2 "story closed" read (deferred hurts 4/6 →
RT patches → joint wins). This was exactly the "is the patch stable?" test — answer: not stably.

1. **"deferred alone hurts ATE" is largely single-seed noise.** Under multi-seed, Deferred-RToff HELPS
   on balloon (−10%) and pt2 (−40%); the mv_no_box +265% is violent bistability (30.0/3.3/17.2), not a
   stable regression. E2's "deferred hurts balloon/mv_no_box/pt2" drew unlucky seeds.
2. **RT's ATE gain is narrower than the −40% story.** Clean ATE wins survive only on balloon
   (Prune-RTon −40%) and pt2 (−30%). mv_no_box +16% (no help), balloon2 +32% (worse),
   mv_no_box2/obox neutral. PROBE2's "3 real wins" shrank.
3. **Joint vs baseline: only balloon is a clean stable win (−53%).** Others neutral (mv_no_box +3%,
   mv_no_box2 −4%, obox −6%, pt2 −2%) or small regression (balloon2 +7%).
4. **Joint arm INTRODUCES bistability on previously-stable sequences.** baseline mv_no_box 4.7/6.0/4.1
   and mv_no_box2 7.8/7.0/6.1 are 0/13 blowups; Deferred-RTon blows one seed each (mv_no_box s2=24.1,
   mv_no_box2 s1=31.3). Joint adds fragility where there was none.

**Robust take:** the only stable-across-seeds joint win is balloon (−53%). box family + pt2 are
dominated by run-to-run bistability (MonoGS multiprocess non-determinism; see
[[dynamic-3dgs-slam-direction]] ops lesson: same-seed full-length runs non-reproducible), so per-seed
deltas there are mostly noise, and the joint arm also worsens stability there.

**STATUS: DATA ARCHIVED. Narrative direction NOT decided — reserved for user.**
