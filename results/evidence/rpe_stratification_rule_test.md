# RPE 分层判据的跨序列检验（零 GPU，2026-08-25，exp46）

> **起因**：写 §5.6（适用域边界）时复核 `skeleton.md:176-193` 的分层判据 ——
> "mask-free RPE > **2.5** cm/frame 时 mask 从冗余变必需"。该阈值由 **pt1/pt2 两条序列**
> 内插得出，skeleton 自辩"不是拍脑袋，来自同类型序列的对照实验"。
> **但一个放在仅有两个定义点之间的阈值是拟合出来的，不是检验过的**：n=2 时
> (1.57, 2.89) 里任何值都同样分开它们。本文件把该规则放到**全部 18 序列**上检验。
>
> **判决：原 2.5 阈值证否（17 决定格中错 4 个）；但 mask-free RPE 本身分得开（17/17 无重叠），
> 正确区间是 (1.57, 1.72)、中点 ≈1.64 cm/frame。** 复现：`scripts/test_rpe_stratification_rule.py`
> ⇒ `results/evidence/rpe_stratification_rule_test.json`。

## 0. 口径（先写死，再看数）

| 项 | 定义 |
|---|---|
| 被检验的规则 | mask-free RPE > 2.5 ⇒ mask **必需**；≤ 2.5 ⇒ mask **冗余** |
| 必要性读数 | `N = ATE(mask-free) / ATE(combined)` |
| 判 necessary | `N ≥ 1.5`（关掉 mask 至少贵 1.5×） |
| 判 redundant | `N ≤ 1.2` |
| 判 ambiguous | `1.2 < N < 1.5` ⇒ **排除、不硬塞到某一侧** |
| provenance | seed 发现与逐格 ATE 一律调用主表脚本自身的 `discover()` / `read_ate()`，RPE 用同一"逐 run CSV 优先"顺序 ⇒ 与主表的 latest-run 规则不可能分叉 |

## 1. 全 18 序列结果

| 序列 | mask-free RPE | mask-free ATE | combined ATE | N | 原规则预测 | 实测 | 判 |
|---|---:|---:|---:|---:|---|---|---|
| f1_desk | 0.847 | 1.49 | 1.39 | 1.07 | redundant | redundant | AGREE |
| f2_xyz | 0.222 | 1.91 | 1.93 | 0.99 | redundant | redundant | AGREE |
| f3_office | 0.456 | 1.59 | 1.55 | 1.02 | redundant | redundant | AGREE |
| f2_person | 0.498 | 6.79 | 7.34 | 0.92 | redundant | redundant | AGREE |
| f3_st_hf | 1.041 | 35.59 | 29.43 | 1.21 | redundant | *ambiguous* | 排除 |
| f3_st_rpy | 1.465 | 2.63 | 2.58 | 1.02 | redundant | redundant | AGREE |
| f3_st_xyz | 0.910 | 2.66 | 4.69 | 0.57 | redundant | redundant | AGREE |
| **f3_wk_hf** | **2.327** | 17.33 | 3.29 | **5.27** | redundant | **necessary** | ❌ **DISAGREE** |
| **f3_wk_rpy** | **2.264** | 14.61 | 4.29 | **3.41** | redundant | **necessary** | ❌ **DISAGREE** |
| **f3_wk_xyz** | **1.717** | 26.84 | 3.06 | **8.76** | redundant | **necessary** | ❌ **DISAGREE** |
| **balloon** | **2.028** | 12.11 | 3.06 | **3.96** | redundant | **necessary** | ❌ **DISAGREE** |
| balloon2 | 2.730 | 10.14 | 5.27 | 1.92 | necessary | necessary | AGREE |
| crowd | 2.643 | 34.89 | 2.29 | 15.24 | necessary | necessary | AGREE |
| crowd2 | 2.980 | 45.89 | 2.19 | 20.95 | necessary | necessary | AGREE |
| mv_no_box | 1.210 | 3.10 | 2.65 | 1.17 | redundant | redundant | AGREE |
| mv_no_box2 | 1.521 | 5.62 | 5.14 | 1.09 | redundant | redundant | AGREE |
| pt1 | 2.894 | 32.41 | 11.89 | 2.73 | necessary | necessary | AGREE |
| pt2 | 1.572 | 9.30 | 10.45 | 0.89 | redundant | redundant | AGREE |

**原规则准确率 = 13/17 = 76%。**

## 2. 【判决 A】2.5 cm/frame 阈值证否

