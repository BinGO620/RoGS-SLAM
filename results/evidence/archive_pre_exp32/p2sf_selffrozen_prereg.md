# 预注册：self-frozen pose de-confounding control（variant C 主 + B sensitivity，2026-08-02）

> **状态**：探索性、前瞻性、机制性对照（mechanistic control on seen data）。
> **不是**主表臂，**不是** H-D 确认实验，**不能**升级 H-D（只能 weaken / leave-unchanged）。
> 生成日期：2026-08-02（任何 self-frozen GPU run 之前）。
> 由 codex + hermes 双审查设计（`consult_synthesis_selffrozen.md`）。
> GO/KILL + 叙事 = 用户保留。

## 0. 这是什么，替代了什么

hermes 的 tracking-difficulty 共线盲点（coverage 与 tracking-difficulty 共线；pt1/pt2 既是高覆盖又是 hard-tracking）在上一轮用 **RGD 借用轨迹** frozen-pose 去混淆失败（gate 1.11cm，文件无时间戳⇒frame 对应不可验证，codex option 2 abandon）。

本对照改用 **self-frozen**：不借外部轨迹，冻结【自家 prune 臂】的自跟踪轨迹，注入回两臂。frame correspondence 100% 可验证（trj_full_final.json 带 trj_gt = dataset GT，anchor 残差 ~0，gate 必过）。

## 1. 两个变体（codex vs hermes 分歧的裁决）

**variant C（主，prune 轨迹注入）**：两臂都用 prune 臂的自跟踪轨迹冻结。完全对称（同注入轨迹，只差 lifecycle）。
- hermes 主张：C 保持真实 11cm regime（pose-map feedback 通道存活）；选择 bias 有界（pt1 seed0 prune-vs-deferred 轨迹发散 ~7cm on 11cm base）+ sign 不可预测（paired 对比所需）。
- codex 认可 C de-confound tracking，但指出 estimand 是 "lifecycle effect when replaying a prune-generated trajectory"（prune-conditioned，post-treatment）。

**variant B（sensitivity，GT-pose）**：两臂都用 dataset GT 冻结（Oracle.gt_pose=true）。
- codex 主张 B 因果最干净（GT exogenous，非任一臂选）。
- hermes 反对 B 主：GT pose = 0cm = 完美 tracking = regime shift（R2-P01-E2 frozen-pose PSNR~15 vs self~23），可能**压住正在测的 pose-map-feedback 通道**⇒ NO-MAP-EFFECT 不可解释（tracking-coupled 或 regime-suppressed）。

**裁决（synthesis）**：**两个都跑，C 主判分支，B 做 regime-extremity sensitivity。** codex 自己说"两臂一致 = 强结果，分歧 = 有信息"。B 的"GT 太完美压住效应"是 validity threat 非 caveat（hermes），所以 C 主。apparatus 8 configs + runner + contract 已就绪。

## 2. 正确的观测量（map-level，非 ATE）

| 量 | 角色 | 说明 |
|---|---|---|
| `refined_num_gaussians` (R_G^F = G_def^F/G_prune^F) | **PRIMARY** | compactness 对比在 pose-map feedback 关闭后是否存活？paired-seed **log-ratio**（codex 修正：不用 2×own_sd） |
| `static_vacated_depth_l1_pen_cm` | GUARDRAIL | 等 pose 下 deferred 是否降保真？inherited 边界 1.56cm |
| `static_vacated_psnr_db` | GUARDRAIL | 同上，inherited 边界 0.28dB |
| `ate_rmse_cm` | **CANARY（非 outcome）** | 两臂按构造相等（共享注入轨迹）；B 下=0；C 下=prune 的 ATE。报但不判 |
| KF count + indices, inserted/promoted/expired/pruned, static PSNR | 记录 | codex: frozen pose ≠ frozen DynamicKeyframe；KF schedule 两臂不同⇒ambiguity trigger |

**保真边界 INHERITED**（不 re-fit）：import `r2_p03_sweep_readout` 的 1.56cm / 0.28dB（与 P2-T 同）。

## 3. 三分支（跑前钉死，codex 修正版）

self-tracked pt1 R_G = 0.794（<1, deferred 更小）。frozen-pose 下分支：

