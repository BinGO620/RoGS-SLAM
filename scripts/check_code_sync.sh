#!/bin/bash
# check_code_sync.sh — 远程批量前强制代码一致性校验（cb 主阵地的演化同步到远程）
#
# 铁律（exp24, 用户明确要求）：cb 是方法演化主阵地，代码都在 cb 改、push origin；
# 远程 jiangwenheng 每次跑批量前必须 HEAD == origin/ours-v3 == 本地已 push 的最新。
# 否则远程跑的是旧代码，之前就是这么白跑 / 跑错（flow 缺失 + 代码滞后）。
#
# 用法（本地 cb 执行）:
#   bash scripts/check_code_sync.sh [host]   # 默认 jiangwenheng@172.16.227.24
#   返回 0 = 一致可跑；非 0 = 不一致，需要先同步。
#
# 校验 3 项:
#   1. 本地 cb 无未提交改动（有则说明 cb 有最新演化未 push，远程必然不一致）
#   2. 本地 origin/ours-v3 == 本地 HEAD（本地已 push）
#   3. 远程 HEAD == origin/ours-v3

set -u
REMOTE=${1:-jiangwenheng@172.16.227.24}
REPO=/home/jiangwenheng/cron/monogs-ours
FAIL=0

echo "=== code-sync check: cb(本地) vs origin vs $REMOTE ==="

# 1. 本地无未提交改动
LOCAL_DIRTY=$(cd "$(dirname "$0")/.." && git status --porcelain | grep -v '^??' | wc -l)
LOCAL_HEAD=$(cd "$(dirname "$0")/.." && git rev-parse HEAD)
LOCAL_ORIGIN=$(cd "$(dirname "$0")/.." && git rev-parse origin/ours-v3)

echo "  本地 HEAD      = ${LOCAL_HEAD:0:9}"
echo "  本地 origin    = ${LOCAL_ORIGIN:0:9}"

if [ "$LOCAL_HEAD" != "$LOCAL_ORIGIN" ]; then
  echo "  ✗ FAIL: 本地 HEAD != origin (有未 push 的 commit)，远程必然落后。"
  FAIL=1
fi

# 2. 远程 HEAD
REMOTE_HEAD=$(timeout 30 ssh -o BatchMode=yes "$REMOTE" "cd $REPO && git rev-parse HEAD 2>/dev/null")
echo "  远程 $REMOTE   = ${REMOTE_HEAD:0:9}"

if [ "$REMOTE_HEAD" != "$LOCAL_ORIGIN" ]; then
  echo "  ✗ FAIL: 远程 HEAD != origin。远程可能是旧代码，勿跑批量。"
  FAIL=1
fi

if [ "$LOCAL_DIRTY" -gt 0 ]; then
  echo "  ✗ FAIL: 本地有 $LOCAL_DIRTY 个已跟踪文件的未提交改动，请先 commit+push。"
  FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
  echo "  ✓ PASS: cb 与 $REMOTE 代码完全一致，可以跑批量。"
else
  echo "  ✗ 不一致。先同步：本地 commit+push；远程 git fetch && git merge --ff-only origin/ours-v3"
fi
exit $FAIL
