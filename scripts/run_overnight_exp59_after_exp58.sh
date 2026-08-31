#!/bin/bash
# Overnight chain: wait for EXP58 to finish, build flow for 6 new BONN sequences,
# then run EXP59 (boundary band validation, 36 runs).
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
cd "$REPO"

echo "[night] $(date -Is) waiting for EXP58 to finish ..."
while pgrep -f run_exp58_kernel_extension > /dev/null; do sleep 120; done
echo "[night] $(date -Is) EXP58 done; building flow for 6 new sequences"

SEQS="crowd3 kidnapping_box kidnapping_box2 balloon_tracking balloon_tracking2 placing_nonobstructing_box"
for s in $SEQS; do
  dir="datasets/bonn/rgbd_bonn_${s}"
  if [ -d "$dir/flow_raft" ] && [ "$(ls $dir/flow_raft 2>/dev/null | wc -l)" -gt 10 ]; then
    echo "[night] $s flow already present, skip"
    continue
  fi
  echo "[night] $(date -Is) building flow: $s"
  CUDA_VISIBLE_DEVICES=0 "$PY" scripts/build_flow_raft.py \
    --sequence-dir "$dir" --variant small --iters 12 --device cuda:0 \
    --config "configs/rgbd/bonn/${s}.yaml" \
    > "results/runs/flow_build_exp59_${s}.log" 2>&1 \
    || echo "[night] WARNING: flow build failed for $s (see log); its runs will fail preflight"
done
echo "[night] $(date -Is) flow build done; launching EXP59"

bash scripts/run_exp59_boundary_validation_3090.sh
echo "[night] $(date -Is) EXP59 finished; night complete"
