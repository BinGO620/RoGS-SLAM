# R2-P02 pre-flight arm E — the 补侧 contrast (2026-07-29)

3/3 runs exit=0 · ATE **2.0618 cm** on all three · ~12 min/run · same screen, same frozen
trajectory, same commit family as the B/D campaign · config `oracle_alpha_exit_fill_balloon.yaml`
(`b6c3594`), diff vs arm D = exactly `{method, AlphaLifecycle.mode}` over 289 resolved keys ·
raw `results/runs/R2-P02/R2-P02-PREFLIGHT-rgd/preflight_results.jsonl`.

**Verdict: H1b falsified. The pre-registered 补侧 contrast is +0.0172 dB — 0.08× the arm's own
noise.** Read with the B/D result (`r2_p02_preflight_pose_rgd.md`, F2), the H1 mechanism chain
does not survive on the headline region. GO/KILL narrative remains the user's (prereg §9).

## 1. Fill fired — this is not a second VOID

| arm | seed | steps | skips | reset | carve | **fill inserted** | cleared_px | vacated_px | vacated/cleared |
|---|---|---|---|---|---|---|---|---|---|
| E | 0 | 19 | 0 | 3905 | 31 | **2687** | 67157 | 8141 | 12.1% |
| E | 1 | 19 | 0 | 3533 | 11 | **1155** | 18619 | 1155 | 6.2% |
| E | 2 | 19 | 0 | 2726 | 5 | **105** | 51671 | 105 | **0.2%** |

Arm-activity PASS on all three seeds. The `51252fe` observability earned itself immediately:
KF103 of seed 0 logged `inserted 0 -- no vacated pixel (now_cleared=209, ...)` — a zero that is
now *attributable* instead of the silent zero that made E2 unreadable.

## 2. H1b — the 补侧 contribution is null on the headline region

