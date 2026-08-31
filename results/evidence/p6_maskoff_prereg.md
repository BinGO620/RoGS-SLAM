# P6 MASK-OFF 消融 — combined backbone 4-14× ATE 的方法内核生死判（预注册）

> 2026-08-09 exp-v3-10 收口。方法期重开后的第一条预注册。
> 用户最高准则：方法贡献必须是"我们自己的"+ 对动态 3DGS SLAM 有用，否则不写稿、继续实验。
> 这条消融回答的是头条能不能立起来的**生死判**（dead-list 上具体没测过的机制差异）。
> **单 seed screening（9 run）先跑，判决路径 3 seed（27 run）。**

## 0. 背景与目的

combined backbone（mask-both + RobustTracking + DynamicKeyframe + ReliabilitySignal，prune lifecycle）
在动态序列上对 vanilla MonoGS 有 **4-14× ATE**（balloon 43.94→3.06 / mv_no_box 13.60→2.66 /
pt2 44.06→10.44；P5 实测 vanilla 单 seed，combined 为 3090 P2-T 3-seed）。

**待判定**：这 4-14× 的增益，方法内核在不在"借来的标准组件"（Mask R-CNN 语义 mask + 密集关键帧）
之外？也就是说，我们有没有"我们自己的"方法贡献？

- 若 **mask-off（combined 减 mask）在 balloon 仍 ~3cm** ⇒ 增益主因不在 mask 上
  ⇒ bundle 里有我们自己的方法内核 ⇒ **combined 4-14× 头条成立，可能含方法贡献**。
- 若 **mask-off 掉回 vanilla 量级（~43cm）** ⇒ bundle = mask + 借来组件打包
  ⇒ 无方法内核 ⇒ 头条只能定位"系统论文"（6GB dynamic 3DGS SLAM 系统贡献）或换方向。

## 1. 可证伪假设

**H-ABL（mask-off 消融）**：combined 减掉 SemanticMask（保留 dense-KF + RT + Reliability）后，
在动态序列上的 ATE 仍显著优于 vanilla（balloon 远低于 43cm，~10cm 以下量级）。
- 成立 ⇒ mask 不是增益唯一主因，有 mask 之外的方法内核路径（dense-KF / RT / Reliability / 组合交互）。
- 证伪（mask-off ≈ vanilla）⇒ bundle 的方法内核集中在借来的 mask，无可独立主张的贡献。

## 2. 判决装置

- **run 矩阵（screening）**：{balloon, mv_no_box, pt2} × seed 0 = **3 run**（~1h on 3090 双卡）。
- **run 矩阵（判决，3 seed）**：{balloon, mv_no_box, pt2} × seeds 0/1/2 = **9 run**（~4h）。
- 全 6 序列 × 3 seed = 18 run 在 P-A 成立、头条确认后再扩（判据先行，别一次跑满）。
- **锚**：
  - vanilla = `method_p5_vanilla_prune.yaml`（已跑 3 序列 seed0；缺 balloon2/mv_no_box2/pt1，继承已修）。
  - combined = `method_combined_maskboth_prune.yaml`（3090 P2-T 3-seed 已有）。
- **对照**：mask-off 需新建 `method_combined_maskoff_prune.yaml`。

## 3. 方法配置（mask-off）

```yaml
# method_combined_maskoff_prune.yaml — combined prune 减 SemanticMask
# 唯一差异：SemanticMask.enabled: true → false。其余逐字节同 method_combined_maskboth_prune.yaml。
inherit_from: "configs/rgbd/experiments/active/candidate/method_combined_maskboth_prune.yaml"
SemanticMask:
  enabled: false
```

合同测试：钉住 `method_combined_maskoff_prune` 与 `method_combined_maskboth_prune` 的解析差
**恰好只有** `SemanticMask.enabled`（类似 `tests/test_p2_combined_twin_configs.py` 的模式）。
注意 inherit_from 是 YAML 继承链——加个 wrapper 继承 combined prune 再关 mask 即可。

## 4. 判据（跑前固定，不事后改）

- **主判据**：mask-off 的 balloon ATE（`tracking_raw.csv ate_rmse_cm`，全轨迹）**显著低于 vanilla**。
  量化：[max(mask-off ATE), compared to 3.06（combined）到 43.94（vanilla）这个区间]。
  - mask-off 在 3.06~15cm（远低于 vanilla 43cm）⇒ 方法内核不在 mask；有可主张的贡献。
  - mask-off ≥ 43cm（≈ vanilla）⇒ bundle 增益全来自 mask ⇒ 无独立内核。
- **辅助**：mv_no_box / pt2 同读；RT-off / Reliability-off 已知 flat/未晋级（死清单），
  所以若 mask-off 仍优，增益最可能来自 dense-KF + 组合交互。
- **单 seed = screening**（硬纪律⑤），4 个主序列 3-seed 才判决。

## 5. 为什么这不是"复活死方法"

死清单上测过的是：
- RT-off（combined 减 RT）= flat +1.2%（在 mask 存在时被冗余吞掉）；
- Reliability-off = 未晋级（−2.9/−5.8% < 15%）；
- mask-vs-deferred（lifecycle 对照）= 不可分辨。

**从没测过**：combined 减 mask（在 dense-KF+RT+Reliability 存在时）。这是之前没测过的具体机制差异，
不复活任何已死格子——它是补一个"bundle 内部到底谁贡献"的缺口。

## 6. 下一步决策树

- P-A（mask-off）成立 + P-B（2×2 交互）有超加性 ⇒ 头条 = "6GB dynamic 3DGS SLAM with
  4-14× over vanilla + our metric"。这是有方法贡献的合法 CCF-C 系统论文头。
- P-A 证伪 ⇒ bundle = mask 打包，无内核。退：① system-paper 尺度重审；② 换基座（RGD-SLAM fork）
  再开方法线；③ （用户定）。

## 7. 用户授权

用户 2026-08-09 明确：3090 + 2060 能验证的都直接跑，不要问，GPU 放着也是放着，不怕浪费。
方向自主裁量权放开。本实验直接执行，不需要再问。
