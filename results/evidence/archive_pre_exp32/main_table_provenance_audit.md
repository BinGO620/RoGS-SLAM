# 主表 provenance 审计：一个格的 ATE 与渲染来自**不同的 run**（已修）+ 同 seed 非确定性证据

> 2026-08-15（exp22）。发现路径：为补"效率自比表"聚合 `efficiency_raw.csv` 时，
> 同一格（f3_wk_rpy / mask-free）算出 18.70±2.36，与主表的 17.75±0.72 对不上，遂逐 run 追。

## 1. 缺陷

`scripts/build_18seq_main_table.py::read_ate` 读的是 run 的**汇总** CSV
`<RUNROOT>/tables/tracking_raw.csv` 并对**其中所有行取平均**。该汇总文件是**追加式**的：
同一个 seed 目录如果跑过两次，就会有两行。而同一函数上方的渲染列只取**最新**那个时间戳。

⇒ 一旦某 seed 跑过两次，**该格的 ATE 是两次运行的平均，渲染却只来自其中一次**——
两半来自不同的 run。

## 2. 影响面（已全量扫描）

258 个 run 的汇总 CSV 中**只有 1 个**含多行：

| run | 完成次数 | 两次 ATE | 轨迹完整度 |
|---|---|---|---|
| `P6/P6-18SEQ/f3_wk_rpy_maskoff_seed0` | 2（2026-08-10 13:07:36 / 16:01:50） | **15.72 / 21.42 cm** | 两次都是 **873/873 帧**（均完整，无残次） |

对主表的影响 = **1 格**：`f3_wk_rpy` × `Ours-mask-free`。
- 旧值 **17.75±0.72**（seed0 被记为两次的均值 18.57，再与 seed1 17.21 / seed2 17.46 取 3-seed）；
- 修复后 **18.70±2.36**（seed0 取与渲染同源的最新那次 21.42）。
- 其余 71 格不受影响（每格恰好一个已完成 run）。

## 3. 修复

1. `read_ate` 改为**只读该时间戳自己的 run**：优先时间戳目录内的 `tracking_raw.csv`，
   否则回退到汇总里 `run_id` 等于该时间戳的那一行。**永不再对汇总取平均**。
2. 新增护栏 `DUPLICATE_RUNS`：任何 seed 目录出现一个以上已完成 run，一律写进表尾
   "运行 provenance"段并标注取哪一次。**这类事再也不能静默通过。**
3. 无重复时表尾输出 `✅ 每个 (序列, 臂, seed) 恰好一个已完成 run，ATE 与渲染同源`。

## 4. 附带的实质发现（比缺陷本身更重要）：**同 seed 的运行间非确定性**

同配置、同 seed、同硬件、两次都跑满 873/873 帧，ATE **15.72 vs 21.42 cm（1.36×）**。

- 这**不是** seed 方差，是**运行间非确定性**。机制：MonoGS 前端/后端异步多进程，
  每帧实际做多少次 mapping 迭代取决于 wall-clock 调度，因此同 seed 不是逐位可复现的。
- **后果（必须写进 limitation）**：我们报告的 ±sd 是**跨 seed** 的离散度，
  **系统性低估**总的运行间离散度；在困难动态序列上尤其如此。
- **写作口径**：凡引用困难序列（walking / crowd / pt1 / balloon）的均值，必须同时给出离散度；
  不得把 ±0.7 这类小 sd 读作"该方法在该序列上稳定"。
- 这条同时**加强**了我们已有的做法（P7/WP-A/WP-B 全部 3-seed、逐 seed 同号才判决），
  也解释了为什么"单 seed screening"在本项目屡次翻车。

## 5. 复核方式

```bash
# 重复 run 扫描（任何时候可重跑）
python3 - <<'EOF'
import csv, glob
for p in glob.glob("results/runs/**/tables/tracking_raw.csv", recursive=True):
    rows = list(csv.DictReader(open(p)))
    if len(rows) > 1:
        print(len(rows), p, [r["ate_rmse_cm"] for r in rows])
EOF
```

## 6. 教训

主表数字对不上时，**先怀疑 provenance，不要先怀疑聚合口径**。这次是"两个指标读了不同的 run"，
而不是 mean/median 之类的口径差异——后者查半天也查不出来。护栏（表尾自动列重复 run）
比再审一次更可靠。
