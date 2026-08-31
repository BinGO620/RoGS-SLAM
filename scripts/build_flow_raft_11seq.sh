#!/bin/bash
# build_flow_raft_11seq.sh — 补全 11 条缺失的 flow_raft (jiangwenheng 远程A, 2x3090)
# 执行: conda run -n monogs-ours-3090 bash scripts/build_flow_raft_11seq.sh
set -e

REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
BASE=/mnt/app/datasets

OUT_DIR=results/runs/flow_build_log; mkdir -p "$OUT_DIR"

# GPU0=0 GPU1=1, 两卡并行：GPU0 建 Bonn, GPU1 建 TUM (先短序列, 后长序列)
# 每个 GPU 串行: 上一个建完再下一个

build_one() {
  local gpu=$1 seq_dir=$2 config_opt=$3 label=$4
  echo "[$(date '+%H:%M:%S')] START $label (GPU$gpu)"
  CMD="$PY scripts/build_flow_raft.py --sequence-dir $seq_dir --variant small --iters 12 --device cuda:0 $config_opt"
  echo "  $CMD"
  if CUDA_VISIBLE_DEVICES=$gpu $CMD > "$OUT_DIR/$label.log" 2>&1; then
    echo "[$(date '+%H:%M:%S')] DONE  $label"
  else
    echo "[$(date '+%H:%M:%S')] FAIL  $label (see $OUT_DIR/$label.log)"
  fi
}

# GPU0: Bonn (distorted=true, 用 Bonn 默认内参，不传 --config)
(
  build_one 0 "$BASE/Bonn/rgbd_bonn_crowd"    "" "bonn_crowd"
  build_one 0 "$BASE/Bonn/rgbd_bonn_crowd2"   "" "bonn_crowd2"
) & GPU0_PID=$!

# GPU1: TUM 短+中序列 (distorted=false, 内参恒等不影响, 但传 config 以记录正确内参)
(
  # f1_base (f1_desk 用 f1_base.yaml)
  build_one 1 "$BASE/TUM/rgbd_dataset_freiburg1_desk"              "--config configs/rgbd/tum/f1_desk.yaml"  "tum_f1_desk"
  build_one 1 "$BASE/TUM/rgbd_dataset_freiburg3_sitting_rpy"      "--config configs/rgbd/tum/f3_st_rpy.yaml" "tum_f3_st_rpy"
  build_one 1 "$BASE/TUM/rgbd_dataset_freiburg3_walking_rpy"      "--config configs/rgbd/tum/f3_wk_rpy.yaml" "tum_f3_wk_rpy"
  build_one 1 "$BASE/TUM/rgbd_dataset_freiburg3_sitting_halfsphere" "--config configs/rgbd/tum/f3_st_hf.yaml" "tum_f3_st_hf"
  build_one 1 "$BASE/TUM/rgbd_dataset_freiburg3_walking_halfsphere" "--config configs/rgbd/tum/f3_wk_hf.yaml" "tum_f3_wk_hf"
  build_one 1 "$BASE/TUM/rgbd_dataset_freiburg3_sitting_xyz"      "--config configs/rgbd/tum/f3_st_xyz.yaml" "tum_f3_st_xyz"
  # f2_xyz 补全(全量 rerun，旧的会被覆盖)
  build_one 1 "$BASE/TUM/rgbd_dataset_freiburg2_xyz"              "--config configs/rgbd/tum/f2_xyz.yaml"   "tum_f2_xyz"
  # 较长序列
  build_one 1 "$BASE/TUM/rgbd_dataset_freiburg3_long_office_household" "--config configs/rgbd/tum/f3_office.yaml" "tum_f3_office"
  build_one 1 "$BASE/TUM/rgbd_dataset_freiburg2_desk_with_person" "--config configs/rgbd/tum/f2_person.yaml" "tum_f2_person"
) & GPU1_PID=$!

echo "Launched GPU0=$GPU0_PID GPU1=$GPU1_PID"
wait $GPU0_PID $GPU1_PID
echo "=== ALL DONE. Log dir: $OUT_DIR ==="
ls -la "$OUT_DIR"/*.log 2>/dev/null | tail -15
