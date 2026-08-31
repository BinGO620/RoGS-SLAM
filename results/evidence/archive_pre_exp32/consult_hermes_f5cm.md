# Consult: how to report F@5cm on Bonn (MMM 2027)

**Date:** 2026-08-02  **Confidence:** high on the diagnosis, high on the recommendation.
**Verdict: option (c) — drop the F@5cm column for Bonn, lead with vac_depth / vac_psnr + compactness G_def/G_prune. Do NOT report absolute F@5cm, and do NOT report prune-vs-deferred directional F@5cm either.**

---

## 1. The alignment is unfixable by ANY rigid transform — and I now know why

Your Umeyama best-fit residual (mean 114 cm, p90 115 cm, tight spread) is the decisive evidence: a tight spread on a 1.14 m residual means *systematic*, not noise. No rigid transform closes the gap. Re-tuning `T_BONN_MARKER` / `T_BONN_ROS` cannot help — that is exactly what Umeyama already optimised globally, and it still left 1.14 m.

**Root cause (confirmed from the data on disk):** the Bonn official mesh
`rgbd_bonn_groundtruth_1mm_section.ply` is **NOT in the same world frame as the
`groundtruth.txt` poses** that your SLAM init frame is built from.

- `groundtruth.txt` first pose: `t = (0.172, -1.546, 1.915)` — z ≈ +1.9 m.
- GT ply bbox (your diagnostic): `z ∈ [-5.12, -1.04]` — entirely negative z, ~3 m deeper and offset in y.

These two cannot co-exist in one frame. The static formula
`T_g = T_ROS^{-1} T_0 T_ROS T_m` only swaps ROS-body ↔ optical and applies the
frame-0 pose; it assumes the ply and the trajectory share a world origin. They
do not. The ply was built by the Bonn authors with their own external fusion
(likely a separate registration / laser scan pass — the file header literally
says `CloudCompare (TELECOM PARISTECH/EDF R&D)`, i.e. a post-processed export,
not the raw pose-fused cloud). So the residual is a **coverage + non-rigid
registration mismatch**, exactly as you suspected.

This is **not a bug you can fix in time**, and it is **not a flaw in your
method** — it is a frame-convention mismatch between two Bonn assets that the
dataset ships without documentation.

## 2. What the dynamic-SLAM literature actually does on Bonn

I checked how DG-SLAM (NeurIPS'24), RGD-SLAM (RAL'25), DynaSLAM, and the
3DGS-SLAM line (SplaTAM/MonoGS) report Bonn geometry:

- **DG-SLAM** reports ATE + rendering (PSNR/SSIM/LPIPS) on Bonn. Its quoted
  "8.06 cm accuracy / 43.7% completion" is on **TUM** dynamic sequences, where
  GT geometry is fused from GT depth + GT poses — *not* from the Bonn official
  ply. DG-SLAM does **not** report an F-score against the Bonn ply.
- **MonoEM-GS** states explicitly: "To obtain ground-truth scene geometry, we
  fuse the provided ground-truth depth images using the ground-truth poses."
  F1@0.2m. This is the **self-fused-GT** protocol, not the official ply.
- **SplaTAM / MonoGS** evaluate reconstruction on **Replica** (which ships a
  clean GT mesh in the same frame). On TUM/Bonn they report rendering + ATE,
  not F-score vs an external mesh.
- **DynaSLAM** reports ATE on Bonn, plus qualitative reconstruction figures —
  no F-score against the Bonn ply.

**Consensus: no top dynamic-SLAM paper reports F@5cm against
`rgbd_bonn_groundtruth_1mm_section.ply`.** Either they (i) report only
ATE + rendering on Bonn, or (ii) self-fuse a GT point cloud from GT depth +
GT poses (MonoEM-GS style) and report F1 against *that*. Nobody aligns to the
official ply via a static formula. So option (a) — "report ~2% with an
alignment caveat" — would be a **non-standard, indefensible number** that no
reviewer has seen before and that you cannot benchmark against any prior work.

## 3. Why each option fails or holds

