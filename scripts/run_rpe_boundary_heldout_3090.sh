#!/bin/bash
# exp47 RPE BOUNDARY HELD-OUT — 3090 批量：RPE 分离区间 (1.572, 1.717) 的新序列外推检验。
#
# 预注册（跑前锁定，先于本脚本 commit）：results/evidence/rpe_boundary_heldout_prereg.md
# 5 held-out 序列 × 2 臂（mask-free / combined，唯一差异 = SemanticMask.enabled，
# 合同由 tests/test_p6_maskoff_configs.py 的方法级 diff 钉住 + 派发前本地已用
# resolve-diff 验证 10 份 run config 只差该键）× 3 seed = 30 runs。
#
# 序列均为 dev-18 之外、flow_raft 已就绪、我方两臂零接触（预注册 §2 审计）。
# 读数/判决规则全部在预注册 §3–§4 写死：τ=1.6445，N 带 ≥1.5/≤1.2，
# 四分支 CONFIRMED / PARTIAL / REFUTED / INCONCLUSIVE。
#
# 用法（jiangwenheng）：
#   nohup bash scripts/run_rpe_boundary_heldout_3090.sh > /dev/null 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours
cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=results/runs/RPE-BOUNDARY/rpe-heldout
mkdir -p "$OUT"
DONE="$OUT/rpeheldout.done"

# 5 seq × 2 arm。seq = config 文件名后缀（rpeh_{arm}_{seq}.yaml）。
SEQS="moving_obstructing_box moving_obstructing_box2 synchronous desk_with_person long_office"
ARMS="maskfree combined"
RUNS=""
for seed in 0 1 2; do
  for s in $SEQS; do
    for a in $ARMS; do
      RUNS="$RUNS ${s}|${a}|${seed}"
    done
  done
done

# MAXCONC=4: 2 GPUs x 2 runs each. Memory headroom measured 2026-08-26: ~1.8GB/run
# peak on 24GB cards; CPU ~5-7 cores/run on 20 cores (some contention, accepted).
MAXCONC=4
wait_slot() {
  while [ "$(pgrep -f 'python slam.py --config' 2>/dev/null | grep -cv pgrep || echo 0)" -ge "$MAXCONC" ]; do
    sleep 20
  done
}

# Pick the idle GPU: one with NO running slam.py process bound to it. Memory-based
# selection raced (CUDA allocates seconds after spawn, so a just-launched run still
# showed ~300MiB and the next pick landed on the same GPU — observed 2026-08-26:
# both seed-0 arms on gpu0, gpu1 idle). Process-based selection cannot race: we read
# each slam.py's CUDA_VISIBLE_DEVICES from /proc, which is set at spawn time.
pick_gpu() {
  # Count slam.py processes per GPU (CUDA_VISIBLE_DEVICES from /proc, set at spawn —
  # no race). 2 runs per GPU allowed (MAXPERGPU).
  MAXPERGPU=2
  for g in 0 1; do
    n=$(for p in $(pgrep -f 'python slam.py --config' 2>/dev/null); do
          tr '\0' '\n' < /proc/$p/environ 2>/dev/null | \
            sed -n "s/^CUDA_VISIBLE_DEVICES=$g\$//p"
        done | grep -c '^$')
    [ "$n" -lt "$MAXPERGPU" ] && { echo "$g"; return; }
  done
  echo ""   # both cards full (should not happen: wait_slot ran first)
}

: > "$DONE"
for entry in $RUNS; do
  seq="${entry%%|*}"; rest="${entry#*|}"; arm="${rest%%|*}"; seed="${rest##*|}"
  outnm="rpeh_${arm}_${seq}_seed${seed}"
  if [ -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "$outnm SKIP" >> "$DONE"
    continue
  fi
  wait_slot
  gpu=$(pick_gpu)
  if [ -z "$gpu" ]; then
    echo "$(date +%H:%M) NOFREEGPU $outnm" >> "$DONE"
    sleep 30
    continue
  fi
  echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
  env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
    $PY slam.py --config "configs/rgbd/experiments/rpe_boundary_heldout/rpeh_${arm}_${seq}.yaml" \
    --seed "$seed" --results-root "$OUT/$outnm" \
    > "$OUT/$outnm.consolelog" 2>&1 &
  echo "$outnm QUEUED($(date +%H:%M))" >> "$DONE"
  sleep 5
done
while [ "$(pgrep -f 'python slam.py --config' 2>/dev/null | grep -cv pgrep || echo 0)" -gt 0 ]; do sleep 30; done

missing=0
for entry in $RUNS; do
  seq="${entry%%|*}"; rest="${entry#*|}"; arm="${rest%%|*}"; seed="${rest##*|}"
  outnm="rpeh_${arm}_${seq}_seed${seed}"
  if [ ! -f "$OUT/$outnm/tables/tracking_raw.csv" ]; then
    echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1))
  fi
done
echo "ALL_DONE $(date) missing=$missing" >> "$DONE"
