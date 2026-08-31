#!/usr/bin/env bash
# STEP 2A runner: terminal compression 3-seed replication (zero-GPU offline).
# Launches mc_terminal_comp_3seed.py on all 12 base prune run dirs (thresholds 0.01,0.05),
# then the opacity-histogram mechanism probe on the 3 compress runs.
set -u
PY=/data/conda_envs/monogs-ours/bin/python
cd /data/monogs-ours || exit 1

# --- collect all base prune run dirs (the one containing point_cloud/final_after_opt) ---
RUN_DIRS=()
for s in balloon mv_no_box pt1 pt2; do
  for k in 0 1 2; do
    d=$(find "results/runs/P2/P2-T/${s}_prune_seed${k}" -name "final_after_opt" -type d -path "*point_cloud*" 2>/dev/null | xargs dirname 2>/dev/null | head -1)
    # fallback: the dir containing config.yml
    if [ -z "$d" ] || [ ! -f "$d/config.yml" ]; then
      d=$(find "results/runs/P2/P2-T/${s}_prune_seed${k}" -name "config.yml" -type f 2>/dev/null | head -1 | xargs dirname)
    fi
    if [ -n "$d" ] && [ -f "$d/config.yml" ]; then
      RUN_DIRS+=("$d")
    else
      echo "SKIP ${s}_seed${k}: no config dir found" >&2
    fi
  done
done

echo "=== Running STEP 2A on ${#RUN_DIRS[@]} base prune run dirs ==="
for d in "${RUN_DIRS[@]}"; do
  echo "  $d"
done

LOG=results/evidence/R3-P05-map-compression-step5b-terminal-3seed.runlog
: > "$LOG"
for d in "${RUN_DIRS[@]}"; do
  echo "=== TERM $d ===" >> "$LOG"
  $PY scripts/mc_terminal_comp_3seed.py "$d" --thresholds 0.01,0.05 2>&1 | tee -a "$LOG"
  echo "" >> "$LOG"
done

echo ""
echo "=== opacity-histogram mechanism probe on compress runs (balloon/mv/pt1 have PLY, pt2 --fast does not) ==="
for s in balloon mv_no_box pt1 pt2; do
  d=$(find "results/runs/P2/P2-MC/${s}_compress_seed0" -name "config.yml" -type f 2>/dev/null | head -1 | xargs dirname)
  if [ -n "$d" ] && [ -f "$d/config.yml" ]; then
    echo "=== HIST $d ===" >> "$LOG"
    $PY scripts/mc_terminal_comp_3seed.py "$d" --hist-only 2>&1 | tee -a "$LOG"
  fi
done

echo "DONE 2A ALL. log: $LOG"
