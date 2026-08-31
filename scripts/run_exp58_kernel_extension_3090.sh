#!/bin/bash
# EXP58 — kernel ablation extension: 4 sequences (mv_no_box/pt1/f3_wk_hf/crowd)
# x 2 kernels (cauchy/gm) x 3 seeds = 24 runs. E0: resolved kernel == expected.
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
EXPECTED_HEAD=c544b940f231f0bd8dda453439158e5c478ef9d8
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/EXP58/kernel_extension}
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

E58=configs/rgbd/experiments/exp58_kernel_extension
M55=configs/rgbd/experiments/exp55_kernel_ablation

# ---- pre-launch: EXP55 method configs still kernel-only, deltas 0.10 ----
if ! "$PY" - <<'PY'
import yaml
BASE_RT = yaml.safe_load(open("configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml"))["RobustTracking"]
for k in ("cauchy", "gm"):
    m = yaml.safe_load(open(f"configs/rgbd/experiments/exp55_kernel_ablation/method_combined_{k}.yaml"))
    rt = {**BASE_RT, **m["RobustTracking"]}
    ok = rt.get("kernel") == k and rt.get("enabled") is True \
        and rt.get("rgb_delta") == 0.10 and rt.get("depth_delta") == 0.10
    print("E58_PRELAUNCH", {"kernel": k, "ok": ok, "merged": rt})
    if not ok:
        raise SystemExit(2)
for seq in ("mv_no_box", "pt1", "f3_wk_hf", "crowd"):
    for k in ("cauchy", "gm"):
        run = yaml.safe_load(open(f"configs/rgbd/experiments/exp58_kernel_extension/exp58_{k}_{seq}.yaml"))
        assert run["method_from"].endswith(f"method_combined_{k}.yaml"), (seq, k)
PY
then
  echo "ERROR: EXP58 prelaunch gate failed" >&2
  exit 2
fi

run_one() {
  gpu="$1"; name="$2"; cfg="$3"; seed="$4"; want_kernel="$5"
  outnm="${name}_seed${seed}"
  got=""
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "$outnm GPU=$gpu SKIP" >> "$OUT/exp58.done"
    return 0
  fi
  log="$OUT/${outnm}.consolelog"
  echo "$outnm GPU=$gpu start $(date -Is)" >> "$OUT/exp58.done"
  env PYTHONPATH=$REPO MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    "$PY" slam.py --config "$cfg" --seed "$seed" --eval \
    --results-root "$OUT/$outnm" > "$log" 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    resolved=$(find "$OUT/$outnm" -name config.yml | head -1)
    got=$(grep -A6 '^RobustTracking:' "$resolved" 2>/dev/null | grep 'kernel:' | head -1 | awk '{print $2}' | tr -d '"')
    if [ "$got" != "$want_kernel" ]; then
      echo "$outnm GPU=$gpu E0_FAIL resolved_kernel='$got' expected='$want_kernel' $(date -Is)" >> "$OUT/exp58.done"
      return 3
    fi
  fi
  echo "$outnm GPU=$gpu finished rc=$rc kernel=$got $(date -Is)" >> "$OUT/exp58.done"
  return "$rc"
}

: > "$OUT/exp58.done"
# 24 runs: GPU0 = cauchy queue (12), GPU1 = gm queue (12); serial per card.
run_queue() {
  gpu="$1"; kernel="$2"
  for seed in 0 1 2; do
    for seq in mv_no_box crowd pt1 f3_wk_hf; do
      run_one "$gpu" "${seq}_${kernel}" "$E58/exp58_${kernel}_${seq}.yaml" "$seed" "$kernel" || return 1
    done
  done
}
run_queue 0 cauchy & pid0=$!
run_queue 1 gm & pid1=$!
wait "$pid0"; rc0=$?
wait "$pid1"; rc1=$?
rc=0
if [ "$rc0" -ne 0 ] || [ "$rc1" -ne 0 ]; then rc=1; fi
printf '=== EXP58 ALL_DONE rc=%s %s ===\n' "$rc" "$(date -Is)" >> "$OUT/exp58.done"
exit "$rc"
