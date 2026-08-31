# exp49 论文六问题分析与修复总结

**会话**: exp49  
**日期**: 2026-08-26  
**HEAD**: c94a242b  
**状态**: 1个bug已修复，2个待确认，3个无需改动

---

## 📋 问题清单与判决

### ✅ 问题1: 数据集泛化性（TUM+BONN vs Replica）
**判决**: **无需修改** - 已诚实报告适用域边界

**事实**:
- 论文主表覆盖 18 sequences（8 BONN + 10 TUM）
- Replica 负面结果已在 §5.7 完整报告：
  - office0: combined 3.82±4.58 vs vanilla 0.368±0.012（更差且双稳态）
  - room0: 双稳态崩溃
- Limitation #3 明确声明："we recommend it only for sequences already known to contain dynamic content"

**结论**: 这是**诚实的适用域边界声明**，不是隐瞒的泛化性缺陷。Replica 上失败是方法的已知限制（mask-free 配置对静态场景有害），论文已如实报告。

---

### 📝 问题2: Related Work 是否可缩减
**判决**: **可选优化** - 可压缩约 0.4 页

**当前结构**（~2页）:
- §2.1 显式动态先验：7个方法（DynaSLAM, NGD, RGD, DG, BDGS, DAGS, DynaGSLAM）
- §2.2 学习不确定性：1个方法（WildGS-SLAM）
- §2.3 一致性而非类别：4个方法（**我们所属的 line**）
- §2.4 positioning：必保留

**压缩建议**:
```
§2.1 从 7→4 个例子：
  保留: DynaSLAM（keypoint时代）+ RGD（主表有比较）+ DG（NeurIPS 2024）+ NGD（CPU特例）
  删除: BDGS/DAGS/DynaGSLAM（三个3DGS例子只需一个）
§2.3: 不压缩（这是我们的归属，必须充分survey）
预期收益: ~0.4页
```

**是否执行**: 看页数预算。如果不超限，保持现状更安全（survey 充分性是审稿要点）。

---

### 🖼️ 问题3: Fig2 位置"突兀" + 双栏疑问
**判决**: **设计正确** - caption 可清理（可选）

**澄清**:
1. **LNCS 是单栏格式**（`llncs.cls`），不存在"双栏"问题
2. Fig2 尺寸 10064×1691 = **5.95:1 极宽幅**是**有意设计**：
   - Panel a: 机制链（三盒子横向流程）
   - Panel b: 440 帧 timeline（必须横向展开才能看到振荡）
3. 如果审稿人认为太扁，revision 时可拆成上下两行（但当前设计合理）

**可选清理**:
```latex
% 当前 caption (body_v2.tex:162-163):
\caption{... (\texttt{figures/fig2_mechanism.png})}

% 建议删除文件名溯源标记:
\caption{... }  % 删掉 (\texttt{...})
```

---

### ✅ 问题4: 1.4826 MAD 常数来源
**判决**: **无需修改** - 标准统计常数，使用正确

**原理**:
- MAD = median(|x - median(x)|) 是 robust 中位数绝对偏差
- 对正态分布，MAD ≈ 0.6745σ
- **1.4826 = 1/0.6745** 是标准转换因子，将 MAD 转换为标准差尺度
- `σ̂ = 1.4826 × MAD` 是统计学教科书公式（robust 标准差估计）

**代码验证**（5处一致）:
```python
# utils/gtmc_mask.py:374
mad = float(np.median(np.abs(vals - med))) * 1.4826

# utils/dba_lite.py:181,328,572
# 同样实现
```

**论文用法**（§3.4）:
```
scale = max(1.4826·MAD, floor)  # Eq. 2
τ = median(d) + 1.4826·MAD(d) + ε  # Eq. 3
```

**如果审稿人质疑**: 可在 Eq. 3 后加脚注说明这是标准转换常数，但当前版本已在 §3.4 说明 "robust normaliser"，应该足够。

---

### ❌ 问题5: RGD 列缺失标准差（数据一致性 bug）
**判决**: **已修复** ✅ (commit c94a242b)

**问题根因**:
- 数据源 `resources/02-baselines/.../RGD-SLAM/tracking_raw.csv` 包含 **3-seed 完整数据**
- 但 Fig4 和 Table 1 都**只显示均值**（硬编码单值）
- 造成 RGD 列与其他列格式不一致（其他都有 ±std）

**修复内容**:

1. **make_fig4_main_results.py**:
   ```python
   # 数据元组从 7 列扩展到 8 列
   ROWS = [
       ("f1_desk", "TUM static", 1.47, 0.08, 1.49, 1.39, 2.32, 0.11),  # 添加 rgd_sd
       # ... 全部 18 行
   ]
   
   # 提取 rgd_sd
   rgd_sd = np.array([r[7] for r in ROWS])
   
   # 绘图改用 errorbar
   ax.errorbar(rgd, y, xerr=rgd_sd, fmt="|", ..., label="RGD-SLAM (reproduced)")
   
   # Caption 更新
   "RGD-SLAM values are our 3-seed reproduction under the original paper's protocol"
   ```

