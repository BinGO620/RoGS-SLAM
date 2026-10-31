"""dynamic_mask_spec.py — **评估掩码的唯一解析入口**（掩码体系重构 v2，2026-09-21）。

体系（重构后只有两条链，名字与用途分开，互不冒充）
--------------------------------------------------
1. **方法输入（在线）**：`utils/semantic_mask.compute_semantic_dynamic_mask`（MaskRCNN）。
   方法自己在运行期用（跟踪/建图降权；L1b 证据门控）。**不属于本模块**。
2. **评估参照（离线、冻结、方法无关）**：`<seq>/dynamic_mask/`
   —— 由 `scripts/build_dynamic_mask.py` 构建，uint8 **0=静态 / 255=动态**，按 depth stem，
   **没有类号**。本模块是消费方解析它的唯一入口。

为什么是 v2（v1 的教训）
------------------------
v1 的表按序列登记"子目录 + 类号"，因为仓里同时存在三套口径：
  * `seg_mask/`（OneFormer, ADE20K-150 **0 起**，person=cls12）——**非数据集自带**，由项目作者生成；
  * `seg_mask/`（本仓 MaskRCNN 生成的 VOC 口径，person=15，如 crowd3）——**同名不同口径**；
  * `dynamic_mask_gtmc/`（GT 位姿运动一致性）——已验证失效（移动者召回 0.10–0.39）。
同名目录混装两套类号 + "auto 优先 gtmc" + "--mask-class 默认 15" 三个静默默认，
曾让整批指标测错区域（`evidence/l3_instrument_rescore_2026-09-21.md`）。
v2 的做法不是"把类号登记得更仔细"，而是**把类号从消费方彻底拿掉**：eval 掩码一律是布尔图。

默认拒
------
目录缺失 ⇒ raise（不猜、不回落、不静默取别的源）。历史来源只能显式放行，用于复现历史渲染。
"""
from __future__ import annotations

import os

EVAL_MASK_SUBDIR = "dynamic_mask"

# 历史来源：显式放行时用于复现，产物须记为 legacy
LEGACY_SOURCES = {
    "dynamic_mask_gtmc": "已废：移动者召回 0.10–0.39、并集 51–96% 静态误标（2026-09-21 审计）",
    "seg_mask": "OneFormer(ADE20K-150 0 起 person=cls12) 或本仓 MaskRCNN(VOC 15)——同名两套口径，"
                "已降级为只读验证参照",
}


def sequence_name(dataset_path: str) -> str:
    return os.path.basename(str(dataset_path).rstrip("/"))


def resolve_eval_mask_dir(dataset_path: str, mask_subdir: str | None = None,
                          allow_legacy: bool = False) -> tuple:
    """解析评估掩码目录。返回 ``(absolute_dir, source_name, is_legacy)``。

    * 默认（``mask_subdir=None``）⇒ ``<dataset_path>/dynamic_mask``；不存在则 raise。
    * ``mask_subdir`` 显式给历史来源（``seg_mask``/``dynamic_mask_gtmc``）⇒ 必须
      ``allow_legacy=True``，否则 raise（防止无声复刻失效口径）。
    """
    ds = str(dataset_path).rstrip("/")
    if mask_subdir is None:
        d = os.path.join(ds, EVAL_MASK_SUBDIR)
        if not os.path.isdir(d) or not any(f.endswith(".png") for f in os.listdir(d)):
            raise ValueError(
                f"{sequence_name(ds)}: 缺评估掩码 {EVAL_MASK_SUBDIR}/。"
                f"先跑 scripts/build_dynamic_mask.py（内置验证，不过不写盘）。"
                f"**不回落到 seg_mask/gtmc**——那些口径已被证伪/废弃。")
        return d, EVAL_MASK_SUBDIR, False

    if mask_subdir in LEGACY_SOURCES:
        if not allow_legacy:
            raise ValueError(
                f"掩码源 '{mask_subdir}' 是历史来源（{LEGACY_SOURCES[mask_subdir]}）。"
                f"确要复现历史请显式 allow_legacy=True（产物须记为 legacy）。")
        d = os.path.join(ds, mask_subdir)
        if not os.path.isdir(d):
            raise ValueError(f"{sequence_name(ds)}: 无 {mask_subdir}/")
        return d, mask_subdir, True

    d = os.path.join(ds, mask_subdir)
    if not os.path.isdir(d):
        raise ValueError(f"{sequence_name(ds)}: 无 {mask_subdir}/"
                         f"（非表内来源，需自行确保口径正确）")
    return d, mask_subdir, False
