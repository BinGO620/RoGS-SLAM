#!/bin/bash
# E-factorial: pt1 B arm (edge3+full hard) + C arm (edge3+erode3) × 3 seed.
# A arm (edge3 alone) already exists (9.16). Discriminator for boundary-band vs full-hard.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P6/P6-EFACT; mkdir -p "$OUT"; DONE="$OUT/efact.done"
RUNS="edge3_hardmask:0 edge3_hardmask:1 edge3_hardmask:2 erode3_band:0 erode3_band:1 erode3_band:2"
MATSON_i=${MATSON_i:-0}
running_slam(){ pgrep -af 'slam.py --config' 2>/dev/null | grep -E '/python[0-9]* ( |$)?slam.py' | wc -l; }
wait_idle(){ while [ "$(running_slam)" -ge 2 ]; do sleep 20; done; }
: > "$DONE"
declare -A CFG=( [edge3_hardmask]=p6_mason_pt1_edge3_hardmask.yaml [erode3_band]=p6_mason_pt1_erode3_band.yaml )
for spec in $RUNS; do
  key="${spec%%:*}"; seed="${spec##*:}"; outnm="${key}_seed${seed}"
  wait_idle
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm"; echo "$outnm SKIP" >> "$DONE"; continue; }
  gpu=$(nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits | awk -F, '{w=$2+($3*100); if(w<best||NR==1){best=w;g=$1}} END{print g}')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p6_mason/pt1_ebranch/${CFG[$key]} \
    --seed "$seed" --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED" >> "$DONE"; sleep 3
done
while [ "$(running_slam)" -gt 0 ]; do sleep 30; done
missing=0
for spec in $RUNS; do
  key="${spec%%:*}"; seed="${spec##*:}"; outnm="${key}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
done
echo "EFACT_ALL_DONE missing=$missing" >> "$DONE"
