# Stage 0 verdict — observation-contradicted eviction (2026-08-05/06)

**VERDICT: CLOSED (NO-GO to Stage 1).** The observation-contradicted-eviction
mechanism (cross-KF free-space violation counting → delete live Gaussians) was
tested offline and fails to show a swept-ghost-specific signal on any of 4
diverse sequences. This closes the 2026-08-05 user-ratified reopening of the
α-carve eviction direction.

Branch: rethink-method. Repo: /data/monogs-ours.
Script: `scripts/stage0_eviction_probe.py` (zero-GPU, offline re-render of saved
final_after_opt PLY at saved trj_full_final est poses — the same render path as
the paper table). No live code changed.

---

## Setup

- Re-render saved final map per sampled frame (interval=5) on prune-arm seed-0
  of the four P2-T dynamic sequences: `balloon`, `mv_no_box`, `pt1`,
  `pt2` (each = datasets/runs/P2/P2-T/{seq}_prune_seed0).
- Free-space violation pixel V =
  `(render_depth < observed_gt − band) ∧ (render_opacity ≥ 0.5) ∧ valid ∧ ¬frozen-dynamic-mask`,
  band = `max(0.05, 0.02·z)`.
- Candidate Gaussians = those whose projected center lands on a V pixel AND whose
  camera-frame center depth is in front of observed by > band (two-sided rule).
- vac_excess (codex-requested disambiguator) =
  `P(V | vacated) − P(V | never-dynamic static control boundary-eroded)`.
  vacated = `(union of past frozen masks) ∖ current mask` (the swept-trail target).
  A positive excess ⇒ swept ghosts really are the violation source; ≈0 means the
  detector reads global pose/rendering bias.

### Critical correctness fix applied first
The rasterizer (`forward.cu:367`) accumulates unnormalized
`D += depth·α·T` (no division by accumulated opacity `1−T`). Raw `render_pkg["depth"]`
is therefore artificially SHALLOW on any semi-transparent pixel. We normalized:
`depth_norm = D/(1−T)`, gated by `render_opacity ≥ 0.5`. This is the codex-specified
disambiguation. (After the fix v_ratio barely moved, so the unnormalized depth was
NOT the whole story — the `≥0.5` opacity gate already covered it.)

---

## Results (all four sequences)

| seq | mover | v_ratio | **vac_excess** | cand n/frame | cand op p50 | cand op p90 | overlap_vac | verdict |
|---|---|---|---|---|---|---|---|---|
| balloon | ball | 0.375 | **+0.017** | 537 | 0.21 | 0.97 | 0.858 | ≈0 — no signal |
| mv_no_box | box | 0.417 | **−0.236** | 760 | 0.21 | 0.999 | 0.847 | negative |
| pt1 | person | 0.631 | **+0.281** | 684 | 0.47 | 0.996 | 0.862 | positive mean, but artifact (below) |
| pt2 | person | 0.567 | **−0.176** | 1232 | 0.24 | 0.915 | 0.858 | negative |

---

## Why the positive pt1 mean is an artifact (not a swept-ghost signal)

Frame-level vac_excess by 50-frame window on pt1:

```
frames 0-49    +0.060
frames 50-99   -0.039
frames 100-149 -0.082
frames 150-199 -0.115
frames 200-249 -0.120
frames 250-299 +0.111
frames 300-349 +0.050
frames 350-399 +0.665   <-- vacated region has grown to ~whole scene
frames 400-449 +0.761
frames 450-499 +0.795
frames 500-549 +0.734
frames 550-599 +0.724
```

The positive mean (+0.28) is ENTIRELY driven by the last ~250 frames, during
which the fraction of violation pixels inside the vacated region rises 92%→100%.
Once `vacated ≈ whole static support`, the base-rate control is swallowed: every
diffuse violation is vacuously "in vacated", so vac_excess becomes meaningless
(the same balloon failure mode, just arriving late). The EARLY phase (frames
0-250, vacated still small) is NEGATIVE or ≈0.