| 分支 | 条件 | 解读 |
|---|---|---|
| **CONCORDANT MAP-EFFECT** | R_G^F 可判 <1 **或** 任一保真 arm-discriminating（>1×own_sd，同号） | deferred 在等位姿下扰动 map ⇒ tracker-orthogonal mapping 通道存在；H-D 机制故事存活（不能归因 coverage vs tracking，但 map-level 通道在） |
| **NO-DETECTABLE-MAP-EFFECT** | R_G^F 落 equivalence 区 **且** 两保真都在 own_sd 内 | 自跟踪 compactness 对比可能依赖 pose-map feedback（tracking-coupled）；H-D 机制故事**减弱**。**B 下若也 NO-MAP-EFFECT 则不可解释（regime-suppressed），需 C 单独判** |
| **REVERSED MAP-EFFECT** | R_G^F 可判 >1（deferred 更大） | 与自跟踪 <1 矛盾⇒自跟踪 compactness 是 tracking-coupled，非 map-level |
| **MIXED/TRADE** | compactness 与保真反方向 | 两轴 trade，记但不单判 |

**不要求保真差才算 G-count effect**（codex）：G-count 可单独构成 map-effect。联合结果分 compactness-benefit / fidelity-benefit / harm / trade。

**equivalence 区**：paired-seed log(G_def/G_prune) 的预声明 equivalence band（从 R2-P03 balloon frozen-pose CV ~7.8% 派生），不是 2×own_sd（codex 修正）。单 seed 时无法估 own_sd→seed 0 只判方向 + 是否明显远离 1；判别性结果补 3 seed 后再下分支。

## 4. 预声明护栏（codex + hermes）

1. **ATE = canary 非 outcome。** 写明构造恒等。
2. **单 seed = screening。** seed 0 不下判决；MAP-EFFECT/REVERSED ⇒ 3 seed。不让单 seed 覆盖 3-seed 自跟踪主表。
3. **保真边界 inherited 不 re-fit。** import 1.56cm/0.28dB。
4. **不从本实验单独升级 H-D。** 上限 = weaken / leave-unchanged。
5. **Provenance：** pt1+balloon2 已见 = "mechanistic control on seen data"。
6. **Selection-bias 披露**（hermes）：C 注入轨迹是 prune 的 post-treatment 产物，bias 有界 ~7cm + sign 不可预测。estimand = "lifecycle effect when replaying a prune-generated trajectory"。
7. **B 是 sensitivity 非 branch。** 若 B 压住效应而 C 显示，符合 pose-map feedback 部分中介；若两者一致 = 强结果。
8. **KF indices**（codex）：冻结 KF indices 若可行；否则两臂 KF schedule 不同 ⇒ ambiguity trigger（R_G^F 测总 lifecycle mapping-policy 效应，非纯 admission efficiency）。

## 5. 序列选择（codex+hermes 一致）

**pt1 + balloon2**（非 pt1 alone，非 balloon）：
- pt1 = hard-tracking + moderate-cov（29.9%），自跟踪 R_G=0.794。
- balloon2 = easy-tracking + highest-cov（59.4%），自跟踪 R_G=0.910（INDETERMINATE）。
- ⇒ 2×2 contrast（hard/easy × frozen-pose delta），pt1-alone 给不了。
- pt2 = 后续 robustness（高方差 + near-limit tracking 削弱诊断清晰度）。

## 6. 与叙事的关系

本对照给 hermes 的 tracking-difficulty 共线盲点一个**直接的机制性检验**（self-frozen 绕开了 RGD 的 frame-correspondence 失败）：
- **CONCORDANT MAP-EFFECT** ⇒ 边界有 map-level 通道，叙事 D′ 的 "lifecycle 直接改变 mapping" 站得住，limitations 写"tracking-difficulty 共线已用 self-frozen 部分排除（C），B 作 regime-extremity 旁证"。
- **NO-MAP-EFFECT**（C 单独）⇒ 边界可能由 tracking 驱动，叙事 D′ 保持"sequence-dependent boundary，mask-coverage 仅 candidate stratifier，tracking-difficulty 共线未排除"。
- **REVERSED** ⇒ pt1 自跟踪方向是 tracking-coupled，H-D 在 pt1 支持进一步减弱。

**不能升级 H-D**：n=2、map-level only、seen data。上限 = weaken / leave-unchanged。

## 7. 配置与合同

- 8 base configs（`p2sf_{b,c}_{prune,deferred}_{pt1,balloon2}.yaml`），C 带 sentinel `__PRUNE_TRAJ__` 由 runner 解析。
- `scripts/r2_p2_sf.py`（runner：解析 sentinel per (seq,seed) → resolved config → slam.py；B 直接调 base config）。
- `tests/test_p2sf_selffrozen_configs.py`（6 tests：C sentinel / B gt_pose / pose freeze / overlay diff / twin lifecycle / C source 存在）—— **全部 PASS 2026-08-02**。
- 跑：`python scripts/r2_p2_sf.py --phase seed0`（8 run ~4h on 2060）→ readout → MAP-EFFECT/REVERSED 才 `--phase full`（seeds 1,2，16 run）。

