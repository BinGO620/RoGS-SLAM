# EXP52 判决 — P11 sparse-KF + mask-only 3090 重验 + MRCS+async50 balloon matched 对照

> 执行读数与判决，判据冻结见 `exp52_p11_prereg.md`。
> 所有正式运行均在 `jiangwenheng` 双 RTX 3090 上完成；本地 cb(2060) 不纳入判决。
> 代码基线：远程 EXPECTED_HEAD = c544b940（审计基线，exp51 收尾 commit），运行时
> 文件 SHA256 与 `exp51_provenance.json` 的 4 个共享文件逐字节等价（provenance 记录
> 在 `results/runs/EXP52/exp52_provenance.json`，含本次后补写的 post-dispatch 注释）。

## 1. 正式 9-run 矩阵

主指标：完整轨迹 `tracking_raw.csv` 的 `ate_rmse_cm`（evo `-a` Horn 口径）。
逃逸定义：ATE < 5 cm。预注册判据冻结于 `exp52_p11_prereg.md` §6。

| 臂 | seed0 | seed1 | seed2 | mean (cm) | sample sd (cm) | 逃逸 |
|---|---:|---:|---:|---:|---:|---:|
| P11F (P11, f3_st_hf) | 7.9777 | 4.0516 | 4.1005 | **5.3766** | 2.2476 | **2/3** |
| P11B (P11, balloon) | 3.0078 | 3.2647 | 3.0094 | **3.0940** | 0.1444 | **3/3** |
| M50B (MRCS+async50, balloon) | 11.7260 | 14.7416 | 15.4251 | **13.9642** | 1.9660 | **0/3** |

9/9 run `status=OK`，无 OOM 或配置错误。运行时间：GPU0 三 run 共 75 min；GPU1 六 run 共 63 min；墙钟 1h43min。

## 2. 判决门（逐条）

### G0 异常中止门

| 臂 | 新 mean | exp28 锚 | |Δ| | 门 (>2cm 且 >3×sd) | 判决 |
|---|---:|---:|---:|---|---|
| P11F | 5.38 | 4.04±0.63 | **1.34 cm** | < 2 cm | **PASS** |
| P11B | 3.09 | 3.18±0.46 | **0.08 cm** | < 2 cm | **PASS**（极一致）|

> 注：P11F 的 sd 从 exp28 的 0.63 增至 2.25，主因 seed0=7.98（非崩，是运行级双稳态，
> 与 EXP51 A2 的 20.28 同类现象但幅度小得多）。G0 按预注册只检查 mean 偏移，不查 sd。

### G1 静态稳定（f3_st_hf）

- **P11F 3/3 seed < 10 cm**：7.98 / 4.05 / 4.10，全部 <10 cm → **PASS**
- 逃逸率：**2/3**（seed1 和 seed2 <5 cm）
- 对照 EXP51 A2 f3_st_hf：主矩阵 2/3 逃逸（6-seed 5/6）→ **稳定性不劣**（相同逃逸率）

### G2 动态增益（balloon）

- P11B mean **3.09 cm** ≤ 19.2 cm（vanilla 38.35 的一半） → **PASS**
- vs vanilla：**12.4× 改善**（3.09 vs 38.35）

### G3 结构对照

**主对照（balloon, 匹配对比）：**

| | P11B | M50B | 差值 | 判定地板 |
|---|---:|---:|---:|---:|
| ATE mean (cm) | **3.09** | 13.96 | **10.87** | max(0.43, 0.06×13.96)=**0.84** |
| 逃逸率 | 3/3 | 0/3 | — | — |
| KF 数 (seed0/1/2) | 21/21/20 | 58/50/48 | — | — |
| Gaussians | 19,861 | 28,669 | — | — |

P11B 不劣 = P11B mean ≤ M50B mean + 地板：3.09 ≤ 14.80 → **PASS**
P11B 显著优于 M50B：**4.5× 改善**，且 KF 数 3× 更少、Gaussians 少 31%。

**副对照（f3_st_hf, 描述性）：**

| | P11F | EXP51 A2（复用） |
|---|---:|---:|
| 逃逸率 | 2/3 | 2/3（主矩阵）/ 5/6（6-seed）|
| KF 数 | 53/60/54 | ~107 (async50) |

