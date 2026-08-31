#!/bin/bash
# insertion 通道分离 —— 补 2×2 因子设计的第四格（exp35, 2026-08-21）
#
# 预注册：results/evidence/insertion_channel_prereg.md（发批前已 commit）
#
# exp34 的 PBA 判决把 44–80% 的增益定位到 BA 侧 mask（mask_mapping），诚实边界自己
# 写下缺口：剩下 20–56% 在 mask_insertion 和 tracking 侧，未分离。本批翻的是
# mask_insertion（与 PBA 完全对偶），补齐第四格：
#
#         | insertion=T          | insertion=F
#   ------|----------------------|--------------------------
#   map=T | eboth      ✅已测    | tracking_only  ← 本批
#   map=F | PBA        ✅已测    | maskfree       ✅已测
#
# 三格已有 ⇒ 本批只跑 tracking_only，对照臂**不重跑**（同机同并发，exp34 已验
# eboth 复跑 3.06→3.18 = +3.9% < 6% 噪声地板）。
#
# 序列 = balloon / f3_wk_xyz / pt1（可分解性门 §3 已过；mv_no_box 比值 0.54 排除）。
# 单变量隔离由 tests/test_pba_ba_coupling.py::TestPBATrackingOnlyConfigs 钉住（8 passed）。
#
# 分阶预算（硬纪律）：
#   PHASE=0  balloon seed0 单 run，只验装置门 G1/G2/G3，不看 ATE。门不过就停。
#   PHASE=1  其余 8 run（balloon seed1/2 + f3_wk_xyz ×3 + pt1 ×3）。
#
# 用法（jiangwenheng 上）：
#   PHASE=0 nohup bash scripts/run_insertion_channel_3090.sh > results/runs/insertion_p0.log 2>&1 &
#   PHASE=1 nohup bash scripts/run_insertion_channel_3090.sh > results/runs/insertion_p1.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/PBA}; mkdir -p "$OUT"
PHASE=${PHASE:-0}
DONE="$OUT/insertion_phase${PHASE}.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-6}

if [ "$PHASE" = "0" ]; then
  SEQS=${SEQS:-"balloon"}; SEEDS=${SEEDS:-"0"}
else
  SEQS=${SEQS:-"balloon f3_wk_xyz pt1"}; SEEDS=${SEEDS:-"0 1 2"}
fi

# ---- precheck：config 存在 + 数据存在 + frozen flow 非空（exp24 静默空转事故）----
for seq in $SEQS; do
  cfg="configs/rgbd/experiments/pba_ba_coupling/pba_tracking_only_${seq}.yaml"
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
  # 装置门 G0（发批前）：解析后必须 mapping=T / insertion=F，否则臂标是错的
  iso=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
c = load_config('$cfg')['SemanticMask']
print('OK' if (c['mask_mapping'] and not c['mask_insertion']) else 'BAD')" 2>/dev/null)
  [ "$iso" = "OK" ] || { echo "ABORT: $seq 臂标错 (mapping/insertion = $iso)" >> "$DONE"; exit 1; }
  dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
  [ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: $seq 数据缺 ($dp)" >> "$DONE"; exit 1; }
  n=$(ls "$dp"/flow_raft/*.npy 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] || { echo "ABORT: $seq flow_raft 空 ($dp)" >> "$DONE"; exit 1; }
  echo "precheck OK $seq iso=$iso flow=$n" >> "$DONE"
done
echo "$(date +%F' '%H:%M) LAUNCH phase=$PHASE seqs=[$SEQS] seeds=[$SEEDS] maxjobs=$MAXJOBS" >> "$DONE"

# pgrep 必须锚定 argv 起始（exp19 一晚咬三次：非锚定会匹配监控命令自身）
SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

for seq in $SEQS; do
  for seed in $SEEDS; do
    cfg="configs/rgbd/experiments/pba_ba_coupling/pba_tracking_only_${seq}.yaml"
    outnm="pba_tracking_only_${seq}_seed${seed}"
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

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done

missing=0
for seq in $SEQS; do for seed in $SEEDS; do
  outnm="pba_tracking_only_${seq}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
done; done

# ---- 装置门 G1（门必须不响）：本臂 console 不得出现插入门日志 -------------------
# 只验一边会把静默退化读成 null-vs-null（R2-P04 的 G5 教训），G2 在判决脚本里验对照臂。
gate_violations=0
for seq in $SEQS; do for seed in $SEEDS; do
  log="$OUT/pba_tracking_only_${seq}_seed${seed}.consolelog"
  [ -f "$log" ] || continue
  hits=$(grep -c "Semantic insertion gate" "$log" 2>/dev/null || echo 0)
  if [ "$hits" -gt 0 ]; then
    echo "G1_VIOLATION pba_tracking_only_${seq}_seed${seed}: 插入门响了 $hits 次（开关没生效）" >> "$DONE"
    gate_violations=$((gate_violations+1))
  else
    echo "G1_OK pba_tracking_only_${seq}_seed${seed}: 插入门 0 次（开关生效）" >> "$DONE"
  fi
done; done

echo "INSERTION_PHASE${PHASE}_DONE $(date) missing=$missing g1_violations=$gate_violations" >> "$DONE"
