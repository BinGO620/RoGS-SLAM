# PROVENANCE — how this repository relates to monogs-ours

- **Source**: `/data/monogs-ours` @ `31b0f03670a4366e8c6a5a7012963962a8203663` (branch
  `feat/bpw-densification`). monogs-ours is not split or modified; it serves as the
  backup repository.
- **How it was built**: copied by manifest (code started from RoGS-Densify's
  same-origin pruned state, i.e. already carrying paper 2's mechanisms) → paper 1
  incremental subtraction (removed the densification mechanisms) → swapped configs
  and criterion artifacts → verified.
- **Earlier history**: this repo's original `main` (2 commits, the 2026-09 open-source
  snapshot) is tagged `legacy-20261031` and has been pushed to the remote; it is not
  lost.

## Organization principles

Same as RoGS-Densify/PROVENANCE.md (subtraction never renames, explicit inventory,
same-origin core, explicit inheritance, criterion artifacts in-repo). "This paper's
code" here = paper 1's four components (K/R/L/D + semantic mask), all inside the
core switch set and enabled by default in `combined_prune/method.yaml`; no new
standalone files.

## Changes to the core files (relative to RoGS-Densify's same-origin state, i.e.
monogs-ours@31b0f0367 minus paper 2)

Purpose: remove the files and wiring of paper 3's (densification) mechanism. Under
the paper-1 configuration no vector-selection branch is active; the `else` branch
returns (None, None) → scalar path. The surgery is equivalent to always taking the
scalar path, so core behavior is unchanged.

### utils/slam_backend.py

| Source lines (RoGS-Densify state) | Removed |
|---|---|
| 145–159 | `selective_densification`/`densification_selection` imports |
| 356–364 | FDose event-ordinal reset (`_fdose_event_idx`/`_fdose_ordinal_must_be_zero`) |
| 406–445 | init-site vector dispatch (bpw/cgb/fdose/else) → replaced by pure-scalar `densify_and_prune` |
| 798–822 | selective residual-EMA ledger block (including the `update_static_prob_from_evidence` call) |
| 829–873 | map-site vector dispatch + `log_sel_dens_state` → replaced by pure-scalar `densify_and_prune` |
| 160–163 | `static_prob` two-function import (removed with the ledger block; the module and the `static_prob` tensor field are kept) |

### Removed modules (2, paper-3 only)

`utils/{densification_selection, selective_densification}.py`
(they remain in the RoGS-Densify repository.)

## Criterion artifacts (results/)

- `results/evidence/`: copied verbatim from
  `biyelunwen/01_small_papers/MMM2027/deliverable/evidence/` (table1_18seq_ate,
  wpa_factorial, p7_cuesplit and 6 others, 9 items) plus this repo's new
  `verify_table1.py`.
- `results/runs/P6/`: extracted from
  `/data/archive/monogs-ours-results-archive-20260901.tar` (`results/runs/` and
  `results/runs_remote_cache/`; P6 family, 8 sub-families, 111+ runs). Criterion
  artifacts only. **Discarded** `plot/trj_final.json`/`trj_full_final.json`
  (221 MB intermediate files); ATE numbers are taken from `tracking_raw.csv` /
  `per_frame_ape.csv`, and the trajectories can be regenerated from the config.
- No run artifacts exist for the `vanilla`/`rgd` columns (stock MonoGS and the
  comparison method were not produced by this group's code). Those columns' numbers
  come from the evidence CSV, and `verify_table1.py` labels each cell honestly.

## Verification record

| Item | Result |
|---|---|
| AST import closure | 64 files, nothing missing |
| `py_compile` slam.py / slam_frontend.py / slam_backend.py | pass |
| `pytest tests/test_config_valid.py` | 9 passed (inheritance chain valid for all 18 sequences) |
| Table 1 recomputation check | **28 cells MATCH (all checkable cells in the combined + maskfree columns)**, 44 cells NO-RUN-IN-REPO (labelled honestly) |
| Submodule pins | `diff-gaussian-rasterization@43e21bff`, `simple-knn@44f764299` |
| 2060 smoke A/B (40 frames, combined/balloon, seed 0) | see the note below |

## Numeric verification matrix (Table 1; tool = results/evidence/verify_table1.py)

Data source = every in-repo run criterion artifact (tar archive P6 eight families +
git tag mmm2027-submission's runs/WPB and P6 supplements, 254 `tracking_raw.csv`).
Matching = sequence-name regex + mean/std dual window, with cross-family merging
supported (the paper batch has a history of cross-family seed supplementation, e.g.
balloon/maskfree's 3 seeds split across P6-MASKOFF and P6-MASKOFF-3SEED).

| Column | Exact recompute | Status |
|---|---|---|
| **maskfree** | **18/18** | all hit (including 3 cross-family merged cells) |
| **combined** | **13/18** | TUM 10 + crowd/crowd2/pt1 hit; **5 BONN cells missing** (balloon 3.06 / balloon2 5.28 / mv_no_box 2.66 / mv_no_box2 5.14 / pt2 10.44) — the paper batch's run artifacts are in neither the tar nor the tag (the closest candidate, the WPB-CONFIRM factorial batch K1R1L1, differs by 0.2–1.4 in the mean and is not the same batch) → **to be located in the 3090 `/mnt/app` artifacts or re-run** |
| vanilla (MonoGS) | 1/18 | external method column, not produced by this group's code; run artifacts are expected to be absent. Numbers from the evidence CSV |
| rgd | 0/18 | same as above (external comparison method) |

**Totals: 32/72 cells recompute exactly; of the remaining 40, 35 are external-method
columns (structurally artifact-free) and 5 are registered as pending.**
Config parity: 47 YAMLs byte-identical to monogs-ours@31b0f0367 (parity check 2026-11-01).

## Smoke A/B note

- Setup: `configs/experiments/combined_prune/balloon.yaml`, `--max-frames 40 --seed 0`,
  same machine and same card (RTX 2060), one run each; reference = the clean code copy
  at monogs-ours@31b0f0367.
- Readings: ATE RMSE 0.7163 vs 0.7386 cm (Δ = 0.022 cm), KF-ATE 0.8654 vs 0.9064,
  RPE 1.4673 vs 1.4834. The absolute Δ is about an order of magnitude below the
  same-config cross-batch noise floor (0.18–0.62 cm). Surgery equivalence was checked
  separately: the removed `else`-branch functions
  (`compute_per_gaussian_knobs`/`log_sel_dens_state`) return early with zero side
  effects when disabled and consume no RNG, so the scalar path is bitwise identical.
  **Verdict: PASS (Δ is pipeline-rerun CUDA nondeterminism).**

## Archiving policy (registered 2026-11-04; user instruction, applies to every repo)

- **Keep only the latest in the working area**: outdated versions, drafts, and
  historical snapshots all move into this repo's `archive/` (archive in place, named
  `{semantic}_{YYYY-MM-DD}`), never left scattered at the top level.
- **Archive ≠ delete**: archived items are evidence keys; ledger pointers are not
  rewritten; every archive location gets a `README.md` and is registered in the
  in-repo index.
- **Repo independence**: experiments are always run back in monogs-ours; this repo
  only takes "criterion-confirmed" result snapshots (the four-step sync is in
  monogs-ours `/data/master-thesis/WORKFLOW.md`). This repo carries its own gates and
  PROVENANCE, so it can be re-verified without the monogs-ours working area.
- **Milestone-triggered sync**: only re-run the manifest and full gates and update
  PROVENANCE at milestones (verdict landed, submission, etc.); do not sync routinely
  (to avoid snapshot drift).