pt2 (the twin person sequence) has mean **−0.176** with 95/114 frames negative —
no positive phase at all. The two person sequences are opposite signs. The
sign-flip across twin sequences, plus the time-profile collapse, rules out a
stable swept-ghost signal.

---

## Overlap_vac ~0.86 is a sampling trap, not precision

`overlap_vac` (fraction of candidate pixels inside vacated) looks strong at
0.83–0.86 on every sequence, but it is a conditional probability with a
diluting denominator: on these Bonn sequences the mover roams a large fraction
of the static support (balloon vacated = 66–84% per CONTEXT; pt1 tail = 100%),
so ANY spatially diffuse violation — including the global pose/rendering bias
that dominates — lands mostly inside the vacated region by area alone.
`vac_excess` (which subtracts the never-dynamic base rate) is the honest
measure, and it is ≈0 or negative on 3/4 sequences.

---

## Candidate opacity: low median, only a thin opaque tail

- cand op p50 = 0.21–0.47 (<0.5 on 3/4) ⇒ most candidates are semi-transparent /
  straddling Gaussians, not clear near-opaque occluders. Even if the detector worked,
  evicting them would not change the rendered surface (they contribute partial opacity).
- cand op p90 = 0.92–1.00 ⇒ a thin ~10% tail IS near-opaque, but these are scattered
  across static and dynamic regions alike, uncorrelated with the vacated dynamic signal.

---

## Consistent with CONTEXT's already-known facts

1. CONTEXT (2026-08-05) had already disqualified admission control as the wrong
   tool (background_reveal : foreground_conflict = 1.7–3.8× ⇒ pollution already in map).
   This probe now disqualifies the other lobe: free-space-violation eviction also
   has no observable dynamic-specific target — the violations are global, not ghost-bound.
2. The `gaussian_th=0.7` "all-opaque" reading in CONTEXT was an overstatement in the
   tail: the PLY stores raw logit-opacity, sigmoid-median ≈0.52, ~40% ≥0.9. The map
   is MOSTLY opaque at the top but has a long semi-transparent body, which is exactly
   what makes both (a) unnormalized depth shallow and (b) eviction candidates mostly
   low-opacity. We should correct that CONTEXT line.

---

## What this closes, and what it does NOT

CLOSED: evict live Gaussians driven by per-pixel free-space violation evidence, in
this mask-both backbone, on these sequences. Also closed: the "swept-region ghost
blocking rays" causal mechanism as a detectable, evictable population — it does not
materialize above global pose/rendering noise.

**Also closed (2026-08-06, forward probe): the FORWARD free-space constraint**
**(`L_freespace` as a mapping loss term).** The same vac_excess measurement applied
to the forward direction (measuring what penalty a forward constraint would apply
to each pixel) shows identical behavior: vac_excess ≈0 or negative on all 4
sequences, and the per-pixel penalty magnitude is near-identical in vacated and
never-dynamic regions. A forward free-space term would penalize global pose/rendering
bias uniformly, NOT preferentially clean swept ghosts. This is the same failure mode
as the reverse probe — the signal itself does not exist, so neither direction can use it.

Forward probe results (4 sequences, `scripts/forward_freespace_probe.py`):

| seq | fwd_viol_frac | vac_excess | penalty vac | penalty ctrl | verdict |
|---|---|---|---|---|---|
| balloon | 0.41 | +0.013 | 0.0107 | 0.0046 | ≈0 |
| mv_no_box | 0.43 | −0.234 | 0.0127 | 0.0199 | negative (ctrl higher!) |
| pt1 | 0.69 | −0.050 | 0.0468 | 0.0491 | ≈0 |
| pt2 | 0.63 | −0.174 | 0.0230 | 0.0249 | negative |

The free-space family (reverse evict + forward L_fs) is now fully excluded on this
backbone with these sequences.

