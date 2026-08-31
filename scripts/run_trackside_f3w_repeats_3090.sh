#!/bin/bash
# exp38 -- f3_wk_xyz within-config 复跑：给 E 和 F 各补一轮，买 ATE 地板
#
# Phase 2（6 run，3090 ~1.5h）：E×3seed + F×3seed 各 1 run 复跑
# tracking_raw.csv 会累积行（同 --results-root 再跑一次 ⇒ 新时间戳目录 + CSV 追加）
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_trackside_f3w_repeats_3090.sh > results/runs/trackside_f3w_repeats.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/PBA}; mkdir -p "$OUT"
DONE="$OUT/trackside_f3w_repeats.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-2}
SEQ=f3_wk_xyz
SEEDS=${SEEDS:-"0 1 2"}

# 臂列表：E trackside + F trackhard
declare -A ARMS
ARMS[E_trackside]=pba_trackside_only
ARMS[F_trackhard]=pba_trackside_hard

# ---- precheck ----
for arm_name in E_trackside F_trackhard; do
  prefix=${ARMS[$arm_name]}
  cfg="configs/rgbd/experiments/pba_ba_coupling/${prefix}_${SEQ}.yaml"
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
  dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
  [ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: $arm_name 数据缺 ($dp)" >> "$DONE"; exit 1; }
  n=$(ls "$dp"/flow_raft/*.npy 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] || { echo "ABORT: $arm_name flow_raft 空" >> "$DONE"; exit 1; }
  echo "precheck OK $arm_name flow=$n" >> "$DONE"
done
echo "$(date +%F' '%H:%M) LAUNCH repeats seq=$SEQ seeds=[$SEEDS] maxjobs=$MAXJOBS" >> "$DONE"

# pgrep 锚定 argv 起始
SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

for arm_name in E_trackside F_trackhard; do
  prefix=${ARMS[$arm_name]}
  cfg="configs/rgbd/experiments/pba_ba_coupling/${prefix}_${SEQ}.yaml"
  for seed in $SEEDS; do
    outnm="${prefix}_${SEQ}_seed${seed}"
    # 检查当前已有几行（不含 header）
    rows=$(PYTHONPATH=$PWD $PY -c "
import csv,sys,os
p='$OUT/$outnm/tables/tracking_raw.csv'
if not os.path.isfile(p): print(0); sys.exit()
with open(p) as f: print(sum(1 for _ in csv.DictReader(f)))
" 2>/dev/null || echo 0)
    if [ "$rows" -ge 2 ]; then
      echo "SKIP $outnm (already $rows runs)" >> "$DONE"
      continue
    fi
    echo "NEED REPEAT $outnm (currently $rows runs)" >> "$DONE"
  done
done

for arm_name in E_trackside F_trackhard; do
  prefix=${ARMS[$arm_name]}
  cfg="configs/rgbd/experiments/pba_ba_coupling/${prefix}_${SEQ}.yaml"
  for seed in $SEEDS; do
    outnm="${prefix}_${SEQ}_seed${seed}"
    rows=$(PYTHONPATH=$PWD $PY -c "
import csv,sys,os
p='$OUT/$outnm/tables/tracking_raw.csv'
if not os.path.isfile(p): print(0); sys.exit()
with open(p) as f: print(sum(1 for _ in csv.DictReader(f)))
" 2>/dev/null || echo 0)
    [ "$rows" -ge 2 ] && continue
    wait_slot
    gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
          | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
    echo "$(date +%H:%M) RUN $outnm (repeat) on gpu$gpu" >> "$DONE"
    env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
      $PY slam.py --config "$cfg" --fast --seed "$seed" \
      --results-root "$OUT/$outnm" > /dev/null 2>&1 &
    sleep 6
  done
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done

echo "TRACKSIDE_F3W_REPEATS_DONE $(date)" >> "$DONE"
