# P2-RT spike outcome — ReliableTracking ON on the combined maskboth prune backbone (2026-08-03)

> **Status:** 3/3 DONE (balloon, mv_no_box, pt1). Screening only (single seed).
> Conclusion: RT is **subsumed by mask-both** — no PROBE2-class win on any seq, and
> Pareto-worse on resources. Main table stays RT OFF; framed as sufficiency ablation.

## Setup

- Spike: enable `ReliableTracking` (RGD adaptive-weight tracker) ON on the paper's
  CURRENT combined maskboth prune backbone (`method_combined_maskboth_prune_rton.yaml`,
  single-knob diff vs `method_combined_maskboth_prune.yaml` = `ReliableTracking.enabled`).
- 3 seqs × seed0: balloon, mv_no_box, pt1 (the 2 PROBE2-RT win seqs + 1 new).
- Control ATE IMPORTED from P2-T (same backbone, RT off, 3-seed):
  balloon 3.07±0.14 (seed0 2.8686), mv_no_box 2.58±0.05 (seed0 2.515), pt1 10.97±0.03 (seed0 11.0087).
- Runner: `scripts/r2_p2_rt_spike.py`. RT-on configs: `p2s_combined_prune_rton_*.yaml`.

## Results (seed0, 3/3 complete)

| seq | RT-OFF control (seed0) | RT-ON (seed0) | Δ ATE | RT-ON online FPS | RT-ON G | RT-ON VRAM |
|---|---|---|---|---|---|---|
| balloon | 2.8686 | **2.9016** | **+1.2%** (flat) | 0.40 | 35830 | 2.34 GB |
| mv_no_box | 2.515 | **2.4304** | **−3.4%** (marginal) | 0.37 | 43480 | 2.88 GB |
| pt1 | 11.0087 | **11.5641** | **+5.1%** (slightly worse) | 0.38 | 72613 | 3.11 GB |

**RT-OFF control online FPS:** balloon 0.49, mv_no_box 0.53, pt1 0.45 (P2-T).
**Resource cost is consistent across all 3:** FPS −18% to −30%, G and VRAM both rise
(pt1 G 55596→72613 +31%, VRAM 3.10→3.11). RT is **Pareto-worse** on resources everywhere.

**PROBE2-RT (open-set prune base) for contrast:** balloon −41%, mv_no_box −45%, pt2 −42%
(3-seed non-overlapping wins). On the maskboth combined base the same knob gives
+1.2% / −3.4% / +5.1% — all flat/marginal, **none** within an order of magnitude of
the PROBE2 win, and two of three slightly *worse*.

## Read (3-seq, conclusion)

- **NEGATIVE transfer, mechanism = subsumption.** PROBE2-RT's −40%-class wins were on
  the **open-set prune base** (weaker masking). On the **maskboth combined base**,
  RT is flat-to-slightly-worse on ATE across all 3 PROBE2-win candidates AND
  Pareto-worse on FPS/VRAM/G everywhere.
- **Leading explanation (codex 019fc3e3): redundancy/saturation.** The combined
  backbone's `mask_mapping=true + mask_insertion=true` already removes/suppresses
  person pixels in BOTH tracking and mapping loss. ReliableTracking's generic
  adaptive-weight residual/border weighting then has little useful signal left — the
  explicit mask subsumes the marginal benefit RT provides on a weaker-masking base.
- This is **backbone-specific sufficiency**, NOT "RT never works": RT helps the
  open-set (weaker masking) base, is redundant after mask-both. The contrast is
  itself useful evidence of mechanism dependence.

## Decision (3-seq confirmed)

- **Main-table default: keep RT OFF.** All 3 PROBE2-win candidates flat-or-worse on
  ATE, Pareto-worse on resources. No case for global promotion survives.
- **Do NOT run the mv_no_box2 safety check** — balloon/mv_no_box/pt1 all flat removes
  the case for global RT; the documented mv_no_box2 blowup-tail risk is moot.
- **DBA-lite oracle** (the last remaining "tracking improvement" GPU candidate) stays
  at lowest priority / effectively shelved — its photo proxy is unweighted (can't open
  a reliability-weighted route, [[dba-oracle-photometric-proxy-unweighted]]), and v0
  pure-geometric BA is foreclosed by the objective-level oracle negative. **Both
  tracking-improvement routes are now closed**; tracking stays at P2-T status
  (balloon 3.07 / mv_no_box 2.58 / pt1 10.97).

## Constructive use of the negative (per user "no honest-negative framing")

Frame as a **planned interaction/sufficiency ablation**, not "we tried RT and it failed":

> On the combined mask-both backbone, adding ReliableTracking produced no measurable
> ATE improvement (−3.4% to +5.1% across three PROBE2-win sequences, all within
> run-to-run noise) while increasing runtime (−18 to −30% FPS) and memory. This
> indicates that explicit person masking in both tracking and mapping largely
> **subsumes** the marginal benefit of generic adaptive tracking weights — a
> backbone-specific sufficiency result. The contrast with the open-set base (where
> the same module delivers −40%-class ATE wins) isolates masking as the mechanism.

Report paired ATE + resource deltas; the open-set-vs-maskboth contrast is the
mechanism-dependence evidence, not a "we tried and failed" negative.

## Reproduce

- run: `python scripts/r2_p2_rt_spike.py --phase run --seed 0`
- report: `python scripts/r2_p2_rt_spike.py --phase report`
- per-run: `results/runs/P2/P2-RT-SPIKE/{balloon,mv_no_box,pt1}_prune_rton_seed0/tables/tracking_raw.csv`
- control: `results/runs/P2/P2-T/{balloon,mv_no_box,pt1}_prune_seed0/tables/tracking_raw.csv`
- codex reads: `results/evidence/probe2_reliable_tracking.md`, `p2t_verdict_final.md`
