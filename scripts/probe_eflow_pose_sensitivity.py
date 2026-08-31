#!/usr/bin/env python3
"""e_flow 对位姿误差的敏感度探针 —— f3_st_hf 完整内核崩溃的机制判据。

WHY THIS EXISTS
---------------
静默空转事故修复后，11 条序列用完整内核（含 ReliabilitySignal）重跑，出现干净的
regime 分裂：动态序列 ATE 降 22-38%，而 TUM sitting 序列变差，f3_st_hf 两臂都崩
到 10 倍（3.05→29.43 / 2.14→35.59，3 seed 一致）。已排除跑崩 / flow 缺建 /
flow 错位 / 信号退化（见 results/evidence/fullkern_rerun_regime_split.md）。

活假设（本脚本要证伪的东西）：
  `rigid_flow` 用**当前正在被优化的位姿**（slam_frontend.py:1005，warmup 第 10 次
  迭代冻结）预测静态场景应有的光流。位姿有误差 -> f_static 预测错 -> 残差在**静态**
  结构上也大 -> e_flow 虚高 -> 降权静态结构 -> 位姿收敛更差 -> 下一帧初值更差。
  帧内冻结挡住了帧内反馈，跨帧正反馈没挡。

为什么预测"平移误差比旋转误差更毒"：
  `flow_anomaly` 走 `robust_anomaly`，是**中位数居中 + MAD 归一化**的
  （A = 1-exp(-[a-median]+/scale)）。
    * 旋转误差 δθ -> 全图近似均匀的流误差（~f·δθ，与深度无关）-> 主要抬高中位数
      -> 大部分被归一化吸收；
    * 平移误差 δt -> 流误差 ∝ 1/depth -> 强烈依深度结构化 -> 撑大 MAD 并造重尾
      -> **深度极值处的静态结构**被标成"动态"。
  所以判据不只是"e_flow 涨多少"，还有"e_flow 是否与深度相关"。

判据（预注册在此，跑之前写死）
------------------------------
H1  位姿误差会显著抬高静态场景的 e_flow：
    在 f3_st_hf 上，δ 取实际 ATE 量级（~20cm 平移 / ~2°旋转）时
    mean_e_flow 相对 δ=0 的抬升 >= 50%。
H2  敏感度是 regime 相关的：f3_st_hf 的抬升斜率 > crowd（L 有用的对照）。
H1 与 H2 同时成立 -> 机制假设存活，进入因果验证（在环 oracle）。
任一不成立 -> 假设被证伪，另找机制。

注意：本脚本用 **GT 位姿**做基线，只注入受控扰动，所以测的是"位姿误差 -> e_flow"
这一条边，不含"e_flow -> 位姿"的回边。它证明不了闭环因果，只能证伪机制的前半段。
因果证明要靠在环 oracle（用 GT 相对位姿喂 rigid_flow，跟踪照常跑）。

用法：
  python scripts/probe_eflow_pose_sensitivity.py \
      --run results/runs/P6/P6-MASON-8SEQ/f3_st_hf_combined_seed0 --label f3_st_hf
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.flow_raft import frozen_flow_index, load_frozen_flow  # noqa: E402
from utils.reliability_signal import (  # noqa: E402
    assemble_flow_consensus,
    flow_jacobian_se3,
    relative_pose_target_from_source,
    rigid_flow,
)


def so3_exp(axis, angle_rad):
    """Rodrigues: 绕单位轴 axis 转 angle_rad 的 3x3 旋转矩阵。"""
    a = np.asarray(axis, dtype=np.float64)
    a = a / (np.linalg.norm(a) + 1e-12)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(angle_rad) * K + (1 - np.cos(angle_rad)) * (K @ K)


def find_ts(run_dir):
    c = [p for p in glob.glob(os.path.join(run_dir, "datasets_*", "*", "seed_*", "*"))
         if os.path.isfile(os.path.join(p, "config.yml"))]
    if not c:
        raise SystemExit(f"no completed timestamp dir under {run_dir}")
    return max(c)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="任一该序列的已完成 run（只取 config + GT 位姿）")
    ap.add_argument("--label", required=True)
    ap.add_argument("--frames", type=int, default=60, help="均匀抽样的帧数")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", default="results/evidence/eflow_pose_sensitivity.csv")
    ap.add_argument("--ego-projection", action="store_true",
                    help="同时测开启 ego-residual projection 后的 e_flow（修法 B 的离线验证）")
    ap.add_argument("--max-corr-px", type=float, default=1e9,
                    help="投影护栏上限；默认放开以便先测出真实修正幅度再定默认值")
    args = ap.parse_args()

    import yaml
    from munch import munchify
    from utils.dataset import load_dataset

    ts = find_ts(args.run)
    with open(os.path.join(ts, "config.yml")) as f:
        config = yaml.safe_load(f)
    mp = munchify(config["model_params"])
    ds = load_dataset(mp, mp.source_path, config=config)

    rel_cfg = config.get("ReliabilitySignal", {}) or {}
    flow_floor = float(rel_cfg.get("flow_scale_floor", 0.0))
    flow_dir = os.path.join(config["Dataset"]["dataset_path"],
                            rel_cfg.get("flow_subdir", "flow_raft"))
    fidx = frozen_flow_index(flow_dir)
    if not fidx:
        raise SystemExit(f"no frozen flow under {flow_dir}")

    dev = torch.device(args.device)
    n = len(ds)
    idxs = [int(round(x)) for x in np.linspace(1, n - 1, args.frames)]

    # 扰动档位：旋转(度) 与 平移(米)，分别单独注入
    ROTS = [0.0, 0.1, 0.25, 0.5, 1.0, 2.0]
    TRANS = [0.0, 0.01, 0.02, 0.05, 0.10, 0.20]
    rng = np.random.default_rng(0)  # 扰动方向固定，跨序列同一组，保证可比

    acc = {("rot", d): [] for d in ROTS}
    acc.update({("trans", d): [] for d in TRANS})
    depth_corr = {("rot", d): [] for d in ROTS}
    depth_corr.update({("trans", d): [] for d in TRANS})
    # 修法 B 开启后的同口径读数 + 拟合诊断
    acc_ego = {k: [] for k in acc}
    corr_px = {k: [] for k in acc}
    applied = {k: [] for k in acc}
    ego_flow_mag = []
    used = 0

    for i in idxs:
        stem = os.path.splitext(os.path.basename(ds.depth_paths[i]))[0]
        fp = fidx.get(stem)
        if fp is None:
            continue
        _, depth_np, pose_t = ds[i]
        _, _, pose_p = ds[i - 1]
        if depth_np is None:
            continue
        obs_depth = torch.from_numpy(np.asarray(depth_np)).to(dev).float()
        f_obs = torch.from_numpy(load_frozen_flow(fp)).to(dev)
        if f_obs.shape[:2] != obs_depth.shape:
            continue
        R0, t0 = relative_pose_target_from_source(pose_p.to(dev), pose_t.to(dev))
        R0n = R0.detach().cpu().numpy().astype(np.float64)
        t0n = t0.detach().cpu().numpy().astype(np.float64).reshape(3)

        ax_r = rng.normal(size=3)
        ax_t = rng.normal(size=3)
        ax_t = ax_t / (np.linalg.norm(ax_t) + 1e-12)

        for kind, levels in (("rot", ROTS), ("trans", TRANS)):
            for d in levels:
                if kind == "rot":
                    Rp = so3_exp(ax_r, np.deg2rad(d)) @ R0n
                    tp = t0n
                else:
                    Rp = R0n
                    tp = t0n + ax_t * d
                f_static, fs_valid = rigid_flow(
                    obs_depth, ds.fx, ds.fy, ds.cx, ds.cy,
                    torch.from_numpy(Rp).to(dev).float(),
                    torch.from_numpy(tp).to(dev).float(),
                )
                valid = fs_valid & torch.isfinite(f_obs).all(dim=-1)
                e_flow, fv = assemble_flow_consensus(
                    [f_obs], [f_static], [valid], scale_floor=flow_floor
                )
                if not bool(fv.any()):
                    continue
                ev = e_flow[fv]
                acc[(kind, d)].append(float(ev.mean()))
                if d == 0.0 and kind == "rot":
                    ego_flow_mag.append(float(f_static[valid].norm(dim=-1).median()))
                if args.ego_projection:
                    J, _ = flow_jacobian_se3(
                        obs_depth, ds.fx, ds.fy, ds.cx, ds.cy,
                        torch.from_numpy(Rp).to(dev).float(),
                        torch.from_numpy(tp).to(dev).float(),
                    )
                    st = {}
                    e2, fv2 = assemble_flow_consensus(
                        [f_obs], [f_static], [valid], scale_floor=flow_floor,
                        ego_jac_list=[J],
                        ego_kwargs={"max_corr_px": args.max_corr_px},
                        ego_stats_out=st,
                    )
                    if bool(fv2.any()):
                        acc_ego[(kind, d)].append(float(e2[fv2].mean()))
                    corr_px[(kind, d)].append(float(st.get("ego_corr_px", 0.0)))
                    applied[(kind, d)].append(float(st.get("ego_fit_applied", 0)))
                # e_flow 与 depth 的相关性：位姿误差的结构化特征
                dv = obs_depth[fv]
                m = torch.isfinite(ev) & torch.isfinite(dv) & (dv > 0)
                if int(m.sum()) > 100:
                    a = ev[m] - ev[m].mean()
                    b = dv[m] - dv[m].mean()
                    den = (a.norm() * b.norm()).clamp_min(1e-12)
                    depth_corr[(kind, d)].append(float((a @ b) / den))
        used += 1

    if used == 0:
        raise SystemExit("no usable frames (flow stem mismatch?)")

    rows = []
    base = float(np.mean(acc[("rot", 0.0)])) if acc[("rot", 0.0)] else float("nan")
    print(f"\n=== {args.label} ===  帧数={used}  flow_scale_floor={flow_floor}")
    if ego_flow_mag:
        print(f"该序列自运动预测流幅度 median|f_static| = {np.mean(ego_flow_mag):.2f} px")
    print(f"基线 mean_e_flow (δ=0, GT 位姿) = {base:.4f}")
    hdr = f"{'扰动':>16s} {'mean_e_flow':>12s} {'相对基线':>10s} {'corr(e_flow,depth)':>20s}"
    if args.ego_projection:
        hdr += f" |{'+投影后':>10s} {'相对基线':>10s} {'修正px':>8s} {'生效率':>7s}"
    print(hdr)
    for kind, levels, unit in (("rot", ROTS, "deg"), ("trans", TRANS, "m")):
        for d in levels:
            v = acc[(kind, d)]
            if not v:
                continue
            m = float(np.mean(v))
            c = float(np.mean(depth_corr[(kind, d)])) if depth_corr[(kind, d)] else float("nan")
            rel = (m - base) / base * 100 if base == base and base > 0 else float("nan")
            line = f"{kind+' '+str(d)+unit:>16s} {m:>12.4f} {rel:>9.1f}% {c:>20.3f}"
            row = {"label": args.label, "kind": kind, "delta": d, "unit": unit,
                   "mean_e_flow": round(m, 5), "rel_pct": round(rel, 2),
                   "corr_e_flow_depth": round(c, 4), "n_frames": used}
            if args.ego_projection:
                ve = acc_ego[(kind, d)]
                me = float(np.mean(ve)) if ve else float("nan")
                rele = (me - base) / base * 100 if base > 0 else float("nan")
                cp = float(np.mean(corr_px[(kind, d)])) if corr_px[(kind, d)] else float("nan")
                ap_ = float(np.mean(applied[(kind, d)])) if applied[(kind, d)] else float("nan")
                line += f" |{me:>10.4f} {rele:>9.1f}% {cp:>8.2f} {ap_:>7.2f}"
                row.update({"mean_e_flow_ego": round(me, 5), "rel_pct_ego": round(rele, 2),
                            "ego_corr_px": round(cp, 3), "ego_applied_frac": round(ap_, 3)})
            print(line)
            rows.append(row)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    import csv
    new = not os.path.isfile(args.out)
    with open(args.out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f"-> appended {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
