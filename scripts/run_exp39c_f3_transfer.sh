#!/bin/bash
# exp39 Step C 跨序列验证 —— f3_wk_xyz 四臂 × 2 run
#
# 预注册：results/evidence/exp39c_f3_transfer_prereg.md（发批前已 commit）
#
# 问题：balloon 上的 admission 判决（31.8% 有害 7.6x 地板、安全份额 <=1%）能否迁移？
# 先验：exp38 已测到效应量随序列衰减（balloon 4.0x vs f3_wk_xyz <1x）
#       ⇒ 很可能读出"不迁移"，那是真结果（预注册分支 C 为它留位）。
#
# 每臂 2 run：f3 的 within-config 地板必须在本序列实测，不能 import balloon 的 0.43
# （项目铁律：run-to-run 非确定性逐臂逐序列，任一个都不可外推）。
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_exp39c_f3_transfer.sh > results/runs/EXP39c_f3/launcher.log 2>&1 &
set -u
REPO=${REPO:-/home/jiangwenheng/cron/monogs-ours}; cd "$REPO"
PY=${PY:-/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python}
OUT=${OUT:-results/runs/EXP39c_f3}; mkdir -p "$OUT"
DONE="$OUT/done.flag"; : > "$DONE"
STAGGER=${STAGGER:-30}
ROUNDS=${ROUNDS:-2}
D=configs/rgbd/experiments/exp39_mapping_soft
SEED=0
ARMS=${ARMS:-"hard zeromask sm cap05"}

cfg_for() {
  case "$1" in
    hard)     echo "$D/exp39c_hard_f3_wk_xyz.yaml" ;;
    zeromask) echo "$D/exp39c_sm_zeromask_f3_wk_xyz.yaml" ;;
    sm)       echo "$D/exp39c_sm_f3_wk_xyz.yaml" ;;
    cap05)    echo "$D/exp39c_cap05_f3_wk_xyz.yaml" ;;
  esac
}

# ---- 数据门：frozen flow 非空（CLAUDE.md rsync 软链纪律）----
FLOW=datasets/tum/rgbd_dataset_freiburg3_walking_xyz/flow_raft
n_flow=$(ls "$FLOW" 2>/dev/null | wc -l)
if [ "$n_flow" -lt 1 ] 2>/dev/null; then
  echo "ABORT: $FLOW 为空或断链（软链被 rsync 打断？见 CLAUDE.md）" >> "$DONE"; exit 1
fi
echo "GATE DATA PASS: frozen flow = $n_flow 帧" >> "$DONE"

# ---- 门 G-1：每臂 config 存在且剂量旋钮解析成预期值 ----
for arm in $ARMS; do
  cfg=$(cfg_for "$arm")
  [ -f "$cfg" ] || { echo "ABORT: config 缺 $cfg" >> "$DONE"; exit 1; }
  r=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
sm = load_config('$cfg')['SemanticMask']
exp = {'hard':(False,None,None,None),'zeromask':(True,True,True,None),
       'sm':(True,True,False,None),'cap05':(True,True,False,0.05)}['$arm']
got = (sm.get('mapping_ema'), sm.get('mapping_ema_mass_match'),
       sm.get('mapping_ema_zero_dynamic'), sm.get('mapping_ema_dynamic_cap'))
ok = got == exp and sm.get('enabled') and sm.get('mask_mapping')
print('OK' if ok else f'BAD got={got} exp={exp}')" 2>/dev/null)
  case "$r" in
    OK) ;;
    *) echo "ABORT: $arm 臂旋钮解析异常 ($r)" >> "$DONE"; exit 1 ;;
  esac
done
echo "GATE G-1 PASS: $ARMS 四臂旋钮解析正确" >> "$DONE"

# ---- 门 B-0/B-1：发批前清场 ----
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
echo "" >> "$DONE"

# ---- 运行：每轮两臂并行（每卡一个），共 ROUNDS 轮 ----
run_pair() {
  local a=$1 b=$2 rnd=$3
  local ca cb
  ca=$(cfg_for "$a"); cb=$(cfg_for "$b")
  echo "=== $(date +%H:%M:%S) R$rnd START $a (GPU 0) ===" >> "$DONE"
  CUDA_VISIBLE_DEVICES=0 $PY slam.py --config "$ca" --fast --seed "$SEED" \
    --results-root "$OUT/r$rnd" --experiment-name "EXP39C-f3-$a-r$rnd" \
    > "$OUT/${a}_r${rnd}.consolelog" 2>&1 &
  local p1=$!
  sleep "$STAGGER"
  echo "=== $(date +%H:%M:%S) R$rnd START $b (GPU 1) ===" >> "$DONE"
  CUDA_VISIBLE_DEVICES=1 $PY slam.py --config "$cb" --fast --seed "$SEED" \
    --results-root "$OUT/r$rnd" --experiment-name "EXP39C-f3-$b-r$rnd" \
    > "$OUT/${b}_r${rnd}.consolelog" 2>&1 &
  local p2=$!
  wait $p1; local rc1=$?
  echo "=== $(date +%H:%M:%S) R$rnd EXIT $a rc=$rc1 ===" >> "$DONE"
  wait $p2; local rc2=$?
  echo "=== $(date +%H:%M:%S) R$rnd EXIT $b rc=$rc2 ===" >> "$DONE"
}

set -- $ARMS
A1=$1; A2=$2; A3=$3; A4=$4
for rnd in $(seq 1 "$ROUNDS"); do
  run_pair "$A1" "$A2" "$rnd"
  run_pair "$A3" "$A4" "$rnd"
done

echo "" >> "$DONE"
echo "=== ALL DONE ($ROUNDS rounds x 4 arms) ===" >> "$DONE"
