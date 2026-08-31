# ⚠ ReliabilitySignal 静默空转事故（exp23, 2026-08-16）

> **✅ 2026-08-17（exp24）已完成修复闭环** —— 详见文末「§7 修复记录」。
> 摘要：运行时硬闸已加（`7b89ff81`）+ 11 条缺失 flow 已补建 + combined 臂 33 run 已重跑核验通过
> + mask-free 臂 33 run 重跑中。审计结论：**论文的证据支柱（WP-A/WP-B/P7）全部干净，
> 受损的只有 18 序列主表两个臂在 11 条缺 flow 序列上的格**。

> **由用户发现**（"crowd/crowd2 的 combined 臂其实没用到 reliability"）。逐条核实后确认存在，
> 且**范围远大于 crowd/crowd2**：18 序列主表里 **10 条从未跑过 ReliabilitySignal**，
> 第 11 条只覆盖 14.7% 的帧。**combined 与 mask-free 两个臂同时受影响。**

## 1. 机制（三步静默失效，无任何告警）

1. `utils/flow_raft.py:105-106` —— `frozen_flow_index()` 在目录缺失时**静默返回 `{}`**：
   ```python
   if not flow_dir or not os.path.isdir(flow_dir):
       return out          # {}，不抛异常、不告警
   ```
2. `utils/slam_frontend.py:909-910` —— 查不到该帧的 flow 就直接关掉该模块：
   ```python
   rel_flow_path = self._reliability_flow_index.get(stem)
   reliability_active = rel_flow_path is not None
   ```
   ⇒ **不是"退化成 geometry-only"，是整个 ReliabilitySignal 被跳过**。
3. 配置里 `ReliabilitySignal.enabled: true` 照写不误，日志无异常，run 正常收敛出 ATE。

## 2. 决定性判据

`utils/slam_frontend.py:1573 _flush_reliability_signal()` 只在
`self.reliability_signal_rows` 非空时才写 `<run>/reliability_signal/frames.csv`
⇒ **该文件存在 ⟺ ReliabilitySignal 真的跑过**。

> 注意几个**看起来相关但其实无关**的信号（排查时先被它们误导过）：
> `efficiency_raw.csv` 的 `reliability_calls` / `tracking_raw.csv` 的
> `method_raw_mean_reliability` 全 18 序列都是 0 / N/A —— 它们属于 `utils/reliability.py`
> 读的**遗留 `Reliability` 配置块**，与 `ReliabilitySignal` 无关，不能用来判断。
> run 目录里的 `reliability/` 子目录同理（每个 run 都有，不区分）。

## 3. 逐序列实测（combined 臂 3 seed；mask-free 臂抽查同结论）

| 序列 | `flow_raft/*.npy` | 数据集帧数 | `reliability_signal/frames.csv` (seed0/1/2) | ReliabilitySignal |
|---|---:|---:|---|:-:|
| f1_desk | 0 | 592 | —, —, — | ❌ 从未跑 |
| **f2_xyz** | 499 | 3397 | 499, 499, 499 | ⚠ **仅 14.7% 帧** |
| f3_office | 0 | 2515 | —, —, — | ❌ |
| f2_person | 0 | 3694 | —, —, — | ❌ |
| f3_st_hf | 0 | 1078 | —, —, — | ❌ |
| f3_st_rpy | 0 | 796 | —, —, — | ❌ |
| f3_st_xyz | 0 | 1215 | —, —, — | ❌ |
| **f3_wk_hf** | 0 | 1030 | —, —, — | ❌ |
| f3_wk_rpy | 0 | 873 | —, —, — | ❌ |
| f3_wk_xyz | 813 | 828 | 827, 827, 827 | ✅ |
| balloon | 438 | 439 | 438, 438, 438 | ✅ |
| balloon2 | 468 | 469 | 468, 468, 468 | ✅ |
| **crowd** | **0** | 928 | —, —, — | ❌ |
| **crowd2** | **0** | 895 | —, —, — | ❌ |
| mv_no_box | 777 | 778 | 776, 777, 777 | ✅ |
| mv_no_box2 | 930 | 937 | 936, 936, 936 | ✅ |
| pt1 | 579 | 580 | 579, 579, 579 | ✅ |
| pt2 | 566 | 567 | 566, 566, 566 | ✅ |

