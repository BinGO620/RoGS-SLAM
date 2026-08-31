# P2-T final verdict (36/36, 2026-08-02)

> Runner DONE 02:49:42 (24 new runs this tranche, 36 total). Readout: `p2t_readout_final.md`.
> 3-seed means. Decision margins IMPORTED from SWEEP (vac_depth≤1.56cm, vac_psnr≤0.28dB).
> H-D three-branch per `hd_coverage_prereg.md` §4. ATE no-harm 50% band per §3.

## Main table (3-seed mean ± own sd)

| seq | prune G±sd | deferred G±sd | prune ATE±sd | deferred ATE±sd | G_def/G_prune |
|---|---|---|---|---|---|
| balloon | 39784±5511 | 19803±267 | 3.07±0.14 | 3.11±0.16 | 0.498 |
| balloon2 | 33524±2631 | 30519±4236 | 5.22±0.15 | 5.84±0.16 | 0.910 |
| mv_no_box | 40806±4228 | 31561±2529 | 2.58±0.05 | 2.87±0.27 | 0.773 |
| mv_no_box2 | 65343±7680 | 50655±16848 | 4.68±0.02 | 5.61±0.14 | 0.775 |
| pt1 | 55596±4072 | 44154±1313 | 10.97±0.03 | 11.51±2.18 | 0.794 |
| pt2 | 69609±16219 | 44196±1961 | 10.35±0.56 | 16.80±4.44 | 0.635 |

## H-D three-branch verdict: **INDETERMINATE**

- Judgable seqs (|ratio−1| > 2× own_sd band) = 3: **balloon 0.498, mv_no_box 0.773, pt1 0.794** — all <1 (deferred better), same direction, **no counterexample**.
- INDETERMINATE seqs (in band, high own_sd): balloon2 0.910, mv_no_box2 0.775 (own_sd 16848), pt2 0.635 (own_sd 16219).
- **prereg §4 CONFIRMED requires "(a)/(b) coverage ranks don't flip"** — (a) per-frame vs (b) ±15fr union ranks FLIP on pt2 (r1→r3) and pt1 (r3→r1) ⇒ INDETERMINATE trigger fires.
- High-coverage side (balloon2 59.4%, should be >1) = 0.910 in-band ⇒ not independently supported.
- Spearman(cov_a, ratio) = +0.257, p=0.62 (n=6; prereg reports direction only, not significance).

**H-D lands INDETERMINATE** as predicted by codex #7/#8 "indeterminacy" warning and the seed-1/2 partial readout. 3/3 judgable low-coverage (<1.0) direction is the surviving directional observation; the monotone-coverage-stratifier form is NOT supported.

## ATE no-harm 50% band

| seq | deferred ATE | prune ATE | % worse | band |
|---|---|---|---|---|
| balloon | 3.11 | 3.07 | +1.3% | ok |
| balloon2 | 5.84 | 5.22 | +11.9% | ok |
| mv_no_box | 2.87 | 2.58 | +11.2% | ok |
| mv_no_box2 | 5.61 | 4.68 | +19.9% | ok |
| pt1 | 11.51 | 10.97 | +4.9% | ok |
| pt2 | 16.80 | 10.35 | **+62.3%** | **FLAG** |

- **deferred ATE ≥ prune on 6/6** (codex+hermes: 6/6 same-sign → "trade" not "indistinguishable"; P=0.031 exchangeability but sign-test not preregistered → exploratory).
- **pt2 breaches the 50% no-harm band (+62.3%)**. Per prereg §3: pt2 标注 "deferred ATE 显著更差", 放弃该序列 no-harm 措辞, 改诚实报告。
- **pt2 +62% is driven by pt2_deferred_seed2 = 23.07cm outlier** (seed0/1 = 13.46/13.46 stable; seed2 = 23.07). NOT catastrophic per §7 (ATE<100cm, G within 3× median). Kept in table, never dropped. pt2_deferred high variance (±4.44) is the box-family bistability (prereg §6.4).
- **No "ATE no-harm" method-level failure** (§3 trigger = "多条序列 >50%劣化" — only pt2; 5/6 in band). But the 6/6 same-sign + pt2 breach together ⇒ per codex/hermes: upgrade deferred-ATE to **conditional trade on a Pareto frontier**, NOT "no-harm"/"indistinguishable".

## What this upgrades from screening (08-01) to verdict (08-02)

1. **骨干成立 = backbone HOLDS** (P2 max risk eliminated, confirmed at verdict): 6/6 seqs no collapse, ATE all table-worthy. balloon 3.07/mv_no_box 2.58 competitive with RGD-SLAM 2.26 / DG-SLAM 3.65.
2. **compactness 非普适 = CONFIRMED at verdict** (not "weakening"): judgable direction is uniformly <1 on low-coverage seqs; high-coverage side indeterminate. The boundary is real; the simple monotone coverage stratifier is not.
3. **H-D = INDETERMINATE** (the prediction, now settled): not confirmed, not falsified — 3 judgable same-direction but (a)/(b) rank flip + high-coverage side in-band.
4. **deferred-ATE = conditional trade** (upgraded from screening): 6/6 same-sign, pt2 breaches band.

## Decision (per prereg §8/§9 + consult_synthesis_p2t.md)

- H-D section → one-sentence limitation (NOT a confirmed section), per prereg §8 INDETERMINATE branch.
- Narrative D′ (codex+hermes consensus): headline = lifecycle applicability-boundary MEASUREMENT (not "deferred wins"); 2×2 central table; compactness<1 reproduces on unseen low-cov seqs; deferred-ATE = trade/frontier.
- **GO/KILL + narrative = user retained** (双审 gave D′ recommendation, did not decide).
- Frozen-pose pt1 de-confounding control apparatus READY (commit 9c5ab53) — tests hermes's tracking-difficulty confound with map-level observables; runs in GPU gap; cannot upgrade H-D, only weaken/unchanged.
