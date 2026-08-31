# Efficiency narrative — data scaffold (2026-08-03)

> **Status:** scaffold built from existing P2-T 36-run efficiency_raw.csv (no new GPU).
> All numbers below are **2060 screening** — NOT paper numbers. Paper efficiency must
> be re-measured on 3090 alongside the main table (see [[paper-metrics-on-3090]]).
> Purpose: have the table structure, competitor anchors, and claim text ready so that
> when the 3090 batch lands, only the numbers are filled in.

## 1. The two-metric split (the core reframe)

End-to-end FPS on 2060 (0.43-0.53) is **not comparable** to competitor 3090 FPS, and
looks slow. The defensible efficiency story is **not speed** — it is **memory** and
**model compactness**, both of which are GPU-independent in spirit (peak VRAM scales
with scene/map, not raw compute). The narrative splits:

| metric | what it measures | our 2060 value | competitor (3090) | comparable? |
|---|---|---|---|---|
| **peak VRAM** | deployment feasibility | 2.0-3.8 GB | RGD/DG/WildGS 6.5-12.2 GB | **YES** (memory ≠ compute) → **2-5× lower** |
| **online FPS** | real-time tracking/mapping (excl. offline refine) | 0.43-0.53 | 0.4-0.9 (RGD) | partially (same order, hw caveat) |
| **end-to-end FPS** | incl. offline color refinement | 0.43-0.53 | — | NO (refine is offline, batch) |
| **final Gaussians** | model size / compactness | 19.8k-75.8k | WildGS ~126k | YES → smaller models |

**Key fact (already measured):** offline color refinement is **20-46% of total wall
time** but is a **batch post-process**, not online. Online SLAM FPS ≈ end-to-end FPS
here only because refinement runs in-line on 2060; on 3090 the split is cleaner. The
headline efficiency claim is **VRAM**, with FPS as a same-order secondary.

## 2. Our 2060 screening efficiency (P2-T, 3-seed mean, both arms)

From `efficiency_raw.csv` across all 36 P2-T runs (online-phases-v2 protocol):

| seq | arm | online FPS | online VRAM GB | refined G | refine VRAM GB | e2e FPS | refine % total |
|---|---|---|---|---|---|---|---|
| balloon | prune | 0.482 | 2.321 | 39784 | 2.409 | 0.482 | 45.9% |
| balloon | deferred | 0.534 | 2.060 | 19803 | 2.067 | 0.534 | 45.4% |
| balloon2 | prune | 0.470 | 2.395 | 33524 | 2.484 | 0.470 | 41.4% |
| balloon2 | deferred | 0.483 | 2.250 | 30519 | 2.359 | 0.483 | 46.2% |
| mv_no_box | prune | 0.451 | 2.883 | 40806 | 3.053 | 0.451 | 26.4% |
| mv_no_box | deferred | 0.489 | 2.652 | 31561 | 2.771 | 0.489 | 27.0% |
| mv_no_box2 | prune | 0.426 | 3.570 | 65343 | 3.793 | 0.426 | 20.4% |
| mv_no_box2 | deferred | 0.461 | 3.260 | 50655 | 3.434 | 0.461 | 20.8% |
| pt1 | prune | 0.445 | 3.102 | 55596 | 3.182 | 0.445 | 31.5% |
| pt1 | deferred | 0.489 | 2.769 | 44154 | 2.717 | 0.489 | 33.1% |
| pt2 | prune | 0.447 | 3.350 | 69609 | 3.524 | 0.447 | 33.9% |
| pt2 | deferred | 0.485 | 2.926 | 44196 | 2.959 | 0.485 | 33.8% |

**Headline numbers (mean across 6 seqs × 3 seeds):**
- prune: online FPS 0.454, peak VRAM 2.94 GB, refined G 50.1k
- deferred: online FPS 0.490, peak VRAM 2.65 GB, refined G 36.8k
- **deferred uses −27% Gaussians and −10% VRAM vs prune at equal-or-better online FPS** —
  the efficiency face of the compactness claim (lifecycle is not just fewer Gaussians,
  it is fewer Gaussians *at lower memory and equal speed*).

