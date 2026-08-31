#!/bin/bash
# 监控 cb 2060 SLAM 进程，每 10 分钟检查一次
# 发现卡住（30min 无写入）就 kill + 重启
set -u
cd /data/monogs-ours
DONE="results/runs/P11/P11-MASKONLY-2060/p11.done"
LAST_WRITE=$(find results/runs/P11/P11-MASKONLY-2060 -name "*.csv" -printf '%T+\n' 2>/dev/null | sort | tail -1)
echo "$(date +%H:%M) MONITOR_START last_write=$LAST_WRITE" >> "$DONE"

while true; do
  sleep 600  # 10 分钟
  
  CURRENT=$(pgrep -f 'slam\.py --config' | grep -v 'conda run' | grep -v pgrep | wc -l)
  if [ "$CURRENT" -eq 0 ]; then
    echo "$(date +%H:%M) MONITOR: no slam processes" >> "$DONE"
    continue
  fi
  
  NEW_WRITE=$(find results/runs/P11/P11-MASKONLY-2060 -name "*.csv" -printf '%T+\n' 2>/dev/null | sort | tail -1)
  if [ "$NEW_WRITE" = "$LAST_WRITE" ]; then
    echo "$(date +%H:%M) MONITOR: STUCK for 10min, killing" >> "$DONE"
    pgrep -f 'slam\.py --config' | grep -v 'conda run' | grep -v pgrep | xargs kill -9 2>/dev/null
    sleep 5
    pkill -9 -f 'multiprocessing.spawn' 2>/dev/null
    sleep 5
    echo "$(date +%H:%M) MONITOR: relaunching" >> "$DONE"
    nohup bash scripts/run_cb_only_critical.sh >> results/runs/P11/critical_2060.log 2>&1 &
  else
    echo "$(date +%H:%M) MONITOR: OK, new write=$NEW_WRITE" >> "$DONE"
    LAST_WRITE="$NEW_WRITE"
  fi
done
