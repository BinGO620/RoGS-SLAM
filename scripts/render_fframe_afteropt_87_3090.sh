#!/bin/bash
# Offline full-frame rendering (PSNR/SSIM/LPIPS/depth) from the PAPER-GRADE map
# `final_after_opt/point_cloud.ply` (the color-refined map produced by
# colorrefine_87_3090.sh) + saved poses. Same 87-run envelope as the two earlier
# batches. Writes each ts-dir's posthoc_fullframeagain (overwriting the final/-based
# numbers with the final_after_opt/-based paper numbers). dual-3090.

set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
RENDER=scripts/r2_p2_t_offline_render.py
DONE=results/runs/render_fframe_afteropt_87.done
: > "$DONE"

collect_tsdirs() {
  for d in "$@"; do
    [ -d "$d" ] || continue
    latest=""
    for ts in "$d"/datasets_*/*/seed_*/*/; do
      ts="${ts%/}"
      [ -f "$ts/config.yml" ] || continue
      [ -f "$ts/plot/trj_full_final.json" ] || continue
      [ -f "$ts/point_cloud/final_after_opt/point_cloud.ply" ] || continue
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
echo "render-afteropt envelope: $Ndrawn ts-dirs" >> "$DONE"

wait_slot() {
  while [ "$(pgrep -fc 'r2_p2_t_offline_render.py' 2>/dev/null || echo 0)" -ge 2 ]; do
    sleep 20
  done
}

for ts in $RUNLIST; do
  if [ -f "$ts/posthoc_fullframe/fullframe_summary.json" ] && grep -q '"psnr"' "$ts/posthoc_fullframe/fullframe_summary.json"; then
    # overwrite: render every run so posthoc reflects final_after_opt
    :
  fi
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RENDER-AFTEROPT gpu$gpu $ts" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY "$RENDER" --no-band-check "$ts" > "$ts.render_afteropt.log" 2>&1 &
  sleep 8
done
while [ "$(pgrep -fc 'r2_p2_t_offline_render.py' 2>/dev/null || echo 0)" -gt 0 ]; do sleep 30; done
missing=0
for ts in $RUNLIST; do
  if [ ! -f "$ts/posthoc_fullframe/fullframe_summary.json" ]; then
    echo "MISSING $ts" >> "$DONE"; missing=$((missing+1))
  fi
done
echo "ALL_DONE $(date) missing=$missing" >> "$DONE"
