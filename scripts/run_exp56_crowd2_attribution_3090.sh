#!/bin/bash
# EXP56 — crowd2 attribution completion: P11+DynKF+Reliability double-variable arm.
# 1 arm x 1 sequence x 3 seeds = 6 runs. E0 gate: resolved config must show
# DynKF=true, Reliability=true, mask_insertion=false.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
EXPECTED_HEAD=c544b940f231f0bd8dda453439158e5c478ef9d8
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/EXP56/crowd2_attribution}
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

E56=configs/rgbd/experiments/exp56_crowd2_attribution

# ---- pre-launch: resolved config asserts exactly two components on ----
if ! "$PY" - <<'PY'
import yaml
run = yaml.safe_load(open("configs/rgbd/experiments/exp56_crowd2_attribution/exp56_p11_dynkf_reliability_crowd2.yaml"))
method = yaml.safe_load(open(run["method_from"]))
base = yaml.safe_load(open(method["inherit_from"]))
sm = {**base.get("SemanticMask", {}), **method.get("SemanticMask", {})}
dk_on = method.get("DynamicKeyframe", {}).get("enabled") is True
rs_on = method.get("ReliabilitySignal", {}).get("enabled") is True
ins = sm.get("mask_insertion", False)
print("E56_PRELAUNCH", {"dynkf": dk_on, "reliability": rs_on, "mask_insertion": ins})
if not (dk_on and rs_on and not ins):
    raise SystemExit(2)
PY
then
  echo "ERROR: EXP56 prelaunch gate failed" >&2
  exit 2
fi

run_one() {
  gpu="$1"; name="$2"; cfg="$3"; seed="$4"
  outnm="${name}_seed${seed}"
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "$outnm GPU=$gpu SKIP" >> "$OUT/exp56.done"
    return 0
  fi
  log="$OUT/${outnm}.consolelog"
  echo "$outnm GPU=$gpu start $(date -Is)" >> "$OUT/exp56.done"
  env PYTHONPATH=$REPO MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    "$PY" slam.py --config "$cfg" --seed "$seed" --eval \
    --results-root "$OUT/$outnm" > "$log" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    resolved=$(find "$OUT/$outnm" -name config.yml | head -1)
    dk=$(grep -A3 "^DynamicKeyframe:" "$resolved" | grep "enabled:" | awk '{print $2}')
    rs=$(grep -A8 "^ReliabilitySignal:" "$resolved" | grep "enabled:" | head -1 | awk '{print $2}')
    ins=$(grep -A10 "^SemanticMask:" "$resolved" | grep "mask_insertion:" | awk '{print $2}')
    if [ "$dk" != "true" ] || [ "$rs" != "true" ] || [ "$ins" != "false" ]; then
      echo "$outnm GPU=$gpu E0_FAIL dk=$dk rs=$rs ins=$ins $(date -Is)" >> "$OUT/exp56.done"
      return 3
    fi
  fi
  echo "$outnm GPU=$gpu finished rc=$rc $(date -Is)" >> "$OUT/exp56.done"
  return "$rc"
}

: > "$OUT/exp56.done"
# 6 runs split 3/3 across two GPUs (crowd2 ~30-45 min/run)
run_queue() {
  gpu="$1"; start="$2"
  for seed in $(seq $start 2 2); do
    run_one "$gpu" "crowd2_dynkf_rel" "$E56/exp56_p11_dynkf_reliability_crowd2.yaml" "$seed" || return 1
  done
}
run_queue 0 0 & pid0=$!
run_queue 1 1 & pid1=$!
wait "$pid0"; rc0=$?
wait "$pid1"; rc1=$?
rc=0
if [ "$rc0" -ne 0 ] || [ "$rc1" -ne 0 ]; then rc=1; fi
printf '=== EXP56 ALL_DONE rc=%s %s ===\n' "$rc" "$(date -Is)" >> "$OUT/exp56.done"
exit "$rc"
