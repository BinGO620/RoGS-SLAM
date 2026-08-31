# exp44 预注册 —— Replica 锚点（补竞品都报、我们从未跑过的 benchmark）

> **commit 于第一个 run 出数之前。** 参照数字取自 MonoGS 原论文（arXiv 2312.06741v2）
> Table 2 / Table 7，**在我们自己的数出来之前抄录**。

## 0. 为什么跑

Replica 是 3DGS SLAM 的标准 benchmark，竞品（MonoGS/SplaTAM/Point-SLAM/RGD/WildGS…）
论文里全都报，而我们 18 序列主表里**一行都没有**。

**但必须先说清一件在派发前查出来的事实**：我们的竞品重跑集
（`resources/02-baselines/baselines_result/*/tracking_raw.csv`，12 个方法）
**Replica 覆盖 = 0**，全部是 TUM(30) + BONN(24)。
⇒ 主表现有的分量来自"同环境同口径重跑"，**Replica 这张表不可能有那个分量**，
只能跟 published 数字比。这是一个**更弱的比较标准**，跑之前就要写明，事后不得含糊。

## 1. Phase 0 的问题（不是"我们好不好"）

既然唯一可比的是 published 数字，第一个必须回答的是**可比性本身**：

> **我们的环境 + 我们这个 fork，能不能复现 published MonoGS 的 Replica RGB-D 数字？**

能 → 与 published 比较被许可，值得铺全矩阵；
不能 → 铺 48 run 出来跟谁都不可比，**不铺**。

## 2. 参照（跑前抄录，不得事后挑）

MonoGS arXiv 2312.06741v2 **Table 2**（Replica RGB-D，ATE RMSE cm）：

| 实现 | r0 | r1 | r2 | **o0** | o1 | o2 | o3 | o4 | Avg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ours（multi-process） | 0.44 | 0.32 | 0.31 | **0.44** | 0.52 | 0.23 | 0.17 | 2.25 | 0.58 |
| Ours (sp)（single-process） | 0.33 | 0.22 | 0.29 | **0.36** | 0.19 | 0.25 | 0.12 | 0.81 | 0.32 |

我们跑的 config = `configs/rgbd/replica/office0.yaml`（**非** `_sp` 变体）
⇒ **对口参照 = 0.44 cm**（同族 sp = 0.36 cm 作为该实现自身的浮动参考）。

渲染（Table 7/15，Replica RGB-D 全场景均值）：**PSNR ≈ 37.5 dB / SSIM ≈ 0.96 / LPIPS ≈ 0.07**
（per-scene office0 未在本次抄录范围内 ⇒ 渲染只作**量级**判读，不作逐场景判据）。

## 3. Phase 0 判据（2 run 之前写死）

臂 A = vanilla（`office0.yaml` 原样，我们的机制全部 default-off，已用 `load_config` 核过：
`SemanticMask.enabled=False`、`RobustTracking.enabled=False`、`ReliabilitySignal/DynamicKeyframe` 缺省）。
**必须 `--eval` 不能 `--fast`**（`slam.py:695-702`：`--fast` 会把 `eval_rendering` 置 False，
refinement 整段跳过 ⇒ 拿不到渲染数，这是 P5-VANILLA 踩过的坑）。

| A 臂 office0 ATE | 判读 |
|---|---|
| ≤ 1.0 cm | **ANCHOR-PASS**：环境可复现 published 量级 ⇒ 与 published 比较被许可 |
| 1.0 – 2.0 cm | **MARGINAL**：可比性存疑，须先查 fork 差异，不铺矩阵 |
| > 2.0 cm | **ANCHOR-FAIL**：不可比 ⇒ **Replica 线就地停**，不铺矩阵 |

带宽理由（非事后拟合）：published 自身两个实现在 o0 上就差 0.36 vs 0.44（±18%），
且 Replica 绝对值是亚厘米量级，任何微小差异都会放大成大比值 ⇒ 用绝对带宽而非比值。

## 4. 若 ANCHOR-PASS，Phase 1（不在本轮承诺）

