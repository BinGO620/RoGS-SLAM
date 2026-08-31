# Consultation Brief — Optimization Strategy (2026-08-03)

## Context
Narrative deadline shifted from 08-04 to 08-10 (+6 days). User directive: continue optimization 
across tracking/rendering/efficiency rather than holding pattern. "不喜欢诚实负结果，相信审稿人也不会喜欢。"
GPU idle, ~160 GPU-hours available.

## Current Performance vs SOTA

**Tracking (ATE cm)**: Never best on any sequence. Worst gaps: pt1 10.97 vs 3.63 (WildGS), 
pt2 10.35 vs 3.09 (+7.3cm). Memory states "3→1.5cm backend gap is BA" (triple-confirmed).

**Rendering**: Full-frame PSNR/SSIM/LPIPS = `nan` in all 36 P2-T runs due to eval_rendering() 
bug (loop skips all frames). Static_psnr 24-26 exists but isn't protocol-comparable (10/11 
baselines use full-frame). Must fix + re-compute.

**Efficiency**: 0.45 FPS end-to-end (2060 GPU), but 46% is post-processing refinement → 
0.89 FPS online. VRAM 2.3-3.6 GB vs RGD/DG/WildGS 6.5-12.2 GB (2-5× advantage). FPS 
incomparable: our 2060 vs their 3090.

## Proposed 8-Day Plan

**Phase 1 (Days 1-2)**: Fix rendering eval bug + re-render 36 runs from checkpoints → 
full-frame PSNR/SSIM/LPIPS for main table.

**Phase 2 (Days 3-5)**: Tracking improvement—pick one:
- **Option A**: Add pose-graph BA (keyframe loop closure + g2o). Targets stated backend gap. 
  Risky (4 days implementation), high ceiling (could gain 3-4cm).
- **Option B**: Tune robust tracking (Huber params, motion model, reliability weighting). 
  Safer (2 days), lower ceiling (1-2cm gain).
- **Option C**: Adaptive masking for high-coverage frames. Conservative (1.5 days), 0.5-1cm gain.

**Phase 3 (Days 6-7)**: Efficiency narrative—separate online/offline metrics, profile semantic 
segmentation, optionally re-run MonoGS baseline on 2060 for fair FPS comparison.

**Phase 4 (Day 8)**: Readout + synthesis for 08-10 narrative gate.

## Questions for Review

### For Codex (protocol + positioning):
1. **Rendering protocol**: Should we argue for static-only evaluation as more appropriate for 
   dynamic scenes, or is full-frame PSNR mandatory for acceptance? If full-frame <20 due to 
   dynamic-pixel penalty, is that a fatal flaw?

2. **Efficiency narrative**: Is "2-5× lower VRAM + 0.89 FPS online" defensible as an efficiency 
   win when end-to-end is 0.45 FPS? Do reviewers accept online/offline split, or expect >1 FPS total?

3. **Positioning**: With 7cm tracking gap, should we pivot from "dynamic SLAM" to "memory-efficient 
   3DGS mapping with dynamic handling"? Where does compactness fit (deferred 0.50-0.79× prune 
   on 3/6 sequences)?

4. **Tracking Option A feasibility**: Is pose-graph BA on dynamic scenes (static-masked features, 
   no global point cloud) implementable in 4 days? What are the failure modes?

5. **Reviewer expectations**: For MMM 2027 (CCF-C), is "competitive but not SOTA tracking + strong 
   rendering + low memory" sufficient, or is best-in-class on ≥1 metric required?

### For Hermes (risk + feasibility):
1. **Risk assessment**: Option A (BA, 4 days, 50% success) vs Option B+C (tuning, 3.5 days, 
   70% success, lower ceiling). Which betting strategy under user's "avoid negative results" directive?

2. **Rendering bug impact**: If full-frame PSNR comes back poor (<20), can we salvage with 
   static-only narrative, or is this campaign unsalvageable for rendering claims?

3. **Scope creep gate**: User shifted deadline +6 days. Is this license to attempt large changes 
   (Option A), or should we consolidate existing results + incremental polish?

4. **Resource allocation**: 8 days / 160 GPU-h. Option A burns 4 days + 9h GPU with 50% success 
   probability. If it fails on day 5, insufficient time for Plan B. Should we run Options B+C in 
   parallel as hedge?

5. **Tracking gap perception**: 10.97 vs 3.63 cm is 3× worse on pt1. Can any 4-day intervention 
   make this "respectable," or is this a structural limitation requiring different sequences / 
   reframing the contribution?

## Constraints from Project Memory
- Do not re-run P2-T 36 runs (user directive + GPU budget)
- Do not change mask backend without trigger conditions (yolo_backend_decision.md)
- Commit before GPU runs (harness gate)
- GO/KILL + narrative = user reserved (we recommend only)
- Compactness non-universal (pt2 反向 1.069×, hardcoded纪律⑨)

## Deliverable
Two independent reviews (codex + hermes) → synthesis with recommended direction + risk/reward 
table → user decision.
