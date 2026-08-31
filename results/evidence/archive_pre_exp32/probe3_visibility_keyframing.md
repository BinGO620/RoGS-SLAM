# PROBE3-VK — visibility-aware keyframing (RGD complement) OFF↔ON

## Setup

RGD-style visibility-aware keyframe-window management (`utils/visibility_window.py`
`update_visibility_window`): when the KF window overflows, evict the keyframe with the lowest
`cov_weight*covisibility + (1-cov_weight)*dynamic_complementarity`. The **complement term needs a
per-pixel dynamic-region mask**; closed-set uses the semantic person mask, but **open-set has none**
(`viewpoint.dynamic_mask` is None) so complement was **identically 0** → the whole mechanism degraded
to pure co-visibility (≈ MonoGS default). This probe wires the **training-free `reliability_s`**
(`s=(1-e_flow)(1-v*g)`, RAFT flow-anomaly + geom + opacity; already computed & stashed per-KF in the
open-set deferred arm via `DeferredCommit.reliability_confirm=True`) as the complement source:
`s < tau = dynamic` on the RAW per-pixel `s` (fixed tau, NOT the Cauchy `w` aggregation → avoids the
PROBE1-X majority-domination knee).

Base = R1-P01 open-set DEFERRED arm reused field-for-field. OFF vs ON **effective config differs by
exactly `VisibilityWindow.enabled`** (load_config-verified, lifecycle=deferred both). Screening,
single seed (incubation rule); does NOT touch the R1-P01 frozen contract. 2060, full-length --fast.
Code: `visibility_window.py` (_dynamic_numpy reliability_s fallback + VW-DIAG engagement counter),
`base_config.yaml` (VisibilityWindow.reliability_dynamic_tau: 0.5).

## Result — deferred arm, seed 0 (PROBE3-VK)

| seq | VWoff (ATE cm) | VWon (ATE cm) | Δ | RPE off→on | verdict |
|-----|-----|-----|-----|-----|-----|
| balloon                    | 27.24 | 31.32 | **+15%** | 2.73→2.60 | small REGRESSION (balloon OFF var proven ±1.26 → +4.1cm ≈ 3σ, likely real) |
| moving_nonobstructing_box  | 4.21  | 6.58  | +56%  | 1.38→1.66 | UNDECIDABLE (bistable seq, both in low basin 4–7, Δ within ±4.98 prune std) |

**Engagement CONFIRMED (not a no-op):** mv_no_box ON run VW-DIAG `calls=20 cur_reliability_s=20/20
cand=140 complement>0=140/140 mean_complement=0.3457` — reliability_s present on every eviction, the
complement fired non-zero on 100% of candidates, mean complement 0.35. balloon ON had <20 evictions
(short seq) so the %20-gated print never triggered, but it is the same code path (OFF baseline
cross-checks clean: VWoff balloon 27.24 ≈ E2 27.41 ≈ PROBE2-RToff 27.41).

### Read (screening)

- **No ATE win.** balloon is a small but likely-real regression (+15% ≈ 3σ against the proven ±1.26
  balloon variance); mv_no_box is undecidable (bistable, both draws in the low basin, Δ inside the
  ±4.98 prune std). Neither direction is a gain on ATE.
- **BUT ATE is the wrong readout for this lever.** visibility-aware keyframing is a
  keyframe-*selection* change; its intended payoff is **map/geometry quality in dynamic regions**
  (keep KFs that reveal now-occluded static surface), NOT trajectory ATE — and like reliable_tracking
  it cannot close the 3→1.5cm BA-backend gap. The geometry readout is **F@5cm / dynamic-region
  completeness**, which needs the 3090 (2060 --eval OOMs on dense-KF maps — see
  [[monogs-expandable-segments-mp-incompat]]).
- **tau untuned:** tau=0.5 is the neutral midpoint of s∈[0,1]; complement mean 0.35 means the mask is
  broad (a big fraction of pixels flagged dynamic). A lower tau (more selective dynamic mask) is the
  one cheap 2060 knob left before any 3090 geometry spend.
- **Status: SCREENED → SHELVED (2026-07-24).** Decision under the deadline-driven scope focus (MMM
  ddl 2026-08-16 AOE, ~3.3 weeks): **shelved, not killed.** Rationale is honest and paper-usable, NOT
  "mechanism ineffective": (1) the mechanism is **confirmed to fire** (VW-DIAG complement>0 on 100% of
  candidates, mean 0.35 — reliability_s wiring works, not a no-op); (2) **ATE is not the correct readout**
  for a keyframe-selection lever — its intended payoff is map/geometry quality in dynamic regions, which
  needs the 3090's large VRAM (2060 --eval OOMs on dense-KF maps); (3) on ATE it is neutral-to-slightly-
  worse (balloon +15% ≈3σ), and its only defensible upside (geometry) **overlaps with what the deferred
  lifecycle already delivers** (6/6 geometry wins), so it is not load-bearing for the headline. Under the
  new hard constraint that every shipped module must materially improve ATE, VK does not qualify.
- **Disposition:** infrastructure committed + archived (reliability_s complement wiring, VW-DIAG,
  tau=0.5 config) so it is reproducible; **not folded into R1-P01**, not run on 3090. Writable as an
  honest discussion/exploration point: "training-free visibility-aware keyframing wires cleanly and
  fires, but its geometry payoff was not separable from the deferred lifecycle under our budget; ATE
  neutral-to-worse; left for future large-VRAM geometry evaluation." Re-openable if 3090 geometry
  budget frees up after the ATE + geometry headline tables land. Superseded focus: PROBE2-RT
  (承重墙, ATE) + deferred lifecycle (geometry). See [[dynamic-3dgs-slam-direction]].
