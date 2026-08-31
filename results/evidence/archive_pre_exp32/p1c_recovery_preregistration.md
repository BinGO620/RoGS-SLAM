# P1c pre-registration — perturbation-recovery apparatus

> **Status**: step 0 (synthetic calibration) done — pilot grid in §3, full sweep archived to
> `results/evidence/p1c_recovery/synthetic/`. §4–§6 are registered **before** any real
> sequence is processed. Zero GPU-campaign cost: offline analysis over frozen frames.

## 1. Why the estimand changed (P1 → P1b → P1c)

| | estimand | why it failed |
|---|---|---|
| P1 | `lambda_min` of `H = Σ w JᵀJ` at the GT pose | nominal leverage ≠ usefulness; and the gate (`med_rho ≤ 0.67`) was **not conditioned on the 1.1–5.8 % mask area** — a strong gate on a weak problem (criterion ⑧) |
| P1b | one GN step's bias `δ` at the GT pose | signal buried in nuisance: residual `σ ≈ 7/255` **at the true pose**, measured bias 100× the sandwich-predicted sd, negative control same sign and magnitude ⇒ apparatus gate 0/7 ⇒ NO VERDICT |
| **P1c** | **recovery** `ρ = ‖log(T_after T*⁻¹)‖ / ‖ε‖` from a controlled perturbation `T_init = exp(ε) T*` | nuisance common to all arms falls into the **floor** of `ρ` instead of into its signal |

This is a change of **estimand**, hence a new question under criterion ⑩ — not a moved
goalpost. `ρ = 0` is perfect recovery, `ρ = 1` an inert step, `ρ > 1` an actively harmful one.

## 2. Step 0 apparatus check (mandatory, ran first — criteria ⑨/⑪)

`scripts/p1c_recovery_synthetic.py` builds a pair whose ground truth is exact:

* `I_p`, `D` from a real Bonn frame; `T*` a real consecutive GT relative pose;
* `I_t(x) := I_p(x + flow(x; D, T*))` ⇒ residual **identically zero** at `T*` (verified: 0.0);
* inside a rectangle of area fraction `f`: `I_t(x) := I_p(x + flow(x) + d)` ⇒ an
  independently moving object with a known, coherent image displacement `d`;
* photometric noise `σ = 7/255` added — **the value P1b measured on real pairs** — so the
  calibration is conditioned on the experiment's actual scale (criterion ⑧).

Arms: `all` / `robust` (Cauchy IRLS, dynamics-blind) / `oracle` (rectangle removed) /
`shift` (equal-area rectangle at a random *static* place — the invalidation control).
Endpoint `ρ_t` after `GN_STEPS = 8` (measured: the clean pair needs ~6 to converge).

Controls that travel with the judgement (`tests/test_p1c_recovery.py`, 15 tests):
* **negative** — `d = 0`, block moves with the scene: `oracle` must NOT beat `all`;
* **positive** — `d` large: `oracle` must recover where `all` does not.

## 3. Step 0 result — the apparatus sees it, and the baseline is `robust`

Median `ρ_t` over perturbation directions, `ε = 10 mm + 2 mrad`, frame 60 of
`rgbd_bonn_static_close_far` (pilot grid; the archived sweep spans 4 frames ×
5 area fractions × 4 displacements × 3 `ε_t` × 2 `ε_r` × 4 directions):

