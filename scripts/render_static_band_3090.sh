#!/bin/bash
# 静态带渲染读数（exp36）—— 检验 exp35 发现的「全帧 PSNR 在动态序列上有偏」
#
# exp35 渲染侧读到 balloon 上 maskfree 的全帧 PSNR 19.58 > eboth 17.31（+2.27 dB），
# 而 SSIM 恰好相反。当时提出的可检验解释：**全帧 PSNR 奖励「把动态人烤进地图」**
# —— GT 帧里有人的像素上，鬼影比空洞更像人。
#
# 验法（exp35 §2 写下的两条之一，本脚本执行第二条）：改用**静态带**口径，支持集
#   M_static = (GT 深度有效) AND NOT(冻结的 GTMC 动态 mask)
# 方法无关、四臂共用同一套 mask（utils/eval_utils.py::eval_static_background_raw）。
# 若排除动态像素后 PSNR 的次序翻转/消失，解释成立。
#
# 复用已有装置，不写新渲染路径：scripts/eval_vacated_posthoc.py 正是「从 run 落盘的
# config + final PLY + trj_full_final 重建 eval 状态并重跑 eval_static_background_raw」。
# 附带产出 ghost/vacated 列（人刚离开的区域的重建质量）—— 那是「烤进地图」假设最直接的
# 观测量，比 PSNR 次序更接近机制。
#
# ⚠ 适用域：只有 balloon 与 pt1 有冻结 GTMC mask（440 / 582 张）；f3_wk_xyz 是 0 张
#   ⇒ 静态带口径在 TUM 那条序列上**不可得**，本脚本只跑 balloon（异常就在 balloon）。
# ⚠ 忠实性锚缺失：这些 run 是 --fast 跑的，盘上没有 band_metrics.json
#   ⇒ eval_vacated_posthoc 的 band 对齐检查会被跳过（band_check=null）。四臂走**同一条**
#   posthoc 路径，跨臂比较仍是同口径；但「与在线 eval 逐 dB 对齐」这条锚这一批拿不到，
#   必须在读数里写明（全帧那批 39 run 也是同样情况）。
#
# 用法（jiangwenheng 上，且必须与 tracking 批错开跑 —— 渲染与 tracking 并跑会改
# wall-clock，虽然 exp36 实测 mapping_iterations 对并发不敏感，纪律仍然照守）：
#   nohup bash scripts/render_static_band_3090.sh > results/runs/staticband.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
DONE=results/runs/PBA/staticband_balloon.done; : > "$DONE"
MAXJOBS=${MAXJOBS:-3}

# 臂 -> 根目录：与 scripts/trackside_verdict.py 的 root 优先级一致，**保证 ATE 与渲染
# 读的是同一批物理 run**（exp35 的全帧那批不是：ATE 取自 T2 根、渲染取自 PBA 根的复跑）。
RUNS=""
for seed in 0 1 2; do
  RUNS="$RUNS results/runs/T2/T2-QUOTA-3090/eboth_balloon_seed${seed}"
  RUNS="$RUNS results/runs/T2/T2-QUOTA-3090/control_maskfree_balloon_seed${seed}"
  RUNS="$RUNS results/runs/PBA/pba_tracking_only_balloon_seed${seed}"     # = insertion-off
  RUNS="$RUNS results/runs/PBA/pba_trackside_only_balloon_seed${seed}"    # exp36 的新臂
done
RUNS="$RUNS results/runs/PBA/pba_mapping_off_balloon_3090_seed0"
RUNS="$RUNS results/runs/PBA/pba_mapping_off_balloon_seed1"
RUNS="$RUNS results/runs/PBA/pba_mapping_off_balloon_seed2"

PAT="^${PY} scripts/eval_vacated_posthoc\.py"
njobs() { pgrep -c -f "$PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(njobs)" -ge "$MAXJOBS" ]; do sleep 15; done; }

for outer in $RUNS; do
  [ -d "$outer" ] || { echo "MISSING_RUNDIR $outer" >> "$DONE"; continue; }
  # 最新的时间戳目录（有复跑的 run 目录会有两个；把选择写下来，别让它隐式发生）
  inner=$(find "$outer" -mindepth 3 -maxdepth 6 -name "config.yml" | sort | tail -1)
  inner=$(dirname "$inner")
  [ -n "$inner" ] && [ -f "$inner/config.yml" ] || { echo "NO_CONFIG $outer" >> "$DONE"; continue; }
  [ -f "$inner/plot/trj_full_final.json" ] || { echo "NO_TRJ $inner" >> "$DONE"; continue; }
  # 渲染脚本写死读 final_after_opt/ ⇒ 只有 final/ 的 run 建绝对路径软链
  if [ ! -e "$inner/point_cloud/final_after_opt" ]; then
    if [ -f "$inner/point_cloud/final/point_cloud.ply" ]; then
      ln -sfn "$REPO/$inner/point_cloud/final" "$inner/point_cloud/final_after_opt"
      echo "LINKED $inner/point_cloud/final_after_opt -> final" >> "$DONE"
    else
      echo "NO_PLY $inner" >> "$DONE"; continue
    fi
  fi
  [ -f "$inner/posthoc_staticband/posthoc_summary.json" ] && { echo "SKIP $inner (done)" >> "$DONE"; continue; }
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RENDER $inner on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY scripts/eval_vacated_posthoc.py "$inner" --out-name posthoc_staticband \
    >> "${outer}.staticband.log" 2>&1 &
  sleep 4
done

while [ "$(njobs)" -gt 0 ]; do sleep 20; done

missing=0
for outer in $RUNS; do
  inner=$(find "$outer" -mindepth 3 -maxdepth 6 -name "config.yml" 2>/dev/null | sort | tail -1)
  [ -n "$inner" ] && inner=$(dirname "$inner")
  if [ -n "$inner" ] && [ -f "$inner/posthoc_staticband/posthoc_summary.json" ]; then
    echo "OK $inner" >> "$DONE"
  else
    echo "MISSING $outer" >> "$DONE"; missing=$((missing+1))
  fi
done
echo "STATICBAND_DONE $(date) missing=$missing" >> "$DONE"
