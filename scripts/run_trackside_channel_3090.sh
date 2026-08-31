#!/bin/bash
# trackside 通道隔离 —— mask 的第三条通道（exp36, 2026-08-21）
#
# 预注册：results/evidence/trackside_channel_prereg.md（发批前已 commit）
#
# 本臂 = `enabled=true, mask_mapping=false, mask_insertion=false`：mask 照算，但两个
# 消费者全关 ⇒ 只剩 tracking 侧（光度损失前 warmup_iters=10 次迭代 + T2 候选集）。
# 它补的不是「2×2 的第四格」——那格 exp35 已补（insertion-off）——而是被 maskfree
# 掩盖掉的第三条通道：
#
#          | ins=T                  | ins=F
#   -------|------------------------|--------------------------
#    map=T | A eboth      ✅已测    | B insertion-off ✅已测(exp35)
#    map=F | C mapping-off ✅已测   | E trackside-only ← 本批
#   （D maskfree = enabled:false，把 tracking 侧和 T2 一起关了，不是 E）
#
# 三格已有 ⇒ 本批只跑 E，对照臂**不重跑**（exp34 已验 eboth 复跑 +3.9% < 6% 噪声地板）。
# 序列 = balloon / f3_wk_xyz（可判）+ pt1（描述性）。mv_no_box 比值 0.54 排除。
# 单变量隔离由 tests/test_pba_ba_coupling.py::TestPBATracksideOnlyConfigs 钉住（15 passed）。
#
# 分阶预算（硬纪律）：
#   PHASE=0  balloon seed0 单 run，只验装置门 G1/G3，不看 ATE。门不过就停。
#   PHASE=1  balloon seed1/2 + f3_wk_xyz ×3 —— 预注册 §4 算过：只跑 balloon 注定
#            INDETERMINATE（间距仅 1.8× 极差），f3_wk_xyz 间距 35× 极差才是判别序列。
#   PHASE=2  pt1 ×3（描述性）。
#
# 用法（jiangwenheng 上）：
#   PHASE=0 nohup bash scripts/run_trackside_channel_3090.sh > results/runs/trackside_p0.log 2>&1 &
#   PHASE=1 nohup bash scripts/run_trackside_channel_3090.sh > results/runs/trackside_p1.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/PBA}; mkdir -p "$OUT"
PHASE=${PHASE:-0}
DONE="$OUT/trackside_phase${PHASE}.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-6}

case "$PHASE" in
  0) SEQS=${SEQS:-"balloon"};            SEEDS=${SEEDS:-"0"} ;;
  1) SEQS=${SEQS:-"balloon f3_wk_xyz"};  SEEDS=${SEEDS:-"0 1 2"} ;;
  2) SEQS=${SEQS:-"pt1"};                SEEDS=${SEEDS:-"0 1 2"} ;;
  *) echo "ABORT: unknown PHASE=$PHASE" >> "$DONE"; exit 1 ;;
esac

# ---- precheck：config 存在 + 臂标正确 + 数据存在 + frozen flow 非空（exp24 空转事故）----
for seq in $SEQS; do
  cfg="configs/rgbd/experiments/pba_ba_coupling/pba_trackside_only_${seq}.yaml"
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
  # 装置门 G0：解析后必须 enabled=T / mapping=F / insertion=F，否则臂标是错的
  iso=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
