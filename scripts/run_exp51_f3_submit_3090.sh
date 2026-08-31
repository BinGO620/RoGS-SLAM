#!/bin/bash
# EXP51 — f3_st_hf 静态 ATE 优化（Phase 1 预算公平对照），3090 双卡批量。
#
# 在远程 jiangwenheng 服务器上执行。4 臂 × 3 seed = 12 run，拆双卡并行。
# 每 run ~25-30 min，两卡并行约 3h 完成。
#
# 约束：远程 HEAD 必须与本地 bc73eb1a 一致（代码同步检查）。
# 正式数据全部以 3090 为准，本地 cb(2060) 不做判决。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
EXPECTED_HEAD=bc73eb1a769434e39ef426fcac8f4713b1d36963
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
export EXPECTED_HEAD PY
OUT=${OUT:-results/runs/EXP51/f3_submit_v2}
mkdir -p "$OUT"
DONE="$OUT/exp51.done"

# Refuse to launch if the tracked code is not the audited cb/origin HEAD.
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
  configs/rgbd/tum/base_config.yaml; do
  if [ ! -f "$required" ]; then
    echo "ERROR: missing required file $required" >&2
    exit 2
  fi
done

# The generic checker compares manifest.n_frames to raw rgb/*.png. TUM's parser
# intentionally associates/subsamples frames, so validate the exact runtime frame
# list and depth-stem keyed flow lookup instead of accepting a raw-file false positive.
if ! "$PY" - <<'PY'
import glob
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from utils.config_utils import load_config
from utils.dataset import TUMParser

config = load_config("configs/rgbd/experiments/exp51_f3_submit/exp51_mrcs_async50_f3_st_hf.yaml")
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
    "parser_frames": parser.n_img,
    "manifest_frames": manifest.get("n_frames"),
    "manifest_unique_stems": len(set(manifest.get("frame_stems", []))),
    "flow_files": len(flow_stems),
    "run_depth_unique": len(set(run_depth_stems)),
    "missing_runtime_flow": len(missing),
}
print("FLOW_PREFLIGHT", report)
if parser.n_img != manifest.get("n_frames") or missing:
    print("ERROR: runtime frame/flow mismatch", file=sys.stderr)
    raise SystemExit(2)
PY
then
  echo "ERROR: f3_st_hf flow preflight failed" >&2
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
    "configs/rgbd/tum/base_config.yaml",
]
exp_files = sorted(Path("configs/rgbd/experiments/exp51_f3_submit").glob("*.yaml"))
files.extend(str(path) for path in exp_files)
files.extend([
    "scripts/run_exp51_f3_submit_3090.sh",
    "scripts/read_exp51_f3_submit.py",
    "tests/test_exp51_f3_submit_configs.py",
    "results/evidence/exp51_f3_submit_prereg.md",
])

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

payload = {
    "experiment": "EXP51-f3-submit-phase1",
    "expected_head": os.environ.get("EXPECTED_HEAD"),
    "actual_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "hostname": socket.gethostname(),
    "python": os.path.realpath(os.environ.get("PY", "")),
    "files_sha256": {path: sha256(path) for path in files},
}
with open("results/runs/EXP51/exp51_provenance.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
print("WROTE results/runs/EXP51/exp51_provenance.json")
PY

# 4 臂。config 前缀 = 配置文件名（不含路径，不含 .yaml）。
# 格式：name|config
ARMS="
A1|exp51_mrcs_async10_f3_st_hf
A2|exp51_mrcs_async50_f3_st_hf
B1|exp51_vanilla_async10_f3_st_hf
B2|exp51_vanilla_async50_f3_st_hf
"

# Fixed per-GPU workers: one SLAM run at a time on each physical 3090.
# This avoids a race between process startup and dynamic nvidia-smi slot selection.
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
    config_yml="configs/rgbd/experiments/exp51_f3_submit/${cfg}.yaml"
    logfile="$OUT/${outnm}.consolelog"
    echo "$outnm GPU=$gpu start $(date)" >> "$DONE"
    env PYTHONPATH=$REPO MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
      "$PY" slam.py --config "$config_yml" --seed "$seed" --eval \
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

# Deliberately assign each arm/seed to a fixed physical GPU. The A2 seed0
# validation was already completed in the old root and is copied below; all
# other formal runs execute serially within one of these two workers.
: > "$DONE"

GPU0_RUNS=(
  "A1|exp51_mrcs_async10_f3_st_hf|0"
  "A1|exp51_mrcs_async10_f3_st_hf|1"
  "A1|exp51_mrcs_async10_f3_st_hf|2"
  "B1|exp51_vanilla_async10_f3_st_hf|0"
  "B1|exp51_vanilla_async10_f3_st_hf|1"
  "B1|exp51_vanilla_async10_f3_st_hf|2"
)
GPU1_RUNS=(
  "A2|exp51_mrcs_async50_f3_st_hf|0"
  "A2|exp51_mrcs_async50_f3_st_hf|1"
  "A2|exp51_mrcs_async50_f3_st_hf|2"
  "B2|exp51_vanilla_async50_f3_st_hf|0"
  "B2|exp51_vanilla_async50_f3_st_hf|1"
  "B2|exp51_vanilla_async50_f3_st_hf|2"
)

# Convert the validated A2 seed0 result into the v2 root without rerunning it.
# The copy is recorded and remains eligible only if its config/provenance matches.
if [ ! -f "$OUT/A2_seed0/tables/tracking_raw.csv" ] \
   && [ -f "results/runs/EXP51/f3_submit/A2_seed0/tables/tracking_raw.csv" ]; then
  cp -a results/runs/EXP51/f3_submit/A2_seed0 "$OUT/A2_seed0"
  cp -a results/runs/EXP51/f3_submit/A2_seed0.consolelog "$OUT/A2_seed0.consolelog"
  echo "A2_seed0 COPIED_FROM_VALIDATED_RUN $(date)" >> "$DONE"
fi

run_worker 0 "${GPU0_RUNS[@]}" &
pid0=$!
run_worker 1 "${GPU1_RUNS[@]}" &
pid1=$!
wait "$pid0"; rc0=$?
wait "$pid1"; rc1=$?
echo "=== EXP51 ALL_DONE rc0=$rc0 rc1=$rc1 $(date) ===" >> "$DONE"
if [ "$rc0" -ne 0 ] || [ "$rc1" -ne 0 ]; then
  exit 1
fi