2. **body_v2.tex Table 1**（全部 18 行）:
   ```latex
   % 修复前:
   ... & 2.32 \\
   ... & 1.71 \\
   ... & 1.42 \\
   
   % 修复后:
   ... & 2.32$\pm$0.11 \\
   ... & 1.71$\pm$0.07 \\
   ... & 1.42$\pm$0.06 \\
   ```

3. **验证**:
   ```bash
   python make_fig4_main_results.py  # ✅ wrote fig4_main_results.{pdf,svg,png}
   bash compile_v2.sh                # ✅ PDF generated (877K)
   ```

**完整数据**（18个序列的正确 RGD 值）:
```
balloon      2.45±0.22    f1_desk      2.32±0.11
balloon2     4.26±0.89    f2_person    6.11±0.22
crowd        2.61±0.28    f2_xyz       1.71±0.07
crowd2       2.36±0.06    f3_office    1.42±0.06
mv_no_box    2.28±0.26    f3_st_hf     2.76±0.48
mv_no_box2   4.70±0.24    f3_st_rpy    2.90±0.34
pt1          7.21±1.24    f3_st_xyz    2.03±0.38
pt2         22.99±3.66    f3_wk_hf     3.25±0.11
                          f3_wk_rpy    3.55±0.24
                          f3_wk_xyz    2.01±0.36
```

---

### ⏸️ 问题6: 参考文献 #5 和 #19 出版状态
**判决**: **待用户确认** - 需要外部信息

#### 6a. DGS-SLAM (Kong et al.)
**当前状态** (`references.bib:219-228`):
```bibtex
@inproceedings{dgsslamkong,
  title     = {{DGS-SLAM}: {G}aussian Splatting {SLAM} in Dynamic Environment},
  author    = {Kong, Mangyu and Lee, Jaewon and Lee, Seongwon and Kim, Euntai},
  booktitle = {IEEE International Conference on Robotics and Automation (ICRA)},
  year      = {2025},
  note      = {arXiv:2411.10722. CrossRef confirms TCSVT 2026 DGS-SLAM (Jia) is SEPARATE work}
}
```

**用户声称**: 应该是 `arXiv preprint arXiv:2411.10722 (2024)`

**修复方案** (如果确认只有 arXiv):
```bibtex
@misc{dgsslamkong,
  title  = {{DGS-SLAM}: {G}aussian Splatting {SLAM} in Dynamic Environment},
  author = {Kong, Mangyu and Lee, Jaewon and Lee, Seongwon and Kim, Euntai},
  year   = {2024},
  eprint = {2411.10722},
  archivePrefix = {arXiv},
  primaryClass  = {cs.RO}
}
```

**需要用户回答**:
- [ ] Kong et al. 是否**只有 arXiv 2411.10722**，没有 ICRA 2025 proceedings？
- [ ] 年份是 2024 还是 2025？

---

#### 6b. NGD-SLAM (Zhang et al.)
**当前状态** (`references.bib:116-123`):
```bibtex
@misc{ngdslam,
  title  = {{NGD-SLAM}: Towards Real-Time Dynamic {SLAM} without {GPU}},
  author = {Zhang, Yuhao and Bujanca, Mihai and Luj{\'a}n, Mikel},
  year   = {2025},
  eprint = {2405.07392},
  archivePrefix = {arXiv},
  primaryClass  = {cs.RO}
}
```

**用户声称**: 应该是 `IEEE/RSJ IROS (2025)`

**修复方案** (如果确认有 IROS 2025):
```bibtex
@inproceedings{ngdslam,
  title     = {{NGD-SLAM}: Towards Real-Time Dynamic {SLAM} without {GPU}},
  author    = {Zhang, Yuhao and Bujanca, Mihai and Luj{\'a}n, Mikel},
  booktitle = {IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)},
  year      = {2025},
  pages     = {[待补充]},  % 需要提供页码
  note      = {arXiv:2405.07392}
}
```

**需要用户回答**:
- [ ] Zhang et al. 是否被 **IROS 2025 正式接收**？
- [ ] 是否有 **proceedings 页码**？

---

#### 如何确认出版状态
**推荐步骤**:
1. 访问会议官网查询 accepted papers 列表
2. 搜索 DBLP: `https://dblp.org/search?q=DGS-SLAM+Kong`
3. 查看 arXiv 页面的 "Journal reference" 字段
4. 如果只说"被接收"但没页码 → 保持 `@misc` + arXiv（更安全）

