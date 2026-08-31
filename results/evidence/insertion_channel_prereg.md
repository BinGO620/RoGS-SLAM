# 预注册 —— mask 增益的第二条通道：insertion 侧（exp35, 2026-08-21）

> **发批前注册。** 本文件在第一个 run 之前 commit，此后不改（判据①：零假设与阈值一起、
> 提前注册）。PBA 那轮把分支标签写反了一次，本文件 §4 先把标签映射写死再谈读数。

## 1. 为什么值得 GPU

exp34 的 PBA 判决把 4–14× 增益的 **44–80%** 定位到 BA 观测聚合（`mask_mapping`）。
诚实边界第 1 条自己写下了缺口：**剩下 20–56% 在 `mask_insertion`（挡动态高斯插入）和
tracking 侧，两者的相对贡献未单独分离**。

`mask_insertion` 在代码里是**单一布尔**（`utils/slam_frontend.py:488-525`
`apply_semantic_insertion_gate`），把关键帧深度图上的 person 像素置零，动态高斯因此
根本不进地图（`create_pcd_from_image_and_depth` 的 `project_valid_depth_only=True` 丢掉）。
翻这一个开关 = 干净的单变量干预，与 PBA 翻 `mask_mapping` 完全对偶。

**这一轮补的是 2×2 因子设计的第四格**，前三格 exp34 已有：

| | `mask_insertion=T` | `mask_insertion=F` |
|---|---|---|
| **`mask_mapping=T`** | `eboth`（对照）✅ 已测 | **`tracking-only` ← 本轮** |
| **`mask_mapping=F`** | `PBA` ✅ 已测 | `maskfree` ✅ 已测 |

拿到第四格才能算**主效应 + 交互项**，而不只是两个各自的 share。

## 2. 装置门（写在主判据之前，且必须真的执行 —— 判据⑨）

**发批前已验**（零 GPU）：

- 三个 config 解析后 `mask_mapping=True, mask_insertion=False`，与对应 `pba_eboth_*`
  的唯一差异就是 `mask_insertion`（`tests/test_pba_ba_coupling.py` 钉住）。

**收批后必须逐 run 验，任一不过 ⇒ 该 run 作废，不进判决**（正负两个方向都验，
沿用 R2-P04 的 G5：只验一边会把静默退化读成 null-vs-null）：

- **G1（门必须不响）**：`tracking-only` 臂 console **不得**出现
  `Semantic insertion gate frame ... person px zeroed`。出现 = 开关没生效。
- **G2（门必须响）**：同批 `eboth` 臂 console **必须**出现该行、且 zeroed 像素 > 0。
  不出现 = 对照臂自己就退化了，问题变成 null-vs-null。
- **G3（机制方向）**：`n_gaussians`（`posthoc_fullframe` 或 PLY）在 `tracking-only`
  **应高于**同序列 `eboth` —— 动态高斯确实进了地图。方向反 = 机制不是我们以为的那个，
  先解释再读 ATE。

## 3. 可分解性门（判据⑧，由 exp34 继承，不重新拟合）

`总效应 = |ATE_maskfree − ATE_eboth|` 必须 ≥ 3× 臂内 seed 极差，否则该序列
**分解不出任何东西**，读处理臂之前就排除。exp34 已算过，本轮**照抄不重算**：

| 序列 | 总效应 | 臂内极差 | 比值 | 可分解 | **本轮 share 的可读地板 = 1/比值** |
|---|---:|---:|---:|:-:|---:|
| balloon | 8.30 | 1.52 | 5.46 | ✅ | **0.183** |
| f3_wk_xyz | 24.01 | 0.39 | 61.6 | ✅ | **0.016** |
| pt1 | 23.59 | 6.47 | 3.65 | ✅ | **0.274** |
| mv_no_box | 0.81 | 1.50 | 0.54 | ❌ | 不跑 |

**可读地板是逐序列的，不是一个全局阈值** —— pt1 的 seed 噪声吃掉总效应的 27%，
所以 pt1 上 share < 0.274 本来就读不出来；f3_wk_xyz 上 0.016 以上就能读。
把它写成单一阈值会在 pt1 上过度解读、在 f3_wk_xyz 上浪费分辨率。

## 4. 判据与分支标签（**先把标签写对，再看数**）

```
share_insertion = (ATE_trackingonly − ATE_eboth) / (ATE_maskfree − ATE_eboth)
```

**标签映射（消融的常规逻辑，PBA 那轮写反过一次）**：
**拆掉某个部件后 ATE 涨上去（变差），才说明那个部件在承载效应。**
- `share_insertion → 1`：拆掉 insertion 就丢掉全部增益 ⇒ insertion 承载增益。
- `share_insertion → 0`：拆掉 insertion 后 ATE 仍贴着 eboth ⇒ 增益**不走** insertion。

**判决（≥2/3 可分解序列同向才算成立）**：

- **INSERTION-CHANNEL-MATERIAL**：share_insertion > 逐序列可读地板。
  ⇒ insertion 是第二条真实通道，2×2 主效应两项都非零。
- **INSERTION-CHANNEL-NEGLIGIBLE**：share_insertion ≤ 逐序列可读地板。
  ⇒ 20–56% 的缺口**不在** insertion，只能在 tracking 侧（`mask_mapping` 也喂 tracking
  的光度残差）⇒ 下一轮靶子改为 tracking-侧隔离。
- **INDETERMINATE**：序列间不同向，或落在地板上下各半 ⇒ 报出来，不外推。

**可达域自检（判据⑧/exp33）**：`share_insertion` 没有守卫把它钉死在任何值上 ——
`ATE_trackingonly` 物理上可以落在 eboth 之下（share<0，拆掉反而更好）、
之间（0<share<1）、或 maskfree 之上（share>1，两条通道互相干扰）。
三段都可达 ⇒ 判据不是空的。

## 5. 2×2 分解（拿到第四格才能算，本轮的真正产出）

```
insertion 主效应  = ½[(trackingonly − eboth) + (maskfree − PBA)]
mapping   主效应  = ½[(PBA − eboth) + (maskfree − trackingonly)]
交互项            = (maskfree − PBA) − (trackingonly − eboth)
```

**交互项的读法（同样先注册）**：
- ≈ 0（|交互| < 臂内极差）⇒ **可加**：两条通道独立，share_BA + share_insertion ≈ 1。
- \> 0 ⇒ **超加性**：两个 mask 一起用比各自之和更值 ⇒ 必须两条都有。
- < 0 ⇒ **冗余**：任一条单独就能拿走大部分增益。

已知一半：balloon 的 `maskfree − PBA = 11.36 − 8.64 = 2.72`；本轮测 `trackingonly − eboth`
就能直接读出交互项。

## 6. 规模（分阶预算硬纪律）

- **Phase 0（1 run，机制自检，不看 ATE）**：balloon seed0 `tracking-only`。
  只看 G1/G2/G3。**门不过 ⇒ 停，不进 Phase 1。**
- **Phase 1/2（8 run）**：balloon seed1/2 + f3_wk_xyz ×3 + pt1 ×3。
  三序列 × 3 seed = 9 run 补齐第四格；对照臂三格 exp34 已有，**不重跑**。
- mv_no_box **不跑**（§3 可分解性门已排除）。

## 7. 本轮不结算什么

- **不测渲染**（PSNR/LPIPS）—— 同批 PLY 会留着，渲染是独立一轮。
- **不碰主表**（mask-free 列的崩溃率重述是另一件事，与本轮无耦合）。
- **不分离 tracking 侧**。若判 NEGLIGIBLE，tracking-侧隔离是下一轮的靶子，
  本轮不预支那个结论。
