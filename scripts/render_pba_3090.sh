#!/bin/bash
# render_pba_3090.sh — PBA 离线全帧重渲（Task 2: 渲染指标）
# =============================================================================
# 渲染 PBA 实验的 PLY 文件，得到 PSNR/SSIM/LPIPS/Depth-L1 指标。
# PBA 实验 = 2×2 因子设计：{mask_mapping: T/F} × {mask_insertion: T/F}
#   - eboth (control): mapping=T, insertion=T
#   - PBA (mapping off): mapping=F, insertion=T
#   - tracking-only (insertion off): mapping=T, insertion=F  ← 需要新跑
#   - maskfree: mapping=F, insertion=F
#
# 本脚本只渲染已有的 PBA runs（eboth + mapping_off + maskfree）。
# tracking-only 需要先跑 SLAM 再渲染。
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/render_pba_3090.sh > results/runs/render_pba.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
RENDER_SCRIPT=scripts/r2_p2_t_offline_render.py
PBA_DIR=results/runs/PBA
LOG=results/runs/render_pba.log

echo "$(date) START PBA rendering" > "$LOG"

# 收集所有 PBA run 目录（带 PLY + trajectory）
RUNLIST=""
for d in "$PBA_DIR"/*/; do
  [ -d "$d" ] || continue
  case "$(basename "$d")" in *.consolelog|*.done|tables|monitor.log) continue;; esac
  latest=""
  for ts in "$d"/datasets_*/*/seed_*/*/; do
    ts="${ts%/}"
    [ -f "$ts/config.yml" ] || continue
    [ -f "$ts/plot/trj_full_final.json" ] || continue
    # 渲染脚本读 final_after_opt/，已建好 symlink
    [ -f "$ts/point_cloud/final_after_opt/point_cloud.ply" ] || continue
    if [ -z "$latest" ] || [ "$ts" \> "$latest" ]; then latest="$ts"; fi
  done
  [ -n "$latest" ] || { echo "NO_RENDER_INPUT $(basename "$d")" >> "$LOG"; continue; }
  # 跳过已有渲染结果的
  if [ -f "$latest/posthoc_fullframe/fullframe_summary.json" ]; then
    echo "SKIP $(basename "$d")" >> "$LOG"; continue
  fi
  RUNLIST="$RUNLIST
$latest"
done

n=$(echo "$RUNLIST" | sed '/^$/d' | wc -l)
echo "envelope: $n runs to render" >> "$LOG"

# 并发渲染（2 GPU slot）
running_render() { pgrep -af 'r2_p2_t_offline_render.py' 2>/dev/null | grep -cE "/python[0-9]* +$RENDER_SCRIPT" || true; }
wait_slot() { while [ "$(running_render)" -ge 2 ]; do sleep 20; done; }

i=0
for ts in $RUNLIST; do
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  n_cards=$(nvidia-smi -L 2>/dev/null | wc -l)
  if [ -z "$gpu" ] || [ "${n_cards:-0}" = "0" ]; then gpu=$((i % 2)); fi
  i=$((i+1))
  name=$(echo "$ts" | sed "s|$PBA_DIR/||;s|/datasets_.*||")
  echo "$(date +%H:%M) RENDER gpu$gpu $name" >> "$LOG"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY "$RENDER_SCRIPT" --no-band-check "$ts" \
    > "$ts.render.consolelog" 2>&1 &
  sleep 8
done

while [ "$(running_render)" -gt 0 ]; do sleep 30; done

# 收集结果
missing=0
for ts in $RUNLIST; do
  if [ ! -f "$ts/posthoc_fullframe/fullframe_summary.json" ]; then
    echo "MISSING $ts" >> "$LOG"; missing=$((missing+1))
  fi
done
echo "RENDER_PBA_ALL_DONE $(date) envelope=$n missing=$missing" >> "$LOG"
