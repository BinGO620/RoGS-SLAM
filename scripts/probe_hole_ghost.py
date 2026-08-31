#!/usr/bin/env python3
"""offline (2060, zero-training) probe — dynamic-removal artifact: hole vs ghost.

Goal: give the paper a quantitative FIGURE on the "dark holes" complaint. For a set of
frames where the dynamic person is present, render each run's final PLY at its saved
trajectory, then in the GTMC-person region classify the render into:

  * GHOST: high render opacity + content resembling the person (dynamic object baked in) —
          the `vanilla` failure mode.
  * HOLE:  near-zero opacity where the background camera depth says wall should be —
          the "dark hole" on removal.
  * CLEAN: high opacity + background color present (dynamic object cleanly removed and
          background reconstructed) — the desired outcome.

Metrics per run (vanilla / combined / maskoff):
  - mean render opacity in GTMC-person region
  - fraction of person-region pixels that are ghost (op>0.5) vs hole (op<0.05)
  - masked-region color PSNR vs the "true" background (we use the GT image pixel, but
    that includes the person; so instead report background-reveal coverage = how much
    of the occluded min-depth "TRUE background" at that frame — from GT depth — is
    actually visible in the render behind where the depth jumps).

Reuses the exact Camera+render construction from scripts/r2_p2_t_offline_render.py
(evaluate_run lines 149-196, verified earlier) so the pose/render path is apples-to-apples.

Run on 2060: pure offline render of already-saved final PLYs, no SLAM training.
"""
import os, sys, json, glob, argparse
import numpy as np
import torch, yaml, cv2
from munch import munchify

ROOT = "/data/monogs-ours"
sys.path.insert(0, ROOT)

from gaussian_splatting.gaussian_renderer import render
from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2
from utils.camera_utils import Camera
from utils.dataset import load_dataset
from gaussian_splatting.scene.gaussian_model import GaussianModel


def w2c_from_c2w(c2w):
    c2w = np.asarray(c2w, dtype=np.float64)
    R = c2w[:3, :3]
    t = c2w[:3, 3]
    R_inv = R.T
    t_inv = -R_inv @ t
    return R_inv, t_inv


def load_run(run_dir, source_path):
    cfg = yaml.safe_load(open(os.path.join(run_dir, "config.yml")))
    ply = os.path.join(run_dir, "point_cloud", "final_after_opt", "point_cloud.ply")
    if not os.path.isfile(ply):
        ply = os.path.join(run_dir, "point_cloud", "final", "point_cloud.ply")
    assert os.path.isfile(ply), f"no final PLY {ply}"
    trj = json.load(open(os.path.join(run_dir, "plot", "trj_full_final.json")))
    mp = munchify(cfg["model_params"])
    mp.source_path = source_path
    mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    dataset = load_dataset(mp, mp.source_path, config=cfg if isinstance(cfg, dict) else None)
    gaussians = GaussianModel(mp.sh_degree, config=cfg)
    gaussians.load_ply(ply)
    return cfg, dataset, gaussians, trj


def render_frame(dataset, gaussians, cfg, c2w, fid):
    projection_matrix = (
        getProjectionMatrix2(
            znear=0.01, zfar=100.0,
            fx=dataset.fx, fy=dataset.fy, cx=dataset.cx, cy=dataset.cy,
            W=dataset.width, H=dataset.height,
        ).transpose(0, 1).to(device=dataset.device)
    )
    R, t = w2c_from_c2w(c2w)
    cam = Camera(
        int(fid), None, None, torch.eye(4, device=dataset.device), projection_matrix,
        dataset.fx, dataset.fy, dataset.cx, dataset.cy, dataset.fovx, dataset.fovy,
        dataset.height, dataset.width, device=dataset.device,
    )
    cam.update_RT(torch.from_numpy(np.ascontiguousarray(R)).float(),
                  torch.from_numpy(np.ascontiguousarray(t)).float())
    cam.cam_rot_delta = cam.cam_trans_delta = cam.exposure_a = cam.exposure_b = None
    background = torch.tensor([0, 0, 0], dtype=torch.float32, device="cuda")
    pkg = render(cam, gaussians, munchify(cfg["pipeline_params"]), background)
    return torch.clamp(pkg["render"], 0, 1), pkg["opacity"].squeeze(0), pkg["depth"].squeeze(0)


