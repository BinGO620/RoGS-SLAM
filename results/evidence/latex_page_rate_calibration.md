# 版面换算率的实测校准（LaTeX 实编译，2026-08-25，exp46）

> **起因**：全项目的版面账（`WRITING_ROADMAP.md` §四-A、`scripts/count_manuscript_pages.py`）
> 建立在 **520 words/页** 这个**从未对编译核对过**的假设上，且把 title+abstract 记作 **0.50 页**。
> v1 压缩后我在 §四-A 自己写下了告警"先复核换算率再继续削，否则可能白削一遍"。本文件执行该复核。
>
> **判决：520 偏乐观约 9%（实测 ~477 md-words/页），且 front matter 少算了 ~1.0 页。
> v1 实测 17 页（仅含 1/3 张图），补齐 Fig2/Fig3 后约 17.65 页 ⇒ v2 要削 ~5.65 页，不是 4.35。**

## 0. 装置

| 项 | 值 |
|---|---|
| 引擎 | `tectonic 0.17.0`（conda env `tex`），XeTeX 后端 |
| 文档类 | `llncs.cls` 2024/01/29 v2.24，`[runningheads]`，10pt |
| 正文源 | `papers/maskfree_bundle/manuscript.md`（v1）经 `scripts/md2latex_manuscript.py` 生成 `latex/body_v1.tex` |
| 驱动 | `latex/main_v1.tex`（含 200 词占位 abstract + keywords；**无** bibliography） |
| 图 | Fig1 用 3.2 cm 灰条占位；**Fig2/Fig3 未入 markdown，故本次未计** |
| 表 | 5 张，`\footnotesize` + `booktabs` |
| 页数读法 | `main_*.log` 的 `Output written on ... (N pages)` |

**⚠ 本次编译缺什么**（读数时必须扣除/补上）：Fig2（0.22 页）、Fig3（0.31 页）及其 caption、
参考文献（LNCS 口径在 12 页正文之外，不占正文额度）。

## 1. 四点标定（不是两点）

只用"全长 vs 半长"两点就能解出斜率与截距，但**两点必然完美拟合**——这正是本会话
`rpe_stratification_rule_test.md` 判据 #26 的同一个陷阱。故取 **4 个长度**做最小二乘并看残差：

| 可见词数（LaTeX） | 实测页数 | 拟合预测 | 残差 |
|---:|---:|---:|---:|
| 2011 | 6 | 5.92 | +0.08 |
| 3397 | 9 | 8.99 | +0.01 |
| 4859 | 12 | 12.22 | −0.22 |
| 6503 | 16 | 15.86 | +0.14 |

**拟合结果**：斜率 ⇒ **452.1 可见词/页**；截距 ⇒ **1.48 页**固定开销。
残差全在 ±0.22 页内 ⇒ 线性模型成立（相邻点的边际率 462 / 487 / 411，散布来自
**分页量化**而非模型误差）。

## 2. 换算到项目用的单位（markdown 词）

`count_manuscript_pages.py` 数的是 **markdown 正文词**。v1 = §1–§7 共 **7204** 词
（+ 图 caption 109 词）。全文实编译 = **17 页**。

扣掉固定开销 1.48 页与 Fig1 灰条面积（3.2 cm / 19.3 cm ≈ 0.17 页 + 浮动间距 ≈ 0.19）：

> **R = 7313 / (17 − 1.48 − 0.19) = 7313 / 15.33 ≈ 477 markdown 词/页**

| 常数 | 旧假设 | **实测** | 差 |
|---|---:|---:|---|
| 正文换算率 | 520 词/页 | **≈477 词/页** | 旧值**乐观 9%** |
| front matter（title+abstract+keywords） | 0.50 页 | **≈1.48 页** | 旧值**少算 ~1.0 页** |
| 浮动体（本次 5 表 + 1 图占位） | 2.0 页（原计 7 个） | **1.0 页** | 表比预想省（`\footnotesize`）|

**两处误差方向相反但不抵消**：换算率偏乐观 −0.6 页、front matter 少算 +1.0 页
⇒ 净 **+0.65 页**，加上缺的两张图 ⇒ 旧账把 v1 低估了约 1.3 页。

## 3. 对页数账的直接后果

