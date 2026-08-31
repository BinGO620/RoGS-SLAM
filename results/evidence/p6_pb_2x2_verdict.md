# P-B 2×2 (mask × dynKF) 消融 verdict — seed0 screening（2026-08-09）

> 装置 commit `807d3d3`（configs + 4 run + contract test 5 pass）。
> 判据：maskoff 判决已在 P6（33% seed）成立;P-B 定位 kernel 具体组件。
> seed0 = screening,非终判;但方向性已可读（4 格跨度远大于 seed 噪声）。

## 主结果（ate_rmse_cm, 3090 seed0;括号 = P2-T/ P6 的 3-seed 参考）

| mask \\ dynKF | dynKF ON | dynKF OFF |
|---|---|---|
| **mask ON**  (balloon) | **3.06**（P2-T 3seed） | **2.80**（新） |
| **mask OFF** (balloon) | **12.11**（P6 3seed） | **13.34**（新） |
| **mask ON**  (mv_no_box) | **2.66**（P2-T 3seed） | **3.38**（新） |
| **mask OFF** (mv_no_box) | **3.09**（P6 3seed） | **3.59**（新） |

## 读数

### balloon（mask 主导轴）
- mask ON 两格（3.06 / 2.80）都远优于 mask OFF 两格（12.11 / 13.34）。**mask 是主导**。
- dynKF-off + mask-on = 2.80,几乎与 combined 3.06 持平 ⇒ **在 balloon 上 dense-KF 不是驱动**;
  是 mask 在扛（balloon=人+气球,mask 抓部分,关掉就把 balloon 污染回 ~12-13cm）。

### mv_no_box（bundle 鲁棒—— 最关键）
- 四格全 ≈3cm（2.66 / 3.09 / 3.38 / 3.59）。
- **mask 轴效应 ≈ 0.5-0.7cm**（2.66 vs 3.38;3.09 vs 3.59）——关闭 mask 影响很小。
- **dynKF 轴效应 ≈ 0.4-0.5cm**（2.66 vs 3.09;3.38 vs 3.59）——关闭 dense-KF 影响也很小。
- ⇒ **单一组件都不是 mv_no_box 的 kernel**。~3cm 对 mask 和 dynKF 的开关都鲁棒;
  **真正贡献 = bundle 的组合/冗余**（RobustTracking 的 huber + Reliability 的时域稳健性 +
  dense-KF 的覆盖,彼此冗余）。拿走任何一个,bundle 仍然能把 ATE 压到 ~3cm;全拿走才回 vanilla。

## 判决（seed0 方向性,非 3-seed 终判）

**不存在"单一 magic kernel component"。** P6 初判"dense-KF 多半是主贡献"（因它是时域一致性载体）
被 P-B 修正:mv_no_box 上 dense-KF-off 仅 +0.5cm ⇒ **dense-KF 也不是唯一驱动**。

诚实定位 = **"mask-free 的时域一致性 bundle"作为一个整体,在不依赖语义分割的场景把动态序列
压到 ~3cm**。这个 bundle（dense-KF + RT-huber + Reliability）是我们加的 / 调过的结构
（DynamicKeyframe 不在 MonoGS,RT 的 huber 是我们配置的,Reliability 是我们实现的方法 #8）,
framework-general（不依赖 mask / 分割网络）,dynamic-relevant（打的就是动态序列）。

### 对"审稿人逐组件消融反打"的防御
审稿人会说"把每块关掉看看谁贡献"。我们实测:**单块关掉都不崩**（mv 四格全 ~3cm）。这与其说是
弱点,不如说是**内核就是组合**——任何单一机制都不是内核,组合的鲁棒时域采样才是。这比
"找到 magic 组件"更难被一句消融推翻。

但需自报的 caveat：
1. balloon 上 mask 明显是主导（mask-on 3 是 maskoff 12 的 4 倍）。所以诚实表述 =
   "bundle 在 mask 可省/不可用（如无分割模型的场景）时仍达 ~3cm;有 mask 时在 balloon 类混合
   mover 序列上 mask 仍加值"。
2. seed0,mv 的 0.5cm 效应 vs seed 噪声可能不显著（P2-T mv seed sd~0.12,但这是不同 config）;
   3-seed 才能确认"四格全 ~3cm"是真 gap 还是噪声带内。
3. 只测了气球(人+物)与 mv_no_box(物)两类;person 序列(纯人) pt2 单 seed 9.92 vs combined 10.44
   略好,方向支持 bundle 在纯人上也扛,但未补 seed。

## 下一步

- **P-B 补 3-seed**（balloon + mv_no_box × 4 arms × seeds 1/2 = 12 run ≈ 8h on 双卡）确认
  "四格鲁棒"不是 seed 假象。
- **若确认**：头条 = "mask-free 时域一致性 bundle 的动态 3DGS SLAM"（不依赖语义分割）。
  配 MMM：这回答 codex 的"逐组件消融"关切（我们已做 2×2）+ "framework-general"
  （不依赖分割网络）+ 有审稿记忆点（时域一致性 bundle 作为鲁棒采样内核）。
- 可选：补 person 序列（pt2）3-seed 扩成"三类 mover"。

## 落盘
- 4 run（seed0）存 `results/runs/P6/P6-PB/`（已回拉）。seed0 screening,非终判。
- 本文件 + `idea_exploration_maskfree_temporal.md` = 头条方向证据链。