NOT closed (do not claim we tested these):
- Map-compression / compactness (an orthogonal axis; deferred's compactness was
  under-seeding, and a genuine prune-based compactness without tracking cost is still
  untried).
- The one positive-admission fact that survived everything: on balloon the mask-leak
  ghost_excess depth 4.37→2.29 cm (−48%, 3/3 seed, non-overlapping) is real but costs
  −0.63 dB static PSNR — a local-benefit-against-global-cost admission effect, NOT an
  eviction effect.

## Recommended next: map-compression (genuine prune-based compactness)

Both free-space directions are dead. The remaining live direction with a clean
hypothesis is **map-compression**: can we prune Gaussians that contribute little to
the rendered output (low opacity, small footprint, far from the visible surface, or
redundant in dense regions) without degrading ATE? The deferred arm's compactness
was an accidental byproduct of under-seeding; S6's was a degenerate lifecycle.
Neither is a deliberate compression lever. The literature has numerous 3DGS
compression methods (scalar quantization, VQ, coreset, variational pruning,
Bayesian) but NONE is tested inside a live SLAM loop — they target static offline
scenes. A SLAM-compatible compression strategy that preserves tracking accuracy is
a clean gap with a measurable paper axis.

---

## Traceability
- 4×~90-frame offline probes, P2-T prune seed-0, `--no-flow-gate` (flow_gate is a
  future refinement, not the cause of these numbers — vac_excess is a base-rate
  comparison independent of the gate).
- Correctness: depth normalization fix applied before interpretation; overlap
  interpretation corrected after vac_excess exposed the base-rate trap.
- Codex adversarial rounds (3) informed the probe design (two-sided rule, vacated-
  region target, vac_excess disambiguator) but all three were run against this
  probe's *hypotheses* — the final kill is empirical, from the CSV.

---

## Deferred-arm replication (2026-08-06, ported to ours-v3/main)

The original CLOSED verdict was prune-arm seed-0 only. Re-ran stage0 on the
**deferred arm** seed-0 of the same 4 sequences (reject/expire residuals are the
natural eviction target under deferred admission — the gap rethink never filled):

| seq | vac_excess (deferred) | cand op p50 | cand op p90 | cand n/frame |
|---|---|---|---|---|
| balloon | **−0.0025** | 0.511 | 0.9995 | 291 |
| mv_no_box | **−0.215** | 0.618 | 1.000 | 517 |
| pt1 | **+0.262** (same tail artifact as prune) | 0.457 | 0.995 | 696 |
| pt2 | **−0.133** | 0.452 | 0.989 | 670 |

**Verdict unchanged: CLOSED strengthens.** vac_excess is ≈0/negative on deferred
just as on prune (balloon/mv_no_box/pt2 all ≤0; pt1's +0.26 is the same
last-~250-frame vacated≈whole-scene base-rate collapse already diagnosed for the
prune arm — two arms independently reproduce the same artifact, confirming it is
NOT a swept-ghost signal). Deferred candidates are more opaque than prune's (p50
0.45-0.62 vs 0.21-0.24, p90 ~1.0 vs ~0.92-0.996) — a real contrast, but it does
not produce a positive vac_excess: there is still no free-space violation
localized to the vacated/swept region on either admission path.

Mechanism note (mirror of terminal-compression GO): eviction dies because the
selectable candidates are semi-transparent floaters (an evictable floater is by
definition not blocking the revealed background), NOT because violations are
absent. This is the complementary half of "terminal op<0.01 deletes safe floaters":
the same floater population that is freely deletable offers no eviction target.

Compatibility fixes to `scripts/stage0_eviction_probe.py` (pure portability, no
algorithmic change; verified prune-balloon reproduces rethink's numbers):
us/vs np.meshgrid -> torch.from_numpy (numpy 1.26.4 no longer does numpy+Tensor),
drop double unsqueeze(0) on cur_flow, ok[...,None] explicit broadcast. Commit
`5afea2d` on port-rethink.
