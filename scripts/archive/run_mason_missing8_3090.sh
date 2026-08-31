#!/bin/bash
# Complete the missing 8 combined(mask-ON) sequences for the 18-seq table.
# 8 seq x 3 seeds = 24 self-tracked SLAM runs on dual 3090.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P6/P6-MASON-8SEQ
mkdir -p "$OUT"
DONE="$OUT/missing8.done"
: > "$DONE"
RUNS="f1_desk:0 f1_desk:1 f1_desk:2 f2_xyz:0 f2_xyz:1 f2_xyz:2 f2_person:0 f2_person:1 f2_person:2 f3_office:0 f3_office:1 f3_office:2 f3_st_hf:0 f3_st_hf:1 f3_st_hf:2 f3_st_rpy:0 f3_st_rpy:1 f3_st_rpy:2 f3_st_xyz:0 f3_st_xyz:1 f3_st_xyz:2 f3_wk_hf:0 f3_wk_hf:1 f3_wk_hf:2"
running_slam() { pgrep -af 'slam.py --config' 2>/dev/null | grep -E '/python[0-9]* ( |$)?slam.py' | wc -l; }
wait_idle() { while [ "$(running_slam)" -ge 2 ]; do sleep 20; done; }
i=0
for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"; outnm="${seq}_combined_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm" >> "$DONE"; continue; }
  wait_idle
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p6_mason/p6_mason_combined_${seq}.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1 &
  i=$((i+1)); sleep 3
done
while [ "$(running_slam)" -gt 0 ]; do sleep 30; done
missing=0
for entry in $RUNS; do seq="${entry%%:*}"; seed="${entry##*:}"; outnm="${seq}_combined_seed${seed}"; [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }; done
echo "ALL_DONE $(date) missing=$missing" >> "$DONE"
