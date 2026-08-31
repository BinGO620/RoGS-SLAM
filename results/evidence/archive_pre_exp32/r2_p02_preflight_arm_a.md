# R2-P02 pre-flight arm A — CHECKPOINT-2 closed, four arms complete (2026-07-29)

3/3 runs exit=0 · ~13.2 min/run · `oracle_prune_balloon.yaml`, diff vs arm B = exactly
`{method, Mapping.lifecycle_mode}` over the resolved key set · `Oracle.pose_file` byte-identical to
arms B/D/E, `cam_rot_delta = cam_trans_delta = 0.0` · commit `58983c1` · raw
`results/runs/R2-P02/R2-P02-PREFLIGHT-rgd/preflight_results.jsonl` · readout
`scripts/r2_p02_preflight_readout.py` (`df44e51`).

**The whole pre-flight is now 12 runs, arms A/B/D/E × seeds {0,1,2}, and `ate_rmse_cm` is
2.0618 on all twelve.** The pose channel is frozen across the entire dataset, so every contrast
below is a pure map-side contrast.

**Verdict: CHECKPOINT-2 fails. All three pre-registered gates on the headline now have data, and
all three are inside the noise band. The corollary clears by 10–13×.** GO/KILL narrative remains
the user's (prereg §9).

## 1. The pre-registered gates, all four arms, one table

