#!/bin/bash
# 渲染基线对照：balloon/mv_no_box × vanilla/mask-only/combined × seed0
# 目标：证明 mask_mapping 消除 ghosting（PSNR/SSIM 定量 + 定性图）
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/RENDER-BASELINE-3090; mkdir -p "$OUT"
DONE="$OUT/render_baseline.done"; : > "$DONE"

RUNS=(
  "balloon:p5_vanilla_prune_balloon"
  "balloon:wpm_balloon_maskonly"
  "balloon:p6_mason_combined_balloon"
  "mv_no_box:p5_vanilla_prune_mv_no_box"
  "mv_no_box:wpm_mv_no_box_maskonly"
  "mv_no_box:p6_mason_combined_mv_no_box"
)

SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge 2 ]; do sleep 20; done; }

for entry in "${RUNS[@]}"; do
  seq="${entry%%:*}"; cfg="${entry##*:}"
  outnm="${seq}_${cfg##*_}_seed0"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm" >> "$DONE"; continue; }
  
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
  
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config "configs/rgbd/experiments/${cfg%_*}/${cfg}.yaml" \
    --seed 0 --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1 &
  sleep 5
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done
echo "RENDER_BASELINE_DONE $(date)" >> "$DONE"
