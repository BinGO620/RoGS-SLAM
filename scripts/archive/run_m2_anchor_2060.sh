#!/bin/bash
# M2 锚点只读探针 — 本地 2060 判决机（exp32, 2026-08-20）。
#
# 为什么在 2060 而不是 3090：判据要求"至少 1 个 seed 确实发生 ATE 崩溃"，而 exp27 实测
# f3_st_hf 的双稳态在 2060 上更容易落到崩溃那一支（3090 5/5 稳、2060 2/3 稳）。
# 崩溃是被观测对象，不是噪声——挑更容易崩的机器是正确的取样，不是挑数据。
#
# 6GB 卡：单 run 串行跑（P2-T 实测单 run 峰值 4.09GB，两 run 并发会 OOM）。
set -u
REPO=/data/monogs-ours; cd "$REPO"
PY=/data/conda_envs/monogs-ours/bin/python
OUT=${OUT:-results/runs/M2/M2-ANCHOR-2060}; mkdir -p "$OUT"
DONE="$OUT/m2.done"; : > "$DONE"

SEQS=${SEQS:-"f3_st_hf"}
SEEDS=${SEEDS:-"0 1 2"}

for seq in $SEQS; do
  cfg="configs/rgbd/experiments/m2_anchor_probe/anchor_${seq}.yaml"
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
  dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
  [ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: $seq 数据缺 ($dp)" >> "$DONE"; exit 1; }
  n=$(ls "$dp/flow_raft"/*.npy 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] || { echo "ABORT: $seq flow_raft 空" >> "$DONE"; exit 1; }
  echo "precheck OK $seq flow=$n" >> "$DONE"
done

for seed in $SEEDS; do
  for seq in $SEQS; do
    outnm="${seq}_m2anchor_seed${seed}"
    [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm" >> "$DONE"; continue; }
    echo "$(date +%H:%M) RUN $outnm" >> "$DONE"
    env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0 \
      $PY slam.py --config configs/rgbd/experiments/m2_anchor_probe/anchor_${seq}.yaml \
      --fast --seed "$seed" --results-root "$OUT/$outnm" \
      > "$OUT/$outnm.consolelog" 2>&1
    echo "$(date +%H:%M) EXIT $outnm rc=$?" >> "$DONE"
  done
done

missing=0
for seed in $SEEDS; do
  for seq in $SEQS; do
    outnm="${seq}_m2anchor_seed${seed}"
    [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
  done
done
echo "M2_2060_ALL_DONE $(date) missing=$missing" >> "$DONE"
