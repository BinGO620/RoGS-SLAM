import os
import time
from queue import Empty

import numpy as np
import torch
import torch.multiprocessing as mp

from gaussian_splatting.gaussian_renderer import render
from gaussian_splatting.utils.graphics_utils import getProjectionMatrix2, getWorld2View2
from gui import gui_utils
from utils.camera_utils import Camera
from utils.bootstrap_vo import (
    BootstrapVO,
    bootstrap_vo_enabled,
    write_bootstrap_summary,
)
from utils.deferred_commit import (
    DeferredCommitManager,
    deferred_commit_enabled,
    deferred_reliability_confirm_enabled,
    lifecycle_mode,
)
from utils.full_frame_pose import (
    FullFramePoseManager,
    full_frame_pose_enabled,
    pose_prior_loss,
)
from utils.eval_utils import eval_ate, save_gaussians
from utils.logging_utils import Log
from utils.multiprocessing_utils import clone_obj, clone_tensor_tree
from utils.oracle_pose import load_external_trajectory, oracle_pose_file
from utils.pose_utils import update_pose
from utils.reliable_tracking import (
    projected_border_weight,
    reliable_tracking_enabled,
    write_reliable_tracking_summary,
)
from utils.reliability import ReliabilityRecorder, get_reliability_config
from utils.reliability_signal import (
    assert_reliability_flow_available,
    compute_reliability_tracking_weight,
    get_reliability_signal_config,
    relative_pose_target_from_source,
    reliability_signal_enabled,
    stash_dba_weights_enabled,
    save_dba_weight_snapshot,
    _dba_weight_stem,
)
from utils.flow_raft import frozen_flow_index, load_frozen_flow
from utils.slam_utils import get_loss_tracking, get_median_depth
from utils.tri_reliability import (
    TriReliabilityRecorder,
    compute_tri_reliability,
    get_tri_reliability_config,
    tri_reliability_policy_enabled,
)
from utils.flow_mask import compute_flow_residual_mask, get_flow_tracking_config
from utils.flow_mask_baseline import resolve_flow_mask
from utils.semantic_mask import (
    compute_semantic_dynamic_mask,
    compute_semantic_person_prob,
    flow_threshold_mask_enabled,
    get_or_compute_dynamic_mask,
    get_semantic_mask_config,
    semantic_mask_enabled,
    write_semantic_timing_summary,
)
from utils.mask_quality import (
    detect_gap,
    dilate_mask,
    get_mask_qa_config,
    mask_coverage,
    mask_qa_enabled,
)
from utils.static_prob import (
    compute_residual_evidence,
    render_static_prob_map,
    static_prob_enabled,
    update_static_prob_from_evidence,
)
from utils.static_evidence import (
    StaticEvidenceRecorder,
    compute_static_evidence,
    static_evidence_enabled,
)
from utils.visibility_window import (
    update_visibility_window,
    visibility_window_enabled,
)
from utils.coarse_pose import (
    coarse_pose_enabled,
    compute_coarse_pose_init,
)


class AteAbort(RuntimeError):
    """Stop an evaluation run after its online prefix has clearly failed."""


def ate_abort_reason(config, ate_m, frame_idx):
    """Return a failure reason when the configured ATE budget is exceeded.

    Ground truth is used only by the evaluator to save experiment time.  This signal
    never enters tracking, mapping, pose selection, or method outputs.
    """

    results = config.get("Results", {})
    threshold_cm = float(results.get("ate_abort_threshold_cm", 0.0))
    min_frames = int(results.get("ate_abort_min_frames", 100))
    ate_cm = float(ate_m) * 100.0
    if (
        threshold_cm > 0.0
        and frame_idx >= min_frames
        and np.isfinite(ate_cm)
        and ate_cm > threshold_cm
    ):
        return (
            f"ATE_ABORT threshold exceeded: frame={frame_idx} "
            f"ate_cm={ate_cm:.4f} threshold_cm={threshold_cm:.4f}"
        )
    return None


# Column contract for reliability_signal/frames.csv. BASE is the historical
# no-harm-audit block; its order is frozen so existing readers keep working.
# Every OTHER key a row carries is appended rather than enumerated here.
#
# WHY derived and not hand-listed: a hard-coded whitelist silently deleted
# `ego_pose_oracle` and every `ego_*` guard stat from the entire P8 campaign,
# while the producer (reliability_signal.py `stats`) and the call site both
# carried comments asserting the column "never disappears". Enumerating the
# columns in a third place is what let the assertion and the disk disagree, so
# the writer now follows the rows instead of a list someone must remember to
# update. See results/evidence/eflow_pose_error_defect.md.
RELIABILITY_FRAMES_BASE_FIELDS = (
    "frame", "tracking_itr", "mean_s", "min_s", "mean_w", "min_w",
    "flow_valid_frac", "e_flow_mean_valid", "g_mean",
)


def reliability_frames_fields(rows):
    """frames.csv column order: frozen base block, then every other key present."""
    base = list(RELIABILITY_FRAMES_BASE_FIELDS)
    seen = set(base)
    return base + sorted({k for r in rows for k in r if k not in seen})


def reliability_frames_summary(rows):
    """Run-level aggregates for summary.json, including ego-projection provenance.

    The ego block only appears when the rows carry it, so a run that never
    enabled the projection is not decorated with meaningless zeros.
    """
    n = len(rows)
    summary = {
        "frames": n,
        "mean_mean_w": sum(r["mean_w"] for r in rows) / n,
        "mean_min_w": sum(r["min_w"] for r in rows) / n,
        "mean_flow_valid_frac": sum(r["flow_valid_frac"] for r in rows) / n,
        "mean_mean_s": sum(r["mean_s"] for r in rows) / n,
    }
    if any("ego_projection" in r for r in rows):
        applied = [r for r in rows if int(r.get("ego_fit_applied", 0) or 0) == 1]
        rejects = {}
        for r in rows:
            reason = str(r.get("ego_reject", "none") or "none")
            rejects[reason] = rejects.get(reason, 0) + 1
        summary["ego_projection"] = int(any(
            int(r.get("ego_projection", 0) or 0) == 1 for r in rows
        ))
        summary["ego_fit_applied_frames"] = len(applied)
        summary["ego_fit_applied_frac"] = len(applied) / n
        summary["ego_reject_counts"] = dict(sorted(rejects.items()))
        if applied:
            summary["mean_ego_corr_px"] = sum(
                float(r.get("ego_corr_px", 0.0) or 0.0) for r in applied
            ) / len(applied)
            summary["mean_ego_explained_frac"] = sum(
                float(r.get("ego_explained_frac", 0.0) or 0.0) for r in applied
            ) / len(applied)
    if any("ego_pose_oracle" in r for r in rows):
        summary["ego_pose_oracle"] = int(any(
            int(r.get("ego_pose_oracle", 0) or 0) == 1 for r in rows
        ))
    if any("mad_excl_applied" in r for r in rows):
        # T2 mechanism self-evidence: the campaign's FIRST criterion is "did the
        # quota actually remove anything, and on how many frames", because an ATE
        # delta read off an inert mechanism is meaningless. `mad_excl_bind` says
        # WHICH cap held k down on the frames where it did little, and
        # `max_mad_zero_frac_after` is the on-disk proof that the collapse the
        # quota is built to prevent never happened (it must stay <= max_zero_frac).
        binds = {}
        for r in rows:
            key = str(r.get("mad_excl_bind", "none") or "none")
            binds[key] = binds.get(key, 0) + 1
        applied = [r for r in rows if int(r.get("mad_excl_applied", 0) or 0) == 1]
        summary["mad_excl_applied_frames"] = len(applied)
        summary["mad_excl_applied_frac"] = len(applied) / n
        summary["mad_excl_bind_counts"] = dict(sorted(binds.items()))
        summary["mean_mad_excl_frac"] = sum(
            float(r.get("mad_excl_frac", 0.0) or 0.0) for r in rows
        ) / n
        summary["mean_mad_zero_frac_before"] = sum(
            float(r.get("mad_zero_frac_before", 0.0) or 0.0) for r in rows
        ) / n
        summary["mean_mad_zero_frac_after"] = sum(
            float(r.get("mad_zero_frac_after", 0.0) or 0.0) for r in rows
        ) / n
        summary["max_mad_zero_frac_after"] = max(
            float(r.get("mad_zero_frac_after", 0.0) or 0.0) for r in rows
        )
    return summary


