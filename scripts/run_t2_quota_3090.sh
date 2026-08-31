#!/bin/bash
# T2 自适应配额 MAD 隔离 — 3090 双卡判决批（exp32, 2026-08-20）。
#
# 矩阵 = ARMS × 5 序列 × 3 seed。默认 ARMS 是 4 个（两个 control + qfree + eboth）；
# T2-scale 臂单独发第二波，因为它的常数 c 按预注册定义 = E-both 实测
# median(mad_tau_after / mad_tau_before)，必须先有 E-both 的盘上数据才能定值。
#
# 为什么两个 control 都要跑：qfree 建在 mask-free 底座、eboth 建在 mask-ON 底座，
# 底座不同 ⇒ 一个 control 撑不起两个臂的 pairwise 差分（config 合同见
# tests/test_retrofit_configs.py::test_each_treatment_differs_from_its_control_only_in_the_mechanism）。
#
# 判据（预注册，见 REVIEW.md §7 与 NEXT_SESSION_PROMPT §3.2）：
#   1. 机制自证先于指标：mad_excl_applied_frac ≥ 0.95 且 max_mad_zero_frac_after ≤ 0.45；
#      E-both 还须 mad_excl_semantic = 1。不满足则 ATE 读数无意义。
#   2. 主判据：E-both / Q-free 相对各自 control 的动态 ATE。
#   3. 静态护栏：{f3_st_hf, f2_xyz} ATE 劣化 ≤ 5%，mean_w 不得进一步下降。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/T2/T2-QUOTA-3090}; mkdir -p "$OUT"
DONE="$OUT/t2.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-4}

ARMS=${ARMS:-"eboth qfree control_maskon control_maskfree"}
# 序列顺序 = 判决价值密度顺序，**不是**字母序。f2_xyz 有 3669 帧，单 run 在
# 4 并发下实测 ~3.2h ⇒ 它一条就占整个队列的 ~9.6 GPU-h。把它排最后，
# 前面四条序列的完整 3-seed 表先落地，判决不必等最长的那条。
SEQS=${SEQS:-"balloon mv_no_box crowd2 f3_st_hf f2_xyz"}
SEEDS=${SEEDS:-"0 1 2"}
# 已在飞或已知要跳过的 run 名（空格分隔）。重启 launcher 时用它挡住"产物还没落盘、
# 但进程还活着"的 run —— 只靠 tracking_raw.csv 判存在会把它们重复发一遍。
SKIP=${SKIP:-""}

# precheck：config 必须存在 + 数据目录存在 + frozen flow 非空（exp24 静默空转事故）
for arm in $ARMS; do
  for seq in $SEQS; do
    cfg="configs/rgbd/experiments/t2_mad_quota/t2_${arm}_${seq}.yaml"
    [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
  done
done
for seq in $SEQS; do
  cfg="configs/rgbd/experiments/t2_mad_quota/t2_eboth_${seq}.yaml"
  dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
  [ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: $seq 数据缺 ($dp)" >> "$DONE"; exit 1; }
  n=$(ls "$dp"/flow_raft/*.npy 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] || { echo "ABORT: $seq flow_raft 空 ($dp)" >> "$DONE"; exit 1; }
  echo "precheck OK $seq flow=$n" >> "$DONE"
done
echo "$(date +%F' '%H:%M) LAUNCH arms=[$ARMS] seqs=[$SEQS] seeds=[$SEEDS] maxjobs=$MAXJOBS" >> "$DONE"

SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

for seq in $SEQS; do
  for seed in $SEEDS; do
    for arm in $ARMS; do
      outnm="${arm}_${seq}_seed${seed}"
      [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm (done)" >> "$DONE"; continue; }
      case " $SKIP " in *" $outnm "*) echo "SKIP $outnm (in flight)" >> "$DONE"; continue;; esac
      wait_slot
      gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
            | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
      echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
      env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
        $PY slam.py --config configs/rgbd/experiments/t2_mad_quota/t2_${arm}_${seq}.yaml \
        --fast --seed "$seed" --results-root "$OUT/$outnm" \
        > "$OUT/$outnm.consolelog" 2>&1 &
      sleep 8
    done
  done
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done
missing=0
for seed in $SEEDS; do for seq in $SEQS; do for arm in $ARMS; do
  outnm="${arm}_${seq}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
done; done; done
echo "T2_3090_WAVE_DONE $(date) missing=$missing" >> "$DONE"
