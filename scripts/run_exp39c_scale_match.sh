#!/bin/bash
# exp39 Step C 尺度对齐三臂 —— 拆开 admission / 形状 / 尺度膨胀
#
# 预注册：results/evidence/exp39c_scale_match_prereg.md（发批前已 commit）
#
# 为什么这批存在：原 E 臂把 loss 乘以 mean(w)，光度项按 w_bar^2 缩放 ⇒ 相对硬臂
# 膨胀 5.7e4 倍，固定 isotropic 正则被事实上删除。原 ADMISSION-NOT-SHAPE 判决
# 因此撤回。本批把总权重质量锁定到硬臂的，使各臂只差一个变量。
#
# 装置：balloon × seed0 × {E-sm, E-sm-zeromask} = 2 run，两卡并行 + 30s 错开
#   H  -> E-sm-zeromask : 单变量 = static 内部权重形状
#   E-sm-zeromask -> E-sm : 单变量 = admission
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_exp39c_scale_match.sh > results/runs/EXP39c_sm/launcher.log 2>&1 &
set -u
REPO=${REPO:-/home/jiangwenheng/cron/monogs-ours}; cd "$REPO"
PY=${PY:-/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python}
OUT=${OUT:-results/runs/EXP39c_sm}; mkdir -p "$OUT"
DONE="$OUT/done.flag"; : > "$DONE"
STAGGER=${STAGGER:-30}

CFG_SM="configs/rgbd/experiments/exp39_mapping_soft/exp39c_sm_balloon.yaml"
CFG_ZM="configs/rgbd/experiments/exp39_mapping_soft/exp39c_sm_zeromask_balloon.yaml"
CFG_BASE="configs/rgbd/experiments/exp39_mapping_soft/exp39c_ema_balloon.yaml"
SEED=0

# ---- precheck ----
for cfg in "$CFG_SM" "$CFG_ZM" "$CFG_BASE"; do
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
done

# 门 G-1：两臂相对基线 EMA config 的差异只能是那两个键
for pair in "sm:$CFG_SM" "zeromask:$CFG_ZM"; do
  name=${pair%%:*}; cfg=${pair#*:}
  diff_keys=$(PYTHONPATH=$PWD $PY -c "
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
           'SemanticMask.mapping_ema_mass_match',
           'SemanticMask.mapping_ema_zero_dynamic'}
extra = [k for k in d if k not in allowed]
print('OK' if not extra else 'BAD:' + ','.join(extra))" 2>/dev/null)
  case "$diff_keys" in
    OK) ;;
    *) echo "ABORT: $name 臂差异超出允许键集 ($diff_keys)" >> "$DONE"; exit 1 ;;
  esac
done
echo "GATE G-1 PASS: 两臂相对基线只差 mass_match / zero_dynamic" >> "$DONE"

# 门 B-0/B-1：发批前清场（Step B 首发栽在这里）
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

# ---- 运行 ----
echo "=== $(date +%H:%M:%S) START E-sm (GPU 0) ===" >> "$DONE"
CUDA_VISIBLE_DEVICES=0 $PY slam.py --config "$CFG_SM" --fast --seed "$SEED" \
  --results-root "$OUT" --experiment-name "EXP39C-sm" \
  > "$OUT/sm_balloon_seed0.consolelog" 2>&1 &
PID_SM=$!

sleep "$STAGGER"

echo "=== $(date +%H:%M:%S) START E-sm-zeromask (GPU 1) ===" >> "$DONE"
CUDA_VISIBLE_DEVICES=1 $PY slam.py --config "$CFG_ZM" --fast --seed "$SEED" \
  --results-root "$OUT" --experiment-name "EXP39C-sm-zeromask" \
  > "$OUT/zeromask_balloon_seed0.consolelog" 2>&1 &
PID_ZM=$!

wait $PID_SM; RC_SM=$?
echo "=== $(date +%H:%M:%S) EXIT sm rc=$RC_SM ===" >> "$DONE"
wait $PID_ZM; RC_ZM=$?
echo "=== $(date +%H:%M:%S) EXIT zeromask rc=$RC_ZM ===" >> "$DONE"
echo "=== ALL DONE (sm=$RC_SM zeromask=$RC_ZM) ===" >> "$DONE"
