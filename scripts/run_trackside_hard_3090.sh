#!/bin/bash
# exp37 tracking 侧正控制 —— 动态惩罚 P 到底看不看得见 tracking 侧介入
#
# 预注册：results/evidence/pose_trackside_prereg_addendum.md（发批前已 commit 2985dd07）
#
# 为什么这 3 run 是 exp37 判决的生死门：exp37 判 TRACKSIDE-INERT，但它唯一的正控制是
# **mapping 侧**的（mask_mapping，间距 3.1× 地板 + 失效对照 3/3）。没有正控制证明 P 对
# tracking 侧介入敏感 ⇒ INERT 严格只能读成「没有本估计量能看见的效应」。
#
# 装置（单变量）：本臂 = trackside 臂 + `SemanticMask.hard_tracking_mask: true`
#   utils/slam_utils.py:126-153 —— reliability 的 soft 项在 warmup_iters=10 之后就位时，
#   硬 mask 会被整条旁路（get_loss_tracking_rgbd_soft），除非该 flag 为真则改走
#   get_loss_tracking_rgbd_hardsoft。⇒ 把通道①作用域从 10/100 扩到 100/100 次跟踪迭代。
#   warmup_iters 本身不动（测试钉住）；该代码路径 p6_mason 臂已在用，default-off。
#
# 判读（跑前写死，地板 0.0831 与口径全部 import exp37，不重新拟合）：
#   |P(E-hard) − P(E=+0.3996)| > 0.0831 ⇒ APPARATUS-TRACKING-SENSITIVE（exp37 判决站住）
#                                 ≤ 0.0831 ⇒ APPARATUS-TRACKING-BLIND（exp37 判决降级为描述性）
#   **不预言方向**：放大①既可能降 P 也可能升 P（P1b 测到「剔除 ⇒ H 变小 ⇒ 放大 nuisance」
#   的杠杆效应）。门只问「P 会不会动」—— 这是 exp36 那条设计对了的 G3 的做法。
#   停跑：range(P) > 0.1200 ⇒ NO VERDICT，不贴任一标签。
#
# Phase 0 纪律：3 run，只看机制诊断（G1/G3 + P 的位移），**不看 ATE**。
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_trackside_hard_3090.sh > results/runs/trackside_hard.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/PBA}; mkdir -p "$OUT"
DONE="$OUT/trackside_hard.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-3}
SEQS=${SEQS:-"balloon"}
SEEDS=${SEEDS:-"0 1 2"}
ARM=pba_trackside_hard

# ---- precheck：config 存在 + 臂标正确(含 hard flag) + 数据 + frozen flow 非空 ----
for seq in $SEQS; do
  cfg="configs/rgbd/experiments/pba_ba_coupling/${ARM}_${seq}.yaml"
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
  # 门 H-0：解析后 enabled=T / mapping=F / insertion=F / hard_tracking_mask=T
  iso=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
c = load_config('$cfg')['SemanticMask']
ok = (c['enabled'] and (not c['mask_mapping']) and (not c['mask_insertion'])
      and c.get('hard_tracking_mask', False))
print('OK' if ok else 'BAD')" 2>/dev/null)
  [ "$iso" = "OK" ] || { echo "ABORT: $seq 臂标错 (H-0 = $iso)" >> "$DONE"; exit 1; }
  # 门 H-0b：与 E 臂的唯一差异必须就是这个 flag（否则门读的是两个介入）
  base="configs/rgbd/experiments/pba_ba_coupling/pba_trackside_only_${seq}.yaml"
  onlydiff=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
a, b = load_config('$cfg'), load_config('$base')
d = []
def walk(x, y, p=''):
    for k in sorted(set(x) | set(y)):
        u, v = x.get(k), y.get(k)
        if isinstance(u, dict) and isinstance(v, dict): walk(u, v, p + k + '.')
        elif u != v: d.append(p + k)
walk(a, b)
print('OK' if sorted(d) == ['SemanticMask.hard_tracking_mask','inherit_from','method'] else ','.join(d))
" 2>/dev/null)
  [ "$onlydiff" = "OK" ] || { echo "ABORT: $seq 非单变量 (diff=$onlydiff)" >> "$DONE"; exit 1; }
  dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('$cfg')['Dataset']['dataset_path'])" 2>/dev/null)
  [ -n "$dp" ] && [ -d "$dp" ] || { echo "ABORT: $seq 数据缺 ($dp)" >> "$DONE"; exit 1; }
  n=$(ls "$dp"/flow_raft/*.npy 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] || { echo "ABORT: $seq flow_raft 空 ($dp)" >> "$DONE"; exit 1; }
  echo "precheck OK $seq H-0=$iso singlevar=$onlydiff flow=$n" >> "$DONE"
done
echo "$(date +%F' '%H:%M) LAUNCH $ARM seqs=[$SEQS] seeds=[$SEEDS] maxjobs=$MAXJOBS" >> "$DONE"

# pgrep 必须锚定 argv 起始（exp19 一晚咬三次；ERE 交替也别用 —— exp36 的 round2 教训）
SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

for seq in $SEQS; do
  for seed in $SEEDS; do
    cfg="configs/rgbd/experiments/pba_ba_coupling/${ARM}_${seq}.yaml"
    outnm="${ARM}_${seq}_seed${seed}"
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
  outnm="${ARM}_${seq}_seed${seed}"
  [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || { echo "MISSING $outnm" >> "$DONE"; missing=$((missing+1)); }
done; done

# ---- 收批门 H-2：插入门仍不响（0 次）+ 被测通道活着（mad_excl_semantic >= 0.95）----
# 正负两边都验（R2-P04 的 G5 教训）。H-3 忠实性锚在读数脚本里逐 run 验。
gate_violations=0
for seq in $SEQS; do for seed in $SEEDS; do
  outnm="${ARM}_${seq}_seed${seed}"
  log="$OUT/$outnm.consolelog"
  if [ -f "$log" ]; then
    # ⚠ 不能写 `$(grep -c ... || echo 0)` —— 见 run_trackside_paired_repeats_3090.sh 的注释。
    # 原 `-gt 0` if/else 版的实际后果（2026-08-22 实测，非推理）：只有零匹配会被污染成 "0\n0"，
    # 比较报错为假 ⇒ 走 else 报 OK，而那时真实计数**确实**是 0 ⇒ 碰巧答对；非零匹配值干净，
    # 会被正确标为 VIOLATION。**所以它没有漏放违规**，但它也没在比数据。已改为守卫式。
    hits=$(grep -c "Semantic insertion gate" "$log" 2>/dev/null || true)
    case "$hits" in
      ''|*[!0-9]*)
        echo "H2_G1_MALFORMED $outnm: count=[$hits] 门没在比数, 按不过计" >> "$DONE"
        gate_violations=$((gate_violations+1)) ;;
      0) echo "H2_G1_OK $outnm: 插入门 0 次" >> "$DONE" ;;
      *) echo "H2_G1_VIOLATION $outnm: 插入门 $hits 次" >> "$DONE"
         gate_violations=$((gate_violations+1)) ;;
    esac
  fi
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
      echo "H2_G3_OK $outnm: mad_excl_semantic frac=$frac" >> "$DONE"
    else
      echo "H2_G3_VIOLATION $outnm: mad_excl_semantic frac=$frac" >> "$DONE"
      gate_violations=$((gate_violations+1))
    fi
  else
    echo "H2_G3_NOFILE $outnm" >> "$DONE"; gate_violations=$((gate_violations+1))
  fi
done; done

echo "TRACKSIDE_HARD_DONE $(date) missing=$missing gate_violations=$gate_violations" >> "$DONE"
