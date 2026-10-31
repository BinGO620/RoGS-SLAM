import json
import math
import os
import time
import traceback
import types

import numpy as np
import torch
import torch.multiprocessing as mp
from tqdm import tqdm

from gaussian_splatting.gaussian_renderer import render
from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2, getWorld2View2
from gaussian_splatting.utils.loss_utils import l1_loss, ssim
from utils.causal_twin import CounterRNG, UNTRACKED, base_rng_key
from utils.logging_utils import Log


def transient_cam_from_msg(fx, fy, cx, cy, R, T, device="cuda"):
    """transient_map（默认关）的 per-frame 插入用相机：把消息里的**数值**还原成 torch tensor。

    **契约（缺了会崩）**：`insert_candidate_gaussians` 走 `getWorld2View2(cam.R, cam.T)`，
    后者内部调用 `translate.to(R.device)` ⇒ `R`/`T` **必须是 torch tensor**，不能是 numpy。
    快筛第二次崩溃正是踩在这里（首次崩在发消息侧的 `np.asarray(CUDA tensor)`）——
    两次都说明"数值往返"的边界要有显式契约，故抽成这个纯函数以便单测钉住。
    """
    cam = types.SimpleNamespace()
    cam.fx, cam.fy, cam.cx, cam.cy = float(fx), float(fy), float(cx), float(cy)
    cam.R = torch.as_tensor(np.asarray(R), dtype=torch.float32, device=device)
    cam.T = torch.as_tensor(np.asarray(T), dtype=torch.float32, device=device)
    return cam


# ── transient_map 修正案 2（Tfit）：插入后局部拟合 ──────────────────────────────
# 预算/超参从探针 P2 原样锁定（scripts/02_analysis/dyn_probe.py fit_dynamic；
# prereg_dyn_probe §5；修正案 2「N 与 lr 锁定」）⇒ lr 不是 config 旋钮，config 只携带
# fit_iters（默认 0 = 关 = 与主线逐位一致）。损失 = 掩码内 RGB L1 + 0.1×掩码内深度 L1(m)，
# 深度源 = 系统入流的传感器深度（在线可部署口径；探针用 GT——该差异属被测的因果差距，如实登记）。
TRANSIENT_FIT_LRS = {"xyz": 5e-4, "scale": 5e-3, "rot": 1e-3, "opa": 5e-2, "dc": 5e-3}
TRANSIENT_FIT_ZNEAR, TRANSIENT_FIT_ZFAR = 0.01, 100.0  # 与 Camera.init_from_gui 同值


def transient_obs_from_msg(image, depth, mask, device="cuda"):
    """Tfit 观测往返契约：把消息里的 numpy 观测还原成渲染/损失用的 torch tensor。

    image (3,H,W) float32 [0,1]；depth (H,W) float32 米（无效=0）；mask (H,W) bool。
    形状不一致即抛错（契约测试钉住）——与 transient_cam_from_msg 同一纪律：数值往返的
    边界必须有显式契约，替身要模拟真实类型。
    """
    img = torch.as_tensor(np.asarray(image), dtype=torch.float32, device=device)
    dpt = torch.as_tensor(np.asarray(depth), dtype=torch.float32, device=device)
    msk = torch.as_tensor(np.asarray(mask), dtype=torch.bool, device=device)
    if img.ndim != 3 or dpt.ndim != 2 or msk.ndim != 2 \
            or img.shape[1:] != dpt.shape or msk.shape != dpt.shape:
        raise ValueError(
            f"transient obs shape mismatch: img{tuple(img.shape)} "
            f"dpt{tuple(dpt.shape)} mask{tuple(msk.shape)}"
        )
    return {"image": img, "depth": dpt, "mask": msk}


class _TransientFitCam:
    """渲染器所需的最小相机视图（插入帧不是 KF，后端没有它的常驻 Camera 对象）。

    属性集 = gaussian_renderer.render 的读取面（FoVx/FoVy/image_height/image_width/
    world_view_transform/full_proj_transform/camera_center），矩阵约定与 utils/camera_utils.py
    的 Camera **逐式相同** ⇒ 拟合渲染与插入反投影（getWorld2View2(cam.R, cam.T)）同约定。
    """

    def __init__(self, fx, fy, cx, cy, R, T, width, height, device="cuda"):
        self.fx, self.fy, self.cx, self.cy = float(fx), float(fy), float(cx), float(cy)
        self.image_width, self.image_height = int(width), int(height)
        self.FoVx = 2 * math.atan(self.image_width / (2 * self.fx))
        self.FoVy = 2 * math.atan(self.image_height / (2 * self.fy))
        # R/T 来自 transient_cam_from_msg ⇒ 生产环境是 **CUDA tensor**（快筛 #3 秒崩的教训，
        # 与首次快筛同一坑类）⇒ 统一经 to_np 过边界，禁 np.asarray 直上。
        to_np = lambda x: (x.detach().cpu().numpy() if hasattr(x, "detach") else np.asarray(x))  # noqa: E731
        self.world_view_transform = getWorld2View2(
            torch.as_tensor(to_np(R), dtype=torch.float32, device=device),
            torch.as_tensor(to_np(T), dtype=torch.float32, device=device),
        ).transpose(0, 1)
        self.projection_matrix = getProjectionMatrix2(
            znear=TRANSIENT_FIT_ZNEAR, zfar=TRANSIENT_FIT_ZFAR,
            fx=self.fx, fy=self.fy, cx=self.cx, cy=self.cy,
            W=self.image_width, H=self.image_height,
        ).transpose(0, 1).to(device=device)
        self.full_proj_transform = (
            self.world_view_transform.unsqueeze(0).bmm(
                self.projection_matrix.unsqueeze(0)
            )
        ).squeeze(0)
        self.camera_center = self.world_view_transform.inverse()[3, :3]
        # 渲染器读取面（gaussian_renderer.render）还包括位姿 delta：拟合用固定插入位姿 ⇒ 零。
        # 与 Camera 的 nn.Parameter(zeros(3)) 同形；不做 requires_grad（位姿在拟合中不优化）。
        self.cam_rot_delta = torch.zeros(3, device=device)
        self.cam_trans_delta = torch.zeros(3, device=device)


def transient_fit_build_optimizer(g):
    """Tfit 的局部 Adam：五参数组、锁定 lr（探针 P2 原样）。独立于主地图优化器
    （不共享状态；拟合后主优化器对这批行的动量略陈旧——无害，瞬态行 ~5 帧内即被硬删）。"""
    groups = [
        (g._xyz, TRANSIENT_FIT_LRS["xyz"]),
        (g._scaling, TRANSIENT_FIT_LRS["scale"]),
        (g._rotation, TRANSIENT_FIT_LRS["rot"]),
        (g._opacity, TRANSIENT_FIT_LRS["opa"]),
        (g._features_dc, TRANSIENT_FIT_LRS["dc"]),
    ]
    opt = torch.optim.Adam([{"params": [p], "lr": lr} for p, lr in groups])
    return opt, groups


def transient_fit_mask_grads(groups, sel):
    """「静态集 detach」的实现：选择行以外的梯度清零。

    Adam 对 grad≡0 的行更新恒为精确 0（m/v 保持 0 ⇒ 步长 0）⇒ 静态集与旧瞬态**逐位不动**；
    features_rest 等不在优化器里的参数永不 step（无需掩码）。"""
    with torch.no_grad():
        for p, _lr in groups:
            if p.grad is not None:
                p.grad[~sel] = 0


from utils.multiprocessing_utils import clone_obj, release_cuda_ipc_cache
from utils.pose_utils import update_pose
from utils.reliability import ReliabilityRecorder, get_reliability_config
from utils.mapping_probe import (
    MappingEMARecorder,
    MappingProbeRecorder,
    mapping_probe_enabled,
    mapping_probe_interval,
)
from utils.mapping_weight import mapping_soft_floor
from utils.mope_layer import mope_cfg, mope_enabled
from utils.slam_utils import get_loss_mapping
from utils.semantic_mask import (
    get_or_compute_dynamic_mask,
    mask_mapping_enabled,
    write_semantic_timing_summary,
)
from utils import alpha_lifecycle
from utils import occupancy_memory
from utils import obsdebt
from utils.tri_reliability import (
    TriReliabilityRecorder,
    compute_tri_reliability,
    get_tri_reliability_config,
    tri_reliability_policy_enabled,
)


