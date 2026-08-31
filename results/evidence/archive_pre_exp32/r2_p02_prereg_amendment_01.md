# R2-P02 pre-registration amendment #01 — headline modality + pose-controlled screen

> **Written 2026-07-29 01:25, BEFORE any pre-flight datum existed.** The canary
> (`--phase canary --pose rgd`, commit `4b7eaf0`) started 01:23 and had produced no
> metric row when this file was committed — verifiable from `preflight.log`'s
> `START`/`END` timestamps and this file's commit time. That ordering is the entire
> point of the document: prereg §0 names "swap in a metric that wins" as this
> project's recurring failure mode, so a metric change is only distinguishable from
> that failure mode if it is recorded pre-hoc with its justification.
>
> Amends `next_plan_alpha_exit_fill_prereg.md` (LOCKED 2026-07-27). §§1–4, 7, 8 are
> untouched: hypothesis, arms, sequences and novelty boundary all stand as written.

## A. What changes, and why it is calibration rather than metric-shopping

**Original (prereg §5 PRIMARY):** `static_vacated_depth_l1_pen_cm`, lower better.

**Amended:** on the pose-controlled screen, the headline readout is
`static_vacated_psnr` (higher better), reported alongside `static_ghost_excess_psnr_db`
as a cross-check and `static_nonvacated_psnr` as a confound sentinel. The
pre-registered depth field is still computed and reported on every row — it is
demoted, not dropped, so the swap stays auditable.

Three measured facts forced this, all of them recorded before any arm contrast was
resolvable, and none of them selected by which arm they favour:

1. **The depth headline cannot resolve any claim.** Deficit-to-noise 0.1× on the
   pre-registered support; the vacated-minus-background gap ranges −2.17…+3.30 cm
   with no consistent sign against a 1.56 cm null sd (`r2_p02_e2.md` §8.2). No
   method could have won *or lost* on it. Mechanical cause: `past_union` unions
   every earlier dynamic mask with no decay, so after 439 frames "where the mover
   has ever been" is 66% of the image and the metric tracks global map quality.
2. **PSNR on the same support can.** Deficit-to-noise 9.9×. The modality changed;
   the support and the arms did not.
3. **The recency window — the fix that looked more principled — failed**, and is
   recorded as failed (ratio 6.6× < 9.9×; it shrinks the deficit more than the
   noise). Recording the losing candidate is what keeps this from being a search
   over metrics for a winner.

**Why raw PSNR and not the paired contrast, in this regime specifically.**
`ghost_excess = vacated − nonvacated` exists to cancel pose drift. Under a frozen
trajectory shared by both arms there is no drift left to cancel, while its confound
stays live: in the R2-P01-E2 posthoc rescoring the non-vacated reference — 16% of the
support — moved **+1.71 dB** between arms while the vacated signal moved **−0.02 dB**
(`r2_p02_preflight_posthoc_note.md` §3). The entire 1.73 dB / 6.6σ "prune wins"
margin came from the denominator, on a vacated region where the two arms were
indistinguishable. A metric whose reference moves 85× more than its signal is not
measuring the claim. Hence: raw vacated PSNR leads, contrast cross-checks,
nonvacated is printed so a repeat of the confound is visible rather than folded
into the headline (implemented in `4b7eaf0`).

**Scope limit.** The headline *region* — 腾空区 (vacated) ghost — does **not** change.
Neither do the arms or the hypothesis. Changing the region would be exactly the §0
failure mode; changing the modality on a region whose instrument was measured
unusable is not. If the amended instrument also fails to resolve, the answer is the
honest-negative route of §6, not a third metric.

## B. The pose-controlled screen is a screen, never a paper row

prereg §8.4's reasoning stands and is restated as binding: the claim under test is
map **admission** and is positioned tracker-orthogonal, so a 30 cm ± 2.6 cm
self-tracked trajectory puts the dominant noise inside the one channel the claim
disowns. Frozen-pose (`rgd`, ATE 2.0618 cm) is the correct screening instrument.

**It cannot appear as the paper's main table.** The headline table stays full SLAM.
Any GO reached on the screen must be re-demonstrated self-tracked at E3 before it is
claimed. This constraint is recorded now so that a screen-only win cannot later be
promoted by convenience.

## C. Fork rules, pre-committed before data

Proposed this session and started on the user's "开始吧"; the **GO/KILL narrative
remains reserved for the user** per prereg §9. These are mechanical gates, not
verdicts.

| fork | condition | action |
|---|---|---|
| **F1** | D arm-activity PASS **and** \|D−B\| on `static_vacated_psnr` > per-arm seed sd | E2 re-run under the pose-controlled screen; run CP-1 / CP-2 |
| **F2** | D active but D≈B inside the noise band | substantive negative for **H1a** (α-exit acts but does not move the headline region). prereg §6 authorises "先修 exit" — **one round only** (tau_reset / tau_carve / β), then §6's fallback |
| **F3** | noise does not collapse under frozen pose, or an activity/support gate fails | headline unwinnable in the time remaining → §6 fallback immediately, no further iteration |

**Date gate: 2026-08-04.** If the campaign has not landed on a fork by then, F3
applies unconditionally. DDL is 2026-08-16 AOE and writing must start ~08-06.

The §6 fallback is unchanged and is not a new headline: honest negative result on
H1, plus the compactness corollary reported as a corollary.

## D. Free calibration to read out of the same six runs

The compactness fallback (−57% Gaussians, R2-P01-E2) has **never been noise-calibrated
or pose-controlled**, and E2 measured `refined_num_gaussians` null sd = 5577 (CV 21%)
self-tracked. The pre-flight's B/D × 3 seeds under frozen pose yield the first
pose-controlled estimate of that dispersion at no extra GPU cost. It is already in the
script's Q1 table. If the campaign ends at F2/F3, this number is a precondition for
citing the compactness result at all — recorded here so it is not discovered as
missing during writing.

## E. Unchanged

§1 hypothesis (H1/H1a/H1b) · §2 locked design (Fork B; α drives 出+补 only) · §3
grounding · §4 arms A–E · §6 CHECKPOINT-1/2 structure and the fidelity veto · §7
sequences and seeds · §8 novelty boundary · §9 GO/KILL reserved for the user.
