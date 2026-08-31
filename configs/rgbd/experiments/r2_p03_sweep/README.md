# R2-P03-SWEEP — arm-A prune-pressure ladder (matched-budget rate–distortion)

Non-preregistered exploration (`02-method.md` P0). Every file here is a **pressure
overlay on arm A** (`r2_oracle_admission/oracle_prune_balloon.yaml`), i.e. the
insert-then-prune control run with its own prune/admission knobs turned up. The
question is the reviewer's:

> "fewer Gaussians ≠ dynamic contamination removed — it could be an **under-tuned
> pruning baseline**."

so arm A is given its best shot at reaching arm B's operating point (~11.3k
Gaussians) along its own hyperparameters, under the frozen RGD trajectory.

Allowed diff of every overlay vs `oracle_prune_balloon.yaml` = `{method}` ∪ the
level's declared knobs, pinned by `tests/test_r2_p03_sweep_configs.py`. Nothing
touches the pose channel, the evaluation masks, or `Mapping.lifecycle_mode`.

## Which knobs, and why these

Effective prune/admission levers on this stack (RGB-D, `sensor_type: depth`):

| lever | where | note |
|---|---|---|
| `DeferredCommit.ttl_keyframes` | `utils/deferred_commit.py:581` | age at which a still-pending candidate expires; in arm A expiry **deletes its lineage** from the map |
| `DeferredCommit.max_candidates_per_keyframe` | `:386` | per-KF candidate budget (default 5000 is saturated: ~4.17M pixels overflow per run) |
| `Training.gaussian_th` | `utils/slam_backend.py:489` → `densify_and_prune(min_opacity=…)` | the native MonoGS opacity prune |
| `opt_params.densify_grad_threshold` | same call | native densification gate |

`Training.prune_mode` is **inert here**: the covisibility prune is guarded by
`if to_prune is not None and self.monocular` (`slam_backend.py:457`) and these runs
are RGB-D, so the opacity/size prune inside `densify_and_prune` is the only native
prune that fires.

## The ladder

| level | file | knobs vs arm A default |
|---|---|---|
| `S1_ttl2` | `sweep_s1_ttl2_balloon.yaml` | `ttl_keyframes: 5 → 2` |
| `S2_ttl1` | `sweep_s2_ttl1_balloon.yaml` | `ttl_keyframes: 5 → 1` |
| `S3_cap1000` | `sweep_s3_cap1000_balloon.yaml` | `max_candidates_per_keyframe: 5000 → 1000` |
| `S4_gth080` | `sweep_s4_gth080_balloon.yaml` | `gaussian_th: 0.7 → 0.8` |
| `S5_gth090` | `sweep_s5_gth090_balloon.yaml` | `gaussian_th: 0.7 → 0.9` |
| `S6_maxpress` | `sweep_s6_maxpress_balloon.yaml` | `ttl 1` + `gaussian_th 0.9` + `densify_grad_threshold 0.0002 → 0.0005` |

Anchors are **not** in this directory — they are the unmodified campaign arms
`r2_oracle_admission/oracle_prune_balloon.yaml` (A0) and
`oracle_deferred_balloon.yaml` (B), re-run inside the same campaign so that the
fidelity comparison is not cross-commit (documented cross-campaign shift on this
arm is 1.5–2.0 cm, the same order as the 1.56 cm non-inferiority margin).

Runner `scripts/r2_p03_sweep.py`, readout `scripts/r2_p03_sweep_readout.py`.
