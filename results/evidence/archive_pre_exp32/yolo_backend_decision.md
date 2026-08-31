# YOLO 后端决定：投稿版不换主表 + 条件性 sensitivity 协议（冻结）

> **状态**：决策记录 + 冻结的条件性协议。**不是** campaign 证据（本文件对应零个 SLAM run）。
> 决定日期 2026-08-01（用户 GO 落盘）。落盘时 P2-T 主表 17/36 跑进中（MRCNN 后端）。
> 来源：`/data/yolo-probe/` 离线 probe 实测 + Codex 对抗讨论（两轮）+ Claude 独立复核。
> probe 原始数据与讨论**不在本仓库**（`/data/yolo-probe/`，隔离 conda env `yolo-probe`）。
> 引用本文件任何 probe 数字必须带 §1 的样本量 caveat。

## 0. 决定

1. **投稿版（MMM 2027，2026-08-16 AOE）主表分割后端保持 Mask R-CNN（`maskrcnn`），不切 YOLO。**
2. **已有 mask-enabled run（32 个）与 P2-T（36 run）全部不动、不重跑。**
3. YOLO 定位 = **条件性 sensitivity 检查**（触发条件、配置、判读全部在 §3 冻结）
   + 下一篇 / journal 版的后端候选（revisit 三条件见 §5）。
4. **YOLO 后端代码在触发条件命中前不实现**（campaign 期间不改 live code + Codex 共识 #3）。

## 1. probe 实测数字（2026-08-01，离线，非 SLAM 实验）

**依赖安全（一票否决项：通过，但限定在隔离 env）**：隔离 conda env 装 `ultralytics
8.4.114` 前后，`torch 2.1.0+cu118 / numpy 1.26.4 / opencv-python 4.8.1.78` 三件套全部未动
⇒ `utils/semantic_mask.py:5` 注释写下的依赖风险已实测排除。**caveat**：这是隔离 env 的
结论；若将来装进主 env（`/data/conda_envs/monogs-ours`），装完必须重验三件套版本。

**性能（Bonn balloon 真实帧 480×640，n=30 帧）**：

| 模型 | 延迟(中位) | VRAM | 加速比 |
|---|---|---|---|
| Mask R-CNN R50-FPN（现役） | 247.2ms | 0.640GB | 1.0× |
| YOLOv8n-seg PT | 13.9ms | 0.060GB | 17.8× |
| YOLOv8n-seg TRT FP16 | 5.4ms | 0.040GB | 45.8× |

**Mask 质量（n=4 有人帧，样本量小——引用必带此注）**：IoU(MRCNN vs YOLO-PT)
mean **0.909** [0.875, 0.923]；含 dilate 后 vs TRT **0.979**；面积比 0.995；
MRCNN-only 像素 5.4%、YOLO-only 9.1%。

**推论口径（决定的事实基础）**：mask 等价级（IoU ≥0.9、面积比 ≈1）⇒ 换后端对
ATE / rendering / compactness 的**任何已定判决无预期改进**；唯一改进 = 组件延迟。
自跟踪 run 里 semantic 占 wall-clock **8-12%**（efficiency_raw.csv，5 个设置 8.4-12.1%），
换 YOLO 每 run 省 ~100s，FPS 0.535→0.599（+12%，竞品带 0.19-1.84 内位置不变）。

## 2. 为什么投稿版不换（三条承重理由 + 两条已弃用的旧理由）

1. **headline 零改进（§1 实测）** + 用户准则（tracking+rendering 要好、efficiency
   过得去即可、纯快意义不大）。"如果换了真的更好，重跑是正确的事"这一原则**成立**，
   但前件不成立：这不是"更好"，是"同样的 mask、更快的组件"。
2. **窗口不存在 + 硬约束**：换 = 停 P2-T（禁）或收工后立刻作废重跑 ~21-25h，外加
   R2-P04 9 run + P2-S 4 run；P2-T 收工 → F@5cm → 08-04 叙事门的 GPU 链直接断。
   且同配置重跑比值已实测漂 **+21%/+29%/−23%**（README ~30% 门槛的来源）⇒ 全量重跑
   = 重掷 M2、pt2 反向、compactness 配对证据等全部边界判决；收益 = 以后每个 36-run
   campaign 快 ~1h（36×100s）。
