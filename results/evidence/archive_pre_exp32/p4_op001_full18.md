# op<0.01 deletion — full 18-map coverage (codex R4 fix, R2-M2)

> 2026-08-09. codex Round4 (REVIEWER_MODEL gpt-5.6-sol) 判定 R2-M2 为 **Blocking Yes**:主 `op<0.01`
> 删除 + 重渲染只验证在 12 图(baloon,mv_no_box,pt1,pt2 × 3 seed),而 **18-map matched-rate 研究删除的
> 是最低 5%/10%(=不同算子)**,且被省略的两个序列(balloon2, mv_no_box2)恰好含 cohort-weight 最大单像素值。
> 本文件:把实际 `op<0.01` 删除 + 离线重渲染补到缺失的 **6 图**(balloon2 + mv_no_box2 × 3 seed),
> 使"op<0.01 删除算子"在全部 18 张 P2-T prune 图上逐图验证。

- 装置:`scripts/mc_terminal_comp_3seed.py <run_dir> --thresholds 0.01`(零 GPU 训练、离线 interval-5
  full-frame 重渲,表口径同 step5b `R3-P05-map-compression-step5b-terminal-3seed.md`)。
- 输入:2060 P2-T prune `final_after_opt` PLY(back in `/data/monogs-ours-bak/`),saved est pose
  (`plot/trj_full_final.json`),同 step5b 与 matched-rate 的源。
- 本地 2060 单机跑,~2 min/run。

## 结果(18 图完整,粗体 = 本轮新补 6 图)

| seq | seed | rm% | dPSNR (dB) |
|---|---|---:|---:|
| balloon | 0 | 12.8% | −0.0001 |
| balloon | 1 | 18.4% | −0.0001 |
| balloon | 2 | 17.3% | +0.0001 |
| balloon2 | 0 | **11.4%** | **−0.0000** |
| balloon2 | 1 | **8.8%** | **−0.0000** |
| balloon2 | 2 | **11.2%** | **−0.0000** |
| mv_no_box | 0 | 9.9% | +0.0000 |
| mv_no_box | 1 | 8.4% | −0.0000 |
| mv_no_box | 2 | 10.0% | −0.0001 |
| mv_no_box2 | 0 | **9.6%** | **−0.0025** |
| mv_no_box2 | 1 | **12.7%** | **−0.0003** |
| mv_no_box2 | 2 | **13.0%** | **−0.0001** |
| pt1 | 0 | 9.9% | +0.0000 |
| pt1 | 1 | 10.1% | −0.0000 |
| pt1 | 2 | 10.3% | +0.0000 |
| pt2 | 0 | 18.4% | −0.0000 |
| pt2 | 1 | 11.2% | +0.0000 |
| pt2 | 2 | 10.5% | +0.0000 |

**聚合(18 图)**:removal 范围 8.4–18.4%;dPSNR max |.| = **0.0025 dB**(mv_no_box2 seed0),17/18
≥ −0.0003,唯一例外 −0.0025。全部远低于 high-op(−1.6~−5.7 dB)/random(−0.2~−1.0 dB)两到三个量级。

## 修正 manuscript 的 ≤0.002 dB 声称

原 §4.3/§4.7 写 "low-opacity deletion 保持 |dPSNR|≤0.002 dB across all 18 maps" (源自
`p3_matched_rate_extended.md` 聚合 max|.|=0.00210 的最低 5%/10% 删除)。本轮把实际 `op<0.01`
算子扩到全 18 图后,mv_no_box2 seed0 给出 **−0.0025 dB** ⇒ 严格上限改为 **≤0.003 dB**,
且单体大值来自一个已知单像素高峰值序列(mv_no_box2)。必要的一致性修正:

1. **§4.7 / §4.3 的 "≤0.002 dB" → "on 17 of 18 maps |dPSNR|≤0.0003 dB,worst −0.0025 dB
   (mv_no_box2 seed-0);全体 ≤0.003 dB"**。零代价的主张**不受影响**——mv_no_box2 序列平均
   (−0.0010) 仍是微小量级,且该序列的 cohort 单像素高峰值早已在 §4.6 诚实标注。
2. **不删 step5b 的 12 图原表**;把它标注为"4 seed-validated 序列"并在旁边注明明细 6 图
   (balloon2/mv_no_box2)是新补的、同口径。原 12/12 |dPSNR|≤0.0001 的强声称仍限 4 序列表;
   18 图全量的较弱声称(≤0.003)才是全骨干 floor。

## 与 matched-rate 的关系(算子一致性)

matched-rate(最低 5%/10% 删除)与 op<0.01 是**两个不同算子**,二者都安全但力度来源不同:
- matched-rate 的 10% 删除 = 终图 10% 低-op 高斯,其最低 op<0.01 部分贡献≈0,同时吃掉一些
  0.01–0.10 带内仍带少量表面细节的高斯 ⇒ dPSNR 上限 0.0021 dB。
- op<0.01 算子 = 只删严格 <0.01 的→理论单高斯贡献<1%(theory.md),实测 dPSNR 上限 0.0025 dB。
- 二者在全部 6 序列上都比 high-op(−1.6~−5.7)/random(−0.2~−1.0)安全两个数量级。

## 原始输出

- 各 run 的 `posthoc_terminal_comp/op010/terminal_summary.json`(写在 bak 源目录,未污染 results/——需
  回拷回本地 `results/runs/P2/P2-T/` 对应目录或保留本证据)。
- runlog:`results/evidence/p4_op001_missing6.runlog`。
