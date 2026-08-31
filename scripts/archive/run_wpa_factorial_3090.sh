#!/bin/bash
# WP-A FACTORIAL — 3090 双卡批量（CCF-C 整改执行卡 v3, 2026-08-14）。
# 8 格 × 5 序列 × 3 seed = 120 run 全因子消融（mask-free，K/R/L 三布尔全组合）。
#
# 判据（NEXT_SESSION_PROMPT §4 WP-A + 预注册）：
#   L1 completion = tracking_raw.csv 存在 且 trj_full_final 帧数 ≥ 数据集总帧数×95%;
#   L2 条件 ATE = ate_rmse_cm（只认 tracking_raw.csv, 不 grep console）;
#   L3 轨迹覆盖 = trj_full_final 帧数 / 数据集总帧数。
#   配对 = 共同完成 seed; k=3 判决 / k=2 描述 / k<=1 UNRESOLVED; 分母固定 5 永不变。
#
# 起跑要求：装置（configs + contract test + prereg）已 commit；软链已重指；协议 = P7 同款
#           （无 --fast，full eval，tracking_raw.csv + plot/trj_full_final.json 均写）。
#           注：--fast 会跳过渲染/精修但保存一致的总帧轨迹；为与 P7 逐协议对齐、消除
#           fast-vs-full 的歧义，本 campaign 用**无 --fast 的完整协议**（P7 同款，120-run 已验证路径）。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/WPA/WPA-FACTORIAL; mkdir -p "$OUT"
DONE="$OUT/wpa.done"
: > "$DONE"

# seqs x 8 arms: filename prefix. arm = K/R/L 三布尔。
SEQS="mv_no_box mv_no_box2 pt2 balloon pt1"
ARMS="K0R0L0 K1R1L1 K0R1L1 K1R0L1 K1R1L0 K0R1L0 K0R0L1 K1R0L0"

RUNS=""
for seed in 0 1 2; do
  for s in $SEQS; do
    for arm in $ARMS; do
      RUNS="$RUNS ${s}|${arm}|${seed}"
    done
  done
done

wait_slot() {
  while [ "$(pgrep -fc 'slam.py --config' 2>/dev/null || echo 0)" -ge 2 ]; do
    sleep 20
  done
}

for entry in $RUNS; do
  seq="${entry%%|*}"; rest="${entry#*|}"; arm="${rest%%|*}"; seed="${rest##*|}"
  outnm="wpa_${seq}_${arm}_seed${seed}"
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "$outnm SKIP(already)" >> "$DONE"
    continue
  fi
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/wpa_factorial/wpa_${seq}_${arm}.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED($(date +%H:%M) gpu$gpu)" >> "$DONE"
  sleep 3
done
while [ "$(pgrep -fc 'slam.py --config' 2>/dev/null || echo 0)" -gt 0 ]; do sleep 30; done

missing=0
for entry in $RUNS; do
  seq="${entry%%|*}"; rest="${entry#*|}"; arm="${rest%%|*}"; seed="${rest##*|}"
  outnm="wpa_${seq}_${arm}_seed${seed}"
  if [ ! -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1))
  fi
done
echo "ALL_DONE $(date) missing=$missing" >> "$DONE"
