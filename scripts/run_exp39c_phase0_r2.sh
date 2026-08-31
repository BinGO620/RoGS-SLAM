#!/bin/bash
# exp39 Step C Phase 0 重跑 —— 残差来源 bug 修复后
#
# 装置：balloon × seed0 × {H, E} = 2 run，两卡并行
# H = 硬 mask（对照臂）
# E = EMA 治疗臂（mapping_ema=true）
#
# 判据：
#   bias_suppression > 0 → 进 Phase 1
#   bias_suppression 仍反 → EMA 死
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_exp39c_phase0_r2.sh > results/runs/EXP39c_phase0_r2/launcher.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/EXP39c_phase0_r2; mkdir -p "$OUT"
DONE="$OUT/done.flag"; : > "$DONE"
MAXJOBS=${MAXJOBS:-1}

# ---- 配置 ----
CFG_HARD="configs/rgbd/experiments/exp39_mapping_soft/exp39c_hard_balloon.yaml"
CFG_EMA="configs/rgbd/experiments/exp39_mapping_soft/exp39c_ema_balloon.yaml"
SEQ=balloon
SEED=0

# ---- precheck ----
for cfg in "$CFG_HARD" "$CFG_EMA"; do
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
done

# 检查远程 HEAD 与本地一致
REMOTE_HEAD=$(git rev-parse HEAD)
LOCAL_HEAD=$(ssh cb@172.16.227.2 'cd /data/monogs-ours && git rev-parse HEAD' 2>/dev/null || echo "unknown")
if [ "$REMOTE_HEAD" != "$LOCAL_HEAD" ]; then
  echo "WARN: remote HEAD $REMOTE_HEAD != local HEAD $LOCAL_HEAD" >> "$DONE"
fi

# ---- 运行 ----
echo "=== $(date +%H:%M:%S) START H (GPU 0) ===" >> "$DONE"
CUDA_VISIBLE_DEVICES=0 $PY slam.py --config "$CFG_HARD" --fast --seed "$SEED" \
  --results-root "$OUT" --experiment-name "EXP39C-r2-hard-balloon" \
  > "$OUT/hard_balloon_seed0.consolelog" 2>&1 &
PID_HARD=$!

echo "=== $(date +%H:%M:%S) START E (GPU 1) ===" >> "$DONE"
CUDA_VISIBLE_DEVICES=1 $PY slam.py --config "$CFG_EMA" --fast --seed "$SEED" \
  --results-root "$OUT" --experiment-name "EXP39C-r2-ema-balloon" \
  > "$OUT/ema_balloon_seed0.consolelog" 2>&1 &
PID_EMA=$!

# ---- 等待 ----
wait $PID_HARD; RC_HARD=$?
echo "=== $(date +%H:%M:%S) EXIT hard rc=$RC_HARD ===" >> "$DONE"
wait $PID_EMA; RC_EMA=$?
echo "=== $(date +%H:%M:%S) EXIT ema rc=$RC_EMA ===" >> "$DONE"

# ---- 收集 ATE ----
echo "" >> "$DONE"
echo "--- ATE summary ---" >> "$DONE"
for log in "$OUT"/*_balloon_seed0.consolelog; do
  name=$(basename "$log" .consolelog)
  ate=$(grep -oP 'ATE\s+\K[0-9.]+' "$log" 2>/dev/null | tail -1 || echo "N/A")
  echo "  $name: ATE=$ate cm" >> "$DONE"
done

echo "=== ALL DONE (hard=$RC_HARD ema=$RC_EMA) ===" >> "$DONE"
