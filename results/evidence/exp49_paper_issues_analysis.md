# exp49 论文问题分析与修复方案
**日期**: 2026-08-26  
**会话**: exp49  
**触发**: 用户发现论文 v2 六个潜在问题

---

## 问题清单与判决

### 1. 数据集泛化性（TUM+BONN vs Replica）
**状态**: ✅ 已诚实报告，无需修改

**事实**:
- 主表覆盖 18 sequences（8 BONN + 10 TUM）
- Replica 结果已在 §5.7 和 Limitation #3 报告为**负面**
  - office0: combined 3.82±4.58 vs vanilla 0.368±0.012（更差且不稳定）
  - room0: 双稳态
- 边界声明清晰："we recommend it only for sequences already known to contain dynamic content"

**判决**: 论文**已正确标注适用域边界**。Replica 上失败是诚实报告的限制，不是隐瞒的泛化性问题。

**可选改进**（非必需）: 在 §4 Experimental Protocol 的"18 RGB-D sequences"后加脚注：
> "Static sequences from Replica were also evaluated and show degradation with our combined configuration (Sec. 5.7, Limitation #3), confirming the method is designed for dynamic content."

---

### 2. Related Work 是否可缩减
**状态**: ✅ 可适度压缩

**当前结构**（~2页）:
- §2.1: 显式动态先验（7个方法：DynaSLAM/NGD/RGD/DG/BDGS/DAGS/DynaGSLAM）
- §2.2: 学习不确定性（1个方法：WildGS-SLAM）
- §2.3: 一致性而非类别（4个方法：Gassidy/DGS-SLAM/Dy3DGS/GARAD）
- §2.4: positioning（1段，不可删）

**压缩建议**:
- §2.1 从 7→4 个例子：
  - 保留 DynaSLAM（keypoint 时代代表）
  - 保留 RGD-SLAM（3DGS 且在主表中比较）
  - 保留 DG-SLAM（3DGS 代表，NeurIPS 2024）
  - 保留 NGD-SLAM（CPU-only 特例）
  - 删除 BDGS/DAGS/DynaGSLAM（三个 3DGS 例子只需要一个）
- §2.3 保持 4 个（这是**我们所属的 line**，必须充分 survey）
- 预期压缩空间：~0.4页

---

### 3. Fig2 位置"突兀" + 双栏疑问
**状态**: ✅ 设计正确，caption 可清理

**事实**:
- LNCS (`llncs.cls`) 是**单栏格式**（不存在双栏问题）
- fig2_mechanism.png 尺寸 10064×1691 = **5.95:1 极宽幅**
  - Panel a: 机制链（三盒子）
  - Panel b: 440 帧 timeline（需要横向展开）
- 当前 caption 包含 `\texttt{figures/fig2_mechanism.png}` 是**溯源标记**

**判决**:
- 图宽是**有意设计**（timeline 必须横向）
- 如果审稿人认为太扁，revision 时可拆成上下两行
- Caption 中的文件名可删除（保留 "Figure 2" + 图说明即可）

**建议修改** caption（body_v2.tex:162-163）:
```latex
\caption{\textbf{Figure 2}. \emph{Mechanism chain: two cues fuse into one Cauchy down-weight.} 
Panel (a) shows the three-box chain: ...}
```
删掉 `(\texttt{figures/fig2\_mechanism.png})`。

---

### 4. 1.4826 MAD 常数来源
**状态**: ✅ 标准统计常数，已正确使用

**原理**:
- MAD（Median Absolute Deviation）= median(|x - median(x)|)
- 对正态分布，MAD ≈ 0.6745σ
- **1.4826 = 1/0.6745**，用于将 MAD 转换为标准差尺度
- 公式 `σ̂ = 1.4826 × MAD` 是 **robust 标准差估计**（对离群值不敏感）

**代码验证**（5处使用，一致）:
- `utils/gtmc_mask.py:374`: `mad = float(np.median(np.abs(vals - med))) * 1.4826`
- `utils/dba_lite.py:181,328,572`: 同样实现

**论文中的用法**（body_v2.tex:138, 154）:
```
scale = max(1.4826·MAD, floor)
τ = median(d) + 1.4826·MAD(d) + ε
```

