# Candidate B pre-registration — is the mask-free bistability driven by SEED or by TIMING?

> Registered **before** dispatch (exp32 criterion ①: null and threshold together, up front).
> Phase 0 of the staged budget: 12 runs, one sequence, ~2.3 GPU-h. Not a rate estimate yet.

## 1. Why this is worth GPU at all

Every judgement this project has made on the mask-free backbone used a **mean difference
across 3 seeds**. On `crowd2` the mask-free control spans **44.2 – 97.0 cm within a single
arm** (T2, `results/evidence/t2_quota_verdict.md`), and `f3_st_hf` produced a "−88.1 %" and a
"+1381.8 %" that were just *which side crashed*. We have therefore been reading a bimodal
distribution through its mean, and we have **never measured the crash rate itself**.

Two rival explanations have never been separated:

* **S (seed)** — the spread is the seed's doing; identical config + identical seed is stable.
* **T (timing)** — the spread comes from asynchronous frontend/backend scheduling, so
  identical config **and** identical seed still lands in different basins.

They imply opposite things about every number in the main table. Under **T**, a 3-seed mean
is not an estimate of a method effect at all, and the ≥6 % noise floor is a floor on the
*wrong* quantity.

## 2. Design (12 runs, one config, one sequence)

Config `configs/rgbd/experiments/t2_mad_quota/t2_control_maskfree_crowd2.yaml`, unchanged —
this is measurement of an existing arm, no mechanism is being altered.

| block | seeds | n | isolates |
|---|---|---|---|
| **T** | `0` repeated 6× (distinct output dirs) | 6 | timing alone: config and seed are identical |
| **S** | `1,2,3,4,5,6`, one run each | 6 | seed + timing together |

`crowd2` chosen because it is where the 44 → 97 cm split was actually observed, and at 895
frames it is cheap. One sequence only: Phase 0 asks "does it split", not "how often".

## 3. Readouts, fixed now

Primary, threshold-free: **within-block max/min ratio** and IQR of `ate_rmse_cm`
(`tables/tracking_raw.csv`, full-trajectory — never the console keyframe RMSE).

Secondary, thresholded: **collapse rate** = fraction of runs with `ate_rmse_cm > 50`. The
50 cm line is set from the regime structure, not from this data: the mask-ON backbone lives
at 2–3 cm and the observed split straddles 44/97, so 50 cm separates "converged" from
"diverged" by an order of magnitude either way. Registered before dispatch.

Descriptive: the frame index at which two runs of block T first diverge by > 5 cm — if
timing is the driver, there should be an identifiable bifurcation point, not a slow drift.

## 4. Verdict rule

* **T-CONFIRMED** — block T's max/min ≥ 1.5 (i.e. identical seed still splits).
  *Consequence: seed-averaged ATE is not a valid estimator on the mask-free backbone, and
  every mask-free judgement must be restated as a crash rate. This retroactively affects the
  main table's mask-free columns.*
* **S-CONFIRMED** — block T's max/min ≤ 1.1 **and** block S's ≥ 1.5. *Consequence: the spread
  is seed variance; the existing multi-seed protocol is sound but needs more seeds.*
* **NEITHER** — both blocks ≤ 1.1: the 44 → 97 cm event did not reproduce at all in 12 runs.
  *Consequence: that spread came from something not captured by config+seed (code state,
  data state); treat the T2 crowd2 numbers as unexplained until it is found.*
* **INDETERMINATE** — any other combination; report and do not extrapolate.

## 5. What this does NOT settle

The crash *rate* (needs ≥ 20 runs for a usable confidence interval) and whether the same
mechanism operates on `f3_st_hf`. Both are Phase 1, and are only bought if Phase 0 splits.
Candidate C (per-Gaussian temporal motion probability) stays blocked until a crash-rate
baseline exists, because its secondary criterion ("ATE not worse by > 5 %") is unreadable
against a ≥ 6 % noise floor of unknown shape.
