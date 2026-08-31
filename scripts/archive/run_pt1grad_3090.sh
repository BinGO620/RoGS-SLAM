#!/bin/bash
# P6-MASON pt1 H-d gradient: edge_threshold 3.0 and 5.0 (strong-edge only), 3090 dual card.
# Extends edge=2.0 (mean 9.53): does keeping only the STRONGEST edges / room lines push
# pt1 closer to RGD 7.2? If it plateaus, the residual is the person's strong edges (H-e:
# hard semantic exclusion needs to drop those), which would require a core change.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P6/P6-MASON-grad
mkdir -p "$OUT"
DONE="$OUT/grad.done"

RUNS="pt1_edge3:0 pt1_edge3:1 pt1_edge3:2 pt1_edge5:0 pt1_edge5:1 pt1_edge5:2"
MATSON_i=${MATSON_i:-0}
running_slam() {
  pgrep -af 'slam.py --config' 2>/dev/null | grep -E '/python[0-9]* ( |$)?slam.py' | wc -l
}
wait_idle() {
  while [ "$(running_slam)" -ge 2 ]; do sleep 20; done
}
: > "$DONE"
for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"
  outnm="${seq}_seed${seed}"
  wait_idle
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "SKIP $outnm"; echo "$outnm SKIP" >> "$DONE"; continue
  fi
  gpu=$(nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits | awk -F, '{w=$2+($3*100); if(w<best||NR==1){best=w;g=$1}} END{print g}')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu"
  # seq is pt1_edge3 or pt1_edge5
  local_cfg="p6_mason_pt1_${seq#pt1_}.yaml"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p6_mason/pt1_edgethresh/$local_cfg \
    --seed "$seed" --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED" >> "$DONE"; sleep 3
done
while [ "$(running_slam)" -gt 0 ]; do sleep 30; done
missing=0
for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"
  outnm="${seq}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
done
echo "GRAD_ALL_DONE missing=$missing" >> "$DONE"
