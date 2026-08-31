#!/bin/bash
# run_p11_maskonly_2060.sh — P11 sparse-KF mask-only baseline (Option A, exp27 交接)
# 4 seqs × 3 seeds = 12 runs, MAX_PARALLEL=2（与在跑的 P10 共用闸：running_slam 计全部 slam.py）
# 用法: nohup bash scripts/run_p11_maskonly_2060.sh > results/runs/P11/master_2060.log 2>&1 &
set -u
REPO=/data/monogs-ours; cd "$REPO"
PY=$(conda run -n monogs-ours which python 2>/dev/null | tail -1)
[ -x "$PY" ] || { echo "ABORT: 解析不到 python"; exit 1; }
OUT=results/runs/P11/P11-MASKONLY-2060
mkdir -p "$OUT"; DONE="$OUT/p11.done"; : > "$DONE"
MAX_PARALLEL=1   # 每 run 含 Mask R-CNN 实测 ~2.9GB，6GB 两并发已实 OOM (exp28 02:00)；串行
SEQS="f3_st_hf balloon f2_xyz mv_no_box"
SEEDS="0 1 2"

# 数据 precheck（mask-only 不吃 flow，只查数据集目录存在）
for d in /data/Datasets/TUM/rgbd_dataset_freiburg3_sitting_halfsphere \
         /data/Datasets/Bonn/rgbd_bonn_balloon \
         /data/Datasets/TUM/rgbd_dataset_freiburg2_xyz \
         /data/Datasets/Bonn/rgbd_bonn_moving_nonobstructing_box; do
  [ -d "$d" ] || { echo "ABORT: 数据缺 $d" >> "$DONE"; exit 1; }
done
echo "precheck datasets OK" >> "$DONE"

# 计数所有真实 slam 进程（含 conda-run 裸 python argv 的 P10），排除 conda wrapper 双计
running_slam() { pgrep -af 'slam\.py --config' 2>/dev/null | grep -v 'conda run' | grep -cv 'pgrep' || true; }
wait_slot() { while [ "$(running_slam)" -ge "$MAX_PARALLEL" ]; do sleep 20; done; }

for seed in $SEEDS; do
  for seq in $SEQS; do
    outnm="${seq}_p11maskonly_seed${seed}"
    [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm" >> "$DONE"; continue; }
    wait_slot
    log="$OUT/$outnm.$(date +%Y%m%d-%H%M%S).consolelog"
    echo "$(date +%H:%M) RUN $outnm" >> "$DONE"
    env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0 \
      "$PY" slam.py --config "configs/rgbd/experiments/p11_maskonly/p11_maskonly_${seq}.yaml" \
      --seed "$seed" --results-root "$OUT/$outnm" > "$log" 2>&1 &
    sleep 30   # 错峰起跑：让上一个先占住显存/初始化（exp26 踩过挤同卡）
  done
done
while [ "$(running_slam)" -gt 0 ]; do sleep 30; done
missing=0
for seed in $SEEDS; do
  for seq in $SEQS; do
    outnm="${seq}_p11maskonly_seed${seed}"
    c="$OUT/$outnm/tables/tracking_raw.csv"
    if [ ! -f "$c" ]; then echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1))
    else echo "DONE $outnm ATE=$(python3 -c "import csv,sys;r=list(csv.DictReader(open(sys.argv[1])));print(r[0]['ate_rmse_cm'] if r else 'NA')" "$c" 2>/dev/null)" >> "$DONE"; fi
  done
done
echo "P11_2060_ALL_DONE $(date) missing=$missing" >> "$DONE"
