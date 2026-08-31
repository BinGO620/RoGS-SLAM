#!/bin/bash
# WP-M MASK-ONLY — 3090 双卡 54-run（2026-08-15, exp22）。
# 18 主表序列 × 3 seed，臂 = combined 主表 overlay 仅关掉 K/R/L（mask-only）。
# 判据冻结：results/evidence/wpm_maskonly_prereg.md（跑前提交）。
# 装置合同：tests/test_wpm_maskonly_configs.py（diff vs combined 恰为三个 kernel flag）。
# 协议 = WP-A / P7 同款完整协议（无 --fast），ATE 只认 tracking_raw.csv。
#
# 槽位纪律（exp19 教训，memory background-monitor-discipline）：
#   pgrep 必须锚定 argv 起始，否则会匹配到监控命令自身 → 计数永不归零 → 收尾死锁。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/WPM/WPM-MASKONLY; mkdir -p "$OUT"
DONE="$OUT/wpm.done"
: > "$DONE"

SEQS="balloon balloon2 crowd crowd2 mv_no_box mv_no_box2 pt1 pt2 \
f1_desk f2_xyz f2_person f3_office f3_st_hf f3_st_rpy f3_st_xyz f3_wk_hf f3_wk_rpy f3_wk_xyz"

RUNS=""
for seed in 0 1 2; do
  for s in $SEQS; do
    RUNS="$RUNS ${s}|${seed}"
  done
done

SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
# 4 槽 = 每张 3090 两个 run（实测 peak ~2.6 GB/run，24 GB 卡足够；计算争用换吞吐）
wait_slot() { while [ "$(slam_count)" -ge 4 ]; do sleep 20; done; }

for entry in $RUNS; do
  seq="${entry%%|*}"; seed="${entry##*|}"
  outnm="wpm_${seq}_maskonly_seed${seed}"
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "$outnm SKIP(already)" >> "$DONE"
    continue
  fi
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/wpm_maskonly/wpm_${seq}_maskonly.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED($(date +%H:%M) gpu$gpu)" >> "$DONE"
  sleep 5
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done

missing=0
for entry in $RUNS; do
  seq="${entry%%|*}"; seed="${entry##*|}"
  outnm="wpm_${seq}_maskonly_seed${seed}"
  if [ ! -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1))
  fi
done
echo "ALL_DONE $(date) missing=$missing" >> "$DONE"
