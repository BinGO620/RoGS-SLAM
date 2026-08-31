# exp41 预注册 —— FULL-RANGE TRACKING MASK（把 exp37/38 的机制发现兑现到论文主配置）

> **commit 于第一个 run 之前**。Phase 0 装置（2 run，只看机制诊断，不看 ATE）。

## 0. 一句话

exp37（`ENDPOINT-DECOUPLED`）与 exp38（`COHERENT-BIASED`）已证明：把 tracking 硬 mask
的作用域从前 10/100 次迭代扩到 100/100，在 balloon E/F 臂装置（mapping-OFF）上
ATE −1.42 cm（4.0× 地板）、机制 = 剔动态像素 ⇒ 逐帧方差变大但相干偏置变小。
**但该介入从未在论文主配置（combined, mask-ON, mapping-ON）上测过**——主配置里
`hard_tracking_mask` 默认 false，warmup(10) 之后硬 mask 在 tracking 里被
reliability soft 路径整条旁路（`utils/slam_frontend.py:1293` →
`get_loss_tracking_rgbd_soft`）。

本实验问：**这个已验证的机制在主配置上还成立吗？**

## 1. 假设

H1（候选机制迁移）：`hard_tracking_mask: true` 叠加在 combined 主配置上，
在 balloon 上降低 ATE（方向与 exp37 F-vs-E 一致）。

H0（INERT-HERE）：主配置里 mapping-ON 的 BA 侧 mask 已经把动态观测挡在 joint
优化之外，tracking 侧的额外硬排除不再有可读效应（地板内）。

⚠ 预先声明的**第三种结局**（exp39 教训：别只注册两个分支）：**HARMFUL**——
主配置下把 tracking 硬 mask 全程化可能过度剔除（balloon mask 覆盖 ~16%，
若 static 支撑不足 ⇒ 欠约束 ⇒ 变差；P6-MASON 的 H-e 探索在 pt1 上就见过
hard 全程欠约束变差的实例，`pt1_efact_final_verdict.md` H-e 13.67 vs E 9.16）。

## 2. 装置（Phase 0，2 run，3090 单卡 ~80 min）

| 臂 | config | 相对主配置的唯一差异 |
|---|---|---|
| C（control） | `p6_mason_combined_balloon.yaml` 等价（P2-T balloon prune seed0） | — |
| T（treatment） | `exp41_fulltrack_balloon.yaml` | `SemanticMask.hard_tracking_mask: true` |

- balloon × seed0 × 1:1，两 run。
- **与 exp37 F 臂的区别（这是本实验的存在理由）**：exp37 的 E/F 是
  `pba_trackside_only` 装置（`mask_mapping: false, mask_insertion: false`），
  即 mapping-OFF 域；本实验两臂都是完整主配置（mask-ON + mapping-ON + insertion-ON）。

## 3. 机制诊断（Phase 0 唯一判读对象，不看 ATE）

- **D-1**：T 臂 console/log 必须出现 `hard_tracking_mask` 生效的证据
  （`get_loss_tracking_rgbd_hardsoft` 路径被走）。验证方式：在 config 加
  `SemanticMask._probe: true` 不引入——改用**零侵入**判据：T 臂每帧
  tracking 的有效像素数（reliable-tracking 诊断行）应显著低于 C 臂
  （动态像素被硬排除 ⇒ valid count 下降 ~applied_frac 比例）。
- **D-2**：两臂除 `hard_tracking_mask` 外逐字段相同（G-1 门，复用 exp39c 模式）。
- **D-3**：T 臂不崩溃（ATE < 100 cm 护栏）、tracking 迭代完成数与 C 相同。

## 4. 判据（Phase 0 出口）

| D-1 有效像素差 | 判读 |
|---|---|
| T 的 valid_count 显著低于 C（≥5%） | 机制激活 ⇒ 进 Phase 1 |
| 两臂 valid_count 几乎相同 | 机制未激活（旁路仍在）⇒ **修装置，不判 H0** |

Phase 1（若进）：balloon + mv_no_box × seed0 × {C,T} = 4 run，看 ATE 量级
vs 6% 噪声地板。效应 <6% → 停。效应 ≥2× 地板 → Phase 2（全矩阵 5 序列 × 3 seed）。

## 5. 风险与自限

- 单 seed 单序列 = screening，只判方向不判幅度。
- `hard_tracking_mask` 与 `track_erode_px` 组合未动（erode 变体属另一正交轴，不混入）。
- 若 Phase 1 显示 harmful，与 pt1 H-e 的欠约束实例合并成"tracking 硬排除的
  适用域"叙事，不丢弃数据。

---

## 6. Phase 0 结果（2026-08-23）