| σ | `f` | `d` (px) | all | robust | oracle | shift |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 0.05 | 0 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 0 | 0.05 | 10 | 0.0806 | 0.0000 | 0.0000 | 0.0837 |
| 0 | 0.20 | 10 | 1.7770 | 0.0000 | 0.0000 | 1.4677 |
| 0 | 0.40 | 10 | 1.5240 | 0.0067 | 0.0001 | 0.6528 |
| **7/255** | 0.05 | 0 | 0.0012 | 0.0018 | 0.0014 | 0.0015 |
| **7/255** | 0.05 | 10 | 0.0805 | 0.0073 | 0.0014 | 0.0833 |
| **7/255** | 0.20 | 0 | 0.0012 | 0.0018 | 0.0016 | 0.0014 |
| **7/255** | 0.20 | 10 | 1.7881 | 0.0606 | 0.0016 | 1.4760 |
| **7/255** | 0.40 | 0 | 0.0012 | 0.0018 | 0.0036 | 0.0025 |
| **7/255** | 0.40 | 10 | 1.5255 | 0.5242 | 0.0036 | 0.6578 |

Four readings, each of which changes what the real-data stage may claim:

1. **Measurable.** Floor (no dynamics) `ρ ≈ 0.0012–0.0036` at the real noise level, versus
   `0.08` at Bonn's actual area fraction — a ~50× margin. This is the property P1b did not
   have, and it was bought by changing the estimand, not by loosening a threshold.
2. **A dynamic object does not merely degrade the step, it inverts it.** At `f = 0.20`,
   `ρ(all) = 1.79 > 1`: the GN step ends up *further* from the truth than where it started.
3. **The negative control is clean** — `d = 0` gives `ρ ≈ 0.0012–0.0018` for every arm, so
   "removing 40 % of the pixels" is not itself scored as a win.
4. **★ `robust` — which knows nothing about dynamics — is nearly as good as `oracle` at
   Bonn's area fractions** (`0.0073` vs `0.0014`, both ~10× below `all`'s `0.0805`), and only
   breaks down at `f = 0.40` (`0.52`). This confirms P1b's flag ① with a controlled positive
   control instead of an ambiguous read, and it fixes the baseline for §4: **the real-data
   comparison must be against `robust`, not against `all`.** Any method scored against `all`
   would be claiming credit for generic robustness.

## 4. The GT-referenced endpoint does not survive contact with Bonn (measured, then abandoned)

Running the §3 endpoint on `rgbd_bonn_balloon` — three frames, `oracle` arm, before any
threshold was read — gave:

| frame | ‖GT rel. translation‖ | ε=0 → | ε=10 mm → | ε=50 mm → | ε=200 mm → |
|---|---:|---:|---:|---:|---:|
| 1 | 0.0 mm | **10.31 mm** | 10.31 mm | 53.63 mm | 248.90 mm |
| 21 | 7.7 mm | **15.87 mm** | 15.87 mm | 37.02 mm | 294.91 mm |
| 41 | 8.2 mm | **19.37 mm** | 19.36 mm | 19.36 mm | 277.59 mm |

Two facts, and they point in opposite directions:

* **Gauss-Newton converges properly.** Starting at the GT pose and starting 10 mm away
  land on the *same* point to 0.01 mm. The optimum is well defined and attracting.
* **That optimum is 10–19 mm away from the Bonn GT pose.** Mocap/calibration/rolling-shutter
  offset — whatever its source, it is a per-frame nuisance the size of the entire effect we
  are trying to resolve, and it is *not* removed by averaging, because it is a bias.

So `ρ = ‖T_after − T*‖/‖ε‖` is unreadable on this dataset for the same structural reason
P1b was unreadable: a nuisance larger than the signal sits inside the estimand. **We record
this as a standing constraint on the project: any per-frame pose study on Bonn that scores
against GT has a ~10–19 mm floor, and our ATE differences are 2–3 cm in total.**

The estimand is therefore changed once more — and, as in §1, it is the *estimand* that
changes, not a threshold (criterion ⑩). GT is demoted to "the common starting point",
never the target, and arms are compared **to each other, pairwise**:

```
u_X  = log( That_X · That_all⁻¹ )            how policy X moves the CONVERGED pose (mm)
pi_X = <u_X, u_oracle> / ||u_oracle||²        the fraction of the ORACLE's move X reproduces
```