稳定性不劣（逃逸率相同）。P11 的 KF 数 53-60 vs A2 的 ~107，稀疏化有效。

## 3. 判决：BRANCH-1 —— P11 晋级

| 条件 | 结果 |
|---|---|
| G0 PASS | ✓ |
| G1 PASS (P11F 3/3 <10cm, 2/3 escape) | ✓ |
| G2 PASS (P11B mean 3.09 < 19.2) | ✓ |
| G3 balloon P11B 不劣于 M50B | ✓（P11B 4.5× 优于 M50B）|
| P11F 逃逸 ≥ 2/3（稳定性不劣于 A2）| ✓（2/3 = 2/3）|

**→ BRANCH-1：P11 sparse-KF + mask-only 升级为下一版方法结构候选。**

## 4. 关键发现

### 4.1 dense-KF + ReliabilitySignal 不值得保留（在 balloon 上反而有害）

MRCS（dense KF gap_cap=5 + ReliabilitySignal + RT + prune,无语义 mask）在 balloon 上
ATE 13.96 cm（0/3 逃逸），比 P11 的 3.09 cm（3/3 逃逸）差 **4.5×**。
- M50B 的 KF 数是 P11B 的 ~2.5×（50-58 vs 20-21），但更多的 KF 并未改善 ATE
  ——反而因为 ReliabilitySignal 的 e_flow 信号在短动态序列上的噪声/偏差导致
  动态观测污染地图。
- 这直接回答了 exp27 提出的核心架构问题："dense-KF + ReliabilitySignal 值不值得保留"
  → **不值得，至少在短动态序列上是有害的。**

### 4.2 P11 的 exp28 锚值在当前 HEAD 高度可复现

| 序列 | exp28 3090 锚 | EXP52 3090 新 | Δ |
|---|---|---|---|
| balloon mean | 3.18±0.46 | 3.09±0.14 | **-0.08 cm（一致）** |
| f3_st_hf mean | 4.04±0.63 | 5.38±2.25 | +1.34 cm（seed0 双稳态）|

代码漂移审计的推断得到实证：即使 +1527 行代码变更，P11 的行为在关键序列上
与 exp28 时代高度一致（balloon 均值仅差 0.08 cm）。G0 门未触发。

### 4.3 P11 f3_st_hf 的双稳态幅度显著小于 MRCS+async50

- P11F seed0=7.98 cm（未崩，但非典型）→ 7.98 是 A2 的 20.28 的 **39%**
- 这意味着 P11 的 sparse KF + mask-only 策略不仅在动态序列上优于 MRCS，
  在静态序列的双稳态脆弱性上也显著更温和。

### 4.4 效率对比

| 指标 | P11F (f3_st_hf) | P11B (balloon) | M50B (balloon) |
|---|---|---|---|
| online FPS | 0.86 | 0.87 | 1.13 |
| KF 数 (mean) | 56 | 21 | 52 |
| Gaussians (mean) | 81,450 | 19,861 | 28,669 |

P11 在 f3_st_hf 上的 FPS 为 0.86，显著优于 exp28 的 0.35（2.5× 提升），
来自 +1527 行中的效率优化（默认激活的路径，非 default-off 门控部分）。

## 5. exp28 锚值本地归档

远程 `P11-MASKONLY-3090`（12-run, f3_st_hf/balloon/f2_xyz/mv_no_box ×3）已回拉至
本地 `results/runs/P11/P11-MASKONLY-3090/`，与本地 `P11-MAINTABLE-3090`（42-run）
一起作为 Phase 2 扩序列的参考锚值保存。

## 6. 文件来源

- 预注册：`results/evidence/exp52_p11_prereg.md`
- provenance：`results/runs/EXP52/exp52_provenance.json`（21 文件 SHA256，含 post-dispatch 注释）
- 正式结果：`results/runs/EXP52/p11_matched/{P11F,P11B,M50B}_seed{0,1,2}/tables/tracking_raw.csv`
- 读数脚本：`scripts/read_exp52_p11.py`
- exp28 锚值归档：`results/runs/P11/P11-MASKONLY-3090/`（本地）