**7/18 完整、1/18 部分（f2_xyz 14.7%）、10/18 完全没跑。**
mask-free 臂抽查（P6-18SEQ seed0）：f1_desk/f3_office/f2_person/f3_st_hf/f3_wk_hf/f3_wk_rpy/
crowd/crowd2 全部无该文件，balloon(438)/pt1(579) 有 ⇒ **同一问题，两臂同病**。

## 4. 影响范围（哪些结论受损、哪些不受损）

### ✅ 不受影响（受控证据链是干净的）

| campaign | 序列 | flow 状态 |
|---|---|---|
| **WP-A 全因子 120-run** | balloon, mv_no_box, mv_no_box2, pt1, pt2 | **5/5 全有 flow** ✅ |
| **WP-B flowmask 36-run** | pt1, pt2, mv_no_box2, balloon2 | **4/4 全有 flow** ✅ |

⇒ 「逐组件必要性」与「同信息量朴素对照」这两条**论文真正的贡献支柱不受影响**。

### ❌ 受影响

1. **18 序列主表**：10 条序列的 `Ours-combined` 与 `Ours-mask-free` 行，**实际配置不含
   ReliabilitySignal**（等价于 K1R1**L0**+mask / K1R1L0）。当前表里的臂名是错的。
2. **两个 headline 竞争力数字都在受影响序列上**：
   - `crowd 2.33` vs RGD 2.61 —— crowd **flow=0**
   - `f3_wk_hf 3.03` vs RGD 3.25 —— f3_wk_hf **flow=0**
   ⇒ 这两个数是 **mask + RobustTracking + DynamicKeyframe** 拿到的，与 ReliabilitySignal 无关。
3. **WP-M 判决（本次 54/54 刚出的 M4）**：分母 18 条里混了两种对照 ——
   有 flow 的 8 条是 `(mask+K+R+L) vs (mask only)`，无 flow 的 10 条是 `(mask+K+R) vs (mask only)`。
   **该判决在修复前不得写进论文。**
   附带一条值得注意：WP-M 唯一判为 `combined-better` 的序列是 **f3_wk_hf，而它 flow=0** ——
   即那处优势也来自 K+R，不来自完整内核。

## 5. 根因与为什么没被拦住

仓库里**本来就有**完整性检查 `scripts/check_flow_complete.py`
（判据：`n_flow >= n_rgb-1` 且 `manifest == n_rgb`），并由 `scripts/main_table_3090.sh:31`
在跑主表前调用。**但这 10 条序列的 run 没有走这个入口**（或该检查被绕过）。
⇒ 缺的是**运行时硬闸**：`ReliabilitySignal.enabled=true` 但 flow 索引为空时，
必须**报错退出或至少在 tracking_raw 里标脏**，而不是静默把模块关掉。

## 6. 待定（呈用户拍板，未擅自执行）

- **A. 补 flow 重跑**：为 10（+f2_xyz）条序列建 flow_raft，重跑 combined + mask-free
  ≈ 11 序列 × 3 seed × 2 臂 = 66 run（WP-M mask-only 臂 K0R0L0 不用 flow，**54 run 无需重跑**）。
- **B. 收窄主表**：只在 flow 完整的 7-8 条序列上主张完整内核，其余明确标注为
  「K+R 配置」——诚实但主表变小，且两个 headline 数字要改口径。
- **C. 先补硬闸**：无论选 A 还是 B，`ReliabilitySignal.enabled` 与空 flow 索引并存时必须硬失败。

---

