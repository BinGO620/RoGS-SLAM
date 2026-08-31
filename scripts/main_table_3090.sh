#!/bin/bash
# ============================================================================
# Managed 3090/2060 wrapper for the ACTIVE experiment contract (R1-P01 series).
#
# 2026-07-21 受管化改造：旧版直接驱动 slam.py 并在脚本里现场生成 4 臂 overlay，
# 绕过了 APPROVED-manifest / clean-git / provenance / paired-config 检查，且 flow
# 只查存在不查完整（obox 79/590 陷阱）——该版本已退役（git 历史保留）。
#
# 本包装只做两件事：
#   1. preflight —— worktree clean 快速检查 + frozen-flow 完整性断言
#      （scripts/check_flow_complete.py：n_flow >= n_rgb-1 且 manifest==n_rgb）；
#   2. 委托 scripts/run_monogs_batch.py --manifest 执行（含 contract 校验、
#      watchdog、geometry eval 与 run_manifest.json provenance）。
# 多臂矩阵不在这里展开：R1-P01=deferred-vs-prune，R1-P02=deferred-vs-immediate，
# R1-P03=combined-vs-prune，各自是独立的 pairwise manifest（见 active/candidate/README）。
# ============================================================================
set -euo pipefail
PY=${PY:-/data/conda_envs/monogs-ours/bin/python}
REPO=${REPO:-/data/monogs-ours}
MANIFEST=${MANIFEST:-configs/rgbd/experiments/active/experiment.yaml}
cd "$REPO"

echo "[preflight] git worktree must be clean (runner enforces authoritatively)"
if [ -n "$(git status --porcelain --untracked-files=all)" ]; then
  git status --short | head -10
  echo "worktree dirty; commit the frozen code/plan/manifest first" >&2
  exit 1
fi

echo "[preflight] frozen-flow completeness for $MANIFEST"
"$PY" scripts/check_flow_complete.py --manifest "$MANIFEST"

echo "[run] managed batch via run_monogs_batch.py"
exec "$PY" scripts/run_monogs_batch.py --manifest "$MANIFEST" "$@"
