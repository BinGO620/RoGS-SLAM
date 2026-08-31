# 动态 3DGS SLAM 新 Idea 调研 — codex adversarial + general 子代理文献核实

> 2026-08-09 exp-v3-11。用户明确要求跳出项目约束，读多篇论文，围绕
> 空洞/ATE差/高斯多/效率慢/显存高 找 MMM 可能的新方法内核。GPU 放开用。
> 本文件 = 调研落点 + 与当天 P6 mask-off 结论的交叉。

---

## 一、来自文献调研子代理（已核实,arxiv 命中）

四大痛点的业界主流解法：

1. **空洞/洞**：主流已从"事后 inpainting 填洞"演化到**双通道大高斯分解**
   （static + transient 分开建模,概率比例合成 alpha）——DeGauss (2503.13176)、
   DeSplat (2411.19756)、DAS3R (2412.19584)。这事中分解比事后补洞更干净,
   天然复用 mask 管线。
2. **ATE 差**：动态 SLAM 的跟踪差距三方确认为 **BA backend 缺失**。业界最新：
   VAR-SLAM (2510.16205) 自适应鲁棒核（Barron loss 替代固定 cauchy）、
   MotionGS (2405.11129) deep feature + motion filter、Gassidy (2411.15476) 光度/几何一致性。
3. **高斯多/慢/显存**：压缩/剪枝是成熟子领域（3DGS.zip 综述 2407.09510、
   Compact3DGS 的 sliding-window masking + geometry codebook 2403.11247）。
   这些**都没被我们的动态模块利用** —— 明显未占的肥肉。
4. **"在线无监督动态性检测"（时域一致性驱动,不做分割）**：**已有直接先例**。
   Gassidy 用渲染 loss flow 逐区域分析区分动态/静态（不做语义分割）；
   D³epth (2411.04826) / CoopNet (2605.07945) 用光度重建残差"两路不一致=动态像素"。
   ⇒ **不能当全新内核直接吹**,但可升级成 3DGS-SLAM 特有的、用渲染残差一致性做
   MAP admission 的动态性 logit —— 这正好接住我 memory 里已埋的 leverage
   （reliability signal,aim at MAP admission）。这是"我们的方法内核"的落点。

## 二、来自 codex 的 adversarial 判断（本次 MCP 返回）

1. **"mask-free 时域残差动态跟踪"不是真空档**。最接近：StaticFusion（RGB-D 用
   时空一致性维护静态地图,不依赖 person mask）、Co-Fusion（多目标运动一致性分割）、
   DSO/LDSO（重投影一致性筛点）、DROID-SLAM（鲁棒残差隐含容忍动态）。
   审稿人会打：①"鲁棒估计+多帧一致性"是重新包装；②单 seed/少序列/无跨数据集；
   ③关闭 mask 后变好可能只是 dense keyframing+鲁棒核+参数共同贡献 → **必须逐组件消融**。
2. **从 3.6cm 继续往下压,性价比排序**：
   - **(a) flow-consensus + 时空加权**——最直接改善动态边界,通常比换核更可能继续降；
     风险：光流在低纹理/快速运动/深度噪声下失稳。
   - **(b) 真正的 BA/loop-closure backend**——若误差是累计漂移,这是上限最高收益；
     风险：工程量+调参最大,动态错误观测进 BA 会全局污染,短序列收益不明显。
   - **(c) BARRON 自适应鲁棒核**——实现成本低,减少固定 Cauchy 不适配；风险：易被读成"换核"增量。
   - **(d) feature-anchored tracking**——补直接法在低纹理/光度变化下的退化；风险：特征落在动态物体上,错误锚点比降权像素更破坏。
   codex 倾向：若没有 backend,优先 (b)；若有,优先 (a)。
3. **记忆点命名**：别叫"mask-free robust loss"。定义明确模块 **Temporal Residual
   Consensus (TRC)**：每个像素维护光度/深度/几何残差的短长时记忆,用一致性与滞回更新
   "静态可信度",该可信度以不同权重进入 pose/Gaussian 加入/Gaussian 更新。
   ⇒ 贡献是"残差记忆驱动的时空共识门控",不是又一个逐帧 outlier rejection。

## 三、与当天 P6 mask-off 结论的交叉（这是真正的增量）

今天刚跑完 P6 mask-off 3-seed：**mask 关闭后**,仅靠 dense-KF + RobustTracking +
ReliabilitySignal,动态序列 ATE 仍远优于 vanilla（balloon 12.11 vs 43.94 /
mv_no_box 3.09 vs 13.60）。这**实测验证了"mask-free 时域一致性动态跟踪"可行**,
它不是竞品声称的东西。

