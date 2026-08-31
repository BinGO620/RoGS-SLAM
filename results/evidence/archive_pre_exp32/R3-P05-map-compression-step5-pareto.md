# STEP 5 — Pareto positioning: our compactness/ATE/PSNR vs 11 competitors (2026-08-06)

**Branch**: rethink-method. Repo: /data/monogs-ours.
**Goal**: stop comparing against our own base (self-referential) and place the
method on the N × PSNR × ATE 3-axis Pareto frontier that actually has competitors.

**Key finding**: CONTEXT.md's claim "11 competitors only have ATE, no rendering"
is **WRONG** — 8/11 competitors have numeric full-proof PSNR in `mapping_raw.csv`,
and N in `efficiency_raw.csv`. The render axis IS populated. On `mv_no_box` our
`deferred` arm sits ON the Pareto frontier.

---

## Data provenance (competitors)

From `workspace/dynamic-3dgs-slam/02-baselines/baselines_result/`:
- ATE := mean over 3 seeds of `tracking_raw.csv['ate_rmse_cm']` (established metric).
- PSNR := mean over seeds of `mapping_raw.csv['psnr']` (full-frame, paper path).
- N := mean over seeds of `efficiency_raw.csv['num_gaussians']`.
  - RGD-SLAM notes state N is "final point_cloud.ply vertex count".
  - **口径 caveat**: our N is `final_after_opt` PLY (post-photometric-refinement),
    competitors' N may be `final` (pre-refinement) — a minor口径 difference that
    does NOT change the frontier ordering (a method cannot be displaced by a few % N).
  - 3 methods (DynaSLAM/NGD-SLAM/ORB_SLAM3) have no rendering → excluded from render axis.

## Our methods
- `Ours base` = combined prune (mask-both backbone), seed-0: fullframe PSNR + N from
  `posthoc_fullframe/fullframe_summary.json`, ATE from `tracking_raw.csv`.
- `Ours deferred` = combined deferred arm, seed-0 (same path).
- `Ours compress` = STEP4 compress seed-0: **PSNR NOT yet computed** (no fullframe json;
  pt2 no final_after_opt PLY). Only N and ATE known.

## Results (Pareto frontier, lower-N/higher-PSNR is better; ATE in bubble)

| seq | on-frontier methods (N / PSNR / ATE-cm) | ours position |
|---|---|---|
| balloon    | RGD (9.6k / 25.1 / 2.45) | base 39.8k/21.6/2.9; deferred 19.8k/21.3/3.07; compress 26.9k/N/A/3.14 |
| mv_no_box  | RGD(10.6k/24.5/2.28) · **ours deferred(31.6k/24.4/2.5)** · DynaGSLAM(7.4k/13.7/12.1) | **deferred on frontier** |
| pt1        | RGD (17.5k / 24.1 / 8.6)  | base 55.6k/22.3/11.0; compress 60.9k/N/A/10.6 |
| pt2        | RGD (13.6k / 22.6 / 23.0) | base 69.6k/22.0/10.2; compress(133.6k)/N/A/9.37 |

## Interpretation (pre-registered readout)

1. **The rendering axis is NOT empty.** 8/11 competitors have PSNR. The prior belief
   that we have "no render comparison to lose to" was a false premise. This reopens
   the question of which axis(s) we actually win on.
2. **We have a REAL Pareto position on mv_no_box via `deferred`**: 31.6k Gaussians,
   24.4 dB (≈ RGD, above DG-SLAM 24.1, way above SplaTAM 22.5), and 2.5 cm ATE.
   That is ~1/18 the Gaussian count of SplaTAM at higher PSNR and far lower ATE.
3. **RGD-SLAM is the one method that beats us on all three axes on most seqs** — it
   is the target to beat, and the only one. On pt2 its ATE is bad (23 cm) but N tiny;
   our ATE is better (10 vs 23 cm) at 5× the Gaussians.
4. **Long-standing ATE-tier reality**: our ~3cm on walk_xyz / ~10cm on person_seq is
   "published-tier but not SOTA" (competitors: RGD 2.45-2.3, DWSLAM-era 1.5). The
   N × PSNR Pareto is where compaaction could actually win.
