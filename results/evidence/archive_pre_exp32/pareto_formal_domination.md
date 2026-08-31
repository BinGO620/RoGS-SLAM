# 结构化 Pareto 形式化分析（2026-08-06）

对 pareto_data.json 做正式三轴支配检查（N 越低越好，PSNR 越高越好，ATE 越低越好）。
方法必须同时有 N、PSNR、ATE 三轴（8/11 竞品满足）。

## 面板 1：每序列的前沿（Pareto frontier）

**balloon** — 前沿只有 RGD-SLAM
- RGD-SLAM: 9.6k / 25.14dB / 2.45cm
- **Ours base 被 RGD 完全支配，Ours deferred 被 RGD 完全支配**

**mv_no_box** — 前沿：DynaGSLAM · Ours deferred · RGD-SLAM · WildGS-SLAM
- Ours deferred: 35.1k / 24.48dB / 2.54cm — 唯一 Ours 在前沿的序列
- Ours base 被 RGD 完全支配，但 Ours deferred 在前沿不被任何方法支配

**pt1** — 前沿：DG-SLAM · RGD-SLAM · WildGS-SLAM
- **Ours base 被 RGD 完全支配，Ours deferred 被 RGD 完全支配**

**pt2** — 前沿：DG-SLAM · Ours base · Ours deferred · RGD-SLAM · WildGS-SLAM
- 前沿上所有方法互不支配

## 面板 2：跨序列支配计数

**Ours base 被 RGD-SLAM 在 3/4 序列完全支配（balloon, mv_no_box, pt1）**

**Ours deferred 被 RGD-SLAM 在 2/4 序列完全支配（balloon, pt1）**

**只有 pt2 上 Ours 两臂不被任何方法支配**（pt2 上 RGD ATE=20.10cm 太差，
Ours 以 N 更差但 ATE 更好换到了前沿位置）

## 面板 3：结论

1. **"Pareto 前沿" 只在 mv_no_box 上成立**（Ours deferred），且这 1/4 序列的
   前沿位置不足以支撑全局 claim。RGD 在 3/4 序列完全支配 Ours base，在 2/4
   支配 Ours deferred。

2. **"1/18 SplaTAM 的高斯数" 成立但战略上弱**：SplaTAM 在动态序列 ATE 37-133cm，
   基本是坏的——击败一个 ATE 上失败的对手不是竞争性证明。

3. **"RGD 在 N×PSNR×ATE 三轴压制我们"是事实**：balloon 上 RGD 是
   9.6k/25.1dB/2.45cm vs 我们 39.8k/22.0dB/2.87cm（三轴全输）；pt1 同样。

4. **建议**：放弃 Pareto 效率 claim，改为：
   "competitive full-frame PSNR at significantly lower Gaussian count than
   SplaTAM/DynaGSLAM, with ATE competitive with DG-SLAM and NGD-SLAM
   on dynamic sequences"——这是诚实的，不依赖"我们不被支配"这类脆弱断言。