# P3-DENSIFY-TAIL — does densify grad threshold control the op<0.01 tail width?

> **Status: PRE-RUN DECLARATIONS (§1-§3), committed before the first GPU run of this campaign.
> §4 holds results and is empty until runs complete.**
>
> Campaign ID `P3-DENSIFY-TAIL` · plan `P3` · results root `results/runs/P3/P3-DENSIFY-TAIL/` ·
> apparatus: runner `scripts/p3_densify_tail.py`, readout `scripts/p3_densify_tail_readout.py`,
> contract `tests/test_p3_densify_tail_configs.py`, configs `configs/rgbd/experiments/p3_densify_tail/`
> 3 arm configs × 6 seqs × 3 seed = 54 runs, batch 1 = seed0 (18 run, ~9h), batch 2 = seeds 1/2 (36 run, ~19h).
> **Post-hoc + non-preregistered ladder-wise** (chosen after terminal compression evidence and theory).
> What *is* pre-registered is this file's §2.

---

## §1 Why this campaign exists

**Theoretical premise** (from `papers/mmm/theory.md` + `papers/mmm/mechanism.md`):
op<0.01 tail is a steady-state product of the ADC loop. The densify gradient threshold
(`densify_grad_threshold`) controls how many new Gaussians are spawned per round:
- **lower** threshold → more clone/split events → more offspring inheriting low opacities → wider tail
- **higher** threshold → fewer clone/split events → narrower tail → less op<0.01 removable

**This is a predictive test of the mechanism claim.** If the mechanism is correct, the observable
`frac_op_lt_001` (the fraction of final-map Gaussians with sigmoid opacity < 0.01) **must** move
systematically with the densify threshold. If it does not, the mechanism claim is falsified.

**How this differs from everything else the project has measured:**
- This is neither a "does method A beat method B" nor a "does compactness work" question.
  It is a **mechanism isolation** experiment: can we *control* the tail width with a single
  known knob, in the direction theory predicts, **proving** the mechanism is understood
  and not a coincidence?
- The readout is a **histogram measurement** (fraction of final-map Gaussians < 0.01), not a
  rate-distortion comparison. The P2-T 3-seed final maps already exist in bak; we can measure
  their tail widths. The new runs are the A/B arms (higher/lower densify thresholds) on the same
  backbone.

**Why this is worth 54 runs.** A positive result (tail width tracks densify threshold in the
predicted direction) turns terminal compression from "an observation with a plausible mechanism
story" into "a **controlled** phenomenon with a **demonstrated** cause". That is a qualitatively
different paper contribution. A negative result (no movement) falsifies the mechanism claim and
forces us to look elsewhere — which is also valuable, and saves future work on a wrong track.

---

## §2 Pre-declared readings — WRITTEN BEFORE THE FIRST RUN

### §2.0 The predicting variable

`opt_params.densify_grad_threshold` — the gradient magnitude threshold below which
`densify_and_clone` / `densify_and_split` do not spawn new Gaussians.

Three arms:
| arm | densify_grad_threshold | predicted effect on frac_op_lt_001 |
|-----|----------------------|-------------------------------------|
| `LO` | 0.0001 (half default) | **more** clone/split → **wider** tail → **higher** frac_op_lt_001 |
| `BASE` | 0.0002 (default) | reference point |
| `HI` | 0.0005 (2.5× default) | **fewer** clone/split → **narrower** tail → **lower** frac_op_lt_001 |

**Prediction**: frac_op_lt_001(LO) > frac_op_lt_001(BASE) > frac_op_lt_001(HI), monotonically,
on every sequence.

### §2.1 Primary readout: frac_op_lt_001 = fraction of final-map Gaussians with sigmoid(opacity) < 0.01

Measured by loading the `final_after_opt` PLY and computing `(sigmoid(_opacity) < 0.01).mean()`.
This is a **zero-GPU, offline** measurement (same method as `mc_terminal_comp_3seed.py`'s
`opacity_hist` function).

### §2.2 Secondary readout: frac_op_lt_005 (to check if the effect is specific to the tail)

If the mechanism is correct, the effect should be **largest** at the extreme tail (op<0.01) and
**smaller** at op<0.05 (the latter includes some genuine surface detail — see balloon seed-1
breaking −0.087 dB at op<0.05).

### §2.3 Tertiary readout: frac_op_ge_090 (to check if the effect is specific to the tail)

If only the tail widens/narrows, the fraction of high-opacity Gaussians should be **stable**
across the three arms. If it moves, the densify threshold is affecting the whole opacity
distribution, not just the tail — which would weaken the mechanism story.

