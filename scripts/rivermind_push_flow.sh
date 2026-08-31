#!/bin/bash
# rivermind_push_flow.sh — 从 cb 推送 18 条序列的 flow_raft 到 rivermind
# 在 cb 上执行（cb→rivermind 2.3MB/s，27G 约 3 小时）
# 用 --partial 断点续传 + 重试，tmux 后台跑不怕断线
set -u
RM="root@sc01-ssh.gpuhome.cc"
PORT=30627
RMD=/root/rivermind-data/datasets

BONN="rgbd_bonn_balloon rgbd_bonn_balloon2 rgbd_bonn_crowd rgbd_bonn_crowd2 \
rgbd_bonn_moving_nonobstructing_box rgbd_bonn_moving_nonobstructing_box2 \
rgbd_bonn_person_tracking rgbd_bonn_person_tracking2"

TUM="rgbd_dataset_freiburg1_desk rgbd_dataset_freiburg2_xyz rgbd_dataset_freiburg2_desk_with_person \
rgbd_dataset_freiburg3_long_office_household rgbd_dataset_freiburg3_sitting_halfsphere \
rgbd_dataset_freiburg3_sitting_rpy rgbd_dataset_freiburg3_sitting_xyz \
rgbd_dataset_freiburg3_walking_halfsphere rgbd_dataset_freiburg3_walking_rpy \
rgbd_dataset_freiburg3_walking_xyz"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

push_one() {
  local cat=$1 seq=$2
  local src="/data/Datasets/$cat/$seq/flow_raft/"
  local dst="$RMD/$cat/$seq/flow_raft/"
  [ -d "$src" ] || { log "SKIP $seq (cb无flow)"; return; }
  log "START $cat/$seq ($(du -sh $src | cut -f1))"
  ssh -p $PORT "$RM" "mkdir -p '$dst'" 2>/dev/null
  for attempt in 1 2 3 4 5 6; do
    if rsync -a --partial -e "ssh -p $PORT" "$src" "$RM:$dst"; then
      log "DONE  $cat/$seq"; return
    fi
    log "  retry $attempt for $seq"; sleep 5
  done
  log "FAIL  $cat/$seq (6次重试均失败)"
}

for s in $BONN; do push_one Bonn "$s"; done
for s in $TUM;  do push_one TUM  "$s"; done

log "=== ALL DONE ==="
