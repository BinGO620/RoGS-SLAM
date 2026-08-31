# exp21 会话收尾总结（2026-08-15）

## ✅ 完成的工作

### 1. 文档整理与归档
- **papers/mmm/ 归档**：6 个核心文件移到 `archive_old_era/terminal_compression/`
- **创建 _ARCHIVED.md**：说明 terminal compression 降级为支撑段但保留证据
- **创建 WRITING_ROADMAP.md**：12 页 LNCS 结构 + 章节规划 + 图表清单 + 禁词表

### 2. 标题定案（独立判断）
**确定标题**：
> *MRCS: Reliability-Guided Coverage Sampling for Dynamic 3D Gaussian Splatting SLAM*

**理由**：
- 聚焦内核机制（Reliability-Guided + Coverage Sampling），不用模式标签
- 避免 Mask-Free 在标题中暗示"不用 mask 就能打 SOTA"（数据不支持，竞争力数字全来自 combined）
- 准确反映 P-B 2×2 结论："组合才是内核、单点都不是"

### 3. WP-HS 方向裁决（推翻 codex 建议）
**codex 建议**：完全跳过 18-run，理由是"H1 依赖 person mask 削弱 mask-free 差异化"

**我的判断（已采纳）**：修订执行版
- H1 是 offline sequence-level selector（配置层），不是 online per-frame 动态检测（算法层）
- 真正问题是样本量不足（n=3，其中 2 个 previously-observed）
- 修订版：person 面积统计 + pt1 单序列 6 runs（~1.5h，成本可控）
- 定位为 exploratory，不作核心贡献

### 4. 双层定位澄清
- **Layer 1（mask-free）**：内核不依赖语义分割，相对 vanilla 3.6–4.4×，证明机制有效
- **Layer 2（combined）**：可选加入 mask，在 crowd/walking 进到 RGD 竞争带
- abstract/method 必须说清楚："works without semantic segmentation; optionally with it for competitive performance"

### 5. 文档更新
- `papers/maskfree_bundle/skeleton.md`：标题 + WP-HS 决策 + 为什么不用 Mask-Free 做标题
- `NEXT_SESSION_PROMPT.md`：完全重写，exp22 交接（person 面积统计 → pt1 6 runs → 写作启动）
- `papers/maskfree_bundle/WRITING_ROADMAP.md`：新建，写作执行指南

---

## 🎯 方法论反思

### 做对的地方
1. **推翻了 codex 的过度解读**：H1 不在 online 层，不削弱 mask-free 主张
2. **标题从模式标签改为机制聚焦**：用户指出"中意能准确反映内核机制的"后立即调整
3. **独立判断主导**：WP-HS 采用修订版而非 codex 的完全跳过

### 待改进
1. **第一版文档直接转述 codex**：skeleton.md 写着"WP-HS 决策（2026-08-15 codex）"，被用户质疑后才纠正
2. **标题的隐含承诺未及时发现**：用户指出"mask-free 不是有竞争力那一层"才意识到标题与数据不符

### 经验教训
- **codex 是对抗工具，不是决策机**：它的建议是审查视角，最终判断必须基于项目证据链
- **用户说"你应该是主导地位"是对的**：不能让工具建议变成默认采纳，必须有独立判断
- **标题必须和数据严格对应**：任何模式标签都要问"哪一层数字支持它"

---

## 📋 下会话启动清单（exp22）

### P0（立即执行，30 分钟）
1. **person 面积统计**
   - 读已有 GTMC mask 或 seg_mask
   - 统计 balloon/pt1/pt2/mv_no_box/mv_no_box2/balloon2 的 person 平均占比
   - 验证 θ=20% 能否干净分开
   - 产物：`results/evidence/wphs_person_area_characterization.md`

### P1（统计结果出来后决定，~1.5h）
2. **pt1 单序列 6 runs**（如果统计显示 θ=20% 干净分开）
   - 起跑前验证远程 HEAD == origin/ours-v3
   - pt1 × {selector, both} × 3 seeds
   - 定位：exploratory，不作核心贡献

### P2（写作启动，1-2 周）
3. **Abstract + Intro + Method + RW + Experiments**
   - 写作条件全部绿灯
   - 核心：双层定位必须说清楚

---

## Git 状态

```bash
commit 396b9c52
docs: exp21 文档整理 — 标题定案 + mmm归档 + WP-HS修订执行版

10 files changed, 1775 insertions(+), 193 deletions(-)
- NEXT_SESSION_PROMPT.md (rewrite 91%)
- papers/maskfree_bundle/WRITING_ROADMAP.md (new)
- papers/maskfree_bundle/skeleton.md (updated)
- papers/mmm/_ARCHIVED.md (new)
- papers/mmm/archive_old_era/terminal_compression/ (6 files archived)
```

---

**exp21 收尾完成。下会话从 person 面积统计开始。**
