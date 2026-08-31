#!/bin/bash
# run_maskfree_fullkern_rerun.sh — 主表 mask-free 臂（完整内核）补 flow 重跑
# =============================================================================
# ★ 目的：与 P6-FULLKERN（combined 臂）配套，修复 exp23 静默空转事故对 mask-free 臂的影响。
#   mask-free = combined 减 SemanticMask，但仍含 ReliabilitySignal（method_combined_maskoff_prune
#   继承 maskboth，只关 SemanticMask）。因此同样在缺 flow 的 11 条序列上被静默跳过，
#   跑成了 K1R1L0（无 Reliability）而非 K1R1L1。
#
#   现在 flow 已全部补齐 + 运行时硬闸已加，用同一 config 重跑这 11 条 × 3 seed。
#
# ★ 先决条件（发批量前必须全过）：
#   1. 远程 HEAD == origin == 本地已 push 最新（scripts/check_code_sync.sh）
#   2. flow_raft 已补齐（脚本内置 precheck）
#   3. 硬闸已加（7b89ff81+）—— flow 缺会直接 abort
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_maskfree_fullkern_rerun.sh > results/runs/P6/P6-FULLKERN-MASKFREE/master.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P6/P6-FULLKERN-MASKFREE
mkdir -p "$OUT"
DONE="$OUT/maskfree.done"
: > "$DONE"

# 与 combined 臂同样的 11 条缺 flow 序列 × 3 seed = 33 run
RUNS="crowd:0 crowd:1 crowd:2 crowd2:0 crowd2:1 crowd2:2 f3_wk_rpy:0 f3_wk_rpy:1 f3_wk_rpy:2 \
f1_desk:0 f1_desk:1 f1_desk:2 f2_person:0 f2_person:1 f2_person:2 \
f3_office:0 f3_office:1 f3_office:2 f3_st_hf:0 f3_st_hf:1 f3_st_hf:2 \
f3_st_rpy:0 f3_st_rpy:1 f3_st_rpy:2 f3_st_xyz:0 f3_st_xyz:1 f3_st_xyz:2 \
f3_wk_hf:0 f3_wk_hf:1 f3_wk_hf:2 f2_xyz:0 f2_xyz:1 f2_xyz:2"

# 前置校验：flow 必须齐（硬闸会更早 fail，这里快速拦截不发批量）
for s in crowd crowd2 f3_wk_rpy f1_desk f2_person f3_office f3_st_hf f3_st_rpy f3_st_xyz f3_wk_hf f2_xyz; do
  case $s in
    crowd|crowd2) fd=/mnt/app/datasets/Bonn/rgbd_bonn_$s/flow_raft;;
    f1_desk)      fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg1_desk/flow_raft;;
    f2_person)    fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg2_desk_with_person/flow_raft;;
    f2_xyz)       fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg2_xyz/flow_raft;;
    f3_office)    fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_long_office_household/flow_raft;;
    f3_st_hf)     fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_sitting_halfsphere/flow_raft;;
    f3_st_rpy)    fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_sitting_rpy/flow_raft;;
    f3_st_xyz)    fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_sitting_xyz/flow_raft;;
    f3_wk_hf)     fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_walking_halfsphere/flow_raft;;
    f3_wk_rpy)    fd=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_walking_rpy/flow_raft;;
  esac
  n=$(ls "$fd"/*.npy 2>/dev/null | wc -l)
  echo "precheck $s flow_npy=$n"
  if [ "$n" -lt 10 ]; then echo "!! ABORT: $s flow 不完整($n), 不发" >> "$DONE"; exit 1; fi
done

running_slam() { pgrep -af 'slam.py --config' 2>/dev/null | grep -E '/python[0-9]* ( |$)?slam.py' | wc -l; }
wait_idle() { while [ "$(running_slam)" -ge 2 ]; do sleep 20; done; }
i=0

for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"
  outnm="${seq}_maskoff_seed${seed}"
  wait_idle
  gpu=$(nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits \
        | awk -F, '{idx=$1; w=$2+($3*100); if(w<best||NR==1){best=w; gidx=$1}} END{print gidx}' | tr -d ' ')
  n_cards=$(nvidia-smi -L 2>/dev/null | wc -l)
  if [ -z "$gpu" ] || [ "${n_cards:-0}" = "0" ]; then gpu=$((i % 2)); fi
  i=$((i+1))
  echo "$(date +%H:%M) RUN $outnm gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p6_maskoff/p6_maskoff_prune_${seq}.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED" >> "$DONE"
  sleep 3
done
while [ "$(running_slam)" -gt 0 ]; do sleep 30; done
missing=0
for entry in $RUNS; do
  seq="${entry%%:*}"; seed="${entry##*:}"; outnm="${seq}_maskoff_seed${seed}"
  if [ ! -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1));
    echo "=== tail $outnm.consolelog ==="; tail -40 "$OUT/$outnm.consolelog" 2>/dev/null; fi
done
echo "MASKFREE_ALL_DONE missing=$missing $(date +%H:%M)"
echo "MASKFREE_ALL_DONE missing=$missing" >> "$DONE"
