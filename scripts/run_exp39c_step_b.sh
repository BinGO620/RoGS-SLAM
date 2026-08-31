#!/bin/bash
# exp39 Step C Phase 0 — Step B: E-decomposed + E-scrambled
#
# 装置：balloon × seed0 × {E, E-scrambled} = 2 run，两卡并行
# E = EMA（含 mu^2/sigma^2 分量分解诊断）
# E-scrambled = D-3 打乱实验（空间打乱 EMA 状态）
#
# 判据：
#   E-decomposed: mu^2_dyn << mu^2_stat → M1（吸收正反馈）
#   E-scrambled ATE ≈ H → EMA 空间结构有害（M1 类）
#   E-scrambled ATE ≈ E → 问题在边际分布，不在空间结构
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_exp39c_step_b.sh > results/runs/EXP39c_step_b/launcher.log 2>&1 &
set -u
# REPO/PY overridable so tests/test_exp39c_step_b_gates.py can drive the gates below
# with stubbed pgrep/nvidia-smi. A gate that is never exercised is not a gate
# (exp33 criterion #11), and these two gates exist precisely because Step B's first
# dispatch skipped them.
REPO=${REPO:-/home/jiangwenheng/cron/monogs-ours}; cd "$REPO"
PY=${PY:-/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python}
OUT=${OUT:-results/runs/EXP39c_step_b}; mkdir -p "$OUT"
DONE="$OUT/done.flag"; : > "$DONE"
MAXJOBS=${MAXJOBS:-1}
STAGGER=${STAGGER:-30}

# ---- 配置 ----
CFG_EMA="configs/rgbd/experiments/exp39_mapping_soft/exp39c_ema_balloon.yaml"
CFG_SCR="configs/rgbd/experiments/exp39_mapping_soft/exp39c_escrambled_balloon.yaml"
SEQ=balloon
SEED=0

# ---- precheck ----
for cfg in "$CFG_EMA" "$CFG_SCR"; do
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
done

# 门 B-0：发批前环境必须干净。exp39 Step B 首发就栽在这里 ——
# 前一次崩溃（IndexError）留下的 frontend/backend 进程仍持有 ~14 GB 显存，
# 两臂在 frame ~300 双双 OOM。整数守卫 + `|| true`（不接 `|| echo 0`，见 exp37 门缺陷）。
n_slam=$(pgrep -fc 'slam[.]py --config' 2>/dev/null || true)
[ -n "$n_slam" ] || n_slam=0
if [ "$n_slam" -gt 0 ] 2>/dev/null; then
  echo "ABORT: 还有 $n_slam 个 slam.py 在跑，先清场（kill -9 <pid>）" >> "$DONE"; exit 1
fi
# 门 B-1：两张卡的残留显存都必须低于 1 GB（干净时约 150-300 MiB）
while read -r idx used; do
  used=${used%% *}
  if [ "$used" -gt 1024 ] 2>/dev/null; then
    echo "ABORT: GPU $idx 残留 ${used} MiB > 1024，有孤儿进程占显存" >> "$DONE"; exit 1
  fi
done < <(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | tr ',' ' ')
echo "GATE B-0/B-1 PASS: 0 slam procs, 两卡显存均 < 1 GB" >> "$DONE"

# ---- 运行 ----
echo "=== $(date +%H:%M:%S) START E-decomposed (GPU 0) ===" >> "$DONE"
CUDA_VISIBLE_DEVICES=0 $PY slam.py --config "$CFG_EMA" --fast --seed "$SEED" \
  --results-root "$OUT" --experiment-name "EXP39C-stepB-ema" \
  > "$OUT/ema_balloon_seed0.consolelog" 2>&1 &
PID_EMA=$!

# 错开 STAGGER 秒：两臂的初始化峰值不叠在同一时刻（虽在不同卡，仍共享 CPU/PCIe）
sleep "$STAGGER"

echo "=== $(date +%H:%M:%S) START E-scrambled (GPU 1) ===" >> "$DONE"
CUDA_VISIBLE_DEVICES=1 $PY slam.py --config "$CFG_SCR" --fast --seed "$SEED" \
  --results-root "$OUT" --experiment-name "EXP39C-stepB-escrambled" \
  > "$OUT/escrambled_balloon_seed0.consolelog" 2>&1 &
PID_SCR=$!

# ---- 等待 ----
wait $PID_EMA; RC_EMA=$?
echo "=== $(date +%H:%M:%S) EXIT ema rc=$RC_EMA ===" >> "$DONE"
wait $PID_SCR; RC_SCR=$?
echo "=== $(date +%H:%M:%S) EXIT scrambled rc=$RC_SCR ===" >> "$DONE"

# ---- 收集 ATE ----
echo "" >> "$DONE"
echo "--- ATE summary ---" >> "$DONE"
for log in "$OUT"/*_balloon_seed0.consolelog; do
  name=$(basename "$log" .consolelog)
  ate=$(grep -oP 'ATE\s+\K[0-9.]+' "$log" 2>/dev/null | tail -1 || echo "N/A")
  echo "  $name: ATE=$ate cm" >> "$DONE"
done

echo "=== ALL DONE (ema=$RC_EMA scrambled=$RC_SCR) ===" >> "$DONE"
