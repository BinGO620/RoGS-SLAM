#!/bin/bash
# exp38 -- f3_wk_xyz F seed0 第三轮复跑 + MAXJOBS=4
#
# F seed0 的 within-config 极差 6.02 cm (19.99 vs 26.02) 异常大
# 再跑一次看是否可复现，同时测试 MAXJOBS=4 的可行性
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_trackside_f3w_rerun_seed0.sh > results/runs/trackside_f3w_rerun.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/PBA}; mkdir -p "$OUT"
DONE="$OUT/trackside_f3w_rerun.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-4}
SEQ=f3_wk_xyz
ARM=pba_trackside_hard
seed=0

cfg="configs/rgbd/experiments/pba_ba_coupling/${ARM}_${SEQ}.yaml"
outnm="${ARM}_${SEQ}_seed${seed}"
dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
n=$(ls "$dp"/flow_raft/*.npy 2>/dev/null | wc -l)
echo "$(date +%F' '%H:%M) LAUNCH rerun $outnm maxjobs=$MAXJOBS flow=$n" >> "$DONE"

SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

wait_slot
gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
      | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
echo "$(date +%H:%M) RUN $outnm (rerun) on gpu$gpu" >> "$DONE"
env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
  $PY slam.py --config "$cfg" --fast --seed "$seed" \
  --results-root "$OUT/$outnm" > /dev/null 2>&1 &

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done

rows=$(PYTHONPATH=$PWD $PY -c "
import csv,os
p='$OUT/$outnm/tables/tracking_raw.csv'
with open(p) as f: print(sum(1 for _ in csv.DictReader(f)))
" 2>/dev/null)
echo "$(date +%H:%M) DONE $outnm total_rows=$rows" >> "$DONE"

# 打印所有 ATE
echo "=== ALL ATE ===" >> "$DONE"
PYTHONPATH=$PWD $PY -c "
import csv
for arm in ['pba_trackside_only','pba_trackside_hard']:
    print(f'  {arm}:')
    for s in range(3):
        p=f'$OUT/${arm}_${SEQ}_seed{s}/tables/tracking_raw.csv'
        try:
            rows=list(csv.DictReader(open(p)))
            ates=[r['ate_rmse_cm'] for r in rows]
            print(f'    seed{s}: {ates}')
        except: pass
" >> "$DONE" 2>&1
