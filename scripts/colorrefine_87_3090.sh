#!/bin/bash
# Offline color-refinement batch: replay the terminal photometric refinement on each
# finished run's final/ PLY, writing a real point_cloud/final_after_opt/point_cloud.ply
# (the paper-grade map), WITHOUT re-running SLAM. Same 87-run envelope as
# render_fframe_18seq_3090.sh (which left `final_after_opt -> final` symlinks for the
# offline render; this batch removes that symlink and writes a REAL dir).
#
# WHAT IT RENDERS (sources identical to render_fframe_18seq_3090.sh):
#   * mask-free 18-seq          = P6-18SEQ + P6-MASKOFF-3SEED + P6-MASKOFF
#   * combined mask-ON BONN-6   = P2-T_3090 *_prune
#   * combined mask-ON crowd/wk_rpy/wk_xyz/pt1 = P6-MASON
# Output: <run>/.../point_cloud/final_after_opt/point_cloud.ply
#
# Dispatches per-run through offline_color_refine.py, 2 concurrent (one per 3090).
# Writes results/runs/colorrefine_87.done on completion. Elapsed ~5-7 min/run full on
# a 3090, so 87 runs ≈ 3.5-5h wall on dual cards.

set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
REFINE=scripts/offline_color_refine.py
DONE=results/runs/colorrefine_87.done
: > "$DONE"

collect_tsdirs() {
  for d in "$@"; do
    [ -d "$d" ] || continue
    latest=""
    for ts in "$d"/datasets_*/*/seed_*/*/; do
      ts="${ts%/}"
      [ -f "$ts/config.yml" ] || continue
      [ -f "$ts/plot/trj_full_final.json" ] || continue
      [ -f "$ts/point_cloud/final/point_cloud.ply" ] || continue
      if [ -z "$latest" ] || [ "$ts" \> "$latest" ]; then latest="$ts"; fi
    done
    [ -n "$latest" ] || continue
    echo "$latest"
  done
}

RUNLIST=$(collect_tsdirs \
  results/runs/P6/P6-18SEQ/* \
  results/runs/P6/P6-MASKOFF-3SEED/* \
  results/runs/P6/P6-MASKOFF/* \
  results/runs/P2/P2-T_3090/*_prune_seed* \
  results/runs/P6/P6-MASON/* )
Ndrawn=$(echo "$RUNLIST" | sed '/^$/d' | wc -l)
echo "color-refine envelope: $Ndrawn ts-dirs" >> "$DONE"

wait_slot() {
  while [ "$(pgrep -fc 'offline_color_refine.py' 2>/dev/null || echo 0)" -ge 2 ]; do
    sleep 20
  done
}

for ts in $RUNLIST; do
  # skip only if final_after_opt is a REAL dir (NOT the render batch's adapter symlink
  # final_after_opt -> final) AND holds a finished refined PLY.
  if [ -d "$ts/point_cloud/final_after_opt" ] && [ ! -L "$ts/point_cloud/final_after_opt" ] \
     && [ -f "$ts/point_cloud/final_after_opt/point_cloud.ply" ]; then
    echo "SKIP $ts" >> "$DONE"; continue
  fi
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) COLORREFINE gpu$gpu $ts" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY "$REFINE" "$ts" > "$ts.colorrefine.log" 2>&1 &
  sleep 8
done
while [ "$(pgrep -fc 'offline_color_refine.py' 2>/dev/null || echo 0)" -gt 0 ]; do sleep 30; done
missing=0
for ts in $RUNLIST; do
  if [ ! -d "$ts/point_cloud/final_after_opt" ] || [ -L "$ts/point_cloud/final_after_opt" ] \
     || [ ! -f "$ts/point_cloud/final_after_opt/point_cloud.ply" ]; then
    echo "MISSING $ts" >> "$DONE"; missing=$((missing+1))
  fi
done
echo "ALL_DONE $(date) missing=$missing" >> "$DONE"
