#!/bin/bash
# run_main_table_fullkern_rerun.sh — 主表 combined(mask-ON L 完整内核) 补 flow 重跑
# =============================================================================
# ★ 目的：修复 exp23 静默空转事故对主表的影响。
#   主表 combined 臂里，11 条序列当初缺 flow_raft → ReliabilitySignal 被静默跳过
#   （跑成 K1R1L0 而非 K1R1L1），臂名是错的。exp23 事故后已加运行时硬闸，
#   flow 也已全部补建到本地 cb 与 jiangwenheng 远程。
#   现在用同一 config（method_combined_maskboth_prune，ReliabilitySignal.enabled）
#   + 完整 flow 重跑这 11 条 × 3 seed，覆盖旧产物得到真·完整内核。
#
# ★ 先决条件（硬闸铁律，发批量前必须全过）：
#   1. 远程 HEAD == origin == 本地已 push 最新（跑 scripts/check_code_sync.sh 校验）
#   2. flow_raft 已补齐（predict 序列在 /mnt/app/datasets 下都有 flow_raft/*.npy）
#   3. 硬闸已加（7b89ff81+）—— flow 缺会直接 abort，不再静默跑错
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_main_table_fullkern_rerun.sh > results/runs/rerun_fullkern.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P6/P6-FULLKERN
mkdir -p "$OUT"
DONE="$OUT/fullkern.done"
: > "$DONE"

# 11 条缺 flow 序列 × 3 seed = 33 run（combined mask-ON 完整内核）
RUNS="crowd:0 crowd:1 crowd:2 crowd2:0 crowd2:1 crowd2:2 f3_wk_rpy:0 f3_wk_rpy:1 f3_wk_rpy:2 \
f1_desk:0 f1_desk:1 f1_desk:2 f2_person:0 f2_person:1 f2_person:2 \
f3_office:0 f3_office:1 f3_office:2 f3_st_hf:0 f3_st_hf:1 f3_st_hf:2 \
f3_st_rpy:0 f3_st_rpy:1 f3_st_rpy:2 f3_st_xyz:0 f3_st_xyz:1 f3_st_xyz:2 \
f3_wk_hf:0 f3_wk_hf:1 f3_wk_hf:2 f2_xyz:0 f2_xyz:1 f2_xyz:2"

# 校验预置：确认这些序列 flow 已补（硬闸会更早fail，这里作快速前置检查）
for s in crowd crowd2 f3_wk_rpy f1_desk f2_person f3_office f3_st_hf f3_st_rpy f3_st_xyz f3_wk_hf f2_xyz; do
  case $s in
    crowd|crowd2) fd=/mnt/app/datasets/Bonn/rgbd_bonn_$s/flow_raft;;
    *) case $s in
         f1_desk) fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg1_desk/flow_raft;;
         f2_person) fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg2_desk_with_person/flow_raft;;
         f3_office) fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_long_office_household/flow_raft;;
         f3_st_hf) fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_sitting_halfsphere/flow_raft;;
         f3_st_rpy) fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_sitting_rpy/flow_raft;;
         f3_st_xyz) fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_sitting_xyz/flow_raft;;
         f3_wk_hf) fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_walking_halfsphere/flow_raft;;
         f3_wk_rpy) fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_walking_rpy/flow_raft;;
         f2_xyz) fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg2_xyz/flow_raft;;
       esac;;
  esac
  n=$(ls "$fd"/*.npy 2>/dev/null | wc -l)
  echo "precheck $s flow_npy=$n"
  if [ "$n" -lt 10 ]; then echo "!! ABORT: $s flow 不完整($n), 硬闸会fail, 不发" >> "$DONE"; exit 1; fi
done

running_slam() { pgrep -af 'slam.py --config' 2>/dev/null | grep -E '/python[0-9]* ( |$)?slam.py' | wc -l; }
wait_idle() { while [ "$(running_slam)" -ge 2 ]; do sleep 20; done; }
i=0

for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"
  outnm="${seq}_combined_seed${seed}"
  # 用新 OUT 目录，不走 SKIP（要覆盖旧 P6-MASON/P6-MASON-8SEQ 的 L0 产物）
  wait_idle
  gpu=$(nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits \
        | awk -F, '{idx=$1; w=$2+($3*100); if(w<best||NR==1){best=w; gidx=$1}} END{print gidx}' | tr -d ' ')
  n_cards=$(nvidia-smi -L 2>/dev/null | wc -l)
  if [ -z "$gpu" ] || [ "${n_cards:-0}" = "0" ]; then gpu=$((i % 2)); fi
  i=$((i+1))
  echo "$(date +%H:%M) RUN $outnm gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p6_mason/p6_mason_combined_${seq}.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED" >> "$DONE"
  sleep 3
done
while [ "$(running_slam)" -gt 0 ]; do sleep 30; done
missing=0
for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"; outnm="${seq}_combined_seed${seed}"
  if [ ! -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1));
    echo "=== tail $outnm.consolelog ==="; tail -40 "$OUT/$outnm.consolelog" 2>/dev/null; fi
done
echo "FULLKERN_ALL_DONE missing=$missing $(date +%H:%M)"
echo "FULLKERN_ALL_DONE missing=$missing" >> "$DONE"
