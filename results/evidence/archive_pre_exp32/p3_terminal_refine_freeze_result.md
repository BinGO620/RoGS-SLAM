# P3-TERMINAL-REFINE — frozen-opacity 反事实结果 + 分支判定（2026-08-07）

> 产出：2026-08-07。反事实（1 run，balloon prune base seed0，exit 0，commit `b3a4170`）
> 回答 `p3_terminal_mech_autopsy.md` §5 的判据：尾巴是否 color-refinement 软抑制产物、锁
> opacity 是否等价质量且无尾巴。

---

## 1. 反事实怎么做

- 新增 `TriReliability.color_refinement_freeze_opacity: true` 旋钮（`slam_backend.py:847-861`,
  `base_config.yaml`）：refinement 的 26000 迭代期间**只冻 opacity**（`opacity` 组 lr→0），
  几何(xyz/scaling/rotation)+颜色(f_dc/f_rest)仍活。与既有 static-guard 路径正交（那个会换
  L1 损失并冻 geometry，不是这个）。
- 配置 = P2-T prune run config by **identity** + 仅这一个旋钮（`tcf_freeze_balloon.yaml`）。
- 对照 = 已存标准 P2-T balloon_prune_seed0（同一 base 配置，无 freeze 旋钮）。

## 2. 结果（PLY 直读 + 同口径 offline render interval-5）

### 2a. 尾巴（op<0.01 占比，final=在线 / after_opt=refinement 后）

| run | 在线 final | refine后 after_opt | 变化 |
|---|---|---|---|
| **std** (P2-T balloon_prune_seed0) | 1.79% | **12.79%** | +11.0pp |
| **freeze**(反事实) | 4.09% | **3.68%** | **−0.4pp** |

另：op<0.05 std +14.5pp vs freeze −1.5pp；>=0.9 std −15pp vs freeze −6pp。

**→ 冻结 opacity 后，refinement 几乎不再制造 op<0.01 尾巴（12.8% → 3.7%）。**

### 2b. 质量与地图规模（同口径 offline render_psnr，final_after_opt 原图 referee）

| run | after_opt PSNR_ref | N_after | 删 op<0.01 能删多少 | 删代价 |
|---|---|---|---|---|
| std | **22.075** | 32653 | 4175 gaussian (12.8%) | dPSNR = **−0.0001** |
| freeze | **21.542** | 44074 | 1622 gaussian (3.7%) | dPSNR = −0.0004 |

> 额外：freeze 在线 N=39074 vs std 32653（+6.4k），且 freeze 的 after_opt N=44074 含一个
> +5000 的 before_opt-eval 插入竞态。map **规模不可比**，PSNR 对比需注意这一 caveat。

## 3. 三分支判定（对照 `p3_terminal_mech_autopsy.md` §5）

| 分支 | 条件 | 实测 | 判定 |
|---|---|---|---|
| ① 等质量+无尾巴 ⇒ refine 缺陷 | freeze ≥ std 质量 且 尾巴消失 | freeze PSNR 21.54 < std 22.08（**−0.53dB**），N 更大 | **✗** |
| ② 质量降 ⇒ 软选择有用 | freeze 明显劣化 | 只降 0.53dB（小幅；且地图规模含竞态干扰） | **≈✗**（小幅）|
| ③ 关联合参数补偿 | freeze 导致几何/scale 补偿 | freeze 后 N 涨 35%（少了 12.8% 软抑制 → 留下更多不透明高斯） | **★ 最接近** |

**科学结论（机制）**：op<0.01 尾巴**确由** color-refinement 的 opacity 软抑制制造（冻 op 后
12.8%→3.7%，机制验证成立）。这**证实了 terminal compression 的"删 op<0.01 零代价"对象**就是
refinement 压到近零的高斯。

**工程结论**：锁 opacity **不是免费修复**——它消尾巴但 cost 了 −0.53dB、且没有省参数（反而
N 涨 35%）。opacity 抑制对 refine 的质量/紧凑有**实际正面贡献**。因此"refine-aware 在线删 inactive
高斯来省参数"这条**不成立**（在地图上它反而更大）。

## 4. 这对论文贡献的真正意义

**原预期（赌 refinement-aware compaction 省参数）被反事实否掉**：不是"更干净的 refine 循环"。

但**留下一个更硬、但更窄的真贡献**：
> **MonoGS 的标准最终 color-refinement 会把 ~10-13pp 的高斯 opacity 软抑制到 <0.01，
> 这批高斯在 volume rendering 里贡献 <1%（theory.md 上界仍然成立），可被终图一次性删除，
> 12/12 run 删 9-16% 且 |dPSNR|≤0.0001 dB。** 它的"存在"是 refine 阶段的 opacity DOF 造成的
> 软选择（freeze 后可消），"删除"零代价（已核）。

这条的定位：
- 是**可复现的后处理压实观测 + 一个机制解释**（为什么会有这么多可零代价删的高斯：因为 refine
  的 RGB-only 优化用 opacity 作自由参数做了隐性软选择，缩出一批近零 opacity 贡献）。
- **不是**系统级"省一次 compute"贡献（refine 本身还是要算，freeze 不省）。
- 对 CCF-C / MMM：诚实主线上可报 = "dynamic 3DGS SLAM 终图的隐性 opacity 软选择 + 零代价终图压实"，
  配 P2-T 骨干 ATE（balloon 3.07/ mv_no_box 2.58 有竞争力的主表）作实证面。这是**降级但真实**，
  比捏一个假机制强。

## 5. 遗留 caveat（写作前必提）

1. freeze 反事实仅 **balloon seed0 单 run**——是机制验证，不是判决；三分支在其它序列/seed 上
   方向可能漂（尤其 0.53dB 与 35% N 差异都受 +5000 插入竞态干扰）。
2. freeze 是"锁 opacity"，不是"refine 中删 inactive"——它测的是 opacity 的因果作用，不是某个
   具体省参数算法。要从反事实到可发贡献还需一个"删除版"实现。
3. PSNR 对比含地图规模不可比 caveat（N 差 +35%）。
4. 同口径 PSNR 用的是 offline interval-5 render（raw full-traj），不是官方 eval 的 fancy PSNR；
   报值时用同口径并注明。