臂 B = combined 主配置（mask-ON + prune）。**已知前置缺口**：
- Replica **没有 `flow_raft`**，而 `ReliabilitySignal` 有硬门（`reliability_signal.py:711-725`，
  空 flow 索引即抛异常，exp24 之后加的）⇒ 必须先为 Replica 建 flow；
- `scripts/build_flow_raft.py` 走 `load_tum_associations()`，**Replica 目录结构不兼容**
  （无 `associations.txt`，是 `results/frame%06d.jpg` + `depth%06d.png`）⇒ 需写适配器。
- ⇒ **锚点未过之前不建这个适配器**（不为可能用不上的臂先修基础设施）。

## 5. 预先声明的风险（第三种结局，exp39 教训：别只注册两个分支）

Replica **全静态**，而我们自己的 FULLKERN 数据记录过**"动态 4/4 改善、静态 6/6 变差"**
（exp25，`03-results.md`）。⇒ 臂 B 有**相当概率输给 vanilla**。
若如此，这张表**削弱而非加强**论文。届时的处置**跑前就定**：
如实进 limitation（"我们的内核以静态场景的轻微退化换动态场景的 4–14×"），
**不得**因为难看就不报、也不得只报 vanilla 那一行冒充我们的结果。

## 6. 成本与自限

- Phase 0 = **1 run**（office0 × seed0 × vanilla，3090 单卡）。2000 帧 + refinement。
- 单 seed = screening，只判可比性，**不判方法效果**。
- Replica 8 场景 × 3 seed × 2 臂 = 48 run 是**上限估计**，本轮不承诺。
- 本轮不撤回任何既有判决。

---

## 7. 首轮 OOM 事故与修复（2026-08-23 夜，2 run 全崩，无判读价值）

**事故**：`office0` OOM @ frame 782、`room0` OOM @ frame 676，两卡各被自己的进程占满 23.5 GB。
两个 run 均无输出，**不进任何判读**。

**根因（两条，都是配置层，非代码）**：

| # | 根因 | 证据 | 修法 |
|---|---|---|---|
| 1 | `configs/rgbd/replica/base_config.yaml` 的 `use_gui: True`（upstream MonoGS 默认；**我们的 `tum/base_config.yaml` 是 False**） | 日志 `FEngine (64 bits) created`；OOM 消息里 GUI 进程独占 **3.08 GiB** | 新 run 配置置 `Results.use_gui: False`（新 run 的 `FEngine` 行数 = 0，已验证） |
| 2 | 多进程模式前端/后端**各持一份**高斯模型 + 关键帧副本 | OOM 消息三进程 `20.05 GiB + 3.08 GiB + 254 MiB` | 改用仓库既有的 `*_sp.yaml`（与多进程版**仅差** `single_thread: true`） |

**为什么我们以前没撞到**：Replica 是本项目**从未跑过**的数据集，
而 TUM/Bonn 的 base_config 早就是 `use_gui: False` ⇒ 这个 upstream 默认从来没进过我们的视野。
（同一轮还发现 `datasets/replica/` 的软链**从来没建过**，见 CLAUDE.md 的「按源建链」一节。）

**修复后实测显存曲线**（`exp44_vanilla_office0.yaml`，单进程 + GUI 关，3090）：

| 帧 | 显存 |
|---:|---:|
| 108 | 2840 MiB |
| 223 | 3195 MiB |

⇒ 增长 **3.1 MiB/帧**，外推 2000 帧 ≈ **8.7 GB**，含末段余量 12–16 GB / 24 GB ⇒ **可跑**。
（此前口头外推的"50 GB"是从**坏配置**推的，作废。）

**参照行随之切换（预注册 §2 已同时抄录两行，非事后挑数）**：
配置从多进程改为 `_sp` ⇒ 对口参照从 Table 2 的 `Ours` 行（o0 0.44 / r0 0.44）
切到 **`Ours (sp)` 行（o0 0.36 / r0 0.33）**。§3 的判据带宽（≤1.0 PASS / >2.0 FAIL）不变。

**可复用教训**：换一个从未跑过的数据集时，**base_config 的 upstream 默认值必须逐项与本项目
已用数据集对表**（`use_gui` 这类不影响正确性、只影响资源的字段最容易漏），
且第一批应先跑 `--max-frames` 的显存探针，而不是直接发全长。
