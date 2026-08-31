#!/bin/bash
# exp41 FULL-RANGE TRACKING MASK —— Phase 0（2 run，balloon seed0 × {control, treatment}）
#
# 预注册：results/evidence/exp41_fulltrack_prereg.md（发批前已 commit）
# 判据：Phase 0 只看机制诊断（D-1 有效像素差 / D-2 单变量 / D-3 护栏），不看 ATE。
#
# 用法（jiangwenheng 上）：
#   nohup bash scripts/run_exp41_fulltrack.sh > results/runs/EXP41_fulltrack/launcher.log 2>&1 &
set -u
REPO=${REPO:-/home/jiangwenheng/cron/monogs-ours}; cd "$REPO"
PY=${PY:-/home/jiangwenheng/anaconda3/envs/monogs-ours-3090/bin/python}
OUT=${OUT:-results/runs/EXP41_fulltrack}; mkdir -p "$OUT"
DONE="$OUT/done.flag"; : > "$DONE"
STAGGER=${STAGGER:-30}

CFG_CTRL="configs/rgbd/experiments/exp41_fulltrack/exp41_control_balloon.yaml"
CFG_TRT="configs/rgbd/experiments/exp41_fulltrack/exp41_fulltrack_balloon.yaml"
SEED=0

# ---- 门 B-0：无残留 slam 进程 ----
n_slam=$(pgrep -fc 'slam[.]py --config' 2>/dev/null || true)
[ -n "$n_slam" ] || n_slam=0
if [ "$n_slam" -gt 0 ]; then
  echo "ABORT: B-0 残留 slam 进程 ${n_slam} 个，先 kill 再发" >> "$DONE"; exit 1
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

# ---- 门 G-1：单变量（control vs treatment 只差 hard_tracking_mask + method） ----
diff_keys=$(PYTHONPATH=$PWD $PY -c "
from utils.config_utils import load_config
a = load_config('$CFG_CTRL'); b = load_config('$CFG_TRT')
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
  OK) echo "GATE G-1 PASS: 单变量 hard_tracking_mask" >> "$DONE" ;;
  *) echo "ABORT: G-1 差异超集 ($diff_keys)" >> "$DONE"; exit 1 ;;
esac
echo "" >> "$DONE"

# ---- run：两臂并行（每卡一个），30s 错开 ----
echo "=== $(date +%H:%M:%S) START control (GPU 0) ===" >> "$DONE"
CUDA_VISIBLE_DEVICES=0 $PY slam.py --config "$CFG_CTRL" --fast --seed "$SEED" \
  --results-root "$OUT" --experiment-name "EXP41-control" \
  > "$OUT/control.consolelog" 2>&1 &
p1=$!
sleep "$STAGGER"
echo "=== $(date +%H:%M:%S) START fulltrack (GPU 1) ===" >> "$DONE"
CUDA_VISIBLE_DEVICES=1 $PY slam.py --config "$CFG_TRT" --fast --seed "$SEED" \
  --results-root "$OUT" --experiment-name "EXP41-fulltrack" \
  > "$OUT/fulltrack.consolelog" 2>&1 &
p2=$!

wait $p1; rc1=$?
echo "=== $(date +%H:%M:%S) EXIT control rc=$rc1 ===" >> "$DONE"
wait $p2; rc2=$?
echo "=== $(date +%H:%M:%S) EXIT fulltrack rc=$rc2 ===" >> "$DONE"

# ---- D-2/D-3 读数（跑完自动收） ----
$PY - <<'PYEOF' >> "$DONE" 2>&1
import csv
from pathlib import Path

out = Path("results/runs/EXP41_fulltrack")
# MonoGS 输出结构: $OUT/EXP41-<tag>/.../tables/tracking_raw.csv
for tag in ("control", "fulltrack"):
    csvs = sorted(out.rglob(f"EXP41-{tag}/**/tracking_raw.csv"))
    if csvs:
        with open(csvs[0]) as f:
            for row in csv.DictReader(f):
                if row.get("ate_rmse_cm"):
                    v = float(row["ate_rmse_cm"])
                    verdict = "OK" if v < 100 else "GUARD-FAIL"
                    print(f"D3 {tag} ATE={v:.4f} ({verdict}, 护栏<100)")
                    break
    else:
        print(f"D3 {tag} tracking_raw.csv NOT FOUND")

# D-1: reliable-tracking 诊断（有效像素）。reliable tracking 的统计在
# viewpoint._reliable_tracking_stats，落盘位置待查；先从 console 抓行数证据。
import re
for tag in ("control", "fulltrack"):
    log = out / f"{tag}.consolelog"
    if not log.exists():
        print(f"D1 {tag} consolelog NOT FOUND"); continue
    txt = log.read_text(errors="ignore")
    m = re.findall(r"rgb_support_ratio[=:\s]+([\d.]+)", txt)
    if m:
        vals = [float(x) for x in m]
        vals_sorted = sorted(vals)
        print(f"D1 {tag} rgb_support_ratio n={len(vals)} median={vals_sorted[len(vals)//2]:.4f}")
    else:
        print(f"D1 {tag} support_ratio pattern NOT FOUND (改由 PLY/表格判读)")
PYEOF

echo "" >> "$DONE"
echo "=== EXP41 Phase0 DONE $(date +%H:%M:%S) ===" >> "$DONE"
