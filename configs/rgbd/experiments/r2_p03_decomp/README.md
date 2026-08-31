# R2-P03-DECOMP — which knob produced S6's dominance?

**Post-hoc, non-preregistered** (added *after* seeing `R2-P03-SWEEP`'s data; the evidence file
`results/evidence/r2_p03_decomp.md` marks it as such, the paper must too, and it does **not**
enter the pre-declared ladder or alter the R2-P02 H1 record).

`R2-P03-SWEEP` closed with **1/6 rungs dominating arm B**: `S6_maxpress` reached 0.63×B's map
size at fidelity inside both non-inferiority margins. But S6 moved **three knobs at once**:

| knob | family | in this codebase because… |
|---|---|---|
| `DeferredCommit.ttl_keyframes` 5 → 1 | candidate-lifecycle **admission budget** | the deferred mechanism exists |
| `Training.gaussian_th` 0.7 → 0.9 | **native** MonoGS opacity prune | stock MonoGS |
| `opt_params.densify_grad_threshold` 2e-4 → 5e-4 | **native** densification gate | stock MonoGS |

So the campaign could not answer the question that decides whether a mechanism claim survives:
**is the compactness win deferred-specific, or does one generic densify knob capture it?**

## The cells

Every file here is a knob overlay on arm A (`r2_oracle_admission/oracle_prune_balloon.yaml`),
same frozen RGD balloon trajectory (`Oracle.pose_file`, `cam_rot_delta = cam_trans_delta = 0`).

| cell | config | knobs vs arm A default | role |
|---|---|---|---|
| `A0_prune` | `r2_oracle_admission/oracle_prune_balloon.yaml` | — | 2×2 "neither" cell + control anchor |
| `D0_ttl1` | `r2_p03_sweep/sweep_s2_ttl1_balloon.yaml` (reused verbatim) | `ttl_keyframes: 5 → 1` | admission budget only (= SWEEP `S2`, re-run in-campaign) |
| `D1_densifyonly` | `decomp_d1_densifyonly_balloon.yaml` | `densify_grad_threshold: 2e-4 → 5e-4` | **the decisive cell**: generic knob only |
| `D2_ttl1_densify` | `decomp_d2_ttl1_densify_balloon.yaml` | both of the above | interaction cell = S6 **minus** `gaussian_th` |
| `B_deferred` | `r2_oracle_admission/oracle_deferred_balloon.yaml` | — | the operating point under test |

`D0` deliberately points at the **existing frozen SWEEP config** rather than a copy: the
in-campaign ttl-only cell is then provably the same file that produced S6's `S2` row, and its
re-run doubles as a same-config cross-campaign drift measurement on top of §5 of
`r2_p03_sweep.md`.

`gaussian_th` alone is **not** re-run here — `R2-P03-SWEEP` already measured it at 3 seeds
(`S5_gth090`, 1.43×B) and it is not on this decomposition's critical path.

## Why anchors are re-run instead of reused

README "跨 campaign 比较禁令": same config / same live code / same machine drifted **+12–15%**
in mean Gaussian count one day apart (single seed up to +47%), and
`static_vacated_depth_l1_pen_cm` drifted **+1.44 cm ≈ 92% of the 1.56 cm margin**. Reusing the
SWEEP B row as this campaign's anchor could manufacture or mask the verdict outright. Both
anchors run inside this campaign, at one commit, on one machine.

The only quantities compared across campaigns are **ratios to the in-campaign B anchor**, each
labelled with its campaign — the form the README permits for trend statements.

## Decision rule

Inherited **by import, not by copy**, from `scripts/r2_p03_sweep_readout.py` (`RATE`,
`DECISION`, `degradation`): rate = `refined_num_gaussians`; decision family =
`static_vacated_depth_l1_pen_cm` (margin 1.56 cm) + `static_vacated_psnr` (margin 0.28 dB);
dominance = rate ≤ B's mean **and** both degradations ≤ margin. `scripts/r2_p03_decomp_readout.py`
adds one **descriptive, pre-declared-before-any-DECOMP-run** column — where a cell that misses
B's mean sits relative to B's rate **noise band** — so that the middle outcome cannot be
argued about after the fact. It does not modify the dominance rule.

Runner `scripts/r2_p03_decomp.py`, readout `scripts/r2_p03_decomp_readout.py`, contract
`tests/test_r2_p03_decomp_configs.py`, evidence `results/evidence/r2_p03_decomp.md`.
