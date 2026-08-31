#!/bin/bash
# T3 语义 Alpha 覆盖 — "保本试水"（exp32, 2026-08-20）。
#
# 规模按 REVIEW §7.2 的自我建议降到 3 序列 × 1 seed × 2 臂 = 6 run：先只买机制自证
# 与两条护栏，不投 3-seed 完整判决预算。smoke 实测 hit=130 / geom_front=104 /
# override=9 说明语义命中的高斯绝大多数贴合观测面（本来就不是 ghost），T3 真正清掉的
# 占地图比例极小 —— 值不值得完整预算，由这 6 run 的误杀率与渲染护栏决定。
#
# 与 T2 不同这里必须 --eval（不是 --fast）：渲染护栏读的 band-PSNR 来自
# eval_rendering 写的 band_metrics.json，--fast 会把 eval_rendering 关掉。
#
# 判据（拍板③：全部 arm 内闭环，绝不与主干比）：
#   1. 机制自证：alpha_sem_override_total > 0 且日志出现 carved > 0；若为 0 先看
#      hit / geom_front / override 三计数定位哪一环空，不看 ATE。
#   2. 误杀死线：被 override 的高斯投影落在 dynamic_mask_gtmc 静态区的比例 ≤ 5%。
#   3. 渲染护栏：band-PSNR 相对 A-off 不劣化。
#   4. ATE 只作观察项。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/T3/T3-SEMALPHA-3090}; mkdir -p "$OUT"
DONE="$OUT/t3.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-2}

ARMS=${ARMS:-"sem off"}
SEQS=${SEQS:-"balloon mv_no_box pt2"}
SEEDS=${SEEDS:-"0"}

for arm in $ARMS; do
  for seq in $SEQS; do
    cfg="configs/rgbd/experiments/t3_semantic_alpha/t3_${arm}_${seq}.yaml"
    [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
    dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
    [ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: $arm/$seq 数据缺 ($dp)" >> "$DONE"; exit 1; }
    # 误杀护栏的 held-out 掩码必须在盘上，否则这一批跑完也判不了
    g=$(ls "$dp"/dynamic_mask_gtmc 2>/dev/null | wc -l)
    [ "$g" -gt 0 ] || { echo "ABORT: $seq dynamic_mask_gtmc 空 ($dp)" >> "$DONE"; exit 1; }
    echo "precheck OK $arm/$seq gtmc=$g" >> "$DONE"
  done
done
echo "$(date +%F' '%H:%M) LAUNCH arms=[$ARMS] seqs=[$SEQS] seeds=[$SEEDS] maxjobs=$MAXJOBS" >> "$DONE"

SLAM_PAT="^${PY} slam\.py"
t3_count() { pgrep -c -f "${SLAM_PAT}.*t3_semantic_alpha" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(t3_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

for seed in $SEEDS; do
  for seq in $SEQS; do
    for arm in $ARMS; do
      outnm="${arm}_${seq}_seed${seed}"
      [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm" >> "$DONE"; continue; }
      wait_slot
      gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
            | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
      echo "$(date +%H:%M) RUN t3_$outnm on gpu$gpu" >> "$DONE"
      env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
        $PY slam.py --config configs/rgbd/experiments/t3_semantic_alpha/t3_${arm}_${seq}.yaml \
        --eval --seed "$seed" --results-root "$OUT/$outnm" \
        > "$OUT/$outnm.consolelog" 2>&1 &
      sleep 8
    done
  done
done

while [ "$(t3_count)" -gt 0 ]; do sleep 30; done
missing=0
for seed in $SEEDS; do for seq in $SEQS; do for arm in $ARMS; do
  outnm="${arm}_${seq}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING t3_$outnm" >> "$DONE"; missing=$((missing+1)); }
done; done; done
echo "T3_3090_ALL_DONE $(date) missing=$missing" >> "$DONE"
