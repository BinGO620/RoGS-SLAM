# WP-B flow-mask —— pilot 阈值选择裁决（2026-08-15，exp19）

> **本文件记录 WP-B pilot 的重跑与阈值定案。** 前一版 pilot/E0（2026-08-14）因远程装置未同步
> 而全部作废（见 §0），本轮为在**正确 flow_threshold 装置**上的重发。判据取自
> `wpb_flowmask_prereg.md §六`（**冻结，未改**）。

## §0 前一轮作废（撤回声明）

2026-08-14 的 E0（balloon-p90 = 3.13）与 pilot（balloon-p80 2.99 / mv_no_box-p80 5.94 /
mv_no_box-p90 3.74）**全部作废，不得引用**。

**根因**：远程 3090 repo 的 HEAD 停在 `7a46595`，WP-B 装置 commits（`47dadf79`/`306e95e1`/
`0ec4e65b`）**从未经 git 同步到远程**，而是被手工拷成 untracked 覆盖态。远程
`utils/slam_frontend.py` **不含** `flow_threshold` 分支，因此 flowmask config 运行时
`semantic_mask_enabled()=true` 落入 `else → compute_semantic_dynamic_mask` = **Mask R-CNN
学习分割**，朴素 flow 阈值**从未执行**。

**证据链**（逐条可复核）：
1. 远程 `grep -c flow_threshold utils/slam_frontend.py` = 0；`_compute_flow_threshold_mask`
   / `resolve_flow_mask` import 均不存在。
2. 运行时 `config.yml` 落盘为 `{enabled:true, model:maskrcnn, source:flow_threshold,
   flow_quantile:0.8}` —— `source`/`flow_quantile` 是**无读取代码的死字段**。
3. `semantic_timing/summary.json` 的 `hard_calls` = 439/439（balloon）、778/778（mv_no_box），
   即 Mask R-CNN **逐帧**被调用。
4. `flow_mask_baseline.py` 的 `compute_flow_threshold_mask` 只能经
   `resolve_flow_mask() ← _compute_flow_threshold_mask()` 触达，而后者远程不存在。
5. p95 两 run 另因远程缺 `flowmask_p95.yaml` 直接 `FileNotFoundError` 静默 no-op。

**处置**：远程重建为**全新 clone**（旧库改名 `cron/monogs-ours-BROKEN` 保留取证），作废结果目录
已删除，撤回 commit `dd3433fc`。**铁律**：发批量前必须验证 `远程 HEAD == origin/ours-v3` 并
`git merge --ff-only`，**不得手工 scp/cp 装置文件**。

## §1 本轮 pilot（正确装置，6/6 完成）

- 网格：3 分位（p80/p90/p95）× 2 dev 序列（balloon, mv_no_box）× seed0 = **6 run**（screening）
- 装置：`configs/rgbd/experiments/wpb_flowmask/pilot_*.yaml`，HEAD `dd3433f`
- 完成率：**6/6 `OK`**，无任一序列 <95% 帧 ⇒ 无阈值被完成率闸淘汰

| 分位 | balloon (cm) | mv_no_box (cm) | **geomean** |
|---|---|---|---|
| p80 | 27.02 | 3.74 | **10.05** |
| **p90** | **10.57** | **4.91** | **7.21** ← 最低 |
| p95 | 30.12 | 4.10 | **11.11** |

**⇒ 阈值定案 = p90**（geomean 7.21，低于 p80 的 10.05 与 p95 的 11.11，差距远超并列线 ε=0.10；
且 p90 恰为 prereg 写死的并列回退值与 `flowmask_vanilla.yaml` 默认分位）。**阈值就此冻结**，
confirm 阶段不再调整（M1）。

## §2 G3 装置活性自证（本轮 PASS）

朴素 flow 阈值**确实执行**，两条独立证据：

1. **离线直接探针**（用 runner 自己那份 frozen flow，balloon）：
   coverage@frame0 = **0.248 (p80)** vs **0.077 (p95)**；frame26/49 同向（0.227/0.232 vs 0.066/0.072）。
2. **运行期插入门 px**（同一序列不同分位）：
   p80 `frame49: 81592 px` vs p95 `frame26: 9319 px`；p80 尾段稳定 68-76k、p95 稳定 20-28k。

**判读**：mask 随 `flow_quantile` 系统性变化 ⇒ **不可能是 Mask R-CNN**（学习分割不读该参数）。
对照前一轮作废数据的 `hard_calls=439/439`，本轮 `semantic_timing` 不再逐帧计数，与
"走 flow 分支、不走 `compute_semantic_dynamic_mask`" 一致。

## §3 与作废轮的读数差异（诚实记录）

同一格 balloon-p90：**作废轮 3.13（实为 Mask R-CNN）vs 本轮 10.57（真朴素 flow 阈值）**。
即真实的朴素 flow-mask **显著弱于**此前误记的读数。这一差异本身是 WP-B 的有效信息：
朴素阈值远不及学习分割，**但 dev 不进判决**，MRCS 对照留给 confirm 的 held-out 判定（B1-B4）。
⚠ 不得据 dev 提前宣布分支归属。

## §4 下一步（confirm，已起跑）

- 三臂 × held-out 4 序列 × 3 seed = **36 run**（`scripts/run_wpb_confirm_3090.sh`，HEAD `c1ad6f1`）
  1. `vanilla` = WP-A `K0R0L0`（本 campaign 自跑锚，不借 WP-A 行）
  2. `flow-mask` = vanilla + flow_threshold **p90**
  3. `MRCS` = WP-A `K1R1L1`
- held-out①（主判据）= `pt1`, `pt2`；held-out②（同族次级）= `mv_no_box2`, `balloon2`
- 判定见 prereg §七（δ=0.20，①2/2）。分母固定 4，全 3-seed。

> 起跑事故记录：confirm 首两次派发未起——`wait_slot` 用 `pgrep -fc 'slam.py --config'`，
> 该模式会匹配**任何字面包含该串的命令行**（含轮询用的 ssh 监控命令），造成幻影计数 ≥2、
> 两个 launcher 永久卡死且 done-file 为空。已改为锚定解释器路径 `^$PY slam\.py`（commit `c1ad6f1`）。
