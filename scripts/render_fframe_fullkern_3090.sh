#!/bin/bash
# render_fframe_fullkern_3090.sh — FULLKERN 两臂离线全帧重渲（主表 P1 的前置）
# =============================================================================
# ★ 为什么需要：静默空转事故的 11 条序列已两臂 3-seed 重跑（P6-FULLKERN /
#   P6-FULLKERN-MASKFREE），但重跑只产出 tracking（ATE）。主表要的是
#   ATE + PSNR/SSIM/LPIPS/Depth-L1，而 build_18seq_main_table.discover() 把
#   `posthoc_fullframe/fullframe_summary.json` 当成一个 run "存在"的判据 ——
#   没重渲的 run 会被直接跳过，那 11 条会**整行从主表消失**（看起来像"没跑过"）。
#   主表侧已加 assert_fullkern_coverage() 硬报错兜底，本脚本负责把渲染补上。
#
# ★ 输入（每 run 都要有，缺则本脚本拒绝开跑）：
#     config.yml / plot/trj_full_final.json / point_cloud/final/point_cloud.ply
#   这些 config 是 eval_rendering:false，只存了 final/；而 r2_p2_t_offline_render.py
#   写死读 final_after_opt/ —— 沿用 render_fframe_18seq_3090.sh 的做法：软链适配。
#
# ★ 输出：<ts>/posthoc_fullframe/fullframe_summary.json（不碰原 run 任何文件）
#
# ★ 不与 tracking 批量并跑（硬前置，见下）：主表 provenance 已记录同 seed 两次
#   ATE 15.72 vs 21.42 cm 的运行间非确定性，机制是"每帧 mapping 迭代数随
#   wall-clock 变化"。combined 臂是 2 并发跑出来的；若在 mask-free tracking
#   跑到一半时插进第三个 GPU 进程，后半批的运行条件就和前半批不同了。
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/render_fframe_fullkern_3090.sh > results/runs/render_fullkern.log 2>&1 &
# 若 tracking 还在跑、想让渲染排在它后面自动起（省 GPU 空转）：
#   nohup bash scripts/render_fframe_fullkern_3090.sh --wait-for-tracking > ... 2>&1 &
#   —— 等待而非并跑，语义与默认的"并跑就 abort"一致，只是不用人守着。
set -u
WAIT_FOR_TRACKING=0
[ "${1:-}" = "--wait-for-tracking" ] && WAIT_FOR_TRACKING=1
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
RENDER_SCRIPT=scripts/r2_p2_t_offline_render.py
OUT_COMB=results/runs/P6/P6-FULLKERN
OUT_FREE=results/runs/P6/P6-FULLKERN-MASKFREE
DONE=results/runs/render_fullkern.done
: > "$DONE"

# pgrep 必须锚定 argv 起始，否则会匹配到监控命令自身（exp19 一晚咬三次）
running_slam()   { pgrep -af 'slam.py --config' 2>/dev/null | grep -cE '/python[0-9]* +slam\.py' || true; }
running_render() { pgrep -af 'r2_p2_t_offline_render.py' 2>/dev/null | grep -cE "/python[0-9]* +$RENDER_SCRIPT" || true; }

# ---- 硬前置 1：tracking 必须已全部收工 --------------------------------------
if [ "$WAIT_FOR_TRACKING" = "1" ]; then
  waited=0
  while [ "$(running_slam)" -gt 0 ]; do
    if [ $((waited % 1800)) = 0 ]; then
      echo "$(date +%H:%M) WAIT tracking 还在跑 ($(running_slam) 个)，已等 ${waited}s" >> "$DONE"
    fi
    sleep 60; waited=$((waited+60))
    # 24h 上限：真卡住就报出来，不无限期占着这个位置
    if [ "$waited" -ge 86400 ]; then
      echo "ABORT: 等 tracking 超过 24h 仍未收工，人工介入。" >> "$DONE"; exit 1
    fi
  done
  echo "$(date +%H:%M) tracking 已收工（等了 ${waited}s），开始渲染前置校验" >> "$DONE"
