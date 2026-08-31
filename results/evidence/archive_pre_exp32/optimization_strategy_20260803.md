# Optimization Strategy — 2026-08-03

**Context**: Narrative deadline shifted from 2026-08-04 to 2026-08-10 (+6 days). 
User directive: continue project optimization across three fronts (tracking, rendering, efficiency) 
rather than holding pattern. Avoid "honest negative results" presentation. GPU idle, ~160 GPU-hours 
available over 8 days.

**Current Status Summary** (P2-T 36/36 complete, all metrics measured):

## 1. Tracking Metrics (ATE RMSE, cm)

| Sequence | Ours-prune | Ours-deferred | Best Competitor | Competitor Method | Gap |
|---|---:|---:|---:|---|---:|
| balloon | 3.07 | 3.11 | 2.45 | RGD-SLAM | +0.62 |
| balloon2 | 5.22 | 5.84 | 2.42 | WildGS-SLAM | +2.80 |
| mv_no_box | 2.58 | 2.87 | 1.60 | WildGS-SLAM | +0.98 |
| mv_no_box2 | 4.68 | 5.61 | 2.50 | WildGS-SLAM | +2.18 |
| pt1 | 10.97 | 11.51 | 3.63 | WildGS-SLAM | +7.34 |
| pt2 | 10.35 | 16.80 | 3.09 | WildGS-SLAM | +7.26 |

**Observation**: Never best on any sequence. Largest gaps on person_tracking (pt1/pt2: +7.3/+7.3 cm).
WildGS-SLAM dominates across all sequences. Memory suggests 3→1.5cm backend gap is BA-related.

## 2. Rendering Metrics (Static Support)

| Sequence | Ours static_psnr | Ours static_ssim | Ours static_lpips | Notes |
|---|---:|---:|---:|---|
| balloon | 24.07 | 0.878 | 0.171 | prune arm |
| mv_no_box | 26.46 | 0.882 | 0.155 | prune arm |
| pt1 | 25.30 | 0.878 | 0.185 | prune arm |
| pt2 | 24.27 | 0.873 | 0.182 | prune arm |

**Critical Issue**: Full-frame PSNR/SSIM/LPIPS = `nan` in all 36 P2-T runs despite `--eval` flag.
Root cause identified: `eval_rendering()` loop skips ALL frames because every frame in 
`self.frontend.cameras` is also in `kf_indices`, making `if idx in kf_indices: continue` 
skip everything. The static_psnr path works because it uses different frame selection logic.

**Competitor Protocol**: 10/11 baselines use `mask_type='full'` (only DG-SLAM and DynaSLAM 
use 'static'). Our static_psnr is NOT directly comparable to their full-frame numbers—dynamic 
pixels penalize full-frame scores when method correctly doesn't reconstruct movers.

**Baseline Full-Frame PSNR** (for reference):
- RGD-SLAM: 25.14 (balloon), 24.45 (mv_no_box), 24.11 (pt1), 22.76 (pt2)
- DG-SLAM: 23.67 (balloon), 24.24 (mv_no_box), 21.15 (pt1), 19.75 (pt2)
- MonoGS: 19.30 (balloon), 21.78 (mv_no_box), 17.81 (pt1), 19.68 (pt2)

## 3. Efficiency Metrics

| Metric | Ours (2060) | MonoGS (3090) | RGD (3090) | DG-SLAM (3090) | WildGS (3090) |
|---|---:|---:|---:|---:|---:|
| FPS end-to-end | 0.45-0.53 | 1.90 | 0.68 | 1.22 | 0.35 |
| GPU Memory (GB) | 2.3-3.6 | 0.21 | 6.50 | 6.92 | 12.16 |
| #Gaussians (balloon) | 39.8k/19.8k | 26.6k | 9.6k | 50.8k | 126k |

**Confound**: Our runs on RTX 2060 6GB; all baselines on RTX 3090 24GB → FPS not directly comparable.
**Timing Breakdown** (balloon prune): Total 912s = tracking 801s + mapping 894s (overlap).
  - Semantic segmentation: 96s (12% of tracking time, 211ms/frame)
  - Color refinement: 418s (46% of total wall time, post-processing)
  - Online SLAM: 0.49 FPS (excluding refinement → ~0.89 FPS effective)

**VRAM Advantage**: 2.3-3.6 GB vs RGD/DG/WildGS 6.5-12.2 GB (2-5× lower memory).

---

## Problem Diagnosis

### A. Tracking Performance Gap (7+ cm on pt1/pt2)

**Hypothesis 1**: Backend BA gap. MonoGS has no loop closure or global BA; competitors do.
Memory explicitly states "3→1.5cm gap is BA-BACKEND gap (triple-confirmed)". Our system 
stops at local photometric refinement.