| | 旧模型预测 | **实测/校准** |
|---|---:|---:|
| v1 全文（现状，1/3 张图） | 16.35 | **17.0** |
| v1 补齐 Fig2+Fig3+caption | — | **≈17.65** |
| v2 目标 | 12.0 | 12.0 |
| **v2 仍需削** | 4.35 | **≈5.65** |

⇒ **§四-A 的"须削 4.35 页"低估了 1.3 页**。v2 的削减量按 **5.65** 规划。

**但方向性结论没变**：v1 压缩本身没有白做（v0 若按实测率约 20.5 页，v1 17.0 页，
仍是实打实的 −3.5 页），只是 v2 的工作量比记的大。

## 4. 意外收获：表比预想便宜、front matter 比预想贵

- 5 张表（`\footnotesize`）+ 1 张图占位 **合计仅 1.0 页**，而旧账给 7 个浮动体留了 2.0 页。
  ⇒ **v2 不必急着合并表格**；真正的大头在 front matter 与正文散文。
- front matter 实测 1.48 页 vs 旧账 0.50。LNCS 的 title 块 + 200 词 abstract + keywords
  比"半页"贵得多。⇒ abstract 写到 200 词上限时要知道它**真的**吃掉 ~1.5 页里的一大半。

## 5. 自限

- **本次编译无参考文献**。LNCS 口径是"12 页正文 + 2 页引用"，引用不占正文额度，故不影响结论；
  但若目标 venue 把引用计入正文，本账要重算。
- **Fig2/Fig3 未入编译**（它们不在 markdown 里，只被正文引用）⇒ 17.65 是**推算**，不是实测。
  真正定稿前应把三张图都放进 `body_v1.tex` 再编一次。
- `md2latex_manuscript.py` 是**为本文档定制**的转换器，不是通用 markdown 实现；
  它对表格用 `\footnotesize`、对图用灰条占位。换排版参数会改变本文件的所有数字。
- 相邻点边际率散布 411–487 ⇒ 单次测量的分页量化误差约 **±8%**（±1.2 页 @17 页）。
  故"17 页"应读作 **17 ± 1**，不要拿它做半页级的决策。
- 4 点标定仍是**同一份文档的前缀**，不是四份独立文档；若某节的排版特征（表密度、公式）
  与全文差异大，局部率会偏离。

## 6. 复现

```bash
conda run -n monogs-ours python scripts/md2latex_manuscript.py \
    papers/maskfree_bundle/manuscript.md --out papers/maskfree_bundle/latex/body_v1.tex
cd papers/maskfree_bundle/latex && conda run -n tex tectonic --keep-logs main_v1.tex
grep -a "Output written" main_v1.log
```

---

## 7. 补编：三张图全部入编译（2026-08-25 同日）

§5 说过"17.65 是**推算**不是实测，定稿前三张图都要进去再编一次"。已执行。

**改动**：Fig2 从 `results/evidence/mechanism_figure_paper.png` 移入
`papers/maskfree_bundle/figures/fig2_mechanism.png`（论文资产不该住在证据目录里）；
Fig2/Fig3 的 caption 与 float 写入 markdown（分别落在 §3.4 末与 §5.2 表后）；
转换器改为**按 caption 里点名的文件路径插入真实图**（`--figdir`），不再用灰条占位。

**实测：`main_v1.tex` = 18 页**（三张图齐、无参考文献）。推算 17.65，实测 18 ⇒
偏低 0.35，落在 §5 声明的 ±1 量化带内。

| | 值 |
|---|---:|
| v1 实测（三图齐、无 bib） | **18 页** |
| v2 目标 | 12 |
| **v2 需削** | **≈6 页** |

模型复核（校准后的 `count_manuscript_pages.py`）：
散文 15.16 + caption 0.74 + front matter 1.48 + 图面积 0.82 = **18.20**，实测 18 ⇒ 差 0.2。

### 7.1 ⚠ 这次编译抓到一个会改变论文内容的静默错误

XeTeX **静默丢弃**它字体里没有的字符。本次首编译的 log 里有
`Missing character: There is no − (U+2212)` **共 8 处** —— 即正文里所有
Unicode 减号被**直接删掉**：`−0.182` 会印成 `0.182`。