3. **论文站位**：贡献 = lifecycle/准入机制，检测器 = 脚手架（DynaSLAM 先例）。R2-P04
   已钉死的 caveat（竞品 mask 离线预计算、运行时不付在环内分割成本）**对 YOLO 同样
   成立** ⇒ 换后端买不掉这句话，"审稿人观感"收益小；反过来主表切 YOLO，每张对比表
   都继承"差异有多少来自检测器"的归因问题。

**已弃用的旧理由（诚实记录，2026-08-01 用户指正后撤下）**：
- ~~"护住 32 个已有 run"~~ —— 沉没成本逻辑，单独不构成理由；
- ~~"M2 可能翻转"~~ —— M2 本就是噪声带内的分辨率陈述（M 的 CV 17%、预声明带宽
  ±38%B，`r2_p04_maskrate.md` §4），不承重、不需要保护；主表不换它也根本不动。

## 3. 条件性 sensitivity 协议（冻结，事后不得改判读）

**触发条件（三者同时命中才跑）**：
(i) P2-T 的 H-D 落 **CONFIRMED**（`hd_coverage_prereg.md` §4 三分支）；
(ii) 用户在 08-04 叙事门决定覆盖率机制写进论文正文；
(iii) 08-06 写作硬起点前有 ≥半天代码 + ~1h GPU 的干净空档。
**任一不命中 ⇒ YOLO 本篇零出场**（efficiency 措辞至多引 §1 数字作 descriptive 观察，
必须带 R2-P04 caveat 与样本量注记），全部材料留给下一篇。

**触发后配置**：`p2s_combined_{prune,deferred}_balloon.yaml` 的孪生 ×
**唯一差异 = `SemanticMask.model: yolov8n-seg`** × seed 0 × **PT 模式（禁 TRT）**。
合同测试须钉住唯一差异（照 `test_p2_combined_twin_configs.py` 的写法）。
禁 TRT 理由：在环内相对 PT 只再省 ~3s/run，却引入双 engine（2060 SM75 ≠ 3090 SM86）、
FP16 跨架构数值差（IoU 0.979≠1）、每机 ~20min 导出——论文里至多一句 deployment 脚注。

**判读（screening 级，跑前钉死；单 seed = screening，硬纪律⑤，不出统计判决）**：
- (a) 两臂 G_def/G_prune 方向与 MRCNN 孪生一致，且 ATE 变化在该序列 seed 带内
  （参照 P2-T balloon 逐 seed 带）⇒ 措辞上限 = "**未见后端依赖迹象（单 seed screening）**"，
  不得写"结论对后端不敏感"之类的判决级表述；
- (b) G 方向翻转或 ATE 大幅劣化 ⇒ **如实报告"该观察依赖分割后端"，不得静默**，
  相应 claim scope 从"person-mask 方法"收缩为"Mask R-CNN 下的观察"；
- (c) 无论哪个分支，**YOLO run 不进主表、不进 registry 主行**（标注 sensitivity）。

**能力边界（Codex 共识 #6/#7，写进论文时同引）**：MRCNN 与 YOLO 都是 COCO-person
detector ⇒ 本检查只证**后端**鲁棒性，不证 **coverage** 鲁棒性；coverage 鲁棒性的直接
实验 = 现有 MRCNN 上扰动 `conf_threshold`/`dilate_px`（零新依赖、零 blocker、4-6 run，
未排期，信息量大于换一个 IoU 0.909 的检测器）。

**实现前置：7 条 blocker 修复清单（实现时逐条销，全部有合同测试）**：
1. ~~仅关键帧跑分割~~ **构造上不可行，直接放弃该优化**：mask 在 `tracking()` 开头
   （`slam_frontend.py:645-657`，pose init 之前）逐帧要用，KF 判定在 `run()` 里
   tracking 返回之后才发生；
2. `_load_model`（`semantic_mask.py:102-125`）现状是未知模型名**静默 fallback 到
   DeepLabV3** ⇒ 改显式后端注册表，未知名 **raise**，不 fallback；
