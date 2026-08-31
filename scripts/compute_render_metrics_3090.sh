#!/bin/bash
source ~/anaconda3/etc/profile.d/conda.sh
conda activate monogs-ours-3090
cd /home/jiangwenheng/cron/monogs-ours

# Find all runs with final_after_opt PLY
RUNS=$(find results/runs/P6/P6-MASKOFF-3SEED results/runs/P6/P6-MASON results/runs/P6/P6-18SEQ results/runs/P2/P2-T_3090 \
  -path "*/final_after_opt/*.ply" -not -path "*/tables/*" | sed 's|/point_cloud/final_after_opt/.*||' | sort -u)

TOTAL=$(echo "$RUNS" | wc -l)
echo "Found $TOTAL runs with afteropt PLY"
COUNT=0

for run in $RUNS; do
  COUNT=$((COUNT + 1))
  if [ -f "$run/posthoc_fullframe/posthoc_fullframe.json" ]; then
    echo "[$COUNT/$TOTAL] SKIP (already done): $(basename $run)"
    continue
  fi
  echo "[$COUNT/$TOTAL] Processing: $(basename $run)"
  python scripts/r2_p2_t_offline_render.py --no-band-check "$run" 2>&1 | tail -1
done

echo "=== ALL DONE ==="
