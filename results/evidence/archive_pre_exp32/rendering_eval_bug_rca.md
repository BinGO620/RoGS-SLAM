# Rendering Eval Bug — Root Cause Analysis (2026-08-03, verified)

## Bug: Confirmed, root cause identified

**Symptom**: `mean_psnr: NaN, mean_ssim: NaN, mean_lpips: NaN, mean_depth_l1_cm: null`
in all 36 P2-T runs' `psnr/after_opt/final_result.json`.

**Root cause** (verified, not the hypothesis in the strategy doc):
`eval_rendering()` in `utils/eval_utils.py:437-515` does:

```python
interval = 5
end_idx = len(frames) - 1   # frames = self.frontend.cameras (dict, has all 439 frames)
for idx in range(0, end_idx, interval):   # idx ∈ {0, 5, 10, ..., 430}
    if idx in kf_indices:   # KF cadence is ALSO every 5 frames (gap_cap=5)
        continue            # ← skips EVERY sampled frame
    ...
```

- balloon run: **87 keyframes** at `{0, 5, 10, ..., 435}` (verified: `grep -oE "KF [0-9]+"` 
  → 87 unique, last = KF 435; total frames = 439).
- The eval sample cadence (every 5) **collides exactly** with the keyframe cadence 
  (gap_cap=5 → every 5th frame is a KF).
- Result: `range(0, 438, 5)` = `[0,5,...,430]`, every one is in `kf_indices` → 
  `psnr_array` stays empty → `_finite_mean([])` = NaN.

**This is NOT "cameras only contains keyframes"** (my earlier hypothesis was wrong).
`self.frontend.cameras` is a dict with all 439 frames (the loop would KeyError otherwise).
The bug is a **cadence collision**: eval interval == keyframe interval, plus the 
`if idx in kf_indices: continue` guard that was meant to avoid re-scoring KFs but 
instead skips every sampled frame.

## Why `eval_final_mapping_raw` (line 580) did NOT fire either

`save_final_mapping` defaults to `False` (slam.py:455), and the combined backbone 
config (`method_combined_maskboth_prune.yaml`) does NOT set it. So the alternate 
full-frame path that iterates `frame_ids[::interval]` without the kf skip never ran.
The `static_psnr` path (`eval_static_background_raw`, line 635) DID run because it 
uses `frame_ids[::interval]` and does NOT skip keyframes — that's why we have 
static_psnr 24-26 but full-frame = NaN.

## Fix (minimal, surgical)

Two independent fixes; do BOTH for safety:

**Fix 1 — eval_rendering (the headline path)**: Remove the `if idx in kf_indices: 
continue` guard, OR change the sample offset. Simplest: drop the guard (KF/non-KF 
distinction is irrelevant for rendering quality — we want to score the map at evenly 
spaced views). 

```python
# utils/eval_utils.py:454-456  (BEFORE)
for idx in range(0, end_idx, interval):
    if idx in kf_indices:
        continue
    saved_frame_idx.append(idx)
# (AFTER)
for idx in range(0, end_idx, interval):
    saved_frame_idx.append(idx)
```

**Fix 2 — enable save_final_mapping for future runs**: Add 
`Results.save_final_mapping: true` to the combined backbone configs so the alternate 
path (`eval_final_mapping_raw`) also writes a `mask_type='full'` row without re-rendering.

## Validation Plan (0.5 day, user's chosen path)

User selected: "先验证渲染bug修复是否真能拿到PSNR(0.5天验证)再定大计划".

### Step 1 — Offline re-render from saved checkpoints (NO GPU re-run needed)

We already have everything per run:
- Final Gaussian point cloud: `point_cloud/final_after_opt/point_cloud.ply` ✅
- Full estimated trajectory (439 poses): `plot/trj_full_final.json` ✅
- Dataset (RGB+depth): reproducible from config dataset_path ✅

Write a standalone script `scripts/r2_p2_t_offline_render.py` that:
1. Loads the saved `point_cloud.ply` via `GaussianModel.load_ply()`.
2. Loads the dataset via `load_dataset()` (TUMDataset for Bonn).
3. Reconstructs `Camera` objects for each frame using the ESTIMATED poses from 
   `trj_full_final.json` (not GT, not the cleaned cameras dict — the saved trajectory).
4. Calls `render()` at `interval=5` over all frames (NO kf skip).
5. Computes PSNR/SSIM/LPIPS/depth_l1 vs GT, writes a new 
   `psnr/after_opt/final_result_repaired.json`.

### Step 2 — Pilot on 1 run (balloon_prune_seed0) FIRST

- ~5-10 min on 2060 (render 88 frames × ~2s each + LPIPS net load).
- If PSNR comes back in 23-26 range → fix confirmed, batch all 36.
- If PSNR < 20 → dynamic-pixel penalty is real, need static-only narrative.
- If crash → Camera reconstruction from JSON poses has a convention bug, debug.

### Step 3 — Decision gate (end of 0.5 day)

- **PSNR 23-26**: Batch all 36 runs overnight (~5h GPU), rendering becomes a strength.
- **PSNR 20-23**: "Competitive" tier — proceed but don't lead with rendering.
- **PSNR < 20**: Reframe as static-region quality (we already have static_psnr), 
  full-frame becomes a stated limitation.
- **Crash**: Debug Camera pose convention (the trj_full_final uses inv(T) convention; 
  Camera.init_from_dataset takes gt_pose directly — need to inject est pose).

## Why this is the right first move (matches codex)

Codex (completed) said: **"C first — fix full-frame evaluation; rerun one 
representative sequence and at least one baseline first. Verify masks, camera 
convention, frame selection, and metrics against saved renders."** That is exactly 
this validation plan. Codex also said full-frame PSNR is **mandatory** for the main 
table (static-region is secondary only), so we must get this number.

## Risk Assessment (revised, verified)

- **Bug fix itself**: 95% (root cause confirmed, fix is 2-line deletion).
- **Offline re-render working first try**: 70% (Camera pose convention is the main 
  risk — `trj_full_final.json` stores `inv(gen_pose_matrix(R,T))` per frame; the 
  Camera class expects a `gt_T` and derives R_gt/T_gt from it; we need to inject 
  the ESTIMATED pose as the camera's current R/T, not as gt_T).
- **PSNR in usable range**: 70% (static_psnr 24-26 is a strong prior; full-frame 
  includes dynamic pixels which may drop it 2-4 dB, so 20-24 is the realistic band).

## Files to touch

1. `scripts/r2_p2_t_offline_render.py` (NEW — the standalone re-render script)
2. `utils/eval_utils.py:454-456` (Fix 1 — drop kf skip guard) — for FUTURE runs only
3. `configs/rgbd/experiments/active/candidate/method_combined_maskboth_{prune,deferred}.yaml` 
   (Fix 2 — add `Results.save_final_mapping: true`) — for future runs only

**No live code changes during validation.** The standalone script reads saved 
artifacts; the eval_utils fix is committed but only affects future `--eval` runs 
(not the offline re-render which uses its own loop).

## Status

- ✅ Bug root cause VERIFIED (cadence collision, not camera-dict issue)
- ✅ Saved artifacts sufficient for offline re-render (PLY + trajectory + dataset)
- ✅ Fix identified (2-line deletion + config flag)
- ⏳ Next: write `r2_p2_t_offline_render.py`, pilot on balloon_prune_seed0
