#!/bin/bash
# EXP59 — boundary band validation on 6 unseen BONN sequences.
# 6 seqs x 2 arms x 3 seeds = 36 runs. E0: resolved SemanticMask.enabled matches arm.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
EXPECTED_HEAD=c544b940f231f0bd8dda453439158e5c478ef9d8
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/EXP59/boundary_validation}
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

E59=configs/rgbd/experiments/exp59_boundary_validation
SEQS="crowd3 kidnapping_box kidnapping_box2 balloon_tracking balloon_tracking2 placing_nonobstructing_box"

run_one() {
  gpu="$1"; seq="$2"; arm="$3"; seed="$4"
  outnm="${seq}_${arm}_seed${seed}"
  got=""
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "$outnm GPU=$gpu SKIP" >> "$OUT/exp59.done"
    return 0
  fi
  cfg="$E59/exp59_${arm}_${seq}.yaml"
  log="$OUT/${outnm}.consolelog"
  echo "$outnm GPU=$gpu start $(date -Is)" >> "$OUT/exp59.done"
  env PYTHONPATH=$REPO MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    "$PY" slam.py --config "$cfg" --seed "$seed" --eval \
    --results-root "$OUT/$outnm" > "$log" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    resolved=$(find "$OUT/$outnm" -name config.yml | head -1)
    sm_on=$(grep -A6 '^SemanticMask:' "$resolved" 2>/dev/null | grep 'enabled:' | head -1 | awk '{print $2}')
    if [ "$arm" = "combined" ] && [ "$sm_on" != "true" ]; then
      echo "$outnm GPU=$gpu E0_FAIL combined but SemanticMask.enabled=$sm_on $(date -Is)" >> "$OUT/exp59.done"
      return 3
    fi
    if [ "$arm" = "maskfree" ] && [ "$sm_on" != "false" ]; then
      echo "$outnm GPU=$gpu E0_FAIL maskfree but SemanticMask.enabled=$sm_on $(date -Is)" >> "$OUT/exp59.done"
      return 3
    fi
  fi
  echo "$outnm GPU=$gpu finished rc=$rc sm=$sm_on $(date -Is)" >> "$OUT/exp59.done"
  return "$rc"
}

: > "$OUT/exp59.done"
# Paired queues: GPU0 = seed0 all seqs then seed2; GPU1 = seed1 then seed2 remainder.
# Simplest robust split: GPU0 does even (seq_idx+seed) combos, GPU1 odd.
i=0
run_half() {
  gpu="$1"; parity="$2"
  for seq in $SEQS; do
    for arm in maskfree combined; do
      for seed in 0 1 2; do
        if (( i % 2 == parity )); then
          run_one "$gpu" "$seq" "$arm" "$seed" || return 1
        fi
        i=$((i+1))
      done
    done
  done
}
run_half 0 0 & pid0=$!
run_half 1 1 & pid1=$!
wait "$pid0"; rc0=$?
wait "$pid1"; rc1=$?
rc=0
if [ "$rc0" -ne 0 ] || [ "$rc1" -ne 0 ]; then rc=1; fi
printf '=== EXP59 ALL_DONE rc=%s %s ===\n' "$rc" "$(date -Is)" >> "$OUT/exp59.done"
exit "$rc"