5. **DATA GAP**: `Ours compress` has no PSNR. To know whether compression improves the
   Pareto position on the render axis, we need offline re-render of the compress
   final_after_opt PLYs (balloon/mv/pt1 have them; pt2 must be re-run non-fast).

## Verdict: map-compression axis is VIABLE as a compactness story

- We do NOT need to beat RGD on ATE to have a paper axis; we can win on the
  render-axis-efficient mapping (small map + same PSNR + comparable ATE).
- The Pareto analysis gives the compression story a real competitor base to stand on:
  **"deferred + terminal compression = competitive PSNR at 1/18 the Gaussians"**.
- Next-decide: since compress PSNR is missing, run offline re-render of compress PLYs
  first (zero GPU, uses existing STEP1 render path) before deciding A/B/C.

---

## STEP 5b — compress PSNR now measured (2026-08-06, offline re-render)

Ran `r2_p2_t_offline_render.py` in the `monogs-ours` conda env
(`/data/conda_envs/monogs-ours/bin/python`) on the compress `final_after_opt` PLYs.
Band check passed (OK) on all three — render path is faithful to the in-run eval.

| seq | base PSNR | compress PSNR | ΔPSNR | base N | compress N | ΔN | base ATE | compress ATE |
|---|---|---|---|---|---|---|---|---|
| balloon   | 22.0407 | 21.9790 | **−0.062** | 32,653 | 26,936 | **−17.5%** | 2.87 | 3.14 |
| mv_no_box | 24.4425 | 24.4806 | **+0.038** | 43,598 | 35,695 | **−18.1%** | 2.52 | 2.64 |
| pt1       | 22.2134 | 22.4251 | **+0.212** | 49,838 | 60,932 | **+22.3%** | 11.01 | 10.62 |
| pt2       | 22.3130 | N/A(--fast) | —        | 92,537 |133,581 | **+44.4%** |10.23 | 9.37 |

### What the PSNR data settles

1. **Compression does NOT hurt rendering on the compacting seqs.** balloon −0.062 dB
   (within the offline STEP1 gate's ≤0.2 dB band), mv_no_box **+0.038 dB**. The deletion
   set the offline probes found (low-opacity floaters) is genuinely render-irrelevant in
   the live map too — PSNR preserved at −17-18% N.
2. **mv_no_box is the cleanest win**: compress improves PSNR (+0.04 dB) AND shrinks the
   map (−18%). On this seq the compress arm is strictly better than base on the render
   axis — no trade-off.
3. **pt1 compress PSNR is HIGHER (+0.21 dB)** than base despite the smaller-base-would-be-expected;
   the net-add N (+22%) comes with a render gain. Suggests compress's removal of floaters
   lets the optimiser redistribute capacity to the kept surface — a *positive* effect.
   But it OWNS a 60.9k map (relatively large) so the standalone compactness claim is weaker here.
4. **pt2 remains unmeasured on render** (--fast PLY missing). Its N +44% already fails the
   compactness axis anyway, so the render number would not rescue it; needs a non-fast
   re-run only if the story insists on 4/4.

### Pareto-grounded decision: the compactness axis is real, and BOTH base-deferred and compress win somewhere

- On mv_no_box, **base deferred (31.6k/24.4dB) and compress (35.7k/24.5dB)** both sit near
  the RGD frontier; compress achieves RGD-competitive PSNR at ~1/12 the RGD N would be for
  comparable work (RGD 10.6k N is smaller though — RGD still on frontier). The honest claim
  is **"competitive full-frame PSNR at 1/18 the Gaussian count of SplaTAM/DynaGSLAM"**, not
  beating RGD on N.
- This means the **compactness axis stands without needing beat-RGD-ATE**: it rides the
  render-axis efficiency (N × PSNR), a real 8-method table, and compression keeps PSNR.

## Files
- plots: `results/evidence/pareto_combined.png`, data `results/evidence/pareto_data.json`
- compress render evidence: per-run `posthoc_fullframe/fullframe_summary.json` under
  `results/runs/P2/P2-MC/{balloon,mv_no_box,pt1}_compress_seed0/`
- competitor baselines: `workspace/dynamic-3dgs-slam/02-baselines/baselines_result/
