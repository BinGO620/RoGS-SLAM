#!/bin/bash
# run_p8_ego_fix_3090.sh — 修法 B 多 seed 验证（cb 发，jiangwenheng 跑，双卡）
# =============================================================================
# ★ exp26 修复：原版的等卡循环是
#       while nvidia-smi -i $gpu --query-compute-apps=pid | grep -qE '[0-9]+'; do ... done
#   即「只要卡上有任何进程就等」。3090 上常年有别的用户占 ~1.3GB/24GB，
#   这个条件永远为真 → 死锁 → seed2 从未启动，而 fix.done 里只留下一行 precheck，
#   看起来像「跑完了」。脚本头当时还写着「zxl 进程只占 1.2GB，互不干扰」——
#   意图和代码互相矛盾。
#
#   正确判据（沿用 run_maskfree_fullkern_rerun.sh 里已跑通 33 run 的写法）：
#   并发闸看**我们自己**的 slam 进程数，选卡看 memory.used + util 的加权分。
#   别人占多少不是我们该等的东西——显存够就上。
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_p8_ego_fix_3090.sh > results/runs/P8/P8-FIX-3090/master.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/P8/P8-FIX-3090
mkdir -p "$OUT"
DONE="$OUT/fix.done"
: > "$DONE"

SEEDS="0 1 2"
MAX_PARALLEL=2          # 双卡，每卡一个 run

# pgrep 必须锚定 argv 起始，否则会匹配到监控命令自身（exp19 一晚咬三次）
running_slam() { pgrep -af 'slam\.py' 2>/dev/null | grep -cE '/python[0-9]* +slam\.py' || true; }
wait_slot() { while [ "$(running_slam)" -ge "$MAX_PARALLEL" ]; do sleep 20; done; }
# 选卡：memory.used + util*100 最小的那张。别人的小占用不构成阻塞。
pick_gpu() {
  nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits \
    | awk -F, '{w=$2+($3*100); if(NR==1||w<best){best=w; g=$1}} END{print g}' | tr -d ' '
}

# 前置：flow
FLOW=/mnt/app/datasets/TUM/rgbd_dataset_freiburg3_sitting_halfsphere/flow_raft
n=$(ls "$FLOW"/*.npy 2>/dev/null | wc -l)
echo "precheck f3_st_hf flow_npy=$n" >> "$DONE"
[ "$n" -ge 10 ] || { echo "ABORT: flow 不全($n)" >> "$DONE"; exit 1; }

i=0
for seed in $SEEDS; do
  outnm="f3_st_hf_fix_seed${seed}"
  # 断点续跑
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    ate=$(python3 -c "import csv,sys;r=list(csv.DictReader(open(sys.argv[1])));print(r[0]['ate_rmse_cm'] if r else 'NA')" \
          "$OUT/$outnm/tables/tracking_raw.csv" 2>/dev/null)
    echo "SKIP $outnm (already done, ATE=${ate:-NA})" >> "$DONE"
    continue
  fi
  wait_slot
  gpu=$(pick_gpu); [ -n "$gpu" ] || gpu=$((i % 2)); i=$((i+1))
  # consolelog 带启动时刻：原版固定文件名会被下一次发批量覆盖，导致
  # seed0.consolelog 里装的其实是一个 16:53 被杀掉的死 run，而出 2.10cm 的是 17:09 那个。
  log="$OUT/$outnm.$(date +%Y%m%d-%H%M%S).consolelog"
  echo "$(date +%H:%M) RUN $outnm gpu$gpu log=$(basename "$log")" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config configs/rgbd/experiments/p8_egooracle/p8_ego_fix_maskoff_f3_st_hf.yaml \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$log" 2>&1 &
  sleep 3
done

while [ "$(running_slam)" -gt 0 ]; do sleep 30; done

missing=0
for seed in $SEEDS; do
  outnm="f3_st_hf_fix_seed${seed}"
  if [ ! -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1))
  else
    ate=$(python3 -c "import csv,sys;r=list(csv.DictReader(open(sys.argv[1])));print(r[0]['ate_rmse_cm'] if r else 'NA')" \
          "$OUT/$outnm/tables/tracking_raw.csv" 2>/dev/null)
    echo "DONE $outnm ATE=${ate:-NA}" >> "$DONE"
  fi
done
echo "FIX_3090_ALL_DONE $(date) missing=$missing" >> "$DONE"