class BackEnd(mp.Process):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.gaussians = None
        self.pipeline_params = None
        self.opt_params = None
        self.background = None
        self.cameras_extent = None
        self.frontend_queue = None
        self.backend_queue = None
        self.live_mode = False

        self.pause = False
        self.device = "cuda"
        self.dtype = torch.float32
        self.monocular = config["Training"]["monocular"]
        # Counter-based keyed RNG (causal-twin): the backend runs in a separate
        # (spawn) process where the global torch/random seed from slam.py does NOT
        # propagate, so its stochastic sites are keyed by (sequence, seed) instead.
        self.rng = CounterRNG(*base_rng_key(config))
        self.iteration_count = 0
        self.last_sent = 0
        self.occ_aware_visibility = {}
        self.viewpoints = {}
        self.current_window = []
        self.initialized = not self.monocular
        self.keyframe_optimizers = None
        self.mapping_time_s = 0.0
        self.mapping_calls = 0
        self.mapping_iterations = 0
        self.color_refinement_time_s = 0.0
        self.color_refinement_iterations = 26000
        # Arm-activity ledger. R2-P02-E2 shipped an inert treatment arm all the way
        # to make-or-break because "the mechanism did nothing" was visible only in
        # a consolelog nobody re-read. These totals ride out through
        # backend_timing.json into efficiency_raw.csv so a zero-activity treatment
        # arm is a *column in the results table*, not a forensic dig.
        self.alpha_lifecycle_steps = 0
        self.alpha_lifecycle_skips = 0
        self.alpha_exit_reset_total = 0
        self.alpha_carve_total = 0
        # T3 arm-activity ledger. Same contract as the fill counters below: an arm
        # labelled `semantic_alpha_override` that reports 0 here did not run its
        # treatment, and no ATE/PSNR number from it means anything.
        self.alpha_sem_override_total = 0
        # L1b evidence-gate arm-activity ledger (治续命). Same contract: an arm
        # labelled `evidence_gate` reporting capped=0 here did not run its
        # treatment. `no_mask_kfs` counts the fail-open steps (mask-free arm
        # or frontend cache miss) so "gate 0" is attributable, never silent.
        self.alpha_gate_capped_total = 0
        self.alpha_gate_prevented_rise_sum = 0.0
        self.alpha_gate_no_mask_kfs = 0
        # L1c occupancy-memory arm-activity ledger (时序先验). Same contract as
        # the gate counters: an arm labelled `occupancy_memory` reporting
        # decayed=0 here did not run its treatment. `lt_guard_total` makes
        # "did the decay ever find reachable alpha" auditable (the guard-fail
        # risk is registered in prereg_L1c_occupancy.md).
        self.occ_decay_events_total = 0
        self.occ_warm_prims_total = 0
        self.occ_alpha_lt_guard_total = 0
        self.occ_no_mask_kfs = 0
        self._occ_memory = None   # OccupancyMemory, lazily built on first occ KF
        # L1e seam-carve arm-activity ledger (D2-008 缝隙带救援). Same contract as
        # the gate/occ counters: an arm labelled `seam_carve` reporting carved=0
        # here did not run its treatment. `no_mask_kfs` counts fail-open steps;
        # `vacated_px_total` makes "was there any vacated region at all" auditable
        # (carved=0 with vacated_px=0 means the region detector found nothing --
        # attributable, never silent).
        self.seam_carve_total = 0
        self.seam_vacated_px_total = 0
        self.seam_no_mask_kfs = 0
        self._seam_history = {}   # kf_uid -> (mask HxW bool, kf_uid) sliding window
        self.alpha_fill_inserted_total = 0
        # Fill-side attribution. `alpha_fill_inserted_total == 0` is ambiguous on its
        # own -- a broken fill and a fill that correctly found no hole look identical
        # -- and that ambiguity is what let an inert arm reach make-or-break in E2.
        # These two split it: cleared_px == 0 means the post-exit re-render still shows
        # an opaque surface (reset lowered per-Gaussian opacity but accumulated alpha
        # stayed above fill_min_opacity); cleared_px > 0 with vacated_px == 0 means the
        # cleared pixels were not occluding observed background, i.e. exit opened no
        # hole and there is genuinely nothing to fill.
        self.alpha_fill_cleared_px_total = 0
        self.alpha_fill_vacated_px_total = 0
        self.alpha_fill_steps = 0
        # L1f 观测债补偿（default-off; prereg_L1f_obsdebt / D2-011 ②）。债账本与
        # 迭代配额诊断计数；obsdebt=False 时整条路径不进入（与主线逐位一致）。
        self._obsdebt_ledger = None
        self.obsdebt_boost_steps_total = 0
        self.obsdebt_fill_realloc_events = 0
        self.reliability_recorder = ReliabilityRecorder(config, "mapping")
        self.mapping_probe = MappingProbeRecorder(config)
        self.mapping_ema = MappingEMARecorder(config)
        # Register the EMA recorder so the probe can read its state
        from utils.mapping_probe import set_global_ema_recorder
        set_global_ema_recorder(self.mapping_ema)
        self.tri_reliability_recorder = TriReliabilityRecorder(config, "mapping")
        self._reliability_observed_labels = set()

    def set_hyperparams(self):
        self.save_results = self.config["Results"]["save_results"]

        self.init_itr_num = self.config["Training"]["init_itr_num"]
        self.init_gaussian_update = self.config["Training"]["init_gaussian_update"]
        self.init_gaussian_reset = self.config["Training"]["init_gaussian_reset"]
        self.init_gaussian_th = self.config["Training"]["init_gaussian_th"]
        self.init_gaussian_extent = (
            self.cameras_extent * self.config["Training"]["init_gaussian_extent"]
        )
        self.mapping_itr_num = self.config["Training"]["mapping_itr_num"]
        self.async_iter_per_kf = int(self.config["Training"].get("async_iter_per_kf", 10))
        self.gaussian_update_every = self.config["Training"]["gaussian_update_every"]
        self.gaussian_update_offset = self.config["Training"]["gaussian_update_offset"]
        self.gaussian_th = self.config["Training"]["gaussian_th"]
        # R3-P05 STEP4: map-compression deletion. Read from optional CompressDeletion
        # section (absent => disabled, mapping stays byte-identical to base).
        cd = self.config.get("CompressionDeletion", {}) or {}
        if isinstance(cd, dict):
            cd = {k: (v if v is not None else 0.0)
                  for k, v in cd.items() if k in ("op_floor", "op_and_foot_th", "foot_th_m", "enabled")}
        self.compress_enabled = bool(cd.get("enabled", False))
        self.compress_op_floor = float(cd.get("op_floor", 0.05))
        self.compress_op_and_foot_th = float(cd.get("op_and_foot_th", 0.10))
        self.compress_foot_th_m = float(cd.get("foot_th_m", 0.02))
        # depth_reanchor D1: None unless enabled (default OFF)
        from utils.depth_reanchor import DepthReanchorer, depth_reanchor_enabled
        self.reanchor = (DepthReanchorer(self.config)
                         if depth_reanchor_enabled(self.config) else None)
        self.gaussian_extent = (
            self.cameras_extent * self.config["Training"]["gaussian_extent"]
        )
        self.gaussian_reset = self.config["Training"]["gaussian_reset"]
        self.size_threshold = self.config["Training"]["size_threshold"]
        self.window_size = self.config["Training"]["window_size"]
        self.single_thread = (
            self.config["Dataset"]["single_thread"]
            if "single_thread" in self.config["Dataset"]
            else False
        )
        self.color_refinement_iterations = int(
            self.config["Training"].get("color_refinement_iterations", 26000)
        )
        if self.color_refinement_iterations < 0:
            raise ValueError("Training.color_refinement_iterations must be >= 0")

    def _log_promoted_parameter_health(self, inserted):
        if inserted <= 0:
            return
        tensors = {
            "xyz": self.gaussians._xyz[-inserted:],
            "features_dc": self.gaussians._features_dc[-inserted:],
            "features_rest": self.gaussians._features_rest[-inserted:],
            "opacity": self.gaussians._opacity[-inserted:],
            "scaling": self.gaussians._scaling[-inserted:],
            "rotation": self.gaussians._rotation[-inserted:],
        }
        invalid = {
            name: int((~torch.isfinite(value).flatten(1).all(dim=1)).sum().item())
            for name, value in tensors.items()
        }
        scale = self.gaussians.get_scaling[-inserted:]
        Log(
            "Deferred promotion health: "
            f"invalid={invalid}, scale_min={float(scale.min().item()):.6f}, "
            f"scale_max={float(scale.max().item()):.6f}, "
            "scale_init="
            f"{getattr(self.gaussians, 'last_scale_initialization', 'unknown')}"
        )

    def add_next_kf(self, frame_idx, viewpoint, init=False, scale=2.0, depth_map=None):
        self.gaussians.extend_from_pcd_seq(
            viewpoint, kf_id=frame_idx, init=init, scale=scale, depthmap=depth_map
        )

    def reset(self):
        self.iteration_count = 0
        self.occ_aware_visibility = {}
        self.viewpoints = {}
        self.current_window = []
        self.initialized = not self.monocular
        self.keyframe_optimizers = None

        # remove all gaussians
        self.gaussians.prune_points(self.gaussians.unique_kfIDs >= 0)
        # remove everything from the queues
        while not self.backend_queue.empty():
            self.backend_queue.get()

    def initialize_map(self, cur_frame_idx, viewpoint):
        mapping_start = time.perf_counter()
        for mapping_iteration in range(self.init_itr_num):
            self.iteration_count += 1
            render_pkg = render(
                viewpoint, self.gaussians, self.pipeline_params, self.background
            )
            (
                image,
                viewspace_point_tensor,
                visibility_filter,
                radii,
                depth,
                opacity,
                n_touched,
            ) = (
                render_pkg["render"],
                render_pkg["viewspace_points"],
                render_pkg["visibility_filter"],
                render_pkg["radii"],
                render_pkg["depth"],
                render_pkg["opacity"],
                render_pkg["n_touched"],
            )
            loss_init = get_loss_mapping(
                self.config, image, depth, viewpoint, opacity, initialization=True
            )
            loss_init.backward()

            with torch.no_grad():
                self.gaussians.max_radii2D[visibility_filter] = torch.max(
                    self.gaussians.max_radii2D[visibility_filter],
                    radii[visibility_filter],
                )
                self.gaussians.add_densification_stats(
                    viewspace_point_tensor, visibility_filter
                )
                if mapping_iteration % self.init_gaussian_update == 0:
                    self.gaussians.densify_and_prune(
                        self.opt_params.densify_grad_threshold,
                        self.init_gaussian_th,
                        self.init_gaussian_extent,
                        None,
                    )

                if self.iteration_count == self.init_gaussian_reset or (
                    self.iteration_count == self.opt_params.densify_from_iter
                ):
                    self.gaussians.reset_opacity()

                self.gaussians.optimizer.step()
                self.gaussians.optimizer.zero_grad(set_to_none=True)

        self.occ_aware_visibility[cur_frame_idx] = (n_touched > 0).long()
        self.mapping_time_s += time.perf_counter() - mapping_start
        self.mapping_calls += 1
        self.mapping_iterations += self.init_itr_num
        self.observe_mapping_reliability(
            image,
            depth,
            opacity,
            viewpoint,
            f"keyframe_{cur_frame_idx:06d}",
            use_exposure=False,
            visibility_filter=visibility_filter,
        )
        Log("Initialized map")
        return render_pkg

    def _compute_ema_weight(self, image, depth, viewpoint):
        """If Step C EMA is enabled, compute the per-pixel weight map from the
        lagged-residual EMA state.  Returns (weight_map, c_mass) -- or (None, None)
        when the EMA arm is off, so the call site is always safe.

        NOTE: This method is READ-ONLY -- it does NOT update the EMA state.
        Call ``_update_ema_state()`` once after the mapping loop to advance the state.
        """
        if not self.mapping_ema.is_enabled():
            return None, None
        gt_image = viewpoint.original_image.cuda()
        rgb_valid = (gt_image.sum(dim=0) > self.config["Training"]["rgb_boundary_threshold"]).view_as(depth)
        w_map, c_mass = self.mapping_ema.compute_weights(rgb_valid, image.dtype)
        return w_map, c_mass

    def _mope_mapping_soft(self, depth, viewpoint):
        """MoPe 用途②（default-off）：取该关键帧持久后验 `p_t` 作逐像素建图权重。

        来源 = 前端 `_mope_step` 把 `p_t` **stash 在 Camera 上**（`viewpoint.mope_p`），
        与既有 `viewpoint.dynamic_mask` 同一条跨进程通路（KF 消息携带同一 Camera 对象，
        clean() 只作用于非 KF 帧）。本方法**只读**；缺失/形状不符/开关关 ⇒ None
        （⇒ get_loss_mapping 走既有路径，逐位一致）。
        """
        if not mope_enabled(self.config):
            return None
        if not mope_cfg(self.config).get("use_mapping", False):
            return None
        p = getattr(viewpoint, "mope_p", None)
        if p is None:
            return None
        import numpy as _np
        arr = _np.asarray(p, dtype=_np.float32)
        if arr.ndim == 3:
            arr = arr[0]
        if tuple(arr.shape) != tuple(depth.shape[-2:]):
            return None
        # 生效证据（DISCIPLINE 9：静默组件须有计数）——后端侧落盘计数，供生效门读。
        self._mope_map_apply_n = getattr(self, "_mope_map_apply_n", 0) + 1
        return torch.from_numpy(arr).to(device=depth.device, dtype=depth.dtype)[None]

    def _update_ema_state(self, last_image, last_depth, last_viewpoint):
        """Advance the EMA state with the last frame's residuals.

        Call once AFTER the mapping loop, so all probes see the same pre-update state.
        """
        if not self.mapping_ema.is_enabled():
            return
        gt_image = last_viewpoint.original_image.cuda()
        rgb_err = torch.abs(last_image - gt_image).mean(dim=0, keepdim=True).detach()
        depth_err = torch.abs(last_depth - torch.from_numpy(last_viewpoint.depth).to(
            dtype=torch.float32, device=last_depth.device
        )[None]).detach()
        self.mapping_ema.update(rgb_err, depth_err)

    def observe_mapping_probe(self, viewpoint):
        """exp39 Phase-0 gradient attribution (default-off, subsampled).

        Runs on its own render graph and reads gradients with ``autograd.grad`` only, so
        it neither steps anything nor perturbs the mapping loss it observes.
        """
        if not mapping_probe_enabled(self.config):
            return
        interval = mapping_probe_interval(self.config)
        if interval <= 0 or (self.iteration_count % interval) != 0:
            return
        self.mapping_probe.observe(
            gaussians=self.gaussians,
            viewpoint=viewpoint,
            pipeline_params=self.pipeline_params,
            background=self.background,
            dynamic_mask=get_or_compute_dynamic_mask(self.config, viewpoint)
            if mask_mapping_enabled(self.config)
            else None,
            floor=mapping_soft_floor(self.config),
            ema_recorder=self.mapping_ema,
        )

    def observe_mapping_reliability(
        self,
        image,
        depth,
        opacity,
        viewpoint,
        label,
        use_exposure=True,
        visibility_filter=None,
    ):
        if label in self._reliability_observed_labels:
            return
        reliability_metrics = self.reliability_recorder.observe(
            image,
            depth,
            opacity,
            viewpoint,
            label,
            use_exposure=use_exposure,
        )
        tri_metrics = self.tri_reliability_recorder.observe(
            image,
            depth,
            opacity,
            viewpoint,
            label,
            gaussians=self.gaussians,
            visibility_filter=visibility_filter,
            use_exposure=use_exposure,
        )
        self._reliability_observed_labels.add(label)
        reliability_config = get_reliability_config(self.config)
        save_interval = int(reliability_config.get("save_interval", 20))
        try:
            frame_id = int(label.rsplit("_", 1)[1])
        except ValueError:
            frame_id = None
        if (
            reliability_metrics is not None
            and frame_id is not None
            and save_interval > 0
            and frame_id % save_interval == 0
        ):
            Log(
                "Reliability mapping "
                f"{label}: mean={reliability_metrics['mean_reliability']:.4f}, "
                f"low_ratio={reliability_metrics['low_reliability_ratio']:.4f}"
            )
        tri_config = get_tri_reliability_config(self.config)
        tri_save_interval = int(tri_config.get("save_interval", 20))
        if (
            tri_metrics is not None
            and frame_id is not None
            and tri_save_interval > 0
            and frame_id % tri_save_interval == 0
        ):
            Log(
                "TriReliability mapping "
                f"{label}: dynamic={tri_metrics['mean_dynamic_evidence']:.4f}, "
                f"unmapped={tri_metrics['mean_unmapped_evidence']:.4f}, "
                f"boundary={tri_metrics['mean_boundary_evidence']:.4f}"
            )

    # ── transient_map 修正案 2（Tfit）：插入后局部拟合（默认关；fit_iters=0 时不进入）──

    def _transient_fit(self, cam, lineage_id, obs, fit_iters):
        """对**当批**（lineage == lineage_id，含其克隆后代）瞬态基元做 N 步局部拟合。

        损失/优化器 = 探针 P2 原样（模块头注释与修正案 2）；渲染相机 = _TransientFitCam
        （与插入反投影 getWorld2View2(cam.R, cam.T) 同约定）。返回证据 dict（进 consolelog，
        供判读与关卡① 抽验）。fit_iters<=0 或当批为空 ⇒ 不进入（两态安全）。
        """
        g = self.gaussians
        g.ensure_lineage_state()
        sel = (g.lineage_id == int(lineage_id))
        n_sel = int(sel.sum().item())
        if fit_iters <= 0 or n_sel == 0:
            return {"iters": 0, "n_sel": n_sel}
        device = g.get_xyz.device
        image = obs["image"].to(device)
        depth_gt = obs["depth"].to(device)
        mask = obs["mask"].to(device)
        fit_cam = _TransientFitCam(cam.fx, cam.fy, cam.cx, cam.cy, cam.R, cam.T,
                                   image.shape[2], image.shape[1], device=device)
        opt, groups = transient_fit_build_optimizer(g)
        m_rgb = (image > 0) & mask.unsqueeze(0)
        m_d = (torch.isfinite(depth_gt) & (depth_gt > 0)) & mask
        opa0 = float(torch.sigmoid(g._opacity.detach()[sel]).mean())
        losses = []
        for it in range(int(fit_iters)):
            pkg = render(fit_cam, g, self.pipeline_params, self.background)
            r = torch.clamp(pkg["render"], 0.0, 1.0)
            loss = torch.abs(r[m_rgb] - image[m_rgb]).mean()
            if bool(m_d.any()):
                loss = loss + 0.1 * torch.abs(
                    pkg["depth"].squeeze()[m_d] - depth_gt[m_d]).mean()
            if not torch.isfinite(loss):
                return {"iters": it, "n_sel": n_sel, "failed": "loss nan",
                        "loss_first": losses[0] if losses else None}
            opt.zero_grad(set_to_none=True)
            loss.backward()
            transient_fit_mask_grads(groups, sel)
            opt.step()
            losses.append(float(loss.detach()))
        return {"iters": int(fit_iters), "n_sel": n_sel,
                "loss_first": round(losses[0], 5), "loss_last": round(losses[-1], 5),
                "opa_mean_before": round(opa0, 4),
                "opa_mean_after": round(float(torch.sigmoid(g._opacity.detach()[sel]).mean()), 4)}

    def map(self, current_window, prune=False, iters=1):
        if len(current_window) == 0:
            return

        mapping_start = time.perf_counter()
        viewpoint_stack = [self.viewpoints[kf_idx] for kf_idx in current_window]
        random_viewpoint_stack = []
        frames_to_optimize = self.config["Training"]["pose_window"]

        current_window_set = set(current_window)
        for cam_idx, viewpoint in self.viewpoints.items():
            if cam_idx in current_window_set:
                continue
            random_viewpoint_stack.append(viewpoint)

        for _ in range(iters):
            self.iteration_count += 1
            self.last_sent += 1

            loss_mapping = 0
            viewspace_point_tensor_acm = []
            visibility_filter_acm = []
            radii_acm = []
            n_touched_acm = []

            keyframes_opt = []

            for cam_idx in range(len(current_window)):
                viewpoint = viewpoint_stack[cam_idx]
                keyframes_opt.append(viewpoint)
                render_pkg = render(
                    viewpoint, self.gaussians, self.pipeline_params, self.background
                )
                (
                    image,
                    viewspace_point_tensor,
                    visibility_filter,
                    radii,
                    depth,
                    opacity,
                    n_touched,
                ) = (
                    render_pkg["render"],
                    render_pkg["viewspace_points"],
                    render_pkg["visibility_filter"],
                    render_pkg["radii"],
                    render_pkg["depth"],
                    render_pkg["opacity"],
                    render_pkg["n_touched"],
                )

                ema_w, ema_c = self._compute_ema_weight(image, depth, viewpoint)
                loss_mapping += get_loss_mapping(
                    self.config,
                    image,
                    depth,
                    viewpoint,
                    opacity,
                    dynamic_mask=get_or_compute_dynamic_mask(self.config, viewpoint)
                    if mask_mapping_enabled(self.config)
                    else None,
                    ema_weight_map=ema_w,
                    ema_c_mass=ema_c,
                    mope_soft=self._mope_mapping_soft(depth, viewpoint),
                )
                self.observe_mapping_reliability(
                    image,
                    depth,
                    opacity,
                    viewpoint,
                    f"keyframe_{viewpoint.uid:06d}",
                    visibility_filter=visibility_filter,
                )
                self.observe_mapping_probe(viewpoint)
                viewspace_point_tensor_acm.append(viewspace_point_tensor)
                visibility_filter_acm.append(visibility_filter)
                radii_acm.append(radii)
                n_touched_acm.append(n_touched)

            # Counter-based keyed RNG (causal-twin): the random-KF subsample is
            # paired across lifecycle arms at the same iteration, not coupled to
            # the global torch stream. See utils/causal_twin.
            rand_perm = self.rng.randperm(
                len(random_viewpoint_stack), "map_randperm", self.iteration_count
            )
            for cam_idx in rand_perm[:2]:
                viewpoint = random_viewpoint_stack[cam_idx]
                render_pkg = render(
                    viewpoint, self.gaussians, self.pipeline_params, self.background
                )
                (
                    image,
                    viewspace_point_tensor,
                    visibility_filter,
                    radii,
                    depth,
                    opacity,
                    n_touched,
                ) = (
                    render_pkg["render"],
                    render_pkg["viewspace_points"],
                    render_pkg["visibility_filter"],
                    render_pkg["radii"],
                    render_pkg["depth"],
                    render_pkg["opacity"],
                    render_pkg["n_touched"],
                )
                ema_w, ema_c = self._compute_ema_weight(image, depth, viewpoint)
                loss_mapping += get_loss_mapping(
                    self.config,
                    image,
                    depth,
                    viewpoint,
                    opacity,
                    dynamic_mask=get_or_compute_dynamic_mask(self.config, viewpoint)
                    if mask_mapping_enabled(self.config)
                    else None,
                    ema_weight_map=ema_w,
                    ema_c_mass=ema_c,
                    mope_soft=self._mope_mapping_soft(depth, viewpoint),
                )
                self.observe_mapping_reliability(
                    image,
                    depth,
                    opacity,
                    viewpoint,
                    f"random_{viewpoint.uid:06d}",
                    visibility_filter=visibility_filter,
                )
                viewspace_point_tensor_acm.append(viewspace_point_tensor)
                visibility_filter_acm.append(visibility_filter)
                radii_acm.append(radii)

            # Advance EMA state once after the loop, so all probes see the same
            # pre-update state (lagged-residual semantics).
            if self.mapping_ema.is_enabled():
                self._update_ema_state(image, depth, viewpoint)

            scaling = self.gaussians.get_scaling
            isotropic_loss = torch.abs(scaling - scaling.mean(dim=1).view(-1, 1))
            loss_mapping += 10 * isotropic_loss.mean()
            loss_mapping.backward()
            gaussian_split = False
            ## Deinsifying / Pruning Gaussians
            with torch.no_grad():
                self.occ_aware_visibility = {}
                for idx in range((len(current_window))):
                    kf_idx = current_window[idx]
                    n_touched = n_touched_acm[idx]
                    self.occ_aware_visibility[kf_idx] = (n_touched > 0).long()

                # # compute the visibility of the gaussians
                # # Only prune on the last iteration and when we have full window
                if prune:
                    if len(current_window) == self.config["Training"]["window_size"]:
                        prune_mode = self.config["Training"]["prune_mode"]
                        prune_coviz = 3
                        self.gaussians.n_obs.fill_(0)
                        for window_idx, visibility in self.occ_aware_visibility.items():
                            self.gaussians.n_obs += visibility.cpu()
                        to_prune = None
                        if prune_mode == "odometry":
                            to_prune = self.gaussians.n_obs < 3
                            # make sure we don't split the gaussians, break here.
                        if prune_mode == "slam":
                            # only prune keyframes which are relatively new
                            sorted_window = sorted(current_window, reverse=True)
                            mask = self.gaussians.unique_kfIDs >= sorted_window[2]
                            if not self.initialized:
                                mask = self.gaussians.unique_kfIDs >= 0
                            to_prune = torch.logical_and(
                                self.gaussians.n_obs <= prune_coviz, mask
                            )
                        if to_prune is not None and self.monocular:
                            self.gaussians.prune_points(to_prune.cuda())
                            for idx in range((len(current_window))):
                                current_idx = current_window[idx]
                                self.occ_aware_visibility[current_idx] = (
                                    self.occ_aware_visibility[current_idx][~to_prune]
                                )
                        if not self.initialized:
                            self.initialized = True
                            Log("Initialized SLAM")
                        # # make sure we don't split the gaussians, break here.
                    self.mapping_time_s += time.perf_counter() - mapping_start
                    self.mapping_calls += 1
                    self.mapping_iterations += iters
                    return False

                for idx in range(len(viewspace_point_tensor_acm)):
                    self.gaussians.max_radii2D[visibility_filter_acm[idx]] = torch.max(
                        self.gaussians.max_radii2D[visibility_filter_acm[idx]],
                        radii_acm[idx][visibility_filter_acm[idx]],
                    )
                    self.gaussians.add_densification_stats(
                        viewspace_point_tensor_acm[idx], visibility_filter_acm[idx]
                    )

                update_gaussian = (
                    self.iteration_count % self.gaussian_update_every
                    == self.gaussian_update_offset
                )
                if update_gaussian:
                    self.gaussians.densify_and_prune(
                        self.opt_params.densify_grad_threshold,
                        self.gaussian_th,
                        self.gaussian_extent,
                        self.size_threshold,
                    )
                    gaussian_split = True

                ## Opacity reset
                if (self.iteration_count % self.gaussian_reset) == 0 and (
                    not update_gaussian
                ):
                    Log("Resetting the opacity of non-visible Gaussians")
                    self.gaussians.reset_opacity_nonvisible(visibility_filter_acm)
                    gaussian_split = True

                self.gaussians.optimizer.step()
                self.gaussians.optimizer.zero_grad(set_to_none=True)
                self.gaussians.update_learning_rate(self.iteration_count)
                self.keyframe_optimizers.step()
                self.keyframe_optimizers.zero_grad(set_to_none=True)
                # Pose update
                for cam_idx in range(min(frames_to_optimize, len(current_window))):
                    viewpoint = viewpoint_stack[cam_idx]
                    if viewpoint.uid == 0:
                        continue
                    update_pose(viewpoint)

                ## R3-P05 STEP4: harmless-deletion map compression, run AFTER this
                ## iteration's optimizer/reset/pose step and AFTER the visibility_*
                ## tensors have been fully consumed. Running it mid-iteration (e.g.
                ## right after densify_and_prune) desyncs the window-local
                ## visibility_filter_acm/occ_aware_visibility (sized for the
                ## pre-compress count) from the post-compress gaussian count, which
                ## crashes reset_opacity_nonvisible on the next use. Between
                ## iterations the next map() call rebuilds occ_aware_visibility from
                ## scratch, so the count-change is clean here. Config-gated — absent
                ## /disabled => identical to base.
                if self.compress_enabled:
                    self.gaussians.compress_deletion(
                        op_floor=self.compress_op_floor,
                        op_and_foot_th=self.compress_op_and_foot_th,
                        foot_th_m=self.compress_foot_th_m,
                        log_prefix="[compress]",
                    )
                    gaussian_split = True
        self.mapping_time_s += time.perf_counter() - mapping_start
        self.mapping_calls += 1
        self.mapping_iterations += iters
        # depth_reanchor D1 (2026-09-09): after the mapping pass on the
        # newest keyframe, periodically re-anchor visible Gaussians to the
        # metric sensor depth (config-gated, default OFF => bit-identical).
        if self.reanchor is not None and current_window:
            self.reanchor.maybe_reanchor(
                current_window[-1],
                self.viewpoints[current_window[-1]],
                self,
            )
        return gaussian_split

    def _alpha_lifecycle_step(self, viewpoint, observed_depth):
        """R2-P02 Fork-B alpha-driven EXIT + FILL, run once per keyframe AFTER the
        vanilla map()/prune so vanilla mapping stays byte-identical when the
        AlphaLifecycle block is absent/off (arm B never reaches here). ``alpha`` ==
        the reused ``static_prob`` tensor (no new per-Gaussian field). Wrapped so a
        lifecycle fault degrades to a logged no-op and never crashes the mapping
        loop / the smoke run. Only the uncertain-region ghost is targeted: reset +
        carve fire ONLY on persistently low-alpha Gaussians in front of the
        observed surface, so static structure is protected."""
        try:
            params = alpha_lifecycle.read_alpha_lifecycle_params(self.config)
            gaussians = self.gaussians
            if gaussians is None or gaussians.get_xyz.shape[0] == 0:
                return
            if observed_depth is None:
                return
            self.alpha_lifecycle_steps += 1
            gaussians.ensure_static_memory_state()
            device = gaussians.get_xyz.device
            height = int(viewpoint.image_height)
            width = int(viewpoint.image_width)
            obs = torch.as_tensor(
                np.asarray(observed_depth), dtype=torch.float32, device=device
            ).squeeze()
            if obs.dim() != 2 or obs.shape[0] != height or obs.shape[1] != width:
                return

            with torch.no_grad():
                pkg = render(viewpoint, gaussians, self.pipeline_params, self.background)
                if pkg is None:
                    return
                rendered_depth = pkg["depth"].squeeze()
                rendered_opacity = pkg["opacity"].squeeze()
                visibility = pkg["visibility_filter"].to(device=device, dtype=torch.bool)

                # one projection of every Gaussian into this KF, shared by the
                # alpha ledger and the exit selection
                u, v, z, proj_valid = alpha_lifecycle.project_gaussians_to_view(
                    gaussians.get_xyz,
                    viewpoint.world_view_transform,
                    viewpoint.fx,
                    viewpoint.fy,
                    viewpoint.cx,
                    viewpoint.cy,
                    height,
                    width,
                )

                # --- alpha ledger (observe / exit / exit_fill) ---
                evidence, ev_valid = alpha_lifecycle.depth_inconsistency_evidence(
                    rendered_depth,
                    obs,
                    params.evidence_band_abs_m,
                    params.evidence_band_rel,
                )
                ev_at = alpha_lifecycle.sample_map_at_gaussians(
                    evidence, u, v, proj_valid, height, width
                )
                evvalid_at = (
                    alpha_lifecycle.sample_map_at_gaussians(
                        ev_valid.float(), u, v, proj_valid, height, width
                    )
                    > 0.5
                )
                update_mask = proj_valid & visibility & evvalid_at
                alpha = gaussians.static_prob.squeeze(1)
                # ema_alpha_update is PURE (it clones); the pre-EMA values stay
                # intact in this tensor, which is what the evidence gate caps
                # against. Purity is pinned by test_evidence_gate.py.
                alpha_pre = alpha
                obs_count = gaussians.static_obs_count.squeeze(1)
                alpha, obs_count = alpha_lifecycle.ema_alpha_update(
                    alpha, obs_count, ev_at, update_mask, params.ema_beta
                )
                # --- L1b evidence gate (default-off, 治续命) ------------------
                # Transient occupants cannot testify for static structure: inside
                # the runtime dynamic mask the EMA may lower alpha but never raise
                # it. Only-decrease cap (NOT freeze/overwrite); deletion still
                # needs the full carve conjunction, so a mask false-positive on
                # static structure (alpha ~ 1) can never reach tau_carve. The
                # mask is read from the frontend cache ONLY (same pattern as T3:
                # no second Mask R-CNN in the backend process). None => fail-open
                # + count. Runs BEFORE reset/carve so a crossed tau_carve fires
                # in the same keyframe's exit pass.
                if params.does_evidence_gate:
                    sem_mask = getattr(viewpoint, "dynamic_mask", None)
                    if sem_mask is None:
                        self.alpha_gate_no_mask_kfs += 1
                        Log(
                            f"alpha-gate KF {int(viewpoint.uid)}: SKIP -- no "
                            f"cached dynamic_mask (fail-open)"
                        )
                    else:
                        gate_hit = (
                            alpha_lifecycle.sample_map_at_gaussians(
                                sem_mask.squeeze().to(
                                    device=device, dtype=torch.float32
                                ),
                                u, v, proj_valid, height, width,
                            )
                            > 0.5
                        )
                        alpha, capped, prevented = (
                            alpha_lifecycle.apply_evidence_gate(
                                alpha_pre, alpha, update_mask, gate_hit
                            )
                        )
                        n_gate_capped = int(capped.sum())
                        self.alpha_gate_capped_total += n_gate_capped
                        self.alpha_gate_prevented_rise_sum += prevented
                        Log(
                            f"alpha-gate KF {int(viewpoint.uid)}: "
                            f"hit={int((proj_valid & gate_hit).sum())} "
                            f"capped={n_gate_capped} prevented={prevented:.2f} "
                            f"a_min={float(alpha.min()):.4f}"
                        )
                gaussians.static_prob = alpha.unsqueeze(1)
                gaussians.static_obs_count = obs_count.unsqueeze(1)

                # --- L1c occupancy memory (default-off, 时序先验) ---------------
                # The per-frame semantic mask is transient. Accumulate it over
                # TIME into a world-space voxel ledger ("this region was occupied
                # within the last K keyframes") and multiply-decay LOW-alpha
                # primitives inside warm regions. The only alpha path NOT gated
                # by a geometric conjunction (reset/carve need in_front --
                # structurally unreachable in the pt 续命 regime; the L1b gate
                # only caps). Safety: alpha >= guard is never touched, so net
                # static structure (alpha ~ 1) has zero ceiling harm from mask /
                # voxel false positives. Uses the SAME cached frontend mask as
                # the L1b gate (no second Mask R-CNN in this process) and the
                # SAME dense sensor depth already fetched for the evidence map.
                if params.does_occupancy_memory:
                    sem_mask_occ = getattr(viewpoint, "dynamic_mask", None)
                    if sem_mask_occ is None:
                        self.occ_no_mask_kfs += 1
                        Log(
                            f"occupancy KF {int(viewpoint.uid)}: SKIP -- no "
                            f"cached dynamic_mask (fail-open)"
                        )
                    else:
                        if self._occ_memory is None:
                            self._occ_memory = occupancy_memory.OccupancyMemory(
                                params.occupancy_voxel_size, params.occupancy_warm_kfs
                            )
                        m_flat = sem_mask_occ.squeeze().to(device) > 0
                        flat_idx = torch.nonzero(
                            m_flat.flatten(), as_tuple=False
                        ).flatten()
                        vox_keys = occupancy_memory.unproject_mask_to_voxels(
                            flat_idx, obs, viewpoint,
                            params.occupancy_voxel_size,
                        )
                        self._occ_memory.observe(vox_keys, int(viewpoint.uid))
                        warm = self._occ_memory.warm_mask(
                            gaussians.get_xyz.detach(), int(viewpoint.uid)
                        )
                        alpha, decayed = occupancy_memory.apply_occupancy_decay(
                            alpha, warm,
                            params.occupancy_alpha_guard, params.occupancy_decay,
                        )
                        n_occ = int(decayed.sum())
                        self.occ_warm_prims_total += int(warm.sum())
                        self.occ_decay_events_total += n_occ
                        self.occ_alpha_lt_guard_total += int(
                            (alpha < params.occupancy_alpha_guard).sum()
                        )
                        Log(
                            f"occupancy KF {int(viewpoint.uid)}: "
                            f"voxels={int(vox_keys.numel())} "
                            f"warm={int(warm.sum())} decayed={n_occ} "
                            f"table={int(self._occ_memory._keys.numel())} "
                            f"a_min={float(alpha.min()):.4f}"
                        )
                        # keep the ledger's alpha authoritative downstream
                        gaussians.static_prob = alpha.unsqueeze(1)

                if not params.does_exit:
                    return

                # --- EXIT: opacity-reset (A) + free-space carve (B) ---
                obs_at = alpha_lifecycle.sample_map_at_gaussians(
                    obs, u, v, proj_valid, height, width
                )
                # --- T3 (default-off): semantic alpha override ---------------
                # Short-circuit the EMA ledger where a semantic mask says
                # "person" AND the geometry says the Gaussian is floating in
                # front of the observed surface. Both conjuncts are required;
                # see select_semantic_override_mask for why the geometry one
                # protects a stationary person's static structure.
                #
                # The mask is read from the frontend's per-viewpoint cache ONLY.
                # get_or_compute_dynamic_mask is deliberately NOT called: this
                # runs in the BACKEND process, so a cache miss would load a
                # second Mask R-CNN into VRAM (a real 6 GB / 2060 risk), and a
                # backend-side mask could silently differ from the one tracking
                # used on the same frame.
                n_sem_hit = n_sem_front = n_sem_override = 0
                if params.does_semantic_override:
                    sem_mask = getattr(viewpoint, "dynamic_mask", None)
                    if sem_mask is None:
                        # mask-free arm: T3 is a no-op by construction. Logged,
                        # not silent -- "override 0" must be attributable.
                        Log(
                            f"alpha-sem KF {int(viewpoint.uid)}: SKIP -- no cached "
                            f"dynamic_mask on this viewpoint (mask-free arm?)"
                        )
                    else:
                        sem_hit = (
                            alpha_lifecycle.sample_map_at_gaussians(
                                sem_mask.squeeze().to(device=device, dtype=torch.float32),
                                u, v, proj_valid, height, width,
                            )
                            > 0.5
                        )
                        override_mask = alpha_lifecycle.select_semantic_override_mask(
                            z, obs_at, sem_hit, proj_valid,
                            params.semantic_override_delta_m,
                        )
                        sem_obs_ok = torch.isfinite(obs_at) & (obs_at > 0.01)
                        n_sem_hit = int((proj_valid & sem_hit).sum())
                        n_sem_front = int(
                            (
                                proj_valid
                                & sem_obs_ok
                                & (z < obs_at - params.semantic_override_delta_m)
                            ).sum()
                        )
                        n_sem_override = int(override_mask.sum())
                        if n_sem_override > 0:
                            alpha[override_mask] = float(params.semantic_alpha_override)
                            # PERSIST (the only implementation -- no opt-out). Without
                            # the writeback the next keyframe's ledger reads the OLD
                            # high alpha and re-derives it from evidence, so the
                            # override would be undone every step and the mechanism
                            # would only ever act within a single keyframe.
                            gaussians.static_prob = alpha.unsqueeze(1)
                        # Per-conjunct counts. "override=0" is ambiguous without
                        # them: no person in view (hit=0), person present but at the
                        # observed surface i.e. correctly protected (hit>0,front=0),
                        # and floaters present but semantics missed them
                        # (front>0,hit=0) are three different stories.
                        self.alpha_sem_override_total += n_sem_override
                        # Held-out audit trail for the misfire guardrail. The
                        # criterion is "overridden Gaussians whose projection lands
                        # in GT-STATIC territory <= 5%", and that fraction is not
                        # recoverable after the fact: an overridden Gaussian may be
                        # pruned later, so the final map cannot be re-projected to
                        # answer it. So the pixel each override landed on is written
                        # HERE, at the moment of the override -- and only the pixel.
                        # No GT is read online: dynamic_mask_gtmc is joined offline
                        # (scripts/t3_semalpha_verdict.py), which keeps the held-out
                        # mask held out.
                        if n_sem_override > 0:
                            self._log_semantic_overrides(
                                viewpoint, override_mask, u, v, z, obs_at
                            )
                        Log(
                            f"alpha-sem KF {int(viewpoint.uid)}: hit={n_sem_hit} "
                            f"geom_front={n_sem_front} override={n_sem_override} "
                            f"a_min={float(alpha.min()):.4f}"
                        )
                reset_mask = alpha_lifecycle.select_reset_mask(
                    z, obs_at, alpha, proj_valid, params.tau_reset, params.delta_occlude_m
                )
                n_reset = gaussians.reset_opacity_masked(reset_mask, params.reset_value)
                carve_mask = alpha_lifecycle.select_carve_mask(
                    z,
                    obs_at,
                    alpha,
                    obs_count,
                    proj_valid,
                    params.tau_carve,
                    params.delta_free_m,
                    params.min_obs_count,
                )
                n_carve = int(carve_mask.sum())
                if n_carve > 0:
                    remove = carve_mask.to(device=device)
                    gaussians.prune_points(remove)
                    # map() rebuilt occ_aware_visibility at the pre-step count; our
                    # carve happens AFTER it, so mirror the prune onto those masks or
                    # the frontend's is_keyframe logical_or hits stale sizes -> crash.
                    self._occ_visibility_drop(~remove)
                self.alpha_exit_reset_total += int(n_reset)
                self.alpha_carve_total += n_carve
                Log(
                    f"alpha-exit KF {int(viewpoint.uid)}: "
                    f"reset {n_reset}, carved {n_carve}"
                )
                # --- L1e seam carve (default off; D2-008 缝隙带救援) -----------
                # Runs AFTER the vanilla carve (so seam counts are disjoint from
                # it) and BEFORE the fill pass (so the fill pipeline sees and
                # recovers whatever the seam deletion revealed). The mask-history
                # union is a 2D pixel ledger over the last `seam_warm_kfs` KFs,
                # built here in the BACKEND from the same cached runtime mask the
                # gate/T3 already consume -- never a second Mask R-CNN.
                if params.does_seam_carve:
                    sem_now = getattr(viewpoint, "dynamic_mask", None)
                    if sem_now is None:
                        self.seam_no_mask_kfs += 1
                        Log(
                            f"alpha-seam KF {int(viewpoint.uid)}: SKIP -- no "
                            f"cached dynamic_mask (fail-open)"
                        )
                    else:
                        now_dyn = sem_now.squeeze().to(device=device) > 0
                        uid = int(viewpoint.uid)
                        hist = self._seam_history
                        # prune entries older than the window, then merge current
                        for k in [k for k, (_, t) in hist.items() if uid - t > params.seam_warm_kfs]:
                            del hist[k]
                        # vacated = pixel was dynamic recently AND is not now.
                        past_any = torch.zeros_like(now_dyn)
                        for m_prev, t in hist.values():
                            past_any |= m_prev
                        sem_vacated_px = past_any & (~now_dyn)
                        hist[uid] = (now_dyn.clone(), uid)
                        # Sample the per-pixel vacated map at the Gaussians (same
                        # sampling path as the T3 semantic hit).
                        sem_vacated_at = alpha_lifecycle.sample_map_at_gaussians(
                            sem_vacated_px.to(dtype=torch.float32), u, v, proj_valid,
                            height, width,
                        ) > 0.5
                        seam_mask = alpha_lifecycle.select_seam_carve_mask(
                            z, obs_at, alpha, obs_count, sem_vacated_at, proj_valid,
                            params.seam_tau, params.seam_delta_m, params.seam_hi_m,
                            params.min_obs_count,
                        )
                        n_seam = int(seam_mask.sum())
                        if n_seam > 0:
                            remove_s = seam_mask.to(device=device)
                            gaussians.prune_points(remove_s)
                            self._occ_visibility_drop(~remove_s)
                        self.seam_carve_total += n_seam
                        self.seam_vacated_px_total += int(sem_vacated_px.sum())
                        Log(
                            f"alpha-seam KF {uid}: vacated_px={int(sem_vacated_px.sum())} "
                            f"hist_regions={len(hist)} carved={n_seam} "
                            f"a_min={float(alpha.min()):.4f}"
                        )
                # Ledger + per-conjunct diagnostics. reset/carve are conjunctions
                # of a GEOMETRY test and an ALPHA gate; without these counts a
                # "reset 0, carved 0" line cannot tell us which conjunct is empty,
                # and an inert mechanism looks identical to a well-behaved one.
                # NOTE: no square brackets -- Log() prints through rich.Console,
                # which silently eats "[...]" as style markup.
                obs_ok_dbg = torch.isfinite(obs_at) & (obs_at > 0.01)
                n_front = int(
                    (proj_valid & obs_ok_dbg & (z < obs_at - params.delta_occlude_m)).sum()
                )
                n_free = int(
                    (proj_valid & obs_ok_dbg & (z < obs_at - params.delta_free_m)).sum()
                )
                Log(
                    f"alpha-ledger KF {int(viewpoint.uid)}: N={int(alpha.numel())} "
                    f"proj_valid={int(proj_valid.sum())} "
                    f"visible={int(visibility.sum())} "
                    f"proj_and_vis={int((proj_valid & visibility).sum())} "
                    f"ev_valid_at={int(evvalid_at.sum())} "
                    f"updated={int(update_mask.sum())} "
                    f"| a_min={float(alpha.min()):.4f} a_mean={float(alpha.mean()):.4f} "
                    f"obs_max={float(obs_count.max()):.0f} "
                    f"obs_ge_min={int((obs_count >= params.min_obs_count).sum())} "
                    f"resets={getattr(gaussians, 'static_memory_reset_count', 0)} "
                    f"grows={getattr(gaussians, 'static_memory_extend_count', 0)} "
                    f"| geom_front={n_front} geom_free={n_free} "
                    f"a_lt_reset={int((alpha < params.tau_reset).sum())} "
                    f"a_lt_carve={int((alpha < params.tau_carve).sum())} "
                    f"| ev_mean={float(evidence.mean()):.4f} "
                    f"ev_hi_frac={float((evidence > 0.65).float().mean()):.4f} "
                    f"ev_valid_frac={float(ev_valid.float().mean()):.4f}"
                )

                if not params.does_fill:
                    return
                if n_reset == 0 and n_carve == 0:
                    # exit opened no hole -> nothing to fill. The exit->fill
                    # coupling made exact: no exit delta, no re-seed (and no wasted
                    # re-render), so we never seed background behind a live ghost.
                    return

                # --- L1f 观测债：本 KF 的掩码覆盖记为债务（在 fill 之前入账）---
                # 掩码覆盖 = 该区域本帧无渲染监督 = 欠债 +1。放这里（fill 管线内、
                # exit 之后）保证：obsdebt=False 或 does_fill=False 时零执行。
                if params.obsdebt:
                    sem_now = getattr(viewpoint, "dynamic_mask", None)
                    if sem_now is not None:
                        if self._obsdebt_ledger is None:
                            self._obsdebt_ledger = obsdebt.ObsDebtLedger(
                                params.obsdebt_voxel_size)
                        m_dyn = sem_now.squeeze().to(device=device) > 0
                        dyn_idx = torch.nonzero(
                            m_dyn.flatten(), as_tuple=False).flatten()
                        vox = obsdebt.unproject_flatidx_to_voxels(
                            dyn_idx, obs, viewpoint, params.obsdebt_voxel_size)
                        self._obsdebt_ledger.observe(vox)
                        Log(
                            f"obsdebt KF {int(viewpoint.uid)}: "
                            f"masked_px={int(m_dyn.sum())} "
                            f"voxels={int(vox.numel())} "
                            f"table={int(self._obsdebt_ledger._keys.numel())} "
                            f"total={self._obsdebt_ledger.n_voxs_total}"
                        )

                # --- FILL: recover background ONLY where exit opened a hole (C) ---
                # Re-render POST-exit and compare against the PRE-exit render: fill
                # only pixels whose opaque near occluder was cleared by carve/reset
                # (detect_vacated_pixels couples fill to that delta). Seed the
                # DIRECTLY-OBSERVED background there (sensor depth, KF-image colour).
                #
                # Every early return below LOGS. A silent return here is what made E2
                # unattributable: zero `alpha-fill` lines could not distinguish a
                # broken mechanism from one correctly finding nothing to do, and the
                # arm reached make-or-break inert (r2_p02_e2.md §2a/§5).
                self.alpha_fill_steps += 1
                pkg2 = render(viewpoint, gaussians, self.pipeline_params, self.background)
                if pkg2 is None:
                    Log(
                        f"alpha-fill KF {int(viewpoint.uid)}: SKIP -- post-exit "
                        f"re-render returned None"
                    )
                    return
                vacated, fill_dbg = alpha_lifecycle.detect_vacated_pixels(
                    rendered_depth,
                    rendered_opacity,
                    pkg2["opacity"].squeeze(),
                    obs,
                    params.fill_band_abs_m,
                    params.fill_band_rel,
                    params.fill_min_opacity,
                    return_diagnostics=True,
                )
                self.alpha_fill_cleared_px_total += int(fill_dbg["n_now_cleared"])
                self.alpha_fill_vacated_px_total += int(fill_dbg["n_vacated"])
                # Mirrors the exit pass's `alpha-ledger` line: per-conjunct counts so a
                # zero is ATTRIBUTABLE. n_now_cleared is the discriminating conjunct.
                # No square brackets -- Log() prints through rich.Console, which
                # silently eats "[...]" as style markup.
                Log(
                    f"alpha-fill-ledger KF {int(viewpoint.uid)}: "
                    f"n_px={fill_dbg['n_px']} valid={fill_dbg['n_valid']} "
                    f"pre_occluded={fill_dbg['n_pre_occluded']} "
                    f"now_cleared={fill_dbg['n_now_cleared']} "
                    f"vacated={fill_dbg['n_vacated']} "
                    f"| op1_min={fill_dbg['op1_min']:.4f} "
                    f"op1_mean={fill_dbg['op1_mean']:.4f} "
                    f"fill_min_opacity={params.fill_min_opacity:.2f}"
                )
                uu, vv = alpha_lifecycle.as_numpy_pixels(vacated)
                if uu.size == 0:
                    Log(
                        f"alpha-fill KF {int(viewpoint.uid)}: inserted 0 -- no vacated "
                        f"pixel (now_cleared={fill_dbg['n_now_cleared']}, "
                        f"pre_occluded={fill_dbg['n_pre_occluded']}); exit removed "
                        f"coverage but it was not hiding observed background"
                    )
                    return
                if uu.size > params.fill_max_points:
                    if params.obsdebt and self._obsdebt_ledger is not None:
                        # L1f 观测债分配律：预算内按债务降序保留（高债区优先补回）。
                        # 纯资源重分配——预算上限不变，只换"保留谁"。
                        vox_sel = obsdebt.unproject_pixels_to_voxels(
                            uu, vv, obs, viewpoint, params.obsdebt_voxel_size)
                        uu, vv, realloc = obsdebt.fill_budget_by_debt(
                            uu, vv, vox_sel, self._obsdebt_ledger,
                            params.fill_max_points)
                        self.obsdebt_fill_realloc_events += 1
                        Log(
                            f"obsdebt-fill KF {int(viewpoint.uid)}: "
                            f"vacated={realloc['kept'] + realloc['dropped']} "
                            f"kept={realloc['kept']} dropped={realloc['dropped']} "
                            f"debt_max={realloc['debt_max']}"
                        )
                    else:
                        keep = np.unique(
                            np.linspace(0, uu.size - 1, params.fill_max_points)
                            .round()
                            .astype(np.int64)
                        )
                        uu, vv = uu[keep], vv[keep]
                vv_t = torch.as_tensor(vv, device=device, dtype=torch.long)
                uu_t = torch.as_tensor(uu, device=device, dtype=torch.long)
                fill_depth = obs[vv_t, uu_t]
                image = viewpoint.original_image.to(device=device)  # (3,H,W), [0,1]
                fill_color = image[:, vv_t, uu_t].transpose(0, 1).contiguous()
                finite = torch.isfinite(fill_depth) & (fill_depth > 0.01)
                if int(finite.sum()) == 0:
                    Log(
                        f"alpha-fill KF {int(viewpoint.uid)}: inserted 0 -- all "
                        f"{uu.size} vacated pixels had non-finite or <1cm sensor depth"
                    )
                    return
                finite_np = finite.detach().cpu().numpy()
                lineage = np.full(int(finite_np.sum()), UNTRACKED, dtype=np.int32)
                deferred_cfg = self.config.get("DeferredCommit", {})
                pre_fill_count = int(gaussians.get_xyz.shape[0])
                inserted = gaussians.insert_candidate_gaussians(
                    viewpoint,
                    uu[finite_np],
                    vv[finite_np],
                    fill_depth[finite].detach().cpu().numpy(),
                    fill_color[finite].detach().cpu().numpy(),
                    kf_id=int(viewpoint.uid),
                    lineage_ids=lineage,
                    min_gaussian_scale=float(
                        deferred_cfg.get("promotion_min_scale_m", 0.001)
                    ),
                    max_gaussian_scale=float(
                        deferred_cfg.get("promotion_max_scale_m", 0.02)
                    ),
                )
                added = int(gaussians.get_xyz.shape[0]) - pre_fill_count
                if added > 0:
                    # freshly inserted Gaussians were unseen by every prior KF ->
                    # append False so the per-KF visibility masks stay map-sized.
                    self._occ_visibility_grow(added, pre_fill_count)
                # L1f 观测债 · 迭代配额：高债区插入基元获得额外局部优化步。
                # 形态 = **独立 Adam**（照抄 _transient_fit 的正确先例：
                # transient_fit_build_optimizer——关卡① 致命-1 整改：共享主优化器
                # 的陈旧动量会在梯度为零时仍推动老基元，纯资源分配承诺被破坏）。
                # 老基元逐位不动的机制：全新 Adam 中 grad≡0 ⇒ m/v≡0 ⇒ 步长精确 0。
                if params.obsdebt and added > 0 and self._obsdebt_ledger is not None:
                    try:
                        new_xyz = gaussians.get_xyz.detach()[pre_fill_count:]
                        vox_new = obsdebt.xyz_to_voxels(
                            new_xyz, params.obsdebt_voxel_size)
                        d = self._obsdebt_ledger.debt_at(vox_new).float()
                        d_hat = (d / max(1.0, float(d.max()))).to(device)
                        n_steps = int(round(params.obsdebt_iter_boost *
                                            float(d_hat.mean()) * 10.0))
                        if n_steps > 0:
                            # 2026-09-24 实装修复：本 step 整体包在 `no_grad()` 里
                            # （见本函数 opening 的 `with torch.no_grad():`），反传
                            # 会报 "does not require grad"。局部重开梯度（仅本块）。
                            _grad_ctx = torch.enable_grad()
                            sel_new = torch.zeros(
                                int(gaussians.get_xyz.shape[0]), dtype=torch.bool,
                                device=device)
                            sel_new[pre_fill_count:] = True
                            boost_opt, boost_groups = transient_fit_build_optimizer(
                                gaussians)
                            with _grad_ctx:
                                for _ in range(n_steps):
                                    pkg3 = render(viewpoint, gaussians,
                                                  self.pipeline_params,
                                                  self.background)
                                    if pkg3 is None:
                                        break
                                    gt_img = viewpoint.original_image.to(device)
                                    img = pkg3["render"].clamp(0.0, 1.0)
                                    loss = (img - gt_img).abs().mean()
                                    boost_opt.zero_grad(set_to_none=True)
                                    loss.backward()
                                    transient_fit_mask_grads(boost_groups, sel_new)
                                    boost_opt.step()
                            self.obsdebt_boost_steps_total += n_steps
                            Log(
                                f"obsdebt-boost KF {int(viewpoint.uid)}: "
                                f"new={added} d_hat_mean={float(d_hat.mean()):.3f} "
                                f"extra_steps={n_steps} opt=independent-adam"
                            )
                    except Exception as boost_exc:
                        Log(f"obsdebt-boost skipped: {boost_exc}")
                else:
                    if params.obsdebt and added > 0:
                        Log(
                            f"obsdebt-boost KF {int(viewpoint.uid)}: SKIP -- "
                            f"ledger absent (obsdebt on but no debt recorded yet)"
                        )
                self.alpha_fill_inserted_total += int(inserted)
                Log(
                    f"alpha-fill KF {int(viewpoint.uid)}: "
                    f"inserted {inserted} background Gaussians"
                )
        except Exception as exc:  # lifecycle must never crash the mapping loop
            self.alpha_lifecycle_skips += 1
            Log(
                f"alpha-lifecycle step skipped "
                f"(KF {getattr(viewpoint, 'uid', '?')}): {exc}"
            )

    def _occ_visibility_drop(self, keep_mask):
        """Shrink every cached per-KF occ_aware_visibility mask by a prune, mirroring
        map()'s own post-prune adjustment. Only masks already sized to the pre-prune
        count are touched (guard against a stale/absent ledger)."""
        for idx in list(self.occ_aware_visibility.keys()):
            m = self.occ_aware_visibility[idx]
            if m.shape[0] == keep_mask.shape[0]:
                self.occ_aware_visibility[idx] = m[keep_mask]

    def _occ_visibility_grow(self, n_added, old_count):
        """Extend every cached per-KF occ_aware_visibility mask with False for
        freshly inserted (never-previously-visible) Gaussians, so the mask stays
        sized to the live map and the frontend's is_keyframe logical_or is safe."""
        if n_added <= 0:
            return
        for idx in list(self.occ_aware_visibility.keys()):
            m = self.occ_aware_visibility[idx]
            if m.shape[0] == old_count:
                pad = torch.zeros(n_added, dtype=m.dtype, device=m.device)
                self.occ_aware_visibility[idx] = torch.cat([m, pad], dim=0)

    def color_refinement(self):
        Log("Starting color refinement")

        # Numerical safety: drop non-finite (Inf/NaN) Gaussians before refining so the
        # after_opt render eval + final_after_opt PLY (the paper's rendering/geometry
        # source) are clean. Inf-scale Gaussians rasterize to NaN and poison PSNR.
        n_bad = self.gaussians.prune_nonfinite_points()
        if n_bad:
            Log(f"Pruned {n_bad} non-finite Gaussians before color refinement")

        refinement_start = time.perf_counter()
        iteration_total = self.color_refinement_iterations
        tri_config = get_tri_reliability_config(self.config)
        static_guard = tri_reliability_policy_enabled(
            self.config, "mapping", "apply_color_refinement_static_guard"
        )
        freeze_geometry = static_guard and tri_config.get(
            "freeze_color_refinement_geometry", True
        )
        original_lrs = self._optimizer_lrs_by_group_name() if freeze_geometry else {}
        if freeze_geometry:
            self._freeze_color_refinement_geometry_lrs()

        # P* (2026-08-07): surgical counterfactual knob — freeze ONLY the opacity group
        # during color refinement, leaving geometry + color live. Orthogonal to the
        # static-guard path (which also swaps the L1 loss and freezes xyz/scaling/
        # rotation). Exists to test whether the op<0.01 tail is a refinement-induced
        # soft-suppression artifact vs. a functionally-useful opacity degree of freedom
        # (see results/evidence/p3_terminal_mech_autopsy.md). No-op when false.
        freeze_opac_refine = bool(
            tri_config.get("color_refinement_freeze_opacity", False)
        )
        op_lrs_saved = None
        if freeze_opac_refine:
            op_lrs_saved = {}
            for pg in self.gaussians.optimizer.param_groups:
                if pg.get("name") == "opacity":
                    op_lrs_saved[pg["name"]] = pg.get("lr", 0.0)
                    pg["lr"] = 0.0

        try:
            for iteration in tqdm(range(1, iteration_total + 1)):
                viewpoint_idx_stack = list(self.viewpoints.keys())
                # Keyed RNG so color refinement is reproducible in the backend
                # (spawn) process, where the global `random` module is unseeded.
                pick = int(
                    self.rng.randperm(
                        len(viewpoint_idx_stack), "color_refine", iteration
                    )[0]
                )
                viewpoint_cam_idx = viewpoint_idx_stack.pop(pick)
                viewpoint_cam = self.viewpoints[viewpoint_cam_idx]
                render_pkg = render(
                    viewpoint_cam, self.gaussians, self.pipeline_params, self.background
                )
                image, visibility_filter, radii = (
                    render_pkg["render"],
                    render_pkg["visibility_filter"],
                    render_pkg["radii"],
                )

                gt_image = viewpoint_cam.original_image.to(
                    device=image.device, dtype=image.dtype
                )
                if static_guard:
                    Ll1 = self._static_weighted_color_refinement_l1(
                        image,
                        render_pkg.get("depth"),
                        render_pkg.get("opacity"),
                        viewpoint_cam,
                        gt_image,
                    )
                else:
                    Ll1 = l1_loss(image, gt_image)
                loss = (1.0 - self.opt_params.lambda_dssim) * (
                    Ll1
                ) + self.opt_params.lambda_dssim * (1.0 - ssim(image, gt_image))
                loss.backward()
                with torch.no_grad():
                    self.gaussians.max_radii2D[visibility_filter] = torch.max(
                        self.gaussians.max_radii2D[visibility_filter],
                        radii[visibility_filter],
                    )
                    self.gaussians.optimizer.step()
                    self.gaussians.optimizer.zero_grad(set_to_none=True)
                    self.gaussians.update_learning_rate(iteration)
                    if freeze_geometry:
                        self._freeze_color_refinement_geometry_lrs()
        finally:
            if original_lrs:
                self._restore_optimizer_lrs(original_lrs)
            if op_lrs_saved:
                for pg in self.gaussians.optimizer.param_groups:
                    if pg.get("name") in op_lrs_saved:
                        pg["lr"] = op_lrs_saved[pg["name"]]
        self.color_refinement_time_s += time.perf_counter() - refinement_start
        Log("Map refinement done")

    def _static_weighted_color_refinement_l1(
        self,
        image,
        depth,
        opacity,
        viewpoint_cam,
        gt_image,
    ):
        tri_config = get_tri_reliability_config(self.config)
        metrics = compute_tri_reliability(
            self.config,
            image,
            depth,
            opacity,
            viewpoint_cam,
            use_exposure=False,
        )
        static_floor = float(tri_config.get("color_refinement_static_floor", 0.25))
        loss_eps = float(tri_config.get("color_refinement_loss_eps", 1e-6))
        static_weight = torch.clamp(
            metrics["static_weight"].to(device=image.device, dtype=image.dtype),
            min=static_floor,
            max=1.0,
        )
        valid_mask = metrics["valid_mask"].to(device=image.device, dtype=image.dtype)
        pixel_l1 = torch.abs(image - gt_image).mean(dim=0, keepdim=True)
        weighted_mask = static_weight * valid_mask
        denom = torch.clamp(weighted_mask.sum(), min=loss_eps)
        return (pixel_l1 * weighted_mask).sum() / denom

    def _optimizer_lrs_by_group_name(self):
        return {
            param_group.get("name"): param_group.get("lr", 0.0)
            for param_group in self.gaussians.optimizer.param_groups
        }

    def _freeze_color_refinement_geometry_lrs(self):
        frozen_names = {"xyz", "opacity", "scaling", "rotation"}
        for param_group in self.gaussians.optimizer.param_groups:
            if param_group.get("name") in frozen_names:
                param_group["lr"] = 0.0

    def _restore_optimizer_lrs(self, lrs_by_name):
        for param_group in self.gaussians.optimizer.param_groups:
            name = param_group.get("name")
            if name in lrs_by_name:
                param_group["lr"] = lrs_by_name[name]

    def _log_semantic_overrides(self, viewpoint, override_mask, u, v, z, obs_at):
        """T3 audit trail: one row per overridden Gaussian (KF uid + pixel + depths).

        Diagnostic only -- nothing online reads it back, and it is written solely on
        keyframes where the override actually fired, so an arm with the mechanism off
        produces no file at all (absence of the file is itself provenance).
        """
        save_dir = self.config["Results"].get("save_dir")
        if not save_dir:
            return
        try:
            out_dir = os.path.join(save_dir, "alpha_semantic")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "overrides.csv")
            new = not os.path.isfile(path)
            sel = override_mask.nonzero(as_tuple=False).squeeze(1)
            uu = u[sel].detach().cpu().tolist()
            vv = v[sel].detach().cpu().tolist()
            zz = z[sel].detach().cpu().tolist()
            oo = obs_at[sel].detach().cpu().tolist()
            with open(path, "a", encoding="utf-8") as fh:
                if new:
                    fh.write("kf_uid,gauss_idx,u,v,z,obs_at\n")
                uid = int(viewpoint.uid)
                for i, gi in enumerate(sel.detach().cpu().tolist()):
                    fh.write(
                        f"{uid},{gi},{uu[i]:.2f},{vv[i]:.2f},{zz[i]:.4f},{oo[i]:.4f}\n"
                    )
        except Exception as exc:  # a diagnostic must never kill a mapping run
            Log(f"alpha-sem override log failed at KF {int(viewpoint.uid)}: {exc}")

    def save_timing_stats(self):
        save_dir = self.config["Results"].get("save_dir")
        if not save_dir:
            return
        self.reliability_recorder.flush_summary()
        self.mapping_probe.flush(save_dir)
        self.tri_reliability_recorder.flush_summary()
        write_semantic_timing_summary(save_dir, "backend")
        os.makedirs(save_dir, exist_ok=True)
        stats = {
            "mapping_time_s": self.mapping_time_s,
            "mapping_calls": self.mapping_calls,
            "mapping_iterations": self.mapping_iterations,
            "color_refinement_time_s": self.color_refinement_time_s,
            # arm-activity ledger (see __init__): a treatment arm that reports
            # zero here did not run its treatment, whatever its metrics say.
            "alpha_lifecycle_steps": self.alpha_lifecycle_steps,
            "alpha_lifecycle_skips": self.alpha_lifecycle_skips,
            "alpha_exit_reset_total": self.alpha_exit_reset_total,
            "alpha_carve_total": self.alpha_carve_total,
            "alpha_sem_override_total": self.alpha_sem_override_total,
            "alpha_gate_capped_total": self.alpha_gate_capped_total,
            "alpha_gate_prevented_rise_sum": self.alpha_gate_prevented_rise_sum,
            "alpha_gate_no_mask_kfs": self.alpha_gate_no_mask_kfs,
            "occ_decay_events_total": self.occ_decay_events_total,
            "occ_warm_prims_total": self.occ_warm_prims_total,
            "occ_alpha_lt_guard_total": self.occ_alpha_lt_guard_total,
            "occ_no_mask_kfs": self.occ_no_mask_kfs,
            "seam_carve_total": self.seam_carve_total,
            "seam_vacated_px_total": self.seam_vacated_px_total,
            "seam_no_mask_kfs": self.seam_no_mask_kfs,
            "alpha_fill_inserted_total": self.alpha_fill_inserted_total,
            "alpha_fill_steps": self.alpha_fill_steps,
            "alpha_fill_cleared_px_total": self.alpha_fill_cleared_px_total,
            "alpha_fill_vacated_px_total": self.alpha_fill_vacated_px_total,
            # MoPe 用途② 生效计数（default-off；静默组件须有落盘证据，DISCIPLINE 9）。
            "mope_mapping_apply_n": getattr(self, "_mope_map_apply_n", 0),
        }
        timing_path = os.path.join(save_dir, "backend_timing.json")
        temporary_path = f"{timing_path}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=4)
        os.replace(temporary_path, timing_path)

    def push_to_frontend(self, tag=None):
        self.last_sent = 0
        keyframes = []
        for kf_idx in self.current_window:
            kf = self.viewpoints[kf_idx]
            keyframes.append((kf_idx, kf.R.clone(), kf.T.clone()))
        if tag is None:
            tag = "sync_backend"

        payload = clone_obj(self.gaussians)
        msg = [tag, payload, self.occ_aware_visibility, keyframes]
        self.frontend_queue.put(msg)

    def _release_cuda_state_for_shutdown(self):
        """Drop tensors imported from the frontend before this process exits."""

        self.keyframe_optimizers = None
        self.gaussians = None
        self.background = None
        self.viewpoints = {}
        self.occ_aware_visibility = {}
        self.current_window = []
        release_cuda_ipc_cache()

    def run(self):
        """Run the worker loop and report failures before process exit."""
        try:
            self._run_loop()
        except BaseException as exc:
            Log(
                "Backend worker failed: "
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            )
            try:
                self.frontend_queue.put(
                    ["backend_error", f"{type(exc).__name__}: {exc}"]
                )
            except (OSError, EOFError, ValueError):
                pass
            try:
                self.save_timing_stats()
            except Exception:
                pass
            raise

    def _run_loop(self):
        while True:
            if self.backend_queue.empty():
                if self.pause:
                    time.sleep(0.01)
                    continue
                if len(self.current_window) == 0:
                    time.sleep(0.01)
                    continue

                if self.single_thread:
                    time.sleep(0.01)
                    continue
                self.map(self.current_window)
                if self.last_sent >= 10:
                    self.map(self.current_window, prune=True, iters=10)
                    self.push_to_frontend()
            else:
                data = self.backend_queue.get()
                if data[0] == "stop":
                    break
                elif data[0] == "pause":
                    self.pause = True
                elif data[0] == "save_timing":
                    self.save_timing_stats()
                    # This CPU-only marker is ordered after every earlier snapshot
                    # put by this producer.  The frontend drains through it before
                    # shutdown, so no CUDA IPC payload remains stranded in the queue.
                    self.frontend_queue.put(["timing_saved"])
                elif data[0] == "unpause":
                    self.pause = False
                elif data[0] == "color_refinement":
                    self.color_refinement()
                    self.save_timing_stats()
                    self.push_to_frontend()
                elif data[0] == "init":
                    cur_frame_idx = data[1]
                    viewpoint = data[2]
                    depth_map = data[3]
                    Log("Resetting the system")
                    self.reset()

                    self.viewpoints[cur_frame_idx] = viewpoint
                    self.add_next_kf(
                        cur_frame_idx, viewpoint, depth_map=depth_map, init=True
                    )
                    self.initialize_map(cur_frame_idx, viewpoint)
                    self.push_to_frontend("init")

                elif data[0] == "promote":
                    source_id = data[1]
                    depth_map = data[2]
                    source = self.viewpoints.get(source_id)
                    if source is None:
                        Log(f"Deferred promotion skipped: missing KF {source_id}")
                        continue
                    inserted = self.gaussians.extend_from_pcd_seq(
                        source,
                        kf_id=source_id,
                        init=False,
                        depthmap=np.ascontiguousarray(depth_map, dtype=np.float32),
                        downsample_factor=int(
                            self.config.get("DeferredCommit", {}).get(
                                "promotion_downsample", 1
                            )
                        ),
                        min_gaussian_scale=float(
                            self.config.get("DeferredCommit", {}).get(
                                "promotion_min_scale_m", 0.001
                            )
                        ),
                        max_gaussian_scale=float(
                            self.config.get("DeferredCommit", {}).get(
                                "promotion_max_scale_m", 0.02
                            )
                        ),
                    )
                    deferred_cfg = self.config.get("DeferredCommit", {})
                    if bool(deferred_cfg.get("cuda_debug_sync", False)):
                        torch.cuda.synchronize()
                    if bool(deferred_cfg.get("validate_state_after_promotion", True)):
                        self.gaussians.validate_runtime_state()
                    Log(
                        f"Deferred promotion KF {source_id}: "
                        f"inserted {inserted} Gaussians"
                    )
                    self._log_promoted_parameter_health(inserted)

                elif data[0] == "keyframe":
                    cur_frame_idx = data[1]
                    viewpoint = data[2]
                    current_window = data[3]
                    depth_map = data[4]

                    self.viewpoints[cur_frame_idx] = viewpoint
                    self.current_window = current_window
                    self.add_next_kf(cur_frame_idx, viewpoint, depth_map=depth_map)

                    opt_params = []
                    frames_to_optimize = self.config["Training"]["pose_window"]
                    iter_per_kf = self.mapping_itr_num if self.single_thread else self.async_iter_per_kf
                    if not self.initialized:
                        if (
                            len(self.current_window)
                            == self.config["Training"]["window_size"]
                        ):
                            frames_to_optimize = (
                                self.config["Training"]["window_size"] - 1
                            )
                            iter_per_kf = 50 if self.live_mode else 300
                            Log("Performing initial BA for initialization")
                        else:
                            iter_per_kf = self.mapping_itr_num
                    for cam_idx in range(len(self.current_window)):
                        if self.current_window[cam_idx] == 0:
                            continue
                        viewpoint = self.viewpoints[current_window[cam_idx]]
                        if cam_idx < frames_to_optimize:
                            opt_params.append(
                                {
                                    "params": [viewpoint.cam_rot_delta],
                                    "lr": self.config["Training"]["lr"]["cam_rot_delta"]
                                    * 0.5,
                                    "name": "rot_{}".format(viewpoint.uid),
                                }
                            )
                            opt_params.append(
                                {
                                    "params": [viewpoint.cam_trans_delta],
                                    "lr": self.config["Training"]["lr"][
                                        "cam_trans_delta"
                                    ]
                                    * 0.5,
                                    "name": "trans_{}".format(viewpoint.uid),
                                }
                            )
                        opt_params.append(
                            {
                                "params": [viewpoint.exposure_a],
                                "lr": 0.01,
                                "name": "exposure_a_{}".format(viewpoint.uid),
                            }
                        )
                        opt_params.append(
                            {
                                "params": [viewpoint.exposure_b],
                                "lr": 0.01,
                                "name": "exposure_b_{}".format(viewpoint.uid),
                            }
                        )
                    self.keyframe_optimizers = torch.optim.Adam(opt_params)

                    self.map(self.current_window, iters=iter_per_kf)
                    self.map(self.current_window, prune=True)
                    if alpha_lifecycle.alpha_lifecycle_active(self.config):
                        kf_view = self.viewpoints[cur_frame_idx]
                        # Feed the DENSE SENSOR depth, never `depth_map`. Under
                        # prune/deferred, `depth_map` is `decision.immediate_depth_map`
                        # (slam_frontend) -- the *insertion* map, i.e. only pixels the
                        # current map does NOT already explain, and for deferred nearly
                        # empty by construction. Using it made the exit pass blind
                        # exactly where the map HAS content, which is where ghosts live:
                        # `depth_inconsistency_evidence` needs `observed > 0.01`, so
                        # evidence validity decayed to ~0 as the map filled in (measured
                        # 6.7% -> 0.02% of pixels over 150 frames) and alpha never moved
                        # more than one EMA step. `viewpoint.depth` is the raw sensor
                        # depth (Camera.depth); it is None only after clean().
                        self._alpha_lifecycle_step(
                            kf_view,
                            kf_view.depth if kf_view.depth is not None else depth_map,
                        )
                    self.push_to_frontend("keyframe")

                elif data[0] == "insert_candidates_cam":
                    # transient_map（默认关）的 per-frame 瞬态插入：与 "insert_candidates" 共用同一个
                    # 构建函数，但**相机参数随消息显式下发** —— 因为插入帧不是 KF，self.viewpoints
                    # 里没有它的视角（见 utils/transient_map.py 模块 docstring 与预注册修正案 1）。
                    # data = [tag, fx, fy, cx, cy, R, T, px, py, depth, color, lineage_id,
                    #         min_scale, max_scale, fit_iters[, image, depth_map, mask]]
                    #（Tfit 修正案 2：fit_iters>0 时消息尾再带观测，len 守卫兼容旧消息）
                    cam = transient_cam_from_msg(data[1], data[2], data[3], data[4],
                                                 data[5], data[6])
                    n_in = len(data[7])
                    inserted = self.gaussians.insert_candidate_gaussians(
                        cam,
                        data[7],
                        data[8],
                        data[9],
                        data[10],
                        kf_id=int(data[11]),  # lineage = 帧号；仅作簿记（该帧未注册为 KF）
                        lineage_ids=np.full(n_in, int(data[11]), dtype=np.int32),
                        min_gaussian_scale=float(data[12]),
                        max_gaussian_scale=float(data[13]),
                    )
                    Log(
                        f"transient insert frame {int(data[11])}: "
                        f"{int(inserted)} Gaussians (lineage {int(data[11])})"
                    )
                    fit_iters = int(data[14]) if len(data) > 14 else 0
                    if fit_iters > 0 and int(inserted) > 0:
                        obs = transient_obs_from_msg(data[15], data[16], data[17])
                        ev = self._transient_fit(cam, int(data[11]), obs, fit_iters)
                        Log(f"transient fit frame {int(data[11])}: {ev}")

                elif data[0] == "insert_candidates":
                    # Prune insert-now / deferred promotion via the deterministic
                    # direct-from-arrays builder (bypasses the o3d depth-map path so
                    # per-candidate lineage survives 1:1). data = [tag, source_id,
                    # px, py, depth, color, lineage_ids, min_scale, max_scale].
                    source_id = data[1]
                    source = self.viewpoints.get(source_id)
                    if source is None:
                        Log(f"Candidate insert skipped: missing KF {source_id}")
                        continue
                    inserted = self.gaussians.insert_candidate_gaussians(
                        source,
                        data[2],
                        data[3],
                        data[4],
                        data[5],
                        kf_id=source_id,
                        lineage_ids=data[6],
                        min_gaussian_scale=float(data[7]),
                        max_gaussian_scale=float(data[8]),
                    )
                    deferred_cfg = self.config.get("DeferredCommit", {})
                    if bool(deferred_cfg.get("cuda_debug_sync", False)):
                        torch.cuda.synchronize()
                    if bool(deferred_cfg.get("validate_state_after_promotion", True)):
                        self.gaussians.validate_runtime_state()
                    Log(
                        f"Candidate insert KF {source_id}: "
                        f"inserted {inserted} Gaussians"
                    )
                    self._log_promoted_parameter_health(inserted)

                elif data[0] == "prune_lineage":
                    # Reject/expire/capacity lineage delete (prune arm). Removes the
                    # full lineage (parent + clone/split descendants + optimizer state)
                    # for each id. data = [tag, [lineage_id, ...]].
                    lineage_ids = data[1]
                    before = self.gaussians.get_xyz.shape[0]
                    self.gaussians.prune_lineage(lineage_ids)
                    removed = before - self.gaussians.get_xyz.shape[0]
                    deferred_cfg = self.config.get("DeferredCommit", {})
                    if bool(deferred_cfg.get("cuda_debug_sync", False)):
                        torch.cuda.synchronize()
                    if bool(deferred_cfg.get("validate_state_after_promotion", True)):
                        self.gaussians.validate_runtime_state()
                    Log(
                        f"Pruned {len(lineage_ids)} lineage(s): "
                        f"removed {removed} Gaussians"
                    )
                else:
                    raise Exception("Unprocessed data", data)
        self.save_timing_stats()
        self._release_cuda_state_for_shutdown()
        return
