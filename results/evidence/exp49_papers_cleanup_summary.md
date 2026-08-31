# exp49 papers/maskfree_bundle 目录梳理总结

**日期**: 2026-08-27  
**会话**: exp49  
**HEAD**: 待补充

---

## 🎯 任务目标

用户反馈：`papers/maskfree_bundle/` 目录"太多了，适当精简"。

---

## 📋 执行的整理工作

### 1. 删除临时文件

| 文件 | 大小 | 操作 | 理由 |
|------|------|------|------|
| `HANDOFF_TO_MULTIMODAL.txt` | 3.7KB | 删除 | 验证任务已完成，不再需要 |
| `fix_references_exp49.sh` | 2.3KB | 删除 | 已确认参考文献无需修改 |
| `FIXES_exp49.md` | 12KB | 移动到 `results/evidence/` | 归档为证据文档 |

### 2. 新增核心文档

**README.md (3.9KB)**
- 目录结构说明
- 工作流程（修改图片/编译论文/验证图片）
- 图片编号映射表（论文编号 vs 文件名）
- 相关文档索引
- 待清理项说明

### 3. 更新状态文件

**STATUS.txt (1.6KB)**
- 简化为快速状态查看
- 核心文件清单
- 论文完成度
- 最近修改记录（exp49）

---

## 📁 整理后的目录结构

### 根目录（5个核心文件）

```
papers/maskfree_bundle/
├── manuscript.md          (61KB)  - 论文正文 Markdown 源文件
├── supplementary.md       (20KB)  - 补充材料
├── README.md             (3.9KB) - 📌 新增：目录说明文档
├── STATUS.txt            (1.6KB) - ✏️ 更新：快速状态
└── WRITING_ROADMAP.md    (34KB)  - 写作路线图（claim framing）
```

### 子目录

```
latex/                     - LaTeX 编译目录
  ├── main_v2.pdf          (1022KB) - 编译产物
  ├── body_v2.tex          - 正文内容
  ├── references.bib       - 参考文献
  └── compile_v2.sh        - 编译脚本

figures/                   - 图片目录（7图×3格式）
  ├── make_fig*.py         - 7个 Python 绘图脚本
  └── fig*.{pdf,svg,png}   - 21个生成的图片

archive/                   - 历史版本归档
  ├── manuscript_v0.md     (66KB) - 初稿
  ├── manuscript_v1.md     (57KB) - 第一版修订
  └── skeleton_exp21.md    (30KB) - 早期骨架
```

---

## ✨ 整理后的优势

### 1. 对新会话更友好
- 打开 `README.md` 即可快速了解整个目录
- 清楚的文件用途说明和工作流程
- 不用翻看多个临时文件

### 2. 结构更清晰
- 根目录只保留5个核心文档
- 临时文件全部清理
- 历史版本在 `archive/` 归档
- 证据文档在 `results/evidence/`

### 3. 易于维护
- `STATUS.txt` - 快速状态（1页纸）
- `README.md` - 详细说明（结构+流程）
- `WRITING_ROADMAP.md` - 写作指导（claim framing）

---

## 📊 多模态模型的图片修改经验（已吸收）

用户让多模态模型修改了图片，并总结了7条经验，已记录在 `NEXT_SESSION_PROMPT.md`：

1. **箭头端点必须由几何边界决定** - 不靠反复试小数，先确定边界再计算端点
2. **"横平竖直"不是所有流程图的目标** - 发散箭头用斜线更清楚
3. **面板标号应在最终页面坐标中对齐** - 使用 `fig.text` 统一坐标，避免 axes-relative
4. **必须同时检查源图和论文PDF** - 5步验证流程（脚本→PNG→编译→渲染→检查）
5. **学术图优先使用真实、可追溯、清晰的证据** - 不用模拟数据、截图
6. **注释的取舍看解释价值** - 不看是否"零散"，看能否回答4个问题
7. **一次只改一个布局变量组** - 避免混淆回归来源

这些经验融入了 `NEXT_SESSION_PROMPT.md`（维护指南），下次修改图片时会遵循。

---

## 🎯 当前论文状态

**版本**: v2  
**进度**: 主体完成，图片多轮打磨完成  
**状态**: 等待最终验证反馈（如有）→ 准备投稿

**核心指标**:
- ✅ 正文 22 页（manuscript.md 61KB）
- ✅ 补充材料 20KB
- ✅ 7张图全部打磨完成（21个文件）
- ✅ 22条参考文献验证通过
- ✅ PDF 编译成功（1022KB）

---

## 📝 Git 记录

**删除的文件**:
- `papers/maskfree_bundle/HANDOFF_TO_MULTIMODAL.txt`
- `papers/maskfree_bundle/fix_references_exp49.sh`

**移动的文件**:
- `papers/maskfree_bundle/FIXES_exp49.md` → `results/evidence/FIXES_exp49.md`

**新增的文件**:
- `papers/maskfree_bundle/README.md`

**修改的文件**:
- `papers/maskfree_bundle/STATUS.txt`

**Commit message**:
```
exp49 papers目录梳理: 删除临时文件+新增README+更新STATUS
```

---

## 🔍 相关文档

- **图片验证指南**: `/data/monogs-ours/NEXT_SESSION_PROMPT.md`
- **项目主文档**: `/data/monogs-ours/CLAUDE.md`
- **论文目录说明**: `papers/maskfree_bundle/README.md`
- **快速状态**: `papers/maskfree_bundle/STATUS.txt`
- **写作路线图**: `papers/maskfree_bundle/WRITING_ROADMAP.md`

---

最后更新: 2026-08-27 (exp49)
