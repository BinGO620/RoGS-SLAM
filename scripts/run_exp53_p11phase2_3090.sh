#!/bin/bash
# EXP53 — P11 Phase 2 扩序列泛化 + Combined 臂对照,3090 双卡批量。
#
# 27 run:5 序列(balloon 只有 C 侧 3 run;其余 4 序列 P11×3 + C×3)。
#   GPU0 = f2_xyz 两臂 ×3(最长序列,~11.5h)
#   GPU1 = balloon C×3 + balloon2/crowd2/mv_no_box 两臂 ×3(~11h)
#
# 预注册:results/evidence/exp53_p11phase2_prereg.md(判据 G0-G3 冻结,先于派发)。
# 预算匹配:所有臂均不设 async_iter_per_kf(同走代码默认 10,主表口径)。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
EXPECTED_HEAD=c544b940f231f0bd8dda453439158e5c478ef9d8
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
export EXPECTED_HEAD PY
OUT=${OUT:-results/runs/EXP53/p11phase2}
mkdir -p "$OUT"
DONE="$OUT/exp53.done"

actual_head=$(git rev-parse HEAD)
if [ "$actual_head" != "$EXPECTED_HEAD" ]; then
  echo "ERROR: remote HEAD=$actual_head, expected=$EXPECTED_HEAD" >&2
  exit 2
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: remote tracked worktree is dirty; refuse to launch" >&2
  exit 2
fi
for required in \
  utils/slam_backend.py \
  utils/slam_frontend.py \
  utils/reliability_signal.py \
  utils/slam_utils.py \
  configs/rgbd/tum/base_config.yaml \
  configs/rgbd/bonn/base_config.yaml \
  configs/rgbd/experiments/p11_maskonly/p11_maskonly_balloon2.yaml \
  configs/rgbd/experiments/p11_maskonly/p11_maskonly_crowd2.yaml \
  configs/rgbd/experiments/p11_maskonly/p11_maskonly_mv_no_box.yaml \
  configs/rgbd/experiments/p11_maskonly/p11_maskonly_f2_xyz.yaml \
  configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml \
  configs/rgbd/experiments/exp53_p11phase2/exp53_combined_balloon.yaml \
  configs/rgbd/experiments/exp53_p11phase2/exp53_combined_balloon2.yaml \
  configs/rgbd/experiments/exp53_p11phase2/exp53_combined_crowd2.yaml \
  configs/rgbd/experiments/exp53_p11phase2/exp53_combined_mv_no_box.yaml \
  configs/rgbd/experiments/exp53_p11phase2/exp53_combined_f2_xyz.yaml; do
  if [ ! -f "$required" ]; then
    echo "ERROR: missing required file $required" >&2
    exit 2
  fi
done

# Flow preflight per sequence (TUMParser frame-stem口径): parser frames must match the
# manifest, and every unique runtime depth stem after the first must have a frozen
# backward-flow .npy. f2_xyz verified locally missing=0 pre-prereg; rerun here as the
# dispatch-time gate. Combined arms need flow for ReliabilitySignal; P11 arms share
# the same parser stems so one check per sequence covers both arms.
if ! "$PY" - <<'PY'
import glob
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from utils.config_utils import load_config
from utils.dataset import TUMParser