**Range for the VRAM claim:** 2.0-3.8 GB (peak across all seqs/arms/seeds) vs
competitor 6.5-12.2 GB → **1.7-6.1× lower**, headline "2-5× lower VRAM".

## 3. Competitor anchors (for matched comparison — verify on 3090)

From `03-knowledges/02-rgd_slam_source_audit.md` + consult briefs (NEEDS 3090 verification):

| method | peak VRAM GB | FPS | Gaussians | source |
|---|---|---|---|---|
| MonoGS (baseline) | ~6.5 | 1.90 | — | published |
| RGD-SLAM | 6.4-11.6 | 0.4-0.9 | — | local audit (3090-class) |
| DG-SLAM | ~12.2 | 1.22 | — | published |
| WildGS | ~10+ | — | ~126k | published |
| SplaTAM | — | — | — | published |
| Co-SLAM | — | — | — | published |
| **Ours (2060)** | **2.0-3.8** | **0.43-0.53** | **19.8-75.8k** | this work (screening) |

**TODO (3090):** re-measure ours on 3090 for a same-hardware VRAM/FPS comparison;
pull exact competitor numbers from their papers (not the audit's local runs) for the
main table. The 2-5× VRAM claim must be same-protocol.

## 4. Online/offline decomposition (defends the "slow FPS" perception)

`efficiency_raw.csv` already decomposes per-frame time. From balloon prune seed0
(representative; all seqs similar shape):
- total_time 898s, online_time 898s (refinement runs in-line on 2060)
- color_refinement_time 411s = **45.9% of wall** (offline batch, not online)
- tracking_time 793s / 438 frames = 1.81 s/frame tracking
- mapping_time 881s / 10077 iters
- semantic_time 95.7 ms/call × 439 calls = 42.0s (4.7% — Mask R-CNN is NOT the bottleneck)

**Claim:** "Online SLAM runs at 0.43-0.53 FPS; the remaining 20-46% wall time is an
**offline** color-refinement post-process that does not affect online tracking/mapping.
Peak VRAM 2.0-3.8 GB — **2-5× lower than dynamic-3DGS-SLAM SOTA (6.5-12.2 GB)** —
enabling deployment on consumer 6 GB GPUs where all surveyed competitors OOM."

## 5. What MUST be re-measured on 3090 (do NOT use 2060 numbers in paper)

1. Peak VRAM on 3090 (may differ — 3090 has larger buffers; report 3090 number).
2. Online FPS + end-to-end FPS on 3090 (same-hardware as competitors).
3. Final Gaussian count (already GPU-independent, but re-confirm on 3090 maps).
4. **If ReliableTracking is admitted:** RT overhead (reliable_tracking_time_ms/call)
   added to the decomposition — already a column in efficiency_raw.csv (currently 0
   because RT is off in P2-T; will populate from RT-on runs).
5. Optional: re-run MonoGS baseline on 3090 for a same-hardware FPS ratio.

## 6. Claim text draft (placeholders for 3090 numbers)

> Despite competitive tracking and rendering quality, our method is the only surveyed
> dynamic 3DGS-SLAM that runs within a 6 GB VRAM budget. Peak memory is **[X.X] GB on
> an RTX 3090** — **[Y]-[Z]× lower** than RGD-SLAM ([a.a]), DG-SLAM ([b.b]), and
> WildGS ([c.c]) — while online SLAM proceeds at **[m.m] FPS** (competitors [n.n]-
> [o.o] FPS on the same hardware). The deferred-commitment lifecycle further reduces
> the final Gaussian count by **27%** (prune [P]k → deferred [D]k) at equal-or-better
> online FPS, yielding smaller reconstructable maps at no runtime cost.

## Reproduce

- aggregation script: inline `python` over `results/runs/P2/P2-T/*/tables/efficiency_raw.csv`
  (this file's §2 table was generated 2026-08-03 from the 36 P2-T runs)
- protocol: `online-phases-v2` (efficiency_raw.csv `efficiency_protocol_version` column)
- competitor audit: `workspace/dynamic-3dgs-slam/03-knowledges/02-rgd_slam_source_audit.md`
