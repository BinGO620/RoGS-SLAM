# exp27 收口：P10 async iter_per_kf 消融（2026-08-18）

> **P0 判定：async50 成立（5/5，3090 n=5）。纯工程修复，不碰 MRCS 内核。**
> f3_st_hf 静态崩溃根因 = async iter_per_kf=10 硬编码 + DynKF gap_cap=5 强插 215KF → 后端欠优化。
> 修法：Training.async_iter_per_kf=50（默认 10 保持向后兼容）。

## 核心数据（3090，f3_st_hf，n=5）

| 臂 | iter_per_kf | 逃逸率 | mean ATE | 判决 |
|---|---|---|---|---|
| control | 10 | **0/5** | 35.88cm | 全崩 |
| **async50** | **50** | **5/5 ✅** | **2.87cm** | **全活** |
| async150 | 150 | **1/5** | 6.16cm | 过头退化 |

## 因果链

```
gap_cap=5 → 215KF/1074帧（vanilla ~20KF）
  × iter_per_kf=10 → 后端仅 2150 次 BA/周期
  + 队列塞满 → 自由跑路径不触发
  = 地图长期欠优化
  → frame 371（GT帧间平移突增）→ 离散崩溃

iter_per_kf=50 → 10750 次 BA/周期（5×）→ 地图充分优化 → 过 371 稳定
iter_per_kf=150 → 过拟合滑窗旧观测 + 后端延迟 → 跟踪更新滞后 → 反而退化
```

## 三路并发 GPU 利用

| GPU | 机器 | 任务 | 状态 |
|---|---|---|---|
| 3090 gpu0 | jiangwenheng | P10 async 系列 | ✅ 15/15 done |
| 3090 gpu1 | jiangwenheng | P10 async 系列 | ✅ 同上 |
| 2060 | cb 本地 | P10 交叉验证 | ⏳ async10s4+async50s0s1 跑中 |
| V100S | chenfan | flow 生成 | ❌ RGB 数据缺失，卡在 IO |

## 下一步

1. 等 2060 交叉验证跑完（async50 在 2060 上是否同样修好）
2. 验证动态序列 4-14× 增益不掉（balloon/mv_no_box/pt2 各 n=2）
3. 做 ① 队列深度反馈（零超参终极修法）
4. chenfan 补 RGB + flow（等 IO 恢复）

## commit

6b9fd0a4 — P10: async iter_per_kf config旋钮 + 三档实验配置 + 预注册判据
