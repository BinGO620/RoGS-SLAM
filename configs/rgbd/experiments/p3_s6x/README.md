# `P3-S6X` configs — the S6 knob group, moved to the self-tracked regime

One file per sequence, and every one of them is the **same three knobs** bolted onto the
P2-T prune run config for that sequence:

```yaml
DeferredCommit.ttl_keyframes      5     -> 1
Training.gaussian_th              0.7   -> 0.9
opt_params.densify_grad_threshold 2e-4  -> 5e-4
```

Those three values are not chosen here. They are `S6_maxpress`, the single rung that ever
pressed below arm B (`scripts/r2_p03_sweep.LEVELS["S6_maxpress"]`), and
`tests/test_p3_s6x_configs.py` asserts this directory's knob values are **identical to that
frozen dict** — if SWEEP's rung ever changed, these configs would fail E0 rather than silently
migrate a different baseline.

**Why each file inherits from the P2-T prune run config rather than restating the backbone.**
The campaign's whole claim is "the same knobs, in a regime that can charge for them". Inheriting
makes the resolved diff against the anchor *structurally* equal to the three knobs: there is no
second copy of the backbone that can drift, and the two anchors this campaign re-runs
(`p2s_combined_{prune,deferred}_{seq}.yaml`) are referenced by identity from
`scripts/r2_p2_t.ARMS`, so this campaign introduces **no anchor config of its own**.

**What changed relative to where S6 was measured.** In `R2-P03-SWEEP` / `-DECOMP` / `-S6REPL`
the base was `oracle_prune_balloon.yaml`: one sequence, an injected RGD trajectory
(`Oracle.pose_file` set, camera lrs zeroed), `ate_rmse_cm` pinned at 2.0618 on all 46 runs.
Here the base is self-tracked (`Oracle.pose_file: ""`, cam lrs 0.003 / 0.001) across 6
sequences. That is the treatment: `ttl=1` drives the prune arm's `promoted` to 0 and collapses
its candidate residue 23927 → 5000, and under a frozen trajectory a degraded map cannot feed
back into the pose. Whether it can here is what the campaign measures.

Pre-registration (dispositions fixed before the first run):
`results/evidence/p3_s6x_prereg.md` §1–§3.