`static_vacated_psnr` (amendment #01 headline, ↑ better). Denominator = the **larger** of the two
arms' own 3-seed sd. prereg §6 additionally requires the sign to hold on every seed.

| gate | contrast | diff (dB) | /larger own sd | per-seed sign | verdict |
|---|---|---|---|---|---|
| **CHECKPOINT-1** (H1a: exit works) | D − B | +0.2222 | 1.00 | 2/3 | **inside band** |
| **H1b** (fill is the key) | E − D | +0.0172 | 0.08 | 2/3 | **inside band** |
| **CHECKPOINT-2** (H1: beat prune) | **E − A** | **+0.1705** | **0.86** | **2/3** | **inside band** |
| — (not a gate) | E − B | +0.2394 | 1.29 | 3/3 | clears, weakly |

Per-arm raw headline, three seeds each:

| arm | seed 0 | seed 1 | seed 2 | mean | own sd |
|---|---|---|---|---|---|
| A_prune | 14.4096 | 14.7938 | 14.5103 | 14.5712 | 0.1992 |
| B_deferred | 14.5165 | 14.4953 | 14.4952 | 14.5023 | **0.0123** |
| D_exit | 14.7962 | 14.9024 | 14.4749 | 14.7245 | 0.2226 |
| E_exit_fill | 14.9069 | 14.7765 | 14.5417 | 14.7417 | 0.1851 |

**CHECKPOINT-2's margin is one seed.** Per-seed E − A is **+0.497 / −0.017 / +0.031**: seed 0 alone
supplies 97% of the +0.1705 mean, and seed 1 reverses. This is the failure mode prereg §6 was
written to catch ("GO 需 ≥2 seed 同向，禁止单 seed 宣胜"), and it is the same shape as
CHECKPOINT-1's (D seed 2 sitting below every B run).

Arm A is also *not* the noisy arm here — its headline sd (0.1992) is comparable to D's and E's. The
band that E fails to clear is not an artifact of a badly-behaved control.

## 2. Arm A was active (its activity gate reads SKIP, and that is correct)

`check_arm_activity.py` reports **SKIP** on all three arm A seeds. That is not a silent failure:
arm A carries no `AlphaLifecycle` block, so there is no α ledger to check — the same reading arm B
gets. Arm A's treatment is `Mapping.lifecycle_mode: prune`, and its activity is evidenced directly
by the map: **25228 ± 1375 Gaussians vs arm B's 11296 ± 878, with non-overlapping per-seed ranges**
(A min 24274 > B max 12084). The insert-then-prune policy demonstrably ran a different insertion
regime. This is the E2-class VOID risk closed by a different instrument, not left open.

## 3. The result that does clear noise — and it is the pre-registered corollary

`refined_num_gaussians` (↓ better), per seed:

| arm | seed 0 | seed 1 | seed 2 | mean ± sd | CV | vs A | /larger own sd | sign |
|---|---|---|---|---|---|---|---|---|
| A_prune | 26805 | 24274 | 24606 | 25228 ± 1375 | 5.5% | — | — | — |
| **B_deferred** | 10349 | 12084 | 11454 | 11296 ± 878 | 7.8% | **−55.2%** | **10.13** | **3/3** |
| D_exit | 12584 | 5844 | 8140 | 8856 ± 3427 | **38.7%** | −64.9% | 4.78 | 3/3 |
| **E_exit_fill** | 9731 | 8538 | 8302 | 8857 ± 766 | 8.6% | **−64.9%** | **11.90** | **3/3** |

**Every A run has more than twice the Gaussians of every B run and nearly three times every E run.**
The ranges do not overlap; the sd ratio understates the separation.

The historical R2-P01-E2 claim was **−57% (deferred vs prune)**. Under a pose-controlled screen, on
the same commit, with the metric's noise now calibrated (arm A CV 5.5%, arm B CV 7.8%), it
reproduces at **−55.2%**. That is the first time this project's load-bearing number has been
measured with the pose channel held fixed.

Peak VRAM follows, 3/3, at a comparable ratio: A 1.006 GB → B 0.804 (−20.1%, **11.93×**) → E 0.7806
(−22.4%, **13.32×**). Throughput: E +8.7% FPS over A (2.97×, 3/3).

## 4. "At equal fidelity" — now a measurement, not an assertion

The corollary's premise is that the compact map is not paid for in quality. B − A, three seeds:

| metric | A | B | diff | /larger own sd | sign | reading |
|---|---|---|---|---|---|---|
| `static_vacated_depth_l1_pen_cm` ↓ | 37.645 | 37.647 | **+0.0018** | **0.00** | 2/3 | identical |
| `static_vacated_psnr` ↑ | 14.5712 | 14.5023 | −0.0689 | 0.35 | 1/3 | indistinguishable |
| `static_psnr` ↑ | 15.019 | 14.935 | −0.0843 | 0.47 | 1/3 | indistinguishable |
| `static_depth_l1_pen_cm` ↓ | 38.062 | 37.986 | −0.0763 | 0.06 | 2/3 | identical |
| `static_ssim` ↑ | 0.6472 | 0.6684 | **+0.0213** | **2.70** | **3/3** | **B better** |

Same for E − A: PSNR-family differences run 0.21–0.89× and all favour E; `static_ssim`
+0.0248 at **3.15×, 3/3**.

So on the pre-registered fidelity family, a 55–65% smaller map costs **nothing measurable** — the
vacated-region depth deficit, which is the pre-registered PRIMARY, differs by 0.002 cm on a 37.6 cm
scale. "Equal fidelity" is quantified rather than claimed.

**One caveat I am flagging rather than banking.** SSIM is the only fidelity metric that separates,
and it favours the compact arms in both independent contrasts (B−A 2.70×, E−A 3.15×, 3/3 each). It
was not the pre-registered arbiter, and it is one of ten metrics examined here, so treating it as a
second win would be exactly the metric-shopping amendment #01 §A was written to prevent. It is also
consistent with a plain mechanical story — arm A's 25k Gaussians buy per-pixel intensity fit while
degrading local structure — so it is worth *checking* if the campaign continues, not citing now.

## 5. Where all pre-registered gates stand, final

| gate | status |
|---|---|
| CHECKPOINT-1 — D beats B on headline (H1a) | **failed** — +0.222 dB = 1.00×, sign flips on seed 2 |
| H1b — E beats D on headline (fill is the key) | **failed** — +0.017 dB = 0.08×; E worse on vacated depth 3/3 |
| **CHECKPOINT-2 — E beats A on headline (H1)** | **failed** — +0.171 dB = 0.86×, sign flips on seed 1, 97% of the mean is seed 0 |
| fidelity veto (prereg §6) | **not triggered** — nothing degrades systematically in any arm |
| compactness corollary | **holds** — −55.2% (B−A) at 10.13× and −64.9% (E−A) at 11.90×, 3/3, pose-controlled, at fidelity indistinguishable to 0.00–0.47× |

Nothing in the pre-registration is now unrun. The α mechanism is real and measurable — it fires on
every seed, it improves the map — but on the region the paper is about it is inside the band against
every one of its three pre-registered comparators, and the F2 finding stands as the reason: the
improvement lands in the 16% non-vacated periphery (+1.59 dB, 3.17×, 3/3), not the 66% vacated
region.

prereg §6's fallback for exactly this state is "compactness 推论 + 干净负结果（诚实报告），**不**改
headline 去挑别的赢指标". The measurements above are that fallback's evidence base, and the
compactness half of it is now stronger than when it was written: pose-controlled, noise-calibrated,
3/3, with non-overlapping ranges, and with "equal fidelity" measured on the pre-registered PRIMARY.

## 6. Cost and provenance

Arms A and E were committed **before** launch (`b6c3594`, arm A's CFG wiring), so unlike the B/D
campaign (§9 of `r2_p02_preflight_pose_rgd.md`) there is no provenance split on these six runs.
Total pre-flight spend: 12 runs × ~12–13 min ≈ **2.5 h on the 2060**, against the 2.3 h estimate.

Decision reserved for the user (prereg §9, amendment #01 §C, 08-04 date gate). Two items still
awaiting the user's call, unchanged: the GO/KILL narrative, and whether
`check_arm_activity.py:137-141` should stop reporting FAIL when a fill-mode arm legitimately
inserts zero.
