#!/bin/bash
# exp39 Step C 剂量扫描 —— admission 份额 1% / 5%
#
# 预注册：results/evidence/exp39c_dose_scan_prereg.md（发批前已 commit）
#
# 问题：已测 31.8% 有害、0% 无害。存不存在足够小的份额使 admission 无害？
# 地板沿用上一批实测的 0.43 cm，基准 = zeromask 3.27。
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_exp39c_dose_scan.sh > results/runs/EXP39c_dose/launcher.log 2>&1 &
set -u
REPO=${REPO:-/home/jiangwenheng/cron/monogs-ours}; cd "$REPO"
PY=${PY:-/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python}
OUT=${OUT:-results/runs/EXP39c_dose}; mkdir -p "$OUT"
DONE="$OUT/done.flag"; : > "$DONE"
STAGGER=${STAGGER:-30}

CFG_05="configs/rgbd/experiments/exp39_mapping_soft/exp39c_cap05_balloon.yaml"
CFG_01="configs/rgbd/experiments/exp39_mapping_soft/exp39c_cap01_balloon.yaml"
CFG_BASE="configs/rgbd/experiments/exp39_mapping_soft/exp39c_sm_balloon.yaml"
SEED=0

for cfg in "$CFG_05" "$CFG_01" "$CFG_BASE"; do
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
done

# 门 G-1：相对 E-sm 基线只允许差 mapping_ema_dynamic_cap 一键
for pair in "cap05:$CFG_05" "cap01:$CFG_01"; do
  name=${pair%%:*}; cfg=${pair#*:}
  r=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
a, b = load_config('$cfg'), load_config('$CFG_BASE')
d = []
def walk(x, y, p=''):
    for k in sorted(set(x) | set(y)):
        u, v = x.get(k), y.get(k)
        if isinstance(u, dict) and isinstance(v, dict): walk(u, v, p + k + '.')
        elif u != v: d.append(p + k)
walk(a, b)
allowed = {'method', 'inherit_from', 'Results.save_dir',
           'SemanticMask.mapping_ema_dynamic_cap'}
extra = [k for k in d if k not in allowed]
print('OK' if not extra else 'BAD:' + ','.join(extra))" 2>/dev/null)
  case "$r" in
    OK) ;;
    *) echo "ABORT: $name 臂差异超出允许键集 ($r)" >> "$DONE"; exit 1 ;;
  esac
done
echo "GATE G-1 PASS: 两臂相对 E-sm 只差 mapping_ema_dynamic_cap" >> "$DONE"

# 门 B-0/B-1：发批前清场
n_slam=$(pgrep -fc 'slam[.]py --config' 2>/dev/null || true)
[ -n "$n_slam" ] || n_slam=0
if [ "$n_slam" -gt 0 ] 2>/dev/null; then
  echo "ABORT: 还有 $n_slam 个 slam.py 在跑，先清场" >> "$DONE"; exit 1
fi
while read -r idx used; do
  used=${used%% *}
  if [ "$used" -gt 1024 ] 2>/dev/null; then
    echo "ABORT: GPU $idx 残留 ${used} MiB > 1024" >> "$DONE"; exit 1
  fi
done < <(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | tr ',' ' ')
echo "GATE B-0/B-1 PASS: 0 slam procs, 两卡显存均 < 1 GB" >> "$DONE"

echo "=== $(date +%H:%M:%S) START cap05 (GPU 0) ===" >> "$DONE"
CUDA_VISIBLE_DEVICES=0 $PY slam.py --config "$CFG_05" --fast --seed "$SEED" \
  --results-root "$OUT" --experiment-name "EXP39C-cap05" \
  > "$OUT/cap05_balloon_seed0.consolelog" 2>&1 &
PID_05=$!

sleep "$STAGGER"

echo "=== $(date +%H:%M:%S) START cap01 (GPU 1) ===" >> "$DONE"
CUDA_VISIBLE_DEVICES=1 $PY slam.py --config "$CFG_01" --fast --seed "$SEED" \
  --results-root "$OUT" --experiment-name "EXP39C-cap01" \
  > "$OUT/cap01_balloon_seed0.consolelog" 2>&1 &
PID_01=$!

wait $PID_05; RC_05=$?
echo "=== $(date +%H:%M:%S) EXIT cap05 rc=$RC_05 ===" >> "$DONE"
wait $PID_01; RC_01=$?
echo "=== $(date +%H:%M:%S) EXIT cap01 rc=$RC_01 ===" >> "$DONE"
echo "=== ALL DONE (cap05=$RC_05 cap01=$RC_01) ===" >> "$DONE"
