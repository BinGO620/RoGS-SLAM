# Synthesis: codex + hermes design review of frozen-pose de-confounding control (2026-08-02)

> Two independent reviews (codex MCP gpt-5.5/high; hermes strong model + web) of the experiment DESIGN before any GPU spent.
> Full text: `consult_codex_frozenpose.md`, `consult_hermes_frozenpose.md`.

## CONSENSUS (both, high confidence) — the proposal as written is a NULL experiment

**Frozen-pose ATE difference = 0 BY CONSTRUCTION.** Both arms share the identical injected pose file; `Oracle.pose_file` sets `oracle_skip=True` at itr 0 and breaks before any Adam step (`utils/oracle_pose.py` + `slam_frontend.py:905`); `viewpoint.R_gt/T_gt` never touched; end-of-run ATE = injected-vs-real-GT, identical for both arms. This is a CODE FACT (hermes traced it) + MEASURED FACT (R2-P01-E2: balloon frozen-pose ATE 2.0618cm to 4dp on ALL runs, both arms, all seeds, ±0.02 fail-fast; registry: "prune=deferred ATE identical under frozen pose").

⇒ "does deferred still cost ATE under frozen pose?" has a predetermined answer: **zero, always, every sequence.** Running pt1 with ATE as the outcome = null experiment. Calling "cost vanished" = category error (consistent with both "tracking artifact" AND "map-level effect too small to move ATE when pose pinned").

## CONSENSUS — correct observable (map-level, NOT ATE)

Both agree: under frozen pose, ATE is a **canary** (= injected-tracker ATE ±0.02, G1 gate), NOT an outcome. The arm-discriminating observables are **map-level**:
- **PRIMARY: G_def/G_prune** (does compactness contrast survive when pose-map feedback disabled? R2-P01-E2 already measured deferred fewer Gaussians 13/14 pairs at identical ATE).
- **SECONDARY: vac_depth, vac_psnr** (fidelity at equal pose; R2-P01-E2 fidelity co-primary gate NOT met — only pt2 cleared 4/4 — so this is a real arm-discriminating axis).
- Record: KF count + indices, VRAM/FPS, inserted/promoted/expired/pruned counts, static PSNR, injected-traj audited ATE.

**What it tests (limited, both agree):** a tracker-orthogonal MAPPING effect. Does NOT show mask coverage causes it. Says nothing about WHY self-tracked deferred ATE is higher. Can only WEAKEN or LEAVE-UNCHANGED the H-D INDETERMINATE verdict; cannot confirm H-D (n=1, one seq, map-level only).

**⚠ codex-only caveat: frozen pose does NOT freeze DynamicKeyframe decisions.** If KF schedules differ between arms, R_G^F measures total lifecycle-induced mapping-policy effect (incl. altered coverage), NOT pure admission efficiency. Freeze KF indices if feasible; else preregister differing schedules as ambiguity trigger.

## Q2 — sequence choice: pt1 defensible but not optimal; NO clean high-coverage+easy cell in Bonn

- hermes: clean high-coverage+easy-tracking cell does NOT exist in Bonn. balloon2 (59.4% cov, ATE 5.2cm, easy) is closest but person+balloon (class-composition confound §6.1) + self-tracked ratio INDETERMINATE (0.910). crowd/synchronous = HARD tracking (synchronous "several people repeatedly jumping"; crowd MonoGS ATE 65-98cm = collapse regime).
- codex: pt1 is the WRONG single sequence; run a matched SET — at minimum balloon2 AND pt1/pt2, not pt1 alone. Better: preregister full 2×2 inclusion rule (coverage measured w/o SLAM outcomes + difficulty by arm-independent baseline).
- **Resolution:** pt1 is the best AVAILABLE single-seq pick (largest self-tracked ATE cost +13-37%, near tracking limit). If budget allows a SET, add balloon2 (high-cov+easy, person+balloon confound flagged). Do NOT run crowd/synchronous. **Run pt1 first (seed 0 screening); if MAP-EFFECT/REVERSED fires, expand to 3 seed + balloon2.**

## Q3 — executable prereg (three branches on R_G^F, fidelity gate)

| branch | condition (frozen-pose pt1, seed 0) | interpretation |
|---|---|---|
| MAP-EFFECT | R_G^F judgable (|r-1|>2×own_sd) AND vac_depth OR vac_psnr arm-discriminating (>1×own_sd, same sign) | deferred perturbs map independently of tracking ⇒ H-D mechanism story survives; self-tracked ATE cost may be partly tracking-coupled but a map-level channel exists |
| NO-MAP-EFFECT | R_G^F in band AND both fidelity metrics within own_sd | deferred's self-tracked ATE cost plausibly tracking-coupled, not map-level ⇒ H-D mechanism story WEAKENED; report as scoped limitation, do NOT claim map-level mechanism |
| REVERSED | R_G^F judgable <1 (deferred smaller) on pt1 under frozen pose | contradicts pt1 self-tracked indeterminate/>1 ⇒ self-tracked pt1 compactness was tracking-coupled, not coverage effect |

Pre-declared guardrails (both):
1. ATE = canary, NOT outcome. State construction-identity fact in prereg.
2. Single seed = screening only; MAP-EFFECT/REVERSED ⇒ 3-seed confirmation before any paper claim. Do NOT let single-seed override 3-seed self-tracked table.
3. Fidelity margins INHERITED (import 1.56cm/0.28dB from r2_p03_sweep_readout, as P2-T does), NOT re-fit on pt1 frozen-pose.
4. Do NOT upgrade H-D status from this experiment alone. Ceiling = weaken/leave-unchanged.
5. Provenance: pt1 already-seen = "mechanistic control on seen data," NOT independent test.
6. codex: audit pt1 RGD trajectory before launch (pt2's injected ATE was 26.30cm; a poor fixed traj changes mapping regime, not "tracking difficulty removed").

## My decision (revised plan, for user GO)

**REVISED experiment = frozen-pose pt1 pair, map-level observables primary, ATE canary.** NOT the ATE-null version. ~1h on 2060, fits F@5cm post-proc gap (cannot run concurrent w/ SLAM).

Config: two new files mirroring p2s_combined_{prune,deferred}_pt1.yaml + Oracle.pose_file (RGD pt1) + cam_lr=0.0. seed 0. Contract test pinning: Oracle.pose_file present + cam_lr=0 + lifecycle_mode the only other diff.

**Order of operations after 36/36:**
1. F@5cm geometry post-proc (36 runs, GPU-gap, scripted) — fills the 2×2's compactness column with fidelity.
2. frozen-pose pt1 pair (map-level de-confound, ~1h) — directly tests hermes's own blind spot with the CORRECT observable.
3. Module ablation (codex blind spot: backbone bundles 4 mechanisms) — at minimum vanilla-MonoGS-vs-backbone on 1-2 seqs.
4. SKIP crowd/synchronous (both reviews).

**Will NOT run without committing the prereg + contract first.** This fits user's "补实验也可以" autonomy grant — it's a labeled mechanistic control on existing data, not a new headline claim.
