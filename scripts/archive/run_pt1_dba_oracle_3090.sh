#!/bin/bash
# P6 (exp-v3-14) — pt1 KF-BA 重启前提探针：DBALite.oracle + diagnostic (只读)。
# 回答：mask-ON + edge3 的 person 序列上，masked geometry 是否偏好 GT。
# 纯只读 toggle，零核心改动，不用 dba weight stash（那是旧 DBAphoto 路线）。
# 3 seed，双卡并发；写 P6-DBA-ORACLE/dba_oracle.done。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P6/P6-DBA-ORACLE; mkdir -p "$OUT"; DONE="$OUT/dba_oracle.done"
RUNS="pt1_edge3_dba:0 pt1_edge3_dba:1 pt1_edge3_dba:2"
MATSON_i=${MATSON_i:-0}
running_slam(){ pgrep -af 'slam.py --config' 2>/dev/null | grep -E '/python[0-9]* ( |$)?slam.py' | wc -l; }
wait_idle(){ while [ "$(running_slam)" -ge 2 ]; do sleep 20; done; }
: > "$DONE"
for spec in $RUNS; do
  key="${spec%%:*}"; seed="${spec##*:}"; outnm="${key}_seed${seed}"
  wait_idle
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm"; echo "$outnm SKIP" >> "$DONE"; continue; }
  gpu=$(nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits | awk -F, '{w=$2+($3*100); if(w<best||NR==1){best=w;g=$1}} END{print g}')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p6_mason/pt1_dba/p6_mason_pt1_dba_oracle.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED" >> "$DONE"; sleep 3
done
while [ "$(running_slam)" -gt 0 ]; do sleep 30; done
missing=0
for spec in $RUNS; do
  key="${spec%%:*}"; seed="${spec##*:}"; outnm="${key}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
done
echo "DBA_ORACLE_ALL_DONE missing=$missing" >> "$DONE"
