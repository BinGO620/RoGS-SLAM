#!/bin/bash
# EXP54 — P11 single-variable component attribution, 2 sequences × 2 arms × 3 seeds.
# Default PHASE=0 runs only the two crowd2 seed0 mechanism checks.
# PHASE=1 adds crowd2 seeds1/2 and mv_no_box seed0 (6 runs).
# PHASE=2 completes mv_no_box seeds1/2 (4 runs).
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
# The remote runtime baseline is the EXP53 audit baseline.  Local HEAD adds only
# post-run documentation, while the tracked runtime files are byte-identical here.
EXPECTED_HEAD=c544b940f231f0bd8dda453439158e5c478ef9d8
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/EXP54/component_attribution}
PHASE=${PHASE:-0}
export EXPECTED_HEAD PY
cd "$REPO"
mkdir -p "$OUT"

actual_head=$(git rev-parse HEAD)
if [ "$actual_head" != "$EXPECTED_HEAD" ]; then
  echo "ERROR: remote HEAD=$actual_head, expected=$EXPECTED_HEAD" >&2
  exit 2
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: remote tracked worktree is dirty; refuse to launch" >&2
  exit 2
fi

P11D=configs/rgbd/experiments/exp54_component_attribution
if ! "$PY" - <<'PY'
import glob, json, os, sys
sys.path.insert(0, os.getcwd())
from utils.config_utils import load_config
from utils.dataset import TUMParser
for label, config_path in (
    ("crowd2", "configs/rgbd/experiments/exp54_component_attribution/exp54_p11_reliability_crowd2.yaml"),
    ("mv_no_box", "configs/rgbd/experiments/exp54_component_attribution/exp54_p11_reliability_mv_no_box.yaml"),
):
    cfg = load_config(config_path)
    seq = cfg["Dataset"]["dataset_path"]
    parser = TUMParser(seq)
    with open(os.path.join(seq, "flow_raft", "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    stems = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(seq, "flow_raft", "*.npy"))}
    depth = [os.path.splitext(os.path.basename(p))[0] for p in parser.depth_paths]
    missing = set(depth[1:]) - stems
    print("FLOW_PREFLIGHT", {"seq": label, "parser_frames": parser.n_img,
          "manifest_frames": manifest.get("n_frames"), "flow_files": len(stems),
          "missing_runtime_flow": len(missing)})
    if parser.n_img != manifest.get("n_frames") or missing:
        raise SystemExit(2)
PY
then
  echo "ERROR: flow preflight failed" >&2
  exit 2
fi

run_one() {
  gpu="$1"; name="$2"; cfg="$3"; seed="$4"
  outnm="${name}_seed${seed}"
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "$outnm GPU=$gpu SKIP" >> "$OUT/exp54.done"
    return 0
  fi
  log="$OUT/${outnm}.consolelog"
  echo "$outnm GPU=$gpu start $(date -Is)" >> "$OUT/exp54.done"
  env PYTHONPATH=$REPO MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    "$PY" slam.py --config "$cfg" --seed "$seed" --eval \
    --results-root "$OUT/$outnm" > "$log" 2>&1
  rc=$?
  echo "$outnm GPU=$gpu finished rc=$rc $(date -Is)" >> "$OUT/exp54.done"
  return "$rc"
}

# One task per card. Phase gates are deliberate: do not launch later phases by default.
RUNS=()
if [ "$PHASE" -ge 0 ]; then
  RUNS+=("crowd2_dynkf|$P11D/exp54_p11_dynkf_crowd2.yaml|0")
  RUNS+=("crowd2_reliability|$P11D/exp54_p11_reliability_crowd2.yaml|0")
fi
if [ "$PHASE" -ge 1 ]; then
  RUNS+=("crowd2_dynkf|$P11D/exp54_p11_dynkf_crowd2.yaml|1")
  RUNS+=("crowd2_dynkf|$P11D/exp54_p11_dynkf_crowd2.yaml|2")
  RUNS+=("crowd2_reliability|$P11D/exp54_p11_reliability_crowd2.yaml|1")
  RUNS+=("crowd2_reliability|$P11D/exp54_p11_reliability_crowd2.yaml|2")
  RUNS+=("mvnobox_dynkf|$P11D/exp54_p11_dynkf_mv_no_box.yaml|0")
  RUNS+=("mvnobox_reliability|$P11D/exp54_p11_reliability_mv_no_box.yaml|0")
fi
if [ "$PHASE" -ge 2 ]; then
  RUNS+=("mvnobox_dynkf|$P11D/exp54_p11_dynkf_mv_no_box.yaml|1")
  RUNS+=("mvnobox_dynkf|$P11D/exp54_p11_dynkf_mv_no_box.yaml|2")
  RUNS+=("mvnobox_reliability|$P11D/exp54_p11_reliability_mv_no_box.yaml|1")
  RUNS+=("mvnobox_reliability|$P11D/exp54_p11_reliability_mv_no_box.yaml|2")
fi
if [ "$PHASE" -lt 0 ] || [ "$PHASE" -gt 2 ]; then
  echo "ERROR: PHASE must be 0, 1, or 2" >&2
  exit 2
fi
: > "$OUT/exp54.done"

# Keep each GPU serial.  This is intentionally two queues rather than launching
# every run in the background, because concurrent workers change the timing regime.
run_queue() {
  gpu="$1"
  start="$2"
  for ((i=start; i<${#RUNS[@]}; i+=2)); do
    entry="${RUNS[$i]}"
    name="${entry%%|*}"; rest="${entry#*|}"; cfg="${rest%%|*}"; seed="${rest##*|}"
    run_one "$gpu" "$name" "$cfg" "$seed" || return 1
  done
}
run_queue 0 0 & pid0=$!
run_queue 1 1 & pid1=$!
wait "$pid0"; rc0=$?
wait "$pid1"; rc1=$?
rc=0
if [ "$rc0" -ne 0 ] || [ "$rc1" -ne 0 ]; then rc=1; fi
printf '=== EXP54 PHASE=%s ALL_DONE rc=%s %s ===\n' "$PHASE" "$rc" "$(date -Is)" >> "$OUT/exp54.done"
exit "$rc"