CONFIGS = [
    ("balloon", "configs/rgbd/experiments/exp53_p11phase2/exp53_combined_balloon.yaml"),
    ("balloon2", "configs/rgbd/experiments/p11_maskonly/p11_maskonly_balloon2.yaml"),
    ("crowd2", "configs/rgbd/experiments/p11_maskonly/p11_maskonly_crowd2.yaml"),
    ("mv_no_box", "configs/rgbd/experiments/p11_maskonly/p11_maskonly_mv_no_box.yaml"),
    ("f2_xyz", "configs/rgbd/experiments/p11_maskonly/p11_maskonly_f2_xyz.yaml"),
]
for label, config_path in CONFIGS:
    config = load_config(config_path)
    seq = config["Dataset"]["dataset_path"]
    parser = TUMParser(seq)
    with open(os.path.join(seq, "flow_raft", "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    flow_stems = {
        os.path.splitext(os.path.basename(path))[0]
        for path in glob.glob(os.path.join(seq, "flow_raft", "*.npy"))
    }
    run_depth_stems = [os.path.splitext(os.path.basename(path))[0] for path in parser.depth_paths]
    missing = set(run_depth_stems[1:]) - flow_stems
    report = {
        "seq": label,
        "parser_frames": parser.n_img,
        "manifest_frames": manifest.get("n_frames"),
        "flow_files": len(flow_stems),
        "run_depth_unique": len(set(run_depth_stems)),
        "missing_runtime_flow": len(missing),
    }
    print("FLOW_PREFLIGHT", report)
    if parser.n_img != manifest.get("n_frames") or missing:
        print(f"ERROR: {label} runtime frame/flow mismatch", file=sys.stderr)
        raise SystemExit(2)
PY
then
  echo "ERROR: flow preflight failed" >&2
  exit 2
fi

# Record immutable run provenance before dispatching any GPU work.
"$PY" - <<'PY'
import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path

files = [
    "utils/slam_backend.py",
    "utils/slam_frontend.py",
    "utils/reliability_signal.py",
    "utils/slam_utils.py",
    "utils/alpha_lifecycle.py",
    "utils/mapping_probe.py",
    "utils/mapping_weight.py",
    "configs/rgbd/tum/base_config.yaml",
    "configs/rgbd/bonn/base_config.yaml",
    "configs/rgbd/bonn/balloon.yaml",
    "configs/rgbd/bonn/balloon2.yaml",
    "configs/rgbd/bonn/crowd2.yaml",
    "configs/rgbd/bonn/moving_nonobstructing_box.yaml",
    "configs/rgbd/tum/f2_xyz.yaml",
    "configs/rgbd/tum/f3_st_hf.yaml",
    "configs/rgbd/experiments/active/candidate/method_combined_maskoff_prune.yaml",
    "configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml",
    "configs/rgbd/experiments/wpm_maskonly/method_maskonly.yaml",
    "configs/rgbd/experiments/p11_maskonly/method_p11_maskonly.yaml",
    "configs/rgbd/experiments/p11_maskonly/p11_maskonly_f3_st_hf.yaml",
    "configs/rgbd/experiments/p11_maskonly/p11_maskonly_balloon.yaml",
    "configs/rgbd/experiments/p11_maskonly/p11_maskonly_balloon2.yaml",
    "configs/rgbd/experiments/p11_maskonly/p11_maskonly_crowd2.yaml",
    "configs/rgbd/experiments/p11_maskonly/p11_maskonly_mv_no_box.yaml",
    "configs/rgbd/experiments/p11_maskonly/p11_maskonly_f2_xyz.yaml",
]
files.extend(str(path) for path in sorted(Path("configs/rgbd/experiments/exp53_p11phase2").glob("*.yaml")))
files.extend([
    "scripts/run_exp53_p11phase2_3090.sh",
    "scripts/read_exp53_p11phase2.py",
    "tests/test_exp53_configs.py",
    "results/evidence/exp53_p11phase2_prereg.md",
])

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

payload = {
    "experiment": "EXP53-P11-phase2-combined",
    "expected_head": os.environ.get("EXPECTED_HEAD"),
    "actual_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "hostname": socket.gethostname(),
    "python": os.path.realpath(os.environ.get("PY", "")),
    "files_sha256": {path: sha256(path) for path in files},
}
with open("results/runs/EXP53/exp53_provenance.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
print("WROTE results/runs/EXP53/exp53_provenance.json")
PY

# run_worker <gpu> <name|config|seed>...
run_worker() {
  gpu="$1"
  shift
  for entry in "$@"; do
    name="${entry%%|*}"; rest="${entry#*|}"; cfg="${rest%%|*}"; seed="${rest##*|}"
    outnm="${name}_seed${seed}"
    if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
      echo "$outnm GPU=$gpu SKIP" >> "$DONE"
      continue
    fi
    logfile="$OUT/${outnm}.consolelog"
    echo "$outnm GPU=$gpu start $(date)" >> "$DONE"
    env PYTHONPATH=$REPO MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
      "$PY" slam.py --config "$cfg" --seed "$seed" --eval \
      --results-root "$OUT/$outnm" \
      > "$logfile" 2>&1
    rc=$?
    echo "$outnm GPU=$gpu finished rc=$rc $(date)" >> "$DONE"
    if [ "$rc" -ne 0 ]; then
      echo "ERROR: $outnm failed with rc=$rc" >&2
      return "$rc"
    fi
  done
}

: > "$DONE"

P11D=configs/rgbd/experiments/p11_maskonly
E53=configs/rgbd/experiments/exp53_p11phase2

# GPU0: f2_xyz both arms (longest sequences, ~90-140 min/run)
GPU0_RUNS=(
  "f2xyz_P11|$P11D/p11_maskonly_f2_xyz.yaml|0"
  "f2xyz_P11|$P11D/p11_maskonly_f2_xyz.yaml|1"
  "f2xyz_P11|$P11D/p11_maskonly_f2_xyz.yaml|2"
  "f2xyz_C|$E53/exp53_combined_f2_xyz.yaml|0"
  "f2xyz_C|$E53/exp53_combined_f2_xyz.yaml|1"
  "f2xyz_C|$E53/exp53_combined_f2_xyz.yaml|2"
)
# GPU1: short/medium sequences, P11 side first (early anchor check), then C
GPU1_RUNS=(
  "balloon_C|$E53/exp53_combined_balloon.yaml|0"
  "balloon_C|$E53/exp53_combined_balloon.yaml|1"
  "balloon_C|$E53/exp53_combined_balloon.yaml|2"
  "balloon2_P11|$P11D/p11_maskonly_balloon2.yaml|0"
  "balloon2_P11|$P11D/p11_maskonly_balloon2.yaml|1"
  "balloon2_P11|$P11D/p11_maskonly_balloon2.yaml|2"
  "balloon2_C|$E53/exp53_combined_balloon2.yaml|0"
  "balloon2_C|$E53/exp53_combined_balloon2.yaml|1"
  "balloon2_C|$E53/exp53_combined_balloon2.yaml|2"
  "crowd2_P11|$P11D/p11_maskonly_crowd2.yaml|0"
  "crowd2_P11|$P11D/p11_maskonly_crowd2.yaml|1"
  "crowd2_P11|$P11D/p11_maskonly_crowd2.yaml|2"
  "crowd2_C|$E53/exp53_combined_crowd2.yaml|0"
  "crowd2_C|$E53/exp53_combined_crowd2.yaml|1"
  "crowd2_C|$E53/exp53_combined_crowd2.yaml|2"
  "mvnobox_P11|$P11D/p11_maskonly_mv_no_box.yaml|0"
  "mvnobox_P11|$P11D/p11_maskonly_mv_no_box.yaml|1"
  "mvnobox_P11|$P11D/p11_maskonly_mv_no_box.yaml|2"
  "mvnobox_C|$E53/exp53_combined_mv_no_box.yaml|0"
  "mvnobox_C|$E53/exp53_combined_mv_no_box.yaml|1"
  "mvnobox_C|$E53/exp53_combined_mv_no_box.yaml|2"
)

run_worker 0 "${GPU0_RUNS[@]}" &
pid0=$!
run_worker 1 "${GPU1_RUNS[@]}" &
pid1=$!
wait "$pid0"; rc0=$?
wait "$pid1"; rc1=$?
echo "=== EXP53 ALL_DONE rc0=$rc0 rc1=$rc1 $(date) ===" >> "$DONE"
if [ "$rc0" -ne 0 ] || [ "$rc1" -ne 0 ]; then
  exit 1
fi
