#!/bin/bash
# P6-MASON pt1 H-d — 3090 dual card: pt1 mask-ON with edge_threshold=2.0 (strong-edge only).
# Tests low-texture-pixel drag hypothesis (user line/edge insight). Pure config, 3-seed.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P6/P6-MASON-pt1Hd
mkdir -p "$OUT"
DONE="$OUT/pt1hd.done"

RUNS="pt1_edge2:0 pt1_edge2:1 pt1_edge2:2"
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
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p6_mason/pt1_edgethresh/p6_mason_pt1_edge2.yaml \
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
echo "PT1HD_ALL_DONE missing=$missing" >> "$DONE"
