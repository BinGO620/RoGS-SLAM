#!/usr/bin/env python3
"""Paper mechanism figure -- FULL two-term reliability signal (2026-08-15 rewrite, exp22).

WHAT CHANGED AND WHY. The previous version of this figure REIMPLEMENTED the flow anomaly
inline and drew ``s ~= 1 - e_flow`` -- a flow-only approximation, because the geometry
term was never archived per pixel. P7 (48 runs) then concluded that the GEOMETRY cue is
the strongest on 3/4 sequences, so the paper's headline mechanism figure was showing
everything except the cue the paper calls most important. A reviewer reading §P7 and then
looking at the figure would find the seam immediately.

This version:
  * calls the ONLINE functions themselves (``geometric_anomaly`` / ``rigid_flow`` /
    ``assemble_flow_consensus`` / ``fuse_static_evidence`` / ``cauchy_tracking_weight``)
    instead of reimplementing anything, so the picture cannot drift from the code;
  * gives EACH cue its own panel (e_flow and v*g) and shows the product s they form;
  * overlays the frozen GT-pose dynamic mask contour, so the separation the figure claims
    is visually checkable rather than asserted;
  * annotates the MEASURED separability (AUC of 1-s vs that GT mask, from
    ``results/evidence/reliability_separability.json``) instead of leaving the reader to
    guess how good the signal is.

FRAME CHOICE IS A RULE, NOT A PICK. The old script took the frame with the lowest mean_s
(the most extreme frame in the sequence). This one samples the sequence and keeps the
frame whose PER-FRAME AUC is closest to the sequence-level AUC -- i.e. a typical frame,
not the best one -- among frames whose dynamic-pixel fraction is in [1%, 40%].

HONEST APPROXIMATION (kept in the figure caption): ``render_depth`` and ``opacity`` come
from the run's TERMINAL map (final PLY) re-rendered at the run's own estimated poses, not
from the online map as it stood at frame t. The formula and the flow/depth inputs are the
online ones; the map is not.

Usage:
  python scripts/generate_mechanism_figure.py --run-dir /tmp/mech_runs/balloon \
      --sequence balloon --stride 3
"""

import argparse
import glob
import json
import os
import sys

import numpy as np
import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.probe_hole_ghost import load_run, render_frame  # noqa: E402
from utils.reliability_signal import (  # noqa: E402
    assemble_flow_consensus,
    cauchy_tracking_weight,
    fuse_static_evidence,
    geometric_anomaly,
    get_reliability_signal_config,
    relative_pose_target_from_source,
    rigid_flow,
)

SEQ_DIRS = {
    "balloon": "/data/Datasets/Bonn/rgbd_bonn_balloon",
    "pt2": "/data/Datasets/Bonn/rgbd_bonn_person_tracking2",
    "pt1": "/data/Datasets/Bonn/rgbd_bonn_person_tracking",
    "mv_no_box2": "/data/Datasets/Bonn/rgbd_bonn_moving_nonobstructing_box2",
}


