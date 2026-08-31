#!/bin/bash
# Offline full-frame rendering (PSNR/SSIM/LPIPS/depth from final/ PLY + trj_full_final)
# for the 18-seq rendering main table. Runs 2 concurrent (one per 3090).
#
# WHAT IT RENDERS (all from point_cloud/final/, self-consistent — these configs have
# eval_rendering:false so only final/ was saved; r2_p2_t_offline_render.py expects
# final_after_opt, so we place a symlink final_after_opt -> final per run dir first):
#   * mask-free 18-seq          = results/runs/P6/P6-18SEQ (crowd/crowd2 + 10 TUM)
#                               + results/runs/P6/P6-MASKOFF-3SEED (BONN-6)
#                               + results/runs/P6/P6-MASKOFF (BONN-6 seed0 leftovers)
#   * combined mask-ON BONN-6   = results/runs/P2/P2-T_3090 *_prune (combined maskboth)
#   * combined mask-ON crowd/wk_rpy/wk_xyz/pt1 = results/runs/P6/P6-MASON
#
# Output: <run>/datasets_*/*/seed_*/*/posthoc_fullframe/fullframe_summary.json
# Dispatches per-run through the offline render script; --no-band-check (these runs
# carry no stored band_metrics.json; band is unavailable from pre-render config anyway).
# Writes results/runs/render_fframe_18seq.done on completion.

set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
RENDER_SCRIPT=scripts/r2_p2_t_offline_render.py
DONE=results/runs/render_fframe_18seq.done
: > "$DONE"

# Collect the FINAL (latest timestamp) TS dir per top-level run dir. A run may have
# multiple TS dirs (retry/re-checkpoint); only the last completed one matches its
# tables/tracking_raw, so we render just that one (saves GPU on dead intermediates).
collect_tsdirs() {
  for d in "$@"; do
    [ -d "$d" ] || continue
    # pick latest-mtime TS dir that is complete (config.yml + final ply + trj)
    latest=""
    for ts in "$d"/datasets_*/*/seed_*/*/; do
      ts="${ts%/}"
      [ -f "$ts/config.yml" ] || continue
      [ -f "$ts/plot/trj_full_final.json" ] || continue
      [ -f "$ts/point_cloud/final/point_cloud.ply" ] || continue
      if [ -z "$latest" ] || [ "$ts" \> "$latest" ]; then latest="$ts"; fi
    done
    [ -n "$latest" ] || continue
    # symlink adapter: final_after_opt -> final (script hardcodes final_after_opt)
    [ -e "$latest/point_cloud/final_after_opt" ] || ln -s "$(realpath "$latest/point_cloud/final")" "$latest/point_cloud/final_after_opt"
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
echo "render envelope: $Ndrawn ts-dirs" >> "$DONE"

wait_slot() {
  while [ "$(pgrep -fc 'r2_p2_t_offline_render.py' 2>/dev/null || echo 0)" -ge 2 ]; do
    sleep 20
  done
}

for ts in $RUNLIST; do
  # skip if already rendered
  if [ -f "$ts/posthoc_fullframe/fullframe_summary.json" ]; then
    echo "SKIP $ts" >> "$DONE"
    continue
  fi
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
        | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RENDER gpu$gpu $ts" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY "$RENDER_SCRIPT" --no-band-check "$ts" \
    > "$ts.render.consolelog" 2>&1 &
  sleep 8
done
while [ "$(pgrep -fc 'r2_p2_t_offline_render.py' 2>/dev/null || echo 0)" -gt 0 ]; do sleep 30; done
# final sweep
missing=0
for ts in $RUNLIST; do
  if [ ! -f "$ts/posthoc_fullframe/fullframe_summary.json" ]; then
    echo "MISSING $ts" >> "$DONE"
    missing=$((missing+1))
  fi
done
echo "ALL_DONE $(date) missing=$missing" >> "$DONE"