def write_reliability_frames(directory, rows):
    """Write frames.csv + summary.json; return the field list actually written."""
    import csv
    import json

    os.makedirs(directory, exist_ok=True)
    fields = reliability_frames_fields(rows)
    with open(
        os.path.join(directory, "frames.csv"), "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in fields})
    with open(os.path.join(directory, "summary.json"), "w", encoding="utf-8") as file:
        json.dump(reliability_frames_summary(rows), file, indent=2)
    return fields


class FrontEnd(mp.Process):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.background = None
        self.pipeline_params = None
        self.frontend_queue = None
        self.backend_queue = None
        self.q_main2vis = None
        self.q_vis2main = None

        self.initialized = False
        self.kf_indices = []
        self.monocular = config["Training"]["monocular"]
        self.iteration_count = 0
        self.occ_aware_visibility = {}
        self.current_window = []

        self.reset = True
        self.requested_init = False
        self.requested_keyframe = 0
        self.use_every_n_frames = 1

        self.gaussians = None
        self.cameras = dict()
        self.device = "cuda:0"
        self.pause = False
        self.tracking_time_s = 0.0
        self.tracking_frames = 0
        self.reliability_recorder = ReliabilityRecorder(config, "tracking")
        self.tri_reliability_recorder = TriReliabilityRecorder(config, "tracking")
        # P2b flow-residual dynamic mask: cache prev frame RGB + pose (before cleanup)
        self.prev_flow_rgb = None
        self.prev_flow_wvt = None
        # P4a coarse pose init (ICP): cache prev frame gt depth before clean() drops it
        self.prev_icp_depth = None
        # masked_icp (SPEC-1): cache prev frame's person mask (matching prev_icp_depth)
        # so the ICP can also reject matches landing on previous-frame person geometry.
        self.prev_icp_mask = None
        # ORB-style full-traj recomposition: record each frame's pose relative to its
        # reference keyframe so non-KFs can inherit the backend-optimized KF pose at
        # export (default-off, config-gated). See eval_utils.save_final_tracking_raw.
        self.kf_propagate = bool(
            config.get("FinalTrajectory", {}).get("kf_propagate", False)
        )
        # Dynamic-crisis keyframing: coverage of the current frame's dynamic (person)
        # mask, updated in tracking(); high coverage / fast motion promotes denser
        # keyframe insertion so fast-motion non-KFs get backend BA (default-off).
        self.last_dyn_coverage = 0.0
        # M2 anchor probe: last frame's anchor statistics dict (READ-ONLY diagnostic).
        # Nothing online consumes it; it exists so a later M3 (anchor-triggered
        # keyframing) can read the same numbers the probe put in frames.csv.
        self._anchor_last = None
        # Latest frame's person mask, stashed by tracking() so the semantic insertion
        # gate (add_new_keyframe, same frame) reuses it instead of re-running Mask R-CNN.
        # Only one mask is held -> no per-viewpoint accumulation. (idx, mask-or-None)
        self._last_semantic_mask_idx = None
        self._last_semantic_mask = None
        # P1 mask QA / propagation-lite state (single owner). Recent coverages + last
        # good (non-gap) mask so a Mask R-CNN detection miss reuses the previous mask
        # instead of leaking the person into tracking/mapping/BA. Default-off (MaskQA).
        self.mask_qa_recent = []
        self.mask_qa_last_mask = None
        self.mask_qa_gap_streak = 0
        self.bootstrap_frames = []
        self.bootstrap_masks = []
        self.bootstrap_fallback = False
        self.deferred_manager = None
        self.full_frame_pose_manager = None
        self.static_evidence_recorder = None
        # Reliability signal s -> Cauchy tracking down-weight (method #8). Frozen-flow
        # index (built lazily from ReliabilitySignal.flow_subdir) + per-frame s/w stats.
        self._reliability_flow_index = None
        self._flow_mask_index = None  # WP-B flow-mask baseline frozen-flow index
        self.reliability_signal_rows = []
        # Fixed external-trajectory oracle (Oracle.pose_file): per-frame W2C tensors,
        # loaded lazily once (needs self.dataset, attached by slam.py after __init__).
        self._oracle_pose_w2c = None
        self._oracle_pose_checked = False
        self.backend_process = None

    def set_hyperparams(self):
        self.save_dir = self.config["Results"]["save_dir"]
        self.save_results = self.config["Results"]["save_results"]
        self.save_trj = self.config["Results"]["save_trj"]
        self.save_trj_kf_intv = self.config["Results"]["save_trj_kf_intv"]

        self.tracking_itr_num = self.config["Training"]["tracking_itr_num"]
        self.kf_interval = self.config["Training"]["kf_interval"]
        self.window_size = self.config["Training"]["window_size"]
        self.single_thread = self.config["Training"]["single_thread"]
        self.max_frames = int(self.config["Dataset"].get("max_frames", 0))
        # Dynamic-crisis keyframing (default-off): promote keyframe insertion during
        # high dynamic-occlusion / fast-motion frames to shrink keyframe gaps where
        # non-KF drift accumulates. See the keyframe-decision block in run().
        self.dyn_kf_cfg = self.config.get("DynamicKeyframe", {})
        self.dyn_kf_enabled = bool(self.dyn_kf_cfg.get("enabled", False))
        # M2 anchor probe (default-off, READ-ONLY). Task B asks whether a tracking
        # collapse is preceded by the set of pixels that still CONSTRAIN the pose
        # thinning out (or going bad). This probe measures that set per frame and
        # writes it to reliability_signal/frames.csv; it never feeds tracking, the
        # keyframe decision, or the map. Off => `rstats` gains no keys, so the
        # frames.csv column set stays identical to every historic run.
        self.anchor_probe_enabled = bool(self.dyn_kf_cfg.get("anchor_probe", False))
        self.anchor_thresholds = tuple(
            float(t) for t in self.dyn_kf_cfg.get("anchor_thresholds", (0.80, 0.90, 0.95))
        )
        self.anchor_require_grad_mask = bool(
            self.dyn_kf_cfg.get("anchor_require_grad_mask", True)
        )
        # Keyframe-decision instrumentation (default-off): dump per-frame covisibility
        # Jaccard + projected person-mask decomposition to test whether un-optimized
        # dynamic Gaussians inflate inter-frame overlap and suppress covisibility
        # keyframing. See _keyframe_diag / the decision block in run().
        self.kf_diag_enabled = bool(
            self.config.get("KeyframeDiag", {}).get("enabled", False)
        )
        self.kf_diag_rows = []
        lifecycle = lifecycle_mode(self.config)
        if (
            bootstrap_vo_enabled(self.config)
            or deferred_commit_enabled(self.config)
            or full_frame_pose_enabled(self.config)
            or lifecycle in ("prune", "deferred")
        ) and self.monocular:
            raise ValueError(
                "BootstrapVO, DeferredCommit, FullFramePose, and the prune/deferred "
                "lifecycle arms support RGB-D input only"
            )
        if bootstrap_vo_enabled(self.config):
            bootstrap_frames = int(
                self.config.get("BootstrapVO", {}).get("max_frames", 3)
            )
            if bootstrap_frames != 3:
                raise ValueError("BootstrapVO is a three-frame initializer")
        if deferred_commit_enabled(self.config) or lifecycle in ("prune", "deferred"):
            self.deferred_manager = DeferredCommitManager(self.config, self.save_dir)
        if full_frame_pose_enabled(self.config):
            if not static_evidence_enabled(self.config):
                raise ValueError("FullFramePose requires StaticEvidence.enabled=true")
            self.full_frame_pose_manager = FullFramePoseManager(
                self.config, self.save_dir
            )
        if static_evidence_enabled(self.config):
            self.static_evidence_recorder = StaticEvidenceRecorder(self.save_dir)

    def add_new_keyframe(
        self, cur_frame_idx, image=None, depth=None, opacity=None, init=False
    ):
        rgb_boundary_threshold = self.config["Training"]["rgb_boundary_threshold"]
        self.kf_indices.append(cur_frame_idx)
        viewpoint = self.cameras[cur_frame_idx]
        gt_img = viewpoint.original_image.cuda()
        valid_rgb = (gt_img.sum(dim=0) > rgb_boundary_threshold)[None]
        if self.monocular:
            if depth is None:
                initial_depth = 2 * torch.ones(1, gt_img.shape[1], gt_img.shape[2])
                initial_depth += torch.randn_like(initial_depth) * 0.3
            else:
                depth = depth.detach().clone()
                opacity = opacity.detach()
                use_inv_depth = False
                if use_inv_depth:
                    inv_depth = 1.0 / depth
                    inv_median_depth, inv_std, valid_mask = get_median_depth(
                        inv_depth, opacity, mask=valid_rgb, return_std=True
                    )
                    invalid_depth_mask = torch.logical_or(
                        inv_depth > inv_median_depth + inv_std,
                        inv_depth < inv_median_depth - inv_std,
                    )
                    invalid_depth_mask = torch.logical_or(
                        invalid_depth_mask, ~valid_mask
                    )
                    inv_depth[invalid_depth_mask] = inv_median_depth
                    inv_initial_depth = inv_depth + torch.randn_like(
                        inv_depth
                    ) * torch.where(invalid_depth_mask, inv_std * 0.5, inv_std * 0.2)
                    initial_depth = 1.0 / inv_initial_depth
                else:
                    median_depth, std, valid_mask = get_median_depth(
                        depth, opacity, mask=valid_rgb, return_std=True
                    )
                    invalid_depth_mask = torch.logical_or(
                        depth > median_depth + std, depth < median_depth - std
                    )
                    invalid_depth_mask = torch.logical_or(
                        invalid_depth_mask, ~valid_mask
                    )
                    depth[invalid_depth_mask] = median_depth
                    initial_depth = depth + torch.randn_like(depth) * torch.where(
                        invalid_depth_mask, std * 0.5, std * 0.2
                    )

                initial_depth[~valid_rgb] = 0  # Ignore the invalid rgb pixels
            initial_depth = self.apply_tri_insertion_gate(
                cur_frame_idx, image, depth, opacity, viewpoint, initial_depth
            )
            initial_depth = self.apply_semantic_insertion_gate(
                cur_frame_idx, viewpoint, initial_depth
            )
            return initial_depth.cpu().numpy()[0]
        # use the observed depth
        initial_depth = torch.from_numpy(viewpoint.depth).to(gt_img.device).unsqueeze(0)
        initial_depth[~valid_rgb] = 0  # Ignore the invalid rgb pixels
        initial_depth = self.apply_tri_insertion_gate(
            cur_frame_idx, image, depth, opacity, viewpoint, initial_depth
        )
        initial_depth = self.apply_semantic_insertion_gate(
            cur_frame_idx, viewpoint, initial_depth
        )
        return initial_depth.cpu().numpy()[0]

    def apply_tri_insertion_gate(
        self, cur_frame_idx, image, depth, opacity, viewpoint, initial_depth
    ):
        if image is None or depth is None or opacity is None:
            return initial_depth
        if not tri_reliability_policy_enabled(
            self.config, "mapping", "apply_insertion_gate"
        ):
            return initial_depth

        tri_config = get_tri_reliability_config(self.config)
        dynamic_threshold = float(tri_config.get("insertion_dynamic_threshold", 0.45))
        max_gate_ratio = float(tri_config.get("max_insertion_gate_ratio", 0.35))
        metrics = compute_tri_reliability(
            self.config,
            image,
            depth,
            opacity,
            viewpoint,
            use_exposure=True,
        )
        valid_mask = metrics["valid_mask"]
        dynamic_mask = (metrics["dynamic_evidence"] > dynamic_threshold) & valid_mask
        valid_pixels = max(int(valid_mask.count_nonzero().item()), 1)
        gate_ratio = dynamic_mask.count_nonzero().item() / valid_pixels
        if gate_ratio > max_gate_ratio:
            Log(
                "TriReliability insertion gate skipped "
                f"frame {cur_frame_idx}: ratio={gate_ratio:.4f}"
            )
            return initial_depth

        initial_depth = initial_depth.clone()
        initial_depth[dynamic_mask] = 0
        Log(
            "TriReliability insertion gate "
            f"frame {cur_frame_idx}: ratio={gate_ratio:.4f}"
        )
        return initial_depth

    def apply_semantic_insertion_gate(self, cur_frame_idx, viewpoint, initial_depth):
        """Semantic insertion gate (default-off): zero the person-mask pixels in a
        new keyframe's depth map so dynamic (person) Gaussians are never inserted
        into the map. Reuses the SAME cached Mask R-CNN person mask as mask-both
        (get_or_compute_dynamic_mask), so it adds no extra detector cost on a
        mask-both run. Complements ``SemanticMask.mask_mapping``, which only masks
        the mapping LOSS -- person Gaussians were still inserted (un-optimized),
        leaving ghost floaters that hurt rendering and inflate keyframe covisibility.
        Zeroed pixels are dropped by ``create_pcd_from_image_and_depth``
        (project_valid_depth_only=True). Gated by ``SemanticMask.mask_insertion``;
        off -> returns the depth unchanged (vanilla insertion)."""
        sem_cfg = get_semantic_mask_config(self.config)
        if not (
            semantic_mask_enabled(self.config)
            and bool(sem_cfg.get("mask_insertion", False))
        ):
            return initial_depth
        # Reuse the mask tracking() already computed for THIS frame (no extra detector
        # forward); only fall back to compute if it is somehow unavailable.
        if self._last_semantic_mask_idx == cur_frame_idx:
            person_mask = self._last_semantic_mask
        else:
            person_mask = get_or_compute_dynamic_mask(self.config, viewpoint)
        if person_mask is None:
            return initial_depth
        pm = person_mask.to(initial_depth.device).bool()
        if pm.shape != initial_depth.shape:
            return initial_depth  # shape guard -- never silently mis-zero
        n = int(pm.count_nonzero().item())
        if n == 0:
            return initial_depth
        initial_depth = initial_depth.clone()
        initial_depth[pm] = 0
        Log(
            "Semantic insertion gate "
            f"frame {cur_frame_idx}: {n} person px zeroed (no dynamic Gaussians)"
        )
        return initial_depth

    def _apply_mask_qa(self, cur_frame_idx, semantic_mask):
        """P1 mask QA / propagation-lite: detect a Mask R-CNN detection gap (person
        present in recent frames but current coverage collapsed) and substitute the
        last good mask (dilated to cover motion), bounded to a few consecutive frames
        so a genuinely person-free stretch is not force-masked forever. Returns the
        mask to use downstream. Default-off (MaskQA.enabled)."""
        cfg = get_mask_qa_config(self.config)
        cov = mask_coverage(semantic_mask)
        is_gap = detect_gap(cov, list(self.mask_qa_recent), cfg)
        max_streak = int(cfg.get("max_consecutive_propagate", 3))
        used = semantic_mask
        propagated = False
        if (
            is_gap
            and self.mask_qa_last_mask is not None
            and self.mask_qa_gap_streak < max_streak
        ):
            used = dilate_mask(
                self.mask_qa_last_mask, int(cfg.get("propagate_dilate_px", 5))
            )
            propagated = True
            self.mask_qa_gap_streak += 1
        else:
            if not is_gap:
                self.mask_qa_gap_streak = 0
                # remember the last good (non-gap, non-empty) mask for future fallback
                if semantic_mask is not None and cov >= float(
                    cfg.get("gap_abs_thresh", 0.005)
                ):
                    self.mask_qa_last_mask = semantic_mask.detach()
        # audit history uses the OBSERVED coverage (not the propagated one)
        self.mask_qa_recent.append(cov)
        if len(self.mask_qa_recent) > int(cfg.get("recent_window", 5)):
            self.mask_qa_recent.pop(0)
        if is_gap or cur_frame_idx % 50 == 0:
            Log(
                f"MaskQA f{cur_frame_idx}: cov={cov:.3f} gap={is_gap} "
                f"propagated={propagated} streak={self.mask_qa_gap_streak}"
            )
        return used

    def _oracle_external_pose(self, cur_frame_idx):
        """Fixed external-trajectory oracle (``Oracle.pose_file``): W2C or ``None``.

        Loaded lazily once. The loader GT-anchors the file into the dataset's
        world frame and raises on any mismatch (self-validating — see
        ``utils/oracle_pose.py``). ``viewpoint.R_gt/T_gt`` are never touched, so
        the final ATE row measures injected-vs-real-GT (sanity anchor: must
        reproduce the borrowed tracker's published ATE).
        """
        if not self._oracle_pose_checked:
            self._oracle_pose_checked = True
            pose_file = oracle_pose_file(self.config)
            if pose_file:
                poses, info = load_external_trajectory(
                    pose_file, np.asarray(self.dataset.poses, dtype=np.float64)
                )
                self._oracle_pose_w2c = [
                    (
                        torch.from_numpy(np.ascontiguousarray(R)).float(),
                        torch.from_numpy(np.ascontiguousarray(t)).float(),
                    )
                    for R, t in poses
                ]
                Log(
                    f"Oracle pose_file loaded: {os.path.basename(pose_file)} "
                    f"frames={info['frames']} anchor_rmse={info['anchor_rmse_cm']:.3f}cm "
                    f"rot_max={info['anchor_rot_max_deg']:.2f}deg scale={info['scale']:.5f}",
                    tag="Oracle",
                )
        if self._oracle_pose_w2c is None:
            return None
        if cur_frame_idx >= len(self._oracle_pose_w2c):
            raise IndexError(
                f"Oracle.pose_file has {len(self._oracle_pose_w2c)} frames, "
                f"frame {cur_frame_idx} requested"
            )
        return self._oracle_pose_w2c[cur_frame_idx]

    def initialize(self, cur_frame_idx, viewpoint, initial_depth=None):
        self.initialized = not self.monocular
        self.kf_indices = []
        self.iteration_count = 0
        self.occ_aware_visibility = {}
        self.current_window = []
        # remove everything from the queues
        while not self.backend_queue.empty():
            self.backend_queue.get()

        # Initialise the frame at the ground truth pose (or the fixed external
        # trajectory when Oracle.pose_file is set — same world frame by anchor).
        oracle_ext_init = self._oracle_external_pose(cur_frame_idx)
        if oracle_ext_init is not None:
            viewpoint.update_RT(*oracle_ext_init)
        else:
            viewpoint.update_RT(viewpoint.R_gt, viewpoint.T_gt)

        self.kf_indices = []
        if initial_depth is None:
            depth_map = self.add_new_keyframe(cur_frame_idx, init=True)
        else:
            self.kf_indices.append(cur_frame_idx)
            depth_map = initial_depth
        self.request_init(cur_frame_idx, viewpoint, depth_map)
        self.reset = False
        # P4a: seed / reset the ICP prev-depth cache at (re)initialization.
        if coarse_pose_enabled(self.config) and viewpoint.depth is not None:
            self.prev_icp_depth = (
                torch.from_numpy(viewpoint.depth).to(self.device).float()
            )
        else:
            self.prev_icp_depth = None
        self.prev_icp_mask = None  # no previous person mask at (re)init
        self.mask_qa_recent = []
        self.mask_qa_last_mask = None
        self.mask_qa_gap_streak = 0

    def _bootstrap_mask(self, frame_idx, viewpoint):
        mask = None
        if semantic_mask_enabled(self.config):
            semantic_cfg = get_semantic_mask_config(self.config)
            if bool(semantic_cfg.get("soft", False)):
                probability = compute_semantic_person_prob(
                    self.config, viewpoint.original_image
                )
                if probability is not None:
                    mask = probability >= 0.5
            else:
                mask = compute_semantic_dynamic_mask(
                    self.config, viewpoint.original_image
                )
        viewpoint.dynamic_mask = None if mask is None else mask.detach()
        return mask

    def _finish_bootstrap(self):
        bootstrap = BootstrapVO(self.config)
        result = bootstrap.run(self.bootstrap_frames, self.bootstrap_masks)
        for camera, pose in zip(self.bootstrap_frames, result.poses_cw):
            camera.update_RT(
                torch.from_numpy(pose[:3, :3]).to(self.device, dtype=torch.float32),
                torch.from_numpy(pose[:3, 3]).to(self.device, dtype=torch.float32),
            )
        self.bootstrap_fallback = result.fallback
        pose_summary = ", ".join(
            f"{item.inliers}/{item.matches}" for item in result.pose_stats
        )
        Log(
            "BootstrapVO "
            f"fallback={result.fallback}, confirmed={result.confirmed_pixels}, "
            f"PnP inliers={pose_summary}"
        )
        write_bootstrap_summary(self.save_dir, result, self.bootstrap_frames)
        source = self.bootstrap_frames[0]
        last_bootstrap = self.bootstrap_frames[-1]
        last_bootstrap_mask = self.bootstrap_masks[-1]
        self.initialize(source.uid, source, initial_depth=result.initial_depth)
        if (
            not result.fallback
            and coarse_pose_enabled(self.config)
            and last_bootstrap.depth is not None
        ):
            self.prev_icp_depth = (
                torch.from_numpy(last_bootstrap.depth).to(self.device).float()
            )
            self.prev_icp_mask = (
                last_bootstrap_mask.squeeze(0).detach().to(self.device)
                if last_bootstrap_mask is not None
                else None
            )
        self.current_window.append(source.uid)
        for camera in self.bootstrap_frames[1:]:
            camera.clean()
            if result.fallback:
                self.cameras.pop(camera.uid, None)
        if result.fallback:
            next_frame_idx = source.uid + self.use_every_n_frames
        else:
            next_frame_idx = self.bootstrap_frames[-1].uid + self.use_every_n_frames
        self.bootstrap_frames = []
        self.bootstrap_masks = []
        return next_frame_idx

    def _deduplicate_promotion(self, promotion):
        source = self.cameras.get(promotion.source_id)
        if (
            source is None
            or self.gaussians is None
            or self.gaussians.get_xyz.numel() == 0
        ):
            return promotion.depth_map
        render_pkg = render(
            source, self.gaussians, self.pipeline_params, self.background
        )
        rendered_depth = render_pkg["depth"].detach().cpu().numpy().squeeze()
        opacity = render_pkg["opacity"].detach().cpu().numpy().squeeze()
        candidate_depth = promotion.depth_map.copy()
        valid = candidate_depth > 0.01
        cfg = self.config.get("DeferredCommit", {})
        threshold = np.maximum(
            float(cfg.get("depth_abs_m", 0.03)),
            float(cfg.get("depth_rel", 0.02)) * candidate_depth,
        )
        explained = valid & (opacity >= float(cfg.get("explained_opacity", 0.8)))
        explained &= np.abs(rendered_depth - candidate_depth) <= threshold
        candidate_depth[explained] = 0.0
        return candidate_depth

    def _dedup_promotion_candidates(self, promotion):
        """Flat-array analogue of ``_deduplicate_promotion``: drop promoted candidates
        the current map already explains (high opacity + depth agreement at the source
        view), returning the surviving ``(px, py, depth, color, lineage_ids)`` so the
        direct builder inserts them WITH their lineage. Preserves 1:1 alignment."""
        px = np.asarray(promotion.pixels_x, dtype=np.int64)
        py = np.asarray(promotion.pixels_y, dtype=np.int64)
        depth = np.asarray(promotion.depth, dtype=np.float32)
        color = np.asarray(promotion.color, dtype=np.float32)
        lineage = np.asarray(promotion.lineage_ids, dtype=np.int32)
        source = self.cameras.get(promotion.source_id)
        if (
            source is None
            or self.gaussians is None
            or self.gaussians.get_xyz.numel() == 0
            or px.size == 0
        ):
            return px, py, depth, color, lineage
        render_pkg = render(
            source, self.gaussians, self.pipeline_params, self.background
        )
        rendered_depth = render_pkg["depth"].detach().cpu().numpy().squeeze()
        opacity = render_pkg["opacity"].detach().cpu().numpy().squeeze()
        cfg = self.config.get("DeferredCommit", {})
        threshold = np.maximum(
            float(cfg.get("depth_abs_m", 0.03)),
            float(cfg.get("depth_rel", 0.02)) * depth,
        )
        explained = (opacity[py, px] >= float(cfg.get("explained_opacity", 0.8))) & (
            np.abs(rendered_depth[py, px] - depth) <= threshold
        )
        keep = ~explained
        return px[keep], py[keep], depth[keep], color[keep], lineage[keep]

    def _pose_w2c(self, cam):
        """4x4 world->camera SE(3) pose from a Camera's estimated (R, t)."""
        M = torch.eye(4, device=self.device, dtype=torch.float32)
        M[:3, :3] = cam.R.to(self.device, torch.float32)
        M[:3, 3] = cam.T.to(self.device, torch.float32)
        return M

    def _pose_w2c_gt(self, cam):
        """Same, from the Camera's GROUND-TRUTH (R, t) -- diagnostic paths only.

        Used ONLY by the default-off `ReliabilitySignal.ego_pose_oracle` probe below.
        Never call this on a path that feeds the tracker: it would leak GT into the pose.
        """
        M = torch.eye(4, device=self.device, dtype=torch.float32)
        M[:3, :3] = cam.R_gt.to(self.device, torch.float32)
        M[:3, 3] = cam.T_gt.to(self.device, torch.float32)
        return M

    def _compute_flow_threshold_mask(self, cur_frame_idx):
        """WP-B flow-mask: resolve the current frame's frozen flow, threshold magnitude."""
        try:
            scfg = get_semantic_mask_config(self.config)
            if self._flow_mask_index is None:
                self._flow_mask_index = frozen_flow_index(
                    os.path.join(
                        self.config["Dataset"]["dataset_path"],
                        scfg.get("flow_flow_subdir", "flow_raft"),
                    )
                )
            stem = os.path.splitext(
                os.path.basename(self.dataset.depth_paths[cur_frame_idx])
            )[0]
            mask, path = resolve_flow_mask(
                self._flow_mask_index,
                self.config["Dataset"]["dataset_path"],
                stem,
                flow_subdir=scfg.get("flow_flow_subdir", "flow_raft"),
                quantile=float(scfg.get("flow_quantile", 0.90)),
                abs_px=float(scfg.get("flow_abs_px", 2.0)),
                dilate_px=int(scfg.get("dilate_px", 7)),
                max_mask_ratio=float(scfg.get("max_mask_ratio", 0.95)),
            )
            if mask is None:
                return None
            return torch.from_numpy(mask)[None].to(self.device).bool()
        except Exception as exc:  # never break tracking on the baseline mask
            Log(f"flow-threshold mask failed frame {cur_frame_idx}: {exc}")
            return None

    def tracking(self, cur_frame_idx, viewpoint):
        prev = self.cameras[cur_frame_idx - self.use_every_n_frames]
        viewpoint.update_RT(prev.R, prev.T)

        # ── HARD GATE (exp23 incident) ── ReliabilitySignal.enabled=true but the
        # frozen-flow dir is empty/missing was the root cause of a silent-noop: the
        # module used to be skipped frame-by-frame with no warning and ATE still
        # converged. Fail fast on the FIRST frame instead of silently degrading to
        # K+R. `enabled && !monocular && depth_paths` is enough to decide — no need
        # to wait for gaussians/iteration, so the abort fires before any work is
        # burned. Located at the top of tracking() so every arm touches it.
        if (
            reliability_signal_enabled(self.config)
            and not self.monocular
            and getattr(self.dataset, "depth_paths", None) is not None
        ):
            if self._reliability_flow_index is None:
                self._reliability_flow_index = assert_reliability_flow_available(
                    self.config, self.config["Dataset"]["dataset_path"]
                )

        # P2d semantic (person) mask -- pose-independent, computed ONCE up front and
        semantic_mask = None
        semantic_soft = None
        if semantic_mask_enabled(self.config):
            if bool(get_semantic_mask_config(self.config).get("soft", False)):
                semantic_soft = compute_semantic_person_prob(
                    self.config, viewpoint.original_image
                )
            elif flow_threshold_mask_enabled(self.config):
                # WP-B: naive flow-threshold baseline — the ONLY difference from the
                # mask-free/MRCS backbone is the mask SOURCE (thresholded |f_obs|, no
                # learning). Consumed identically via mask_mapping/mask_insertion.
                semantic_mask = self._compute_flow_threshold_mask(cur_frame_idx)
            else:
                semantic_mask = compute_semantic_dynamic_mask(
                    self.config, viewpoint.original_image
                )
        # P1 mask QA: fix Mask R-CNN detection gaps (reuse last good mask) BEFORE any
        # consumer (coarse pose, tracking loss, insertion gate, dyn-coverage) sees it.
        if mask_qa_enabled(self.config) and not bool(
            get_semantic_mask_config(self.config).get("soft", False)
        ):
            semantic_mask = self._apply_mask_qa(cur_frame_idx, semantic_mask)
        # Dynamic-mask coverage (fraction flagged dynamic); stored per-frame for the
        # per-frame APE occlusion stratification + dynamic-crisis keyframing signal.
        dyn_cov = 0.0
        if semantic_mask is not None:
            dyn_cov = float(semantic_mask.float().mean().item())
        elif semantic_soft is not None:
            dyn_cov = float((semantic_soft > 0.5).float().mean().item())
        viewpoint.dyn_coverage = dyn_cov
        if self.dyn_kf_enabled:
            self.last_dyn_coverage = dyn_cov
        if self.kf_diag_enabled and semantic_mask is not None:
            viewpoint.person_mask = semantic_mask.detach()
        # Stash this frame's person mask for the semantic insertion gate (same frame,
        # add_new_keyframe) so it reuses this instead of re-running Mask R-CNN.
        self._last_semantic_mask_idx = cur_frame_idx
        self._last_semantic_mask = semantic_mask
        viewpoint.dynamic_mask = (
            semantic_mask.detach() if semantic_mask is not None else None
        )

        # P4a (Lever A): robust coarse pose init BEFORE Adam photometric refine.
        # Escapes local minima on dynamic frames; default-off, falls back to the
        # copy-prev-pose init above on any failure. masked_icp (SPEC-1) additionally
        # masks the person on BOTH the current source and previous target frames.
        if coarse_pose_enabled(self.config):
            pp_idx = cur_frame_idx - 2 * self.use_every_n_frames
            prevprev = self.cameras.get(pp_idx, None)
            curr_dyn_mask = (
                semantic_mask.squeeze(0) if semantic_mask is not None else None
            )
            with torch.no_grad():
                try:
                    coarse = compute_coarse_pose_init(
                        self.config,
                        viewpoint,
                        prev,
                        prevprev,
                        self.prev_icp_depth,
                        curr_dynamic_mask=curr_dyn_mask,
                        prev_dynamic_mask=self.prev_icp_mask,
                        frame_idx=cur_frame_idx,
                    )
                    if coarse is not None:
                        viewpoint.update_RT(coarse[0], coarse[1])
                except Exception as e:
                    Log(f"CoarsePoseInit frame {cur_frame_idx} failed: {e}")

        full_frame_proposal = None
        full_frame_target_pose = None
        if self.full_frame_pose_manager is not None:
            constant_velocity_pose = np.eye(4, dtype=np.float64)
            constant_velocity_pose[:3, :3] = viewpoint.R.detach().cpu().numpy()
            constant_velocity_pose[:3, 3] = viewpoint.T.detach().cpu().numpy()
            with torch.no_grad():
                seed_render = render(
                    viewpoint, self.gaussians, self.pipeline_params, self.background
                )
                seed_evidence = compute_static_evidence(
                    self.config,
                    viewpoint.depth,
                    seed_render["depth"],
                    seed_render["opacity"],
                    semantic_mask,
                )

            def map_precheck(pose_cw):
                original_rotation = viewpoint.R.detach().clone()
                original_translation = viewpoint.T.detach().clone()
                try:
                    viewpoint.update_RT(
                        torch.as_tensor(
                            pose_cw[:3, :3], device=self.device, dtype=torch.float32
                        ),
                        torch.as_tensor(
                            pose_cw[:3, 3], device=self.device, dtype=torch.float32
                        ),
                    )
                    with torch.no_grad():
                        package = render(
                            viewpoint,
                            self.gaussians,
                            self.pipeline_params,
                            self.background,
                        )
                        loss = get_loss_tracking(
                            self.config,
                            package["render"],
                            package["depth"],
                            package["opacity"],
                            viewpoint,
                            tracking_dynamic_mask=semantic_mask,
                        )
                    return float(loss.detach().item())
                finally:
                    viewpoint.update_RT(original_rotation, original_translation)

            full_frame_proposal = self.full_frame_pose_manager.propose(
                viewpoint,
                seed_evidence,
                constant_velocity_pose,
                map_precheck,
            )
            self.full_frame_pose_manager.record(cur_frame_idx, full_frame_proposal)
            if full_frame_proposal.accepted:
                full_frame_target_pose = full_frame_proposal.pose_cw.copy()
                viewpoint.update_RT(
                    torch.as_tensor(
                        full_frame_target_pose[:3, :3],
                        device=self.device,
                        dtype=torch.float32,
                    ),
                    torch.as_tensor(
                        full_frame_target_pose[:3, 3],
                        device=self.device,
                        dtype=torch.float32,
                    ),
                )

        opt_params = []
        opt_params.append(
            {
                "params": [viewpoint.cam_rot_delta],
                "lr": self.config["Training"]["lr"]["cam_rot_delta"],
                "name": "rot_{}".format(viewpoint.uid),
            }
        )
        opt_params.append(
            {
                "params": [viewpoint.cam_trans_delta],
                "lr": self.config["Training"]["lr"]["cam_trans_delta"],
                "name": "trans_{}".format(viewpoint.uid),
            }
        )
        # Per-frame exposure compensation (default-on = vanilla MonoGS). Probe: if this
        # freedom absorbs geometric error it can hurt pose precision -> Training.
        # optimize_exposure:false freezes exposure; Training.exposure_lr tunes its LR.
        if self.config["Training"].get("optimize_exposure", True):
            exp_lr = float(self.config["Training"].get("exposure_lr", 0.01))
            opt_params.append(
                {
                    "params": [viewpoint.exposure_a],
                    "lr": exp_lr,
                    "name": "exposure_a_{}".format(viewpoint.uid),
                }
            )
            opt_params.append(
                {
                    "params": [viewpoint.exposure_b],
                    "lr": exp_lr,
                    "name": "exposure_b_{}".format(viewpoint.uid),
                }
            )

        pose_optimizer = torch.optim.Adam(opt_params)
        flow_cfg = get_flow_tracking_config(self.config)
        flow_enabled = (
            bool(flow_cfg.get("enabled", False)) and self.prev_flow_rgb is not None
        )
        flow_warmup = int(flow_cfg.get("warmup_iters", 10))
        flow_mask = None
        flow_computed = False
        # (semantic person mask / dyn_coverage / kf-diag / stash computed up front,
        # before the coarse-pose block, so masked_icp can use it — see tracking() top.)
        # P3b temporal static_prob -> render per-pixel static weight (once/frame)
        static_soft = None
        if static_prob_enabled(self.config) and self.gaussians is not None:
            static_map = render_static_prob_map(
                self.config, self.gaussians, viewpoint, self.pipeline_params
            )
            if static_map is not None:
                static_soft = (1.0 - static_map).clamp(0.0, 1.0)  # -> dynamic_soft
        # Reliability signal s -> Cauchy tracking down-weight (method #8, doc-10 §1).
        # Frozen backward RAFT flow (f_obs) + online ego f_static -> e_flow; opacity-gated
        # geometric anomaly g -> s=(1-e_flow)(1-v*g) -> Cauchy w. Computed ONCE after a
        # warm-up (freeze; a live pose must not suppress its own contradictions), then fed
        # as a per-pixel tracking soft weight. NO new pose estimator (down-weight only),
        # no-harm (s->1 => w->1), and shared by ALL lifecycle arms (not the
        # allowed_config_diff) so it never confounds the make-or-break ablation.
        # Default-off, RGB-D only; skips (no-harm) if no frozen flow exists for the frame.
        reliability_soft = None
        reliability_frozen = False
        rel_cfg = get_reliability_signal_config(self.config)
        rel_warmup = int(rel_cfg.get("warmup_iters", 10))
        reliability_active = (
            reliability_signal_enabled(self.config)
            and not self.monocular
            and self.gaussians is not None
            and cur_frame_idx > 0
            and getattr(self.dataset, "depth_paths", None) is not None
        )
        rel_flow_path = None
        if reliability_active:
            if self._reliability_flow_index is None:
                self._reliability_flow_index = frozen_flow_index(
                    os.path.join(
                        self.config["Dataset"]["dataset_path"],
                        rel_cfg.get("flow_subdir", "flow_raft"),
                    )
                )
            stem = os.path.splitext(
                os.path.basename(self.dataset.depth_paths[cur_frame_idx])
            )[0]
            rel_flow_path = self._reliability_flow_index.get(stem)
            reliability_active = rel_flow_path is not None
        # Diagnostic A: GT-pose oracle -- force ground-truth pose + skip tracking
        # optimization, run mapping only. Isolates whether the ATE ceiling is the
        # tracking estimator (pose) or the mapping. Default-off.
        # Oracle.pose_file: same skip, but the pose comes from a FIXED external
        # trajectory (borrowed tracker) instead of GT -> mapping-only on that traj.
        oracle_gt = bool(self.config.get("Oracle", {}).get("gt_pose", False))
        oracle_ext = self._oracle_external_pose(cur_frame_idx)
        if oracle_ext is not None:
            viewpoint.update_RT(*oracle_ext)
        elif oracle_gt:
            viewpoint.update_RT(viewpoint.R_gt, viewpoint.T_gt)
        tracking_view_weight = None
        if reliable_tracking_enabled(self.config) and self.current_window:
            border_keyframe = self.current_window[0]
            if self.gaussians is not None:
                for candidate_id in self.current_window:
                    if (
                        self.gaussians.unique_kfIDs == int(candidate_id)
                    ).count_nonzero().item() >= 32:
                        border_keyframe = candidate_id
                        break
            tracking_view_weight = projected_border_weight(
                self.config,
                self.gaussians,
                viewpoint,
                border_keyframe,
            )
        for tracking_itr in range(self.tracking_itr_num):
            render_pkg = render(
                viewpoint, self.gaussians, self.pipeline_params, self.background
            )
            image, depth, opacity = (
                render_pkg["render"],
                render_pkg["depth"],
                render_pkg["opacity"],
            )
            if oracle_gt or oracle_ext is not None:
                # Oracle pose is already final. Do NOT break yet: fall through so the
                # reliability signal below can compute+freeze at itr 0 from the final
                # (injected) pose — deferred confirmation needs viewpoint.reliability_s
                # stashed exactly as in normal runs. The oracle break happens right
                # after that block, before any optimization.
                oracle_skip = True
            else:
                oracle_skip = False
            if flow_enabled and not flow_computed and tracking_itr >= flow_warmup:
                flow_computed = True
                cur_depth = torch.from_numpy(viewpoint.depth).to(image.device)
                flow_mask, _ = compute_flow_residual_mask(
                    self.config,
                    self.prev_flow_rgb,
                    viewpoint.original_image,
                    cur_depth,
                    self.prev_flow_wvt,
                    viewpoint.world_view_transform,
                    viewpoint.fx,
                    viewpoint.fy,
                    viewpoint.cx,
                    viewpoint.cy,
                )
            if semantic_mask is None:
                dyn_mask = flow_mask
            elif flow_mask is None:
                dyn_mask = semantic_mask
            else:
                dyn_mask = semantic_mask.to(flow_mask.device) | flow_mask
            # Reliability weight (method #8): compute ONCE at the warm-up iteration from
            # the detached warmed-up pose + render, then freeze (recomputing per-iter lets
            # a bad pose suppress its own contradictions). w is stored as a dynamic-soft
            # (=1-w) and composed with any semantic/static soft by max (either cue may
            # down-weight). No-harm: on a static frame w->1 => dynamic-soft->0.
            if (
                reliability_active
                and not reliability_frozen
                and (tracking_itr >= rel_warmup or oracle_skip)
            ):
                reliability_frozen = True
                with torch.no_grad():
                    # DIAGNOSTIC (default-off): `ego_pose_oracle` feeds the GT relative
                    # pose to the ego `rigid_flow` prediction ONLY -- tracking still
                    # optimizes its own pose normally, no GT leaks into the estimate.
                    # It isolates the closed-loop claim in eflow_pose_error_defect.md:
                    # e_flow inflates because f_static is predicted from the pose being
                    # optimized, so the tracker's own error is read as "dynamic" evidence.
                    # If f3_st_hf recovers under this oracle, the loop is causal and the
                    # oracle is the ceiling any real fix can reach. NEVER ship enabled.
                    if bool(rel_cfg.get("ego_pose_oracle", False)):
                        pose_prev = self._pose_w2c_gt(prev)
                        pose_cur = self._pose_w2c_gt(viewpoint)
                    else:
                        pose_prev = self._pose_w2c(prev)
                        pose_cur = self._pose_w2c(viewpoint)
                    R_ts, t_ts = relative_pose_target_from_source(pose_prev, pose_cur)
                    # T_{t-1<-t} for the ego f_static (backward, current-anchored)
                    obs_depth = torch.from_numpy(viewpoint.depth).to(self.device).float()
                    f_obs = torch.from_numpy(load_frozen_flow(rel_flow_path)).to(
                        self.device
                    )
                    s_map, w_map, fv_map, rstats = compute_reliability_tracking_weight(
                        obs_depth,
                        depth.squeeze(),
                        opacity.squeeze(),
                        f_obs,
                        R_ts,
                        t_ts,
                        viewpoint.fx,
                        viewpoint.fy,
                        viewpoint.cx,
                        viewpoint.cy,
                        geo_scale_floor=float(rel_cfg.get("geo_scale_floor", 0.0)),
                        flow_scale_floor=float(rel_cfg.get("flow_scale_floor", 0.0)),
                        mode=str(rel_cfg.get("mode", "both")),
                        # Ego-residual projection (default-off): remove the part of the
                        # flow residual that any camera-pose error could explain, so the
                        # tracker's own pose error is not read as dynamics.
                        # results/evidence/eflow_pose_error_defect.md
                        ego_projection=bool(rel_cfg.get("ego_projection", False)),
                        ego_kwargs=dict(rel_cfg.get("ego_projection_kwargs", {}) or {}),
                        # T2 adaptive-quota MAD isolation (default-off). `tau` is a
                        # majority statistic, so a large mover sets its own knee and
                        # cannot be down-weighted relative to itself; estimating tau
                        # on the static subgroup fixes that. The quota (not a fixed
                        # cue threshold) is what makes the zero-mass MAD collapse
                        # unreachable -- see cauchy_tracking_weight and
                        # results/evidence/m0_mad_exclusion/.
                        semantic_mask=semantic_mask,
                        mad_exclusion=bool(rel_cfg.get("mad_exclusion", False)),
                        mad_excl_e_thresh=float(
                            rel_cfg.get("mad_excl_e_thresh", 0.5)
                        ),
                        mad_excl_candidates=str(
                            rel_cfg.get("mad_excl_candidates", "cue")
                        ),
                        mad_excl_max_zero_frac=float(
                            rel_cfg.get("mad_excl_max_zero_frac", 0.45)
                        ),
                        mad_excl_min_keep_frac=float(
                            rel_cfg.get("mad_excl_min_keep_frac", 0.20)
                        ),
                        mad_excl_tau_floor=float(
                            rel_cfg.get("mad_excl_tau_floor", 0.0)
                        ),
                        # T2-scale counterfactual (default 1.0 = exact no-op): no
                        # exclusion at all, just tau *= c. Its only job is to let the
                        # campaign find out whether the quota's frame-adaptive
                        # sharpening beats a fixed one -- see cauchy_tracking_weight.
                        tau_scale=float(rel_cfg.get("tau_scale", 1.0)),
                    )
                    reliability_soft = (1.0 - w_map).clamp(0.0, 1.0)
                    # DIAGNOSTIC (default-off): force w == 1 in the TRACKING loss only.
                    # The signal is still computed, logged and stashed for the map path;
                    # ONLY the photometric down-weight is removed, and the loss stays on
                    # the same soft branch (dynamic_soft=0 => static_conf=1 everywhere),
                    # so the arm differs from the normal one in the WEIGHT VALUES alone.
                    #
                    # WHY: `cauchy_tracking_weight`'s tau = median(d)+1.4826*MAD(d) makes w
                    # strictly invariant to the absolute level of s -- mean_w is 0.57-0.66
                    # on static and dynamic sequences alike, i.e. ~38% of the photometric
                    # signal is discarded even on a fully static desk scene. This arm tests
                    # whether that discard is what breaks f3_st_hf at frame 371.
                    # results/evidence/exp26_static_collapse_rootcause.md
                    downweight_off = bool(
                        rel_cfg.get("tracking_downweight_off", False)
                    )
                    if downweight_off:
                        reliability_soft = torch.zeros_like(reliability_soft)
                    rstats["frame"] = int(cur_frame_idx)
                    rstats["tracking_itr"] = int(tracking_itr)
                    # Provenance: a run must be able to prove WHICH ego pose fed
                    # rigid_flow. The silent-no-op incident cost 4 sessions precisely
                    # because the arm label and the executed mechanism could disagree
                    # with nothing on disk to show it. This column never disappears.
                    rstats["ego_pose_oracle"] = int(
                        bool(rel_cfg.get("ego_pose_oracle", False))
                    )
                    # Provenance: `mean_w` above records what the signal COMPUTED; this
                    # column records whether it was actually APPLIED to tracking. Without
                    # it a w==1 arm is indistinguishable on disk from a normal one.
                    rstats["tracking_downweight_off"] = int(downweight_off)
                    # M2 (default-off, READ-ONLY): anchor survival + residual
                    # contrast. Placed here so it sees the SAME frozen snapshot the
                    # weight was built from (same render, same warmed-up pose) --
                    # a probe read one iteration later would describe a different
                    # pose than the one whose s_map it is reporting on.
                    if self.anchor_probe_enabled:
                        rstats.update(
                            self._anchor_stats(
                                viewpoint, s_map, image, depth, obs_depth
                            )
                        )
                    self.reliability_signal_rows.append(rstats)
                    # P2-DBAphoto: persist the EXACT online w_map + its warmup render
                    # context (render_depth, opacity, prev/cur W2C) so DBA-lite can
                    # re-run a reliability-weighted geometric oracle on the SAME weights
                    # the online tracker froze — NOT a post-hoc recompute from the final
                    # (co-adapted) PLY. Default-off (ReliabilitySignal.stash_dba_weights);
                    # only a DBA-photo campaign run turns it on. See
                    # results/evidence/consult_codex_dbaphoto_design.md.
                    if stash_dba_weights_enabled(self.config):
                        try:
                            save_dba_weight_snapshot(
                                os.path.join(self.save_dir, "dba_weight_snapshots"),
                                _dba_weight_stem(
                                    self.dataset.depth_paths[cur_frame_idx]
                                ),
                                w_map, s_map,
                                depth.squeeze(), opacity.squeeze(),
                                self._pose_w2c(viewpoint), self._pose_w2c(prev),
                                cur_frame_idx, int(tracking_itr),
                            )
                        except Exception as exc:  # never block tracking on stash IO
                            Log(f"DBA-weight stash failed frame {cur_frame_idx}: {exc}")
                    # R3: stash the FROZEN reliability signal s + its flow-consensus
                    # support map on the keyframe, so deferred/prune candidate CONFIRMATION
                    # (doc-10 §6) can read s_j(y) / flow_valid at each re-observed pixel.
                    # Confirmation is opt-in (DeferredCommit.reliability_confirm); the
                    # signal itself stays the same across arms (tracking down-weight), so
                    # this does not confound the make-or-break ablation. Frozen at the same
                    # warm-up snapshot as w (a live pose must not curate its own evidence).
                    if deferred_reliability_confirm_enabled(self.config):
                        viewpoint.reliability_s = (
                            s_map.detach().cpu().numpy().astype(np.float32)
                        )
                        viewpoint.reliability_flow_valid = (
                            fv_map.detach().cpu().numpy().astype(bool)
                        )
            if oracle_skip:
                break  # oracle pose final; reliability stashed; skip optimization
            base_soft = static_soft if static_soft is not None else semantic_soft
            if reliability_soft is not None:
                combined_soft = (
                    reliability_soft
                    if base_soft is None
                    else torch.maximum(base_soft, reliability_soft)
                )
            else:
                combined_soft = base_soft
            pose_optimizer.zero_grad()
            loss_tracking = get_loss_tracking(
                self.config,
                image,
                depth,
                opacity,
                viewpoint,
                tracking_dynamic_mask=dyn_mask,
                tracking_dynamic_soft=combined_soft,
                tracking_view_weight=tracking_view_weight,
            )
            prior = pose_prior_loss(
                viewpoint,
                full_frame_target_pose,
                full_frame_proposal,
                tracking_itr,
                self.config,
            )
            if prior is not None:
                loss_tracking = loss_tracking + prior
            loss_tracking.backward()

            with torch.no_grad():
                pose_optimizer.step()
                converged = update_pose(viewpoint)

            if tracking_itr % 10 == 0:
                self.q_main2vis.put(
                    gui_utils.GaussianPacket(
                        current_frame=viewpoint,
                        gtcolor=viewpoint.original_image,
                        gtdepth=viewpoint.depth
                        if not self.monocular
                        else np.zeros((viewpoint.image_height, viewpoint.image_width)),
                    )
                )
            if converged:
                break

        if bool(flow_cfg.get("enabled", False)):
            # cache before FrontEnd.cleanup() may clear original_image on non-keyframes
            self.prev_flow_rgb = viewpoint.original_image.detach().clone()
            self.prev_flow_wvt = viewpoint.world_view_transform.detach().clone()

        # P4a: cache this frame's gt depth as "prev" for the next frame's ICP init
        # (Camera.clean() drops .depth on non-keyframes).
        if coarse_pose_enabled(self.config) and viewpoint.depth is not None:
            self.prev_icp_depth = (
                torch.from_numpy(viewpoint.depth).to(self.device).float()
            )
            # cache this frame's person mask (matching prev_icp_depth) for the next
            # frame's masked_icp prev-target rejection; None -> next frame falls back.
            self.prev_icp_mask = (
                semantic_mask.squeeze(0).detach().to(self.device)
                if semantic_mask is not None
                else None
            )

        if static_prob_enabled(self.config) and self.gaussians is not None:
            update_static_prob_from_evidence(
                self.config,
                self.gaussians,
                viewpoint,
                compute_residual_evidence(self.config, image, viewpoint),
                render_pkg["visibility_filter"],
            )

        reliability_metrics = self.reliability_recorder.observe(
            image,
            depth,
            opacity,
            viewpoint,
            f"frame_{cur_frame_idx:06d}",
            use_exposure=True,
        )
        reliability_config = get_reliability_config(self.config)
        save_interval = int(reliability_config.get("save_interval", 20))
        if (
            reliability_metrics is not None
            and save_interval > 0
            and cur_frame_idx % save_interval == 0
        ):
            Log(
                "Reliability tracking frame "
                f"{cur_frame_idx}: mean="
                f"{reliability_metrics['mean_reliability']:.4f}, low_ratio="
                f"{reliability_metrics['low_reliability_ratio']:.4f}"
            )

        tri_metrics = self.tri_reliability_recorder.observe(
            image,
            depth,
            opacity,
            viewpoint,
            f"frame_{cur_frame_idx:06d}",
            gaussians=self.gaussians,
            visibility_filter=render_pkg["visibility_filter"],
            use_exposure=True,
        )
        tri_config = get_tri_reliability_config(self.config)
        tri_save_interval = int(tri_config.get("save_interval", 20))
        if (
            tri_metrics is not None
            and tri_save_interval > 0
            and cur_frame_idx % tri_save_interval == 0
        ):
            Log(
                "TriReliability tracking frame "
                f"{cur_frame_idx}: dynamic="
                f"{tri_metrics['mean_dynamic_evidence']:.4f}, unmapped="
                f"{tri_metrics['mean_unmapped_evidence']:.4f}, boundary="
                f"{tri_metrics['mean_boundary_evidence']:.4f}"
            )

        if self.static_evidence_recorder is not None:
            final_evidence = compute_static_evidence(
                self.config,
                viewpoint.depth,
                depth,
                opacity,
                semantic_mask,
            )
            self.static_evidence_recorder.record(cur_frame_idx, final_evidence)
            if self.full_frame_pose_manager is not None:
                self.full_frame_pose_manager.cache_frame(viewpoint, final_evidence)

        self.median_depth = get_median_depth(depth, opacity)
        return render_pkg

    def is_keyframe(
        self,
        cur_frame_idx,
        last_keyframe_idx,
        cur_frame_visibility_filter,
        occ_aware_visibility,
    ):
        kf_translation = self.config["Training"]["kf_translation"]
        kf_min_translation = self.config["Training"]["kf_min_translation"]
        kf_overlap = self.config["Training"]["kf_overlap"]

        curr_frame = self.cameras[cur_frame_idx]
        last_kf = self.cameras[last_keyframe_idx]
        pose_CW = getWorld2View2(curr_frame.R, curr_frame.T)
        last_kf_CW = getWorld2View2(last_kf.R, last_kf.T)
        last_kf_WC = torch.linalg.inv(last_kf_CW)
        dist = torch.norm((pose_CW @ last_kf_WC)[0:3, 3])
        dist_check = dist > kf_translation * self.median_depth
        dist_check2 = dist > kf_min_translation * self.median_depth

        union = torch.logical_or(
            cur_frame_visibility_filter, occ_aware_visibility[last_keyframe_idx]
        ).count_nonzero()
        intersection = torch.logical_and(
            cur_frame_visibility_filter, occ_aware_visibility[last_keyframe_idx]
        ).count_nonzero()
        point_ratio_2 = intersection / union
        return (point_ratio_2 < kf_overlap and dist_check2) or dist_check

    def add_to_window(
        self, cur_frame_idx, cur_frame_visibility_filter, occ_aware_visibility, window
    ):
        if visibility_window_enabled(self.config):
            return update_visibility_window(
                self.config,
                cur_frame_idx,
                cur_frame_visibility_filter,
                occ_aware_visibility,
                window,
                self.cameras,
            )
        N_dont_touch = 2
        window = [cur_frame_idx] + window
        # remove frames which has little overlap with the current frame
        curr_frame = self.cameras[cur_frame_idx]
        to_remove = []
        removed_frame = None
        for i in range(N_dont_touch, len(window)):
            kf_idx = window[i]
            # szymkiewicz–simpson coefficient
            intersection = torch.logical_and(
                cur_frame_visibility_filter, occ_aware_visibility[kf_idx]
            ).count_nonzero()
            denom = min(
                cur_frame_visibility_filter.count_nonzero(),
                occ_aware_visibility[kf_idx].count_nonzero(),
            )
            point_ratio_2 = intersection / denom
            cut_off = (
                self.config["Training"]["kf_cutoff"]
                if "kf_cutoff" in self.config["Training"]
                else 0.4
            )
            if not self.initialized:
                cut_off = 0.4
            if point_ratio_2 <= cut_off:
                to_remove.append(kf_idx)

        if to_remove:
            window.remove(to_remove[-1])
            removed_frame = to_remove[-1]
        kf_0_WC = torch.linalg.inv(getWorld2View2(curr_frame.R, curr_frame.T))

        if len(window) > self.config["Training"]["window_size"]:
            # we need to find the keyframe to remove...
            inv_dist = []
            for i in range(N_dont_touch, len(window)):
                inv_dists = []
                kf_i_idx = window[i]
                kf_i = self.cameras[kf_i_idx]
                kf_i_CW = getWorld2View2(kf_i.R, kf_i.T)
                for j in range(N_dont_touch, len(window)):
                    if i == j:
                        continue
                    kf_j_idx = window[j]
                    kf_j = self.cameras[kf_j_idx]
                    kf_j_WC = torch.linalg.inv(getWorld2View2(kf_j.R, kf_j.T))
                    T_CiCj = kf_i_CW @ kf_j_WC
                    inv_dists.append(1.0 / (torch.norm(T_CiCj[0:3, 3]) + 1e-6).item())
                T_CiC0 = kf_i_CW @ kf_0_WC
                k = torch.sqrt(torch.norm(T_CiC0[0:3, 3])).item()
                inv_dist.append(k * sum(inv_dists))

            idx = np.argmax(inv_dist)
            removed_frame = window[N_dont_touch + idx]
            window.remove(removed_frame)

        return window, removed_frame

    def request_keyframe(self, cur_frame_idx, viewpoint, current_window, depthmap):
        msg = ["keyframe", cur_frame_idx, viewpoint, current_window, depthmap]
        self.backend_queue.put(msg)
        self.requested_keyframe += 1

    def request_promotion(self, source_id, depthmap):
        self.backend_queue.put(["promote", source_id, depthmap])

    def request_candidate_insert(self, source_id, px, py, depth, color, lineage_ids):
        """Insert per-candidate Gaussians (prune insert-now / deferred promotion) with
        lineage, via the backend direct-from-arrays builder (bypasses the o3d path)."""
        cfg = self.config.get("DeferredCommit", {})
        self.backend_queue.put(
            [
                "insert_candidates",
                int(source_id),
                np.asarray(px, dtype=np.int32),
                np.asarray(py, dtype=np.int32),
                np.asarray(depth, dtype=np.float32),
                np.asarray(color, dtype=np.float32),
                np.asarray(lineage_ids, dtype=np.int32),
                float(cfg.get("promotion_min_scale_m", 0.001)),
                float(cfg.get("promotion_max_scale_m", 0.02)),
            ]
        )

    def request_prune(self, lineage_ids):
        """Delete rejected/expired candidate lineages from the map (prune arm)."""
        self.backend_queue.put(["prune_lineage", [int(i) for i in lineage_ids]])

    def reqeust_mapping(self, cur_frame_idx, viewpoint):
        msg = ["map", cur_frame_idx, viewpoint]
        self.backend_queue.put(msg)

    def request_init(self, cur_frame_idx, viewpoint, depth_map):
        msg = ["init", cur_frame_idx, viewpoint, depth_map]
        self.backend_queue.put(msg)
        self.requested_init = True

    def _get_backend_message(self):
        """Avoid blocking forever when the CUDA backend dies."""
        while True:
            try:
                return self.frontend_queue.get(timeout=0.5)
            except Empty:
                process = self.backend_process
                if process is not None and not process.is_alive():
                    raise RuntimeError(
                        "Backend process exited before sending a frontend message "
                        f"(exit code {process.exitcode})"
                    )

    def sync_backend(self, data):
        # Queue-delivered CUDA tensors use storage exported by the backend process.
        # Keeping that storage alive while stopping its producer triggers the known
        # CudaIPCTypes warning and, with the 535 driver, can segfault in libcuda
        # during backend teardown.  Adopt a process-local copy immediately and clear
        # the transport payload so the IPC references are released before shutdown.
        gaussians = clone_obj(data[1])
        occ_aware_visibility = clone_tensor_tree(data[2])
        keyframes = clone_tensor_tree(data[3])
        for idx in range(1, len(data)):
            data[idx] = None

        self.gaussians = gaussians
        self.occ_aware_visibility = occ_aware_visibility

        for kf_id, kf_R, kf_T in keyframes:
            self.cameras[kf_id].update_RT(kf_R, kf_T)

    def cleanup(self, cur_frame_idx):
        self.cameras[cur_frame_idx].clean()
        if cur_frame_idx % 10 == 0:
            torch.cuda.empty_cache()

    def _record_ref_kf_relative(self, viewpoint, ref_kf_id):
        """Record viewpoint's pose relative to its reference keyframe, using current
        online poses: T_rel = Tcw_frame @ inv(Tcw_refkf). At export a non-KF pose is
        recomposed as T_rel @ Tcw_refkf_optimized so it inherits the ref-KF's backend
        BA correction (ORB/DynaSLAM-style full-trajectory export). Survives clean()."""
        ref = self.cameras.get(ref_kf_id)
        if ref is None:
            return
        try:
            Tcw_f = torch.eye(4, device=viewpoint.R.device)
            Tcw_f[:3, :3] = viewpoint.R
            Tcw_f[:3, 3] = viewpoint.T
            Tcw_r = torch.eye(4, device=ref.R.device)
            Tcw_r[:3, :3] = ref.R
            Tcw_r[:3, 3] = ref.T
            T_rel = Tcw_f @ torch.inverse(Tcw_r)
            viewpoint.ref_kf_id = int(ref_kf_id)
            viewpoint.T_rel_to_refkf = T_rel.detach().cpu().numpy()
        except Exception:
            viewpoint.ref_kf_id = None
            viewpoint.T_rel_to_refkf = None

    def _dynamic_crisis_keyframe(self, cur_frame_idx, last_keyframe_idx):
        """Promote a non-keyframe to a keyframe when it risks accumulating drift, so it
        enters backend BA. All triggers config-gated and tightened under high dynamic
        occlusion (the map is least reliable there). Supports the three joint-plan
        configs from one helper:
          - legacy coverage: crisis_interval + person_mask_ratio_thresh
          - gap cap ("no pose stays > N frames from a KF" -- a local-BA-support
            invariant): gap_cap, tightened to gap_cap_tight when occluded
          - motion (same primitive as is_keyframe's kf_translation*median_depth, but as
            a hard cap independent of covisibility): motion_tau_depth / motion_tau_tight
        A pure fixed-interval control = gap_cap only, occ_tighten_thresh disabled."""
        cfg = self.dyn_kf_cfg
        # Identical-count control (off by default): cap total keyframes so adaptive-vs-
        # uniform can be compared at MATCHED count (mgap@N vs fixed@N) -- isolates
        # placement from the +count confound. Only caps crisis promotions; default
        # covisibility keyframing is untouched.
        kf_budget = cfg.get("kf_budget")
        if kf_budget is not None and len(self.kf_indices) >= int(kf_budget):
            return False
        gap = cur_frame_idx - last_keyframe_idx
        high_occ = self.last_dyn_coverage >= float(cfg.get("occ_tighten_thresh", 2.0))

        # Legacy coverage trigger (round-1 design).
        ci = cfg.get("crisis_interval")
        cov_th = cfg.get("person_mask_ratio_thresh")
        if ci is not None and cov_th is not None:
            if gap >= int(ci) and self.last_dyn_coverage >= float(cov_th):
                return True

        # Hard gap cap (systems invariant), tightened under occlusion.
        gap_cap = (
            cfg.get("gap_cap_tight")
            if (high_occ and cfg.get("gap_cap_tight"))
            else cfg.get("gap_cap")
        )
        if gap_cap and gap >= int(gap_cap):
            return True

        # Motion cap (distinct from is_keyframe: a hard bound ignoring covisibility).
        tau = (
            cfg.get("motion_tau_tight")
            if (high_occ and cfg.get("motion_tau_tight"))
            else cfg.get("motion_tau_depth")
        )
        if tau and gap >= 1 and getattr(self, "median_depth", None):
            dist = self._kf_translation_since(cur_frame_idx, last_keyframe_idx)
            if dist is not None and dist > float(tau) * self.median_depth:
                return True
        return False

    def _kf_translation_since(self, cur_frame_idx, last_keyframe_idx):
        """Camera translation between the current frame and the last keyframe (same
        primitive is_keyframe uses), in world units."""
        try:
            cur = self.cameras[cur_frame_idx]
            last_kf = self.cameras[last_keyframe_idx]
            pose_CW = getWorld2View2(cur.R, cur.T)
            last_kf_WC = torch.linalg.inv(getWorld2View2(last_kf.R, last_kf.T))
            return float(torch.norm((pose_CW @ last_kf_WC)[0:3, 3]).item())
        except Exception:
            return None

    def _project_centers_in_mask(self, xyz, cam, mask):
        """Project Gaussian centers into `cam` and return a (N,) bool of which land
        inside `cam`'s (1,H,W) person mask. No render hook -- center projection only
        (codex-specified minimum for the covisibility-inflation diagnostic)."""
        N = xyz.shape[0]
        if mask is None:
            return torch.zeros(N, dtype=torch.bool, device=xyz.device)
        ones = torch.ones(N, 1, device=xyz.device, dtype=xyz.dtype)
        Xh = torch.cat([xyz, ones], dim=1)
        Xc = Xh @ cam.world_view_transform.to(device=xyz.device, dtype=xyz.dtype)
        z = Xc[:, 2]
        eps = 1e-6
        u = cam.fx * Xc[:, 0] / z.clamp(min=eps) + cam.cx
        v = cam.fy * Xc[:, 1] / z.clamp(min=eps) + cam.cy
        m2 = mask.view(mask.shape[-2], mask.shape[-1]).bool()
        H, W = m2.shape
        valid = (z > eps) & (u >= 0) & (u < W) & (v >= 0) & (v < H)
        inmask = torch.zeros(N, dtype=torch.bool, device=xyz.device)
        ui = u.long().clamp(0, W - 1)
        vi = v.long().clamp(0, H - 1)
        inmask[valid] = m2[vi[valid], ui[valid]]
        return inmask

    def _anchor_stats(self, viewpoint, s_map, render_image, render_depth, obs_depth):
        """M2 (default-off, READ-ONLY): anchor survival rate + residual contrast.

        An ANCHOR is a pixel the reliability signal still trusts (``s >= theta``)
        inside the photometric support the tracker actually optimises
        (``rgb_boundary_threshold``, optionally intersected with the edge
        ``grad_mask`` -- only high-gradient pixels carry pose information).
        Design B's premise is that a collapse is preceded by that set thinning
        out or going bad, in which case a keyframe should be forced. This block
        only MEASURES; it returns a dict that goes to frames.csv and to
        ``self._anchor_last``. It touches no pose, no weight, no keyframe.

        ``anchor_ratio_*`` is the discriminating quantity, not ``anchor_frac_*``:
        the survival rate falls whenever the support shrinks for ANY reason
        (motion blur, exposure, a wall filling the view), whereas the ratio
        -- median residual inside the anchor set over the same median in its
        complement -- says whether the anchors that survived are still the GOOD
        pixels. A ratio drifting toward/above 1 means the signal is keeping the
        wrong pixels, which is the failure Design B would have to detect.

        Wrapped: a diagnostic must never be able to kill a tracking run. On
        failure it emits ``anchor_probe=0`` so a disk reader can tell a failed
        probe from a probe that was off (which emits no columns at all).
        """
        def _median_or_nan(t):
            return float(t.median()) if t.numel() else float("nan")

        out = {"anchor_probe": 1}
        try:
            with torch.no_grad():
                dev = s_map.device
                gt = viewpoint.original_image.to(dev)
                thr = float(self.config["Training"]["rgb_boundary_threshold"])
                support = gt.sum(dim=0) > thr
                if self.anchor_require_grad_mask:
                    gm = getattr(viewpoint, "grad_mask", None)
                    if gm is not None:
                        support = support & gm.squeeze().to(dev, torch.bool)
                s = s_map.detach().float()
                rgb_res = (render_image.detach() - gt).abs().mean(dim=0)
                dep_ren = render_depth.detach().squeeze().float()
                dep_obs = obs_depth.detach().squeeze().float()
                dep_ok = (
                    support
                    & (dep_obs > 0.01)
                    & torch.isfinite(dep_ren)
                    & torch.isfinite(dep_obs)
                )
                dep_res = (dep_ren - dep_obs).abs()

                n_sup = int(support.sum())
                out["anchor_support_frac"] = float(support.float().mean())
                out["anchor_support_n"] = n_sup
                for th in self.anchor_thresholds:
                    tag = f"s{int(round(th * 100)):02d}"
                    a = support & (s >= th)
                    bg = support & ~a
                    n_a = int(a.sum())
                    r_a = _median_or_nan(rgb_res[a])
                    r_bg = _median_or_nan(rgb_res[bg])
                    out[f"anchor_n_{tag}"] = n_a
                    out[f"anchor_frac_{tag}"] = (
                        n_a / n_sup if n_sup else float("nan")
                    )
                    out[f"anchor_rgb_med_{tag}"] = r_a
                    out[f"anchor_rgb_med_bg_{tag}"] = r_bg
                    out[f"anchor_dep_med_{tag}"] = _median_or_nan(dep_res[a & dep_ok])
                    out[f"anchor_ratio_{tag}"] = (
                        r_a / r_bg if (r_bg == r_bg and r_bg > 0.0) else float("nan")
                    )
            self._anchor_last = dict(out)
        except Exception as exc:  # never let a diagnostic kill tracking
            Log(f"anchor-probe failed at frame {int(viewpoint.uid)}: {exc}")
            out = {"anchor_probe": 0}
        return out

    def _keyframe_diag(
        self, cur_frame_idx, last_kf_idx, curr_visibility, create_kf, reason
    ):
        """Record the covisibility Jaccard decision variables + a projected person-mask
        decomposition. person_delta_ratio = point_ratio_2 - ratio_without_projected_person;
        >0 means projected person-region Gaussians inflate inter-frame overlap (the
        mask-induced keyframe-suppression hypothesis). Default-off (KeyframeDiag)."""
        try:
            last_vis = self.occ_aware_visibility.get(last_kf_idx)
            if last_vis is None:
                return
            cur = curr_visibility.bool()
            last = last_vis.bool()
            n = min(cur.shape[0], last.shape[0])
            cur, last = cur[:n], last[:n]
            inter = int((cur & last).sum().item())
            union = int((cur | last).sum().item())
            ratio = inter / max(union, 1)

            xyz = self.gaussians.get_xyz.detach()[:n]
            cur_cam = self.cameras[cur_frame_idx]
            last_cam = self.cameras[last_kf_idx]
            cur_p = self._project_centers_in_mask(
                xyz, cur_cam, getattr(cur_cam, "person_mask", None)
            )
            last_p = self._project_centers_in_mask(
                xyz, last_cam, getattr(last_cam, "person_mask", None)
            )
            person = cur_p | last_p
            cur_np, last_np = cur & (~person), last & (~person)
            union_np = int((cur_np | last_np).sum().item())
            ratio_np = int((cur_np & last_np).sum().item()) / max(union_np, 1)

            dist = self._kf_translation_since(cur_frame_idx, last_kf_idx) or 0.0
            md = getattr(self, "median_depth", None)
            md = float(md) if md is not None else 0.0
            kt = self.config["Training"]["kf_translation"]
            kmt = self.config["Training"]["kf_min_translation"]
            self.kf_diag_rows.append(
                {
                    "cur_idx": cur_frame_idx,
                    "last_kf_idx": last_kf_idx,
                    "intersection": inter,
                    "union": union,
                    "point_ratio_2": round(ratio, 5),
                    "curr_visible_count": int(cur.sum().item()),
                    "last_visible_count": int(last.sum().item()),
                    "num_gaussians": int(n),
                    "dist": round(float(dist), 5),
                    "dist_check": int(float(dist) > kt * md),
                    "dist_check2": int(float(dist) > kmt * md),
                    "create_kf": int(bool(create_kf)),
                    "trigger_reason": reason,
                    "person_coverage": round(
                        float(getattr(cur_cam, "dyn_coverage", 0.0) or 0.0), 5
                    ),
                    "curr_person_visible": int((cur & cur_p).sum().item()),
                    "last_person_visible": int((last & last_p).sum().item()),
                    "point_ratio_no_person": round(ratio_np, 5),
                    "person_delta_ratio": round(ratio - ratio_np, 5),
                }
            )
        except Exception as e:
            Log(f"kf_diag failed frame {cur_frame_idx}: {e}")

    def _dump_keyframe_diag(self):
        if not self.kf_diag_enabled or not self.kf_diag_rows or self.save_dir is None:
            return
        import csv
        import os

        path = os.path.join(self.save_dir, "keyframe_diag.csv")
        cols = list(self.kf_diag_rows[0].keys())
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(self.kf_diag_rows)
        kfs = sum(r["create_kf"] for r in self.kf_diag_rows)
        import numpy as _np

        pdr = _np.array([r["person_delta_ratio"] for r in self.kf_diag_rows])
        Log(
            f"keyframe_diag: {len(self.kf_diag_rows)} decisions, {kfs} KFs, "
            f"mean point_ratio_2={_np.mean([r['point_ratio_2'] for r in self.kf_diag_rows]):.4f}, "
            f"mean person_delta_ratio={pdr.mean():.4f}",
            tag="Eval",
        )

    def _flush_diagnostics(self):
        self.reliability_recorder.flush_summary()
        self.tri_reliability_recorder.flush_summary()
        write_reliable_tracking_summary(self.save_dir, self.cameras)
        write_semantic_timing_summary(self.save_dir, "frontend")
        if self.deferred_manager is not None:
            self.deferred_manager.flush()
        if self.static_evidence_recorder is not None:
            self.static_evidence_recorder.flush()
        if self.full_frame_pose_manager is not None:
            self.full_frame_pose_manager.flush()
        self._flush_reliability_signal()
        self._dump_keyframe_diag()

    def _flush_reliability_signal(self):
        """Write per-frame reliability s/w stats (method #8) for the no-harm audit."""
        if not self.save_dir or not self.reliability_signal_rows:
            return
        write_reliability_frames(
            os.path.join(self.save_dir, "reliability_signal"),
            self.reliability_signal_rows,
        )

    def _abort_if_ate_exceeded(self, ate_m, frame_idx):
        reason = ate_abort_reason(self.config, ate_m, frame_idx)
        if reason is None:
            return
        if self.save_dir is not None:
            import json
            import os

            with open(
                os.path.join(self.save_dir, "ate_abort.json"),
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    {
                        "status": "ATE_ABORT",
                        "frame": int(frame_idx),
                        "ate_cm": float(ate_m) * 100.0,
                        "threshold_cm": float(
                            self.config["Results"]["ate_abort_threshold_cm"]
                        ),
                    },
                    file,
                    indent=2,
                )
        self._flush_diagnostics()
        Log(reason, tag="Eval")
        raise AteAbort(reason)

    def final_pose_refinement(self):
        """Step 2 (offline, default-off): re-optimize each NON-keyframe pose against
        the frozen final (dynamic-clean via mask-both) map to remove the intra-keyframe
        -gap drift that MonoGS's online one-shot non-KF tracking leaves. Keyframes are
        already backend-BA-optimized and are left untouched (refine_keyframes:false).
        No GT is used; the map is frozen (only camera pose is optimized); per frame we
        fall back to the online pose unless refinement reduces the masked tracking loss.
        Runs in the main process after frontend.run(), before save_final_tracking_raw."""
        cfg = self.config.get("FinalPoseRefine", {})
        if not bool(cfg.get("enabled", False)) or self.gaussians is None:
            return
        n_iters = int(cfg.get("iters", 50))
        refine_keyframes = bool(cfg.get("refine_keyframes", False))
        max_trans_jump = float(cfg.get("max_trans_jump_m", 0.5))
        max_mask_ratio = float(cfg.get("max_mask_ratio", 0.9))
        kf_set = set(self.kf_indices)

        projection_matrix = (
            getProjectionMatrix2(
                znear=0.01,
                zfar=100.0,
                fx=self.dataset.fx,
                fy=self.dataset.fy,
                cx=self.dataset.cx,
                cy=self.dataset.cy,
                W=self.dataset.width,
                H=self.dataset.height,
            )
            .transpose(0, 1)
            .to(device=self.device)
        )

        # Freeze the map: no gaussian grads needed (pose-only), avoids wasted backward.
        gauss_params = [
            getattr(self.gaussians, a)
            for a in [
                "_xyz",
                "_features_dc",
                "_features_rest",
                "_scaling",
                "_rotation",
                "_opacity",
            ]
            if getattr(self.gaussians, a, None) is not None
        ]
        orig_rg = [p.requires_grad for p in gauss_params]
        for p in gauss_params:
            p.requires_grad_(False)

        n_refined, n_fallback = 0, 0
        try:
            for frame_id in sorted(self.cameras.keys()):
                if frame_id in kf_set and not refine_keyframes:
                    continue
                online_cam = self.cameras[frame_id]
                R0, T0 = online_cam.R.clone(), online_cam.T.clone()

                cam = Camera.init_from_dataset(
                    self.dataset, frame_id, projection_matrix
                )
                cam.update_RT(R0, T0)
                cam.compute_grad_mask(self.config)

                dyn_mask = None
                if semantic_mask_enabled(self.config):
                    dyn_mask = compute_semantic_dynamic_mask(
                        self.config, cam.original_image
                    )
                    if dyn_mask is not None:
                        if float(dyn_mask.float().mean().item()) > max_mask_ratio:
                            n_fallback += 1  # too little static support -> keep online
                            cam.clean()
                            continue

                pose_opt = torch.optim.Adam(
                    [
                        {
                            "params": [cam.cam_rot_delta],
                            "lr": self.config["Training"]["lr"]["cam_rot_delta"],
                        },
                        {
                            "params": [cam.cam_trans_delta],
                            "lr": self.config["Training"]["lr"]["cam_trans_delta"],
                        },
                    ]
                )
                init_loss = None
                last_loss = None
                for _ in range(n_iters):
                    render_pkg = render(
                        cam, self.gaussians, self.pipeline_params, self.background
                    )
                    image, depth, opacity = (
                        render_pkg["render"],
                        render_pkg["depth"],
                        render_pkg["opacity"],
                    )
                    pose_opt.zero_grad()
                    loss = get_loss_tracking(
                        self.config,
                        image,
                        depth,
                        opacity,
                        cam,
                        tracking_dynamic_mask=dyn_mask,
                    )
                    if init_loss is None:
                        init_loss = loss.item()
                    loss.backward()
                    with torch.no_grad():
                        pose_opt.step()
                        update_pose(cam)
                    last_loss = loss.item()

                trans_jump = torch.norm(cam.T - T0).item()
                accept = (
                    init_loss is not None
                    and last_loss is not None
                    and last_loss <= init_loss
                    and trans_jump <= max_trans_jump
                )
                if accept:
                    online_cam.update_RT(cam.R.detach(), cam.T.detach())
                    n_refined += 1
                else:
                    n_fallback += 1
                cam.clean()
        finally:
            for p, rg in zip(gauss_params, orig_rg):
                p.requires_grad_(rg)

        Log(
            f"Final pose refinement: refined {n_refined}, fell back {n_fallback} "
            f"(non-KF, {n_iters} iters, map frozen)",
            tag="Eval",
        )

    def run(self):
        cur_frame_idx = 0
        projection_matrix = getProjectionMatrix2(
            znear=0.01,
            zfar=100.0,
            fx=self.dataset.fx,
            fy=self.dataset.fy,
            cx=self.dataset.cx,
            cy=self.dataset.cy,
            W=self.dataset.width,
            H=self.dataset.height,
        ).transpose(0, 1)
        projection_matrix = projection_matrix.to(device=self.device)
        tic = torch.cuda.Event(enable_timing=True)
        toc = torch.cuda.Event(enable_timing=True)

        while True:
            if self.q_vis2main.empty():
                if self.pause:
                    continue
            else:
                data_vis2main = self.q_vis2main.get()
                self.pause = data_vis2main.flag_pause
                if self.pause:
                    self.backend_queue.put(["pause"])
                    continue
                else:
                    self.backend_queue.put(["unpause"])

            if self.frontend_queue.empty():
                tic.record()
                sequence_finished = cur_frame_idx >= len(self.dataset) or (
                    self.max_frames > 0 and cur_frame_idx >= self.max_frames
                )
                if sequence_finished:
                    if self.requested_init or self.requested_keyframe > 0:
                        time.sleep(0.01)
                        continue
                    if self.save_results:
                        eval_ate(
                            self.cameras,
                            self.kf_indices,
                            self.save_dir,
                            0,
                            final=True,
                            monocular=self.monocular,
                        )
                        save_gaussians(
                            self.gaussians, self.save_dir, "final", final=True
                        )
                    break

                if self.requested_init:
                    time.sleep(0.01)
                    continue

                if self.single_thread and self.requested_keyframe > 0:
                    time.sleep(0.01)
                    continue

                if not self.initialized and self.requested_keyframe > 0:
                    time.sleep(0.01)
                    continue

                viewpoint = Camera.init_from_dataset(
                    self.dataset, cur_frame_idx, projection_matrix
                )
                viewpoint.compute_grad_mask(self.config)

                self.cameras[cur_frame_idx] = viewpoint

                if self.reset:
                    if bootstrap_vo_enabled(self.config):
                        if not self.bootstrap_frames:
                            viewpoint.update_RT(viewpoint.R_gt, viewpoint.T_gt)
                        mask = self._bootstrap_mask(cur_frame_idx, viewpoint)
                        self.bootstrap_frames.append(viewpoint)
                        self.bootstrap_masks.append(mask)
                        cur_frame_idx += 1
                        required = int(
                            self.config.get("BootstrapVO", {}).get("max_frames", 3)
                        )
                        if len(self.bootstrap_frames) >= required:
                            cur_frame_idx = self._finish_bootstrap()
                        continue
                    self.initialize(cur_frame_idx, viewpoint)
                    self.current_window.append(cur_frame_idx)
                    cur_frame_idx += 1
                    continue

                self.initialized = self.initialized or (
                    len(self.current_window) == self.window_size
                )

                # Tracking
                tracking_start = time.perf_counter()
                render_pkg = self.tracking(cur_frame_idx, viewpoint)
                self.tracking_time_s += time.perf_counter() - tracking_start
                self.tracking_frames += 1

                if self.kf_propagate and len(self.current_window) > 0:
                    self._record_ref_kf_relative(viewpoint, self.current_window[0])

                current_window_dict = {}
                current_window_dict[self.current_window[0]] = self.current_window[1:]
                keyframes = [self.cameras[kf_idx] for kf_idx in self.current_window]

                self.q_main2vis.put(
                    gui_utils.GaussianPacket(
                        gaussians=clone_obj(self.gaussians),
                        current_frame=viewpoint,
                        keyframes=keyframes,
                        kf_window=current_window_dict,
                    )
                )

                if self.requested_keyframe > 0:
                    self.cleanup(cur_frame_idx)
                    cur_frame_idx += 1
                    continue

                last_keyframe_idx = self.current_window[0]
                check_time = (cur_frame_idx - last_keyframe_idx) >= self.kf_interval
                curr_visibility = (render_pkg["n_touched"] > 0).long()
                create_kf = self.is_keyframe(
                    cur_frame_idx,
                    last_keyframe_idx,
                    curr_visibility,
                    self.occ_aware_visibility,
                )
                if len(self.current_window) < self.window_size:
                    union = torch.logical_or(
                        curr_visibility, self.occ_aware_visibility[last_keyframe_idx]
                    ).count_nonzero()
                    intersection = torch.logical_and(
                        curr_visibility, self.occ_aware_visibility[last_keyframe_idx]
                    ).count_nonzero()
                    point_ratio = intersection / union
                    create_kf = (
                        check_time
                        and point_ratio < self.config["Training"]["kf_overlap"]
                    )
                if self.single_thread:
                    create_kf = check_time and create_kf
                kf_reason = "covis" if create_kf else "none"
                if self.dyn_kf_enabled and not create_kf:
                    create_kf = self._dynamic_crisis_keyframe(
                        cur_frame_idx, last_keyframe_idx
                    )
                    if create_kf:
                        kf_reason = "crisis"
                if self.kf_diag_enabled:
                    self._keyframe_diag(
                        cur_frame_idx,
                        last_keyframe_idx,
                        curr_visibility,
                        create_kf,
                        kf_reason,
                    )
                if create_kf:
                    self.current_window, removed = self.add_to_window(
                        cur_frame_idx,
                        curr_visibility,
                        self.occ_aware_visibility,
                        self.current_window,
                    )
                    if self.monocular and not self.initialized and removed is not None:
                        self.reset = True
                        Log(
                            "Keyframes lacks sufficient overlap to initialize the map, resetting."
                        )
                        continue
                    depth_map = self.add_new_keyframe(
                        cur_frame_idx,
                        image=render_pkg["render"],
                        depth=render_pkg["depth"],
                        opacity=render_pkg["opacity"],
                        init=False,
                    )
                    pending_candidate_inserts = []
                    if self.deferred_manager is not None:
                        decision = self.deferred_manager.process_keyframe(
                            viewpoint,
                            self.cameras,
                            depth_map,
                            render_pkg["depth"].detach().cpu().numpy(),
                            render_pkg["opacity"].detach().cpu().numpy(),
                            getattr(viewpoint, "dynamic_mask", None),
                        )
                        # deferred: commit HELD candidates now via the lineage-carrying
                        # direct builder, after dropping any the map already explains.
                        # These target PAST keyframes already registered in the backend,
                        # so they are safe to send before this keyframe's message.
                        for promotion in decision.promotions:
                            px, py, depth, color, lineage = (
                                self._dedup_promotion_candidates(promotion)
                            )
                            self.deferred_manager.record_commit_decision(
                                promotion, int(len(px))
                            )
                            if len(px):
                                self.request_candidate_insert(
                                    promotion.source_id, px, py, depth, color, lineage
                                )
                        # prune: delete the rejected/expired candidate lineages (past KFs).
                        if decision.prunes:
                            self.request_prune(decision.prunes)
                        # prune insert-now targets THIS keyframe; the backend only
                        # registers cur_frame_idx when it processes the "keyframe"
                        # message below, so defer these inserts until AFTER it or the
                        # backend skips them as a missing KF (candidates never enter the
                        # map and the later prune deletes nothing).
                        pending_candidate_inserts = decision.candidate_inserts
                        depth_map = decision.immediate_depth_map
                    self.request_keyframe(
                        cur_frame_idx, viewpoint, self.current_window, depth_map
                    )
                    for insert in pending_candidate_inserts:
                        self.request_candidate_insert(
                            insert.source_id,
                            insert.pixels_x,
                            insert.pixels_y,
                            insert.depth,
                            insert.color,
                            insert.lineage_ids,
                        )
                else:
                    self.cleanup(cur_frame_idx)
                cur_frame_idx += 1

                if (
                    self.save_results
                    and self.save_trj
                    and create_kf
                    and len(self.kf_indices) % self.save_trj_kf_intv == 0
                ):
                    Log("Evaluating ATE at frame: ", cur_frame_idx)
                    ate_m = eval_ate(
                        self.cameras,
                        self.kf_indices,
                        self.save_dir,
                        cur_frame_idx,
                        monocular=self.monocular,
                    )
                    self._abort_if_ate_exceeded(ate_m, cur_frame_idx)
                toc.record()
                torch.cuda.synchronize()
                if create_kf:
                    # throttle at 3fps when keyframe is added
                    duration = tic.elapsed_time(toc)
                    time.sleep(max(0.01, 1.0 / 3.0 - duration / 1000))
            else:
                data = self._get_backend_message()
                if data[0] == "sync_backend":
                    self.sync_backend(data)

                elif data[0] == "keyframe":
                    self.sync_backend(data)
                    self.requested_keyframe -= 1

                elif data[0] == "init":
                    self.sync_backend(data)
                    self.requested_init = False

                elif data[0] == "stop":
                    Log("Frontend Stopped.")
                    break
                elif data[0] == "backend_error":
                    raise RuntimeError(f"Backend worker failed: {data[1]}")
        self._flush_diagnostics()