fi
n_slam=$(running_slam)
if [ "$n_slam" -gt 0 ]; then
  echo "ABORT: 还有 $n_slam 个 slam.py 在跑；渲染会挤占 GPU 并改变其 wall-clock" >> "$DONE"
  echo "       -> mapping 迭代数随之变化 -> 污染这批 ATE。等 tracking 收完再发。" >> "$DONE"
  exit 1
fi

# ---- 硬前置 2：两臂 33+33 run 的渲染输入必须齐 -------------------------------
# 半齐就开跑 = 渲出一张半新半旧的表，正是本次事故的同类失败。
collect_tsdirs() {
  for d in "$@"; do
    [ -d "$d" ] || continue
    case "$(basename "$d")" in *.consolelog|*.done|tables|monitor.log) continue;; esac
    latest=""
    for ts in "$d"/datasets_*/*/seed_*/*/; do
      ts="${ts%/}"
      [ -f "$ts/config.yml" ] || continue
      [ -f "$ts/plot/trj_full_final.json" ] || continue
      [ -f "$ts/point_cloud/final/point_cloud.ply" ] || continue
      if [ -z "$latest" ] || [ "$ts" \> "$latest" ]; then latest="$ts"; fi
    done
    [ -n "$latest" ] || { echo "NO_RENDER_INPUT $d" >> "$DONE"; continue; }
    echo "$latest"
  done
}

LIST_COMB=$(collect_tsdirs "$OUT_COMB"/*)
LIST_FREE=$(collect_tsdirs "$OUT_FREE"/*)
n_comb=$(echo "$LIST_COMB" | sed '/^$/d' | wc -l)
n_free=$(echo "$LIST_FREE" | sed '/^$/d' | wc -l)
echo "envelope: combined=$n_comb maskfree=$n_free (期望 33 / 33)" >> "$DONE"
if [ "$n_comb" -ne 33 ] || [ "$n_free" -ne 33 ]; then
  echo "ABORT: 渲染输入不齐（combined=$n_comb maskfree=$n_free），不发半批。" >> "$DONE"
  echo "       缺输入的 run 见上面的 NO_RENDER_INPUT 行。" >> "$DONE"
  exit 1
fi

RUNLIST="$LIST_COMB
$LIST_FREE"

# 软链适配：r2_p2_t_offline_render.py 写死 final_after_opt/，这些 run 只有 final/
for ts in $RUNLIST; do
  [ -e "$ts/point_cloud/final_after_opt" ] || \
    ln -s "$(realpath "$ts/point_cloud/final")" "$ts/point_cloud/final_after_opt"
done

wait_slot() { while [ "$(running_render)" -ge 2 ]; do sleep 20; done; }

i=0   # set -u 下计数器必须先初始化（本项目栽过两次）
for ts in $RUNLIST; do
  if [ -f "$ts/posthoc_fullframe/fullframe_summary.json" ]; then
    echo "SKIP $ts" >> "$DONE"; continue
  fi
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  n_cards=$(nvidia-smi -L 2>/dev/null | wc -l)
  if [ -z "$gpu" ] || [ "${n_cards:-0}" = "0" ]; then gpu=$((i % 2)); fi
  i=$((i+1))
  echo "$(date +%H:%M) RENDER gpu$gpu $ts" >> "$DONE"
  # CUDA_VISIBLE_DEVICES 屏蔽后进程内部只看得到 cuda:0，不要在下游传 cuda:$gpu
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY "$RENDER_SCRIPT" --no-band-check "$ts" \
    > "$ts.render.consolelog" 2>&1 &
  sleep 8
done
while [ "$(running_render)" -gt 0 ]; do sleep 30; done

missing=0
for ts in $RUNLIST; do
  if [ ! -f "$ts/posthoc_fullframe/fullframe_summary.json" ]; then
    echo "MISSING $ts" >> "$DONE"; missing=$((missing+1))
  fi
done
echo "RENDER_FULLKERN_ALL_DONE $(date) rendered_envelope=66 missing=$missing" >> "$DONE"
