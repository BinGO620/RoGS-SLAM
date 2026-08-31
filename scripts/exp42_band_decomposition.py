#!/usr/bin/env python3
"""exp42 Phase -1 —— 渲染误差三带分解 + 动态重建可达域（零新 SLAM run）。

**这个测量项目从来没做过**：73 个注册实验的火力全部打在 ATE 侧，渲染侧只做过
全帧/静态带两个聚合数（exp35/36），从没问过「渲染误差到底分布在哪条带上」。

## 为什么需要它（判据 #11：先算可达域，再决定跑不跑）

候选方向「动态渲染分支」的头条理由是关闭 balloon 上 vs RGD-SLAM 的 3.58 dB 渲染差距
（我们 21.56 / RGD 25.14，同环境同口径重跑、mask_type=full、after_opt）。
若完美重建动态内容的增益上界远小于 3.58 dB，该头条**在跑任何 GPU 之前就不成立**。

## 为什么不能用 exp36 的数反解（我自己踩过的坑，记录在此）

先做过一次解析反解：由全帧 17.31 dB 与静态带 18.78 dB 反解动态带 = 10.04 dB，
进而推出「RGD 的动态带必须 ≥13.1 dB」。**该推导已撤回**——静态带支持集是
`(GT 深度有效) AND NOT(GTMC 动态)`，而 balloon 上**深度无效像素占 14.0%**（本轮实测），
它们在全帧支持集里、不在静态带里 ⇒ 「全帧−静态带」的超额误差被整包错记到 6.2% 的
动态像素头上。与 exp36 判据 #16（分母要逐通道审计）同一个失效模式。
⇒ 只能直接测三条**互斥**的带。

## 三条互斥带（全部限制在项目既有全帧支持集 gt_image > 0 内）

    D = GTMC 动态
    S = ~D 且 GT 深度有效      （= exp36 的静态带）
    I = ~D 且 GT 深度无效      （此前从未被单独量过的那 14%）

## 可达域（本探针的判读对象）

逐帧把 D 带的误差置零（= 完美重建动态内容），重算全帧 PSNR：

    ceiling_gain = mean_frame[ PSNR_oracle ] − mean_frame[ PSNR_full ]

**逐帧算再平均**，不是聚合 MSE 反解——balloon 的动态占比逐帧从 0% 到 49%，
PSNR 是逐帧算完再平均的非线性量，聚合代数会给错数。

判读（跑前写死）：
  * ceiling_gain ≥ 3.58 dB  → 动态内容足以解释整条渲染差距 ⇒ 方向成立
  * 1.0 ≤ ceiling_gain < 3.58 → 只能解释一部分 ⇒ 头条降级为「差距的一个组成部分」
  * ceiling_gain < 1.0 dB   → **方向的渲染头条判死**（不再花 GPU）

无论落哪一档，I 带的读数都是新信息：若 I 带误差占大头，则渲染差距的主要成因
既不是动态也不是静态重建，而是深度无效区（该区没有几何约束、纯靠光度外插）。

用法：
    conda run -n monogs-ours python scripts/exp42_band_decomposition.py \
        --run results/runs/P2/P2-T_3090/balloon_prune_seed0/datasets_bonn/p2s_combined_prune_balloon/seed_0/2026-08-08-23-07-31
"""

import argparse
import glob
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))


def _psnr_from_sse(sse, n_elem):
    """PSNR over an arbitrary pixel subset, MAX=1 (images are in [0,1])."""
    if n_elem == 0:
        return None
    mse = sse / n_elem
    if mse <= 0:
        return None
    return float(-10.0 * np.log10(mse))


