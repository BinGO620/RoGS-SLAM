#!/bin/bash
# exp37 配对化装置 —— 给 E 与 F 各补一轮 within-config 复跑（同 config、同 seed）
#
# 预注册：results/evidence/pose_trackside_paired_prereg.md（发批前已 commit）
#
# 买的是**分母**：E 与 F 各自的 within-config 配对地板。上一轮门比「均值位移 vs 臂内极差」
# 而停跑规则第二次为同一理由响；配对化换掉那个比法，但配对**修不了 run-to-run 非确定性**
# ⇒ 只有量出同 config 同 seed 的 |ΔP|，才知道这条路线是可判还是 UNREACHABLE。
#
# 为什么两个臂都补（而不只补 F）：配对位移的噪声由**两臂**的 within-config 方差共同决定，
# 而本轮的核心怀疑正是"F 比 E 更散"。只补 F 就得把 E 的地板从别的臂借过来 = 用假设回答问题。
# 并发 3 下 6 run 与 2 run 的 wall-clock 相同（上批 3 run 用 16 min）。
#
# 落盘形式：**写进同一个 run 目录**（同 --results-root）⇒ slam.py 追加一个新的时间戳目录、
# tracking_raw.csv 累积一行，与 exp37 那 4 对 null 的形式一致，scripts/pose_rpe_calibration.py
# 的 _load_runs 自动认得两次。**所以这里不能带 "已存在就 SKIP" 的判断** —— 恰恰相反，
# 本脚本要求每格跑完后有 >=2 个 run，并在收批时验证（门 J-2）。
#
# Phase 0 纪律：只看机制（地板与位移），**不看 ATE**。
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_trackside_paired_repeats_3090.sh > results/runs/paired_rep.log 2>&1 &
set -u
REPO=/home/jiangwenheng/cron/monogs-ours; cd "$REPO"
PY=/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python
OUT=${OUT:-results/runs/PBA}; mkdir -p "$OUT"
DONE="$OUT/trackside_paired_repeats.done"; touch "$DONE"
MAXJOBS=${MAXJOBS:-3}
SEEDS=${SEEDS:-"0 1 2"}
SEQ=balloon
# arm-tag -> config basename
ARMS=${ARMS:-"pba_trackside_only pba_trackside_hard"}

# ---- precheck：两个 config 都在、臂标正确、唯一差异是 hard flag、数据与 frozen flow 非空 ----
for arm in $ARMS; do
  cfg="configs/rgbd/experiments/pba_ba_coupling/${arm}_${SEQ}.yaml"
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
  iso=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
c = load_config('$cfg')['SemanticMask']
print('OK' if (c['enabled'] and not c['mask_mapping'] and not c['mask_insertion']) else 'BAD')" 2>/dev/null)
  [ "$iso" = "OK" ] || { echo "ABORT: $arm 臂标错 ($iso)" >> "$DONE"; exit 1; }
  # 每格必须已经有 >=1 个 run（本批是"补复跑"，不是首跑）
  for seed in $SEEDS; do
    outnm="${arm}_${SEQ}_seed${seed}"
    [ -f "$OUT/$outnm/tables/tracking_raw.csv" ] || {
      echo "ABORT: $outnm 还没有首跑，本批是补复跑" >> "$DONE"; exit 1; }
  done
  echo "precheck OK $arm iso=$iso" >> "$DONE"
done
# 门 J-4：两臂唯一差异必须仍是 hard_tracking_mask
onlydiff=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
a = load_config('configs/rgbd/experiments/pba_ba_coupling/pba_trackside_hard_${SEQ}.yaml')
b = load_config('configs/rgbd/experiments/pba_ba_coupling/pba_trackside_only_${SEQ}.yaml')
d = []
def walk(x, y, p=''):
    for k in sorted(set(x) | set(y)):
        u, v = x.get(k), y.get(k)
        if isinstance(u, dict) and isinstance(v, dict): walk(u, v, p + k + '.')
        elif u != v: d.append(p + k)
