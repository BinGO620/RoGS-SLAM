#!/bin/bash
# WP-B CONFIRM — 3090 双卡 36-run（CCF-C 整改执行卡 v3 §4 WP-B; 2026-08-15 exp19）。
# 三臂（同 campaign, held-out 4 序列 × 3 seed）, 全部无 --fast 完整协议（P7/WP-A 同款）。
#   1) vanilla   = WP-A K0R0L0              (reuse wpa_<seq>_K0R0L0.yaml; balloon2 new)
#   2) flow-mask = vanilla + flow_threshold p90  (new configs/configs/rgbd/experiments/wpb_confirm/)
#   3) MRCS      = WP-A K1R1L1              (reuse wpa_<seq>_K1R1L1.yaml; balloon2 new)
# held-out: pt1, pt2 (=① clean, 主判据), mv_no_box2, balloon2 (=② same-family, 次级).
# 判定 prerg §七 (δ=0.20, held-out①=pt1/pt2 为主判据 2/2)。分母固定 4, 全 3-seed。
# 起跑要求：装置 commit；软链 OK；协议=WP-A 同款完整 (tracking_raw.csv + trj_full_final.json)。
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/WPB/WPB-CONFIRM; mkdir -p "$OUT"
DONE="$OUT/wpb_confirm.done"
: > "$DONE"

# grid: {seq-prefix}|{arm-config}|{arm-tag}|{seed}
# vanilla/MRCS reuse wpa_factorial configs (pt1/pt2/mv_no_box2 exist; balloon2 uses new)
SEQS="pt1 pt2 mv_no_box2 balloon2"
RUNS=""
for seed in 0 1 2; do
  for s in $SEQS; do
    # vanilla K0R0L0
    case $s in
      balloon2) v_cfg=configs/rgbd/experiments/wpb_confirm/confirm_balloon2_vanilla.yaml; v_tag=vanilla;;
      *)        v_cfg=configs/rgbd/experiments/wpa_factorial/wpa_${s}_K0R0L0.yaml; v_tag=vanilla;;
    esac
    RUNS="$RUNS ${s}|$v_cfg|$v_tag|$seed"
    # flow-mask p90
    RUNS="$RUNS ${s}|configs/rgbd/experiments/wpb_confirm/confirm_${s}_flowmask.yaml|flowmask|$seed"
    # MRCS K1R1L1
    case $s in
      balloon2) m_cfg=configs/rgbd/experiments/wpb_confirm/confirm_balloon2_MRCS.yaml; m_tag=MRCS;;
      *)        m_cfg=configs/rgbd/experiments/wpa_factorial/wpa_${s}_K1R1L1.yaml; m_tag=MRCS;;
    esac
    RUNS="$RUNS ${s}|$m_cfg|$m_tag|$seed"
  done
done

# Slot gate: count ONLY real SLAM workers. The naive pattern 'slam.py --config' also
# matches any monitoring/ssh command line that merely CONTAINS that literal text, which
# deadlocks the gate at a phantom count (observed 2026-08-15: 2 launcher instances hung
# forever while zero SLAM ran). Anchor on the interpreter path instead — only a genuine
# worker's argv starts with it.
SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }

wait_slot() {
  while [ "$(slam_count)" -ge 2 ]; do
    sleep 20
  done
}

for entry in $RUNS; do
  seq="${entry%%|*}"; rest="${entry#*|}"
  cfg="${rest%%|*}"; rest="${rest#*|}"
  arm="${rest%%|*}"; seed="${rest##*|}"
  outnm="${arm}_${seq}_${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "$outnm SKIP" >> "$DONE"; continue; }
  wait_slot
  gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
  echo "$(date +%H:%M) RUN $outnm ($cfg) on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config "$cfg" --seed "$seed" --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED($(date +%H:%M))" >> "$DONE"; sleep 3
done
while [ "$(slam_count)" -gt 0 ]; do sleep 30; done
echo "CONFIRM_ALL_DONE $(date)" >> "$DONE"
