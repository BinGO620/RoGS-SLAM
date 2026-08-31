"""exp39 Step C Phase 0 判读器：EMA 分量分解 + D-3 打乱对照。

复现 results/evidence/exp39c_ema_decomposition_verdict.md 的全部读数。

核心问题：w = 1/(σ̂² + λμ̂² + ε) 为什么给动态像素更高权重？
  μ̂²_dyn < μ̂²_stat  → M1（吸收：动态残差被地图吃掉后变小）
  σ̂²_dyn < σ̂²_stat  → M2（跨视点混合：静态像素跨视点看起来更噪）
  两者同向 ⇒ 分量本身无法分离 M1/M2，由 D-3 分离。

D-3 判读：置换保持权重边际分布与总质量，只摧毁"权重↔像素"对应。
  scrambled ATE ≈ H  → 伤害来自权重形状（形状可修）
  scrambled ATE ≈ E  → 伤害来自"放回"本身（形状无关，整族关门）

用法：conda run -n monogs-ours python scripts/exp39c_ema_decompose.py
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

# 各轮 ATE（headline 口径 = tracking_raw.csv 的 ate_rmse_cm，不是 console 的 RMSE ATE）
ATE_HISTORY = {
    "H (hard)":        [3.46, 2.99],
    "E (EMA)":         [5.31, 8.25, 4.81],
    "S (scrambled)":   [5.36],
}
NOISE_FLOOR_PCT = 6.0  # 全项目 ATE 噪声地板（exp32 自测）

COMPONENT_KEYS = [
    "ema_mu2_dynamic", "ema_mu2_static", "ema_mu2_ratio",
    "ema_sigma2_dynamic", "ema_sigma2_static", "ema_sigma2_ratio",
]


def load_rows(path):
    with open(path) as fh:
        return json.load(fh)["rows"]


def med(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return float(np.median(vals)) if vals else None


def pct(rows, key, q):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return float(np.percentile(vals, q)) if vals else None


def read_ate(probe_path):
    csv_path = Path(probe_path).parent / "tracking_raw.csv"
    if not csv_path.exists():
        return None
    with open(csv_path) as fh:
        for row in csv.DictReader(fh):
            if row.get("ate_rmse_cm"):
                return float(row["ate_rmse_cm"])
    return None


def report_arm(label, path):
    rows = load_rows(path)
    er = [r for r in rows if r.get("ema_dynamic_over_static") is not None]
    comp = [r for r in rows if r.get("ema_mu2_ratio") is not None]

    print(f"\n{'='*66}")
    print(f"  {label}   ({len(er)}/{len(rows)} frames w/ EMA diag, "
          f"{len(comp)} w/ components)")
    print(f"{'='*66}")

    dos, bs = med(er, "ema_dynamic_over_static"), med(er, "ema_bias_suppression")
    print(f"  dynamic_over_static  median={dos:7.4f}  "
          f"p10={pct(er,'ema_dynamic_over_static',10):.3f} "
          f"p90={pct(er,'ema_dynamic_over_static',90):.3f}")
    print(f"  bias_suppression     median={bs:7.4f}   "
          f"({'PASS >0' if bs and bs > 0 else 'FAIL <=0 (预注册第二分支 => 死)'})")

    if comp:
        print(f"\n  --- 分量分解（判 M1/M2）---")
        mu_r, sig_r = med(comp, "ema_mu2_ratio"), med(comp, "ema_sigma2_ratio")
        print(f"    mu2  dyn={med(comp,'ema_mu2_dynamic'):.6f}  "
              f"stat={med(comp,'ema_mu2_static'):.6f}  ratio={mu_r:.4f}")
        print(f"    sig2 dyn={med(comp,'ema_sigma2_dynamic'):.6f}  "
              f"stat={med(comp,'ema_sigma2_static'):.6f}  ratio={sig_r:.4f}")
        if mu_r and mu_r < 1:
            print(f"    => mu2_dyn < mu2_stat ({1/mu_r:.1f}x lower): M1 吸收签名确证")
        if sig_r and sig_r < 1:
            print(f"    => sig2_dyn < sig2_stat ({1/sig_r:.1f}x lower): 与 M2 同向，"
                  f"分量无法单独分离 M1/M2")

    ate = read_ate(path)
    if ate is not None:
        print(f"\n  ATE (tracking_raw.csv) = {ate:.4f} cm")
    return {"dos": dos, "bias_suppression": bs, "ate": ate,
            "mu2_ratio": med(comp, "ema_mu2_ratio") if comp else None,
            "sigma2_ratio": med(comp, "ema_sigma2_ratio") if comp else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ema", default="results/evidence/exp39c_stepb_ema/mapping_probe.json")
    ap.add_argument("--scrambled",
                    default="results/evidence/exp39c_stepb_escrambled/mapping_probe.json")
    args = ap.parse_args()

    out = {}
    for label, path in [("E (EMA)", args.ema), ("S (E-scrambled, D-3)", args.scrambled)]:
        if Path(path).exists():
            out[label] = report_arm(label, path)
        else:
            print(f"\n[skip] {label}: {path} 不存在")

    # ---- D-3 判读 ----
    print(f"\n{'='*66}")
    print("  D-3 判读：伤害来自权重形状，还是来自「放回」本身？")
    print(f"{'='*66}")
    s = out.get("S (E-scrambled, D-3)", {})
    if s.get("dos") is not None:
        ok = abs(s["dos"] - 1.0) < 0.05
        print(f"  装置自检（正对照）: scrambled dos = {s['dos']:.4f}  "
              f"{'PASS' if ok else 'FAIL'} (打乱后两总体均权应趋同 -> 1)")

    h, e = min(ATE_HISTORY["H (hard)"]), out.get("E (EMA)", {}).get("ate")
    sc = s.get("ate")
    if e and sc:
        print(f"\n  H={h:.2f}  E={e:.2f} ({(e-h)/h*100:+.0f}%)  "
              f"S={sc:.2f} ({(sc-h)/h*100:+.0f}%)")
        print(f"  S vs E = {(sc-e)/e*100:+.0f}%")
        if sc > e or abs(sc - e) / e * 100 < 20:
            print("  => 随机权重没有回到 H，与 E 同档 ⇒ "
                  "ADMISSION-NOT-SHAPE（形状无关，连续加权整族关门）")

    # ---- 效应量 vs run-to-run spread ----
    print(f"\n{'='*66}")
    print("  效应量可靠性（逐臂 spread，不外推）")
    print(f"{'='*66}")
    for arm, vals in ATE_HISTORY.items():
        spread = max(vals) - min(vals) if len(vals) > 1 else float("nan")
        print(f"  {arm:16s} {vals}  mean={np.mean(vals):.2f} spread={spread:.2f}")
    E, H = ATE_HISTORY["E (EMA)"], ATE_HISTORY["H (hard)"]
    cons = (min(E) - max(H)) / max(H) * 100
    print(f"\n  E vs H 最保守配对: {cons:+.0f}%  "
          f"({'稳，远超' if cons > NOISE_FLOOR_PCT else '不可读，未过'} {NOISE_FLOOR_PCT}% 地板)")
    if sc and e:
        diff, e_spread = abs(sc - e), max(E) - min(E)
        print(f"  E vs S 差值 {diff:.2f} cm vs E 自身 spread {e_spread:.2f} cm "
              f"=> {'INDETERMINATE（须补 seed）' if diff < e_spread else '可读'}")


if __name__ == "__main__":
    main()
