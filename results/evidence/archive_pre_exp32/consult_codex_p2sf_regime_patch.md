# codex 复审 — P2-SF regime patch（2026-08-02，第二轮）

> 输入 = `consult_brief_p2sf_regime_patch.md`。模型 = codex MCP（gpt-5.5/high），read-only。
> thread `019fc292-764f-7393-82b7-067736125116`。**原样记录**；综合见
> `consult_synthesis_p2sf_readout.md` §6–§10。

---

# P2-SF Regime Patch Re-review

## Bottom Line

This patch does **not** justify reversing the preregistered `C primary / B sensitivity` ordering. More importantly, it makes cross-variant synthesis less defensible: C and B are operating in sharply different mapping/fidelity regimes, so B cannot validate, calibrate, or explain C.

It **strengthens** the recommendation to stop and write the limitation. Do not run `--phase full` under the current apparatus.

There is also a provenance error in the patch's central premise: the `1.56 cm / 0.28 dB` margins were **applied** in R2-P03's 14–15 dB frozen-pose regime, but they were **derived** as one null SD from seven identical-algorithm self-tracked replicates:

- vacated depth: mean `23.425 cm`, SD `1.559 cm`
- vacated PSNR: mean `21.103 dB`, SD `0.278 dB`

See `r2_p02_e2_metric_calibration.txt:13` and the explicit provenance in `r2_p03_sweep.md:67`. R2-P03 did not estimate those margins from its own 14–15 dB runs.

## Q1. Is C-pt1's `+2.423 cm` still a breach?

**Mechanically yes; scientifically uncalibrated.**

The preregistered rule imported `1.56 cm`, so the honest readout remains:

> C-pt1 exceeded the preregistered inherited depth margin: `+2.423 cm > 1.56 cm`.

It cannot now be relabelled a "false breach." That would be post-hoc threshold replacement. But it also cannot be presented as a calibrated fidelity loss for C, because the imported null SD has not been shown to transport across pose, keyframe, sequence, and map-size regimes.

The patch offers no basis for choosing between "false breach" and "underestimated breach":

- One seed provides no C-specific null variance.
- A change in absolute PSNR does not determine the variance of the **depth** metric.
- Even for PSNR, matching or mismatching an absolute mean does not establish matching or mismatching SD.
- C-balloon2 is actually near the original null-calibration PSNR mean (`21.1 dB`); C-pt1 is higher. B is farther away at `15 dB`.

Therefore write it as a **preregistered-margin exceedance with unknown calibration validity**, not as confirmed harm and not as a harmless false positive.

## Q2. Should B become primary because it matches the 14–15 dB regime?

**No. That inference fails twice.**

First, as noted above, `14–15 dB` was the R2-P03 application regime, not the regime from which the margins were estimated. On absolute PSNR, B matches R2-P03, while C-balloon2 more closely matches the actual `21.103 dB` null-calibration mean. Neither observation proves variance transportability.

Second, even if the margins really had been derived at `14.5 dB`, equality of absolute PSNR would still be insufficient. Calibration requires the null distribution under comparable:

- pose injection,
- sequence,
- keyframe schedule,
- lifecycle activity,
- map scale,
- and metric support.

B matches only one scalar mean while differing radically on the rest. Its pt1 prune map is `13,258` Gaussians versus C's `56,915`; its lifecycle activity and KF schedules also differ. Calling B "boundary-applicable" from PSNR alone would be calibration by coincidence.

Consequently:

- **C remains primary only in the preregistered/protocol sense.**
- **B remains a sensitivity experiment**, but no longer a quantitatively commensurate sensitivity analysis.
- B cannot overrule C's fidelity readout or supply C's missing null distribution.
- Neither variant currently has a regime-specific fidelity margin strong enough for substantive equivalence or harm claims.

This does not rehabilitate B. It demotes the comparability of **both** variants.

## Q3. Does the 9 dB split strengthen "B/C measure different things" and stopping?

**Yes, materially.**

The approximately `6–9 dB` cross-variant shift is stronger evidence of non-transportability than the `4.3x` pt1 map-size shift because it shows that the intervention changes not just representation size but the achieved image-fidelity operating point. A `9 dB` PSNR difference corresponds to roughly an eightfold MSE ratio, not a minor scale displacement.

But "only pose quality changed" is too narrow. Changing injected poses also changed downstream KF schedules, mapping exposure, lifecycle activity, and map size. Therefore the data identify a **pose-regime × mapping-policy interaction**, not pose quality alone.

The defensible conclusion is:

> C and B are different controlled-regime experiments. Their rank reversal and large absolute fidelity separation prevent cross-variant mediation or robustness interpretation.

This further supports **stop and write limitation**:

- More seeds would estimate repeatability within two noncommensurate regimes.
- They would not calibrate the inherited fidelity margins.
- They would not repair the divergent KF schedules.
- They would not reconnect the frozen experiment to the self-tracked main table.
- They would not convert B into a valid sensitivity analysis for C.

A future experiment would need matched KF schedules and regime-specific repeated null controls, ideally across prespecified pose-error levels. That is a new apparatus, not `--phase full`.

## Q4. Is the vacated guardrail no longer arm-discriminating?

**The patch weakens its interpretation, but does not prove that it is non-discriminating.**

"Arm-discriminating" and "mechanism-specific" are different. A sign difference can discriminate arms while still being caused by global map-regime changes rather than vacated-region lifecycle behavior.

The claimed quadrant-wide sign chaos is also overstated:

- C-pt1 does show a genuine PSNR region reversal: deferred is slightly worse in vacated PSNR (`24.33 < 24.41`) but better in non-vacated PSNR (`24.31 > 23.72`).
- B-pt1 is deferred-better in both regions.
- B-balloon2 appears prune-better in both reported PSNR regions.
- Thus the supplied table demonstrates one clear within-cell region reversal, not a systematic four-cell reversal pattern.

Still, C-pt1 is enough to show that raw vacated PSNR is not a stable proxy for whole-map fidelity. Combined with the cross-variant regime split, the metric is presently:

- usable as a preregistered descriptive guardrail;
- not calibrated for C- or B-specific equivalence;
- not evidence of a vacated-region mechanism;
- not the "unique calibrated-usable contrast" in any strong inferential sense.

## Revised Recommendation

Keep H-D **INDETERMINATE**. Do not upgrade or assign a P2-SF branch.

Report the C-pt1 margin exceedance exactly, attach the calibration-transport limitation, treat B and C as noncommensurate controlled regimes, and retain the earlier recommendation: **do not run the current `--phase full`; stop and write the limitation.**