`static_vacated_psnr` (amendment #01 headline, ↑ better). Per-arm own sd from 3 seeds:

| contrast | diff | /pooled sd | **/larger own sd** | per-seed sign |
|---|---|---|---|---|
| **E − D** (= fill, the H1b claim) | **+0.0172** | 0.08 | **0.08** | 2/3 |
| E − B (full method vs deferred) | +0.2394 | 2.43 | 1.29 | **3/3** |
| D − B (= exit, H1a) | +0.2222 | 1.89 | 1.00 | 2/3 |

`static_vacated_depth_l1_pen_cm` (↓ better) says the same or worse: **E − D = +0.629** (E worse),
3/3 consistent in that direction, 0.42× noise.

**Fill adds nothing to the vacated region.** prereg H1b said the opposite — "补侧(E)是打赢 prune
的关键 … 靠'补'填洞才低 depth_l1". Arm E's vacated depth is *higher* than arm D's on all three
seeds.

## 3. Why it fails, mechanically — the 补侧 premise mostly does not occur

The 补侧 assumes: exit removes a ghost → a hole over real background is exposed → fill it.
The counters say that chain is rare. Of the pixels exit actually cleared, the fraction that were
occluding observed background is **12.1% / 6.2% / 0.2%**.

So **88–99.8% of what exit clears was not hiding any background** — there is no hole to fill,
and `detect_vacated_pixels` correctly declines. Fill's activity then collapses 26× across seeds
(2687 → 1155 → 105); on seed 2 it effectively did not happen.

This is the same finding as F2 §5 seen from the other side. Exit's benefit is spread across the
whole image because what it removes is mostly not vacated-region ghost. Fill, which is spatially
targeted by construction, therefore has almost nothing to target.

## 4. Fidelity — no harm, and no vacated-region win either

E vs B, three seeds, `|d|` over the larger own sd:

| metric | E − B | ratio | sign | reading |
|---|---|---|---|---|
| `static_psnr` ↑ | +0.2590 | 1.32 | **3/3** | small consistent gain |
| `static_vacated_psnr` ↑ | +0.2394 | 1.29 | **3/3** | small consistent gain |
| `static_ssim` ↑ | +0.0035 | 0.77 | 2/3 | flat |
| `static_depth_l1_pen_cm` ↓ | −0.9122 | 0.47 | 1/3 | mixed |
| `static_freshvac_ghost_excess_psnr_db` ↑ | +0.0533 | 0.35 | 2/3 | flat |
| `static_ghost_excess_depth_l1_cm` ↓ | +2.3898 | 0.66 | 2/3 | flat/worse, unusable metric |

No fidelity veto triggered (prereg §6): nothing degrades systematically. But nothing on the
vacated region clears its own noise either.

## 5. The one effect in this entire pre-flight that clears noise 3/3 — and it is the corollary

| metric | B | E | E − B | ratio | sign |
|---|---|---|---|---|---|
| **`online_num_gaussians`** | 11296 ± 878 | **8857 ± 766** | **−2439 (−21.6%)** | **2.78** | **0/3 (E fewer on every seed)** |
| `online_peak_gpu_memory_gb` ↓ | 0.8040 ± 0.0108 | 0.7806 ± 0.0141 | −0.0234 | 1.66 | 0/3 (E lower every seed) |
| `online_fps` ↑ | 7.876 ± 0.549 | 8.483 ± 0.156 | +0.607 | 1.11 | **3/3** |

Arm E is also *stable* where arm D is not: E's Gaussian-count CV is **8.6%** vs D's **39%** — fill
appears to re-regularise what exit destabilises, even though it does not improve the map metric.

So the measured package is: **equal-or-slightly-better fidelity, ~22% fewer Gaussians, lower VRAM,
higher FPS, consistent on 3/3 seeds** — under a pose-controlled screen, which R2-P01-E2's version
of this claim never had.

**This does not become the headline.** prereg §2(a) fixed compactness as "α 机制天然副产品，同表
出现，不当卖点" and §6's fallback is explicitly "compactness 推论 + 干净负结果（诚实报告），**不**改
headline 去挑别的赢指标". Recording it as the corollary it was pre-registered to be.

## 6. Where the pre-registered checkpoints now stand

| gate | status |
|---|---|
| CHECKPOINT-1 — D beats B on headline (H1a) | **failed** — +0.222 dB = 1.00× D's own sd, sign flips on seed 2 (F2) |
| H1b — E beats D on headline (fill is the key) | **failed** — +0.017 dB = 0.08×; E is worse on vacated depth 3/3 |
| CHECKPOINT-2 — E beats A/prune on headline (H1) | **not runnable on this screen — no arm A run here** |
| fidelity veto | not triggered |
| compactness corollary | holds, 3/3, 2.78× noise, now pose-controlled |

**The honest statement.** Both mechanism links the pre-registration set up as prerequisites for H1
fail on the headline region, measured against a control arm whose seed-to-seed spread is 0.021 dB.
This is not a seed-count problem and not an instrument problem — the instrument is the cleanest
this project has built, and that is precisely why the null is legible.

## 7. What is still missing, and why it is needed under every branch

**Arm A (prune) × 3 seeds on this screen, ~36 min.** `oracle_prune_balloon.yaml` already exists
(R2-P01-E2 used it). It is required under both outcomes:

- **To close CHECKPOINT-2 formally.** Right now H1's terminal gate is *unrun*, not *failed*. A
  pre-registered negative result with an unrun checkpoint is incomplete, and the pre-registration's
  whole purpose was to make the verdict evidence-driven rather than narrative-driven.
- **To give the compactness corollary its load-bearing contrast.** The historical claim is
  **A-vs-B** (prune vs deferred, −57% in R2-P01-E2) — never noise-calibrated or pose-controlled.
  This pre-flight measured B and E only. Arm A supplies the missing half, on the same screen, same
  frozen trajectory, same commit.

Deliberately *not* reusing R2-P01-E2's on-disk arm A: it is a different campaign and commit, and
E2 §4 measured a 1.5–2.0 cm cross-campaign shift on arm A with configuration unchanged.

Decision reserved for the user (prereg §9, amendment #01 §C, 08-04 date gate).
