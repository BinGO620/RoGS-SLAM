# long-horizon 位姿正则 — 对抗复核综合（exp-v3-15）

> 2026-08-11。`results/probes/pose_reg/pose_reg_findings.md` 经 hermes + codex 双对抗复核 + 我以
> C2W 修正口径复验。本页 = 双审的共识/分歧 + 我的最终决策。

## codex 复核（thread 019fefb9）— **推翻一处关键裁定，并给出新判别实验**
codex 三点（均已校验）：
1. **"旋转贡献 0"只成立一半**。`evo translation-part ATE` 根本不算姿态旋转，9.16cm 由 C2W **相机中心
  轨迹**决定（措辞应改，非"被对齐吸收"）；且**离线替换固定平移不能证明在线旋转正则无收益**——旋转
  改善仍可能通过渲染→后续跟踪**间接**改善平移。
2. **"无现成信号"过强**。`utils/full_frame_pose.py:175` 已有静态区 ORB + 源帧深度 + PnP；frozen RAFT
  提供独立于光度残差的像素对应。缺的是**已验证的长时锚实现**，不是观测源。（现版 FullFramePose 只
  offset 1/2、继承源帧漂移、用同一 map loss 门控 ⇒ 是短程里程计，非长基线锚；既往 NEGATIVE 未直接
  否定 pt1 长基线约束。）
3. **唯一建议再做的低成本判别** = **离线长基线 ORB-PnP pose graph**：pt1 取 offset 15/30/60，用现成
  静态 mask + RGB + 源帧深度生成相对位姿边，与逐帧边一起 SE(3) pose-graph 优化，按同口径算 ATE；
  **先绕过 `map_precheck`**（否则独立观测仍被已知有偏的光度目标否决）。若长边覆盖不足或优化仍 ≥9.16
  ⇒ 支持停止；若改善 ⇒ 说明不是"换估计器才有信号"，是现版 FullFramePose 的短基线+门控设计限制。

## hermes 复核（`consult_hermes_posereg_findings.md`）— 有效且推翻多处
1. **探针脚本用错相机中心约定**（对 C2W 用 `inv(T)[:3,3]`）⇒ 初版比值错：path 1.10 → 真 **1.28**、
   raw dist 299cm → 真 **133/244cm**、方向≈100% → 真 **11.7/12.0 近等**。初版裁决链支点"长度≈0%"撤销。
2. **旋转不是"欠转"，是"转向相反"**（9/9 run，yaw 符号一致率 ~0.11，corr -0.63）。"0.35×欠转"是测地线
   绝对值求和的假象。
3. 特征锚初版 strawman（est 增量回放 + GT 重定位）**否不了特征锚**；hermes 插值对照 K=60→7.67cm
   优于 baseline 9.16，**候选③恢复 open**。
4. hermes 建议跑 yaw 符号翻转 oracle（判旋转正则方向）。

## 我的复验（C2W 修正，脚本 `scripts/probes/pose_reg_probe.py`）
- **决定性（措辞经 codex 修正）**：`gtROT+estTRANS` ATE=9.16（不变）、`estROT+gtTRANS` ATE=0.0
  ⇒ **`evo translation-part ATE` 根本不算姿态旋转，9.16cm 由相机中心轨迹（C2W 平移列）误差决定**
  ——不是"旋转漂移被对齐吸收"，而是该 metric 不参与旋转评分。**且**离线替换固定平移**不能证明在线
  旋转正则无收益**：旋转改善仍可能通过渲染→后续跟踪间接改善平移。（此 caveat 已并入决策）
- **rotation-自由**：`GTlen+estdir` 11.7 与 `estlen+GTdir` 12.0 近等。翻转 yaw 增量符号 oracle ATE
  仍 9.16（不变）——但这是**离线平移不变**下的观察，不能排除在线旋转隐式纠偏。
- 平移增量残差 autocorr lag1=0.99（平滑低-中频），方向性（across > along）。

## 对候选的最终裁定（结合两审 + 我的复验）
| 候选 | 初版判 | hermes 判 | codex 判 | **最终裁定** |
|---|---|---|---|---|
| ①轨迹平滑/恒速先验 | 否 | 推翻(需重审) | —（同②域） | **低优先**：作用平移增量方向性漂移，codex 已判此局部域饱和（RPE 1.60 优于 RGD） |
| ②航位推算死区 | 否 | 前提假但"非独立"保留 | — | **不值跑**：继承同一跟踪增量偏置，无新信息 |
| ③特征锚 | 否掉 | 插值 K=60→7.67 open | "无现成信号"过强，建议离线长基线 PnP 判别 | **按 codex 判据判死（3/3 定稿）**：ORB-PnP 长边相对 GT 旋转误差中位 12.4/17.1/37.1°（fail <3°/p90<8° 门槛 4–13×）；pose-graph 全边优化后 ATE 9.42/9.69/9.31 ≥ 基线 9.16/9.31/8.99，无 ≤7.2cm。见 `pose_graph/orb_pnp_long_edges_findings.md` |
| 旋转正则 | 需绝对航向 | 提议 yaw oracle | **离线替换不能证在线无效** | **不因离线证据判死**；旋转改善可能间接改善平移（编码为 caveat） |

## 决策（最终）
- person-ATE 9.16 = **当前 dense-edge 光度跟踪公式在 person 序列的 empirical limit**（codex 已定，
  非数据集 floor）。
- codex 建议的**离线长基线 ORB-PnP pose-graph 判别已跑完（3/3 seed）**：PNP 长边旋转误差 12–39°
  （fail codex <3°、p90<8° 门槛 4–13×），pose-graph 优化后 ATE 均 ≥ baseline（9.42/9.69/9.31 vs
  9.16/9.31/8.99），无 ≤7.2cm ⇒ **特征锚方向按 codex 判据判死**。
- ⇒ **long-horizon 位姿正则三候选（①平滑 ②航位推算 ③特征锚）+ 旋转正则全部离线/离线实验判死，
  探索彻底闭环**。**不烧进一步 GPU 追 person-ATE**；算力还给双层头条主线。写作上 pt1 作适用域边界
  + RPE 优于 RGD。
