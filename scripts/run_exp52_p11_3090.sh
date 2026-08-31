#!/bin/bash
# EXP52 — P11 sparse-KF mask-only 当前 HEAD 重验 + MRCS+async50 balloon matched 对照。
#
# 在远程 jiangwenheng 服务器上执行。3 臂 × 3 seed = 9 run,拆双卡并行:
#   GPU0 = P11F (P11 mask-only, f3_st_hf) ×3
#   GPU1 = P11B (P11 mask-only, balloon) ×3 + M50B (MRCS+async50, balloon) ×3
#
# 预注册:results/evidence/exp52_p11_prereg.md(判据 G0-G3 冻结,先于本脚本派发)。
# 约束:远程 tracked HEAD 必须与 EXPECTED_HEAD 一致且 worktree 干净;
# 正式数据全部以 3090 为准;本地 cb(2060) 不做判决。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
EXPECTED_HEAD=c544b940f231f0bd8dda453439158e5c478ef9d8
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
export EXPECTED_HEAD PY
OUT=${OUT:-results/runs/EXP52/p11_matched}
mkdir -p "$OUT"
DONE="$OUT/exp52.done"

# Refuse to launch if the tracked code is not the audited HEAD.
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
  configs/rgbd/experiments/p11_maskonly/p11_maskonly_f3_st_hf.yaml \
  configs/rgbd/experiments/p11_maskonly/p11_maskonly_balloon.yaml \
  configs/rgbd/experiments/exp52_p11/exp52_mrcs_async50_balloon.yaml; do
  if [ ! -f "$required" ]; then
    echo "ERROR: missing required file $required" >&2
    exit 2
  fi
done

# Flow preflight per sequence, in the loader's frame-stem口径 (TUMParser for both TUM
# and Bonn): parser frames must match the flow manifest, and every runtime frame after
# the first must have a frozen backward-flow .npy keyed by its stem.
if ! "$PY" - <<'PY'
import glob
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from utils.config_utils import load_config
from utils.dataset import TUMParser

PAIRS = [
    ("configs/rgbd/experiments/p11_maskonly/p11_maskonly_f3_st_hf.yaml", "f3_st_hf"),
    ("configs/rgbd/experiments/exp52_p11/exp52_mrcs_async50_balloon.yaml", "balloon"),
]
for config_path, label in PAIRS:
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
        "manifest_unique_stems": len(set(manifest.get("frame_stems", []))),
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

# Record immutable run provenance before dispatching any GPU work. The runtime-file
# list matches exp51_provenance.json's four runtime entries (plus the rest of the
# runtime surface and the EXP52 config chains) so the verdict can diff hashes against
# EXP51 and prove runtime-code equivalence for the reused A2 f3_st_hf comparison side.
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
    "configs/rgbd/tum/f3_st_hf.yaml",
    "configs/rgbd/experiments/active/candidate/method_combined_maskoff_prune.yaml",
    "configs/rgbd/experiments/wpm_maskonly/method_maskonly.yaml",
    "configs/rgbd/experiments/p11_maskonly/method_p11_maskonly.yaml",
    "configs/rgbd/experiments/p11_maskonly/p11_maskonly_f3_st_hf.yaml",
    "configs/rgbd/experiments/p11_maskonly/p11_maskonly_balloon.yaml",
]
files.extend(str(path) for path in sorted(Path("configs/rgbd/experiments/exp52_p11").glob("*.yaml")))
files.extend([
    "scripts/run_exp52_p11_3090.sh",
    "scripts/read_exp52_p11.py",
    "tests/test_exp52_p11_configs.py",
    "results/evidence/exp52_p11_prereg.md",
])

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

payload = {
    "experiment": "EXP52-P11-revalidate-matched",
    "expected_head": os.environ.get("EXPECTED_HEAD"),
    "actual_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "hostname": socket.gethostname(),
    "python": os.path.realpath(os.environ.get("PY", "")),
    "files_sha256": {path: sha256(path) for path in files},
}
with open("results/runs/EXP52/exp52_provenance.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
print("WROTE results/runs/EXP52/exp52_provenance.json")
PY

# 3 臂。config = 完整配置路径。格式:name|config_path|seed
# P11F: vanilla KF + mask_mapping + huber (ReliabilitySignal/DynKF/insertion OFF)
# P11B: 同 P11F, balloon
# M50B: MRCS (mask-free combined) + async_iter_per_kf=50, balloon
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

P11F=configs/rgbd/experiments/p11_maskonly/p11_maskonly_f3_st_hf.yaml
P11B=configs/rgbd/experiments/p11_maskonly/p11_maskonly_balloon.yaml
M50B=configs/rgbd/experiments/exp52_p11/exp52_mrcs_async50_balloon.yaml

GPU0_RUNS=(
  "P11F|$P11F|0"
  "P11F|$P11F|1"
  "P11F|$P11F|2"
)
GPU1_RUNS=(
  "P11B|$P11B|0"
  "P11B|$P11B|1"
  "P11B|$P11B|2"
  "M50B|$M50B|0"
  "M50B|$M50B|1"
  "M50B|$M50B|2"
)

run_worker 0 "${GPU0_RUNS[@]}" &
pid0=$!
run_worker 1 "${GPU1_RUNS[@]}" &
pid1=$!
wait "$pid0"; rc0=$?
wait "$pid1"; rc1=$?
echo "=== EXP52 ALL_DONE rc0=$rc0 rc1=$rc1 $(date) ===" >> "$DONE"
if [ "$rc0" -ne 0 ] || [ "$rc1" -ne 0 ]; then
  exit 1
fi
