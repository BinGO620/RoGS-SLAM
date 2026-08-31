# exp26 判别批 — 预注册判据（跑前冻结）

> **冻结时间：2026-08-17（exp26），发批量之前。** 本文件在任何 run 启动前提交。
> 结果回来后只填「实测」栏，**不改判据**。

---

## 1. 要判别什么

exp25 定位了 `rigid_flow` 自运动预测使用「正在被优化的位姿」这个内核缺陷，并用在环
oracle 坐实了闭环因果（control 35.29 → oracle 2.85cm，12.4×，均 n=1，cb 2060）。
随后修法 B（`ego_residual_projection`）在 3090 上出现**双稳态**：

| run | 机器 | seed | FPS | ATE |
|---|---|---|---|---|
| fix | 2060（静、串行） | 0 | 0.450 | **2.99** ✅ |
| fix | 3090（被别的用户占） | 0 | **0.279** | **2.10** ✅ |
| fix | 3090（被别的用户占） | 1 | **0.572** | **35.86** ❌ |

两个 3090 run 的 e_flow 统计量几乎相同（mean 0.105 vs 0.104），ATE 却天差地别。

### 三个竞争假设

- **H-A 修法实现不足**：护栏（`min_explained_frac` / `max_corr_px`）在早期帧拒修，
  残差漏过去，漂移累积后进入坏吸引盆。→ 预测：坏 run 的早期 `ego_fit_applied` 率显著低。
- **H-B 缺陷叙事不完整**：还有第二个失效模式，位姿误差只是其一。
  → 预测：oracle 补到 n=3 时也会出现 ~35cm 的 run。
- **H-C 双稳态是异步竞态的产物**：修法本身有效，是映射预算这个混杂变量在决定吸引盆。
  → 预测：把预算固定住，control 仍崩、fix 稳定收敛。

### H-C 的机制依据（exp26 查明，非猜测）

`utils/slam_backend.py::_run_loop`：`single_thread=False` 时后端在队列空闲时
**自由跑** `self.map(...)`；关键帧到达时 `iter_per_kf = 10`。
所以**两帧之间摊到多少次映射迭代，完全由前端相对后端的快慢决定，也就是机器负载**，
没有任何东西约束它。`single_thread=True` 时后端不自由跑、`iter_per_kf = mapping_itr_num = 150`
（固定预算），前端也会等待挂起的关键帧请求。

⚠ **两处都要设**：frontend 读 `Training.single_thread`，backend 读 `Dataset.single_thread`。
TUM base 只在 `Training` 下有 → **本项目历史上后端从来是无条件自由跑的**。

这同时解释了项目里一条一直没被解释的旧观测（`p8_ego_control_maskoff_f3_st_hf.yaml`
注释里记着的）「同 seed 两次 ATE 15.72 vs 21.42 的非确定性」。

---

## 2. 已有证据（免费，不重跑）

**control 在 async 下是稳定崩的，n=3**。`p6_maskoff_prune_f3_st_hf.yaml` 与
`p8_ego_control_maskoff_f3_st_hf.yaml` 配置等价（只差一个 no-op 的 `ego_pose_oracle: false`），
所以 P6-FULLKERN-MASKFREE 那三个 seed 就是 control 的 n=3：

| control (3090, async) | seed0 36.09 / seed1 35.16 / seed2 35.52 |
|---|---|
| control (2060, async) | seed0 35.29 |

→ **缺陷可复现，不是运气**。control 不需要再跑。
→ 但 **oracle 只有 n=1**，所以「12.4×」目前是 n=1 对 n=3。

---

## 3. 批次组成（8 run）

分机原则：**async 臂放静机（2060，串行）**，因为它测的正是「无外部负载下的内在方差」，
放在被别人占着的 3090 上等于把要研究的混杂变量灌进去；**sync 臂放 3090**，
因为它按构造对负载不敏感，且能吃双卡并行。

### 2060（静、串行，5 run，~40min/run ≈ 3.5h）

