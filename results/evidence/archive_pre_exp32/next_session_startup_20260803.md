# Next-session startup prompt (2026-08-03, written mid mv_no_box RT spike)

## Where things stand
- Narrative deadline: **08-10** (shifted from 08-04). Continue optimizing, no honest-negative framing.
- GPU: RTX 2060 (paper metrics must re-run on 3090, batch rendering deferred).
- **P2-RT spike IN PROGRESS** (scripts/r2_p2_rt_spike.py --phase run, PID in results/runs/P2/P2-RT-SPIKE/):
  - balloon DONE: RT-ON 2.9016 vs control 2.8686 = FLAT (+1.2%) → RT subsumed by maskboth. Main table RT OFF.
  - mv_no_box RUNNING (~KF 415/778). pt1 queued after.
  - When done: `python scripts/r2_p2_rt_spike.py --phase report` → fill p2_rt_spike_outcome.md table.
  - Monitor task `bypgadv92` watches for END lines.

## What's DONE this session (commits e3c6091, 7a58f82, 8ed5c8b, d4e4ef5, 9aa46d5, 6734039)
1. **Rendering NaN bug RCA + fix** (rendering_eval_bug_rca.md, r2_p2_t_offline_render.py): cadence collision
   root-caused, offline re-render validated (balloon PSNR 22.04, band_check OK). 36-run batch → 3090.
2. **DBA-lite oracle provenance audit** (dba_lite_oracle_provenance_audit.md): old negative (e94158d) on
   different base; oracle photo proxy UNWEIGHTED → can't open reliability-weighted photo-DBA; v0 spike
   not worth GPU. codex 019fc3c7.
3. **P2-RT spike** (p2_rt_spike_outcome.md): balloon flat = RT redundant after mask-both. Main table RT OFF.
   Framed as sufficiency ablation (not honest-negative).
4. **3 scaffolds** (efficiency_narrative_scaffold.md, rendering_data_scaffold.md,
   ablation_2x2_tracker_lifecycle_template.md): paper-prep tables with 3090 placeholders.
5. **RT twin contract test** (test_p2_rt_twin_configs.py, 6 tests PASS).
6. **HANDOFF.md** synced with full 08-03 round.

## Memories written
- paper-metrics-on-3090 (2060=spike, 3090=main table)
- dba-oracle-photometric-proxy-unweighted (oracle can't open weighted photo-DBA)
- reliabletracking-subsumed-by-maskboth (RT OFF, sufficiency ablation)

## Open decisions (USER retained — do NOT decide)
- GO/KILL + narrative D′ (sequence-dependent boundary)
- 3090 batch approval (main table PSNR + efficiency official numbers)

## Suggested next (no GPU until spike done):
- Finish mv_no_box + pt1 reads → confirm RT-flat conclusion holds → finalize sufficiency ablation framing.
- If user approves 3090: batch r2_p2_t_offline_render.py on 36 P2-T runs (full-frame PSNR/SSIM/LPIPS).
- The 3 scaffolds need only numbers filled once 3090 runs land.