**记录时间：2026-08-16（exp23）。发现者：用户。核实方式：flow 文件计数 + 代码路径 +
`reliability_signal/frames.csv` 产物存在性三重交叉。**

---

## §7 修复记录（exp24, 2026-08-17）

### 7.1 运行时硬闸（commit `7b89ff81`）

**关键设计**：闸放在 `tracking()` **入口**，判定只用 `enabled && !monocular && depth_paths`，
**不依赖 `gaussians`/迭代状态**。

> 为什么不能放在原来的 `reliability_active` 分支里：那个变量本身含 `self.gaussians is not None`，
> 而空转发生时它本就是 False，闸放进去永远是**死代码**。这是第一版实现踩过的坑。

- `utils/reliability_signal.py::assert_reliability_flow_available(config, dataset_path)` — 独立可测函数，
  flow 索引为空时 `RuntimeError` 并指明该建 flow 或关 `enabled`
- `tests/test_reliability_flow_gate.py` — 6 条规则（空目录/缺 subdir/正常/自定义 subdir/空 .npy/disabled 边界）

### 7.2 补建 11 条缺失 flow

`scripts/build_flow_raft_11seq.sh`（jiangwenheng 2×3090 并行，17,455 帧对，RAFT small peak 0.35GB）。
cb 与 jiangwenheng **manifest sha256 抽查 6 条完全一致**，两机 18 条 flow 现已全齐。

踩坑：`CUDA_VISIBLE_DEVICES=$gpu` 屏蔽后脚本内部必须用 `cuda:0`（用 `cuda:$gpu` 会 invalid device ordinal）。

### 7.3 全量审计（判据 = `frames.csv` 存在性）

| campaign | frames.csv | 判决 |
|---|---|---|
| WP-A 全因子 120run | 61（= 恰好所有 L1 组合） | ✅ 干净 |
| P2-T_3090 36run / P7-CUESPLIT 36run | 满 | ✅ 干净 |
| P6-EFACT / DBA-ORACLE / MASKOFF(-3SEED) / MASON-grad / pt1* / PB | 满 | ✅ 干净 |
| WPM-MASKONLY 54run | 0 | ✅ 预期（mask-only 不用 reliability） |
| P6-MASON (crowd/crowd2/f3_wk_rpy) | 0 | ❌ 污染 9run |
| P6-MASON-8SEQ (7条 + f2_xyz部分) | 3/24 | ❌ 污染 21run |
| P6-18SEQ mask-free (10条) | 6/36 | ❌ 污染 30run |

⇒ **论文真正的证据支柱（逐组件必要性 WP-A、同信息量朴素对照 WP-B、cue-split P7）全部不受影响**。

### 7.4 重跑

| 臂 | 目录 | 状态 |
|---|---|---|
| combined (mask-ON) | `results/runs/P6/P6-FULLKERN` | ✅ **33/33 `missing=0`**；逐 run 核验 tracking_raw + frames.csv 全有；frames.csv 行数吻合序列长度（crowd 927 / f2_person 3693 / f2_xyz 3395） |
| mask-free | `results/runs/P6/P6-FULLKERN-MASKFREE` | 🔄 33 run 跑中 |

新目录**不覆盖**旧 P6-MASON / P6-MASON-8SEQ / P6-18SEQ 的 L0 产物（保留历史对照）。

> ⚠ **下会话必做**：`scripts/build_18seq_main_table.py` 的 `roots` 仍指向旧目录，
> 需切到 P6-FULLKERN / P6-FULLKERN-MASKFREE 后重出主表，并更新两个 headline 数字的口径。

### 7.5 防复发机制

- **运行时硬闸**（本节 7.1）：flow 缺失时首帧 abort，不再静默降级
- **代码一致性校验** `scripts/check_code_sync.sh`：远程批量前必跑，校验
  「本地无未提交改动 + 本地 HEAD == origin + 远程 HEAD == origin」三项
  （用户明确要求：cb 是方法演化主阵地，远程跑的必须是同一份代码）