| # | 臂 | config | seed |
|---|---|---|---|
| 1-2 | oracle async | `p8_ego_oracle_maskoff_f3_st_hf` | 1, 2 |
| 3-5 | fix async | `p8_ego_fix_maskoff_f3_st_hf` | 0, 1, 2 |

与已有的 2060 oracle/fix seed0 同机可比 → oracle n=3、fix n=4。
全部带 exp26 新加的 provenance 列（`ego_fit_applied` / `ego_reject` / `ego_explained_frac` …）。

### 3090（双卡，3 run，时长未知）

| # | 臂 | config | seed |
|---|---|---|---|
| 6 | control sync | `p8_sync_control_maskoff_f3_st_hf` | 0 |
| 7 | fix sync | `p8_sync_fix_maskoff_f3_st_hf` | 0 |
| 8 | fix sync | `p8_sync_fix_maskoff_f3_st_hf` | **1** ← 关键：async 下这个 seed 崩到 35.86 |

（oracle sync 视 6-8 结果再决定，不预排。）

⚠ sync 是**另一个工作点**（150 iters/KF + 无自由跑），其 ATE 与主表**不可比**，
只用于回答「关掉竞态后还崩不崩」。诊断专用，绝不入主表。

---

## 4. 冻结判据

### D1 — oracle 完整性（判 H-B）

- **oracle async n=3 全部 < 5cm** ⇒ 缺陷解释完整。12.4× 因果 claim 保留，
  改写为 n=3 对 n=3。
- **任一 oracle run ≥ 20cm** ⇒ 缺陷解释不完整，存在第二失效模式 ⇒
  **停止打磨修法，回到定位**。（这一条优先级高于 D2/D3：上界不成立时，
  讨论「修法逼近上界多少」没有意义。）
- 5-20cm 之间 ⇒ 判为 INDETERMINATE，补到 n=5 再判。

### D2 — 竞态（判 H-C）

- **sync control ≥ 20cm 且 sync fix 两 seed 均 < 5cm** ⇒ **H-C 成立**。
  双稳态是 async 竞态的产物，修法本身有效。
  行动：修法保留；主表必须诚实报 async 的 run-to-run 方差；
  「是否整表改 sync 重新基线」另立议题，**不在本批次决定**。
- **sync control < 5cm** ⇒ 崩溃需要竞态才发生。缺陷叙事要从「位姿误差被当成动态」
  单因，改写为「位姿误差 × 无界异步映射预算」的联合正反馈。
  这**不否定**缺陷存在，但改写 headline 的因果表述。
- **sync fix 仍有任一 ≥ 20cm** ⇒ H-C 否定，双稳态是方法内在的 ⇒ 走 D3。

### D3 — 护栏（判 H-A）

比较 fix async 的好 run（<5cm）与坏 run（≥20cm）的逐帧 `ego_fit_applied` / `ego_reject`：

- **坏 run 前 100 帧的 `ego_fit_applied` 率比好 run 低 ≥ 20 个百分点** ⇒
  护栏早期漏修 ⇒ 修法方向 = 早期帧放宽 / `min_explained_frac` 改帧自适应。
- **两者分布无实质差异（差 < 10 个百分点）** ⇒ 不是护栏问题，投影本身不足 ⇒
  需要更强修法（改 `robust_anomaly` 内部归一化，而不是后处理残差）。
- 10-20 个百分点之间 ⇒ INDETERMINATE，不据此改方法。

⚠ 若 fix async 5 个 run（含已有 2.99）**全部** < 5cm，D3 无坏 run 可比，
   记为 N/A，并把「3090 上那次 35.86」标注为待解释的单次异常（不删）。

### D4 — FPS↔ATE（观察性，不单独判决）

汇总所有 f3_st_hf fix run 的 (FPS, ATE)。**好 run 的 FPS 一致低于坏 run 且无交叉（n≥5）**
⇒ 支持 H-C。只与 D2 合读，**不单独作为判决依据**（FPS 与机器负载完全混杂）。

---

## 5. 反证条件（什么结果会让我们否定当前叙事）

