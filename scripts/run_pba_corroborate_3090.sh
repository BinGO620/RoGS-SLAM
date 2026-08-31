#!/bin/bash
# PBA 佐证批 —— 给 BA-CHANNEL-DOMINANT 判决补可分解序列（exp34, 2026-08-21）
#
# balloon 已判 share_BA = 0.672（只关 BA 侧 mask 丢掉 67% 的 mask 增益），
# 但只有一条可分解序列。本批补两条：
#
#   f3_wk_xyz  —— 18 序列可分解性筛选里比值最高（19.8），且是 TUM/行人走动型，
#                 跨数据集跨动态类型，是真正的佐证；**进判决**。
#   pt1        —— 用户点名。可分解性比值 1.43 < 3（mask-free 臂 seed 极差 14.4cm
#                 就是 memory 里"pt1 全员失败区 38-63cm"那条），**发批前即声明
#                 不进判决**，只作失败区的描述性读数。
#
# 矩阵 = 2 序列 × 3 臂 × 3 seed = 18 run。三臂：
#   eboth      mask_mapping=T, mask_insertion=T   （完整 mask，上界）
#   mapping_off mask_mapping=F, mask_insertion=T  （处理臂，唯一差异）
#   maskfree   SemanticMask.enabled=F             （无 mask，下界）
# 单变量隔离由 tests/test_pba_ba_coupling.py 钉住。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/PBA}; mkdir -p "$OUT"
DONE="$OUT/corroborate.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-8}          # 实测每 run 峰值 ~2GB，两卡 49GB，8 并发很安全

SEQS=${SEQS:-"f3_wk_xyz pt1"}
ARMS=${ARMS:-"eboth mapping_off maskfree"}
SEEDS=${SEEDS:-"0 1 2"}

# precheck：config 存在 + 数据存在 + frozen flow 非空（exp24 静默空转事故）
for seq in $SEQS; do
  for arm in $ARMS; do
    case $arm in
      mapping_off) cfg="configs/rgbd/experiments/pba_ba_coupling/pba_mapping_off_${seq}.yaml";;
      *)           cfg="configs/rgbd/experiments/pba_ba_coupling/pba_${arm}_${seq}.yaml";;
    esac
    [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
  done
  cfg="configs/rgbd/experiments/pba_ba_coupling/pba_eboth_${seq}.yaml"
  dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
  [ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: $seq 数据缺 ($dp)" >> "$DONE"; exit 1; }
  n=$(ls "$dp"/flow_raft/*.npy 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] || { echo "ABORT: $seq flow_raft 空 ($dp)" >> "$DONE"; exit 1; }
  echo "precheck OK $seq flow=$n" >> "$DONE"
done
echo "$(date +%F' '%H:%M) LAUNCH seqs=[$SEQS] arms=[$ARMS] seeds=[$SEEDS] maxjobs=$MAXJOBS" >> "$DONE"

SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

for seq in $SEQS; do
  for seed in $SEEDS; do
    for arm in $ARMS; do
      case $arm in
        mapping_off) cfg="configs/rgbd/experiments/pba_ba_coupling/pba_mapping_off_${seq}.yaml"
                     outnm="pba_mapping_off_${seq}_seed${seed}";;
        eboth)       cfg="configs/rgbd/experiments/pba_ba_coupling/pba_eboth_${seq}.yaml"
                     outnm="eboth_${seq}_seed${seed}";;
        maskfree)    cfg="configs/rgbd/experiments/pba_ba_coupling/pba_maskfree_${seq}.yaml"
                     outnm="control_maskfree_${seq}_seed${seed}";;
      esac
      [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm (done)" >> "$DONE"; continue; }
      wait_slot
      gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
            | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
      echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
      env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
        $PY slam.py --config "$cfg" --fast --seed "$seed" \
        --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1 &
      sleep 6
    done
  done
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done
missing=0
for seq in $SEQS; do for seed in $SEEDS; do for arm in $ARMS; do
  case $arm in
    mapping_off) outnm="pba_mapping_off_${seq}_seed${seed}";;
    eboth)       outnm="eboth_${seq}_seed${seed}";;
    maskfree)    outnm="control_maskfree_${seq}_seed${seed}";;
  esac
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
done; done; done
echo "PBA_CORROBORATE_DONE $(date) missing=$missing" >> "$DONE"