---

## 8. 跑中 addendum（2026-08-02，**写于 1/8 run 完成时、任一 ratio 可计算之前**）

> **时点声明**：本节写于 seed0 campaign 启动后、第 1 个 run（`pt1_c_prune_seed0`）刚收工时。
> 当时**没有任何 deferred 臂完成**，因此 `R_G^F` 在本节落笔时**在数学上尚不可计算**。
> 这是把 §3 留空的常数钉死的唯一诚实窗口。**§1–§7 一字未改。**

### 8.1 equivalence band 的数值化（§3 只给了推导来源，没给数）

§3 写的是「从 R2-P03 balloon frozen-pose CV ~7.8% 派生」——**推导来源是预声明的，常数不是**。
现按该来源逐字实算：取先前**每一个**带成对 (A0_prune, B_deferred) 冻结位姿臂的 campaign，
算 **paired log-ratio `log(G_def/G_prune)` 的 seed 间 sd**（= P2-SF primary 观测量本身的零散布），
再按 df 加权**组内**合并（**只取 seed 抖动，A0-vs-B 的真实大效应不进入**）：

| campaign | n | 逐 seed ratio | sd_log |
|---|---|---|---|
| R2-P03-SWEEP | 3 | 0.4706 / 0.4369 / 0.4603 | 0.0382 |
| R2-P03-DECOMP | 3 | 0.5315 / 0.4912 / 0.5817 | 0.0845 |
| R2-P04-MASKRATE | 3 | 0.4979 / 0.5071 / 0.4556 | 0.0572 |
| **POOLED（df=6）** | 9 | — | **0.0629 = 6.29%** |

⇒ **±1×sd band = ratio [0.9390, 1.0649]**（±1.5× = [0.9099, 1.0990]；±2× = [0.8818, 1.1341]）。
**k=1 是继承的房规**，不是新规则：两条保真 margin（1.56cm / 0.28dB）**各自就是 1× null sd**。
readout 同时打印 k=1/1.5/2 三档，分支若对 k 敏感必须显式写出来。

**S6REPL 故意缺席**：它按自己的跑前声明**没有 A0_prune 锚**，因而没有成对 ratio。

**三条 caveat（引用该 band 处必须同引）**：
1. band 来自**另一个 regime**（rtoff 骨干 + balloon + RGD 注入位姿），是**噪声尺度**，
   **不是**本骨干/本序列的零分布；
2. 实算 6.29% 与 §3 手写的 "~7.8%" 同量级但**不相等**——以本节实算为准，§3 那个数是设计期估计；
3. **对 seed 0 基本不承重**：§3 已规定单 seed「只判方向 + 是否明显远离 1」，band 只作参照。

### 8.2 runner 取数缺陷（**不改 runner**，readout 侧补救）

`scripts/r2_p2_sf.py::_extract` **自己手写了取数**而没有 import 全项目通用的 `parse_run`，
四处独立写错，实测第 1 个 run 的日志行即为
`exit=0 18.1min G=None ate=None vac_depth=None vac_psnr=None`：

1. glob 了 `<run>/datasets_bonn/*/seed_*/*/tables` —— **该目录不存在**（表在 `<run>/tables`），
   glob 空 ⇒ `_extract` 提前返回，记录只有 exit 没有任何 metric；
2. 取 `next(csv.DictReader(f))` = **第一行**，其 `mask_type=full`；预注册口径是 `mask_type=="static"` 行；
3. 要 `static_vacated_psnr_db`，实际列名是 `static_vacated_psnr`；
4. 要 `num_keyframes`，关键帧数实际来自 `plot/trj_final.json`（`r2_p03_sweep_readout.keyframe_count`）。

**处置（钉死）**：**campaign 期间不改 runner**（硬纪律③）。`slam.py` 把每张表都正常写盘了
⇒ **GPU 工作零损失、完全可恢复**。新增 `scripts/r2_p2_sf_readout.py`，用
`parse_run` + `keyframe_count`（**import 不复制**）直接从 run 目录重算全部观测量，
`p2sf_results.jsonl` 的 metric 字段**作废不用**（其 `exit` 仍有效）。
**runner 的修复留到 campaign 收工之后**，且属于装置 bug 修复、不改任何判据。