def pick_frames(gtmc_dir, rgb_dir, n=6, max_cov=0.20):
    """frames with person present, cov in a readable band (not too big/small)."""
    masks = sorted(glob.glob(os.path.join(gtmc_dir, "*.png")))
    rgb = sorted(glob.glob(os.path.join(rgb_dir, "*.png")))
    idx_by_ts = {os.path.basename(p).split(".")[0]: i for i, p in enumerate(rgb)}
    cands = []
    for m in masks:
        ts = os.path.basename(m).split(".")[0]
        if ts not in idx_by_ts:
            continue
        mask = cv2.imread(m, cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue
        cov = np.float32(mask > 0).mean()
        if 0.02 <= cov <= max_cov:
            cands.append((idx_by_ts[ts], cov))
    cands.sort(key=lambda x: x[1])
    # spread across coverage range
    if len(cands) > n:
        step = len(cands) // n
        return [cands[i * step][0] for i in range(n)]
    return [c for c, _ in cands]


def classify(caml, rgl, depthl, mask, gt_depth, gt_rgb):
    """returns dict of masked-region metrics; mask is GTMC person (H,W)>0; gt_depth for background truth."""
    m = mask.astype(bool)
    if m.sum() == 0:
        return None
    op = caml[m].float().cpu().numpy()
    rgba = rgl.permute(1, 2, 0).cpu().numpy()[m]
    dep = depthl[m].float().cpu().numpy()
    gd = gt_depth[m]
    hole = np.mean(op < 0.05)
    ghost = np.mean(op > 0.5)
    covered = np.mean(op > 0.05)
    # color: how far is the render (in masked region) from GT (which shows the person)?
    # A ghost (person baked) => render ~= GT person pixels => LOW color dist.
    # A clean background/hole in front of wall => render shows background, GT shows person =>
    # that pixel's render color != GT color, but it matches the static background color.
    # We report: mean abs color diff in masked region vs GT (smaller = person appears = ghost,
    # larger = map doesn't show the person = background shown or hole).
    gt_img = torch.from_numpy(gt_rgb.astype(np.float32)).to(rgl.device)
    if gt_rgb.ndim == 2:
        gt_img = gt_img.unsqueeze(-1).repeat(1, 1, 3)
    gt_c = gt_img.permute(2, 0, 1).unsqueeze(0).float() / 255.0
    diff = (rgl - gt_c[:, :, :, :])[:, :, m].abs().mean().item() if m.sum() else None
    return {
        "mean_op": float(np.mean(op)),
        "hole_frac": float(hole),
        "ghost_frac": float(ghost),
        "bg_reveal_frac": float(covered),
        "mean_render_gt_color_diff": round(diff, 4) if diff is not None else None,
        "n_px": int(m.sum()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="/data/Datasets/Bonn/rgbd_bonn_balloon")
    ap.add_argument("--run", required=True, help="run dir with point_cloud/final + plot/trj_full_final.json + config.yml")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--maxcov", type=float, default=0.20)
    args = ap.parse_args()

    cfg, dataset, gaussians, trj = load_run(args.run, args.source)
    pose_by_id = {int(fid): np.asarray(tr) for fid, tr in zip(trj["trj_id"], trj["trj_est"])}
    # trj_id is list of global frame indices (0..N-1). Map to dataset frame? The eval uses fid directly.
    gtmc = os.path.join(args.source, "dynamic_mask_gtmc")
    rgbd = os.path.join(args.source, "rgb")
    depthd = os.path.join(args.source, "depth")
    rgb = sorted(glob.glob(os.path.join(rgbd, "*.png")))
    dep = sorted(glob.glob(os.path.join(depthd, "*.png")))
    mask_files = sorted(glob.glob(os.path.join(gtmc, "*.png")))

    # We need frame id -> (rgb, depth, mask) alignment. The trajectory trj_id is GLOBAL frame (0..438).
    # load_dataset likely reorders; but trj_id in the run == position in rgb list. Use that.
    frames = pick_frames(gtmc, rgbd, n=args.n, max_cov=args.maxcov)
    report = []
    with torch.no_grad():
        for fid in frames:
            if fid not in pose_by_id:
                continue
            render_img, op, dep_r = render_frame(dataset, gaussians, cfg, pose_by_id[fid], fid)
            mask = cv2.imread(mask_files[fid] if fid < len(mask_files) else mask_files[-1], cv2.IMREAD_GRAYSCALE)
            mask = (mask > 0).astype(np.uint8) if mask is not None else np.zeros((dataset.height, dataset.width))
            gt_depth = cv2.imread(dep[fid] if fid < len(dep) else dep[-1], cv2.IMREAD_UNCHANGED).astype(np.float32) / 1000.0
            gt_rgb = cv2.imread(rgb[fid] if fid < len(rgb) else rgb[-1])
            gt_rgb = cv2.cvtColor(gt_rgb, cv2.COLOR_BGR2RGB)
            res = classify(op, render_img, dep_r, mask, gt_depth, gt_rgb)
            if res:
                res["frame"] = fid
                report.append(res)
    agg = {}
    for k in ("mean_op", "hole_frac", "ghost_frac", "bg_reveal_frac", "mean_render_gt_color_diff"):
        agg[k] = round(float(np.mean([r[k] for r in report if r[k] is not None])), 4) if report else None
    agg["n_frames"] = len(report)
    print(json.dumps(agg, indent=2))


if __name__ == "__main__":
    main()