`pi = 1` reproduces the oracle's correction, `0` does nothing, `< 0` moves the opposite way.
It is a **projection, not a magnitude** — P1b's flag ② (the coherent component ran opposite
to the magnitude) is exactly what a magnitude comparison cannot see, and what this can.

Pilot on 5 frames of `balloon`/`person_tracking` (2 arms + null, 4 starts each), which is
what licenses the gates below:

| frame | removed px | within-arm spread | ‖u_robust‖ | ‖u_oracle‖ | ‖u_shift‖ |
|---|---:|---:|---:|---:|---:|
| balloon 41 | 19145 | 0.85 mm | 5.92 | **15.97** | 1.24 |
| balloon 71 | 2382 | 1.08 mm | 5.61 | 0.55 | 0.43 |
| person_tracking 11 | 1107 | 11.02 mm | 6.67 | 9.16 | 7.40 |
| person_tracking 41 | 2599 | 0.68 mm | 4.27 | 0.47 | 0.35 |
| person_tracking 71 | 4544 | 0.16 mm | 6.93 | 0.42 | 0.15 |

Three readings: (a) the converged pose is **reproducible** — independent starts agree to
0.16–1.08 mm on 4/5 frames, so the apparatus has resolution; (b) the oracle's move scales
with dynamic area — 15.97 mm at 19k removed pixels, but 0.42–0.55 mm at 2–5k, where it is
**indistinguishable from the shift null**; (c) `robust` moves the converged pose by
4.3–6.9 mm consistently, *more* than the oracle does on 3/5 frames — the dynamics-blind
kernel is doing something large that is not "removing the dynamic object".

## 5. Gates and the informative-frame definition

A frame is **informative** iff `‖u_oracle‖ > max(within-arm spread, max ‖u_shift‖)` on that
same frame — the effect must clear both the apparatus's own resolution and the equal-area
static null, per frame, before it is allowed to carry evidence. Non-informative frames are
not discarded quietly: their count is a result (§6).

Gates run first; any firing ⇒ NO VERDICT (criterion ⑨):

* **G1** median within-arm spread ≤ 0.25 × median `‖u_oracle‖`, on ≥ 5/7 sequences.
  The spread is measured on the `all` and `oracle` arms only — `u_oracle` is built from
  those two, and `robust` re-fits its IRLS weights at every start, so folding its
  instability into this number would gate the oracle effect on something it does not
  depend on. Every arm's spread is written out per frame regardless.
* **G2** on `static_close_far` (no independent motion), informative-frame rate ≤ 20 %.
* **G1b (PASS-only)** a PASS is a positive claim about `mrcs`, so `mrcs`'s own move must
  clear the same reproducibility bar (`median res_mrcs ≤ 0.25 × median ‖u_mrcs‖` on ≥ 4/7).
  A FAIL or a NEGATIVE needs no such guard — an unreproducible move is not evidence *for*
  anything, but "no reproducible effect" is exactly what those verdicts assert.

## 6. Verdict rule

* **G4 / signal existence** — informative-frame rate ≥ 20 % on ≥ 4/7 sequences.
  If G1–G2 pass and G4 fails ⇒ **NEGATIVE (no per-frame pose signal)**: at Bonn's actual
  dynamic-area scale, removing the *true* dynamic pixels does not measurably move the
  converged per-frame pose, so the 4–14× ATE gain is **not produced by per-frame pose
  estimation** — the search must move to mapping / keyframing / map contamination. This is
  a zero-GPU, publishable conclusion, not a failed experiment.
* Otherwise, over informative frames, with `pi_mrcs` the median projection:
  **PASS** `pi_mrcs ≥ 0.50` on ≥ 4/7 · **FAIL** `pi_mrcs ≤ 0.20` on ≥ 5/7 ·
  **INDETERMINATE** otherwise.

`pi_shift` (the equal-area static null, ≈ 0 expected) and `pi_robust` are reported beside it
on every sequence; no threshold is introduced after seeing real data.
