#!/bin/bash
# 静态带读数第二批（exp36）—— 把「同一批物理 run」这件事补齐，并把新臂放进渲染图
#
# 第一批（render_static_band_3090.sh）暴露了一个配对问题：balloon 的 eboth 在
#   ATE 读数     -> T2 根（trackside_verdict 的 root 优先级）
#   全帧渲染读数 -> PBA 根（exp35 的 collect_pba_rendering 的 root 优先级）
# 两者是**同 config 的两次不同物理 run**。要把「全帧 PSNR vs 静态带 PSNR」摆在一起，
# 两个指标必须来自同一次 run，否则次序翻转可能只是复跑差（balloon 上 eboth 复跑
# 3.06 -> 3.18 = 3.9%）。
#
# 本批做两件事：
#   ① 给 PBA 根的 eboth balloon ×3 补静态带 -> 与它们已有的全帧读数同 run 配对；
#   ② 给 exp36 的 trackside balloon ×3 补全帧 -> 新臂进入渲染图，
#      作为 balloon 上那条 INDETERMINATE 的**独立观测量旗标**（⚠ 描述性、非预注册，
#      不能拿来翻 §5 的判决，只能作为下一个预注册问题的线索）。
#
# 用法：nohup bash scripts/render_static_band_round2_3090.sh > results/runs/staticband2.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
DONE=results/runs/PBA/staticband_round2.done; : > "$DONE"
MAXJOBS=${MAXJOBS:-3}

PAT="^${PY} scripts/(eval_vacated_posthoc|r2_p2_t_offline_render)\.py"
njobs() { pgrep -c -f "$PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(njobs)" -ge "$MAXJOBS" ]; do sleep 15; done; }

inner_of() {  # 最新时间戳目录
  local d; d=$(find "$1" -mindepth 3 -maxdepth 6 -name "config.yml" 2>/dev/null | sort | tail -1)
  [ -n "$d" ] && dirname "$d"
}
ensure_link() {
  local inner="$1"
  if [ ! -e "$inner/point_cloud/final_after_opt" ]; then
    [ -f "$inner/point_cloud/final/point_cloud.ply" ] || return 1
    ln -sfn "$REPO/$inner/point_cloud/final" "$inner/point_cloud/final_after_opt"
    echo "LINKED $inner" >> "$DONE"
  fi
}

# ---- ① PBA 根 eboth balloon 的静态带 ------------------------------------------
for seed in 0 1 2; do
  outer="results/runs/PBA/eboth_balloon_seed${seed}"
  inner=$(inner_of "$outer") || true
  [ -n "${inner:-}" ] || { echo "NO_CONFIG $outer" >> "$DONE"; continue; }
  ensure_link "$inner" || { echo "NO_PLY $inner" >> "$DONE"; continue; }
  [ -f "$inner/posthoc_staticband/posthoc_summary.json" ] && { echo "SKIP $inner" >> "$DONE"; continue; }
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) STATICBAND $inner on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY scripts/eval_vacated_posthoc.py "$inner" --out-name posthoc_staticband \
    >> "${outer}.staticband.log" 2>&1 &
  sleep 4
done

# ---- ② trackside balloon 的全帧 -----------------------------------------------
for seed in 0 1 2; do
  outer="results/runs/PBA/pba_trackside_only_balloon_seed${seed}"
  inner=$(inner_of "$outer") || true
  [ -n "${inner:-}" ] || { echo "NO_CONFIG $outer" >> "$DONE"; continue; }
  ensure_link "$inner" || { echo "NO_PLY $inner" >> "$DONE"; continue; }
  [ -f "$inner/posthoc_fullframe/fullframe_summary.json" ] && { echo "SKIP $inner" >> "$DONE"; continue; }
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) FULLFRAME $inner on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY scripts/r2_p2_t_offline_render.py "$inner" --no-band-check \
    >> "${outer}.fullframe.log" 2>&1 &
  sleep 4
done

while [ "$(njobs)" -gt 0 ]; do sleep 20; done
echo "ROUND2_DONE $(date)" >> "$DONE"
