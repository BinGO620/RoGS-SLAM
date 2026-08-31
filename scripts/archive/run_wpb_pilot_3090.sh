#!/bin/bash
# WP-B FLOW-MASK — 3090 pilot（阈值选择，CCF-C 整改执行卡 §4 WP-B）。
# Pilot = 3 分位（p80/p90/p95）× 2 dev 序列（mv_no_box, balloon）× seed0 = 6 run（screening）。
# 目标函数 = dev 两序列 seed0 的 ATE 几何平均最小；完成率优先（<95% 帧直接淘汰）；并列取 p90。
# 判据（冻结）：results/evidence/wpb_flowmask_prereg.md。确认阶段在 held-out 4 序列。
# 2026-08-15 exp19：旧 E0/pilot 因远程代码未经 git 同步、朴素 flow_threshold 分支缺失而全部作废
# （跑的是 Mask R-CNN 学习分割，非朴素 flow 阈值）。本脚本改为 FULL 6-run grid（含 balloon-p90
# 作为 E0 重发，不再假设 E0 存在），全部用正确的 flow_threshold 装置。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/WPB/WPB-PILOT; mkdir -p "$OUT"
DONE="$OUT/wpb_pilot.done"
: > "$DONE"

# run grid (full): {seq}|{quantile} × seed0, both dev seqs × p80/p90/p95.
RUNS="balloon|p80 balloon|p90 balloon|p95 mv_no_box|p80 mv_no_box|p90 mv_no_box|p95"
# Slot gate: count ONLY real SLAM workers. The naive pattern 'slam.py --config' also
# matches any monitoring/ssh command line that merely CONTAINS that literal text, which
# pins the count above zero forever (observed 2026-08-15: this launcher completed all 6
# runs but hung in the tail wait-loop below and never wrote PILOT_ALL_DONE). Anchor on
# the interpreter path — only a genuine worker's argv starts with it.
SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot(){ while [ "$(slam_count)" -ge 2 ]; do sleep 20; done; }

for entry in $RUNS; do
  seq="${entry%%|*}"; q="${entry##*|}"
  outnm="pilot_${seq}_${q}_seed0"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "$outnm SKIP" >> "$DONE"; continue; }
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  # 用 pilot_*_${q}.yaml（flowmask_${q} overlay）—— run_balloon.yaml 默认 p90 无此 overlay 的 mv_no_box-p90；用 pilot config
  cfg="configs/rgbd/experiments/wpb_flowmask/${seq}"
  # seq→run 前缀映射：mv_no_box→run_mv_no_box(p90) 没有 pilot_mv_no_box_p90? 有。统一用 pilot config
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/wpb_flowmask/pilot_${seq}_${q}.yaml \
    --seed 0 --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED($(date +%H:%M))" >> "$DONE"; sleep 3
done
while [ "$(slam_count)" -gt 0 ]; do sleep 30; done
echo "PILOT_ALL_DONE $(date)" >> "$DONE"
