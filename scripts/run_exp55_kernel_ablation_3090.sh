#!/bin/bash
# EXP55 — RobustTracking kernel ablation: 2 kernels (cauchy/gm) x 2 sequences
# (balloon/pt2) x 3 seeds = 12 runs. Huber anchor = existing main-table runs
# (P2-T_3090), NOT rerun here.
#
# E0 GATE (prereg §4): _robust_irls_weight silently returns all-ones weights for
# any unknown kernel string (exp23-class failure). Two guards:
#   (a) pre-launch python merge check: resolved RobustTracking.kernel == expected;
#   (b) post-run: resolved config.yml inside the run dir must contain the kernel.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
EXPECTED_HEAD=c544b940f231f0bd8dda453439158e5c478ef9d8
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/EXP55/kernel_ablation}
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

E55=configs/rgbd/experiments/exp55_kernel_ablation

# ---- pre-launch gate (a): resolve the inherit chain and assert the kernel ----
if ! "$PY" - <<'PY'
import os, sys
import yaml

def load(rel):
    with open(rel) as fh:
        return yaml.safe_load(fh)

def resolve(rel):
    cfg = load(rel)
    parent = cfg.pop("inherit_from", None)
    if parent:
        merged = resolve(parent)
        merged.update(cfg)
        return merged
    return cfg

BASE = "configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml"
for k in ("cauchy", "gm"):
    method = load(f"configs/rgbd/experiments/exp55_kernel_ablation/method_combined_{k}.yaml")
    base = load(BASE)
    rt = {**base.get("RobustTracking", {}), **method.get("RobustTracking", {})}
    ok = rt.get("kernel") == k and rt.get("enabled") is True \
        and rt.get("rgb_delta") == 0.10 and rt.get("depth_delta") == 0.10
    print("KERNEL_PRELAUNCH", {"kernel": k, "resolved": rt.get("kernel"),
                               "enabled": rt.get("enabled"), "ok": ok})
    if not ok:
        raise SystemExit(2)
PY
then
  echo "ERROR: kernel prelaunch gate failed" >&2
  exit 2
fi

# ---- flow preflight: balloon/pt2 flow_raft must already exist ----
if ! "$PY" - <<'PY'
import glob, json, os, sys
sys.path.insert(0, os.getcwd())
from utils.config_utils import load_config
from utils.dataset import TUMParser
for label, config_path in (
    ("balloon", "configs/rgbd/experiments/exp55_kernel_ablation/exp55_cauchy_balloon.yaml"),
    ("pt2", "configs/rgbd/experiments/exp55_kernel_ablation/exp55_cauchy_pt2.yaml"),
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
  gpu="$1"; name="$2"; cfg="$3"; seed="$4"; want_kernel="$5"
  outnm="${name}_seed${seed}"
  got=""
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "$outnm GPU=$gpu SKIP" >> "$OUT/exp55.done"
    return 0
  fi
  log="$OUT/${outnm}.consolelog"
  echo "$outnm GPU=$gpu start $(date -Is)" >> "$OUT/exp55.done"
  env PYTHONPATH=$REPO MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    "$PY" slam.py --config "$cfg" --seed "$seed" --eval \
    --results-root "$OUT/$outnm" > "$log" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    # ---- E0 gate (b): resolved config.yml must carry the expected kernel ----
    resolved=$(find "$OUT/$outnm" -name config.yml | head -1)
    got=$(grep -A6 '^RobustTracking:' "$resolved" 2>/dev/null | grep 'kernel:' | head -1 | awk '{print $2}' | tr -d '"')
    if [ "$got" != "$want_kernel" ]; then
      echo "$outnm GPU=$gpu E0_FAIL resolved_kernel='$got' expected='$want_kernel' $(date -Is)" >> "$OUT/exp55.done"
      return 3
    fi
  fi
  echo "$outnm GPU=$gpu finished rc=$rc kernel=$got $(date -Is)" >> "$OUT/exp55.done"
  return "$rc"
}

RUNS=()
for seed in 0 1 2; do
  RUNS+=("balloon_cauchy|$E55/exp55_cauchy_balloon.yaml|$seed|cauchy")
  RUNS+=("balloon_gm|$E55/exp55_gm_balloon.yaml|$seed|gm")
done
for seed in 0 1 2; do
  RUNS+=("pt2_cauchy|$E55/exp55_cauchy_pt2.yaml|$seed|cauchy")
  RUNS+=("pt2_gm|$E55/exp55_gm_pt2.yaml|$seed|gm")
done
: > "$OUT/exp55.done"

# One task per card: GPU0 = balloon queue, GPU1 = pt2 queue.
run_queue() {
  gpu="$1"; start="$2"
  for ((i=start; i<${#RUNS[@]}; i+=2)); do
    entry="${RUNS[$i]}"
    name="${entry%%|*}"; rest="${entry#*|}"; cfg="${rest%%|*}"; r2="${rest#*|}"
    seed="${r2%%|*}"; want="${r2##*|}"
    run_one "$gpu" "$name" "$cfg" "$seed" "$want" || return 1
  done
}
run_queue 0 0 & pid0=$!
run_queue 1 1 & pid1=$!
wait "$pid0"; rc0=$?
wait "$pid1"; rc1=$?
rc=0
if [ "$rc0" -ne 0 ] || [ "$rc1" -ne 0 ]; then rc=1; fi
printf '=== EXP55 ALL_DONE rc=%s %s ===\n' "$rc" "$(date -Is)" >> "$OUT/exp55.done"
exit "$rc"
