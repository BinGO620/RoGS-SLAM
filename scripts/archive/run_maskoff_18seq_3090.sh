#!/bin/bash
# Fills 3090 dual card with the full 18-sequence maskoff batch (mask-free bundle main table,
# aligned to the baseline 18-seq set that RGD/DG/MonoGS etc. were measured on).
# Already-completed 6 BONN (balloon/balloon2/mv_no_box/mv_no_box2/pt1/pt2) are skipped.
# New 12-seq batch = crowd/crowd2 + f1_desk/f2_xyz/f2_person/f3_office/f3_st_{hf,rpy,xyz}/f3_wk_{hf,rpy,xyz}.
# Runs 2 concurrent (one per GPU). Writes P6-MASKOFF-3SEED/full_18seq.done on completion.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P6/P6-18SEQ
mkdir -p "$OUT"
DONE="$OUT/full_18seq.done"

# 12 new seqs × 3 seed. (6 BONN already done under P6-MASKOFF-3SEED.)
RUNS="crowd:0 crowd:1 crowd:2 crowd2:0 crowd2:1 crowd2:2 f1_desk:0 f1_desk:1 f1_desk:2 f2_xyz:0 f2_xyz:1 f2_xyz:2 f2_person:0 f2_person:1 f2_person:2 f3_office:0 f3_office:1 f3_office:2 f3_st_hf:0 f3_st_hf:1 f3_st_hf:2 f3_st_rpy:0 f3_st_rpy:1 f3_st_rpy:2 f3_st_xyz:0 f3_st_xyz:1 f3_st_xyz:2 f3_wk_hf:0 f3_wk_hf:1 f3_wk_hf:2 f3_wk_rpy:0 f3_wk_rpy:1 f3_wk_rpy:2 f3_wk_xyz:0 f3_wk_xyz:1 f3_wk_xyz:2"

wait_slot() {
  # NOTE: pgrep -f 'slam.py' also matches the bash -c wrapper that launched these,
  # so counting EVERY match is unreliable. Count precisely the running slam.py --config
  # python processes instead (exclude the bash wrappers).
  while [ "$(pgrep -fc 'slam.py --config' 2>/dev/null || echo 0)" -ge 2 ]; do
    sleep 20
  done
}

: > "$DONE"
for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"
  outnm="${seq}_maskoff_seed${seed}"
  # skip if the run already produced a final tracking table (not just any dir)
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "SKIP $outnm (has tracking)"
    echo "$outnm SKIP" >> "$DONE"
    continue
  fi
  wait_slot
  # pick the card with the LOWEST absolute memory load (not most-recently-used)
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p6_maskoff/p6_maskoff_prune_${seq}.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1 &
  # record as queued (DONE marker written on launch; actual tracking verified later)
  echo "$outnm QUEUED($(date +%H:%M))" >> "$DONE"
  sleep 3
done
while [ "$(pgrep -fc 'slam.py --config' 2>/dev/null || echo 0)" -gt 0 ]; do sleep 30; done
# final sweep: confirm every queued run has a tracking table
missing=0
for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"
  outnm="${seq}_maskoff_seed${seed}"
  if [ ! -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "MISSING $outnm" >> "$DONE"
    missing=$((missing+1))
  fi
done
echo "ALL_DONE $(date) missing=$missing" >> "$DONE"