### §2.4 Decision rule: three branches per sequence

For each sequence, compare the three arms' frac_op_lt_001:

| branch | condition | interpretation |
|--------|-----------|----------------|
| **CONFIRMED** | LO > BASE > HI (strict monotonic, all 3 pairwise gaps > 0.005 = 0.5pp) | Mechanism claim supported: densify threshold controls tail width |
| **PARTIAL** | LO > BASE OR BASE > HI but not both, or gaps ≤ 0.005 | Mechanism partially supported: effect is in the right direction but weak or noisy |
| **FALSIFIED** | LO ≤ BASE, or BASE ≤ HI, or both (i.e., monotonicity violated in any direction) | Mechanism claim falsified: tail width is not controlled by densify threshold |

**Campaign-level statement:**
- **6/6 CONFIRMED or PARTIAL** → mechanism claim is supported across all sequences.
- **≥1 FALSIFIED** → mechanism claim is sequence-dependent at best, falsified as a general claim.
- **≥3 FALSIFIED** → mechanism claim is falsified. The theory is wrong.

### §2.5 Additional checks

1. **P2-T base run comparison**: The BASE arm's frac_op_lt_001 should match the already-measured
   values from the P2-T prune seed0 runs (balloon ~17%, mv_no_box ~10%, pt1 ~10%, pt2 ~12%).
   Discrepancy > 0.02 (2pp) flags an apparatus issue (different backbone, timing, etc.).
2. **Terminal compressibility**: For each arm, report how many Gaussians would be removed by
   op<0.01 deletion (replicating the terminal compression measurement). This connects the
   mechanism test to the paper's headline claim.
3. **Confound check**: Track VRAM, FPS, ATE, and vacated metrics to verify that the densify
   threshold change does not systematically break tracking or mapping quality on one arm.

---

## §3 Apparatus

### §3.1 Arms

| arm | config | knob value | predicted frac_op_lt_001 |
|-----|--------|-----------|--------------------------|
| `LO` | `p3_densify_tail_lo_{seq}.yaml` | densify_grad_threshold: 0.0001 | highest |
| `BASE` | P2-T's prune run config (identity import from `p2t.ARMS["prune"]`) | densify_grad_threshold: 0.0002 (default) | middle |
| `HI` | `p3_densify_tail_hi_{seq}.yaml` | densify_grad_threshold: 0.0005 | lowest |

The three arms differ ONLY in `opt_params.densify_grad_threshold`. Pinned by
`tests/test_p3_densify_tail_configs.py`.

### §3.2 Sequences

The 6 P2-T dynamic sequences: balloon, balloon2, mv_no_box, mv_no_box2, pt1, pt2.
All self-tracked on the combined backbone (same as P2-T prune arm).

### §3.3 Run plan

- **Batch 1** (seed0): 6 seqs × 3 arms = 18 runs, ~9h on 2060.
- **Batch 2** (seeds 1/2): 18 × 2 = 36 runs, ~19h on 2060.
- **Total**: 54 runs, ~28h.

### §3.4 Harness gates

- G1: exit 0
- G2: self-tracked (same check as P3-S6X: empty Oracle.pose_file, gt_pose off, cam lrs > 0)
- G3: knobs live (config echo check: the dumped config carries the expected densify_grad_threshold)
- G4: final_after_opt PLY exists (the primary measurement reads from it)
- G5: activity not FAIL

### §3.5 What this campaign does NOT decide

- This does not decide the compactness headline (already dead per narrative D).
- This does not decide whether terminal compression is a paper-worthy result (it is, per
  `03-contribution-sizing.md` + `04-paper-positioning.md`).
- This does not resurrect any deferred/prune lifecycle comparison.
- This does not provide a new ATE headline (densify threshold changes are not expected to
  systematically improve tracking).

---

## §4 Results (to be filled after runs)

### §4.1 Batch 1 seed0 screening

| seq | LO frac_lt_001 | BASE frac_lt_001 | HI frac_lt_001 | branch |
|-----|:-:|:-:|:-:|:-:|
| TBD | | | | |

### §4.2 Batch 2 (seeds 1/2)

| seq | LO frac_lt_001 (3-seed) | BASE frac_lt_001 (3-seed) | HI frac_lt_001 (3-seed) | branch |
|-----|:-:|:-:|:-:|:-:|
| TBD | | | | |

### §4.3 Campaign-level verdict

**TBD** — to be written after all 54 runs complete.