#!/bin/bash
# monitor_chenfan_sync.sh — 监控chenfan同步进度和服务器健康状态
# 在cb上运行：bash scripts/monitor_chenfan_sync.sh

CF=chenfan@100.72.201.57
LOG_FILE="results/runs/chenfan_sync_full.log"

check_progress() {
    echo "=== $(date '+%H:%M:%S') 进度检查 ==="

    # 检查同步日志状态
    echo "--- 同步状态 ---"
    if grep -q "=== ALL SEQUENCES SYNCED ===" "$LOG_FILE" 2>/dev/null; then
        echo "✅ 所有序列同步完成!"
        return 0
    else
        echo "🔄 同步进行中..."
        echo "最新状态:"
        grep -E "(START|DONE)" "$LOG_FILE" | tail -5
    fi

    # 检查服务器健康状态
    echo ""
    echo "--- 服务器健康 ---"
    ssh "$CF" "
        echo '磁盘:' && df -h /home/chenfan | tail -1
        echo '负载:' && uptime | awk -F'load average:' '{print \$2}'
        echo 'GPU温度:' && nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader | tr '\n' ' '
        echo ''
        echo '内存:' && free -h | grep Mem | awk '{print \$3\"/\"\$2}'
    "

    # 检查数据集大小
    echo ""
    echo "--- 数据集大小 ---"
    ssh "$CF" "du -sh /home/chenfan/cron/Datasets/Bonn/ /home/chenfan/cron/Datasets/TUM/ 2>/dev/null"

    # 检查flow_raft进度（仅对正在同步的序列）
    echo ""
    echo "--- Flow Raft进度 ---"
    for seq in rgbd_bonn_crowd rgbd_bonn_crowd2; do
        LOCAL_FLOW=$(ls /data/Datasets/Bonn/$seq/flow_raft/*.npy 2>/dev/null | wc -l)
        REMOTE_FLOW=$(ssh "$CF" "ls /home/chenfan/cron/Datasets/Bonn/$seq/flow_raft/*.npy 2>/dev/null | wc -l")
        if [ "$LOCAL_FLOW" -gt 0 ]; then
            echo "$seq: $REMOTE_FLOW/$LOCAL_FLOW files ($(($REMOTE_FLOW * 100 / $LOCAL_FLOW))%)"
        fi
    done

    echo ""
    echo "========================================"
}

# 主循环
while true; do
    check_progress
    if grep -q "=== ALL SEQUENCES SYNCED ===" "$LOG_FILE" 2>/dev/null; then
        echo "监控完成，同步已结束。"
        break
    fi
    sleep 120  # 每2分钟检查一次
done
