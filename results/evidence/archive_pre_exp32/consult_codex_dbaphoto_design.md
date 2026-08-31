# DBA photo-weighted BA — codex review + synthesis (2026-08-03)

> **Codex review (thread 019fc47b) on `dba_photo_weighted_design.md`**, code points
> independently verified by me. Hermes CLI failed (auth/timeout, known issue —
> `[[multi-tool-adversarial-direction]]` records hermes hangs; not blocking).
> Synthesis = codex + verified code facts.

## Verdict: the design as written CANNOT support a GO/KILL oracle gate. Two fatal flaws.

### Fatal flaw 1 — offline `w_map` is NOT a reproduction of online reliability; it is a
###            different quantity (post-hoc map + wrong time span)

**Codex (verified):** online `w_map` is computed once at the warmup iteration (itr 10)
and frozen, using the **map snapshot at that moment** (`slam_frontend.py:935`). The design
proposes recomputing it offline from `final_after_opt/point_cloud.ply` — the **final**,
color-refined map (`slam.py:500`→`565`). These differ:

- final map co-adapted to the online trajectory → rendering at online pose makes the
  geometric anomaly `g` **smaller** (map-pose consistency inflated) → biases toward
  "still prefers online" = **false negative**.
- later frames filled holes / raised opacity / improved static surfaces → pixels that
  were low-weight/unmapped online become high-weight offline → biases toward "prefers
  GT" = **false positive**.
- `s=(1-e_flow)(1-v·g)` (`reliability_signal.py:191`) directly depends on render
  opacity + depth residual, then median/MAD-normalized into `w` (`:206`). Not a small
  perturbation — can **reorder** the whole-frame weights.

**⇒ Either sign is possible; the oracle verdict would be uninterpretable.** A "photo
prefers GT" result could be final-map leakage, not a real objective preference. A
"still prefers online" could be co-adaptation, not a real bias. **The gate decides
nothing.**

### Fatal flaw 2 — prev-frame semantics are wrong (KF-KF vs frame-frame)

**Codex (verified):** online `prev = cur_frame_idx - use_every_n_frames`
(`slam_frontend.py:641`) — the **adjacent previous frame**, and frozen flow is
`f_{t→t-1}` single-frame (`reliability_signal.py:337`). DBA-lite only has KF indices
(~5 frames apart). Using the previous **KF** as prev → `f_static` (rigid flow prediction)
computed from 5-frame cumulative motion, compared against single-frame RAFT flow →
mass static pixels misclassified as flow anomalies → `e_flow` and `w_map` poisoned.

**Fix:** use `frame_id-1` pose from `trj_full_final.json` (it stores per-frame ID + C2W,
`eval_utils.py:321`, invert to W2C). Still not the exact warmup pose, but the correct
endpoint pair for single-frame flow.

## Critical design issue — the whole premise (E) is suspect

**Codex (verified):** `static_conf = clamp(1 - strength·d_soft, floor, 1)`
(`slam_utils.py:447-449`) where `d_soft = reliability_soft = (1-w)` — and it weights
**BOTH** `l1_rgb` AND `l1_depth` (`slam_utils.py:471,475`). So online poses are
**already** optimized under a reliability-weighted RGB+depth objective.

**⇒ The premise "reliability-weighted photo-BA is a NEW objective the online pose
wasn't optimized for" is FALSE.** Re-consuming the same `w` in a photometric BA repeats
a signal already absorbed online; it cannot create new information that points toward
GT. The DBA's only genuinely-new coupling is **KF-KF multi-view** (online is
single-frame-to-map), but the *weight* is not the new information.

**Codex's reframing (the right order):**
1. **First** re-run the **geometric** oracle with reliability-weighted geometry. Current
   DBA geometry has only residual-MAD robust weight (`dba_lite.py:179`), NO reliability.
   This is the cheapest, most-directly-missing term — and it's NOT redundant with
   online (online weighted photo+depth, but DBA's geometric point-to-plane never had
   reliability). Use **exact online `w_map`** (see flaw 1 fix).
