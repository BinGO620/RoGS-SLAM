# Optimization Strategy Synthesis — 2026-08-03

## Executive Summary

After investigation and partial consultation with codex (running) and hermes (timeout after key findings), I recommend a **staged hedge strategy** that guarantees progress while preserving option value for high-reward improvements.

**Immediate Plan (Days 1-3, Guaranteed ROI)**:
1. Fix rendering evaluation bug (4h) + extract full-frame PSNR from existing runs (8h)
2. If PSNR 23-26: rendering becomes a strength to lead with
3. If PSNR <20: reframe as "static-region quality" with full-frame as limitation

**Conditional Track (Days 4-6, High Upside if Viable)**:
4. Enable + validate DBA-lite on 1-2 sequences (pilot, 1 day)
5. If pilot shows >1cm improvement: launch full P2-T re-run with DBA enabled
6. If pilot fails: fall back to robust tracking tuning (Option B)

**Consolidation (Days 7-8)**:
7. Efficiency narrative + final readout
8. Synthesis for 08-10 narrative gate

---

## Critical Findings

### Finding 1: Rendering Data Exists But Contains NaN (Bug Confirmed)
**Evidence**:
```json
// results/runs/P2/P2-T/balloon_prune_seed0/.../psnr/after_opt/final_result.json
{
    "mean_psnr": NaN,
    "mean_ssim": NaN,
    "mean_lpips": NaN,
    "mean_depth_l1_cm": null
}
```

**Root Cause** (from code inspection):
- `eval_rendering()` at utils/eval_utils.py:437-556 iterates `range(0, end_idx, interval)`
- Skips frames with `if idx in kf_indices: continue`
- `self.frontend.cameras` passed to eval contains ONLY keyframes
- Result: every idx is in kf_indices → psnr_array stays empty → mean = NaN

**Fix Complexity**: LOW (4-8 hours)
- Change loop to iterate over dataset indices, not cameras.keys()
- OR use `eval_final_mapping_raw()` which has different frame selection logic
- Re-extract from existing 36 runs (no GPU, just re-process saved checkpoints)

**Expected Outcome**:
- Best case: Full-frame PSNR 23-26 → competitive with RGD (22-25), ahead of MonoGS (17-22)
- Worst case: Full-frame PSNR <20 → becomes limitation, but we know the number

**Risk**: 10% (bug is identified, fix is straightforward)

---

### Finding 2: DBA-Lite Module Exists But Is Disabled
**Evidence**:
- `utils/dba_lite.py` exists (31KB, dated 2026-07-16)
- Has three modes: `diagnostic` (default-off), `oracle` (falsifier), `v0` (solver)
- Config section `DBALite` is **absent** from `method_combined_maskboth_prune.yaml`
- No mentions in `results/registry.csv` or `results/evidence/` → never tested in any campaign

**Code Structure**:
```python
def dba_lite_diagnostic_enabled(config):
    return bool(get_dba_lite_config(config).get("diagnostic", False))

def dba_lite_enabled(config):
    # Actual BA solver, disabled by default
```

**Implication**: Option A is NOT "implement pose-graph BA from scratch" (4 days, 50% success).
It is "enable existing DBA-lite code + tune parameters" (2 days, 70% success if code works).

**Critical Unknown**: Why was DBA-lite written but never tested?
- Possibility 1: Never finished validation, parked as future work
- Possibility 2: Tested informally, found broken, disabled
- Possibility 3: Written speculatively, no time to integrate

**De-risking Strategy**: Pilot on 1 sequence (balloon, 1 seed) with DBA enabled (6h + 30min GPU).
- If ATE improves >1cm: full launch viable
- If crashes/diverges: abort Option A, pivot to Option B

---

### Finding 3: Tracking Gap Is Structural, Not Noise
**Data** (from P2-T 36/36 complete):

| Sequence | Ours-prune ATE | Best Competitor | Gap | Gap Ratio |
|---|---:|---:|---:|---:|
| balloon | 3.07 | 2.45 (RGD) | +0.62 | 1.25× |
| mv_no_box | 2.58 | 1.60 (WildGS) | +0.98 | 1.61× |
| pt1 | 10.97 | 3.63 (WildGS) | +7.34 | **3.02×** |
| pt2 | 10.35 | 3.09 (WildGS) | +7.26 | **3.35×** |

