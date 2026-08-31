#!/bin/bash
# chenfan 渲染基线：3序列×4臂 seed0（含 mask-free，证明"人有鬼影/物无鬼影"）
# 三类代表性：f2_person（纯人）/ balloon（人+物）/ mv_no_box（纯物）
set -u
REPO=/home/chenfan/cron/monogs-ours; cd "$REPO"
PY=$(source /home/chenfan/miniconda3/etc/profile.d/conda.sh && conda activate monogs-ours && which python 2>/dev/null | tail -1)
[ -x "$PY" ] || { echo "ABORT: python"; exit 1; }
OUT=results/runs/RENDER-CHENFAN-3090; mkdir -p "$OUT"
DONE="$OUT/render.done"; : > "$DONE"

# 3序列 × 4臂 = 12 run
# f2_person（纯人）: Mask R-CNN 精准 → mask-only 应该最干净
# balloon（人+气球混合）: Mask R-CNN 漏气球 → mask-free 的 reliability 应该捕捉到气球运动
# mv_no_box（纯物）: Mask R-CNN 无词表 → mask-free 的 reliability 是唯一解
RUNS=(
  "f2_person:p5_vanilla_prune_f2_person:vanilla"
  "f2_person:wpm_f2_person_maskonly:maskonly"
  "f2_person:p6_mason_combined_f2_person:combined"
  "f2_person:p6_mason_combined_f2_person:maskfree"
  "balloon:p5_vanilla_prune_balloon:vanilla"
  "balloon:wpm_balloon_maskonly:maskonly"
  "balloon:p6_mason_combined_balloon:combined"
  "balloon:p6_mason_combined_balloon:maskfree"
  "mv_no_box:p5_vanilla_prune_mv_no_box:vanilla"
  "mv_no_box:wpm_mv_no_box_maskonly:maskonly"
  "mv_no_box:p6_mason_combined_mv_no_box:combined"
  "mv_no_box:p6_mason_combined_mv_no_box:maskfree"
)

# mask-free 需要额外配置（关掉 mask_mapping 和 mask_insertion）
cat > /tmp/method_maskfree_overlay.yaml <<'EOF'
# mask-free overlay: 关掉所有 mask 相关，只保留 reliability + kernel
SemanticMask:
  mask_mapping: false
  mask_insertion: false
EOF

SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge 4 ]; do sleep 20; done; }

# 先检查数据完整性
echo "=== 数据 precheck ===" >> "$DONE"
for seq in f2_person balloon mv_no_box; do
  case $seq in
    f2_person) base=tum/rgbd_dataset_freiburg2_desk_with_person;;
    balloon) base=bonn/rgbd_bonn_balloon;;
    mv_no_box) base=bonn/rgbd_bonn_moving_nonobstructing_box;;
  esac
  n_flow=$(ls "$base/flow_raft"/*.npy 2>/dev/null | wc -l)
  echo "$seq: flow=$n_flow" >> "$DONE"
  [ "$n_flow" -ge 10 ] || { echo "ABORT: $seq flow 不全"; exit 1; }
done

for entry in "${RUNS[@]}"; do
  IFS=: read seq cfg arm <<< "$entry"
  outnm="${seq}_${arm}_seed0"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm" >> "$DONE"; continue; }
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
  
  # mask-free 用 overlay 修改配置
  if [ "$arm" = "maskfree" ]; then
    EXTRA="--method_from /tmp/method_maskfree_overlay.yaml"
  else
    EXTRA=""
  fi
  
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config "configs/rgbd/experiments/${cfg%_*}/${cfg}.yaml" \
    --seed 0 --results-root "$OUT/$outnm" $EXTRA \
    > "$OUT/$outnm.consolelog" 2>&1 &
  sleep 5
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done
echo "RENDER_DONE $(date)" >> "$DONE"