3. 输出格式：MRCNN `(N,1,H,W)` sigmoid vs YOLO `(N,H,W)` binary ⇒ 适配层统一到现有
   `(1,H,W) bool | None` 契约（`compute_semantic_dynamic_mask` docstring）；
4. 类 ID per-backend：MRCNN person=**1** / YOLO person=**0** / DeepLabV3 person=**15**
   ⇒ per-backend 默认表，配置里的 `dynamic_classes` 语义显式按后端解析；
5. soft 路径（`compute_semantic_person_prob`）始终 DeepLabV3 ⇒ **不动**；
6. `conf_threshold` 语义 per-backend 默认（MRCNN 0.5 / YOLO 0.25），可显式覆盖；
7. letterbox 坐标还原、None vs 全-false 语义保持、ultralytics VRAM 预分配实测。
另加两条环境前置：实现必须在 **P2-T 收工后**（campaign 期间不改 live code）；
ultralytics 装主 env 后重验三件套版本（§1 caveat）。

## 4. Codex 对抗讨论共识（2026-08-01 冻结转录）

1. 架构：YOLO 加为**可选后端**，不替换 Mask R-CNN 默认；
2. 32 个已有 mask-enabled run 不动；
3. 08-04 预注册门前不实现 YOLO；
4. 条件性实验协议冻结（即本文件 §3）；
5. 只有 P2-T 支持 H-D 且覆盖率机制写进论文正文时才跑 YOLO sensitivity；
6. YOLO 只能证明**后端**鲁棒性，不能证明 **coverage** 鲁棒性（两者都是 COCO-person）；
7. 真正的 coverage 鲁棒性用 confidence/dilation 扰动测；
8. R2-P04 效率观察措辞限定为"**本实现中 Mask R-CNN 的成本**"。

**Codex 两条纠正（防止误用 sensitivity 结果）**：
- **M2 与 H-D 是两回事**：M2 = 无 mask B vs Mask R-CNN M（冻结轨迹）；H-D sensitivity
  = combined prune vs deferred（自跟踪，两臂都开 mask）⇒ YOLO sensitivity **不 retest
  M2**，其结果不得写成对 M2 的任何支持或反驳；
- **YOLO 审计不了 R2-P04 的 2.01× VRAM / 2.7× FPS**：P2 两臂同开 mask，换 YOLO 两臂
  成本同降；要审计需"无 mask B vs YOLO hard-mask M"不对称新 campaign——除非
  efficiency 升级为论文贡献，否则不开。

## 5. revisit 触发条件（何时重议"全量切换 + 重跑"）

① 投稿后 journal / camera-ready 有 GPU 预算（2-3 天重跑在无 deadline 时便宜）；
② 2060 VRAM 真挡住必需实验（当前 P2-T 自跟踪 2.0-3.24GB，距 6GB 远；5.22GB 那个
   是已废弃的 probe1 路线，不在投稿路径上）；
③ efficiency 升级为论文贡献之一。
**任一命中 ⇒ 全量切换 + 全部 mask-enabled campaign 重跑**；同一张表内两臂必须同后端，
新旧 run **永远不得混后端比较**。

## 6. 论文措辞草稿（写作期取用；sensitivity 未跑前只能用第一段）

- efficiency 节（sensitivity 未跑版）：分割后端在环内每帧 ~210-247ms（Mask R-CNN
  R50-FPN，占自跟踪 wall-clock 8-12%）。该成本是**实现选择而非方法属性**：离线实测
  YOLOv8n-seg 在 mask IoU 0.909（n=4 帧）下延迟 13.9ms（17.8×）。同时（R2-P04 caveat）
  竞品 mask 通常离线预计算，运行时同样不付在环内分割成本。
- sensitivity 已跑且落 §3(a) 时可追加："balloon 上以 YOLOv8n-seg 复跑两臂，方向性
  结论不变（单 seed screening）"。落 §3(b) 时按 (b) 措辞如实报告。
- **禁写**（任何分支）："结论对分割后端不敏感"（判决级）、"YOLO 验证了 coverage
  机制"（共识 #6）、以及一切从 sensitivity 推 M2 的表述（§4 纠正一）。