- oracle n=3 里出现崩 ⇒ 「位姿误差是主因」被削弱，回定位。
- sync control 不崩 ⇒ 「单因缺陷」叙事被否定，改写为联合机制。
- fix 在 sync 与 async 下都随机双稳 ⇒ 修法 B 不可信赖，弃用，另找修法方向。

以上任一发生，**都不进入全序列重跑，不重出主表**。

---

## 6. 实测（2026-08-18 回填，判据未改）

| # | 臂 | 机器 | seed | ATE(cm) | 371 处翻倍 | 备注 |
|---|---|---|---|---|---|---|
| 1 | oracle async | 2060 | 1 | **37.34** ❌ | 是 | `ego_pose_oracle=1` 1077/1077 帧自证 |
| 2 | oracle async | 2060 | 2 | **34.66** ❌ | 是 | |
| 3 | fix async | 2060 | 0 | **33.70** ❌ | — | ⚠ exp25 同机同 config 同 seed 曾 = **2.99** ✅ |
| 4 | fix async | 2060 | 1 | **2.73** ✅ | 否 | ⚠ exp25 3090 同 seed 曾 = **35.86** ❌ |
| 5 | fix async | 2060 | 2 | 跑中 | | |
| 6 | control sync | 3090 | 0 | **3.394** ✅ | 否 | |
| 7 | fix sync | 3090 | 0 | **3.189** ✅ | 否 | 与 sync control 几乎相同 |
| 8 | fix sync | 3090 | 1 | 跑中 | | |
| 附 | **w≡1 async** | 3090 | 0 | **35.99** ❌ | 是 | 独立预注册 `exp26_w1_causal_prereg.md` |

### 判决

**D1（oracle 完整性）= 第二分支触发**：oracle n=3 中 2 个 ≥20cm（37.34 / 34.66）
⇒ **缺陷解释不完整**。exp25 的「control 35.29 → oracle 2.85，12.4×」是 n=1 对 n=1。
按冻结判据：**停止打磨修法 B，不进全序列重跑，不重出主表。**

**D2（竞态）= 第二分支触发**：**sync control = 3.394 < 5cm** ⇒ 崩溃需要 async 才发生。
⚠ **但 sync 同时改了两件事**：`iter_per_kf` 10 → 150（`mapping_itr_num`）**且**后端不再自由跑。
所以**不能读成「竞态是病因」**，更可能是**每关键帧的映射预算**。
分开二者需要另一个探针（async + 提高 `iter_per_kf`），**在分开之前不下这个结论**。

**D3（护栏）= N/A 且已被上游作废**：w≡1 臂证明去掉整个下权重也照样崩，
所以护栏是否漏修不再是有意义的问题。

**D4（FPS↔ATE）= 不成立**：2060 静机上同 config 同 seed 两次跑出 2.99 与 33.70
⇒ 结局是 **run-to-run 非确定**，既不是 seed 决定，也不是负载决定。
之前基于 FPS 的相关（0.279→2.10 / 0.572→35.86）是小样本巧合，**撤回**。

### 逃逸率汇总（async）

| 臂 | 逃逸 |
|---|---|
| control | **0 / 4** |
| w≡1 | **0 / 1** |
| oracle | 1 / 3 |
| fix | 3 / 5（seed2 未回） |
| sync control | 1 / 1 |
| sync fix | 1 / 1 |

⚠ **统计诚实**：control 0/4 vs oracle+fix 4/8，Fisher 精确检验 p≈0.09，
**在 α=0.05 下不显著**。禁止写「改 e_flow 提高逃逸率」——目前没有统计支持。
唯一清楚的信号是 **sync 侧 2/2 全活**。

### 尚缺的关键对照（本批未含）

**vanilla 在 async 下 n>1 从未测过。** 主表的 MonoGS 2.80cm 是单点。
若 vanilla 也双稳，则 f3_st_hf 的 async 不稳定是 **MonoGS 自身性质**，不是我们的回归，
整个「静态退化」的定性都要改写。**这是下一个必须先跑的 run。**