walk(a, b)
print('OK' if sorted(d) == ['SemanticMask.hard_tracking_mask','inherit_from','method'] else ','.join(d))
" 2>/dev/null)
[ "$onlydiff" = "OK" ] || { echo "ABORT: J-4 非单变量 (diff=$onlydiff)" >> "$DONE"; exit 1; }
dp=$(PYTHONPATH=$PWD $PY -c "from utils.config_utils import load_config;print(load_config('configs/rgbd/experiments/pba_ba_coupling/pba_trackside_only_${SEQ}.yaml')['Dataset']['dataset_path'])" 2>/dev/null)
n=$(ls "$dp"/flow_raft/*.npy 2>/dev/null | wc -l)
[ "$n" -gt 0 ] || { echo "ABORT: flow_raft 空 ($dp)" >> "$DONE"; exit 1; }
echo "$(date +%F' '%H:%M) LAUNCH paired-repeats arms=[$ARMS] seeds=[$SEEDS] flow=$n" >> "$DONE"

# pgrep 锚定 argv 起始，不用 ERE 交替（exp19/exp36 教训）
SLAM_PAT="^${PY} slam\.py"
slam_count() { pgrep -c -f "$SLAM_PAT" 2>/dev/null || echo 0; }
wait_slot() { while [ "$(slam_count)" -ge "$MAXJOBS" ]; do sleep 20; done; }

for arm in $ARMS; do
  for seed in $SEEDS; do
    cfg="configs/rgbd/experiments/pba_ba_coupling/${arm}_${SEQ}.yaml"
    outnm="${arm}_${SEQ}_seed${seed}"
    before=$(PYTHONPATH=$PWD $PY -c "
import csv;print(sum(1 for _ in csv.DictReader(open('$OUT/$outnm/tables/tracking_raw.csv'))))" 2>/dev/null || true)
    case "$before" in ''|*[!0-9]*) before="?" ;; esac
    echo "$(date +%H:%M) REPEAT $outnm (rows_before=$before)" >> "$DONE"
    wait_slot
    gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
          | sort -t',' -k2 -n | head -1 | cut -d',' -f1 | tr -d ' ')
    env PYTHONPATH=$PWD MPLBACKEND=Agg CUDA_VISIBLE_DEVICES=$gpu \
      $PY slam.py --config "$cfg" --fast --seed "$seed" \
      --results-root "$OUT/$outnm" >> "$OUT/$outnm.repeat.consolelog" 2>&1 &
    sleep 6
  done
done

while [ "$(slam_count)" -gt 0 ]; do sleep 30; done

# ---- 收批门 J-2（每格 >=2 个 run）+ J-3（通道存活，正负两侧）----------------------
violations=0
for arm in $ARMS; do for seed in $SEEDS; do
  outnm="${arm}_${SEQ}_seed${seed}"
  rows=$(PYTHONPATH=$PWD $PY -c "
import csv;print(sum(1 for _ in csv.DictReader(open('$OUT/$outnm/tables/tracking_raw.csv'))))" 2>/dev/null || true)
  trj=$(find "$OUT/$outnm" -name trj_full_final.json 2>/dev/null | wc -l)
  case "$rows" in ''|*[!0-9]*) rows=-1 ;; esac
  if [ "$rows" -ge 2 ] && [ "$trj" -ge 2 ]; then
    echo "J2_OK $outnm: rows=$rows trj=$trj" >> "$DONE"
  else
    echo "J2_VIOLATION $outnm: rows=$rows trj=$trj (需要 >=2)" >> "$DONE"
    violations=$((violations+1))
  fi
  log="$OUT/$outnm.repeat.consolelog"
  if [ -f "$log" ]; then
    # ⚠ 别写 `$(grep -c ... || echo 0)`：grep -c 在**零匹配**时既打印 0 又以状态 1 退出，
    # `|| echo 0` 于是也执行，拼出 "0\n0"，整数比较报错 ⇒ 门不再比那个计数。
    # 只有零匹配会被污染（非零匹配 grep 退出 0，值是干净的），所以后果取决于怎么写比较：
    #   `[ "$hits" -eq 0 ] && OK || BAD`  -> 报错为假 -> **永远 BAD**（本轮 6 个假警报就是它）
    #   `if [ "$hits" -gt 0 ]; else OK`   -> 报错为假 -> 走 else 报 OK，而真实计数确实是 0
    #                                        ⇒ 碰巧答对，**不是**漏放违规
    # 无论哪种，门都没在比数据。正确形式：`|| true` 只吞退出码 + 整数守卫，坏值必须响。
    hits=$(grep -c "Semantic insertion gate" "$log" 2>/dev/null || true)
    case "$hits" in
      ''|*[!0-9]*)
        echo "J3_G1_MALFORMED $outnm: count=[$hits] 门没在比数, 按不过计" >> "$DONE"
        violations=$((violations+1)) ;;
      0) echo "J3_G1_OK $outnm: 插入门 0 次" >> "$DONE" ;;
      *) echo "J3_G1_VIOLATION $outnm: 插入门 $hits 次" >> "$DONE"
         violations=$((violations+1)) ;;
    esac
  else
    echo "J3_G1_NOLOG $outnm" >> "$DONE"; violations=$((violations+1))
  fi
  fcsv=$(find "$OUT/$outnm" -name frames.csv 2>/dev/null | tail -1)
  if [ -n "$fcsv" ]; then
    frac=$(PYTHONPATH=$PWD $PY -c "
import csv,sys
rows=list(csv.DictReader(open('$fcsv')))
if not rows or 'mad_excl_semantic' not in rows[0]: print('NOCOL'); sys.exit()
n=sum(1 for r in rows if str(r['mad_excl_semantic']).strip() in ('1','1.0'))
print(f'{n/len(rows):.4f}')" 2>/dev/null)
    ok=$(PYTHONPATH=$PWD $PY -c "print('YES' if '$frac' not in ('','NOCOL') and float('$frac')>=0.95 else 'NO')" 2>/dev/null)
    [ "$ok" = "YES" ] && echo "J3_G3_OK $outnm: frac=$frac" >> "$DONE" \
      || { echo "J3_G3_VIOLATION $outnm: frac=$frac" >> "$DONE"; violations=$((violations+1)); }
  else
    echo "J3_G3_NOFILE $outnm" >> "$DONE"; violations=$((violations+1))
  fi
done; done

echo "PAIRED_REPEATS_DONE $(date) violations=$violations" >> "$DONE"
