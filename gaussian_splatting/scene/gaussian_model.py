#
# Copyright (C) 2023, Inria
# GRAPHDECO research group, https://team.inria.fr/graphdeco
# All rights reserved.
#
# This software is free for non-commercial, research and evaluation use
# under the terms of the LICENSE.md file.
#
# For inquiries contact  george.drettakis@inria.fr
#

import os

import numpy as np
import open3d as o3d
import torch
from plyfile import PlyData, PlyElement
from simple_knn._C import distCUDA2
from torch import nn

from gaussian_splatting.utils.general_utils import (
    build_rotation,
    build_scaling_rotation,
    get_expon_lr_func,
    helper,
    inverse_sigmoid,
    strip_symmetric,
)
from utils.logging_utils import Log
from gaussian_splatting.utils.graphics_utils import BasicPointCloud, getWorld2View2
from gaussian_splatting.utils.sh_utils import RGB2SH
from gaussian_splatting.utils.system_utils import mkdir_p
from utils.causal_twin import (
    UNTRACKED,
    CounterRNG,
    LineageAllocator,
    base_rng_key,
    lineage_prune_mask,
)


def sparse_scale_fallback_value(
    point_count,
    point_size,
    min_gaussian_scale=None,
    max_gaussian_scale=None,
):
    """Return a finite scale for point sets too small for SimpleKNN.

    ``distCUDA2`` estimates the mean squared distance to three neighbours, so it
    does not have a well-defined result unless the input contains at least four
    points. Deferred promotion can legitimately commit only one to three pixels;
    those batches must bypass the CUDA KNN kernel instead of leaving an async CUDA
    error to surface later in mapping.
    """

    if int(point_count) >= 4:
        return None

    minimum = 1e-4 if min_gaussian_scale is None else float(min_gaussian_scale)
    maximum = None if max_gaussian_scale is None else float(max_gaussian_scale)
    if not np.isfinite(minimum) or minimum <= 0.0:
        raise ValueError("min_gaussian_scale must be finite and positive")
    if maximum is not None:
        if not np.isfinite(maximum) or maximum <= 0.0:
            raise ValueError("max_gaussian_scale must be finite and positive")
        if maximum < minimum:
            raise ValueError("max_gaussian_scale must be >= min_gaussian_scale")

    point_size = float(point_size)
    if not np.isfinite(point_size) or point_size <= 0.0:
        raise ValueError("Dataset.point_size must be finite and positive")
    fallback = max(minimum, float(np.sqrt(1e-7 * point_size)))
    if maximum is not None:
        fallback = min(fallback, maximum)
    return fallback


