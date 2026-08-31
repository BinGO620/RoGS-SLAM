#!/bin/bash
# cb 2060 mask-free 渲染证明：短序列不会OOM
# 目标：证明 mask-free 在短序列上能跑，且渲染质量与 mask-only 可比
set -u
REPO=/data/monogs-ours; cd "$REPO"
PY=/data/conda_envs/monogs-ours/bin/python
OUT=results/runs/P11/P11-MASKFREE-PROOF-2060; mkdir -p "$OUT"
DONE="$OUT/proof.done"; : > "$DONE"

# 短序列 mask-free（mask_mapping=false，无Mask R-CNN 开销）
RUNS=(
  "f1_desk:p6_maskoff_prune_f1_desk:0:desk_maskfree"
  "f1_desk:wpm_f1_desk_maskonly:0:desk_maskonly"
  "f1_desk:p5_vanilla_prune_f1_desk:0:desk_vanilla"
  "f3_office:p6_maskoff_prune_f3_office:0:office_maskfree"
  "f3_office:wpm_f3_office_maskonly:0:office_maskonly"
  "balloon:p6_maskoff_prune_balloon:0:balloon_maskfree"
  "balloon:wpm_balloon_maskonly:0:balloon_maskonly"
  "mv_no_box:p6_maskoff_prune_mv_no_box:0:mvno_maskfree"
  "mv_no_box:wpm_mv_no_box_maskonly:0:mvno_maskonly"
)

SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge 2 ]; do sleep 20; done; }  # 2060 只跑2个

for entry in "${RUNS[@]}"; do
  IFS=: read seq cfg seed label <<< "$entry"
  outnm="${label}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm" >> "$DONE"; continue; }
  cfgpath=$(find configs/rgbd/experiments -name "${cfg}.yaml" | head -1)
  [ -z "$cfgpath" ] && { echo "ABORT: config not found $cfg" >> "$DONE"; continue; }
  wait_slot
  log="$OUT/$outnm.$(date +%Y%m%d-%H%M%S).consolelog"
  echo "$(date +%H:%M) RUN $outnm" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0 \
    $PY slam.py --config "$cfgpath" \
    --seed "$seed" --results-root "$OUT/$outnm" > "$log" 2>&1 &
  sleep 30
done
while [ "$(slam_count)" -gt 0 ]; do sleep 30; done
echo "PROOF_DONE $(date)" >> "$DONE"
