#!/bin/bash
# run_p8_ego_fix_2060.sh — 修法 B 验证臂（排在 control/oracle 之后，2060 串行）
# 判据：fix 的 ATE 应显著低于 control(35.29cm)，并逼近 oracle。
# 若 fix 未改善而 oracle 改善 -> 机制对但这个修法不够；两者都不改善 -> 机制被证伪。
set -u
cd /data/monogs-ours
PY=$(conda run -n monogs-ours which python 2>/dev/null | tail -1)
OUT=results/runs/P8/P8-EGOORACLE
DONE="$OUT/egofix.done"
: > "$DONE"
running_slam() { pgrep -af 'slam.py --config' 2>/dev/null | grep -cE '/python[0-9]* +slam\.py' || true; }
waited=0
while [ "$(running_slam)" -gt 0 ]; do
  sleep 60; waited=$((waited+60))
  [ $((waited % 1800)) = 0 ] && echo "$(date +%H:%M) WAIT 前序 run 未完, 已等 ${waited}s" >> "$DONE"
  [ "$waited" -ge 43200 ] && { echo "ABORT: 等超过12h" >> "$DONE"; exit 1; }
done
SEED=${SEED:-0}
outnm="f3_st_hf_fix_seed${SEED}"
echo "$(date +%H:%M) RUN $outnm" >> "$DONE"
env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0 \
  "$PY" slam.py --config configs/rgbd/experiments/p8_egooracle/p8_ego_fix_maskoff_f3_st_hf.yaml \
  --seed "$SEED" --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1
echo "$(date +%H:%M) DONE $outnm rc=$?" >> "$DONE"
echo "EGOFIX_ALL_DONE $(date)" >> "$DONE"