**这恰好命中本文最承重的负号**：§5.2 的 Δ_K(balloon) = **−0.182**（"覆盖在混合 mover 上有害"）
是 F1 的核心，符号丢了整句话就反了。同批还有 Δ_R 的两个负值、ATE −1.4157、coherent_amp −0.0248。

**处置**：
1. 转换器补映射 U+2212 → `$-$`（另补 `§`→`\S`、`·`→`$\cdot$`、`÷`→`$\div$`、
   代码跨度内的 `·`→`\textperiodcentered`）。
2. **加了一道门**：转换后若还有任何非 ASCII 字符，**默认直接报错退出**
   （`--allow-unrepresentable` 才降级为警告）。这道门当场又抓出 3 个字符（§ / · / ÷）。
   理由：一个会静默改数字的构建，比没有构建更糟。

**判据（可复用）**：**排版工具链的"静默降级"和实验代码的静默降级同等危险。**
本项目已有两次同型事故 —— `ReliabilitySignal` 缺 flow 时静默跳过（臂标写着 L1 实跑 L0）、
`grep -c || echo 0` 让门不再比数据。处理方式相同：**把静默失败改成硬失败**。

### 7.2 顺带修掉的排版缺陷（都不改数字，只改可读性）

| 问题 | 症状 | 处置 |
|---|---|---|
| 6 列因子表溢出 | Overfull 90.9pt | ≥6 列改 `\scriptsize` + 收紧 `tabcolsep`；表头的 (object)/(person) 标注移进导言句 |
| §5.5 分组表溢出 | Overfull **218pt**（一格塞 9 个序列名） | 长单元格列改 `p{}` 自动换行（按其他列估宽算余量） |
| `Δ_K` 印成 `Δ\_K` | 下标变成文本下划线 | 补 `Δ\_X` → `$\Delta_X$`（注意 `_escape()` 先跑，模式要匹配已转义的下划线）|
| 竞品引文两端都是右引号 | LaTeX 里裸 `"` 两端同形 | 直引号成对映射为 ``` `` '' ``` |
| 长 math 撑破行 | Overfull 39.6pt | `$N = \text{ATE(...)}/\text{ATE(...)}$` 改成可断行的散文式定义 |

最终 log：**无 `Float too large`**，最大 Overfull 降到 **14.95pt**（约 5 mm，justified 正文常态）。

### 7.3 本次仍未做

- **无参考文献**（LNCS 口径在 12 页正文之外；若目标 venue 计入正文，本账要重算）。
- abstract 是 200 词**占位文本**（提到 `WRITING_ROADMAP.md`），定稿要替换为真 abstract；
  长度已按上限计，故页数账不受影响。
- 剩余 14.95pt 溢出来自不可断的 `\texttt{}` 长标识符，属定稿期润饰。

---

## 8. 真 abstract 入编译（2026-08-25 同日）

§7 说"abstract 是占位文本，定稿要替换"。已执行（203 词）。

**改动**：main_v1.tex 的 abstract 从"Placeholder abstract sized to the 200-word..."
替换为根据当前事实从头写成的真 abstract（6 要素：问题+数值、现有方案不足、我们的做法、
F1 regime-dependent、F2 信息不够、F3 variance-bias + 边界诚实）。roadmap §一 的 abstract
要素清单有 3 项在本会话中作废（组件列表 vs F1/F2/F3；mv_no_box 倍数禁引；pt1 阈值 2.5 误分 4 个）。

abstract 的每一句都 check 过证据：
- balloon 39.32±1.01、crowd2 147.5±39.0（headline_ratio_recompute.md 行 22/1）
- 静态 ~1.5 cm（f1_desk/f2_xyz/f3_office 平均 1.59）
- 120 run = 8×5×3（wpa_reliability_contribution.md）
- 0/5 序列三者全正（roadmap §零）
- Δ_K(balloon) = −0.182（make_fig3_regime_split.py 行 55）
- pt2 naive 0.90×（wpb_flowmask_verdict.md）

**实测：仍 18 页**（三图齐，真 abstract，无参考文献）。前后零变化 ⇒ 1.48 页的 front matter
估算包容了 abstract 从占位（200 词但提到 WRITING_ROADMAP.md）到真实（203 词纯正文）的替换。

