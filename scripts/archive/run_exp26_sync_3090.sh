#!/bin/bash
# run_exp26_sync_3090.sh — exp26 判别批 sync 臂（jiangwenheng 3090 双卡）
# =============================================================================
# 判据冻结在 results/evidence/exp26_discriminant_prereg.md，跑前已提交。勿改判据。
#
# sync = single_thread（Dataset + Training 两处都设），把「每两帧摊到多少次映射迭代」
# 从「随机器负载漂的自由跑」变成「固定 150 iters/KF」。按构造对外部负载不敏感，
# 所以可以放在被别的用户占着的 3090 上，且能吃双卡。
#
# ⚠ 这是另一个工作点，ATE 与主表不可比，诊断专用，绝不入主表。
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_exp26_sync_3090.sh > results/runs/P8/P8-EXP26-SYNC/master.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P8/P8-EXP26-SYNC
mkdir -p "$OUT"
DONE="$OUT/sync.done"
: > "$DONE"

# arm:seed —— control 判「关掉竞态后还崩不崩」；fix 两个 seed，seed1 是 async 下崩到 35.86 的那个
RUNS="control:0 fix:0 fix:1"
MAX_PARALLEL=2

FLOW=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_sitting_halfsphere/flow_raft
n=$(ls "$FLOW"/*.npy 2>/dev/null | wc -l)
echo "precheck f3_st_hf flow_npy=$n" >> "$DONE"
[ "$n" -ge 10 ] || { echo "ABORT: flow 不全($n)" >> "$DONE"; exit 1; }

if ! grep -q "write_reliability_frames" utils/slam_frontend.py; then
  echo "ABORT: provenance writer 不在位（exp26 commit 未同步）" >> "$DONE"; exit 1
fi

# 并发闸看我们自己的进程数（别人占 1.3GB/24GB 不构成阻塞）；pgrep 锚定 argv 起始
running_slam() { pgrep -af 'slam\.py' 2>/dev/null | grep -cE '/python[0-9]* +slam\.py' || true; }
wait_slot() { while [ "$(running_slam)" -ge "$MAX_PARALLEL" ]; do sleep 20; done; }
pick_gpu() {
  nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits \
    | awk -F, '{w=$2+($3*100); if(NR==1||w<best){best=w; g=$1}} END{print g}' | tr -d ' '
}

i=0
for entry in $RUNS; do
  arm="${entry%%:*}"; seed="${entry##*:}"
  outnm="f3_st_hf_sync_${arm}_seed${seed}"
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "SKIP $outnm (already done)" >> "$DONE"; continue
  fi
  wait_slot
  gpu=$(pick_gpu); [ -n "$gpu" ] || gpu=$((i % 2)); i=$((i+1))
  log="$OUT/$outnm.$(date +%Y%m%d-%H%M%S).consolelog"
  echo "$(date +%H:%M) RUN $outnm gpu$gpu log=$(basename "$log")" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config "configs/rgbd/experiments/p8_egooracle/p8_sync_${arm}_maskoff_f3_st_hf.yaml" \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$log" 2>&1 &
  sleep 3
done

while [ "$(running_slam)" -gt 0 ]; do sleep 30; done

missing=0
for entry in $RUNS; do
  arm="${entry%%:*}"; seed="${entry##*:}"; outnm="f3_st_hf_sync_${arm}_seed${seed}"
  csv="$OUT/$outnm/tables/tracking_raw.csv"
  if [ ! -f "$csv" ]; then
    echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1))
  else
    ate=$(python3 -c "import csv,sys;r=list(csv.DictReader(open(sys.argv[1])));print(r[0]['ate_rmse_cm'] if r else 'NA')" "$csv" 2>/dev/null)
    fr=$(find "$OUT/$outnm" -name frames.csv | head -1)
    prov=$(head -1 "$fr" 2>/dev/null | grep -c "ego_fit_applied\|ego_pose_oracle" || true)
    echo "DONE $outnm ATE=${ate:-NA} ego_cols=${prov}" >> "$DONE"
  fi
done
echo "EXP26_SYNC_ALL_DONE $(date) missing=$missing" >> "$DONE"
