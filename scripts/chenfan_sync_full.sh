#!/bin/bash
# chenfan_sync_full.sh — 同步18条主表序列完整数据到chenfan
# 使用rsync的--limit-bytes限制IO，防止服务器死机
# 在cb上执行：nohup bash scripts/chenfan_sync_full.sh > results/runs/chenfan_sync_full.log 2>&1 &
set -u

CF=chenfan@100.72.201.57
CB=cb@100.108.170.66
CF_DATA=/home/chenfan/cron/Datasets
CB_DATA=/data/Datasets

declare -A BONN=( [balloon]=rgbd_bonn_balloon [balloon2]=rgbd_bonn_balloon2 [crowd]=rgbd_bonn_crowd [crowd2]=rgbd_bonn_crowd2 [mv_no_box]=rgbd_bonn_moving_nonobstructing_box [mv_no_box2]=rgbd_bonn_moving_nonobstructing_box2 [pt1]=rgbd_bonn_person_tracking [pt2]=rgbd_bonn_person_tracking2 )
declare -A TUM=( [f1_desk]=rgbd_dataset_freiburg1_desk [f2_xyz]=rgbd_dataset_freiburg2_xyz [f2_person]=rgbd_dataset_freiburg2_desk_with_person [f3_office]=rgbd_dataset_freiburg3_long_office_household [f3_st_hf]=rgbd_dataset_freiburg3_sitting_halfsphere [f3_st_rpy]=rgbd_dataset_freiburg3_sitting_rpy [f3_st_xyz]=rgbd_dataset_freiburg3_sitting_xyz [f3_wk_hf]=rgbd_dataset_freiburg3_walking_halfsphere [f3_wk_rpy]=rgbd_dataset_freiburg3_walking_rpy [f3_wk_xyz]=rgbd_dataset_freiburg3_walking_xyz )

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# 单序列同步：用--limit-bytes限制IO，--partial断点续传
sync_one() {
  local seq_name=$1
  local src_path=$2
  local dst_path=$3

  log "START syncing $seq_name"

  # 在chenfan上执行rsync，使用--bwlimit限制带宽为10MB/s
  ssh "$CF" "
    mkdir -p '$dst_path'
    for attempt in 1 2 3 4 5; do
      echo \"Attempt \$attempt for $seq_name\"
      if rsync -av --partial --bwlimit=10000 '$CB:$src_path/' '$dst_path/'; then
        echo '$seq_name synced successfully'
        break
      else
        echo '$seq_name attempt \$attempt failed, retrying...'
        sleep 10
      fi
    done
  "
  log "DONE  syncing $seq_name"
}

# 同步18条主表序列
log "=== Starting chenfan full sync ==="
log "Sequences: Bonn 8 + TUM 10 = 18 total"

# Bonn序列
for s in balloon balloon2 crowd crowd2 mv_no_box mv_no_box2 pt1 pt2; do
  sync_one "bonn_$s" "/data/Datasets/Bonn/${BONN[$s]}" "$CF_DATA/Bonn/${BONN[$s]}"
done

# TUM序列
for s in f1_desk f2_xyz f2_person f3_office f3_st_hf f3_st_rpy f3_st_xyz f3_wk_hf f3_wk_rpy f3_wk_xyz; do
  sync_one "tum_$s" "/data/Datasets/TUM/${TUM[$s]}" "$CF_DATA/TUM/${TUM[$s]}"
done

log "=== ALL SEQUENCES SYNCED ==="
