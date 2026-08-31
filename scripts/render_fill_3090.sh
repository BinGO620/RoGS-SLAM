#!/bin/bash
# 补渲缺格：balloon 的 maskfree 臂 + 新跑的 tracking_only 九臂（exp35 Task 2 收尾）
#
# 为什么要补：pba_render_verdict.py 的三臂比较缺 balloon/maskfree 一格 —— 它的 run 在
# T2-QUOTA-3090 而不在 PBA 目录里，上一轮 render_pba_3090.sh 的扫描范围没覆盖到。
# PLY + trj_full_final 都在，可直接离线渲。
# 同时把本轮新跑的 9 个 tracking_only run 也渲上，好让 2×2 四格在渲染侧也齐。
#
# ★ 硬前置：不与 tracking 并跑（主表 provenance 记过同 seed 两次 ATE 15.72 vs 21.42 的
#   运行间非确定性，机制 = 每帧 mapping 迭代数随 wall-clock 变化）。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
RENDER=scripts/r2_p2_t_offline_render.py
LOG=results/runs/render_fill.log
: > "$LOG"

# pgrep 必须锚定 argv 起始
n_slam=$(pgrep -c -f "^${PY} slam\.py" 2>/dev/null || echo 0)
if [ "$n_slam" -gt 0 ]; then
  echo "ABORT: 还有 $n_slam 个 slam.py 在跑，渲染会改变其 wall-clock 从而污染 ATE" >> "$LOG"
  exit 1
fi
echo "$(date) START fill-in rendering (slam procs=0)" >> "$LOG"

TARGETS=""
for d in results/runs/T2/T2-QUOTA-3090/control_maskfree_balloon_seed*/ \
         results/runs/PBA/pba_tracking_only_*/; do
  [ -d "$d" ] || continue
  case "$(basename "$d")" in *.consolelog|*.done|tables) continue;; esac
  latest=""
  for ts in "$d"datasets_*/*/seed_*/*/; do
    ts="${ts%/}"
    [ -f "$ts/config.yml" ] || continue
    [ -f "$ts/plot/trj_full_final.json" ] || continue
    [ -f "$ts/point_cloud/final/point_cloud.ply" ] || continue
    if [ -z "$latest" ] || [ "$ts" \> "$latest" ]; then latest="$ts"; fi
  done
  [ -n "$latest" ] || { echo "NO_INPUT $(basename "$d")" >> "$LOG"; continue; }
  [ -f "$latest/posthoc_fullframe/fullframe_summary.json" ] && { echo "SKIP $(basename "$d")" >> "$LOG"; continue; }
  # 渲染脚本写死读 final_after_opt/；这些 run 只存了 final/ ⇒ 绝对路径软链适配
  [ -e "$latest/point_cloud/final_after_opt" ] || \
    ln -s "$(realpath "$latest/point_cloud/final")" "$latest/point_cloud/final_after_opt"
  TARGETS="$TARGETS
$latest"
done

n=$(echo "$TARGETS" | sed '/^$/d' | wc -l)
echo "envelope: $n runs" >> "$LOG"

running() { pgrep -c -f "^${PY} $RENDER" 2>/dev/null || echo 0; }
i=0
for ts in $TARGETS; do
  while [ "$(running)" -ge 2 ]; do sleep 20; done
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  [ -n "$gpu" ] || gpu=$((i % 2)); i=$((i+1))
  echo "$(date +%H:%M) RENDER gpu$gpu $ts" >> "$LOG"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY "$RENDER" --no-band-check "$ts" > "$ts.render.consolelog" 2>&1 &
  sleep 8
done
while [ "$(running)" -gt 0 ]; do sleep 30; done

missing=0
for ts in $TARGETS; do
  [ -f "$ts/posthoc_fullframe/fullframe_summary.json" ] || { echo "MISSING $ts" >> "$LOG"; missing=$((missing+1)); }
done
echo "RENDER_FILL_DONE $(date) envelope=$n missing=$missing" >> "$LOG"