**判决**: 这是**统计学标准常数**，不是 tuning 参数，使用正确。

**可选补充**（如果审稿人质疑）:
在 τ 公式（Eq 3）后加脚注：
> "The constant 1.4826 is the standard scale factor for converting MAD to standard-deviation units under Gaussian assumption."

---

### 5. RGD 列缺失标准差
**状态**: ❌ **数据不一致 BUG，必须修复**

**问题根因**:
- `resources/02-baselines/baselines_result/RGD-SLAM/tracking_raw.csv` 包含 **3-seed 完整数据**
- 但 `make_fig4_main_results.py` **硬编码了单值**（只用均值）
- Table 1（body_v2.tex:253-274）也**只显示单值**

**正确数据**（见上方 python 输出）:
- f1_desk: 2.32±0.11（不是 2.32）
- f2_xyz: 1.71±0.07（不是 1.71）
- balloon: 2.45±0.22（不是 2.45）
- ... 全部 18 个序列

**修复方案**: 需要两步
1. 更新 `make_fig4_main_results.py` 数据元组（加 std 列）
2. 重新生成 fig4_main_results.{pdf,png,svg}
3. 更新 Table 1（body_v2.tex）RGD 列为 `mean±std` 格式

**标记**: 下一步需要修复（优先级**高**）

---

### 6. 参考文献 #5 和 #19 出版状态
**状态**: ⚠️ 需用户确认后修复

**当前状态**:
- **dgsslamkong**（引用顺序 #14，不是 #5）:
  ```bibtex
  @inproceedings{dgsslamkong,
    booktitle = {IEEE International Conference on Robotics and Automation (ICRA)},
    year      = {2025},
    note      = {arXiv:2411.10722. CrossRef confirms...}
  }
  ```
  - Note 说明 TCSVT 2026 的 DGS-SLAM (Jia et al.) 是**不同工作**
  - 如果 Kong 2024 **没有正式 proceedings**，应改为 `@misc` arXiv

- **ngdslam**（引用顺序 #3，不是 #19）:
  ```bibtex
  @misc{ngdslam,
    year   = {2025},
    eprint = {2405.07392},
    archivePrefix = {arXiv},
  }
  ```
  - 用户声称应为 **IROS 2025 proceedings**

**需要用户提供**:
1. Kong et al.: 是否只有 arXiv 2411.10722（year=2024），没有 ICRA 2025 正式录用？
2. Zhang et al.: 是否有 IROS 2025 正式页码（或仍为 arXiv）？

**待修复**: 用户确认出版信息后更新 `references.bib`

---

## 引用顺序校正
用户说的"第5篇"和"第19篇"是**出现顺序**，实际对应：
- 第5篇 = **rgdslam**（Pattern Recognition 2026，正确）
- 第14篇 = **dgsslamkong**（ICRA 2025?，待确认）
- 第3篇 = **ngdslam**（arXiv → IROS 2025?，待确认）

---

## 下一步行动清单

### 立即修复（本会话）
1. ✅ **修复 RGD 数据**（问题5）
   - 更新 `make_fig4_main_results.py`
   - 重新生成 Fig4
   - 更新 Table 1

### 需用户确认
2. ⏸ **参考文献更新**（问题6）
   - 等待用户提供 Kong/Zhang 正式出版信息

### 可选改进
3. ⭕ **压缩 Related Work**（问题2）
   - §2.1 从 7→4 个方法
   - 删除 BDGS/DAGS/DynaGSLAM 三段
4. ⭕ **清理 Fig2 caption**（问题3）
   - 删除 `\texttt{figures/fig2_mechanism.png}` 溯源标记

### 无需改动
5. ✅ **数据集泛化性**（问题1）- 已诚实报告
6. ✅ **1.4826 常数**（问题4）- 标准统计常数，正确

---

## 总结
- **1个必修bug**（RGD数据）
- **2个待确认**（Kong/Zhang参考文献）
- **2个可选优化**（Related Work压缩 + Fig2 caption清理）
- **2个无需改动**（数据集边界 + MAD常数）
