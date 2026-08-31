# exp27 跨机器交叉验证更新（2026-08-19 会话收尾）

## 当前完成状态

### jiangwenheng (3090 ×2)

**P10 ASYNC BUDGET — ✅ 15/15 完成**

| 臂 | seed0 | seed1 | seed2 | seed3 | seed4 | mean | 逃逸 |
|---|---|---|---|---|---|---|---|
| async10 | 36.3 | 35.9 | 35.6 | 35.5 | 36.1 | **35.9cm** | 0/5 |
| **async50** | 3.3 | 3.3 | 2.5 | 2.8 | 2.5 | **2.9cm** | **5/5 ✅** |
| async150 | 6.5 | 6.3 | 6.1 | 2.6 | 8.9 | **6.1cm** | 1/5 |

**P10 DYN VERIFY — 10/12 完成**

| 序列 | async10_s0 | async10_s1 | async50_s0 | async50_s1 | 判决 |
|---|---|---|---|---|---|
| balloon | 16.1 | 15.4 | 11.6 | 14.8 | async50 仅 −27% 改善，非 14× |
| f2_xyz | 2.0 | 1.9 | 1.8 | 2.0 | async50 与 async10 同量级 |
| f2_person | 6.7 | 7.6 | ⏳跑中 | ⏳跑中 | — |

### cb (2060)

**P10 ASYNC BUDGET — 9/15 完成，6 进程跑中**

| 臂 | seed0 | seed1 | seed2 | seed3 | seed4 | 状态 |
|---|---|---|---|---|---|---|
| async10 | 32.9 | 36.6 | 32.4 | 34.3 | 36.0 | ✅ 5/5 done |
| async50 | 2.8 ✅ | **20.7 ❌** | 2.7 ✅ | ⏳跑中 | 未开始 | **seed1 崩了** |
| async150 | 未开始 | 未开始 | 未开始 | 未开始 | 未开始 | — |

## 关键发现

### ① async50 在 2060 上不稳定（硬件依赖）

- 3090: 5/5 全活（mean 2.9cm）
- 2060: 2/3 现状（seed0=2.8, seed1=20.7❌, seed2=2.7, seed3 跑中）

**说明**：iter_per_kf=50 在 6GB 显存下不够鲁棒，修法是硬件依赖的补丁。

### ② 动态序列上 async50 无显著增益（balloon）

- balloon async10: 16.1, 15.4 (mean 15.8cm)
- balloon async50: 11.6, 14.8 (mean 13.2cm)
- 改善仅 16%，远非之前 P5 的 14× (43.94→3.06)

**说明**：之前的 14× 来自 MRCS 内核 (combined vs vanilla)，不是 iter_per_kf。
async10 vs async50 只是"同样用 combined，不同优化预算"，差异小。

### ③ f2_xyz 上两臂无差异

- async10: 2.0, 1.9
- async50: 1.8, 2.0

两臂同量级（~2cm），说明 f2_xyz 不是 iter_per_kf 敏感序列。

## 技术判断（结合 codex 咨询）

### 根因三层叠加（codex 诊断）

```
① vanilla MonoGS 在 f3_st_hf 本身脆弱（exp26 测得 vanilla 4/5 失败）
   ↓
② dense KF (215个) 饿死后端 → 地图欠优化（async 队列满，自由跑不触发）
   ↓
③ reliability signal 闭环缺陷：pose error → 误判 dynamic flow → 下权重静态 → pose 更差
   ↓
结果：把 vanilla 的"偶尔失败"(1/5) 变成"必然失败"(5/5)
```

### async50 修法的性质

- **不是方法贡献，是工程补丁**：用"更多迭代"补偿 dense KF 的后端饥饿
- **硬件依赖**：3090 稳定、2060 不稳定（显存/算力差异）
- **不改变动态增益来源**：balloon 上仅 16% 改善，证明 14× 来自 MRCS 不是 iter

### 项目根本问题（架构审视结论）

1. **没有稳定的 baseline**：V1 在 f2_xyz 漂 55cm，current combined 在 f3_st_hf 崩溃
2. **方法是组件堆叠，无通用内核**：WP-A 判 3 组件非联合必要、P7 判 cue 融合 regime-dependent
3. **最高准则检验失败**：
   - "方法贡献是我们自己的吗？" → 不确定（MRCS = {Mask, Huber, Reliability, DenseKF}，只有 Reliability 是我们的，但机制不清）
   - "对动态 3DGS SLAM 有用吗？" → 部分是（balloon 4-14×），但以静态崩溃为代价

## 下会话建议（codex + claude 一致）

### 立刻做：P11 sparse KF + mask-only baseline（Option A）

**假设**：3DGS SLAM 不需要 dense KF + 复杂 reliability，mask-guided static-only mapping 足够。

**配置**：
```yaml
DynamicKeyframe: false   # vanilla KF
ReliabilitySignal: false
SemanticMask: 
  mask_mapping: true     # 只 map 静态区域
RobustTracking: true     # 保留 Huber
```

**实验**：{f3_st_hf, balloon, f2_xyz, mv_no_box} × 3 seeds = 12 runs（~3h）

**判据**：
- f3_st_hf 不崩（验证稳定性）
- balloon 有改善（验证动态增益）
- KF 数量回到 ~20（不是 215）
- Gaussian 数量、FPS、渲染质量

**三种结果**：
- A: mask-only 成立 → 写"3DGS-specific mask-guided mapping"（需论证为什么 3DGS 特殊）
- B: 静态稳定但动态无增益 → 证明需要 reliability，实现 queue-aware + ego-protected reliability
- C: 仍然崩溃 → 问题在更底层，论文转向"诚实的失败分析"或放弃 f3_st_hf

### 无论如何都做：Option B (queue-aware budget)

即使不作为方法贡献，也要修工程 artifact：
```python
queue_depth = len(self.current_window)
iter_per_kf = max(base_iters, target_total / queue_depth)
```

### 不做（codex 明确反对）

- Option C (adaptive config paper)：除非有 principled regime detector
- Option D (explicit object tracking)：超出 1-2 周时间线

## commit 状态

- HEAD: b47064d4 (fix balloon config inherit)
- 完成的修改：P10 config 旋钮 + 3 档实验 + 预注册判据
- 未 commit：本次交叉验证结果（等 2060/3090 全部跑完）
