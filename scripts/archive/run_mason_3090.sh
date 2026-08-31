#!/bin/bash
# P6-MASON — fill 3090 dual card with mask-ON discriminator batch.
# Question: does adding the semantic mask (combined mask-ON) bring the mask-off
# weak seqs (crowd / crowd2 / f3_wk_rpy / f3_wk_xyz) into the RGD/DG competitive band?
# Re-verifies pt1 combined (mask-ON stable) as control.
#
# Runs 2 concurrent (one per GPU). Writes results/runs/P6/P6-MASON/mason.done on completion,
# and a per-seq SKIP row if the run already produced a tracking table.
#
# Sets TRACEBACK: if any slam run dies with a non-zero exit, its consolelog tail is printed.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P6/P6-MASON
mkdir -p "$OUT"
DONE="$OUT/mason.done"

# 5 seqs × 3 seed. (All are mask-ON combined; the 6 BONN mask-ON runs already exist in P2-T_3090.)
RUNS="crowd:0 crowd:1 crowd:2 crowd2:0 crowd2:1 crowd2:2 f3_wk_rpy:0 f3_wk_rpy:1 f3_wk_rpy:2 f3_wk_xyz:0 f3_wk_xyz:1 f3_wk_xyz:2 pt1:0 pt1:1 pt1:2"

launch_one() {
  local seq="$1" seed="$2"
  local outnm="${seq}_combined_seed${seed}"
  # skip if a tracking table already exists
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "SKIP $outnm (has tracking)"
    echo "$outnm SKIP" >> "$DONE"
    return 0
  fi
  # pick the card with the LOWEST relative load; if tied, alternate via a counter
  local gpu n_cards
  gpu=$(nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits \
        | awk -F, '{idx=$1; w=$2+($3*100); if(w<best||NR==1){best=w; gidx=$1}} END{print gidx}' | tr -d ' ')
  # empty (no cards) -> fall back to a round-robin slot
  n_cards=$(nvidia-smi -L 2>/dev/null | wc -l)
  if [ -z "$gpu" ] || [ "${n_cards:-0}" = "0" ]; then
    gpu=$((MATSON_i % 2))
  fi
  MATSON_i=$((MATSON_i + 1))
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p6_mason/p6_mason_combined_${seq}.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED" >> "$DONE"
  sleep 3
}

# Tail-of-batch: capture any crash via the consolelog `Traceback` marker.
# Count ONLY python slam.py processes (exclude the launcher's own bash wrapper,
# which also contains 'slam.py --config' in its argv).
running_slam() {
  pgrep -af 'slam.py --config' 2>/dev/null \
    | grep -E '/python[0-9]* ( |$)?slam.py' \
    | wc -l
}
# round-robin tie-break counter (declared up-front, since `set -u` + local inside
# a function makes the first `MATSON_i + 1` unbound unless initialised outside)
MATSON_i=${MATSON_i:-0}
wait_idle() {
  while [ "$(running_slam)" -ge 2 ]; do
    sleep 20
  done
}

: > "$DONE"
for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"
  wait_idle
  launch_one "$seq" "$seed"
done
# wait for ALL to finish
while [ "$(running_slam)" -gt 0 ]; do sleep 30; done
# final sweep: confirm each run has a tracking table; if missing, show consolelog tail
missing=0
for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"
  outnm="${seq}_combined_seed${seed}"
  if [ ! -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "MISSING $outnm" >> "$DONE"
    missing=$((missing+1))
    echo "=== tail $outnm.consolelog (last 40) ==="
    tail -40 "$OUT/$outnm.consolelog" 2>/dev/null
  fi
done
echo "MASON_ALL_DONE missing=$missing $(date +%H:%M)"
echo "MASON_ALL_DONE missing=$missing" >> "$DONE"
