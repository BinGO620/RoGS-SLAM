# Hermes Consultation Output (Partial) — 2026-08-03

**Status**: Hermes consultation timed out after 2min but made key discoveries before interruption.

## Key Findings from Hermes Investigation

### 1. DBA-lite Infrastructure Already Exists
**Location**: `utils/dba_lite.py` (lines 530-829 scanned)

**Impact on Option A Risk Assessment**:
- Original estimate: "4 days implementation + 50% success probability"
- Revised: Infrastructure exists, not greenfield. Risk profile changes from "implement from scratch" 
  to "enable + tune existing module"
- **Critical question**: Why was DBA-lite not enabled in P2-T runs? Is it disabled by default, 
  or did it fail validation?

**Action Items**:
1. Check DBALite config in `method_combined_maskboth_prune.yaml` 
2. Search for any campaign that tested DBA-lite (grep registry.csv, evidence/)
3. If never tested: Option A becomes "enable existing code" (2 days) not "implement BA" (4 days)
4. If tested-and-disabled: Must understand failure mode before attempting

### 2. Rendering Bug Confirmed
Hermes verified the eval_rendering bug exists and located the code paths:
- `eval_utils.py L437-556`: Loop skips when `idx in kf_indices`
- `slam.py L380-539`: Calls eval_rendering with `self.frontend.cameras`
- **Root cause hypothesis**: `self.frontend.cameras` dict only contains keyframes, so every 
  index in range(0, end_idx, interval) is in kf_indices → loop body never executes

**Salvage Path**:
- `eval_final_mapping_raw()` at L575-694 may be the working alternative
- Check if P2-T used `save_final_mapping=True` and has this data already

### 3. Config Discovery
Hermes found `method_combined_maskboth_prune.yaml` and was about to read it when timeout hit.
This is the exact config used for P2-T runs. Need to check:
- Is `DBALite.enabled` present and set to false?
- Is `Results.save_final_mapping` set to true (would give us rendering data)?

## Interrupted Analysis Path
Hermes was building toward:
1. Verify rendering bug claim by checking P2-T run console logs
2. Check if DBA-lite was ever tested (registry search)
3. Read combined backbone config to see current DBA-lite settings
4. Assess whether Option A is "enable existing" vs "implement new"

## Revised Risk Assessment (Preliminary)

**Option A — Revised**:
- **If DBA-lite exists and was never tested**: Effort drops to 2 days (enable + tune + validate) 
  instead of 4 days. Success probability rises to 70% (existing code, just needs config).
- **If DBA-lite exists but was disabled after failure**: Must diagnose failure first. Original 
  4-day estimate holds, success probability drops to 30% (known broken).
- **Critical gate**: Check `results/evidence/` for any dba_lite mention and registry.csv for 
  dba_lite configs.

**Option C — Confirmed High Priority**:
- Hermes verified the bug exists and is fixable
- Rendering evaluation likely already ran via alternative path (`save_final_mapping`)
- May be able to extract full-frame PSNR from existing data without re-render

## Immediate Actions (Before Full Plan)

1. **Check DBA-lite status**:
   ```bash
   grep -r "DBALite\|dba_lite" configs/rgbd/experiments/active/ results/evidence/ results/registry.csv
   ```

2. **Check if rendering data exists**:
   ```bash
   find results/runs/P2/P2-T -name "final_result.json" -o -name "*mapping*.json" | head -5
   ```

3. **Read combined config**:
   ```bash
   grep -A5 "DBALite:\|save_final_mapping:" configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml
   ```

## Recommendation Pending Full Data

**Likely optimal path** (contingent on checks above):
1. **Days 1-2**: Fix rendering eval bug OR extract from existing data (Option C, 90% success)
2. **Day 3**: Check DBA-lite status and run pilot on 1 sequence if code looks viable
3. **Days 4-5**: If DBA-lite pilot works, enable in full P2-T re-run; else fall back to Option B
4. **Days 6-7**: Efficiency narrative + any remaining tuning
5. **Day 8**: Readout + synthesis

**Key insight**: Hermes discovery of existing DBA-lite code changes the entire risk calculus. 
Must verify status before committing to plan.

---

**Next Step**: Complete the three immediate action checks, then synthesize with codex results 
(still running, task kmg6kgk31).