class GaussianModel:
    def __init__(self, sh_degree: int, config=None):
        self.active_sh_degree = 0
        self.max_sh_degree = sh_degree

        self._xyz = torch.empty(0, device="cuda")
        self._features_dc = torch.empty(0, device="cuda")
        self._features_rest = torch.empty(0, device="cuda")
        self._scaling = torch.empty(0, device="cuda")
        self._rotation = torch.empty(0, device="cuda")
        self._opacity = torch.empty(0, device="cuda")
        self.max_radii2D = torch.empty(0, device="cuda")
        self.xyz_gradient_accum = torch.empty(0, device="cuda")

        self.unique_kfIDs = torch.empty(0).int()
        self.n_obs = torch.empty(0).int()
        # Causal-twin lineage label (method #7): a CPU int id per Gaussian naming the
        # candidate it descends from; UNTRACKED (-1) for normal map growth. Mirrors
        # unique_kfIDs exactly (extended in densification_postfix, inherited through
        # clone/split, sliced in prune_points) and is NEVER read by the renderer,
        # optimizer, or loss -> carrying it cannot change any live-pipeline result.
        self.lineage_id = torch.empty(0).int()
        self._lineage_alloc = LineageAllocator()
        self.static_prob = torch.empty((0, 1), device="cuda")
        self.static_obs_count = torch.empty((0, 1), device="cuda")
        self.unmapped_score = torch.empty((0, 1), device="cuda")

        self.optimizer = None

        self.scaling_activation = torch.exp
        self.scaling_inverse_activation = torch.log

        self.covariance_activation = self.build_covariance_from_scaling_rotation

        self.opacity_activation = torch.sigmoid
        self.inverse_opacity_activation = inverse_sigmoid

        self.rotation_activation = torch.nn.functional.normalize

        self.config = config
        self.ply_input = None
        self.last_scale_initialization = "none"

        self.isotropic = False

    def build_covariance_from_scaling_rotation(
        self, scaling, scaling_modifier, rotation
    ):
        L = build_scaling_rotation(scaling_modifier * scaling, rotation)
        actual_covariance = L @ L.transpose(1, 2)
        symm = strip_symmetric(actual_covariance)
        return symm

    @property
    def get_scaling(self):
        return self.scaling_activation(self._scaling)

    @property
    def get_rotation(self):
        return self.rotation_activation(self._rotation)

    @property
    def get_xyz(self):
        return self._xyz

    @property
    def get_features(self):
        features_dc = self._features_dc
        features_rest = self._features_rest
        return torch.cat((features_dc, features_rest), dim=1)

    @property
    def get_opacity(self):
        return self.opacity_activation(self._opacity)

    def ensure_static_memory_state(self, default_static_prob=0.7, preserve=True):
        """Resize the per-Gaussian static memory (alpha ledger) to the Gaussian count.

        ``static_prob`` is the R2-P02 alpha ledger and ``static_obs_count`` its
        persistence counter; both only mean something if they survive across
        keyframes. Every add/remove routes through ``densification_postfix`` /
        ``prune_points``, so a length mismatch here is a desync -- and the old
        behaviour (rebuild every entry at the default) silently destroyed all
        accumulated evidence, which alone can keep the exit gate unreachable.

        A GROW mismatch can only come from an append-only path, so the existing
        prefix still maps 1:1 onto the same Gaussians and is kept (``preserve``);
        only the new tail gets defaults. A SHRINK mismatch means some path
        removed Gaussians without slicing the ledger, so index alignment is
        unknowable and a rebuild is the only safe option -- that one is counted
        in ``static_memory_reset_count`` because it loses information.
        """
        num_points = self.get_xyz.shape[0]
        n_old = int(self.static_prob.shape[0])
        if n_old == num_points:
            return
        device = self.get_xyz.device

        def _resize(tensor, fill):
            if preserve and 0 < n_old < num_points and tensor.shape[0] == n_old:
                tail = torch.full(
                    (num_points - n_old, 1), float(fill),
                    dtype=torch.float32, device=device,
                )
                return torch.cat((tensor.to(device=device), tail), dim=0)
            return torch.full(
                (num_points, 1), float(fill), dtype=torch.float32, device=device
            )

        if preserve and 0 < n_old < num_points:
            self.static_memory_extend_count = (
                getattr(self, "static_memory_extend_count", 0) + 1
            )
        else:
            self.static_memory_reset_count = (
                getattr(self, "static_memory_reset_count", 0) + 1
            )
        self.static_prob = _resize(self.static_prob, default_static_prob)
        self.static_obs_count = _resize(self.static_obs_count, 0.0)
        self.unmapped_score = _resize(
            getattr(self, "unmapped_score", torch.empty((0, 1), device=device)), 0.0
        )

    def ensure_lineage_state(self):
        """Resize ``lineage_id`` to the current Gaussian count (defensive).

        Every add/remove routes through ``densification_postfix``/``prune_points``
        which keep ``lineage_id`` in sync, so this only fires after a wholesale
        replacement (e.g. ``load_ply`` for offline rendering) and back-fills
        UNTRACKED so a later prune cannot index-mismatch.
        """
        num_points = self.get_xyz.shape[0]
        if self.lineage_id.shape[0] == num_points:
            return
        self.lineage_id = torch.full((num_points,), UNTRACKED, dtype=torch.int32)

    def allocate_lineage_ids(self, count):
        """Fresh contiguous lineage ids for a new candidate batch (method #7).

        The single source of candidate ids for this run; clone/split descendants
        inherit them, so an id names the whole sub-tree of one candidate.
        """
        return self._lineage_alloc.allocate(count)

    def prune_lineage(self, target_ids):
        """Delete every Gaussian in ``target_ids`` and its optimizer state.

        Used by the ``prune`` ablation arm to remove a rejected/expired candidate
        together with its ENTIRE clone/split lineage (a faithful insert-then-remove
        twin of ``deferred``). No-op when ``target_ids`` is empty.
        """
        self.ensure_lineage_state()
        mask = lineage_prune_mask(self.lineage_id, target_ids)
        if not bool(mask.any()):
            return
        self.prune_points(mask.to(self.get_xyz.device))

    def static_memory_summary(self):
        self.ensure_static_memory_state()
        if self.static_prob.numel() == 0:
            return {
                "gaussian_count": 0,
                "mean_static_prob": None,
                "low_static_ratio": None,
                "mean_unmapped_score": None,
            }
        low_threshold = 0.5
        return {
            "gaussian_count": int(self.static_prob.shape[0]),
            "mean_static_prob": float(self.static_prob.mean().item()),
            "low_static_ratio": float(
                (self.static_prob < low_threshold).float().mean().item()
            ),
            "mean_unmapped_score": float(self.unmapped_score.mean().item()),
        }

    def get_covariance(self, scaling_modifier=1):
        return self.covariance_activation(
            self.get_scaling, scaling_modifier, self._rotation
        )

    def oneupSHdegree(self):
        if self.active_sh_degree < self.max_sh_degree:
            self.active_sh_degree += 1

    def _counter_rng(self):
        """Lazily-built CounterRNG for this model's stochastic init/densify sites.

        Keyed by ``(sequence, seed)`` (via :func:`base_rng_key`) so the three
        lifecycle arms draw identical streams at identical logical events -- the
        causal-twin contract (``03-knowledges/11-*.md``). Rebuilt from ``config``
        if the attribute is absent (e.g. after unpickling across the mp boundary),
        so it never depends on a live object surviving the process hop.
        """
        rng = getattr(self, "_counter_rng_cache", None)
        if rng is None:
            rng = CounterRNG(*base_rng_key(getattr(self, "config", None)))
            self._counter_rng_cache = rng
        return rng

    def _next_rng_event(self, site):
        """A site-local, monotonically-increasing event index for ``site``.

        The CounterRNG key contract requires a SITE-LOCAL counter (the k-th draw
        at this site), never a global draw counter (which would be arm-dependent).
        Candidate Gaussians held out of the active map trigger no draws here, so a
        deferred arm's active-map RNG stream is untouched by candidate state --
        exactly the non-influence invariant.
        """
        counters = getattr(self, "_rng_site_counter", None)
        if counters is None:
            counters = {}
            self._rng_site_counter = counters
        idx = counters.get(site, 0)
        counters[site] = idx + 1
        return idx

    def create_pcd_from_image(
        self,
        cam_info,
        init=False,
        scale=2.0,
        depthmap=None,
        downsample_factor=None,
        min_gaussian_scale=None,
        max_gaussian_scale=None,
    ):
        cam = cam_info
        image_ab = (torch.exp(cam.exposure_a)) * cam.original_image + cam.exposure_b
        image_ab = torch.clamp(image_ab, 0.0, 1.0)
        rgb_raw = (image_ab * 255).byte().permute(1, 2, 0).contiguous().cpu().numpy()

        if depthmap is not None:
            rgb = o3d.geometry.Image(rgb_raw.astype(np.uint8))
            depth = o3d.geometry.Image(depthmap.astype(np.float32))
        else:
            depth_raw = cam.depth
            if depth_raw is None:
                depth_raw = np.empty((cam.image_height, cam.image_width))

            if self.config["Dataset"]["sensor_type"] == "monocular":
                depth_raw = (
                    np.ones_like(depth_raw)
                    + (np.random.randn(depth_raw.shape[0], depth_raw.shape[1]) - 0.5)
                    * 0.05
                ) * scale

            rgb = o3d.geometry.Image(rgb_raw.astype(np.uint8))
            depth = o3d.geometry.Image(depth_raw.astype(np.float32))

        return self.create_pcd_from_image_and_depth(
            cam,
            rgb,
            depth,
            init,
            downsample_factor=downsample_factor,
            min_gaussian_scale=min_gaussian_scale,
            max_gaussian_scale=max_gaussian_scale,
        )

    def create_pcd_from_image_and_depth(
        self,
        cam,
        rgb,
        depth,
        init=False,
        downsample_factor=None,
        min_gaussian_scale=None,
        max_gaussian_scale=None,
    ):
        if downsample_factor is None:
            if init:
                downsample_factor = self.config["Dataset"]["pcd_downsample_init"]
            else:
                downsample_factor = self.config["Dataset"]["pcd_downsample"]
        point_size = self.config["Dataset"]["point_size"]
        if "adaptive_pointsize" in self.config["Dataset"]:
            if self.config["Dataset"]["adaptive_pointsize"]:
                depth_values = np.asarray(depth, dtype=np.float32)
                valid_depth = depth_values[
                    np.isfinite(depth_values) & (depth_values > 0.01)
                ]
                if valid_depth.size:
                    point_size = min(0.05, point_size * np.median(valid_depth))
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            rgb,
            depth,
            depth_scale=1.0,
            depth_trunc=100.0,
            convert_rgb_to_intensity=False,
        )

        W2C = getWorld2View2(cam.R, cam.T).cpu().numpy()
        pcd_tmp = o3d.geometry.PointCloud.create_from_rgbd_image(
            rgbd,
            o3d.camera.PinholeCameraIntrinsic(
                cam.image_width,
                cam.image_height,
                cam.fx,
                cam.fy,
                cam.cx,
                cam.cy,
            ),
            extrinsic=W2C,
            project_valid_depth_only=True,
        )
        # Deterministic keyed downsample replacing o3d's unseedable C++ RNG, so
        # the lifecycle arms keep an identical init cloud at identical keyframes
        # (``random_down_sample`` cannot be seeded from Python). ``int(n/factor)``
        # truncates -> matches o3d's floor(ratio*n) count exactly (same density);
        # a keyed subset -> paired across arms. causal-twin.
        n_pts = np.asarray(pcd_tmp.points).shape[0]
        keep_k = int(n_pts / downsample_factor)
        keep_idx = self._counter_rng().subsample_indices(
            n_pts, keep_k, "init_downsample", self._next_rng_event("init_downsample")
        )
        pcd_tmp = pcd_tmp.select_by_index([int(i) for i in keep_idx])
        new_xyz = np.asarray(pcd_tmp.points)
        new_rgb = np.asarray(pcd_tmp.colors)
        if new_xyz.shape[0] > 0:
            self.ply_input = BasicPointCloud(
                points=new_xyz, colors=new_rgb, normals=np.zeros((new_xyz.shape[0], 3))
            )
        return self._gaussians_from_points(
            torch.from_numpy(new_xyz).float(),
            torch.from_numpy(new_rgb).float(),
            point_size,
            min_gaussian_scale=min_gaussian_scale,
            max_gaussian_scale=max_gaussian_scale,
        )

    def _gaussians_from_points(
        self,
        points,
        colors,
        point_size,
        min_gaussian_scale=None,
        max_gaussian_scale=None,
    ):
        """Shared Gaussian-tensor init from explicit world points + RGB colors.

        Maps ``points`` (N,3 world) + ``colors`` (N,3 in [0,1]) -> the five Gaussian
        tensors (xyz, SH features, log-scales, unit rots, 0.5 opacities) with the EXACT
        scale rule (SimpleKNN ``distCUDA2``, or the sparse fallback for < 4 points) used
        by the o3d depth-map path. The point ORDER is preserved 1:1, so a caller may
        align a parallel per-point ``lineage_id`` array -- this is precisely what lets
        the deterministic direct-from-arrays candidate builder carry the lineage the o3d
        path (project_valid_depth_only compaction + random_down_sample) destroys.
        """
        scale_dimensions = 1 if self.isotropic else 3
        coefficient_count = (self.max_sh_degree + 1) ** 2
        if points.shape[0] == 0:
            return (
                torch.empty((0, 3), dtype=torch.float32, device="cuda"),
                torch.empty(
                    (0, 3, coefficient_count), dtype=torch.float32, device="cuda"
                ),
                torch.empty((0, scale_dimensions), dtype=torch.float32, device="cuda"),
                torch.empty((0, 4), dtype=torch.float32, device="cuda"),
                torch.empty((0, 1), dtype=torch.float32, device="cuda"),
            )
        fused_point_cloud = points.float().cuda()
        fused_color = RGB2SH(colors.float().cuda())
        features = (
            torch.zeros((fused_color.shape[0], 3, coefficient_count)).float().cuda()
        )
        features[:, :3, 0] = fused_color
        features[:, 3:, 1:] = 0.0

        sparse_fallback = sparse_scale_fallback_value(
            fused_point_cloud.shape[0],
            point_size,
            min_gaussian_scale=min_gaussian_scale,
            max_gaussian_scale=max_gaussian_scale,
        )
        if sparse_fallback is None:
            gaussian_scale = torch.sqrt(
                torch.clamp_min(distCUDA2(fused_point_cloud), 0.0000001) * point_size
            )
            self.last_scale_initialization = "knn"
        else:
            gaussian_scale = torch.full(
                (fused_point_cloud.shape[0],),
                sparse_fallback,
                dtype=torch.float32,
                device=fused_point_cloud.device,
            )
            self.last_scale_initialization = "sparse-fallback"
        if min_gaussian_scale is not None:
            gaussian_scale = gaussian_scale.clamp_min(float(min_gaussian_scale))
        if max_gaussian_scale is not None:
            gaussian_scale = gaussian_scale.clamp_max(float(max_gaussian_scale))
        scales = torch.log(gaussian_scale)[..., None]
        if not self.isotropic:
            scales = scales.repeat(1, 3)

        rots = torch.zeros((fused_point_cloud.shape[0], 4), device="cuda")
        rots[:, 0] = 1
        opacities = inverse_sigmoid(
            0.5
            * torch.ones(
                (fused_point_cloud.shape[0], 1), dtype=torch.float, device="cuda"
            )
        )

        return fused_point_cloud, features, scales, rots, opacities

    def init_lr(self, spatial_lr_scale):
        self.spatial_lr_scale = spatial_lr_scale

    def extend_from_pcd(
        self, fused_point_cloud, features, scales, rots, opacities, kf_id, lineage_ids=None
    ):
        new_xyz = nn.Parameter(fused_point_cloud.requires_grad_(True))
        new_features_dc = nn.Parameter(
            features[:, :, 0:1].transpose(1, 2).contiguous().requires_grad_(True)
        )
        new_features_rest = nn.Parameter(
            features[:, :, 1:].transpose(1, 2).contiguous().requires_grad_(True)
        )
        new_scaling = nn.Parameter(scales.requires_grad_(True))
        new_rotation = nn.Parameter(rots.requires_grad_(True))
        new_opacity = nn.Parameter(opacities.requires_grad_(True))

        new_unique_kfIDs = torch.ones((new_xyz.shape[0])).int() * kf_id
        new_n_obs = torch.zeros((new_xyz.shape[0])).int()
        self.densification_postfix(
            new_xyz,
            new_features_dc,
            new_features_rest,
            new_opacity,
            new_scaling,
            new_rotation,
            new_kf_ids=new_unique_kfIDs,
            new_n_obs=new_n_obs,
            new_lineage_id=lineage_ids,
        )

    def extend_from_pcd_seq(
        self,
        cam_info,
        kf_id=-1,
        init=False,
        scale=2.0,
        depthmap=None,
        downsample_factor=None,
        min_gaussian_scale=None,
        max_gaussian_scale=None,
    ):
        if depthmap is not None and not np.any(
            np.isfinite(depthmap) & (np.asarray(depthmap) > 0.01)
        ):
            return 0
        fused_point_cloud, features, scales, rots, opacities = (
            self.create_pcd_from_image(
                cam_info,
                init,
                scale=scale,
                depthmap=depthmap,
                downsample_factor=downsample_factor,
                min_gaussian_scale=min_gaussian_scale,
                max_gaussian_scale=max_gaussian_scale,
            )
        )
        if fused_point_cloud.shape[0] == 0:
            return 0
        self.extend_from_pcd(
            fused_point_cloud, features, scales, rots, opacities, kf_id
        )
        return int(fused_point_cloud.shape[0])

    def insert_candidate_gaussians(
        self,
        cam,
        pixels_x,
        pixels_y,
        depth,
        color,
        kf_id,
        lineage_ids,
        min_gaussian_scale=None,
        max_gaussian_scale=None,
    ):
        """Deterministically insert per-pixel candidates with per-candidate lineage.

        The lifecycle action path for the ``prune`` arm's insert-now and the
        ``deferred`` arm's promotion. Backprojects the flat ``(pixels_x, pixels_y,
        depth)`` arrays with ``cam``'s CURRENT (BA-updated) pose + intrinsics to world
        points -- the SAME convention as the o3d path (``inv(getWorld2View2(R,T)) @
        K^-1 pixel``) -- then builds Gaussians via the shared ``_gaussians_from_points``
        and stamps ``lineage_ids`` 1:1. Order is preserved with NO downsample/compaction,
        so a later ``prune_lineage`` deletes exactly these candidates (and descendants).
        ``color`` is (N,3) in [0,1]. Returns the number of Gaussians inserted.
        """
        n = int(len(pixels_x))
        if n == 0:
            return 0
        device = "cuda"
        px = torch.as_tensor(np.asarray(pixels_x), dtype=torch.float32, device=device)
        py = torch.as_tensor(np.asarray(pixels_y), dtype=torch.float32, device=device)
        z = torch.as_tensor(np.asarray(depth), dtype=torch.float32, device=device)
        xc = (px - float(cam.cx)) / float(cam.fx) * z
        yc = (py - float(cam.cy)) / float(cam.fy) * z
        cam_points = torch.stack([xc, yc, z, torch.ones_like(z)], dim=0)  # 4 x n
        w2c = getWorld2View2(cam.R, cam.T).to(device=device, dtype=torch.float32)
        world = (torch.linalg.inv(w2c) @ cam_points)[:3].transpose(0, 1).contiguous()
        colors = torch.as_tensor(np.asarray(color), dtype=torch.float32, device=device)

        point_size = self.config["Dataset"]["point_size"]
        if self.config["Dataset"].get("adaptive_pointsize", False):
            zz = np.asarray(depth, dtype=np.float32)
            zz = zz[np.isfinite(zz) & (zz > 0.01)]
            if zz.size:
                point_size = min(0.05, point_size * float(np.median(zz)))

        fused_point_cloud, features, scales, rots, opacities = (
            self._gaussians_from_points(
                world,
                colors,
                point_size,
                min_gaussian_scale=min_gaussian_scale,
                max_gaussian_scale=max_gaussian_scale,
            )
        )
        if fused_point_cloud.shape[0] == 0:
            return 0
        lineage = torch.as_tensor(np.asarray(lineage_ids), dtype=torch.int32)
        self.extend_from_pcd(
            fused_point_cloud,
            features,
            scales,
            rots,
            opacities,
            kf_id,
            lineage_ids=lineage,
        )
        return int(fused_point_cloud.shape[0])

    def training_setup(self, training_args):
        self.percent_dense = training_args.percent_dense
        self.xyz_gradient_accum = torch.zeros((self.get_xyz.shape[0], 1), device="cuda")
        self.denom = torch.zeros((self.get_xyz.shape[0], 1), device="cuda")

        param_groups = [
            {
                "params": [self._xyz],
                "lr": training_args.position_lr_init * self.spatial_lr_scale,
                "name": "xyz",
            },
            {
                "params": [self._features_dc],
                "lr": training_args.feature_lr,
                "name": "f_dc",
            },
            {
                "params": [self._features_rest],
                "lr": training_args.feature_lr / 20.0,
                "name": "f_rest",
            },
            {
                "params": [self._opacity],
                "lr": training_args.opacity_lr,
                "name": "opacity",
            },
            {
                "params": [self._scaling],
                "lr": training_args.scaling_lr * self.spatial_lr_scale,
                "name": "scaling",
            },
            {
                "params": [self._rotation],
                "lr": training_args.rotation_lr,
                "name": "rotation",
            },
        ]

        self.optimizer = torch.optim.Adam(param_groups, lr=0.0, eps=1e-15)
        self.xyz_scheduler_args = get_expon_lr_func(
            lr_init=training_args.position_lr_init * self.spatial_lr_scale,
            lr_final=training_args.position_lr_final * self.spatial_lr_scale,
            lr_delay_mult=training_args.position_lr_delay_mult,
            max_steps=training_args.position_lr_max_steps,
        )

        self.lr_init = training_args.position_lr_init * self.spatial_lr_scale
        self.lr_final = training_args.position_lr_final * self.spatial_lr_scale
        self.lr_delay_mult = training_args.position_lr_delay_mult
        self.max_steps = training_args.position_lr_max_steps

    def update_learning_rate(self, iteration):
        """Learning rate scheduling per step"""
        for param_group in self.optimizer.param_groups:
            if param_group["name"] == "xyz":
                # lr = self.xyz_scheduler_args(iteration)
                lr = helper(
                    iteration,
                    lr_init=self.lr_init,
                    lr_final=self.lr_final,
                    lr_delay_mult=self.lr_delay_mult,
                    max_steps=self.max_steps,
                )

                param_group["lr"] = lr
                return lr

    def construct_list_of_attributes(self):
        attributes = ["x", "y", "z", "nx", "ny", "nz"]
        # All channels except the 3 DC
        for i in range(self._features_dc.shape[1] * self._features_dc.shape[2]):
            attributes.append("f_dc_{}".format(i))
        for i in range(self._features_rest.shape[1] * self._features_rest.shape[2]):
            attributes.append("f_rest_{}".format(i))
        attributes.append("opacity")
        for i in range(self._scaling.shape[1]):
            attributes.append("scale_{}".format(i))
        for i in range(self._rotation.shape[1]):
            attributes.append("rot_{}".format(i))
        attributes.append("static_prob")
        attributes.append("static_obs_count")
        attributes.append("unmapped_score")
        return attributes

    def save_ply(self, path):
        mkdir_p(os.path.dirname(path))

        xyz = self._xyz.detach().cpu().numpy()
        normals = np.zeros_like(xyz)
        f_dc = (
            self._features_dc.detach()
            .transpose(1, 2)
            .flatten(start_dim=1)
            .contiguous()
            .cpu()
            .numpy()
        )
        f_rest = (
            self._features_rest.detach()
            .transpose(1, 2)
            .flatten(start_dim=1)
            .contiguous()
            .cpu()
            .numpy()
        )
        opacities = self._opacity.detach().cpu().numpy()
        scale = self._scaling.detach().cpu().numpy()
        rotation = self._rotation.detach().cpu().numpy()
        self.ensure_static_memory_state()
        static_prob = self.static_prob.detach().cpu().numpy()
        static_obs_count = self.static_obs_count.detach().cpu().numpy()
        unmapped_score = self.unmapped_score.detach().cpu().numpy()

        dtype_full = [
            (attribute, "f4") for attribute in self.construct_list_of_attributes()
        ]
        elements = np.empty(xyz.shape[0], dtype=dtype_full)
        attributes = np.concatenate(
            (
                xyz,
                normals,
                f_dc,
                f_rest,
                opacities,
                scale,
                rotation,
                static_prob,
                static_obs_count,
                unmapped_score,
            ),
            axis=1,
        )
        elements[:] = list(map(tuple, attributes))
        el = PlyElement.describe(elements, "vertex")
        PlyData([el]).write(path)

    def reset_opacity(self):
        opacities_new = inverse_sigmoid(torch.ones_like(self.get_opacity) * 0.01)
        optimizable_tensors = self.replace_tensor_to_optimizer(opacities_new, "opacity")
        self._opacity = optimizable_tensors["opacity"]

    def reset_opacity_nonvisible(
        self, visibility_filters
    ):  ##Reset opacity for only non-visible gaussians
        opacities_new = inverse_sigmoid(torch.ones_like(self.get_opacity) * 0.4)

        for filter in visibility_filters:
            opacities_new[filter] = self.get_opacity[filter]
        optimizable_tensors = self.replace_tensor_to_optimizer(opacities_new, "opacity")
        self._opacity = optimizable_tensors["opacity"]

    def reset_opacity_masked(self, mask, reset_value=0.01):
        """Reset opacity of ONLY the masked Gaussians to ``reset_value`` (the
        inverse selection of ``reset_opacity_nonvisible``). Used by the R2-P02
        Fork-B alpha exit pass (mechanism A): low-alpha occluders that hide the
        observed background get their opacity knocked down so the background can
        be re-optimized -- reversible, unlike a hard prune, and it leaves every
        other Gaussian's opacity logit exactly as-is. Returns #reset."""
        if mask is None:
            return 0
        mask = mask.to(device=self._opacity.device, dtype=torch.bool).view(-1)
        n = int(mask.sum())
        if n == 0:
            return 0
        opacities_new = self._opacity.detach().clone()
        opacities_new[mask] = inverse_sigmoid(
            torch.tensor(
                float(reset_value),
                device=opacities_new.device,
                dtype=opacities_new.dtype,
            )
        )
        optimizable_tensors = self.replace_tensor_to_optimizer(opacities_new, "opacity")
        self._opacity = optimizable_tensors["opacity"]
        return n

    def load_ply(self, path):
        plydata = PlyData.read(path)

        def fetchPly_nocolor(path):
            plydata = PlyData.read(path)
            vertices = plydata["vertex"]
            positions = np.vstack([vertices["x"], vertices["y"], vertices["z"]]).T
            normals = np.vstack([vertices["nx"], vertices["ny"], vertices["nz"]]).T
            colors = np.ones_like(positions)
            return BasicPointCloud(points=positions, colors=colors, normals=normals)

        self.ply_input = fetchPly_nocolor(path)
        xyz = np.stack(
            (
                np.asarray(plydata.elements[0]["x"]),
                np.asarray(plydata.elements[0]["y"]),
                np.asarray(plydata.elements[0]["z"]),
            ),
            axis=1,
        )
        opacities = np.asarray(plydata.elements[0]["opacity"])[..., np.newaxis]

        features_dc = np.zeros((xyz.shape[0], 3, 1))
        features_dc[:, 0, 0] = np.asarray(plydata.elements[0]["f_dc_0"])
        features_dc[:, 1, 0] = np.asarray(plydata.elements[0]["f_dc_1"])
        features_dc[:, 2, 0] = np.asarray(plydata.elements[0]["f_dc_2"])

        extra_f_names = [
            p.name
            for p in plydata.elements[0].properties
            if p.name.startswith("f_rest_")
        ]
        extra_f_names = sorted(extra_f_names, key=lambda x: int(x.split("_")[-1]))
        assert len(extra_f_names) == 3 * (self.max_sh_degree + 1) ** 2 - 3
        features_extra = np.zeros((xyz.shape[0], len(extra_f_names)))
        for idx, attr_name in enumerate(extra_f_names):
            features_extra[:, idx] = np.asarray(plydata.elements[0][attr_name])
        # Reshape (P,F*SH_coeffs) to (P, F, SH_coeffs except DC)
        features_extra = features_extra.reshape(
            (features_extra.shape[0], 3, (self.max_sh_degree + 1) ** 2 - 1)
        )

        scale_names = [
            p.name
            for p in plydata.elements[0].properties
            if p.name.startswith("scale_")
        ]
        scale_names = sorted(scale_names, key=lambda x: int(x.split("_")[-1]))
        scales = np.zeros((xyz.shape[0], len(scale_names)))
        for idx, attr_name in enumerate(scale_names):
            scales[:, idx] = np.asarray(plydata.elements[0][attr_name])

        rot_names = [
            p.name for p in plydata.elements[0].properties if p.name.startswith("rot")
        ]
        rot_names = sorted(rot_names, key=lambda x: int(x.split("_")[-1]))
        rots = np.zeros((xyz.shape[0], len(rot_names)))
        for idx, attr_name in enumerate(rot_names):
            rots[:, idx] = np.asarray(plydata.elements[0][attr_name])

        self._xyz = nn.Parameter(
            torch.tensor(xyz, dtype=torch.float, device="cuda").requires_grad_(True)
        )
        self._features_dc = nn.Parameter(
            torch.tensor(features_dc, dtype=torch.float, device="cuda")
            .transpose(1, 2)
            .contiguous()
            .requires_grad_(True)
        )
        self._features_rest = nn.Parameter(
            torch.tensor(features_extra, dtype=torch.float, device="cuda")
            .transpose(1, 2)
            .contiguous()
            .requires_grad_(True)
        )
        self._opacity = nn.Parameter(
            torch.tensor(opacities, dtype=torch.float, device="cuda").requires_grad_(
                True
            )
        )
        self._scaling = nn.Parameter(
            torch.tensor(scales, dtype=torch.float, device="cuda").requires_grad_(True)
        )
        self._rotation = nn.Parameter(
            torch.tensor(rots, dtype=torch.float, device="cuda").requires_grad_(True)
        )
        self.active_sh_degree = self.max_sh_degree
        self.max_radii2D = torch.zeros((self._xyz.shape[0]), device="cuda")
        self.unique_kfIDs = torch.zeros((self._xyz.shape[0]))
        self.n_obs = torch.zeros((self._xyz.shape[0]), device="cpu").int()
        self.lineage_id = torch.full(
            (self._xyz.shape[0],), UNTRACKED, dtype=torch.int32
        )
        property_names = {p.name for p in plydata.elements[0].properties}
        if "static_prob" in property_names:
            static_prob = np.asarray(plydata.elements[0]["static_prob"])[
                ..., np.newaxis
            ]
        else:
            static_prob = np.full((self._xyz.shape[0], 1), 0.7)
        if "static_obs_count" in property_names:
            static_obs_count = np.asarray(plydata.elements[0]["static_obs_count"])[
                ..., np.newaxis
            ]
        else:
            static_obs_count = np.zeros((self._xyz.shape[0], 1))
        if "unmapped_score" in property_names:
            unmapped_score = np.asarray(plydata.elements[0]["unmapped_score"])[
                ..., np.newaxis
            ]
        else:
            unmapped_score = np.zeros((self._xyz.shape[0], 1))
        self.static_prob = torch.tensor(static_prob, dtype=torch.float32, device="cuda")
        self.static_obs_count = torch.tensor(
            static_obs_count, dtype=torch.float32, device="cuda"
        )
        self.unmapped_score = torch.tensor(
            unmapped_score, dtype=torch.float32, device="cuda"
        )

    def replace_tensor_to_optimizer(self, tensor, name):
        optimizable_tensors = {}
        for group in self.optimizer.param_groups:
            if group["name"] == name:
                stored_state = self.optimizer.state.get(group["params"][0], None)
                stored_state["exp_avg"] = torch.zeros_like(tensor)
                stored_state["exp_avg_sq"] = torch.zeros_like(tensor)

                del self.optimizer.state[group["params"][0]]
                group["params"][0] = nn.Parameter(tensor.requires_grad_(True))
                self.optimizer.state[group["params"][0]] = stored_state

                optimizable_tensors[group["name"]] = group["params"][0]
        return optimizable_tensors

    def _prune_optimizer(self, mask):
        optimizable_tensors = {}
        for group in self.optimizer.param_groups:
            stored_state = self.optimizer.state.get(group["params"][0], None)
            if stored_state is not None:
                stored_state["exp_avg"] = stored_state["exp_avg"][mask]
                stored_state["exp_avg_sq"] = stored_state["exp_avg_sq"][mask]

                del self.optimizer.state[group["params"][0]]
                group["params"][0] = nn.Parameter(
                    (group["params"][0][mask].requires_grad_(True))
                )
                self.optimizer.state[group["params"][0]] = stored_state

                optimizable_tensors[group["name"]] = group["params"][0]
            else:
                group["params"][0] = nn.Parameter(
                    group["params"][0][mask].requires_grad_(True)
                )
                optimizable_tensors[group["name"]] = group["params"][0]
        return optimizable_tensors

    def prune_points(self, mask):
        valid_points_mask = ~mask
        if self.static_prob.shape[0] != valid_points_mask.shape[0]:
            # Ledger desync caught right before the slice. get_xyz is still at
            # the PRE-prune count here, so the shared resizer applies: a grow
            # keeps the accumulated alpha prefix, a shrink rebuilds and counts.
            self.ensure_static_memory_state()
        if self.lineage_id.shape[0] != valid_points_mask.shape[0]:
            self.lineage_id = torch.full(
                (valid_points_mask.shape[0],), UNTRACKED, dtype=torch.int32
            )
        self.static_prob = self.static_prob[valid_points_mask]
        self.static_obs_count = self.static_obs_count[valid_points_mask]
        self.unmapped_score = self.unmapped_score[valid_points_mask]

        optimizable_tensors = self._prune_optimizer(valid_points_mask)

        self._xyz = optimizable_tensors["xyz"]
        self._features_dc = optimizable_tensors["f_dc"]
        self._features_rest = optimizable_tensors["f_rest"]
        self._opacity = optimizable_tensors["opacity"]
        self._scaling = optimizable_tensors["scaling"]
        self._rotation = optimizable_tensors["rotation"]

        self.xyz_gradient_accum = self.xyz_gradient_accum[valid_points_mask]

        self.denom = self.denom[valid_points_mask]
        self.max_radii2D = self.max_radii2D[valid_points_mask]
        self.unique_kfIDs = self.unique_kfIDs[valid_points_mask.cpu()]
        self.n_obs = self.n_obs[valid_points_mask.cpu()]
        self.lineage_id = self.lineage_id[valid_points_mask.cpu()]

    def prune_nonfinite_points(self):
        """Numerical safety: remove Gaussians with any non-finite (Inf/NaN) parameter.
        Inf-scale Gaussians rasterize to NaN pixels and poison PSNR/SSIM/LPIPS eval
        (``np.mean`` over frames -> NaN); they are never valid geometry. Prunes through
        the optimizer when one is live (keeps Adam state consistent), else slices the
        raw parameter tensors directly -- so it is safe to call at final eval/save time
        in either the frontend or backend process. No-op on a healthy map. Returns the
        number of Gaussians removed."""
        with torch.no_grad():
            finite = (
                torch.isfinite(self._xyz).all(dim=1)
                & torch.isfinite(self._scaling).all(dim=1)
                & torch.isfinite(self._rotation).all(dim=1)
                & torch.isfinite(self._opacity).all(dim=1)
                & torch.isfinite(self._features_dc).flatten(1).all(dim=1)
                & torch.isfinite(self._features_rest).flatten(1).all(dim=1)
            )
            n_bad = int((~finite).sum().item())
            if n_bad == 0:
                return 0
            try:
                # Full path: prunes optimizer state + all bookkeeping tensors.
                self.prune_points(~finite)
            except Exception:
                # Fallback (no live optimizer): slice the raw tensors the PLY/render
                # need. self._prune_raw also fixes static-memory tensor lengths.
                self._prune_raw(finite)
            return n_bad

    def _prune_raw(self, keep):
        """Optimizer-free prune: keep only ``keep`` (bool) Gaussians on the parameter
        and bookkeeping tensors. Used when no live optimizer owns the parameters."""
        self._xyz = nn.Parameter(self._xyz[keep].requires_grad_(True))
        self._features_dc = nn.Parameter(self._features_dc[keep].requires_grad_(True))
        self._features_rest = nn.Parameter(
            self._features_rest[keep].requires_grad_(True)
        )
        self._opacity = nn.Parameter(self._opacity[keep].requires_grad_(True))
        self._scaling = nn.Parameter(self._scaling[keep].requires_grad_(True))
        self._rotation = nn.Parameter(self._rotation[keep].requires_grad_(True))
        keep_cpu = keep.cpu()
        n = keep.shape[0]
        for attr in ("max_radii2D", "xyz_gradient_accum", "denom"):
            t = getattr(self, attr, None)
            if isinstance(t, torch.Tensor) and t.shape[0] == n:
                setattr(self, attr, t[keep])
        for attr in ("unique_kfIDs", "n_obs", "lineage_id"):
            t = getattr(self, attr, None)
            if isinstance(t, torch.Tensor) and t.shape[0] == n:
                setattr(self, attr, t[keep_cpu])
        for attr, fill in (
            ("static_prob", 0.7),
            ("static_obs_count", 0.0),
            ("unmapped_score", 0.0),
        ):
            t = getattr(self, attr, None)
            if isinstance(t, torch.Tensor):
                if t.shape[0] == n:
                    setattr(self, attr, t[keep])
                elif 0 < t.shape[0] < n:
                    # append-only desync -> the prefix still maps 1:1, so pad the
                    # tail with defaults and slice, keeping accumulated evidence
                    self.static_memory_extend_count = (
                        getattr(self, "static_memory_extend_count", 0) + 1
                    )
                    tail = torch.full(
                        (n - t.shape[0], 1), float(fill),
                        dtype=torch.float32, device=self._xyz.device,
                    )
                    setattr(
                        self, attr,
                        torch.cat((t.to(device=self._xyz.device), tail), dim=0)[keep],
                    )
                else:  # length drifted downward -> alignment unknowable, rebuild
                    self.static_memory_reset_count = (
                        getattr(self, "static_memory_reset_count", 0) + 1
                    )
                    setattr(
                        self,
                        attr,
                        torch.full(
                            (int(keep.sum().item()), 1),
                            fill,
                            dtype=torch.float32,
                            device=self._xyz.device,
                        ),
                    )

    def cat_tensors_to_optimizer(self, tensors_dict):
        optimizable_tensors = {}
        for group in self.optimizer.param_groups:
            assert len(group["params"]) == 1
            extension_tensor = tensors_dict[group["name"]]
            stored_state = self.optimizer.state.get(group["params"][0], None)
            if stored_state is not None:
                stored_state["exp_avg"] = torch.cat(
                    (stored_state["exp_avg"], torch.zeros_like(extension_tensor)), dim=0
                )
                stored_state["exp_avg_sq"] = torch.cat(
                    (stored_state["exp_avg_sq"], torch.zeros_like(extension_tensor)),
                    dim=0,
                )

                del self.optimizer.state[group["params"][0]]
                group["params"][0] = nn.Parameter(
                    torch.cat(
                        (group["params"][0], extension_tensor), dim=0
                    ).requires_grad_(True)
                )
                self.optimizer.state[group["params"][0]] = stored_state

                optimizable_tensors[group["name"]] = group["params"][0]
            else:
                group["params"][0] = nn.Parameter(
                    torch.cat(
                        (group["params"][0], extension_tensor), dim=0
                    ).requires_grad_(True)
                )
                optimizable_tensors[group["name"]] = group["params"][0]

        return optimizable_tensors

    def densification_postfix(
        self,
        new_xyz,
        new_features_dc,
        new_features_rest,
        new_opacities,
        new_scaling,
        new_rotation,
        new_kf_ids=None,
        new_n_obs=None,
        new_static_prob=None,
        new_static_obs_count=None,
        new_unmapped_score=None,
        new_lineage_id=None,
    ):
        prev_count = self.get_xyz.shape[0]
        d = {
            "xyz": new_xyz,
            "f_dc": new_features_dc,
            "f_rest": new_features_rest,
            "opacity": new_opacities,
            "scaling": new_scaling,
            "rotation": new_rotation,
        }

        optimizable_tensors = self.cat_tensors_to_optimizer(d)
        self._xyz = optimizable_tensors["xyz"]
        self._features_dc = optimizable_tensors["f_dc"]
        self._features_rest = optimizable_tensors["f_rest"]
        self._opacity = optimizable_tensors["opacity"]
        self._scaling = optimizable_tensors["scaling"]
        self._rotation = optimizable_tensors["rotation"]

        self.xyz_gradient_accum = torch.zeros((self.get_xyz.shape[0], 1), device="cuda")
        self.denom = torch.zeros((self.get_xyz.shape[0], 1), device="cuda")
        self.max_radii2D = torch.zeros((self.get_xyz.shape[0]), device="cuda")
        if new_kf_ids is not None:
            self.unique_kfIDs = torch.cat((self.unique_kfIDs, new_kf_ids)).int()
        if new_n_obs is not None:
            self.n_obs = torch.cat((self.n_obs, new_n_obs)).int()
        # Always extend lineage_id (default UNTRACKED) so its length tracks the
        # Gaussian count for any caller; kept on CPU/int like unique_kfIDs. A
        # wrong-length caller tensor is a silent-desync footgun (it would let a
        # later prune_lineage reset every label), so reject it loudly here.
        if new_lineage_id is None:
            new_lineage_id = torch.full(
                (new_xyz.shape[0],), UNTRACKED, dtype=torch.int32
            )
        elif int(new_lineage_id.shape[0]) != int(new_xyz.shape[0]):
            raise ValueError(
                f"new_lineage_id length {int(new_lineage_id.shape[0])} != "
                f"new Gaussian count {int(new_xyz.shape[0])}"
            )
        self.lineage_id = torch.cat((self.lineage_id, new_lineage_id.cpu().int()))
        self._extend_static_memory_state(
            prev_count,
            new_xyz.shape[0],
            new_static_prob,
            new_static_obs_count,
            new_unmapped_score,
        )

    def validate_runtime_state(self):
        """Validate parameter, bookkeeping, and Adam-state cardinality.

        Gaussian extension replaces every optimizer-owned parameter tensor. A
        cardinality mismatch is unsafe for the rasterizer and optimizer, and can
        otherwise appear later as an unrelated asynchronous CUDA failure.
        """

        count = int(self.get_xyz.shape[0])
        tensor_names = (
            "_xyz",
            "_features_dc",
            "_features_rest",
            "_opacity",
            "_scaling",
            "_rotation",
            "max_radii2D",
            "xyz_gradient_accum",
            "denom",
            "unique_kfIDs",
            "n_obs",
            "lineage_id",
            "static_prob",
            "static_obs_count",
            "unmapped_score",
        )
        mismatches = []
        for name in tensor_names:
            value = getattr(self, name, None)
            if isinstance(value, torch.Tensor) and value.ndim > 0:
                if int(value.shape[0]) != count:
                    mismatches.append(f"{name}={int(value.shape[0])}")
        if mismatches:
            raise RuntimeError(
                "Gaussian state length mismatch: "
                f"expected {count}; " + ", ".join(mismatches)
            )

        optimizer_names = {
            "xyz": "_xyz",
            "f_dc": "_features_dc",
            "f_rest": "_features_rest",
            "opacity": "_opacity",
            "scaling": "_scaling",
            "rotation": "_rotation",
        }
        if self.optimizer is None:
            return count
        for group in self.optimizer.param_groups:
            group_name = group.get("name")
            if group_name not in optimizer_names or len(group.get("params", [])) != 1:
                continue
            parameter = group["params"][0]
            owned = getattr(self, optimizer_names[group_name])
            if parameter is not owned:
                raise RuntimeError(
                    f"Gaussian optimizer group {group_name} owns a stale parameter"
                )
            state = self.optimizer.state.get(parameter)
            if state is None:
                continue
            for state_name in ("exp_avg", "exp_avg_sq"):
                moment = state.get(state_name)
                if isinstance(moment, torch.Tensor) and moment.shape != parameter.shape:
                    raise RuntimeError(
                        "Gaussian optimizer state shape mismatch: "
                        f"{group_name}.{state_name}={tuple(moment.shape)} "
                        f"parameter={tuple(parameter.shape)}"
                    )
        return count

    def _extend_static_memory_state(
        self,
        prev_count,
        new_count,
        new_static_prob=None,
        new_static_obs_count=None,
        new_unmapped_score=None,
    ):
        if self.static_prob.shape[0] != prev_count:
            # Desync caught at append time. get_xyz already holds prev+new, so
            # the shared resizer keeps whatever prefix is still aligned and
            # default-fills the rest; it counts the lossy case itself.
            self.ensure_static_memory_state()
            return
        device = self.get_xyz.device
        if new_static_prob is None:
            new_static_prob = torch.full(
                (new_count, 1), 0.7, dtype=torch.float32, device=device
            )
        if new_static_obs_count is None:
            new_static_obs_count = torch.zeros(
                (new_count, 1), dtype=torch.float32, device=device
            )
        if new_unmapped_score is None:
            new_unmapped_score = torch.zeros(
                (new_count, 1), dtype=torch.float32, device=device
            )
        self.static_prob = torch.cat(
            (self.static_prob, new_static_prob.detach()), dim=0
        )
        self.static_obs_count = torch.cat(
            (self.static_obs_count, new_static_obs_count.detach()), dim=0
        )
        self.unmapped_score = torch.cat(
            (self.unmapped_score, new_unmapped_score.detach()), dim=0
        )

    def densify_and_split(self, grads, grad_threshold, scene_extent, N=2):
        n_init_points = self.get_xyz.shape[0]
        # Extract points that satisfy the gradient condition
        padded_grad = torch.zeros((n_init_points), device="cuda")
        padded_grad[: grads.shape[0]] = grads.squeeze()
        selected_pts_mask = torch.where(padded_grad >= grad_threshold, True, False)
        selected_pts_mask = torch.logical_and(
            selected_pts_mask,
            torch.max(self.get_scaling, dim=1).values
            > self.percent_dense * scene_extent,
        )

        stds = self.get_scaling[selected_pts_mask].repeat(N, 1)
        # Counter-based keyed RNG (causal-twin): identical split jitter across
        # lifecycle arms at the same logical densify event, independent of the
        # global torch RNG stream (which desyncs the arms). See utils/causal_twin.
        samples = self._counter_rng().normal_like(
            stds, "densify_split", self._next_rng_event("densify_split")
        )
        rots = build_rotation(self._rotation[selected_pts_mask]).repeat(N, 1, 1)
        new_xyz = torch.bmm(rots, samples.unsqueeze(-1)).squeeze(-1) + self.get_xyz[
            selected_pts_mask
        ].repeat(N, 1)
        new_scaling = self.scaling_inverse_activation(
            self.get_scaling[selected_pts_mask].repeat(N, 1) / (0.8 * N)
        )
        new_rotation = self._rotation[selected_pts_mask].repeat(N, 1)
        new_features_dc = self._features_dc[selected_pts_mask].repeat(N, 1, 1)
        new_features_rest = self._features_rest[selected_pts_mask].repeat(N, 1, 1)
        new_opacity = self._opacity[selected_pts_mask].repeat(N, 1)

        new_kf_id = self.unique_kfIDs[selected_pts_mask.cpu()].repeat(N)
        new_n_obs = self.n_obs[selected_pts_mask.cpu()].repeat(N)
        self.ensure_static_memory_state()
        new_static_prob = self.static_prob[selected_pts_mask].repeat(N, 1)
        new_static_obs_count = self.static_obs_count[selected_pts_mask].repeat(N, 1)
        new_unmapped_score = self.unmapped_score[selected_pts_mask].repeat(N, 1)
        new_lineage_id = self.lineage_id[selected_pts_mask.cpu()].repeat(N)

        self.densification_postfix(
            new_xyz,
            new_features_dc,
            new_features_rest,
            new_opacity,
            new_scaling,
            new_rotation,
            new_kf_ids=new_kf_id,
            new_n_obs=new_n_obs,
            new_static_prob=new_static_prob,
            new_static_obs_count=new_static_obs_count,
            new_unmapped_score=new_unmapped_score,
            new_lineage_id=new_lineage_id,
        )

        prune_filter = torch.cat(
            (
                selected_pts_mask,
                torch.zeros(N * selected_pts_mask.sum(), device="cuda", dtype=bool),
            )
        )

        self.prune_points(prune_filter)

    def densify_and_clone(self, grads, grad_threshold, scene_extent):
        # Extract points that satisfy the gradient condition
        selected_pts_mask = torch.where(
            torch.norm(grads, dim=-1) >= grad_threshold, True, False
        )
        selected_pts_mask = torch.logical_and(
            selected_pts_mask,
            torch.max(self.get_scaling, dim=1).values
            <= self.percent_dense * scene_extent,
        )

        new_xyz = self._xyz[selected_pts_mask]
        new_features_dc = self._features_dc[selected_pts_mask]
        new_features_rest = self._features_rest[selected_pts_mask]
        new_opacities = self._opacity[selected_pts_mask]
        new_scaling = self._scaling[selected_pts_mask]
        new_rotation = self._rotation[selected_pts_mask]

        new_kf_id = self.unique_kfIDs[selected_pts_mask.cpu()]
        new_n_obs = self.n_obs[selected_pts_mask.cpu()]
        self.ensure_static_memory_state()
        new_static_prob = self.static_prob[selected_pts_mask]
        new_static_obs_count = self.static_obs_count[selected_pts_mask]
        new_unmapped_score = self.unmapped_score[selected_pts_mask]
        new_lineage_id = self.lineage_id[selected_pts_mask.cpu()]
        self.densification_postfix(
            new_xyz,
            new_features_dc,
            new_features_rest,
            new_opacities,
            new_scaling,
            new_rotation,
            new_kf_ids=new_kf_id,
            new_n_obs=new_n_obs,
            new_static_prob=new_static_prob,
            new_static_obs_count=new_static_obs_count,
            new_unmapped_score=new_unmapped_score,
            new_lineage_id=new_lineage_id,
        )

    def densify_and_prune(self, max_grad, min_opacity, extent, max_screen_size):
        grads = self.xyz_gradient_accum / self.denom
        grads[grads.isnan()] = 0.0

        self.densify_and_clone(grads, max_grad, extent)
        self.densify_and_split(grads, max_grad, extent)

        prune_mask = (self.get_opacity < min_opacity).squeeze()
        if max_screen_size:
            big_points_vs = self.max_radii2D > max_screen_size
            big_points_ws = self.get_scaling.max(dim=1).values > 0.1 * extent

            prune_mask = torch.logical_or(
                torch.logical_or(prune_mask, big_points_vs), big_points_ws
            )
        self.prune_points(prune_mask)

    def add_densification_stats(self, viewspace_point_tensor, update_filter):
        self.xyz_gradient_accum[update_filter] += torch.norm(
            viewspace_point_tensor.grad[update_filter, :2], dim=-1, keepdim=True
        )
        self.denom[update_filter] += 1

    def compress_deletion(
        self, op_floor=0.05, op_and_foot_th=0.10, foot_th_m=0.02, log_prefix=""
    ):
        """Map-compression deletion pass (R3-P05, STEP4).

        WHY THIS EXISTS. The paper's compactness axis is currently a false lever:
        deferred's was under-seeding, S6's was a degenerate lifecycle. This adds a
        GENUINE prune-style compression: delete Gaussians that contribute almost
        nothing to the rendered output. The offline gate (results/evidence/
        R3-P05-map-compression-step1.md, 4 seqs × prune seed-0) showed a safe set
        exists: deleting sigmoid opacity < 0.01 costs 0.000 dB at 10-18%; < 0.05
        costs ≤ 0.016 dB at 12.6-23.6%; the set is dynamics-agnostic (vac_excess≈0)
        and surface-embedded (distance-to-TSDF flat), so it is a pure
        output-contribution axis needing no masks/TSDF.

        Deletion rule (recommended default from STEP2/3):
            delete if (sigmoid_op < op_floor)
                 OR (sigmoid_op < op_and_foot_th  AND  max_scale_axis < foot_th_m)
        ``foot_th_m=0`` disables the joint half, leaving pure ``op_floor``.

        Live-loop safety: when a live optimizer owns the parameters (mid-mapping,
        the STEP4 case), it routes through ``prune_points`` -> ``_prune_optimizer``
        so the removed set's Adam state is sliced too (the critical correctness
        requirement — leaving orphaned optimizer state behind would poison the next
        ``optimizer.step()``). The offline-probe path (no optimizer) uses
        ``_prune_raw``. Both slice every bookkeeping tensor (xyz, scaling, rotation,
        opacity, static_* ledger, lineage). Return the number removed (0 on a
        length mismatch that would desync the ledger)."""
        if op_floor <= 0.0 and foot_th_m <= 0.0:
            return 0
        N = self._xyz.shape[0]
        if N == 0:
            return 0
        sig = self.get_opacity.reshape(-1)  # sigmoid opacity (N,)
        foot = self.get_scaling.max(dim=1).values  # max scale axis in m (N,)
        mask = sig < op_floor
        if foot_th_m > 0.0:
            mask = mask | ((sig < op_and_foot_th) & (foot < foot_th_m))
        remove_mask = mask
        n_remove = int(remove_mask.sum().item())
        if n_remove == 0:
            return 0
        # keep = NOT removed. Live optimizer => prune_points (slices Adam state).
        if self.optimizer is not None:
            self.prune_points(remove_mask.to(self._xyz.device))
        else:
            self._prune_raw((~remove_mask).to(self._xyz.device))
        Log(f"{log_prefix}compress_deletion: removed {n_remove}/{N} "
            f"({n_remove / max(N, 1) * 100:.1f}%) -> {self._xyz.shape[0]}")
        return n_remove