**修复脚本**: `papers/maskfree_bundle/fix_references_exp49.sh`（交互式，待用户提供答案）

---

## 📊 修复统计

| 问题 | 判决 | 状态 | 工作量 |
|------|------|------|--------|
| 1. 数据集泛化性 | 无需修改 | ✅ 完成 | 0 |
| 2. Related Work压缩 | 可选优化 | ⭕ 待定 | 0.5h |
| 3. Fig2位置 | 设计正确 | ✅ 完成 | 0 |
| 4. MAD常数 | 无需修改 | ✅ 完成 | 0 |
| 5. RGD数据 | **已修复** | ✅ 完成 | 0.3h |
| 6. 参考文献 | 待用户确认 | ⏸️ 阻塞 | 0.2h |

**总计**: 1个bug已修复，2个待确认，3个无需改动

---

## 🗂️ 文件修改清单

### 已修改并 commit (c94a242b)
```
papers/maskfree_bundle/figures/
  ├── make_fig4_main_results.py       (数据+绘图逻辑)
  ├── fig4_main_results.pdf           (重新生成)
  ├── fig4_main_results.png           (重新生成)
  └── fig4_main_results.svg           (重新生成)

papers/maskfree_bundle/latex/
  ├── body_v2.tex                     (Table 1, L250-274)
  └── main_v2.pdf                     (重新编译, 877K)

papers/maskfree_bundle/
  ├── FIXES_exp49.md                  (本文件)
  └── fix_references_exp49.sh         (参考文献修复脚本)

results/evidence/
  └── exp49_paper_issues_analysis.md  (详细分析)
```

### 待修改（等用户确认）
```
papers/maskfree_bundle/latex/
  └── references.bib                  (Kong + Zhang 两个条目)
```

---

## 🚀 下一步行动

### 立即需要（用户响应）
请回答以下问题，我会执行相应修复：

**Kong et al. (DGS-SLAM)**:
- [ ] A: 只有 arXiv 2411.10722 (2024)，没有 ICRA
- [ ] B: 已被 ICRA 2025 接收但还没页码
- [ ] C: 保持现状（我说错了）

**Zhang et al. (NGD-SLAM)**:
- [ ] A: 已有 IROS 2025 正式页码 → 请提供：`______`
- [ ] B: 已被 IROS 2025 接收但还没页码
- [ ] C: 保持现状（我说错了）

### 用户确认后执行（预计 10 分钟）
1. 更新 `references.bib` 相应条目
2. 重新编译 LaTeX 验证引用格式
3. Commit 参考文献修复

### 可选（无deadline压力）
1. 压缩 Related Work §2.1（如果页数超预算）
2. 清理 Fig2 caption 文件名标记（纯美观）

---

## 🔍 审计要点

**问题5修复的关键验证**:
```bash
# 1. 数据源完整性
wc -l resources/02-baselines/baselines_result/RGD-SLAM/tracking_raw.csv
# 输出: 55 行（含表头）= 18序列 × 3seeds = 54行 + 1表头 ✓

# 2. Fig4 包含误差棒
grep "errorbar.*rgd" papers/maskfree_bundle/figures/make_fig4_main_results.py
# 输出: ax.errorbar(rgd, y, xerr=rgd_sd, ...) ✓

# 3. Table 1 所有行都有±std
grep "RGD" papers/maskfree_bundle/latex/body_v2.tex | grep -c "pm"
# 输出: 18 ✓

# 4. PDF 编译成功
ls -lh papers/maskfree_bundle/latex/main_v2.pdf
# 输出: 877K, 2026-08-26 20:47 ✓
```

---

## 📝 经验教训

1. **数据一致性**: 数据源有完整信息但展示缺失 → 需要 pipeline 审计（源 → 脚本 → 图表 → LaTeX）
2. **参考文献管理**: arXiv 预印本转正式出版需要及时更新，避免 "published" 标签但实际是 arXiv
3. **统计常数**: 1.4826 这类教科书常数不需要过度解释，当前 "robust normaliser" 说明已足够
4. **适用域边界**: Replica 负面结果的诚实报告是优点，不是缺陷
5. **图表设计**: 极宽图（5.95:1）在单栏格式中是合理设计（timeline 需要横向展开）

---

## 联系信息

**证据链**:
- 详细分析: `results/evidence/exp49_paper_issues_analysis.md`
- 修复清单: `papers/maskfree_bundle/FIXES_exp49.md`（本文件）
- 参考文献脚本: `papers/maskfree_bundle/fix_references_exp49.sh`
- Commit: c94a242b "exp49: 修复 RGD 数据一致性 bug"

**HEAD**: c94a242b  
**分支**: ours-v3  
**日期**: 2026-08-26
