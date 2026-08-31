#!/bin/bash
# EXP57 — P11+mask_insertion single-variable arm on crowd2. 1 arm x 3 seeds = 3 runs.
# E0: resolved config.yml must have SemanticMask.mask_insertion=true; DynKF/Reliability stay off.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
EXPECTED_HEAD=c544b940f231f0bd8dda453439158e5c478ef9d8
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/EXP57/crowd2_attribution}
export EXPECTED_HEAD PY
cd "$REPO"
mkdir -p "$OUT"

actual_head=$(git rev-parse HEAD)
if [ "$actual_head" != "$EXPECTED_HEAD" ]; then
  echo "ERROR: remote HEAD=$actual_head, expected=$EXPECTED_HEAD" >&2
  exit 2
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: remote tracked worktree is dirty; refuse to launch" >&2
  exit 2
fi

CFG=configs/rgbd/experiments/exp57_crowd2_attribution/exp57_p11_mask_insertion_crowd2.yaml

# ---- pre-launch: mask_insertion on, DynKF/Reliability off ----
if ! "$PY" - <<'PY'
import yaml
run = yaml.safe_load(open("configs/rgbd/experiments/exp57_crowd2_attribution/exp57_p11_mask_insertion_crowd2.yaml"))
method = yaml.safe_load(open(run["method_from"]))
base = yaml.safe_load(open(method["inherit_from"]))
sm = {**base.get("SemanticMask", {}), **method.get("SemanticMask", {})}
dk_on = method.get("DynamicKeyframe", {}).get("enabled", False)
rs_on = method.get("ReliabilitySignal", {}).get("enabled", False)
ins = sm.get("mask_insertion", False)
print("E57_PRELAUNCH", {"dynkf": dk_on, "reliability": rs_on, "mask_insertion": ins})
if ins is not True or dk_on or rs_on:
    raise SystemExit(2)
PY
then
  echo "ERROR: EXP57 prelaunch gate failed" >&2
  exit 2
fi

run_one() {
  gpu="$1"; name="$2"; cfg="$3"; seed="$4"
  outnm="${name}_seed${seed}"
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "$outnm GPU=$gpu SKIP" >> "$OUT/exp57.done"
    return 0
  fi
  log="$OUT/${outnm}.consolelog"
  echo "$outnm GPU=$gpu start $(date -Is)" >> "$OUT/exp57.done"
  env PYTHONPATH=$REPO MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    "$PY" slam.py --config "$cfg" --seed "$seed" --eval \
    --results-root "$OUT/$outnm" > "$log" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    resolved=$(find "$OUT/$outnm" -name config.yml | head -1)
    ins=$(grep -A10 "^SemanticMask:" "$resolved" | grep "mask_insertion:" | awk '{print $2}')
    if [ "$ins" != "true" ]; then
      echo "$outnm GPU=$gpu E0_FAIL mask_insertion=$ins (expected true) $(date -Is)" >> "$OUT/exp57.done"
      return 3
    fi
  fi
  echo "$outnm GPU=$gpu finished rc=$rc $(date -Is)" >> "$OUT/exp57.done"
  return "$rc"
}

: > "$OUT/exp57.done"
# 3 runs: seed0 on GPU0, seed1 on GPU1, seed2 on GPU0 (serial after seed0)
run_one 0 "crowd2_mask_ins" "$CFG" 0 & pid0=$!
run_one 1 "crowd2_mask_ins" "$CFG" 1 & pid1=$!
wait "$pid0"; rc0=$?
run_one 0 "crowd2_mask_ins" "$CFG" 2
rc2=$?
rc=0
if [ "$rc0" -ne 0 ] || [ "$rc2" -ne 0 ]; then rc=1; fi
printf '=== EXP57 ALL_DONE rc=%s %s ===\n' "$rc" "$(date -Is)" >> "$OUT/exp57.done"
exit "$rc"
