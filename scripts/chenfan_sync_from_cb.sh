#!/bin/bash
# chenfan_sync_from_cb.sh — 从 cb 全量同步数据集到 chenfan（后台,走 0.85MB/s pull 方向）
# 在 cb 上执行本脚本，实际 rsync 通过 ssh 在 chenfan 上发起（chenfan→cb pull）
# 用户已配好 chenfan→cb 免密（ssh cb@100.108.170.66）
#
# 同步范围：
#  A. 18条主表序列全部（图+flow 增量同步）：9 Bonn + 10 TUM（含7条补flow + 11条补图+flow）
#  B. Replica 12G（用户要两台远程数据都齐）
set -e
CB=cb@100.108.170.66
CF=/home/chenfan/cron/Datasets

# 目标目录（chenfan 已有结构）
declare -A BONN=( [balloon]=rgbd_bonn_balloon [balloon2]=rgbd_bonn_balloon2 [crowd]=rgbd_bonn_crowd [crowd2]=rgbd_bonn_crowd2 [mv_no_box]=rgbd_bonn_moving_nonobstructing_box [mv_no_box2]=rgbd_bonn_moving_nonobstructing_box2 [pt1]=rgbd_bonn_person_tracking [pt2]=rgbd_bonn_person_tracking2 )
declare -A TUM=( [f1_desk]=rgbd_dataset_freiburg1_desk [f2_xyz]=rgbd_dataset_freiburg2_xyz [f2_person]=rgbd_dataset_freiburg2_desk_with_person [f3_office]=rgbd_dataset_freiburg3_long_office_household [f3_st_hf]=rgbd_dataset_freiburg3_sitting_halfsphere [f3_st_rpy]=rgbd_dataset_freiburg3_sitting_rpy [f3_st_xyz]=rgbd_dataset_freiburg3_sitting_xyz [f3_wk_hf]=rgbd_dataset_freiburg3_walking_halfsphere [f3_wk_rpy]=rgbd_dataset_freiburg3_walking_rpy [f3_wk_xyz]=rgbd_dataset_freiburg3_walking_xyz )

log() { echo "[$(date '+%H:%M:%S')] $*"; }
sync_one() {
  # 在 chenfan 上 rsync cb 的序列目录 → 本地
  local src=$1 dst=$2 name=$3
  log "START $name"
  ssh chenfan@100.72.201.57 "rsync -a --partial --delete $CB:$src/ $dst/"
  log "DONE  $name"
}

# Bonn 8条
for s in balloon balloon2 crowd crowd2 mv_no_box mv_no_box2 pt1 pt2; do
  sync_one "/data/Datasets/Bonn/${BONN[$s]}" "$CF/Bonn/${BONN[$s]}" "bonn_$s"
done
# TUM 10条
for s in f1_desk f2_xyz f2_person f3_office f3_st_hf f3_st_rpy f3_st_xyz f3_wk_hf f3_wk_rpy f3_wk_xyz; do
  sync_one "/data/Datasets/TUM/${TUM[$s]}" "$CF/TUM/${TUM[$s]}" "tum_$s"
done
# Replica
sync_one "/data/Datasets/Replica" "$CF/Replica" "replica"

echo "=== ALL DONE ==="
