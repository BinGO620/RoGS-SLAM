#!/bin/bash
# run_p8_ego_oracle_2060.sh — ego-pose oracle 诊断（cb 本地 2060，串行）
# =============================================================================
# 判据（跑前写死）：
#   若 oracle 臂 ATE 回到 control 臂的 1/3 以内（f3_st_hf control 预期 ~30cm 量级，
#   oracle 若 <10cm）⇒ 闭环因果坐实：e_flow 虚高确实由 tracker 自身位姿误差驱动，
#   且 oracle 值 = 任何真实修法的上界。
#   若 oracle 与 control 相当 ⇒ 因果被证伪，缺陷不在 ego 位姿这条边，另找机制。
#
# 为什么串行：2060 只有 6GB，一次一个 run。两个 run 同机同卡同序，
# 消除跨机非确定性（本项目有同 seed 两次 ATE 15.72 vs 21.42 的证据）。
#
# ⚠ 诊断专用，产物不进主表。每个 run 的 reliability_signal/frames.csv 里
#   ego_pose_oracle 列自证跑的是哪个模式。
set -u
cd /data/monogs-ours
PY=$(conda run -n monogs-ours which python 2>/dev/null | tail -1)
[ -x "$PY" ] || { echo "找不到 monogs-ours python"; exit 1; }
OUT=results/runs/P8/P8-EGOORACLE
mkdir -p "$OUT"
DONE="$OUT/egooracle.done"
: > "$DONE"

# 前置：本地 flow 必须在（硬闸会 abort，这里给出更早更清楚的信息）
FLOW=/data/Datasets/TUM/rgbd_dataset_freiburg3_sitting_halfsphere/flow_raft
n=$(ls "$FLOW"/*.npy 2>/dev/null | wc -l)
echo "precheck f3_st_hf flow_npy=$n" >> "$DONE"
[ "$n" -ge 10 ] || { echo "ABORT: flow 不全($n)" >> "$DONE"; exit 1; }

SEED=${SEED:-0}
for arm in control oracle; do
  outnm="f3_st_hf_${arm}_seed${SEED}"
  cfg="configs/rgbd/experiments/p8_egooracle/p8_ego_${arm}_maskoff_f3_st_hf.yaml"
  echo "$(date +%H:%M) RUN $outnm" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=0 \
    "$PY" slam.py --config "$cfg" --seed "$SEED" --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1
  rc=$?
  ate=$(awk -F, 'NR>1&&$0!=""{for(i=1;i<=NF;i++)if(h[i]=="ate_rmse_cm")v=$i} NR==1{for(i=1;i<=NF;i++)h[i]=$i} END{print v}' \
        "$OUT/$outnm/tables/tracking_raw.csv" 2>/dev/null)
  echo "$(date +%H:%M) DONE $outnm rc=$rc ATE=${ate:-NA}" >> "$DONE"
done
echo "EGOORACLE_ALL_DONE $(date)" >> "$DONE"