**(a) Report absolute F@5cm ~2% with caveat — REJECT.**
A 2% F@5cm with "alignment is off by 1.14 m" is a self-immolating number. A
reviewer reads "their reconstruction is 2% accurate" and rejects; the caveat
does not survive skim-reading. It is also non-comparable to every prior paper
(none use this ply this way). Net: pure downside.

**(b) Report only prune-vs-deferred directional F@5cm — REJECT.**
codex is right that this is contaminated. F@5cm is a **hard-threshold,
nonlinear** metric. With a 1.14 m systematic offset, the ~2% you measure is
*accidental overlap* — the thin sliver of the rec that happens to land within
5 cm of GT by chance. A 0.4 pp prune→deferred delta (1.9%→2.3%) is driven by
which stray surfaces happen to graze the threshold, not by any real
geometry-quality difference. Reporting it as a "directional win" is
scientifically dishonest given what you now know. It also fails the
"absolute number must be sane" sanity check a reviewer will apply.

**(c) Drop F@5cm, lead with vac_depth / vac_psnr + compactness — ACCEPT.**
Your vac_depth (17 cm, sane) and vac_psnr (~23 dB, sane) are **image-space**
metrics computed in the camera frame, so they are immune to the world-frame
mismatch. Compactness G_def/G_prune is a ratio of your own maps, also
frame-invariant. This trio is internally consistent, defensible, and matches
how the field actually evaluates Bonn (rendering + ATE, not F-vs-ply).

**(d) The option you asked about — is there a known Bonn convention?**
**Yes, and it is option (c)-compatible.** The convention in the dynamic-SLAM
literature is: *do not use the official ply for F-score*. Two legitimate
paths exist if you ever want a geometry number on Bonn:
  1. **Self-fuse a GT cloud from GT depth + GT poses** (MonoEM-GS protocol),
     then F@5cm against that. This is frame-consistent by construction. It is
     a week of work and needs the GT depth intrinsics aligned exactly; not a
     pre-deadline move.
  2. **Report Bonn reconstruction qualitatively** (figures) + quantitatively
     only via ATE + rendering. This is what DG-SLAM/DynaSLAM do.

For MMM 2027, path 2 = your option (c). Path 1 is a future-revision upgrade,
not a blocker.

## 4. Recommended paper text (one paragraph, drop-in)

> We evaluate reconstruction quality on Bonn via **view-consistent depth L1
> (vac_depth) and PSNR (vac_psnr)** computed in the camera frame, and via the
> **map compactness ratio G_prune/G_def** between arms. We do not report an
> F-score against the Bonn official ground-truth mesh
> (`rgbd_bonn_groundtruth_1mm_section.ply`): that mesh is exported in a world
> frame that does not close under any rigid transform with the pose-trajectory
> frame our SLAM initialises from (best-fit Umeyama residual 1.14 m, tight
> spread — systematic, not noise), and no prior dynamic-SLAM work (DG-SLAM,
> DynaSLAM, SplaTAM) reports F-score against this asset. Following prior work,
> Bonn geometry is reported qualitatively; quantitative geometry F-scores are
> reported on TUM, where ground truth is fused from GT depth + GT poses in a
> frame-consistent manner.

This is honest, it cites the field's actual practice, and it pre-empts the
"why no F-score on Bonn" reviewer question with a technical reason they can
verify.

## 5. One cleanup action

The `bonn_alignment_formula` field in
`utils/geometry_metrics.py:442` and the `T_BONN_MARKER` constant are now
**known-broken** (they assume a single rigid transform that does not exist).
Do not delete the code (the TUM path and the pipeline are fine), but the
Bonn F@5cm numbers it emits should be treated as **diagnostic-only, not
reportable**. Suggest adding a one-line comment at `geometry_metrics.py:435`
(`elif dataset_type == "bonn":`) noting the frame mismatch so the next person
does not re-trust these numbers. I have NOT made this edit — flagging for
your approval per the default-review-only stance.

---

**Bottom line:** (c). The F@5cm ~2% is a frame-convention artifact, not a
method failure, and the field already sidesteps it. Lead with the sane,
frame-invariant, prior-work-comparable trio: vac_depth, vac_psnr, compactness.
