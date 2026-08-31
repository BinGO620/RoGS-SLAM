# P2-S smoke (2026-07-31) — the combined backbone's first ever Bonn run

> **Screening only.** 2 runs, single seed, balloon. No verdict may be written from this
> (README discipline ⑤). It exists to buy two numbers — the backbone's real Bonn ATE, and the
> real per-run wall clock — before 36 runs are committed. Both were unknowns: the combined
> backbone (`mask-both + RobustTracking + DynamicKeyframe + ReliabilitySignal`) had **zero rows
> in registry.csv**; the ~3 cm reference was `V1-FIXED5` on TUM `f3_wk_xyz`, whose universal-V1
> sibling drifted to 55.54 cm on `f2_xyz`.
>
> Configs: `configs/rgbd/experiments/p2_render/p2s_combined_{prune,deferred}_balloon.yaml`,
> self-tracked (no `Oracle.pose_file`, cam lrs live 0.003/0.001), the only resolved difference
> between the two arms = `Mapping.lifecycle_mode`, pinned at both method-base and run-config
> level by `tests/test_p2_combined_twin_configs.py` (8 tests green). Run against commit `a8bda68`,
> clean worktree.

## §1 The two numbers P2-S was built to buy

| arm | ATE cm | KF-ATE cm | refined G | VRAM GB | online FPS | wall min |
|---|---|---|---|---|---|---|
| `Combined-Prune` | **3.1872** | 3.173 | 35991 | 2.318 | 0.485 | ~28 |
| `Combined-Deferred` | **3.2307** | 3.1749 | 18391 | 2.004 | 0.535 | ~25 |

- **The backbone's Bonn ATE is competitive, not last.** Both arms land at ~3.2 cm — between
  RGD-SLAM (2.26, the published trajectory source) and DG-SLAM (3.65). This **refutes the
  scoping-time constraint #1** as it applied to the combined backbone: the 37.72/29.03 cm
  figures were from the `*_rtoff` arms (no mask, no adaptive tracking), which is the wrong
  base for a main table. The 5 ATE experiments in the tracking-exploration archive
  (FullFramePose / CoarsePoseInit / masked_icp / DBA-lite / ReliabilitySignal) were each on
  different bases; none ran this combined backbone, so this number was genuinely unmeasured.
- **The per-run cost is now measured, not estimated.** ~25–28 min/run online (mapping_time_s
  805/889). The scoping estimate was 45–90 min/run extrapolated from rtoff × a guess for the
  mask+keyframing overhead — the guess was ~2× too high. **P2-T (36 runs) is therefore
  ~15–17 h on the 2060, not 27–54 h** — it fits in one day, which materially changes the
  schedule.

## §2 Compactness holds on the combined backbone (screening)

At single seed, the lifecycle result that carries the paper appears on the competitive backbone
too: **deferred = 18391 vs prune = 35991 = 0.511× (−48.9%)**, VRAM 0.864×, with ATE essentially
tied (+1.36%, 3.23 vs 3.19). The rtoff B-vs-A0 series was −55.2 / −54.3 / −46.6 / −51.4% across
four frozen-pose campaigns; this self-tracked combined-backbone single seed lands inside that
range. **Not a verdict** — one seed — but the direction is present where the paper most needs it.

## §3 The caveat that bounds both numbers (single seed, one sequence)

1. **One seed.** ATE 3.19 vs 3.23 is a 0.04 cm gap — far below any seed-variance band this
   project has measured. The ATE-tie reading is "indistinguishable at n=1", not "deferred
   matches prune". P2-T's 3 seeds are what make ATE readable.
2. **balloon only.** The sequence most likely to flatter a person mask (the mover is a person
   *holding* a balloon; see the MASKRATE limitation). pt2 was the worst rtoff ATE (44 cm); it
   is the highest-risk P2-T sequence and is not screened here.
3. **Self-tracked, not the frozen-pose screen.** These ATEs are real tracker output, which is
   the point — but it means map-fidelity metrics run in a noisier regime than the controlled
   screen (static_psnr ~23.3 vs the screen's ~14.5 is a different scale entirely, and the
   vacated/nonvacated columns are not comparable across regimes).

## §4 Decision for P2-T (go condition met)

P2-S's pre-committed kill condition was "ATE > 10 cm ⇒ redesign, 2 runs". Both arms are at
~3.2 cm. **P2-T is go-eligible**: 5 dynamic × {A,B} × seeds 0/1/2 + f1_desk × {A,B} × 3 = 36
runs, ~15–17 h on the 2060. The remaining screening risk is pt2 (untested on this backbone);
P2-T could lead with pt2 seed 0 if the user wants that de-risked before committing all 36.

Single seed. No verdict. GO/KILL is the user's.