→ **这是 headroom 最有希望的一个新内核方向**：**Temporal Residual Consistency
(mask-free)**。三个组件里,代码审查显示 **dense-keyframing（DynamicKeyframe）最可能是主贡献**——它改变关键帧密度/时序覆盖,是时域一致性的载体;RT+Reliability 是鲁棒补充。

下一步（P-B）直接用 2×2 消融（mask × dynKF）+ RT/Reliability 单独拆,就能既回答
"到底哪个组件撑起 mask-free 4.4×",又给 codex 担心的"逐组件消融"提供证据。
若 dense-KF 单独就扛大头 → **头条可聚焦为"mask-free 时域稠密关键帧动态跟踪"**,
这是纯我们自己的机制（DynamicKeyframe 是我们加的,不在 MonoGS 里）。

## 四、给 MMM 的候选头条（待 P-B 实证后选定）

按最高准则（方法是我们的吗/对动态 3DGS SLAM 有用吗）：
- **候选 1（最优,接今天证据）**：mask-free 时域一致性动态跟踪（dense-KF 主导）。
  "对动态 SLAM 有用"✓，"我们的机制"✓（DynamicKeyframe 是我们加的）。
- **候选 2**：TRC 残差记忆门控（在候选 1 上叠加"静态可信度"模块,给审稿记忆点）。
  若 P-B 显示 dense-KF 主贡献,TRC 可作为方法正文的输入门控层。
- **候选 3（支撑段）**：双通道 static/transient 软分解（DeGauss 式）——若后续要与
  mask 结合,这是比二值 mask 更现代的形态。

## 资源与引用（已核实）

见文献调研子代理输出：DeGauss / DeSplat / DAS3R / GA-GS / VideoPainter / Gaussian
Grouping / VAR-SLAM / Gassidy / DGS-SLAM / MotionGS / DynaGSLAM / Dy3DGS-SLAM /
DynoSAM / Compact3DGS / 3DGS.zip / MemGS / LEGO-SLAM / RP-SLAM / Hier-SLAM /
3DGS-LM / D³epth / CoopNet / SAM+Flow / FASA / SlotLifter / sVORF / QASA /
HS-SLAM / Grid4D（全部 arxiv 号在调研输出,真标题作者年份）。

## 一句话

P6 给了我们一个被竞品忽略、被我们自己在 P6 之前没测到的方向：**mask-free 时域一致性
动态跟踪能压到 3cm 量级**,这是 novel + framework-general + 有自己内核的方向,
需要用 P-B（2×2 消融）实证它是 dense-KF 主导,再配上 TRC 残差记忆门控作为方法记忆点。

## 五、后续实证更新（exp-v3-12 overnight 批,2026-08-10）

**P8 mask-off 全 6 序列主表已回拉**（见 `p6_maskoff_6seq_main_table.md`）：
- 纯物双复现（mv_no_box 3.09≈2.66 / mv_no_box2 5.62≈5.14）⇒ mask 冗余 ✓
- 纯人 pt2（9.30≈10.44）⇒ mask 冗余 ✓
- 混合 balloon（3.96×）⇒ mask 主导,但 bundle 仍优于 vanilla 3.6×
- **⚠ pt1（纯人）:maskoff 32.4±8.5 vs combined 10.0±0.6 = 3.23×,mask 主导,与 pt2 直接矛盾。**
  同一 person 族,一个 mask-free 行、一个不行。pt1 双稳态/高 RPE（2.8-3.1 vs pt2 ~1.6）。
  ⇒ **"纯人 mask 冗余"收窄为 pt2 结论;pt1 是适用域边界反例**（入 limitation,防审稿人反打）。

**对候选头条的影响**：
- 候选 1（mask-free 时域一致性动态跟踪）仍成立（mv 双复现 + pt2 + balloon 仍优于 vanilla 3.6×）,
  但**诚实适用域 = 低遮挡/纯物/部分 person；难跟踪 person（pt1）与混合（balloon）不如 mask**。
- 候选 2（TRC 残差记忆门控）：pt1 的失败正暴露"bundle 缺一个能处理 person 大 RPE 的强模块"——
  TRC 可能正是补 pt1 的方向（但需实验裁决,不空谈）。
- 扩展序列的 vanilla 基线待补：mv_no_box2 / pt1 / balloon2。