c = load_config('$cfg')['SemanticMask']
ok = c['enabled'] and (not c['mask_mapping']) and (not c['mask_insertion'])
print('OK' if ok else 'BAD')" 2>/dev/null)
  [ "$iso" = "OK" ] || { echo "ABORT: $seq 臂标错 (enabled/mapping/insertion = $iso)" >> "$DONE"; exit 1; }
  dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
  [ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: $seq 数据缺 ($dp)" >> "$DONE"; exit 1; }
  n=$(ls "$dp"/flow_raft/*.npy 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] || { echo "ABORT: $seq flow_raft 空 ($dp)" >> "$DONE"; exit 1; }
  echo "precheck OK $seq iso=$iso flow=$n" >> "$DONE"
done
echo "$(date +%F' '%H:%M) LAUNCH phase=$PHASE seqs=[$SEQS] seeds=[$SEEDS] maxjobs=$MAXJOBS" >> "$DONE"

# pgrep 必须锚定 argv 起始（exp19 一晚咬三次：非锚定会匹配监控命令自身）
SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

for seq in $SEQS; do
  for seed in $SEEDS; do
    cfg="configs/rgbd/experiments/pba_ba_coupling/pba_trackside_only_${seq}.yaml"
    outnm="pba_trackside_only_${seq}_seed${seed}"
    [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] && { echo "SKIP $outnm (done)" >> "$DONE"; continue; }
    wait_slot
    gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
          | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
    echo "$(date +%H:%M) RUN $outnm on gpu$gpu" >> "$DONE"
    env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
      $PY slam.py --config "$cfg" --fast --seed "$seed" \
      --results-root "$OUT/$outnm" > "$OUT/$outnm.consolelog" 2>&1 &
    sleep 6
  done
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done

missing=0
for seq in $SEQS; do for seed in $SEEDS; do
  outnm="pba_trackside_only_${seq}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
done; done

# ---- 装置门 G1（插入门必须不响）+ G3（被测通道必须活着）-------------------------
# 正负两边都验（R2-P04 的 G5 教训：只验一边会把静默退化读成 null-vs-null）。
# G2/G4 在判决脚本里对控制臂验（控制臂不重跑，引用其自身日志）。
gate_violations=0
for seq in $SEQS; do for seed in $SEEDS; do
  outnm="pba_trackside_only_${seq}_seed${seed}"
  log="$OUT/$outnm.consolelog"
  if [ -f "$log" ]; then
    # ⚠ 2026-08-22 exp37 修：原写法 `$(grep -c ... || echo 0)` 在**零匹配**时拼出 "0\n0"
    # （grep -c 既打印 0 又退出 1），`[ "0\n0" -gt 0 ]` 报错为假 ⇒ 走 else 报 G1_OK。
    # 实测后果：只有零匹配被污染，而那时真实计数确实是 0 ⇒ **碰巧答对，没有漏放违规**；
    # 非零匹配值干净会被正确标出。exp36 那次 G1 6/6 已用直接测量独立复核成立
    # （6 run 真实全 0，对照臂 67 次）。仍然改掉：门必须真的在比数据。
    hits=$(grep -c "Semantic insertion gate" "$log" 2>/dev/null || true)
    case "$hits" in
      ''|*[!0-9]*)
        echo "G1_MALFORMED $outnm: count=[$hits] 门没在比数, 按不过计" >> "$DONE"
        gate_violations=$((gate_violations+1)) ;;
      0) echo "G1_OK $outnm: 插入门 0 次" >> "$DONE" ;;
      *) echo "G1_VIOLATION $outnm: 插入门响了 $hits 次（开关没生效）" >> "$DONE"
         gate_violations=$((gate_violations+1)) ;;
    esac
  fi
  # G3：frames.csv 的 mad_excl_semantic 占比 >= 0.95 ⇒ semantic mask 确实算出来且
  # 进了 tracking 侧的消费路径（日志级直接量，不是代理量）。
  fcsv=$(find "$OUT/$outnm" -name frames.csv 2>/dev/null | head -1)
  if [ -n "$fcsv" ]; then
    frac=$(PYTHONPATH=$PWD $PY -c "
import csv,sys
rows=list(csv.DictReader(open('$fcsv')))
if not rows or 'mad_excl_semantic' not in rows[0]: print('NOCOL'); sys.exit()
n=sum(1 for r in rows if str(r['mad_excl_semantic']).strip() in ('1','1.0'))
print(f'{n/len(rows):.4f}')" 2>/dev/null)
    ok=$(PYTHONPATH=$PWD $PY -c "print('YES' if '$frac' not in ('','NOCOL') and float('$frac')>=0.95 else 'NO')" 2>/dev/null)
    if [ "$ok" = "YES" ]; then
      echo "G3_OK $outnm: mad_excl_semantic frac=$frac（通道活着）" >> "$DONE"
    else
      echo "G3_VIOLATION $outnm: mad_excl_semantic frac=$frac（<0.95 或无该列 ⇒ 被测通道没活）" >> "$DONE"
      gate_violations=$((gate_violations+1))
    fi
  else
    echo "G3_NODATA $outnm: 找不到 frames.csv" >> "$DONE"
    gate_violations=$((gate_violations+1))
  fi
done; done

echo "TRACKSIDE_PHASE${PHASE}_DONE $(date) missing=$missing gate_violations=$gate_violations" >> "$DONE"
