#!/bin/bash
# 候选 B Phase 0 — mask-free 双稳态是 seed 驱动还是异步时序驱动？（exp34, 2026-08-21）
#
# 判据、区组与阈值预注册于 results/evidence/candidateB_crashrate_preregistration.md
# （发批前提交）。本脚本只执行，不引入任何新阈值。
#
# 矩阵 = 1 config × 1 序列 × 12 run：
#   区组 T（时序）: seed 0 重复 6 次，输出目录不同  -> config 与 seed 完全相同
#   区组 S（种子）: seed 1..6 各 1 次
# 二者的组内 max/min 之比就是判据（见预注册 §4）。
#
# 这里**不改任何机制**：用的是既有的 t2_control_maskfree_crowd2.yaml 原配置，
# 测的是这个臂自己的分布。crowd2 = 895 帧，4 并发下单 run ~45min ⇒ 3 波 ~2.3h。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
CFG=configs/rgbd/experiments/t2_mad_quota/t2_control_maskfree_crowd2.yaml
OUT=${OUT:-results/runs/B/B-CRASHRATE-3090}; mkdir -p "$OUT"
DONE="$OUT/b.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-4}
N_REP=${N_REP:-6}

# precheck：config 存在 + 数据目录存在 + frozen flow 非空（exp24 静默空转事故）
[ -f "$CFG" ] || { echo "ABORT: config 缺 $CFG" >> "$DONE"; exit 1; }
dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$CFG')['Dataset']['dataset_path'])" 2>/dev/null)
[ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: 数据缺 ($dp)" >> "$DONE"; exit 1; }
n=$(ls "$dp"/flow_raft/*.npy 2>/dev/null | wc -l)
[ "$n" -gt 0 ] || { echo "ABORT: flow_raft 空 ($dp)" >> "$DONE"; exit 1; }
echo "precheck OK crowd2 flow=$n" >> "$DONE"
echo "$(date +%F' '%H:%M) LAUNCH blockT=seed0x$N_REP blockS=seed1..$N_REP maxjobs=$MAXJOBS" >> "$DONE"

SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

launch() {   # $1 = run name, $2 = seed
  local outnm="$1" seed="$2"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm (done)" >> "$DONE"; return; }
  wait_slot
  local gpu
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm seed=$seed on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config "$CFG" --fast --seed "$seed" \
    --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1 &
  sleep 8
}

# 交错发：两个区组同时在飞，避免"区组 T 全在 A 卡、区组 S 全在 B 卡"这种
# 与判据共线的系统性差异（两块 3090 同型号，但温度/占用历史不同）。
for i in $(seq 1 "$N_REP"); do
  launch "T_seed0_rep${i}" 0
  launch "S_seed${i}" "$i"
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done
missing=0
for i in $(seq 1 "$N_REP"); do
  for outnm in "T_seed0_rep${i}" "S_seed${i}"; do
    [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
  done
done
echo "B_PHASE0_DONE $(date) missing=$missing" >> "$DONE"