2. **Then** test a photo cost **matching the solver's objective** (not the median proxy).
3. Only if **at least one** shows a stable descent direction near `t=0` → build a joint
   solver. If both still prefer online → close the door; don't expect re-consuming
   reliability to add information.

## Oracle-gate statistical adequacy (C)

- 5 points `t∈{0,.25,.5,.75,1}` × 1 seq × 1 seed is insufficient. A 2% drop at t=1 with
  a rising `t=0→0.2` is useless to GN (which starts at t=0). **Must** densify near online:
  `t={0,.02,.05,.1,.2,.5,.75,1}` and require the **initial direction** to descend.
- Report per-edge GT-better counts + KF-block bootstrap CI, not edge-median-of-medians.
- ≥2 seqs × 2 seeds; pre-set a practical margin; 2% with CI crossing 0 = inconclusive,
  not GO.

## Solver-weight coupling (D)

- Don't apply the geometric MAD weight to photo. Two independent IRLS terms:
  `W_geo = w_geo_robust`, `W_photo = w_photo_robust · w_rel`; `H += JgᵀW_geoJg/Ng + lam_photo·JpᵀW_photoJp/Np`.
- **Objective mismatch:** the design's oracle is `Σw|r|/Σw` (L1) but GN optimizes squared
  residuals. Oracle must test the **same robust cost the solver will use** or the gate is
  invalid.
- Source-side `w_photo` alone is insufficient — residual is sampled at **target j**
  (`dba_lite.py:493`); need `w_j` sampled too, `sqrt(w_i·w_j)` for two-sided.
- `lam_photo`: whiten by scale first (geo=m, photo=[0,1] gray, prior=mixed). Set
  `lam_photo=1` center, sweep `{0.1,1,10}`, check initial Hessian block traces match
  order of magnitude. Don't hard-guess.
- `lam_photo:0.0` → keep oracle flag separate from solver lambda; `photo_weighted:true`
  with `lam_photo:0` would silently no-op the solver — footgun.

## SYNTHESIS — what I'm changing in the design

The two flaws + the E-premise together mean: **the current design (offline-recompute
w_map from final PLY → oracle gate → maybe v0) must not be built as-is.** The gate would
be uninterpretable and the premise partly redundant.

**Revised plan (codex's order, adopted):**

1. **Fix the evidence-acquisition first.** Persist exact-online `w_map` + the warmup
   render (depth/opacity) + the exact warmup `prev`/cur poses per KF to disk at run time
   (float16, KF-only — cheap). **This is now a small online-loop change**, not just
   `dba_lite.py`. Branch on `ReliabilitySignal.stash_dba_weights: false` (default off
   so P2-T contract isn't disturbed).
2. **Geometric-weighted oracle first** (cheapest, most-directly-missing, NOT redundant
   with online): re-run `run_dba_oracle` with reliability-weighted **geometry** edges
   (currently only MAD weight). Densify t-sampling near 0; ≥2 seqs × 2 seeds; report
   per-edge + CI. This is the real gate.
3. **Photo term only if** the weighted-geometric oracle shows stable descent near t=0
   — and test the solver's actual squared-robust cost, two-sided weights, not the L1
   median proxy.
4. If both prefer online → **close the door cleanly** (third mechanism finding:
   geometric AND reliability-weighted-geometric objectives both prefer online on these
   short no-loop masked seqs), tracking stays at P2-T.

**Cost re-estimate:** step 1 is a small frontend change + a re-run of ≥2 seqs × 2 seeds
to populate exact-online weights (the P2-T runs did NOT persist w_map). That's the real
GPU floor — not "one oracle run." Decision: this is now a 2-3 day path, not a 30-min
gate. **Higher than I told the user.** Surface that honestly.

## Status
- Design doc `dba_photo_weighted_design.md` is now **superseded by this synthesis**
  for the gate-via-offline-recompute path. Step 1 (persist exact-online w) is the new
  first task.
- hermes not available (auth timeout) — `[[multi-tool-adversarial-direction]]` note:
  when hermes hangs on auth, don't block; codex + code-verification is an acceptable
  single adversarial pass.
