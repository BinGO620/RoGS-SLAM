# DBA-lite GT-oracle NEGATIVE result — provenance & transferability audit (2026-08-03)

> **Question driving this audit:** the method/results docs record a "DBA-lite
> GT-oracle: geometric residual does NOT drop when poses → GT" negative
> conclusion (`03-results.md:83`, `02-method.md:83`, `10-method_math_formalization.md:407`).
> Before spending any GPU on a DBA spike on the *current* backbone, we must know:
> **on what base config / sequence / code state was that negative obtained, and
> does it bind the current combined backbone?**

## TL;DR

The negative is **real and was obtained deterministically**, but on a **structurally
different, older backbone** than the current paper main table. The negative is a
claim about *the masked dense geometric/photometric objective's information limit*,
which is **objective-dependent, not backbone-dependent** — so it **partially binds**
the current backbone (same masked RGB-D point-to-plane objective) but does **NOT**
foreclose the two routes that change the objective. The decision: re-run the
read-only oracle on the current backbone (cheap, no pose writes) to confirm
transfer before any v0 spike.

## 1. Where the negative came from (provenance)

- **Commit:** `e94158d` "DBA-lite v0 + GT-oracle: deterministic NEGATIVE result
  (learning-free geometric/photometric BA cannot close the dynamic ATE gap)"
  (2026-07-15, tag `probe1-screening-2026-07-21`).
- **Code:** `utils/dba_lite.py` — `run_dba_oracle()` (lines 543-653) is the
  read-only falsifier; `run_dba_v0()` (656+) is the actual BA. Both default-off.
  The oracle is **deterministic** (SE(3) geodesic interpolation online→GT, no
  optimization, no solver RNG).
- **Sequence / measurement:** `f3_wk_xyz` seed0, **490 masked KF edges**.
  Finding: as poses go online(ATE ~4-5cm) → GT, **both** the dense point-to-plane
  **geometric** residual (+6%) **and** the brightness-corrected **photometric**
  residual (+20%) **rise monotonically**. Both dense objectives are minimized at
  the *online* tracking poses, NOT at GT. `gt_better` (per-edge GT-fits-better
  count) was minority.
- **v0 side-note:** v0 also confirmed "within CUDA noise vs a fresh baseline
  anchor (3.79 vs 4.085)" — i.e. a single-run ATE cannot judge v0; the oracle is
  the right tool. v0 was kept as a default-off ablation, not promoted.

## 2. The base config the oracle ran on (and why it differs from today)

The oracle config inherited `f3_wk_xyz_maskboth_fixed5_dbaoracle.yaml` →
`f3_wk_xyz_maskboth_fixed5.yaml` → `f3_wk_xyz_maskboth.yaml` → `f3_wk_xyz.yaml`.

| module | OLD oracle base (`f3_wk_xyz_maskboth_fixed5`, 2026-07-15) | CURRENT combined backbone (`method_combined_maskboth_prune`, 2026-07-31) |
|---|---|---|
| `CoarsePoseInit` | **enabled, mode=const_vel** | **ABSENT** (probe1 falsified: 15.4→1.81cm on removal) |
| `RobustTracking` | huber rgb/depth 0.10 | huber rgb/depth 0.10 (SAME) |
| `SemanticMask` | maskrcnn person, mask_mapping=true | maskrcnn person, mask_mapping=true, **mask_insertion=true** (+insertion) |
| `DynamicKeyframe` | gap_cap=5, occ_tighten=2.0 | gap_cap=5, occ_tighten=2.0 (SAME) |
| `ReliabilitySignal` | **ABSENT** | **enabled=true** |
| `DeferredCommit` | **ABSENT** | enabled=true, reliability_confirm=true |
| `ReliableTracking` (RGD adaptive-wt) | ABSENT | **NOT enabled** (defaults false — see §4) |
| dataset | **TUM f3_wk_xyz** (static-ish, fast/short) | **Bonn dynamic** (balloon/mv_box/pt1/pt2) |
| lifecycle | insert-then-prune (no deferred) | prune (twin-isolated) |

