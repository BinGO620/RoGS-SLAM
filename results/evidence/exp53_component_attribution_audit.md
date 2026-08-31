# EXP53 组件归因审计（零 GPU）

> 本文档只读取 EXP53 已落盘产物，不运行 SLAM、不申请 GPU。它审计结构与机制活动，
> 不把 bundled contrast 解释成单组件因果效应。

- campaign: `EXP53-P11-phase2`
- run root: `/data/monogs-ours/results/runs/EXP53/p11phase2`
- hardware: jiangwenheng dual RTX 3090; one task per GPU
- metric: `full-trajectory tracking_raw.csv ate_rmse_cm (evo -a Horn)`
- seeds: `0/1/2`; mean ± sample sd（ddof=1）; escape = ATE < 5 cm

## 1. EXP53 目标结果

| sequence | P11 seed0/1/2 | P11 mean±sd | Combined seed0/1/2 | Combined mean±sd | P11−C mean | ratio |
|---|---:|---:|---:|---:|---:|---:|
| crowd2 | 7.9308/7.7350/5.0033 | 6.89±1.64 | 2.0671/2.2005/2.0583 | 2.11±0.08 | 4.78 | 3.27× |
| mv_no_box | 3.4180/4.0247/3.5150 | 3.65±0.33 | 2.5598/2.6025/2.7384 | 2.63±0.09 | 1.02 | 1.39× |

## 2. Resolved configuration and activity

| sequence | arm | DynKF | Reliability | mask mapping | mask insertion | reliability frames | KF count | KF gap | completed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| crowd2 | P11 | [False] | [False] | [True] | [False] | 0/0/0 | 16/15/15 | 7–374/5–379/5–400 | True |
| crowd2 | C | [True] | [True] | [True] | [True] | 893/893/894 | 179/179/179 | 5–5/5–5/5–5 | True |
| mv_no_box | P11 | [False] | [False] | [True] | [False] | 0/0/0 | 35/34/33 | 5–79/5–157/5–150 | True |
| mv_no_box | C | [True] | [True] | [True] | [True] | 777/777/777 | 156/156/156 | 5–5/5–5/5–5 | True |

### Directly observed

- Both sequences have complete 3-seed P11 and Combined records; all runs report `status=OK`.
- P11 and Combined share `mask_mapping=ON`, RobustTracking/Huber, `lifecycle_mode=prune`, and `kf_interval=5`.
- The resolved P11→Combined difference is exactly three switches: `DynamicKeyframe.enabled`, `ReliabilitySignal.enabled`, and `mask_insertion`.
- Combined has complete frozen-flow reliability artifacts; P11 has no reliability-signal artifact, as expected from its disabled setting.
- Combined KF IDs are spaced at five frames in both target sequences, while P11 is substantially sparser and irregular.
- `deferred_commit_summary.json` exists for both arms, so lifecycle activity is present on both sides; its counters differ substantially with the KF schedule and reliability confirmation path.

## 3. What the artifacts can and cannot establish

### Mechanism clues, not causal estimates

- Combined's reliability frames and weighted candidate-confirmation path show that ReliabilitySignal is active, but activity is not an ATE counterfactual.
- Combined's five-frame KF spacing is consistent with the configured `gap_cap=5`; without `KeyframeDiag`, existing logs cannot distinguish ordinary covisibility KFs from `crisis` promotions.
- Insertion-gate log activity separates the arms operationally, but does not quantify the counterfactual effect of insertion while the other two switches remain fixed.
- The different deferred/prune counters are compatible with a changed keyframe schedule and reliability confirmation, but are downstream observations rather than isolated effects.

### Causal gap

The EXP53 contrast is a three-variable bundled intervention. It cannot identify the separate effects of DynamicKeyframe, ReliabilitySignal, or `mask_insertion`, and it cannot tell whether the observed improvement is additive or interactive.

The next causal test therefore remains a new, pre-registered 2-sequence × 2-single-variable-arm × 3-seed campaign:

- `P11 + DynKF`: only `DynamicKeyframe.enabled=true`; Reliability and insertion remain OFF.
- `P11 + Reliability`: only `ReliabilitySignal.enabled=true`; DynKF and insertion remain OFF. Because `reliability_confirm=true` changes C± confirmation when maps exist, this arm measures the Reliability signal family (tracking + candidate confirmation), not pure tracking down-weight.
- Open `KeyframeDiag.enabled` in both intervention arms so `covis` versus `crisis` decisions are recorded.

## 4. Historical evidence boundary

Each historical item below is a separate reference. Its numbers are not merged into EXP53 means:

| evidence | campaign | hardware | seeds | metric | scope |
|---|---|---|---|---|---|
| `results/evidence/p6_pb_2x2_3seed_verdict.md` | P-B exp-v3-11 | jiangwenheng 3090 | 0/1/2 | full-trajectory tracking_raw.csv ate_rmse_cm, evo -a Horn | mv_no_box mask x DynamicKeyframe 2x2; not EXP53 and not crowd2 |
| `results/evidence/archive_pre_exp32/wpa_factorial_verdict.md` | WP-A exp-v3-18 | jiangwenheng 3090 | 0/1/2 | full-trajectory ATE, log-ratio factor readout | mv_no_box DynamicKeyframe/Reliability/RobustTracking factorization; mask-free backbone |
| `results/evidence/p7_cuesplit_verdict.md` | P7 exp-v3-17 | jiangwenheng 3090 | 0/1/2 | full-trajectory tracking_raw.csv ate_rmse_cm, evo -a Horn | mv_no_box Reliability cue split; not a P11-vs-Combined contrast |
| `results/evidence/archive_pre_exp32/fullkern_rerun_regime_split.md` | EXP25 FULLKERN rerun | jiangwenheng 3090 | 0/1/2 | full-trajectory tracking_raw.csv ate_rmse_cm, evo -a Horn | crowd2 old K1R1L0 versus complete K1R1L1; historical source correction |
| `results/evidence/exp53_p11phase2_verdict.md` | EXP53 P11 phase 2 | jiangwenheng 3090 | 0/1/2 | full-trajectory tracking_raw.csv ate_rmse_cm, evo -a Horn | current bundled P11-vs-Combined contrast |

## 5. Audit verdict

**ZERO-GPU STRUCTURAL AUDIT PASS; COMPONENT CAUSAL ATTRIBUTION UNRESOLVED.**

The current evidence supports the EXP53 regime split: Combined is better on `crowd2` and `mv_no_box` under the full bundled configuration. It does not license a claim that DynamicKeyframe or ReliabilitySignal alone caused the gain. Freeze the EXP54 single-variable design before any GPU dispatch.