**Pattern**: Gaps on pt1/pt2 are 3× worse, not just 20-30% behind. This suggests **structural limitation**
(lack of backend BA, confirmed by memory "3→1.5cm backend gap triple-confirmed").

**Realistic Improvement Ceiling**:
- Best case (DBA-lite works): +3-4cm on pt1/pt2 → 7-8cm ATE (still 2× behind, but "respectable")
- Conservative (tuning only): +1-2cm → 9-10cm ATE (incremental)
- Worst case (no intervention): 11cm ATE (current, "badly behind")

**Narrative Impact**:
- 11cm → 7cm: Moves from "badly behind" to "competitive but not SOTA" (viable for CCF-C)
- 11cm → 9cm: Marginal improvement, hard to defend as progress
- 11cm → 11cm: Must pivot positioning away from tracking as contribution

---

### Finding 4: Efficiency Narrative Is Salvageable
**Current Numbers** (2060 GPU, incomparable FPS to 3090 baselines):
- End-to-end FPS: 0.45-0.53 (slower than MonoGS 1.90, DG-SLAM 1.22)
- **But**: 46% of wall time is post-processing color refinement (418s / 912s total)
- Online SLAM FPS: ~0.89 (excluding refinement)
- VRAM: 2.3-3.6 GB vs RGD/DG/WildGS 6.5-12.2 GB (**2-5× lower**)
- Gaussian count: 19.8k-69.6k (competitive, lower than WildGS 126k)

**Reframing Strategy**:
1. Report online and offline metrics separately (Table: "Online FPS" vs "Total incl. refinement")
2. Lead with VRAM advantage: "2-5× lower memory enables deployment on consumer GPUs"
3. Note FPS incomparable due to hardware difference (ours 2060, baselines 3090)
4. Optional: Re-run MonoGS baseline on 2060 for fair ratio comparison (9h GPU)

**Defensibility**: 70% (reviewers may still perceive 0.45 FPS as "slow", but VRAM win is undeniable)

---

## Recommended 8-Day Execution Plan

### Phase 1: Guaranteed Progress (Days 1-2)
**Objective**: Fix rendering evaluation and establish baseline for comparison

**Tasks**:
1. **Day 1 Morning (4h)**: Fix eval_rendering bug
   - Diagnosis: Change loop in utils/eval_utils.py:454 to iterate dataset, not cameras
   - Write test script to validate fix on 1 run before batch processing
   - Commit fix to branch `fix/eval-rendering-bug`

2. **Day 1 Afternoon + Day 2 (12h)**: Re-extract full-frame PSNR from 36 P2-T runs
   - Script: Load saved Gaussian PLY from `point_cloud/final_after_opt/`
   - Re-render along estimated poses at eval_rendering_interval=5
   - Aggregate PSNR/SSIM/LPIPS for all 36 runs
   - Update results/evidence/p2t_readout_final.md with full-frame metrics

**Deliverable**: Full-frame PSNR/SSIM/LPIPS for main table, protocol-comparable to baselines

**Success Criteria**:
- ✅ Best case: PSNR 23-26 → rendering becomes headline strength
- ⚠️ Acceptable: PSNR 20-23 → "competitive" tier
- ❌ Worst case: PSNR <20 → reframe as static-only strength + full-frame limitation

**Risk**: 10% (fix is straightforward, data exists)

---

### Phase 2: DBA-Lite Pilot (Days 3-4)
**Objective**: Validate whether existing DBA-lite code is viable before committing to full re-run

**Day 3 Tasks**:
1. **Morning (2h)**: Code review of utils/dba_lite.py
   - Check v0 solver implementation completeness
   - Verify it uses masked edges (static-only features)
   - Review any TODO/FIXME comments for known issues

2. **Afternoon (4h)**: Single-sequence pilot
   - Add `DBALite: {enabled: true}` to balloon config
   - Run balloon prune seed0 with DBA enabled (~30min GPU)
   - Compare ATE: baseline 3.07cm vs DBA-enabled