**Two confounds in the old base that are gone today:**
1. `CoarsePoseInit(const_vel)` was PRESENT — probe1 later proved it *drifts* on
   slow/long sequences and was *masked* on fast/dynamic ones (why V1 "looked
   fine"). f3_wk_xyz is fast/short, so the 4-5cm online ATE there was **not**
   const_vel drift — it was the photometric ceiling. But the base was still the
   const_vel-contaminated family, now abandoned.
2. The old base had **no ReliabilitySignal, no DeferredCommit, no mask_insertion**.
   The current backbone's tracking/mapping loss is materially different.

## 3. Does the negative bind the current backbone? — objective vs backbone

The oracle's verdict is a statement about **the dense masked RGB-D objective
itself**, not about which tracker produced the online poses:

> "a learning-free BA re-optimizing the **dense masked RGB-D objective** cannot
> recover the last ~1.5cm on short no-loop masked dynamic sequences; the gap is an
> **information limit of masked appearance alignment**, not an optimization failure."

- **What transfers (binds):** the *geometric* residual rising toward GT is a
  property of masked point-to-plane on these edges. The current backbone uses the
  **same masked point-to-plane geometric objective** (mask_mapping=true, same
  depth/normal gates, same edge offsets in `DBALite.opt_offsets`). So the
  geometric-BIASED verdict is **expected to reproduce** on the current backbone.
  → v0 (pure geometric BA) is **unlikely** to help and the old evidence already
  says why. **Do not spike v0 expecting a geometric win.**
- **What does NOT transfer (open):**
  - The **photometric** verdict (+20% rising) was measured on a base **without**
    ReliabilitySignal / mask_insertion / DeferredCommit. The current backbone's
    photometric term is weighted differently (reliability-gated, insertion-masked).
    The photometric-bias *might* soften on the current backbone — **untested**.
  - The negative is about the **dense masked** objective specifically. Routes
    that **change the objective** — feature-anchor edges (sparse ORB/SIFT
    correspondences), loop-closure edges, or a hybrid geo+photo with the
    reliability gate — are **not** foreclosed by this negative. `10-method_math_formalization.md:407`
    itself notes: "the bottleneck is the **mapping objective**, not tracking →
    changing the mapping side is the right call."

## 4. Adjacent finding the optimization docs missed: ReliableTracking

While auditing, recovered `results/evidence/probe2_reliable_tracking.md` (2026-07-23):
**`ReliableTracking`** (RGD adaptive-weight tracking, `utils/reliable_tracking.py`,
committed `762dbee`, base_config `enabled:false`) was screened OFF↔ON on the
open-set prune base and produced **variance-separated ATE wins**:

| seq | OFF | ON | verdict |
|---|---|---|---|
| balloon | 27.41 | 16.18 | REAL win −41% (prune 3-seed clean, non-overlapping) |
| mv_no_box | 9.61 | 4.67 | REAL win −45/−51% (prune 3-seed clean) |
| person_tracking2 | ~47 | 20.31/26.80/35.12 | REAL win −42% (3 ON < both OFF) |
| balloon2 | 9.63 | 10.77 | within noise (+12% < 34% floor) — undecidable |
| obox | 34.38 | 31.67 | within noise (−8%) — undecidable |
| mv_no_box2 | ~5.6 | 31.95/8.18/5.91 | BISTABLE — neutral-when-good + blowup tail |

Decision recorded = **③ conservative per-seq admission** (NOT global default,
because mv_no_box2 had a non-reproducible blowup tail). **Critically: it is NOT
enabled in the current combined backbone** (defaults false), and the current
main-table ATE (balloon 3.07, mv_no_box 2.58 — `p2t_verdict_final.md`) is on the
base **without** it. PROBE2-RT's wins were on the *open-set* base; whether they
reproduce on the *maskboth* combined backbone is **untested**.

This is a **front-end pixel-weight tracking fix** (abs ATE still far from SOTA
~3cm), **orthogonal** to deferred-vs-prune. It is the most promising
"something else" that is **low-risk, existing-code, and was already
variance-separated** — unlike DBA v0, which the oracle negative already
explains.

## 5. Decision (no GPU yet)

1. **DBA v0 (pure geometric BA) spike: DEFER / likely-kill.** The oracle negative
   is objective-level and the current backbone shares that objective. A v0 spike
   would most likely reproduce "geometric residual minimized at online, not GT."
   **Not worth GPU** unless the oracle is first re-shown to flip on the current
   backbone.
2. **DBA-lite oracle RE-RUN on current backbone: cheap de-risk (read-only).**
   Set `DBALite.oracle: true` on the combined prune config, run balloon seed0
   `--fast` (~30min, no pose writes). If the **photometric** verdict softens
   (GT lowers photo residual on the reliability-gated term), a photo-hybrid BA
   route opens. If both still BIASED → DBA track closed with current evidence.
   This is the *one* DBA GPU spend that is justified: it either opens a door or
   cleanly closes it on the *current* backbone.
3. **ReliableTracking on combined backbone: the higher-value spike.** Existing
   code, variance-separated wins on a sibling base, orthogonal to novelty. Spike
   = enable on combined prune, run balloon/mv_no_box/pt2 seed0 (3 runs, ~1.5h),
   compare to P2-T prune ATE (3.07/2.58/10.97). If it reproduces the −40% class
   of win on the maskboth base, it is a real tracking-side contribution to add to
   the main table — **without touching the deferred-vs-prune headline**.

## Reproduce pointers

- oracle code: `utils/dba_lite.py:543` (`run_dba_oracle`), config flag `DBALite.oracle`
- v0 code: `utils/dba_lite.py:656` (`run_dba_v0`), flag `DBALite.enabled`
- wiring: `slam.py:423-443` (oracle then v0, both before `save_final_tracking_raw`)
- old negative commit: `e94158d` (configs `f3_wk_xyz_maskboth_fixed5_dbaoracle.yaml` etc., now gone from this branch)
- old base chain: `*_maskboth_fixed5` → `*_maskboth` → `f3_wk_xyz` (all carried `CoarsePoseInit.const_vel`)
- current backbone: `configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml`
- ReliableTracking screening: `results/evidence/probe2_reliable_tracking.md`