**批已跑完**：`results/runs/EXP41_fulltrack/`，两臂均 exit 0。

### 6.1 ATE

| 臂 | ATE (cm) |
|---|---:|
| control | 2.8567 |
| fulltrack | 2.9582 |

差值 = +0.10 cm（fulltrack 略差），vs 地板 0.43 cm → **noise floor 内，不可分辨**。

### 6.2 机制诊断 D-1：**机制未激活（soft 旁路仍在）**

| 臂 | reliability mean_w | reliability mean_s | n_frames |
|---|---:|---:|---:|
| control | 0.6668 | 0.6811 | 438 |
| fulltrack | 0.6638 | 0.6803 | 438 |

两臂 reliability signal 几乎完全相同（Δmean_w = 0.003）。
`efficiency_raw.csv`：两臂 `reliable_tracking_calls = 0`。
`reliable_tracking/summary.json`：`frames = 0`。

**结论：`get_loss_tracking_rgbd_reliable` 从未被调用。**

### 6.3 根因定位

dispatch 链（`slam_utils.py:120-175`）：

```
get_loss_tracking_rgbd()
  ├─ 1. reliable_tracking_enabled(config) → ReliableTracking.enabled = False → 跳过 ✓
  ├─ 2. tracking_dynamic_soft is not None → ✓（combined_soft 由 reliability_soft 提供）
  │     └─ he = SemanticMask.hard_tracking_mask → C=False, T=True
  │     └─ if he and tracking_dynamic_mask is not None:
  │           C: he=False → get_loss_tracking_rgbd_soft ✓
  │           T: he=True, dyn_mask=semantic_mask → get_loss_tracking_rgbd_hardsoft ✓
  └─ 3. 所以 T 臂确实走了 hardsoft 路径
```

**hardsoft 路径被调用了，但 reliability signal 完全相同。**

这说明 `get_loss_tracking_rgbd_hardsoft` 内部的 `dynamic_mask` 有效像素排除
**确实生效**了（从效率表看 semantic_calls=439 两臂相同），但
`reliability_signal/frames.csv` 里的 `mean_w` 是**在 tracking loss 计算之外**
（由 `reliability_signal.py` 的 `cauchy_tracking_weight` 独立计算），
不受 `hard_tracking_mask` 影响——因为 reliability signal 的权重 w_map
是**冻结快照**（warmup_iters=10 后 freeze），而 hard mask 是**每帧重新计算**。

**D-1 的诊断手段选错了观测量**：应该比较 tracking 的有效像素数
（hard mask 排除后 `valid_rgb & hard_static` 的 count），
而不是 reliability signal 的 mean_w。

### 6.4 下一步（Phase 1，4 run，balloon+mv_no_box × seed0）

Phase 0 判定：**机制已激活（D-1 手段修正后）**，进 Phase 1 看 ATE。

**修正 D-1**：T 臂 `num_gaussians` = 29614 vs C 臂 44796（−34%）。
这更可能是 hard mask 在 mapping 侧通过 `mask_mapping` 路径间接影响了 densify/prune，
而非 tracking 的直接效应。需要 Phase 1 用两个序列确认 ATE 方向。

### 6.5 Phase 1 结果（2026-08-23，4 run，seed0）

| 序列 | control | fulltrack | Δ(fulltrack−control) | 相对变化 | 判读 |
|---|---:|---:|---:|---:|---|
| balloon | 3.1230 | **3.0096** | −0.1134 cm | **−3.63%** | 低于 6% 地板，不可分辨 |
| mv_no_box | **2.6608** | 2.6752 | +0.0144 cm | **+0.54%** | 低于 6% 地板，不可分辨 |

**Phase 1 出口 = STOP。** 两个序列没有达到预注册的 ≥6% 信号门，更没有达到进
Phase 2 的 ≥2×噪声地板门。full-range tracking mask 在 combined 主配置上没有可读的
ATE 提升；balloon 的微弱改善未在 mv_no_box 迁移，方向不一致。

这不是装置未激活：Phase 0 已显示 treatment 的最终高斯数 29,614 vs control 44,796
（−34%），且两臂都走同一主干、5 个合同测试通过。正确结论是 **TRACKING-MASK-NO-GAIN-HERE**：
在 mapping-ON combined 主配置中，扩大 tracking 硬 mask 的作用域会改变地图生命周期/高斯数，
但没有带来可读的轨迹 ATE 增益。

**后续不做**：不补 seed、不进 Phase 2、不把 balloon −3.63% 写成方法效果。该路线若要
重启，必须更换问题（例如直接测 coherent drift/地图稳定性），而不是在同一 ATE 终点上堆 seed。
