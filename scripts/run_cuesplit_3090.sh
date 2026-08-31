#!/bin/bash
# P7 CUE-SPLIT — 3090 批量：拆解 ReliabilitySignal 双线索固定乘法里逐 cue 的独立贡献。
#
# 2026-08-13（ours-method 移交方法期立项）。口号：既然固定 both 被证明非普适内核
# （纯物/纯人偏 geometry、balloon 偏 flow、mv_no_box2 上 both 真实退化 5.68→12.72），
# 就先用同一 mask-free 骨干把 4 序列 × 4 臂（off / on-default-both / flow-only /
# geometry-only）对齐跑到 3 seed，确认 ours-method 单 seed 结论在大方差的 3090 上是否成立。
#
# 4 seq × 4 mode × 3 seed = 48 runs。双 3090 并行（每 run ~25-30min，约 12h 两卡）。
# 这 4 序列是 ours-method 已证区分度最高的（balloon / mv_no_box / mv_no_box2 / pt2）。
# mask-free（SemanticMask off）—— 纯内核维度，不掺借来的 mask。
# mode 默认 both 与历史逐字节一致；on 臂 = reliability 开 + 默认 both（= P6 mask-free on）。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P7/P7-CUESPLIT
mkdir -p "$OUT"
DONE="$OUT/cuesplit.done"

# 4 seq × 4 mode。seq 名对 config 文件前缀；mode = on|off|flow|geo（screen_{seq}_{mode}.yaml）。
# 注意：seq 名含下划线（mv_no_box / mv_no_box2），所以 RUNS 存 "seq|mode" 而非拼接串。
SEQS="balloon mv_no_box mv_no_box2 pt2"
MODES="on off flow geo"
RUNS=""
for seed in 0 1 2; do
  for s in $SEQS; do
    for m in $MODES; do
      RUNS="$RUNS ${s}|${m}|${seed}"
    done
  done
done

wait_slot() {
  while [ "$(pgrep -fc 'slam.py --config' 2>/dev/null || echo 0)" -ge 2 ]; do
    sleep 20
  done
}

: > "$DONE"
for entry in $RUNS; do
  seq="${entry%%|*}"; rest="${entry#*|}"; mode="${rest%%|*}"; seed="${rest##*|}"
  outnm="cuesplit_${seq}_${mode}_seed${seed}"
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "$outnm SKIP" >> "$DONE"
    continue
  fi
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p7_cuesplit/screen_${seq}_${mode}.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED($(date +%H:%M))" >> "$DONE"
  sleep 3
done
while [ "$(pgrep -fc 'slam.py --config' 2>/dev/null || echo 0)" -gt 0 ]; do sleep 30; done

missing=0
for entry in $RUNS; do
  seq="${entry%%|*}"; rest="${entry#*|}"; mode="${rest%%|*}"; seed="${rest##*|}"
  outnm="cuesplit_${seq}_${mode}_seed${seed}"
  if [ ! -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1))
  fi
done
echo "ALL_DONE $(date) missing=$missing" >> "$DONE"
