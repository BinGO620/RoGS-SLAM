#!/bin/bash
# chenfan_pull_from_cb.sh — chenfan 后台全量同步数据集（从 cb pull, 走快方向 0.85MB/s）
# 通过 ssh 在 chenfan 上发起 rsync（chenfan 持 key 连 cb），每条序列做成独立后台任务，
# 用 --partial 断点续传 + 重试，确保在慢/不稳链路上最终传完，不因单次超时中断。
#
# 在 cb 上执行：
#   nohup bash scripts/chenfan_pull_from_cb.sh > results/runs/chenfan_sync.log 2>&1 &
#
# 同步范围：18 条主表序列（Bonn 8 + TUM 10）图+flow 全量。
# 不传 Replica（它不在 18 序列主表内，用户确认不需要）。
# 进度核对：登录 chenfan 数各目录 png/flow 数量与 cb 一致。
set -u
CF=chenfan@100.72.201.57
CB=cb@100.108.170.66
CF_DATA=/home/chenfan/cron/Datasets

declare -A BONN=( [balloon]=rgbd_bonn_balloon [balloon2]=rgbd_bonn_balloon2 [crowd]=rgbd_bonn_crowd [crowd2]=rgbd_bonn_crowd2 [mv_no_box]=rgbd_bonn_moving_nonobstructing_box [mv_no_box2]=rgbd_bonn_moving_nonobstructing_box2 [pt1]=rgbd_bonn_person_tracking [pt2]=rgbd_bonn_person_tracking2 )
declare -A TUM=( [f1_desk]=rgbd_dataset_freiburg1_desk [f2_xyz]=rgbd_dataset_freiburg2_xyz [f2_person]=rgbd_dataset_freiburg2_desk_with_person [f3_office]=rgbd_dataset_freiburg3_long_office_household [f3_st_hf]=rgbd_dataset_freiburg3_sitting_halfsphere [f3_st_rpy]=rgbd_dataset_freiburg3_sitting_rpy [f3_st_xyz]=rgbd_dataset_freiburg3_sitting_xyz [f3_wk_hf]=rgbd_dataset_freiburg3_walking_halfsphere [f3_wk_rpy]=rgbd_dataset_freiburg3_walking_rpy [f3_wk_xyz]=rgbd_dataset_freiburg3_walking_xyz )

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# chenfan 上用 --partial 单序列 rsync，内部重试直到完成（--partial 断点续传）
pull_one() {
  local src=$1 dst=$2 name=$3
  log "START $name ($src)"
  ssh "$CF" "
    mkdir -p '$dst'
    for attempt in 1 2 3 4 5 6 7 8; do
      if rsync -a --partial '$CB:$src/' '$dst/'; then
        break
      else
        echo \"$name attempt \\\$attempt retry\"
        sleep 5
      fi
    done
  "
  log "DONE  $name"
}

for s in balloon balloon2 crowd crowd2 mv_no_box mv_no_box2 pt1 pt2; do
  pull_one "/data/Datasets/Bonn/${BONN[$s]}" "$CF_DATA/Bonn/${BONN[$s]}" "bonn_$s"
done
for s in f1_desk f2_xyz f2_person f3_office f3_st_hf f3_st_rpy f3_st_xyz f3_wk_hf f3_wk_rpy f3_wk_xyz; do
  pull_one "/data/Datasets/TUM/${TUM[$s]}" "$CF_DATA/TUM/${TUM[$s]}" "tum_$s"
done

echo "=== ALL DONE ==="
