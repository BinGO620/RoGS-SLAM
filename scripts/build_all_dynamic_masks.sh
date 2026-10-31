#!/usr/bin/env bash
# build_all_dynamic_masks.sh — 为全部 Bonn 动态序列构建**唯一**冻结评估掩码（远程 3090）
#
# 掩码体系重构（2026-09-21）：见 scripts/build_dynamic_mask.py 的模块 docstring。
# 产出 <seq>/dynamic_mask/{<depth_stem>.png, manifest.json}（0/255 布尔，无类号）。
# 每序列内置验证（vs OneFormer person 参照的召回 / 炸裂护栏 / 空掩码率），不过则不写盘。
#
# 用法（在远程 REPO 下）: bash scripts/build_all_dynamic_masks.sh [DEVICE]
set -u

DEV="${1:-cuda:0}"
REPO=/home/jiangwenheng/cron/monogs-ours
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
export CUDA_DEVICE_ORDER=PCI_BUS_ID
cd "$REPO" || exit 1
DS=/mnt/app/datasets/Bonn
OUT=results/lifecycle_paper2
DONE="$OUT/dynamic_mask_build.done"
LOG="$OUT/dynamic_mask_build.log"

echo "=== build dynamic_mask: device=$DEV $(date) ===" | tee -a "$DONE"
for seq in person_tracking person_tracking2 crowd crowd2 crowd3 \
           balloon balloon2 moving_nonobstructing_box moving_nonobstructing_box2; do
  d="$DS/rgbd_bonn_$seq"
  if [ ! -d "$d" ]; then echo "SKIP $seq NO-DIR" >> "$DONE"; continue; fi
  echo "--- $seq start $(date)" >> "$DONE"
  "$PY" scripts/build_dynamic_mask.py --sequence-dir "$d" --device "$DEV" --force \
      >> "$LOG" 2>&1
  rc=$?
  echo "--- $seq rc=$rc $(date)" >> "$DONE"
done
echo "DYNAMIC_MASK_BUILD_ALL_DONE $(date)" >> "$DONE"