**Day 4 Tasks**:
1. **Morning (3h)**: Expand pilot if Day 3 successful
   - Run pt1 prune seed0 with DBA (baseline 10.97cm, ~25min GPU)
   - If pt1 shows >2cm improvement: proceed to full launch
   
2. **Afternoon (4h)**: Decision gate
   - **If pilot shows >1cm improvement on either sequence**: Prepare full P2-T re-run configs
     - Create 12 new configs with DBA enabled (6 seq × 2 arms)
     - Update runner script for P2-T-DBA campaign
     - Commit apparatus, ready for Day 5 launch
   
   - **If pilot shows <1cm or crashes**: Abort DBA track, pivot to Option B
     - Spend Day 5-6 on robust tracking tuning instead
     - Lower ceiling (+1-2cm) but safer path

**Success Criteria**:
- ✅ Pilot ATE improvement >1cm: Launch full DBA re-run (Days 5-6)
- ⚠️ Pilot improvement 0.5-1cm: Marginal, user decides whether to pursue
- ❌ Pilot no improvement or crashes: Abort, pivot to Option B

**Risk**: 40% (code exists but never tested, may be incomplete/broken)

---

### Phase 3A: Full DBA Re-Run (Days 5-6, Conditional on Pilot Success)
**Prerequisites**: Pilot showed >1cm improvement

**Tasks**:
- **Day 5**: Launch P2-T-DBA campaign
  - 6 sequences × 2 arms × 3 seeds = 36 runs
  - Estimated time: 36 × 16min = 9.6h GPU (fits in overnight run)
  - Monitor first 6 runs (seed0 tranche), check for crashes

- **Day 6**: Readout + comparison
  - Run readout script on DBA campaign
  - Compare ATE: original P2-T vs DBA-enabled
  - If improvement holds across sequences: DBA becomes contribution
  - If improvement only on pilot sequences: report as sequence-dependent

**Expected Outcome**:
- Best case: pt1/pt2 drop 3-4cm → 7-8cm ATE, paper leads with tracking improvement
- Acceptable: pt1/pt2 drop 1-2cm → 9-10cm ATE, tracking becomes "competitive"
- Worst case: No improvement beyond pilot → pilot was noise, fall back to Phase 3B

