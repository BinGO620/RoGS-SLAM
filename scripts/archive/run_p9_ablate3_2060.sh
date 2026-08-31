#!/bin/bash
# run_p9_static_ablate_2060.sh — P9 静态崩溃机制消融，2060 串行（判据 p9_static_ablate_prereg.md）
# 用法: nohup bash scripts/run_p9_static_ablate_2060.sh > results/runs/P9/master_2060.log 2>&1 &
set -u
REPO=/data/monogs-ours; cd "$REPO"
PY=$(conda run -n monogs-ours which python 2>/dev/null | tail -1)
[ -x "$PY" ] || { echo "ABORT: 解析不到 python"; exit 1; }
OUT=results/runs/P9/P9-ABLATE3-2060
mkdir -p "$OUT"; DONE="$OUT/ablate.done"; : > "$DONE"
MAX_PARALLEL=1
# 头号嫌疑排最前，vanilla 锚点次之
RUNS="vanilla:4 bothoff:4"

FLOW=/data/Datasets/TUM/rgbd_dataset_freiburg3_sitting_halfsphere/flow_raft
n=$(ls "$FLOW"/*.npy 2>/dev/null | wc -l); echo "precheck flow_npy=$n" >> "$DONE"
[ "$n" -ge 10 ] || { echo "ABORT: flow 不全($n)" >> "$DONE"; exit 1; }

running_slam() { pgrep -af 'slam\.py' 2>/dev/null | grep -cE '/python[0-9]* +slam\.py' || true; }
wait_slot() { while [ "$(running_slam)" -ge "$MAX_PARALLEL" ]; do sleep 20; done; }
pick_gpu() { nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits \
    | awk -F, '{w=$2+($3*100); if(NR==1||w<best){best=w; g=$1}} END{print g}' | tr -d ' '; }

i=0
for entry in $RUNS; do
  arm="${entry%%:*}"; seed="${entry##*:}"; outnm="f3_st_hf_${arm}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm" >> "$DONE"; continue; }
  wait_slot
  gpu=0
  log="$OUT/$outnm.$(date +%Y%m%d-%H%M%S).consolelog"
  echo "$(date +%H:%M) RUN $outnm gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0 \
    "$PY" slam.py --config "configs/rgbd/experiments/p9_static_ablate/p9_${arm}_f3_st_hf.yaml" \
    --seed "$seed" --results-root "$OUT/$outnm" > "$log" 2>&1 &
  sleep 3    # 让上一个先占住显存，避免选卡时两个挤同一张（exp26 踩过）
done
while [ "$(running_slam)" -gt 0 ]; do sleep 30; done
missing=0
for entry in $RUNS; do
  arm="${entry%%:*}"; seed="${entry##*:}"; outnm="f3_st_hf_${arm}_seed${seed}"
  c="$OUT/$outnm/tables/tracking_raw.csv"
  if [ ! -f "$c" ]; then echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1))
  else echo "DONE $outnm ATE=$(python3 -c "import csv,sys;r=list(csv.DictReader(open(sys.argv[1])));print(r[0]['ate_rmse_cm'] if r else 'NA')" "$c" 2>/dev/null)" >> "$DONE"; fi
done
echo "P9C_2060_ALL_DONE $(date) missing=$missing" >> "$DONE"