def run(run_dir, interval=None, mask_subdir="dynamic_mask_gtmc", limit=None):
    import torch
    import yaml
    from munch import munchify
    from PIL import Image

    from gaussian_splatting.scene.gaussian_model import GaussianModel
    from gaussian_splatting.gaussian_renderer import render
    from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
    from utils.camera_utils import Camera
    from utils.dataset import load_dataset

    run_dir = os.path.normpath(run_dir)
    cfg_path = os.path.join(run_dir, "config.yml")
    ply_path = os.path.join(run_dir, "point_cloud", "final_after_opt", "point_cloud.ply")
    trj_path = os.path.join(run_dir, "plot", "trj_full_final.json")
    for p in (cfg_path, ply_path, trj_path):
        if not os.path.isfile(p):
            raise FileNotFoundError(f"required run artifact missing: {p}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if interval is None:
        interval = config.get("Results", {}).get("eval_rendering_interval", 5)

    model_params = munchify(config["model_params"])
    model_params.sh_degree = 3 if config["Training"]["spherical_harmonics"] else 0
    dataset = load_dataset(model_params, model_params.source_path, config=config)

    gaussians = GaussianModel(model_params.sh_degree, config=config)
    gaussians.load_ply(ply_path)

    with open(trj_path, "r", encoding="utf-8") as f:
        trj = json.load(f)
    pose_by_id = {int(fid): np.asarray(c2w, dtype=np.float64) for fid, c2w in zip(trj["trj_id"], trj["trj_est"])}
    frame_ids = sorted(pose_by_id.keys())

    # run configs carry source_path='' and keep the real path in Dataset.dataset_path
    # (relative to the repo root, where datasets/bonn/* are symlinks to /data/Datasets).
    ds_root = model_params.source_path or config["Dataset"]["dataset_path"]
    mask_dir = os.path.join(ds_root, mask_subdir)
    if not os.path.isdir(mask_dir):
        raise FileNotFoundError(f"GTMC mask dir missing: {mask_dir}")

    projection_matrix = (
        getProjectionMatrix2(
            znear=0.01, zfar=100.0,
            fx=dataset.fx, fy=dataset.fy, cx=dataset.cx, cy=dataset.cy,
            W=dataset.width, H=dataset.height,
        ).transpose(0, 1).to(device=dataset.device)
    )
    background = torch.tensor([0, 0, 0], dtype=torch.float32, device="cuda")

    rows = []
    n_missing_mask = 0
    todo = frame_ids[::interval]
    if limit:
        todo = todo[:limit]

    with torch.no_grad():
        for fid in todo:
            c2w = pose_by_id[fid]
            w2c = np.linalg.inv(c2w)
            rotation, translation = w2c[:3, :3], w2c[:3, 3]

            cam = Camera(
                int(fid), None, None, torch.eye(4, device=dataset.device), projection_matrix,
                dataset.fx, dataset.fy, dataset.cx, dataset.cy,
                dataset.fovx, dataset.fovy, dataset.height, dataset.width,
                device=dataset.device,
            )
            cam.update_RT(
                torch.from_numpy(np.ascontiguousarray(rotation)).float(),
                torch.from_numpy(np.ascontiguousarray(translation)).float(),
            )
            cam.cam_rot_delta = None
            cam.cam_trans_delta = None
            cam.exposure_a = None
            cam.exposure_b = None

            gt_image, gt_depth, _ = dataset[fid]
            render_pkg = render(cam, gaussians, munchify(config["pipeline_params"]), background)
            image = torch.clamp(render_pkg["render"], 0.0, 1.0)

            # --- frozen GTMC mask, keyed by this frame's depth stem (same key as
            # eval_static_background_raw) ---
            stem = os.path.splitext(os.path.basename(dataset.depth_paths[fid]))[0]
            mpath = os.path.join(mask_dir, stem + ".png")
            if not os.path.isfile(mpath):
                n_missing_mask += 1
                continue
            dyn = torch.from_numpy(np.array(Image.open(mpath)) > 0).to(image.device)

            gt_depth_t = torch.as_tensor(np.asarray(gt_depth), device=image.device, dtype=torch.float32)
            depth_valid = gt_depth_t > 0.01
            if dyn.shape != depth_valid.shape:
                raise RuntimeError(f"mask/depth shape mismatch: {tuple(dyn.shape)} vs {tuple(depth_valid.shape)}")

            # project's full-frame support: gt_image > 0, per-channel
            support = gt_image > 0                          # (3,H,W)
            sq = (image - gt_image) ** 2                     # (3,H,W)

            dyn3 = dyn.unsqueeze(0).expand_as(support)
            valid3 = depth_valid.unsqueeze(0).expand_as(support)

            m_full = support
            m_D = support & dyn3
            m_S = support & (~dyn3) & valid3
            m_I = support & (~dyn3) & (~valid3)

            sse = lambda m: float(sq[m].sum().item())
            cnt = lambda m: int(m.sum().item())

            sse_full, n_full = sse(m_full), cnt(m_full)
            sse_D, n_D = sse(m_D), cnt(m_D)
            sse_S, n_S = sse(m_S), cnt(m_S)
            sse_I, n_I = sse(m_I), cnt(m_I)

            # oracle: dynamic-band error -> 0, same denominator (full support)
            psnr_oracle = _psnr_from_sse(sse_full - sse_D, n_full)

            rows.append({
                "fid": int(fid),
                "psnr_full": _psnr_from_sse(sse_full, n_full),
                "psnr_D": _psnr_from_sse(sse_D, n_D),
                "psnr_S": _psnr_from_sse(sse_S, n_S),
                "psnr_I": _psnr_from_sse(sse_I, n_I),
                "psnr_oracle": psnr_oracle,
                "frac_D": n_D / n_full if n_full else 0.0,
                "frac_S": n_S / n_full if n_full else 0.0,
                "frac_I": n_I / n_full if n_full else 0.0,
                "sse_share_D": sse_D / sse_full if sse_full > 0 else 0.0,
                "sse_share_S": sse_S / sse_full if sse_full > 0 else 0.0,
                "sse_share_I": sse_I / sse_full if sse_full > 0 else 0.0,
            })
            del cam

    def _mean(key):
        vals = [r[key] for r in rows if r[key] is not None and np.isfinite(r[key])]
        return float(np.mean(vals)) if vals else float("nan")

    out = {
        "run_dir": run_dir,
        "sequence": os.path.basename(ds_root),
        "n_frames_scored": len(rows),
        "n_missing_mask": n_missing_mask,
        "interval": interval,
        "psnr_full": round(_mean("psnr_full"), 4),
        "psnr_oracle_dynamic_perfect": round(_mean("psnr_oracle"), 4),
        "ceiling_gain_db": round(_mean("psnr_oracle") - _mean("psnr_full"), 4),
        "bands": {
            "D_dynamic":       {"psnr": round(_mean("psnr_D"), 4), "pixel_frac": round(_mean("frac_D"), 4), "sse_share": round(_mean("sse_share_D"), 4)},
            "S_static_valid":  {"psnr": round(_mean("psnr_S"), 4), "pixel_frac": round(_mean("frac_S"), 4), "sse_share": round(_mean("sse_share_S"), 4)},
            "I_depth_invalid": {"psnr": round(_mean("psnr_I"), 4), "pixel_frac": round(_mean("frac_I"), 4), "sse_share": round(_mean("sse_share_I"), 4)},
        },
        "per_frame": rows,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run dir containing config.yml + point_cloud/final_after_opt + plot/trj_full_final.json")
    ap.add_argument("--interval", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None, help="score only the first N eval frames (smoke)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = run(args.run, interval=args.interval, limit=args.limit)

    b = out["bands"]
    print("=" * 68)
    print(f"exp42 三带分解 — {out['sequence']}  ({out['n_frames_scored']} frames, interval {out['interval']})")
    print("=" * 68)
    print(f"  全帧 PSNR                  {out['psnr_full']:.2f} dB")
    print()
    print("  带           PSNR      像素占比    误差占比(SSE)")
    for name, key in (("D 动态      ", "D_dynamic"), ("S 静态深度有效", "S_static_valid"), ("I 深度无效  ", "I_depth_invalid")):
        r = b[key]
        p = f"{r['psnr']:.2f}" if r["psnr"] == r["psnr"] else "n/a"
        print(f"  {name}  {p:>7} dB   {r['pixel_frac']*100:5.1f}%      {r['sse_share']*100:5.1f}%")
    print()
    print(f"  完美重建动态内容 => 全帧 {out['psnr_oracle_dynamic_perfect']:.2f} dB")
    print(f"  ** 可达域 ceiling_gain = +{out['ceiling_gain_db']:.2f} dB **")
    print(f"     (balloon vs RGD-SLAM 差距 = 3.58 dB)")
    g = out["ceiling_gain_db"]
    verdict = "方向成立" if g >= 3.58 else ("头条降级为「差距的一部分」" if g >= 1.0 else "渲染头条判死")
    print(f"     判读: {verdict}")
    if out["n_missing_mask"]:
        print(f"  ! {out['n_missing_mask']} 帧缺 mask，已跳过并计数")

    dst = args.out or os.path.join("results", "evidence", "exp42_band_decomposition.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\n  -> {dst}")


if __name__ == "__main__":
    main()
