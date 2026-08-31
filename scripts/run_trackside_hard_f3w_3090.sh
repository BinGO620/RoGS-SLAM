#!/bin/bash
# exp38 -- F 臂 f3_wk_xyz：方差-偏置机制在判别序列上是否成立？
#
# Phase 1（3 run，3090 ~30min）：E/F 对比在 f3_wk_xyz 上的 ATE 差异
# 先看 ATE 量级 vs 噪声地板，再决定是否补 seed
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_trackside_hard_f3w_3090.sh > results/runs/trackside_hard_f3w.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/PBA}; mkdir -p "$OUT"
DONE="$OUT/trackside_hard_f3w.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-3}
SEQ=f3_wk_xyz
SEEDS=${SEEDS:-"0 1 2"}
ARM=pba_trackside_hard

# ---- precheck ----
cfg="configs/rgbd/experiments/pba_ba_coupling/${ARM}_${SEQ}.yaml"
[ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
iso=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
c = load_config('$cfg')['SemanticMask']
ok = (c['enabled'] and (not c['mask_mapping']) and (not c['mask_insertion'])
      and c.get('hard_tracking_mask', False))
print('OK' if ok else 'BAD')" 2>/dev/null)
[ "$iso" = "OK" ] || { echo "ABORT: 臂标错 (H-0 = $iso)" >> "$DONE"; exit 1; }
base="configs/rgbd/experiments/pba_ba_coupling/pba_trackside_only_${SEQ}.yaml"
onlydiff=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
a, b = load_config('$cfg'), load_config('$base')
d = []
def walk(x, y, p=''):
    for k in sorted(set(x) | set(y)):
        u, v = x.get(k), y.get(k)
        if isinstance(u, dict) and isinstance(v, dict): walk(u, v, p + k + '.')
        elif u != v: d.append(p + k)
walk(a, b)
print('OK' if sorted(d) == ['SemanticMask.hard_tracking_mask','inherit_from','method'] else ','.join(d))
" 2>/dev/null)
[ "$onlydiff" = "OK" ] || { echo "ABORT: 非单变量 (diff=$onlydiff)" >> "$DONE"; exit 1; }
dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
[ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: 数据缺 ($dp)" >> "$DONE"; exit 1; }
n=$(ls "$dp"/flow_raft/*.npy 2>/dev/null | wc -l)
[ "$n" -gt 0 ] || { echo "ABORT: flow_raft 空 ($dp)" >> "$DONE"; exit 1; }
echo "precheck OK seq=$SEQ H-0=$iso singlevar=$onlydiff flow=$n" >> "$DONE"
echo "$(date +%F' '%H:%M) LAUNCH $ARM seq=$SEQ seeds=[$SEEDS] maxjobs=$MAXJOBS" >> "$DONE"

# pgrep 锚定 argv 起始
SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

for seed in $SEEDS; do
  outnm="${ARM}_${SEQ}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm (done)" >> "$DONE"; continue; }
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config "$cfg" --fast --seed "$seed" \
    --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1 &
  sleep 6
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done

missing=0
for seed in $SEEDS; do
  outnm="${ARM}_${SEQ}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
done

echo "TRACKSIDE_HARD_F3W_DONE $(date) missing=$missing" >> "$DONE"
