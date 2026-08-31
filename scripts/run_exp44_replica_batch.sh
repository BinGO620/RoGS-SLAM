#!/bin/bash
# exp44 Replica 批量调度（office0 + room0 × {vanilla, combined} = 4 run）
# 依赖：flow_raft 已为两个场景构建完成
set -u
REPO=${REPO:-/home/jiangwenheng/cron/monogs-ours}; cd "$REPO"
PY=${PY:-/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python}
OUT=${OUT:-results/runs/EXP44_replica_full}; mkdir -p "$OUT"
LOG="$OUT/dispatch.log"

STAGGER=30

# ---- 门 B-0：无残留 slam 进程 ----
n_slam=$(pgrep -fc '^/home.*bin/python slam.py' 2>/dev/null || true)
[ -z "$n_slam" ] && n_slam=0
if [ "$n_slam" -gt 0 ]; then
  echo "ABORT: B-0 残留 slam 进程 $n_slam 个" >> "$LOG"; exit 1
fi
echo "GATE B-0 PASS: 0 残留进程" >> "$LOG"

# ---- 门 B-1：两卡显存 < 1 GB ----
for gi in 0 1; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "$gi" | tr -d ' ')
  if [ "$used" -gt 1000 ]; then
    echo "ABORT: B-1 GPU${gi} 显存 ${used}MB > 1000MB" >> "$LOG"; exit 1
  fi
done
echo "GATE B-1 PASS: 两卡空闲" >> "$LOG"

# ---- 门 D-0：flow_raft 就位 ----
for s in office0 room0; do
  n=$(ls datasets/replica/$s/flow_raft/*.npy 2>/dev/null | wc -l)
  if [ "$n" -lt 1900 ]; then
    echo "ABORT: D-0 $s flow_raft 不足 ($n < 1900)" >> "$LOG"; exit 1
  fi
  echo "GATE D-0 PASS: $s flow_raft $n files" >> "$LOG"
done
echo "" >> "$LOG"

# ---- Round 1：combined（需要 flow）----
SEED=0
run_pair() {
  local seq=$1 rnd=$2
  local cfg_c="configs/rgbd/experiments/exp44_replica/exp44_vanilla_${seq}.yaml"
  local cfg_t="configs/rgbd/experiments/exp44_replica/exp44_combined_${seq}.yaml"
  echo "=== $(date +%H:%M:%S) R$rnd START $seq (GPU0=combined GPU1=vanilla) ===" >> "$LOG"
  CUDA_VISIBLE_DEVICES=0 $PY slam.py --config "$cfg_t" --eval --seed "$SEED" \
    --results-root "$OUT" --experiment-name "EXP44-combined-${seq}" \
    > "$OUT/combined_${seq}.consolelog" 2>&1 &
  local p1=$!
  sleep "$STAGGER"
  CUDA_VISIBLE_DEVICES=1 $PY slam.py --config "$cfg_c" --eval --seed "$SEED" \
    --results-root "$OUT" --experiment-name "EXP44-vanilla-${seq}" \
    > "$OUT/vanilla_${seq}.consolelog" 2>&1 &
  local p2=$!
  wait $p1; local rc1=$?
  echo "=== $(date +%H:%M:%S) R$rnd EXIT $seq combined rc=$rc1 ===" >> "$LOG"
  wait $p2; local rc2=$?
  echo "=== $(date +%H:%M:%S) R$rnd EXIT $seq vanilla rc=$rc2 ===" >> "$LOG"
}

run_pair "office0" 1
sleep 5
run_pair "room0" 2

echo "" >> "$LOG"

# ---- 读数 ----
$PY - <<'PYEOF' >> "$LOG" 2>&1
import csv, os, glob
from pathlib import Path

out = Path("results/runs/EXP44_replica_full")
print("=" * 60)
print("EXP44 Replica 结果")
print("=" * 60)
for seq in ["office0", "room0"]:
    print(f"\n--- {seq} ---")
    for arm in ("combined", "vanilla"):
        pattern = f"**/EXP44-{arm}-{seq}/**/tracking_raw.csv"
        csvs = list(out.glob(pattern))
        if not csvs:
            csvs = list(out.glob(f"**/{seq}*/tracking_raw.csv"))
        for c in csvs:
            with open(c) as f:
                for r in csv.DictReader(f):
                    if r.get("ate_rmse_cm"):
                        v = float(r["ate_rmse_cm"])
                        verdict = "PASS" if v <= 1.0 else ("MARGINAL" if v <= 2.0 else "FAIL")
                        print(f"  {arm}: ATE={v:.4f} cm ({verdict})")
                        break
                else:
                    print(f"  {arm}: no ATE")
            break
        else:
            print(f"  {arm}: NOT FOUND")
PYEOF

echo "" >> "$LOG"
echo "=== EXP44 ALL DONE $(date +%H:%M:%S) ===" >> "$LOG"
