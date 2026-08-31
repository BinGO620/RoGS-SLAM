#!/bin/bash
# run_exp26_async_2060.sh — exp26 判别批 async 臂（cb 2060，静、串行）
# =============================================================================
# 判据冻结在 results/evidence/exp26_discriminant_prereg.md，跑前已提交。勿改判据。
#
# 为什么 async 臂放 2060 而不是 3090：这一臂测的正是「无外部负载下的内在 run-to-run
# 方差」。3090 现在被别的用户占着（93-95% util 波动），把它当 async 臂的平台，
# 等于把我们要研究的那个混杂变量（映射预算随负载漂）直接灌进测量里。
# 2060 静且串行 ⇒ 每个 run 的 FPS 可比，且与已有的 2060 oracle/fix seed0 同机可比。
#
# 5 run × ~40min ≈ 3.5h。
# 用法（cb 上）：
#   nohup bash scripts/run_exp26_async_2060.sh > results/runs/P8/P8-EXP26-ASYNC/master.log 2>&1 &
set -u
REPO=/data/monogs-ours; cd "$REPO"
# 解析出解释器绝对路径再直接调用（沿用 run_p8_ego_fix_2060.sh 的写法）：
# 直接用 `conda run ... python` 会缓冲子进程输出，consolelog 变成收尾才落盘。
PY=$(conda run -n monogs-ours which python 2>/dev/null | tail -1)
[ -x "$PY" ] || { echo "ABORT: 解析不到 monogs-ours 的 python"; exit 1; }
OUT=results/runs/P8/P8-EXP26-ASYNC
mkdir -p "$OUT"
DONE="$OUT/async.done"
: > "$DONE"

# arm:seed —— oracle 补到 n=3；fix 三个 seed 全带新 provenance 列重跑
RUNS="oracle:1 oracle:2 fix:0 fix:1 fix:2"

# 前置：flow 必须齐（运行时硬闸会更早 fail，这里快速拦截不发批量）
FLOW=/data/Datasets/TUM/rgbd_dataset_freiburg3_sitting_halfsphere/flow_raft
n=$(ls "$FLOW"/*.npy 2>/dev/null | wc -l)
echo "precheck f3_st_hf flow_npy=$n" >> "$DONE"
[ "$n" -ge 10 ] || { echo "ABORT: flow 不全($n)" >> "$DONE"; exit 1; }

# 前置：provenance 闸必须在位，否则 D3 无逐帧证据可判，白跑
if ! grep -q "write_reliability_frames" utils/slam_frontend.py; then
  echo "ABORT: provenance writer 不在位（exp26 commit 未同步）" >> "$DONE"; exit 1
fi

# 2060 6GB 串行：任何时刻只允许一个 run
running_slam() { pgrep -af 'slam\.py' 2>/dev/null | grep -cE '/python[0-9]* +slam\.py' || true; }
wait_slot() { while [ "$(running_slam)" -ge 1 ]; do sleep 20; done; }

for entry in $RUNS; do
  arm="${entry%%:*}"; seed="${entry##*:}"
  outnm="f3_st_hf_${arm}_seed${seed}"
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "SKIP $outnm (already done)" >> "$DONE"; continue
  fi
  wait_slot
  log="$OUT/$outnm.$(date +%Y%m%d-%H%M%S).consolelog"
  echo "$(date +%H:%M) RUN $outnm log=$(basename "$log")" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0 \
    "$PY" slam.py --config "configs/rgbd/experiments/p8_egooracle/p8_ego_${arm}_maskoff_f3_st_hf.yaml" \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$log" 2>&1
  echo "$(date +%H:%M) EXIT $outnm rc=$?" >> "$DONE"
done

while [ "$(running_slam)" -gt 0 ]; do sleep 30; done

missing=0
for entry in $RUNS; do
  arm="${entry%%:*}"; seed="${entry##*:}"; outnm="f3_st_hf_${arm}_seed${seed}"
  csv="$OUT/$outnm/tables/tracking_raw.csv"
  if [ ! -f "$csv" ]; then
    echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1))
  else
    ate=$(python3 -c "import csv,sys;r=list(csv.DictReader(open(sys.argv[1])));print(r[0]['ate_rmse_cm'] if r else 'NA')" "$csv" 2>/dev/null)
    # provenance 自证：ego 列必须真的落盘了，否则这个 run 对 D3 无用
    fr=$(find "$OUT/$outnm" -name frames.csv | head -1)
    prov=$(head -1 "$fr" 2>/dev/null | grep -c "ego_fit_applied" || true)
    echo "DONE $outnm ATE=${ate:-NA} ego_cols=${prov}" >> "$DONE"
    [ "${prov:-0}" = "1" ] || { echo "  !! WARN $outnm 无 ego 列，D3 判不了" >> "$DONE"; }
  fi
done
echo "EXP26_ASYNC_ALL_DONE $(date) missing=$missing" >> "$DONE"
