# R3-P05 STEP 2A: terminal compression — 3-seed replication (2026-08-06)

**VERDICT: TERMINAL COMPRESSION IS A REAL, REPLICABLE COMPACTNESS RESULT at op<0.01
(8.4-18.4% removal, |dPSNR| ≤ 0.0001 dB, 12/12 runs). op<0.05 is NOT a safe band
(balloon seed1 breaks −0.087 dB). The mechanism probe directly CONFIRMS why STEP4's
online per-window compress failed: the ADC regrows the low-opacity tail it deletes.**

Branch: rethink-method. Repo: /data/monogs-ours.
Probe: `scripts/mc_terminal_comp_3seed.py` (offline, zero-training: load final_after_opt
PLY, delete sigmoid-op < threshold via `_prune_raw`, re-render at saved est poses,
interval-5 full-frame PSNR). Run with `/data/conda_envs/monogs-ours/bin/python`
(torch 2.1.0+cu118, CUDA available on the 2060).

---

## Body results (12 runs: 4 seqs × 3 seeds, base prune)

| seq | seed | op<0.01 rm% | dPSNR | op<0.05 rm% | dPSNR |
|---|---|---:|---:|---:|---:|
| balloon   | 0 | 12.8% | −0.0001 | 20.4% | −0.0156 |
| balloon   | 1 | 18.4% | −0.0001 | 27.8% | **−0.0867** |
| balloon   | 2 | 17.3% | +0.0001 | 27.4% | −0.0273 |
| mv_no_box | 0 |  9.9% | +0.0000 | 15.0% | −0.0110 |
| mv_no_box | 1 |  8.4% | −0.0000 | 12.2% | −0.0324 |
| mv_no_box | 2 | 10.0% | −0.0001 | 14.6% | −0.0118 |
| pt1       | 0 |  9.9% | +0.0000 | 12.6% | −0.0059 |
| pt1       | 1 | 10.1% | −0.0000 | 13.1% | −0.0041 |
| pt1       | 2 | 10.3% | +0.0000 | 13.5% | −0.0046 |
| pt2       | 0 | 18.4% | −0.0000 | 23.6% | −0.0030 |
| pt2       | 1 | 11.2% | +0.0000 | 14.7% | −0.0041 |
| pt2       | 2 | 10.5% | +0.0000 | 13.9% | −0.0048 |

Mean op<0.01 removal: balloon 16.2% · mv_no_box 9.4% · pt1 10.1% · pt2 13.4%.
Mean op<0.05 removal: balloon 25.2% · mv_no_box 13.9% · pt1 13.1% · pt2 17.4%.

## Interpretation

1. **op<0.01 is the SAFE, REPLICABLE band.** Every one of the 12 runs keeps the map
   within |dPSNR| ≤ 0.0001 dB while removing 8.4-18.4% (mean 9-16%) of Gaussians.
   This is a strictly-better-than-crossover result that holds across seeds AND seqs,
   satisfying CONTEXT:156's single-seed rule. The low-opacity tail below 1% is
   uniformly disposable floater — 100% reproducibly.
2. **op<0.05 is NOT a safe band.** STEP1 (seed-0 only) claimed ≤0.016 dB at op<0.05,
   but balloon seed-1 breaks −0.087 dB. The 0.05-0.10 opacity band carries *some*
   surface detail on some seeds. Paper should NOT use op<0.05; use op<0.01 (or 0.02).
3. **Robustness is uneven across seqs.** balloon has the most op<0.01 removables
   (16.2%) and the largest spread (8.4-18.4%); mv_no_box/pt1 are tight (~9-10%,
   ±1%). pt2 is fertile (13.4%) but its base N is also the noisiest (57.6k-92.5k).
4. **Foldable into the Pareto story**: terminal op<0.01 compression is the
   "zero-render-cost map shrink" that the STEP5 Pareto positioning wanted — it adds
   a N↓ axis movement at flat PSNR, on top of the base method's own N vs PSNR vs ATE
   frontier position.

## Mechanism probe — why STEP4 failed (opacity histogram base vs compress)

Dumped sigmoid-opacity histograms (n_total, frac below thresholds) of the compress
final maps (would have been the low-opacity population STEP4 deleted):

| seq | base frac_op<0.05 (mean 3 seeds) | compress-seed0 frac_op<0.05 | Δ |
|---|---|---|---|
| balloon   | ~0.25 (0.20/0.28/0.27) | **0.175** | compress map still 17.5% low-opacity |
| mv_no_box | ~0.14 (0.15/0.12/0.15) | **0.149** | ≈ flat (compress still has the tail) |
| pt1       | ~0.13 (0.13/0.13/0.14) | **0.122** | ≈ flat |
| pt2       | — (no compress PLY, --fast) | — | N/A |

**Direct confirmation**: STEP4's per-window compress *did* delete low-opacity floaters
(net-delete logs showed Σcompress up to 12× final N), yet the ENDING map has essentially
the SAME low-opacity tail as base (mv/pt1 flat; balloon slightly lower but still 17.5%).
⇒ **The ADC (densify clone/split + insert-then-prune) regrows the low-opacity tail that
online deletion removes.** The terminal-map floater population is a steady-state product
of the adaptive density process, not a process-once accumulation. This is why STEP4's
online compress could never win against densify (and why the ledger's "2-12× final N
deleted" was the signature of the regrowth loop, not under-powering).

## Verdict and next-step implication

- **GO on compactness as a terminal-compression paper axis.** op<0.01 gives a
  replicable 9-16% map shrink at ~0 dB render cost — a clean, honest, reproducible
  compactness contribution. NOT online (STEP4 dead by mechanism), NOT op<0.05.
- STEP4's online per-window compress is **closed by root cause** (ADC regrowth loop),
  consistent with the earlier ledger finding that final N is insertion-budget-decided.
- 2B (budget-bound online density control) is the only live-loop lever left, but the
  ledger + this probe both say it's fighting the ADC's steady-state — high risk of
  recreating S6's degenerate lifecycle. Recommend NOT pursuing 2B unless the paper
  specifically needs a *live* (not terminal) compactness mechanism.

## Files
- Probe: `scripts/mc_terminal_comp_3seed.py` (+ `--hist-only` mechanism mode)
- Runner: `scripts/run_mc_step2a.sh`
- Raw output: `results/evidence/R3-P05-map-compression-step5b-terminal-3seed.runlog`
- Per-run summaries: `each_run_dir/posthoc_terminal_comp/op010|op050/terminal_summary.json`
  and `.../opacity_histogram.json`
