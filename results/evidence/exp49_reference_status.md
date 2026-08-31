# exp49 参考文献状态分析

## 问题6：Kong 和 Zhang 两篇文献出版状态

用户报告：
- Kong et al. (DGS-SLAM): 应该是 arXiv 2024（不是 ICRA 2025）
- Zhang et al. (NGD-SLAM): 应该是 IROS 2025（不是 arXiv 2025）

---

## 当前 BibTeX 状态

### Zhang et al. (NGD-SLAM)
```bibtex
@inproceedings{ngdslam,
  title     = {{NGD-SLAM}: Towards Real-Time Dynamic {SLAM} without {GPU}},
  author    = {Zhang, Yuhao and Bujanca, Mihai and Luj{\'a}n, Mikel},
  booktitle = {IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)},
  year      = {2025},
  pages     = {3467--3473},
  doi       = {10.1109/IROS60139.2025.11246202},
  note      = {arXiv:2405.07392}
}
```

**判决**: ✅ **已经是 IROS 2025**，有完整页码和 DOI！
- 用户说"应该是 IROS 2025" → 当前就是 IROS 2025
- 类型正确：`@inproceedings`
- 有页码：3467--3473
- 有 DOI：10.1109/IROS60139.2025.11246202
- 保留了 arXiv 链接在 note 字段

**结论**: 无需修改，当前是正确的 IROS 2025 正式出版条目。

---

### Kong et al. (DGS-SLAM)
```bibtex
@misc{dgsslamkong,
  title  = {{DGS-SLAM}: {G}aussian Splatting {SLAM} in Dynamic Environment},
  author = {Kong, Mangyu and Lee, Jaewon and Lee, Seongwon and Kim, Euntai},
  year   = {2024},
  eprint = {2411.10722},
  archivePrefix = {arXiv},
  primaryClass  = {cs.RO},
  note   = {CrossRef confirms the TCSVT 2026 "DGS-SLAM: Robust Visual SLAM
            With 3D Gaussian Splatting in Dynamic Environments" (Jia et al., IEEE TCSVT
            36(5):6890--6904, doi:10.1109/tcsvt.2025.3645351) is a SEPARATE work by a
            different group -- not the extended version of this paper.}
}
```

**判决**: ✅ **已经是 arXiv 2024**，用户说的就是当前状态！
- 用户说"应该是 arXiv 2024" → 当前就是 arXiv 2024
- 类型正确：`@misc`
- arXiv ID：2411.10722
- 年份：2024
- 重要 note：澄清了同名的 TCSVT 2026 是不同作者组的不同工作

**结论**: 无需修改，当前是正确的 arXiv 2024 条目。

---

## 总结

**问题6: 参考文献修复** → ✅ **无需修复**

两篇文献当前状态与用户要求**完全一致**：
- Zhang et al.: ✅ IROS 2025（有页码、有DOI）
- Kong et al.: ✅ arXiv 2024（预印本）

用户可能是：
1. 对当前状态不确定，要求确认（现已确认正确）
2. 记忆与实际文件不一致（文件是对的）
3. 看到了旧版本（当前版本已修复）

**行动**: 无需修改 references.bib，保持现状。
