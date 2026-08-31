# exp41 FULL-RANGE TRACKING MASK — Phase 1（4 run，balloon+mv_no_box × seed0）
#
# 预注册：results/evidence/exp41_fulltrack_prereg.md §4
# Phase 1 目标：看 ATE 量级 vs 6% 噪声地板。效应 <6% → 停。效应 >2× 地板 → Phase 2。
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_exp41_phase1.sh > results/runs/EXP41_fulltrack/launcher_phase1.log 2>&1 &
set -u
REPO=${REPO:-/home/jiangwenheng/cron/monogs-ours}; cd "$REPO"
PY=${PY:-/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python}
OUT=${OUT:-results/runs/EXP41_fulltrack}; mkdir -p "$OUT"
DONE="$OUT/done_phase1.flag"; : > "$DONE"
STAGGER=${STAGGER:-30}

CFG_CTRL_BALLOON="configs/rgbd/experiments/exp41_fulltrack/exp41_control_balloon.yaml"
CFG_TRT_BALLOON="configs/rgbd/experiments/exp41_fulltrack/exp41_fulltrack_balloon.yaml"

# mv_no_box configs：继承主配置，改数据集
# 先生成 mv_no_box 的 control/treatment config（用 inherit_from）
cat > configs/rgbd/experiments/exp41_fulltrack/exp41_control_mv_no_box.yaml << 'YAML'
# exp41 FULL-RANGE TRACKING MASK — control arm for mv_no_box (= P2-T mv_no_box prune)
inherit_from: "configs/rgbd/bonn/moving_nonobstructing_box.yaml"
method_from: "configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml"
method: "Exp41-control-mv_no_box"
YAML

cat > configs/rgbd/experiments/exp41_fulltrack/exp41_fulltrack_mv_no_box.yaml << 'YAML'
# exp41 FULL-RANGE TRACKING MASK — treatment arm for mv_no_box
# 唯一差异：hard_tracking_mask: true
inherit_from: "configs/rgbd/bonn/moving_nonobstructing_box.yaml"
method_from: "configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml"
method: "Exp41-fulltrack-mv_no_box"

SemanticMask:
  hard_tracking_mask: true
YAML

CFG_CTRL_MV="configs/rgbd/experiments/exp41_fulltrack/exp41_control_mv_no_box.yaml"
CFG_TRT_MV="configs/rgbd/experiments/exp41_fulltrack/exp41_fulltrack_mv_no_box.yaml"
SEED=0

# ---- 门 B-0：无残留 slam 进程 ----
n_slam=$(pgrep -fc 'slam[.]py --config' 2>/dev/null || true)
[ -n "$n_slam" ] || n_slam=0
if [ "$n_slam" -gt 0 ]; then
  echo "ABORT: B-0 残留 slam 进程 ${n_slam} 个" >> "$DONE"; exit 1
fi
echo "GATE B-0 PASS: 0 残留进程" >> "$DONE"

# ---- 门 B-1：两卡显存 < 1 GB ----
for gi in 0 1; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "$gi" | tr -d ' ')
  if [ "$used" -gt 1000 ]; then
    echo "ABORT: B-1 GPU${gi} 显存 ${used}MB > 1000MB" >> "$DONE"; exit 1
  fi
done
echo "GATE B-1 PASS: 两卡空闲" >> "$DONE"

# ---- 门 G-1：每对 config 单变量 ----
for pair in "balloon:$CFG_CTRL_BALLOON:$CFG_TRT_BALLOON" "mv:$CFG_CTRL_MV:$CFG_TRT_MV"; do
  seq=$(echo $pair | cut -d: -f1); cfg_c=$(echo $pair | cut -d: -f2); cfg_t=$(echo $pair | cut -d: -f3)
  diff_keys=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
a, b = load_config('$cfg_c'), load_config('$cfg_t')
d = []
def walk(x, y, p=''):
    for k in sorted(set(x) | set(y)):
        u, v = x.get(k), y.get(k)
        if isinstance(u, dict) and isinstance(v, dict): walk(u, v, p + k + '.')
        elif u != v: d.append(p + k)
walk(a, b)
allowed = {'method', 'SemanticMask.hard_tracking_mask'}
extra = [k for k in d if k not in allowed]
print('OK' if not extra else 'BAD:' + ','.join(extra))" 2>/dev/null)
  case "$diff_keys" in
    OK) echo "GATE G-1 PASS: $seq 单变量" >> "$DONE" ;;
    *) echo "ABORT: G-1 $seq 差异超集 ($diff_keys)" >> "$DONE"; exit 1 ;;
  esac
done
echo "" >> "$DONE"

# ---- run：Round 1 (balloon) + Round 2 (mv_no_box)，每轮两卡并行 ----
run_pair() {
  local seq=$1 cfg_c=$2 cfg_t=$3 rnd=$4
  echo "=== $(date +%H:%M:%S) R$rnd START $seq control (GPU 0) ===" >> "$DONE"
  CUDA_VISIBLE_DEVICES=0 $PY slam.py --config "$cfg_c" --fast --seed "$SEED" \
    --results-root "$OUT/r$rnd" --experiment-name "EXP41-$seq-control" \
    > "$OUT/${seq}_control_r${rnd}.consolelog" 2>&1 &
  local p1=$!
  sleep "$STAGGER"
  echo "=== $(date +%H:%M:%S) R$rnd START $seq fulltrack (GPU 1) ===" >> "$DONE"
  CUDA_VISIBLE_DEVICES=1 $PY slam.py --config "$cfg_t" --fast --seed "$SEED" \
    --results-root "$OUT/r$rnd" --experiment-name "EXP41-$seq-fulltrack" \
    > "$OUT/${seq}_fulltrack_r${rnd}.consolelog" 2>&1 &
  local p2=$!
  wait $p1; local rc1=$?
  echo "=== $(date +%H:%M:%S) R$rnd EXIT $seq control rc=$rc1 ===" >> "$DONE"
  wait $p2; local rc2=$?
  echo "=== $(date +%H:%M:%S) R$rnd EXIT $seq fulltrack rc=$rc2 ===" >> "$DONE"
}

run_pair "balloon" "$CFG_CTRL_BALLOON" "$CFG_TRT_BALLOON" 1
sleep 5
run_pair "mv_no_box" "$CFG_CTRL_MV" "$CFG_TRT_MV" 2

echo "" >> "$DONE"

# ---- Phase 1 读数 ----
$PY - <<'PYEOF' >> "$DONE" 2>&1
import csv
from pathlib import Path

out = Path("results/runs/EXP41_fulltrack")
print("=" * 60)
print("EXP41 Phase 1 结果")
print("=" * 60)
for seq in ["balloon", "mv_no_box"]:
    print(f"\n--- {seq} ---")
    for rnd, tag in [(1, "balloon"), (2, "mv_no_box")]:
        for arm in ("control", "fulltrack"):
            pattern = f"r{rnd}/EXP41-{seq}-{arm}/tables/tracking_raw.csv"
            csvs = list(out.glob(pattern))
            if not csvs:
                # fallback: search recursively
                csvs = list(out.glob(f"r{rnd}/**/{seq}*/tracking_raw.csv"))
            if csvs:
                with open(csvs[0]) as f:
                    for r in csv.DictReader(f):
                        if r.get("ate_rmse_cm"):
                            v = float(r["ate_rmse_cm"])
                            print(f"  {arm}: {v:.4f} cm")
                            break
            else:
                print(f"  {arm}: NOT FOUND")
PYEOF

echo "" >> "$DONE"
echo "=== EXP41 Phase1 DONE $(date +%H:%M:%S) ===" >> "$DONE"
