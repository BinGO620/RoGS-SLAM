# 2×2 ablation template — Tracker × Lifecycle (2026-08-03)

> Per codex (thread 019fc3c7): if ReliableTracking (RT) survives global-on safety
> testing, the clean two-mechanism story is **reliability-aware tracking** ×
> **deferred lifecycle**, presented as a 2×2. The decisive ablation isolates the
> tracking gain from the lifecycle gain. **RT-on runs are NOT yet complete** (spike
> in progress); this is the empty template to fill.

## The 2×2

| | **lifecycle = prune** | **lifecycle = deferred** | role |
|---|---|---|---|
| **RT off** | (A) existing P2-T prune control | (B) existing P2-T deferred | current main table (RT-off) = ablation evidence |
| **RT on** | (C) RT-on prune — isolates tracking gain | (D) RT-on deferred — full method | **final main comparison = C vs D** |

- **A, B** = already measured (P2-T, 36 runs, 3 seeds). ATE: prune 3.07/2.58/10.97...
  (see `p2t_verdict_final.md`).
- **C** = P2-RT spike (seed0 in progress on balloon/mv_no_box/pt1). Needs 3-seed +
  mv_no_box2 safety check before admission.
- **D** = RT-on deferred twin — **not yet run**. Needed only if C survives safety.

## Framing (codex): two-mechanism story, not sequence-conditioned tracker

1. **Reliability-aware tracking** — robustly weights image/depth evidence → better
   camera trajectories (applies to BOTH arms, lifecycle-independent).
2. **Deferred lifecycle management** — controls when uncertain Gaussians enter the map
   → compactness–tracking trade boundary, measured **under the same tracker**.

The final main table compares **C (RT-on prune) vs D (RT-on deferred)**; the RT-off
table (A vs B) becomes ablation evidence showing the lifecycle effect holds with and
without the tracking improvement.

**Critical (codex):** do NOT present a sequence-name-conditioned tracker (RT on for
balloon/mv_no_box, off elsewhere) as a method contribution — without a causal online
admission rule that looks like test-set tuning. Either RT becomes **globally safe**
(via the mv_no_box2 safety check) or it stays an **informative ablation**, not a
headline.

## Metrics to fill per cell (3-seed mean ± sd, ddof=1)

| cell | ATE cm | RPE cm | full PSNR | full SSIM | full LPIPS | G count | online FPS | peak VRAM | RT overhead |
|---|---|---|---|---|---|---|---|---|---|
| A (RT-off prune) | 3.07±0.14... | [have] | [3090] | [3090] | [3090] | 39784±5511... | 0.454 | 2.94 GB | 0 (RT off) |
| B (RT-off deferred) | 3.11±0.16... | [have] | [3090] | [3090] | [3090] | 19803±267... | 0.490 | 2.65 GB | 0 (RT off) |
| C (RT-on prune) | [spike→3seed] | [run] | [3090] | [3090] | [3090] | [run] | [run] | [run] | [run] |
| D (RT-on deferred) | [pending] | [pending] | [3090] | [3090] | [3090] | [pending] | [pending] | [pending] | [pending] |

## GO/KILL gates for RT admission (codex)

1. **Transfer (seed0, current spike):** balloon + mv_no_box both improve ≥20-25%
   beyond P2-T variance; no regression; pt1 not worse >10-15%. → GO to multiseed.
   - ATE 3.07→~1.8 and 2.58→~1.4 = emphatic GO.
2. **Safety (mv_no_box2, 3 seeds RT-on):** the documented 1/3 blowup tail (PROBE2-RT
   open-set: +435% seed0, not reproduced s1/s2) must NOT appear on the maskboth base.
   One clean seed cannot clear it.
3. **Global-on decision:** if mv_no_box2 safe across 3 seeds → RT becomes a global
   backbone component (both arms). If blowup reproduces → RT stays an ablation, not
   a method contribution.

## 3090 decision manifest (to freeze BEFORE seeing RT multiseed results)

- [ ] GO/KILL thresholds (above) frozen
- [ ] all 6 seqs × 2 arms × 3 seeds (C + D = 36 runs) configs ready
- [ ] failure handling (catastrophic-run rule from P2-T prereg §7)
- [ ] exact same protocol as P2-T (online-phases-v2, eval cadence fix applied)
- [ ] never mix 2060 screening numbers with 3090 paper numbers

## Reproduce pointers

- A/B: `results/runs/P2/P2-T/` (36 runs), `p2t_verdict_final.md`
- C: `results/runs/P2/P2-RT-SPIKE/` (seed0 spike, in progress), `scripts/r2_p2_rt_spike.py`
- RT-on configs: `configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune_rton.yaml` + per-seq `p2s_combined_prune_rton_*.yaml`
- RT-off→on single-knob diff: verified key-by-key (only `ReliableTracking.enabled: false→true`)
