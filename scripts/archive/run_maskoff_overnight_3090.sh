#!/bin/bash
# Re-runnable overnight 3090 batch for the mask-free bundle headline.
# Fills 2×RTX3090, 2 concurrent, skips completed, writes full_overnight.done.
# Relies on the REMOTE dataset symlinks being retargeted to /mnt/app/datasets/Bonn/<seq>
# (see next-session prompt: after any rsync, retarget datasets/bonn/rgbd_* to /mnt/app/datasets).
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P6/P6-MASKOFF-3SEED; mkdir -p "$OUT"
DONE="$OUT/full_overnight.done"
RUNS="balloon2:1 balloon2:2 mv_no_box2:0 mv_no_box2:1 mv_no_box2:2 pt1:0 pt1:1 pt1:2"
wait_slot(){ while [ "$(pgrep -c -f slam.py 2>/dev/null || echo 0)" -ge 2 ]; do sleep 20; done; }
: > "$DONE"
for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"; outnm="${seq}_maskoff_seed${seed}"
  [ -d "$OUT/$outnm" ] && echo "SKIP $outnm (exists)" && echo "$outnm SKIP" >> "$DONE" && continue
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p6_maskoff/p6_maskoff_prune_${seq}.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm DONE($(date +%H:%M))" >> "$DONE"; sleep 3
done
while [ "$(pgrep -c -f slam.py 2>/dev/null || echo 0)" -gt 0 ]; do sleep 30; done
echo "ALL_DONE $(date)" >> "$DONE"
