#!/bin/bash
# P11 sparse-KF mask-only — 3090 双卡跨机复现臂（exp28, 2026-08-19）。
# 与 2060 主判决同一 12-run 矩阵（4 seq × 3 seed）；2060 = 预注册判决机，
# 3090 = 跨机复现（exp27 证明硬件依赖是真实风险，两机都稳才是硬结论）。
# 输出根独立（P11-MASKONLY-3090），不与 2060 产物混淆。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/P11/P11-MASKONLY-3090}; mkdir -p "$OUT"
DONE="$OUT/p11.done"; : > "$DONE"

# 可注入：默认 = 4 序列判决矩阵；铺 18 序列主表时由调用方传 SEQS
SEQS=${SEQS:-"f3_st_hf balloon f2_xyz mv_no_box"}
SEEDS=${SEEDS:-"0 1 2"}

# precheck：每个 seq 的 config 必须存在，且其 dataset_path 目录必须存在（mask-only 不吃 flow）
for seq in $SEQS; do
  cfg="configs/rgbd/experiments/p11_maskonly/p11_maskonly_${seq}.yaml"
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
  dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
  [ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: $seq 数据缺 ($dp)" >> "$DONE"; exit 1; }
done
echo "precheck OK: $(echo $SEQS | wc -w) seqs x $(echo $SEEDS | wc -w) seeds" >> "$DONE"

SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge 4 ]; do sleep 20; done; }

for seed in $SEEDS; do
  for seq in $SEQS; do
    outnm="${seq}_p11maskonly_seed${seed}"
    [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm" >> "$DONE"; continue; }
    wait_slot
    gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
          | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
    echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
    env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
      $PY slam.py --config configs/rgbd/experiments/p11_maskonly/p11_maskonly_${seq}.yaml \
      --seed "$seed" --results-root "$OUT/$outnm" \
      > "$OUT/$outnm.consolelog" 2>&1 &
    sleep 5
  done
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done
missing=0
for seed in $SEEDS; do
  for seq in $SEQS; do
    outnm="${seq}_p11maskonly_seed${seed}"
    [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
  done
done
echo "P11_3090_ALL_DONE $(date) missing=$missing" >> "$DONE"
