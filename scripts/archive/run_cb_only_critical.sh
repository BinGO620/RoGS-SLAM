#!/bin/bash
# cb 2060 只跑判决核心 + 渲染验证
set -u
REPO=/data/monogs-ours; cd "$REPO"
PY=$(conda run -n monogs-ours which python 2>/dev/null | tail -1)
[ -x "$PY" ] || { echo "ABORT: python"; exit 1; }
OUT=results/runs/P11/P11-MASKONLY-2060; mkdir -p "$OUT"
DONE="$OUT/critical.done"; : > "$DONE"

# 判决 + 渲染基线（只跑缺的）
RUNS=(
  "f3_st_hf:2"
  "mv_no_box:1"
  "mv_no_box:2"
  "balloon:1"
  "balloon:2"
)

running_slam() { pgrep -af 'slam\.py --config' 2>/dev/null | grep -v 'conda run' | grep -v pgrep | wc -l; }
wait_slot() { while [ "$(running_slam)" -ge 1 ]; do sleep 20; done; }

for entry in "${RUNS[@]}"; do
  seq="${entry%%:*}"; seed="${entry##*:}"
  outnm="${seq}_p11maskonly_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm" >> "$DONE"; continue; }
  wait_slot
  log="$OUT/$outnm.$(date +%Y%m%d-%H%M%S).consolelog"
  echo "$(date +%H:%M) RUN $outnm" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0 \
    "$PY" slam.py --config "configs/rgbd/experiments/p11_maskonly/p11_maskonly_${seq}.yaml" \
    --seed "$seed" --results-root "$OUT/$outnm" > "$log" 2>&1 &
  sleep 30
done
while [ "$(running_slam)" -gt 0 ]; do sleep 30; done
echo "CRITICAL_DONE $(date)" >> "$DONE"