**Risk**: 30% (pilot success doesn't guarantee generalization)

---

### Phase 3B: Robust Tracking Tuning (Days 5-6, Fallback if Pilot Fails)
**Trigger**: DBA pilot showed <1cm improvement or crashed

**Tasks**:
- **Day 5**: Diagnostic analysis
  - Plot per-frame ATE error over time on pt1/pt2
  - Identify failure modes: gradual drift vs sudden jump vs oscillation
  - Check correlation with camera motion, mask coverage, reliability signal

- **Day 6**: Targeted tuning
  - Tune Huber kernel delta (rgb_delta, depth_delta) based on failure mode
  - Increase pose_window if drift is issue (6 → 12 frames)
  - Adaptive weighting based on reliability signal
  - Run validation on pt1/pt2 seed0 (2 runs × 25min = 50min GPU)

**Expected Outcome**:
- Best case: +1-2cm improvement → pt1/pt2 at 9-10cm
- Worst case: No measurable gain → tracking limitation becomes stated constraint

**Risk**: 50% (tuning without root cause understanding often fails)

---

### Phase 4: Consolidation (Days 7-8)
**Day 7 Tasks**:
1. **Efficiency narrative** (4h)
   - Create two-column table: "Online SLAM" vs "Total (incl. post-processing)"
   - Write efficiency section emphasizing VRAM advantage
   - Optionally: Re-run MonoGS baseline on 2060 for fair FPS comparison (9h GPU, overnight)

2. **Update documentation** (4h)
   - Sync 03-results.md with new PSNR numbers
   - Update HANDOFF.md with final status
   - Update registry.csv if new campaign ran

**Day 8 Tasks**:
1. **Final readout** (3h)
   - Run all readout scripts on updated data
   - Generate comparison tables for main paper
   
2. **Synthesis for narrative gate** (4h)
   - Write 2-page summary: what improved, what didn't, what's the story
   - Provide 3 positioning options with pros/cons
   - User decides final narrative direction on 08-10

---

## Risk Matrix

| Option | Timeline | GPU Hours | Success Prob | Best Case Gain | Worst Case Loss |
|---|---|---:|---:|---|---|
| **C: Fix rendering** | Days 1-2 | 0h | 90% | PSNR 23-26 → new strength | PSNR <20 → known limitation |
| **A: DBA pilot** | Days 3-4 | 1h | 60% | Validates full re-run path | 2 days "wasted", still have fallback |
| **A: DBA full** | Days 5-6 | 10h | 50% | ATE 7-8cm → competitive | No gain, but tried |
| **B: Tuning** | Days 5-6 | 1h | 50% | ATE 9-10cm → incremental | No gain, limitation exposed |
| **Efficiency** | Day 7 | 0-9h | 80% | VRAM narrative established | Still "slow" perception |

**Expected Value Calculation** (rough):
- Path 1 (C only): 90% × "rendering fixed" = guaranteed minor win
- Path 2 (C + A pilot + A full): 90% × 60% × 50% × "tracking competitive" = 27% major win
- Path 3 (C + A pilot fail + B): 90% × 40% × 50% × "tracking incremental" = 18% minor win
- Path 4 (C + efficiency): 90% × 80% × "VRAM narrative" = 72% moderate win

**Recommendation**: Pursue C + A pilot + (A full OR B) + efficiency. This maximizes option value while 
guaranteeing at least rendering fix + efficiency narrative (72% moderate win floor, 27% major win ceiling).

---

## Decision Points for User

### Gate 1 (End of Day 2): Rendering PSNR Result
**Question**: What did full-frame PSNR come back as?
- If 23-26: Lead with rendering quality in narrative
- If 20-23: Rendering is "competitive" tier, not headline
- If <20: Rendering becomes limitation, pivot to efficiency/compactness narrative

### Gate 2 (End of Day 4): DBA Pilot Result
**Question**: Did DBA pilot show >1cm improvement?
- Yes + confident: Launch full P2-T-DBA re-run (Days 5-6)
- Yes + uncertain: Run 1 more sequence to confirm, then decide
- No: Abort DBA, pivot to Option B tuning (Days 5-6)

### Gate 3 (Day 8): Final Positioning
**Question**: Given all results, what's the paper positioning?
- Option A: "Memory-efficient dynamic 3DGS SLAM" (lead with VRAM, rendering quality)
- Option B: "Lifecycle-adaptive 3DGS mapping" (lead with compactness, deemphasize tracking)
- Option C: "Dynamic scene 3DGS with explicit handling" (balanced, competitive but not SOTA)

---

## Open Questions Requiring User Input

1. **Risk tolerance**: User said "avoid negative results" but also "push forward not spin wheels". 
   Is 50% chance of major tracking improvement (DBA) worth risking 4 days, or prefer 80% chance 
   of guaranteed progress (rendering + efficiency)?

2. **Venue expectations**: For MMM 2027 CCF-C, is "competitive but not SOTA on all metrics" 
   acceptable, or must we be best-in-class on ≥1 dimension?

3. **Narrative pivot**: If tracking stays at 10-11cm (3× behind), should we reframe contribution 
   away from "dynamic SLAM" toward "memory-efficient 3DGS mapping"?

4. **Resource allocation**: 8 days / 160 GPU-hours. If DBA pilot succeeds, do we have approval 
   to burn 10h GPU on full re-run, or should we conserve for other experiments?

---

## Appendix: Codex Consultation Status

Codex consultation (task kmg6kgk31) is still running after 2+ hours. When it completes, I will:
1. Compare codex recommendations against this synthesis
2. Update risk assessments based on codex's protocol/positioning advice
3. Write final consult_synthesis document with merged recommendations

Expected codex insights:
- Whether full-frame PSNR <20 is fatal flaw for CCF-C venue
- Whether "memory-efficient" positioning is defensible if tracking lags
- Whether 4-day BA implementation timeline is realistic (may differ from my "enable existing" finding)

---

**Status**: Synthesis complete, pending codex results and user decision on risk tolerance.
**Next Action**: Present this document to user, await direction on Gates 1-3.