四条错判序列的 mask-free RPE 落在 **1.72–2.33**（阈值下方 ⇒ 预测"冗余"），
而 mask 在它们身上恰恰**必需且幅度巨大**：f3_wk_xyz **8.76×**、f3_wk_hf 5.27×、
balloon 3.96×、f3_wk_rpy 3.41×。

⇒ **2.5 是被 pt1/pt2 这一对"顶起来"的**：pt2 恰好 1.572、pt1 恰好 2.894，
内插值自然偏高，正好跨过了 1.7–2.4 这一整段"mask 必需但 RPE 不高"的区域。
**skeleton §3.1 的 2.5 与"分层阈值不是拍脑袋"这句自辩一并撤回。**

## 3. 【判决 B】但 mask-free RPE 确实分得开 —— 区间是 (1.57, 1.72)

| 组 | mask-free RPE 范围 | 成员 |
|---|---|---|
| mask **冗余** | **0.22 – 1.57** | f2_xyz · f3_office · f2_person · f1_desk · f3_st_xyz · mv_no_box · f3_st_rpy · mv_no_box2 · pt2 |
| mask **必需** | **1.72 – 2.98** | f3_wk_xyz · balloon · f3_wk_rpy · f3_wk_hf · crowd · balloon2 · pt1 · crowd2 |

**两组不重叠**（max(冗余) 1.572 < min(必需) 1.717）⇒ **17/17 决定格可被单一阈值完全分开**，
区间 (1.57, 1.72)、中点 **≈1.64 cm/frame**。

被排除的那一格**不是靠排除才成立的**：f3_st_hf 的 N=1.21 紧贴 redundant 界，
按其 RPE 1.041 预测 redundant ⇒ **若计入也是 AGREE**（18/18）。排除只让规则更保守。

### 3.1 这个分离不是"ATE 差就 RPE 差"的同义反复

关键反例：**f3_st_hf 与 crowd 的 mask-free ATE 几乎相同（35.59 vs 34.89），
但 N 差 12.6×（1.21 vs 15.24）** —— 而 mask-free **RPE 把它们分开了**（1.041 vs 2.643）。
即：逐帧漂移量能区分"mask 会不会帮上忙"，而全轨迹 ATE 不能。
这与 exp37 的 `ENDPOINT-DECOUPLED`（逐帧幅度与全轨迹质量是两个终点）方向一致。

## 4. 自限（每条都必须随结论同写）

1. **阈值是拟合的，不是验证过的**：区间读自定义它的同一批 18 序列，**无 held-out**。
   17 点上的完全分离比 2 点强得多，但仍是**描述性**结论。要当判据必须**先预注册再上新序列**。
2. **它是事后诊断，不是先验 selector**：算 mask-free RPE 需要**先跑 mask-free 臂**。
   因此不能写成"我们能事先判断该不该开 mask"。
   （但它满足 roadmap 对 future-work selector 的硬要求 —— **来自 mask-free 可观测量**，
   不像已被证否的"序列级语义占比"那样需要跑语义检测器。）
3. **N 的两侧都带噪**：逐格 3 seed，`mv_no_box`/`mv_no_box2` 等序列的 vanilla 高方差不影响本表
   （N 只比我方两臂、不经 vanilla 分母），但 `f3_st_hf` combined 自身 sd=8.00 ⇒ 其 N 本就不稳，
   这也是它落进 ambiguous 带的原因。
4. **未测**：1.64 这个中点对**新序列**的预测力；也未测 RPE 之外的 mask-free 可观测量
   （flow 分离比、geometry 残差）是否分得更开或更稳。
5. 本文件**不新增 run**，只重读已落盘的 18 序列 × 2 臂 × 3 seed 的 ATE/RPE。

## 5. 写作后果

| # | 位置 | 动作 |
|---|---|---|
| A | `skeleton.md:176-193` | 2.5 阈值 + "不是拍脑袋"自辩就地标注撤回，指向本文件 |
| B | §5.6 / §6 Limitations | 边界改写为 **(1.57, 1.72) 无重叠分离、17/17**，并同写"拟合非验证 + 事后诊断非先验" |
| C | future work | 从"selector 必须来自 mask-free 可观测量（尚无候选）"升级为"**已测得一个候选**（mask-free RPE，17/17 分离），下一步 = 预注册 + 新序列检验" |
| D | 禁词表 | 新增 ❌ "RPE > 2.5 cm/frame 时 mask 变必需"；❌ 把 1.64 写成"验证过的阈值"或"selector" |