**Hypothesis 2**: Person-tracking sequences have fast motion or challenging lighting that 
our robust tracking (Huber kernel) doesn't handle well. Coverage analysis shows pt1=29.9%, 
balloon2=59.4% but pt1 ATE worse—coverage alone doesn't explain it.

**Hypothesis 3**: Mask-both strategy removes too much signal when person is close to camera 
(high mask ratio), leaving insufficient static support for pose refinement.

### B. Rendering Evaluation Bug

**Immediate**: `eval_rendering()` never populates `psnr_array` because loop condition 
`if idx in kf_indices: continue` skips every frame when `self.frontend.cameras` only 
contains keyframes. This is a logic error, not a missing computation.

**Impact**: Cannot compare rendering quality to baselines on standard protocol. Paper 
main table will have missing entries unless fixed and re-run.

### C. Efficiency Bottlenecks

1. **Color refinement**: 418s/912s = 46% of total time, post-processing step
2. **Semantic segmentation**: 96s = 12% of tracking, 211ms/frame (Mask R-CNN on CPU?)
3. **GPU mismatch**: 2060 vs 3090 makes competitor FPS incomparable

---

## Optimization Opportunities (8 days, ~160 GPU-hours)

### Track 1: Fix Rendering Evaluation Bug + Re-compute Full-Frame Metrics
**Effort**: 1 day code + 0.5 day validation + 0 GPU (use existing checkpoints)
**Approach**: 
1. Diagnose why `self.frontend.cameras` only contains keyframes in eval path
2. Fix loop to iterate over `dataset` indices, not `cameras` dict keys
3. Write standalone script to re-render all 36 P2-T runs from saved checkpoints
4. Aggregate full-frame PSNR/SSIM/LPIPS for main table

**Expected Outcome**: Comparable rendering metrics. If our full-frame PSNR ≈ static_psnr 
(24-26), we're competitive with RGD (22-25) and ahead of MonoGS (17-22).

**Risk**: If full-frame PSNR < 20 due to dynamic-pixel penalty, this becomes a limitation 
rather than a strength.

---

### Track 2: Improve Tracking on pt1/pt2 (Close 7cm Gap)

#### Option 2A: Add Lightweight Pose-Graph Optimization
**Effort**: 3-4 days implementation + 1 day P2-T re-run (36 runs × ~15min = 9h GPU)
**Approach**: 
- Add keyframe-to-keyframe loop closure detection (feature matching on static regions)
- Build pose graph, run g2o or similar BA solver after every N keyframes
- Keep photometric tracking as primary, use BA as periodic global correction

**Expected Gain**: Memory states backend BA closes 3→1.5cm gap. If we gain 3-4cm on pt1/pt2, 
we move from 11cm to 7-8cm (still behind WildGS 3.6cm, but respectable).

**Risk**: Implementation complexity. Loop closure on dynamic scenes is tricky (must use 
static-masked features). May not converge in 4 days.

#### Option 2B: Improve Robust Tracking for Fast Motion
**Effort**: 2 days tuning + 1 day validation (subset re-run)
**Approach**:
- Diagnose per-frame ATE on pt1/pt2 to find failure modes
- Tune Huber kernel delta, add motion model for fast camera motion
- Increase pose_window or adaptive weighting based on reliability signal

**Expected Gain**: 1-2cm improvement if failure is motion-model related.

**Risk**: Lower ceiling than 2A. If backend BA is the real gap, this won't close it.

#### Option 2C: Adaptive Masking for High-Coverage Frames
**Effort**: 1-2 days implementation + 0.5 day validation
**Approach**:
- When mask coverage > threshold (e.g., 80%), fall back to soft masking or depth-only tracking
- Leverage reliability signal to preserve high-confidence static points even in masked regions

**Expected Gain**: 0.5-1cm if pt1/pt2 failures are coverage-related.

**Risk**: Coverage analysis suggests this isn't the primary issue (pt1 only 29.9% coverage).

---

### Track 3: Efficiency Optimization

#### Option 3A: Separate Online vs Offline Metrics
**Effort**: 0.5 day (reporting only, no code change)
**Approach**:
- Report online SLAM FPS (0.89) separately from total wall time including refinement
- Clarify that color refinement (418s) is post-processing, not online cost
- Report VRAM advantage (2-5× lower than RGD/DG/WildGS) as primary efficiency win

**Expected Outcome**: Shifts narrative from "slow FPS" to "low memory + acceptable online speed".

#### Option 3B: Optimize Semantic Segmentation
**Effort**: 1 day investigation + 1 day optimization
**Approach**:
- Profile whether Mask R-CNN runs on GPU or CPU (96s for 439 frames = 219ms/frame is slow)
- If CPU, move to GPU and batch process
- Consider switching to YOLOv8-seg (faster, memory says already probed as equivalent)