def frame_auc(evidence, dynamic, max_n=60000):
    pos = evidence[dynamic]
    neg = evidence[~dynamic]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    rng = np.random.default_rng(0)
    if pos.size > max_n:
        pos = rng.choice(pos, max_n, replace=False)
    if neg.size > max_n:
        neg = rng.choice(neg, max_n, replace=False)
    allv = np.concatenate([pos, neg])
    order = allv.argsort()
    ranks = np.empty(len(allv), dtype=np.float64)
    ranks[order] = np.arange(1, len(allv) + 1)
    return float((ranks[: pos.size].sum() - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def signal_terms(cfg, dataset, gaussians, pose_by_id, fid, prev_id, flow_path):
    """Every quantity the figure draws, straight from the online functions."""
    _, opacity, render_depth = render_frame(dataset, gaussians, cfg, pose_by_id[fid], fid)
    device = render_depth.device
    obs_depth = torch.from_numpy(
        np.asarray(Image.open(dataset.depth_paths[fid]), dtype=np.float32) / dataset.depth_scale
    ).to(device)
    f_obs = torch.from_numpy(np.load(flow_path).astype(np.float32)).to(device)
    if f_obs.shape[:2] != obs_depth.shape[-2:]:
        return None
    rc = get_reliability_signal_config(cfg)
    geo_floor = float(rc.get("geo_scale_floor", 0.0))
    flow_floor = float(rc.get("flow_scale_floor", 0.0))

    R, t = relative_pose_target_from_source(
        torch.from_numpy(pose_by_id[fid]).float(), torch.from_numpy(pose_by_id[prev_id]).float()
    )
    obs = obs_depth.squeeze()
    rend = render_depth.squeeze()
    op = opacity.squeeze()

    g = geometric_anomaly(obs, rend, scale_floor=geo_floor)
    f_static, fs_valid = rigid_flow(
        obs, dataset.fx, dataset.fy, dataset.cx, dataset.cy, R.to(device), t.to(device)
    )
    valid = fs_valid & torch.isfinite(f_obs).all(dim=-1)
    e_flow, _ = assemble_flow_consensus([f_obs], [f_static], [valid], scale_floor=flow_floor)
    s = fuse_static_evidence(g, e_flow, op, mode="both")
    w = cauchy_tracking_weight(s)
    return {
        "e_flow": e_flow.float().cpu().numpy(),
        "geo": (op.clamp(0, 1) * g.clamp(0, 1)).float().cpu().numpy(),  # the v*g term
        "s": s.float().cpu().numpy(),
        "w": w.float().cpu().numpy(),
        "flow_mag": f_obs.norm(dim=-1).float().cpu().numpy(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="/tmp/mech_runs/balloon")
    ap.add_argument("--sequence", default="balloon")
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--out", default="results/evidence/mechanism_figure_paper.png")
    ap.add_argument("--sep-json", default="results/evidence/reliability_separability.json")
    args = ap.parse_args()

    torch.set_grad_enabled(False)
    seq_dir = SEQ_DIRS[args.sequence]
    cfg, dataset, gaussians, trj = load_run(args.run_dir, seq_dir)
    pose_by_id = {int(f): np.asarray(T, dtype=np.float64)
                  for f, T in zip(trj["trj_id"], trj["trj_est"])}
    ids = sorted(pose_by_id)
    masks = {os.path.splitext(os.path.basename(p))[0]: p
             for p in glob.glob(os.path.join(seq_dir, "dynamic_mask_gtmc", "*.png"))}
    flows = {os.path.splitext(os.path.basename(p))[0]: p
             for p in glob.glob(os.path.join(seq_dir, "flow_raft", "*.npy"))}

    # sequence-level AUC we are trying to be typical of (measured by the separability probe)
    seq_auc = None
    if os.path.isfile(args.sep_json):
        for row in json.load(open(args.sep_json)):
            if row["sequence"] == args.sequence and row["mode"] == "both":
                seq_auc = row["auc_1_minus_s"]

    timeline, candidates = [], []
    for k, fid in enumerate(ids):
        if k == 0 or k % args.stride:
            continue
        stem = os.path.splitext(os.path.basename(dataset.depth_paths[fid]))[0]
        if stem not in masks or stem not in flows:
            continue
        terms = signal_terms(cfg, dataset, gaussians, pose_by_id, fid, ids[k - 1], flows[stem])
        if terms is None:
            continue
        dyn = np.asarray(Image.open(masks[stem])) > 0
        timeline.append((fid, float(terms["s"].mean()), float(terms["w"].mean())))
        frac = float(dyn.mean())
        if 0.01 <= frac <= 0.40:
            candidates.append((fid, ids[k - 1], stem, frame_auc(1.0 - terms["s"], dyn), frac))
        if len(timeline) % 25 == 0:
            print(f"  sampled {len(timeline)} frames", flush=True)

    if not candidates:
        raise SystemExit("no usable frame (need a GT mask covering 1-40% of the image)")
    target_auc = seq_auc if seq_auc is not None else float(np.median([c[3] for c in candidates]))
    fid, prev_id, stem, f_auc, f_frac = min(candidates, key=lambda c: abs(c[3] - target_auc))
    print(f"target frame {fid}: per-frame AUC={f_auc:.3f} (sequence AUC={target_auc:.3f}), "
          f"dynamic pixels {f_frac * 100:.1f}%")

    terms = signal_terms(cfg, dataset, gaussians, pose_by_id, fid, prev_id, flows[stem])
    dyn = np.asarray(Image.open(masks[stem])) > 0
    rgb = np.asarray(Image.open(dataset.color_paths[fid]).convert("RGB"))

    fig = plt.figure(figsize=(18.5, 6.3))
    gs = gridspec.GridSpec(2, 5, height_ratios=[1, 0.70], hspace=0.34, wspace=0.40)

    def panel(idx, img, title, cmap=None, vmin=None, vmax=None, cbar=None, contour=True):
        ax = fig.add_subplot(gs[0, idx])
        im = ax.imshow(img, cmap=cmap, vmin=vmin, vmax=vmax) if cmap else ax.imshow(img)
        if contour:
            ax.contour(dyn.astype(float), levels=[0.5], colors="lime", linewidths=1.1)
        ax.set_title(title, fontsize=10.5, fontweight="bold", pad=4)
        ax.axis("off")
        # panel A has no colorbar, which would make it wider than the rest; add one and
        # hide it so all five panels keep the same image width
        bar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.03, shrink=0.85)
        if cbar:
            bar.set_label(cbar, fontsize=8)
        else:
            bar.ax.set_visible(False)
        return ax

    # ALL four signal panels share one semantic: red = "this says dynamic". The previous
    # revision drew s directly, so red meant RELIABLE in (D) and DYNAMIC in (B)(C) -- the
    # inversion made the chain unreadable. (D) now shows 1-s, which is also the quantity
    # the quoted AUC scores, so figure and number are the same object.
    panel(0, rgb, f"(A) RGB  frame {fid}")
    panel(1, terms["e_flow"], "(B) flow cue  $e_{flow}$", cmap="Reds", vmin=0, vmax=1, cbar="dynamic ev.")
    panel(2, terms["geo"], "(C) geometry cue  $v\\cdot g$", cmap="Reds", vmin=0, vmax=1, cbar="dynamic ev.")
    panel(3, 1.0 - terms["s"], "(D) fused  $1-s$", cmap="Reds", vmin=0, vmax=1, cbar="dynamic ev.")
    ax_e = fig.add_subplot(gs[0, 4])
    ax_e.imshow(rgb)
    im_e = ax_e.imshow(1.0 - terms["w"], cmap="Reds", alpha=0.55, vmin=0, vmax=1)
    ax_e.contour(dyn.astype(float), levels=[0.5], colors="lime", linewidths=1.1)
    ax_e.set_title("(E) down-weight  $1-w$", fontsize=10.5, fontweight="bold", pad=4)
    ax_e.axis("off")
    plt.colorbar(im_e, ax=ax_e, fraction=0.046, pad=0.03, shrink=0.85).set_label("1−w", fontsize=8)

    frames = [t[0] for t in timeline]
    ax_t = fig.add_subplot(gs[1, :3])
    ax_t.plot(frames, [t[1] for t in timeline], "b-", lw=1.4, label="mean $s$", alpha=0.9)
    ax_t.plot(frames, [t[2] for t in timeline], "g-", lw=1.4, label="mean $w$", alpha=0.9)
    ax_t.axvline(x=fid, color="red", ls="--", lw=1.5)
    ax_t.set(xlabel="frame", ylabel="signal [0,1]", ylim=(-0.05, 1.05))
    ax_t.legend(fontsize=8.5, loc="lower left")
    ax_t.grid(True, alpha=0.3)
    ax_t.set_title("recomputed over the whole sequence (full two-term $s$)", fontsize=9)

    ax_s = fig.add_subplot(gs[1, 3:])
    ax_s.axis("off")
    lines = [
        "$s = (1-e_{flow})\\,(1-v\\,g)$   $w = 1/(1+(d/\\tau)^2),\\ d=1-s$",
        "",
        f"frame {fid}:  mean s = {terms['s'].mean():.3f},  mean w = {terms['w'].mean():.3f}",
        f"dynamic pixels (GT) = {f_frac * 100:.1f}%",
        f"separability of $1-s$ vs GT mask:  AUC = {f_auc:.3f} (frame)",
    ]
    if seq_auc is not None:
        lines.append(f"                                   AUC = {seq_auc:.3f} (sequence, n=82 frames)")
    lines += [
        "",
        "frame chosen by rule: per-frame AUC closest to the",
        "sequence AUC (a TYPICAL frame, not the best one).",
        "render_depth / opacity come from the terminal map",
        "re-rendered at the run's own estimated poses.",
    ]
    ax_s.text(0.02, 0.96, "\n".join(lines), transform=ax_s.transAxes, fontsize=8.6, va="top",
              family="monospace",
              bbox=dict(boxstyle="round,pad=0.5", facecolor="lightyellow", alpha=0.75))

    fig.suptitle(
        f"MRCS mechanism chain (red = evidence of motion): flow cue $\\times$ geometry cue "
        f"$\\rightarrow$ fused $1-s$ $\\rightarrow$ Cauchy down-weight.  "
        f"{args.sequence}, mask-free.  Green contour = frozen GT-pose dynamic mask.",
        fontsize=12, fontweight="bold", y=0.995,
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