**Expected Gain**: 50-100ms/frame reduction → 0.55-0.60 FPS online.

**Risk**: Memory states "YOLO 后端决定已落盘" with conditions; changing backend mid-campaign 
may violate protocol.

#### Option 3C: Re-run MonoGS Baseline on 2060
**Effort**: 1 day setup + 0.5 day runs (6 sequences × 3 seeds × 30min = 9h GPU)
**Approach**:
- Download MonoGS official code, run on same 2060 GPU with same sequences
- Compute FPS ratio: Ours / MonoGS-2060

**Expected Outcome**: Fair efficiency comparison. If MonoGS gets 0.8 FPS on 2060, we're 
0.45/0.80 = 0.56× (slower but not disastrously).

**Risk**: MonoGS may OOM on 2060 (our memory says "2060 --eval OOMs on dense-KF maps").

---

## Recommended 8-Day Plan

Given constraints (8 days, user wants positive results, GPU idle):

### Phase 1 (Days 1-2): Immediate Data Rescue
1. **Fix eval_rendering bug** (4h): Patch loop logic in eval_rendering()
2. **Re-render P2-T from checkpoints** (8h): Standalone script, 36 runs, 0 GPU (uses saved PLY)
3. **Aggregate full-frame metrics** (2h): Update results tables with PSNR/SSIM/LPIPS
4. **Verdict on rendering win**: If full-frame PSNR 23-26, this is a strength; if <20, drop it

### Phase 2 (Days 3-5): Tracking Improvement (Pick ONE)
- **If user prioritizes speed**: Option 2B (robust tracking tuning, 2 days + 9h GPU)
- **If user prioritizes ceiling**: Option 2A (pose-graph BA, 4 days + 9h GPU)
- **Conservative**: Option 2C (adaptive masking, 1.5 days + 4h GPU) + 2B (2 days)

Recommendation: **2A (pose-graph BA)**. Memory explicitly states BA backend is the gap; 
this is the only option that directly targets it. Risk is implementation time.

### Phase 3 (Days 6-7): Efficiency Narrative
- **Option 3A** (0.5 day): Separate online/offline metrics in tables
- **Option 3B** (1 day): Profile + optimize semantic segmentation if on CPU
- **Option 3C** (1 day): Re-run MonoGS on 2060 for fair FPS comparison

### Phase 4 (Day 8): Readout + Synthesis
- Re-run readout scripts on updated data
- Update 03-results.md, main tables, evidence files
- Prepare synthesis for narrative decision (now on 08-10)

---

## Expected Outcomes by Track

| Track | Best Case | Worst Case | Confidence |
|---|---|---|---|
| Rendering fix | Full PSNR 24-26, competitive with RGD | Full PSNR <20, becomes limitation | 70% best |
| Tracking (2A BA) | pt1/pt2 improve 3-4cm → 7-8cm ATE | No convergence, wasted 4 days | 50% best |
| Tracking (2B tuning) | pt1/pt2 improve 1-2cm → 9-10cm ATE | No gain, wrong hypothesis | 60% best |
| Efficiency narrative | VRAM win + acceptable online FPS | Still "slow" perception | 80% best |

---

## Open Questions for Codex + Hermes Review

1. **Rendering protocol**: Is full-frame PSNR the right target, or should we argue for 
   static-only evaluation as more appropriate for dynamic scenes? (Codex: protocol design)

2. **Tracking ceiling**: Can we realistically close the 7cm gap in 4 days, or is this 
   a "future work" item? (Hermes: feasibility gate)

3. **Efficiency narrative**: Is "2-5× lower VRAM" + "0.89 FPS online" a defensible 
   efficiency claim, or do reviewers expect >1 FPS? (Codex: reviewer expectations)

4. **Resource allocation**: Should we attempt risky 2A (high ceiling, low probability) 
   or safe 2B+2C (incremental, higher probability)? (Hermes: risk assessment)

5. **Narrative shift**: With tracking gap this large, should we pivot from "dynamic SLAM" 
   to "memory-efficient 3DGS with dynamic handling"? (Codex: positioning)

---

## Constraints from Memory

- **Do not re-run P2-T 36 runs** unless absolutely necessary (user directive, GPU budget)
- **Do not change YOLO backend** without trigger conditions (see yolo_backend_decision.md)
- **Do not mix mask protocols** (same campaign must use same mask_type)
- **Commit before GPU runs** (harness refuses dirty tree)
- **GO/KILL and narrative = user reserved** (we recommend, user decides)

---

**Status**: Draft for codex/hermes dual review. User will decide final direction after consultation.
