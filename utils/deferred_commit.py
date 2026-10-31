import csv
import json
import os
from dataclasses import dataclass, field

import numpy as np

from utils.causal_twin import UNTRACKED, LineageAllocator
from utils.static_evidence import compute_static_evidence


def deferred_commit_enabled(config):
    return bool(config.get("DeferredCommit", {}).get("enabled", False))


def deferred_reliability_confirm_enabled(config):
    """Whether candidate CONFIRMATION consumes the reliability signal ``s`` + ``flow_valid``.

    Opt-in (default False), matching the R0/R1/R2 default-off discipline: when off, the
    shared decision engine keeps its integer support/contradiction counts byte-for-byte
    (so every characterization/non-influence test and every prior deferred run reproduces
    exactly). When on -- AND the observing keyframe carries ``reliability_s`` /
    ``reliability_flow_valid`` maps (only produced when ``ReliabilitySignal.enabled``) --
    ``_update_batch`` switches to the doc-10 §6 weighted symmetric evidence ``C±`` with
    the missing-cue policy (a view with no valid frozen-flow consensus is gated OUT of
    both ``C⁺`` and ``C⁻``). This is the SHARED confirmation both prune and deferred use
    ("same C±", spec §make-or-break), so it never confounds the 3-arm ablation.
    """
    return bool(config.get("DeferredCommit", {}).get("reliability_confirm", False))


LIFECYCLE_MODES = ("immediate", "prune", "deferred")


def lifecycle_mode(config):
    """The Gaussian-lifecycle arm for the make-or-break ablation (doc-11).

    Canonical key ``Mapping.lifecycle_mode`` in ``{immediate, prune, deferred}``
    (the sole ``allowed_config_diff`` between arms). The three arms share the same
    candidate-decision logic and differ ONLY in the action on an uncertain pixel:
      * ``immediate`` -- insert it into the map at once (vanilla MonoGS control);
      * ``prune``     -- insert it at once WITH a lineage tag, then delete its whole
                         lineage on reject/expire (insert-then-remove control);
      * ``deferred``  -- hold it OUT of the map, promote only on confirmation (ours).
    Back-compat: with no ``Mapping.lifecycle_mode`` set, fall back to the legacy
    ``DeferredCommit.enabled`` toggle (True -> ``deferred``, else ``immediate``).
    """
    mode = config.get("Mapping", {}).get("lifecycle_mode")
    if mode is not None:
        mode = str(mode).lower()
        if mode not in LIFECYCLE_MODES:
            raise ValueError(
                f"Mapping.lifecycle_mode must be one of {LIFECYCLE_MODES}, got {mode!r}"
            )
        return mode
    return "deferred" if deferred_commit_enabled(config) else "immediate"



def _image_numpy(camera):
    image = camera.original_image.detach().cpu().permute(1, 2, 0).numpy()
    return np.clip(image, 0.0, 1.0).astype(np.float32)


def _mask_numpy(mask, shape):
    if mask is None:
        return np.zeros(shape, dtype=bool)
    array = mask.detach().cpu().numpy() if hasattr(mask, "detach") else np.asarray(mask)
    return np.squeeze(array).astype(bool)


def _pose_cw(camera):
    pose = np.eye(4, dtype=np.float64)
    pose[:3, :3] = camera.R.detach().cpu().numpy()
    pose[:3, 3] = camera.T.detach().cpu().numpy()
    return pose


@dataclass
class Promotion:
    source_id: int
    depth_map: np.ndarray
    candidate_count: int
    fast_count: int
    candidate_type: str = "mixed"
    # Per-candidate identity of the promoted set (method #9 action layer). ``depth_map``
    # is retained for the legacy o3d commit + dedup path; the flat arrays below feed the
    # deterministic direct-from-arrays builder so a promotion can be inserted WITH its
    # lineage ids (identity the o3d depth-map path irreversibly destroys).
    promoted_local_ids: np.ndarray = None
    pixels_x: np.ndarray = None
    pixels_y: np.ndarray = None
    depth: np.ndarray = None
    color: np.ndarray = None
    lineage_ids: np.ndarray = None


@dataclass
class CandidateInsert:
    """Prune-arm action: commit these uncertain candidates to the map NOW, each tagged
    with its lineage id, via the deterministic direct-from-arrays backend builder (NOT
    the o3d depth-map path, which cannot carry per-candidate identity). A later
    reject/expire deletes exactly these lineages -> a faithful insert-then-remove twin
    of ``deferred``.
    """

    source_id: int
    pixels_x: np.ndarray
    pixels_y: np.ndarray
    depth: np.ndarray
    color: np.ndarray
    lineage_ids: np.ndarray


@dataclass
class KeyframeDecision:
    immediate_depth_map: np.ndarray
    promotions: list
    candidate_inserts: list = field(default_factory=list)
    prunes: list = field(default_factory=list)


@dataclass
class PendingBatch:
    source_id: int
    height: int
    width: int
    x: np.ndarray
    y: np.ndarray
    depth: np.ndarray
    color: np.ndarray
    support: np.ndarray
    contradictions: np.ndarray
    pending: np.ndarray
    candidate_type: np.ndarray
    age: int = 0
    # Per-candidate lineage id (method #7/#9). Allocated by the manager at batch
    # creation; UNTRACKED for a batch built without ids (e.g. a decision-engine test).
    lineage_id: np.ndarray = None
    # Weighted symmetric confirmation evidence (doc-10 §6), populated ONLY in the
    # reliability-confirm path: C⁺ = Σ_j s_j(y)·h (reliably-static, depth-consistent
    # re-observations) and C⁻ = Σ_j s_j(y) (reliably-static views that see the surface
    # GONE). Parallel to the integer support/contradictions counters (which stay the
    # decision driver whenever the reliability maps are absent).
    c_plus: np.ndarray = None
    c_minus: np.ndarray = None

    def __post_init__(self):
        if self.lineage_id is None:
            self.lineage_id = np.full(len(self.x), UNTRACKED, dtype=np.int32)
        if self.c_plus is None:
            self.c_plus = np.zeros(len(self.x), dtype=np.float32)
        if self.c_minus is None:
            self.c_minus = np.zeros(len(self.x), dtype=np.float32)

    @property
    def pending_count(self):
        return int(self.pending.sum())


class DeferredCommitManager:
    def __init__(self, config, save_dir=None):
        self.config = config
        self.cfg = config.get("DeferredCommit", {})
        self.save_dir = save_dir
        # Lifecycle arm for the make-or-break ablation. The decision engine
        # (_update_batch) is identical across arms; only the ACTION on an uncertain
        # pixel differs (see lifecycle_mode docstring). Allocator + prune buffer are the
        # action-side state: fresh per-candidate lineage ids and the reject/expire/
        # capacity-drop ids the prune arm must delete from the map this keyframe.
        self.mode = lifecycle_mode(config)
        self._lineage = LineageAllocator()
        self._prune_buffer = []
        self.batches = []
        self.events = []
        self.summary = {
            "protocol_version": "uncertain-regions-v2",
            "lifecycle_mode": self.mode,
            "valid_static_pixels": 0,
            "immediate_insert": 0,
            "prune_immediate_insert": 0,
            "explained": 0,
            "semantic_dynamic": 0,
            "deferred_front_foreground": 0,
            "deferred_background_reveal": 0,
            "candidate_overflow": 0,
            "candidate_total": 0,
            "promoted": 0,
            "queued_for_commit": 0,
            "deduplicated_before_commit": 0,
            "fast_promoted": 0,
            "rejected": 0,
            "pruned": 0,
            "expired": 0,
            "dropped_capacity": 0,
            "pending_peak": 0,
            "occluded_observations": 0,
            "unknown_observations": 0,
        }

    def process_keyframe(
        self,
        viewpoint,
        cameras,
        insertion_depth,
        rendered_depth,
        opacity,
        dynamic_mask=None,
    ):
        promotions = self._update_existing(viewpoint, cameras)
        immediate, candidate_inserts = self._classify_new_keyframe(
            viewpoint,
            insertion_depth,
            rendered_depth,
            opacity,
            dynamic_mask,
        )
        self._finish_observation()
        return KeyframeDecision(
            immediate, promotions, candidate_inserts, self._drain_prunes()
        )

    def process_initial_keyframe(self, viewpoint, insertion_depth, dynamic_mask=None):
        observed = np.asarray(insertion_depth, dtype=np.float32).copy()
        dynamic = _mask_numpy(dynamic_mask, observed.shape)
        observed[dynamic | (~np.isfinite(observed)) | (observed <= 0.01)] = 0.0
        inserted = int((observed > 0.01).sum())
        self.summary["valid_static_pixels"] += inserted
        self.summary["immediate_insert"] += inserted
        self.summary["semantic_dynamic"] += int(dynamic.sum())
        self._event(viewpoint.uid, "initial_immediate_insert", inserted, 0)
        return observed

    def observe_keyframe(self, viewpoint, cameras, dynamic_mask=None):
        promotions = self._update_existing(viewpoint, cameras)
        self._add_batch(viewpoint, dynamic_mask)
        self._finish_observation()
        return promotions, self._drain_prunes()

    def _queue_prune(self, lineage_ids):
        """Record candidate lineages the prune arm must delete from the map.

        No-op unless the run is the ``prune`` arm. ``UNTRACKED`` ids (a batch built
        without allocated ids) are never queued -- they would match normal map growth.
        """
        if self.mode != "prune":
            return
        ids = [
            int(i) for i in np.asarray(lineage_ids).reshape(-1) if int(i) != UNTRACKED
        ]
        if ids:
            self._prune_buffer.extend(ids)
            self.summary["pruned"] += len(ids)

    def _drain_prunes(self):
        drained = self._prune_buffer
        self._prune_buffer = []
        return drained

    def _update_existing(self, viewpoint, cameras):
        promotions = []
        for batch in list(self.batches):
            source = cameras.get(batch.source_id)
            if source is None or source.depth is None or source.original_image is None:
                self._queue_prune(batch.lineage_id[np.nonzero(batch.pending)[0]])
                self._expire_batch(batch, "missing_source")
                continue
            pending_before = batch.pending.copy()
            promotion = self._update_batch(batch, source, viewpoint)
            promoted_local = (
                promotion.promoted_local_ids
                if promotion is not None and promotion.promoted_local_ids is not None
                else np.empty(0, dtype=np.int64)
            )
            if self.mode == "prune":
                # Promoted candidates are already in the map (inserted at classify) and
                # stay; only rejected/expired ones get their lineage deleted. A prune-arm
                # promotion is therefore a no-op -- do NOT re-insert it.
                unpending = np.nonzero(pending_before & ~batch.pending)[0]
                dropped = np.setdiff1d(unpending, promoted_local, assume_unique=False)
                self._queue_prune(batch.lineage_id[dropped])
            elif promotion is not None:
                # deferred: promotion == first insertion of the (held) candidate.
                promotions.append(promotion)
            if batch.pending_count == 0:
                self.batches.remove(batch)
        return promotions

    def _finish_observation(self):
        self._enforce_capacity()
        pending = sum(batch.pending_count for batch in self.batches)
        self.summary["pending_peak"] = max(self.summary["pending_peak"], pending)

    def _classify_new_keyframe(
        self,
        viewpoint,
        insertion_depth,
        rendered_depth,
        opacity,
        dynamic_mask,
    ):
        observed = np.asarray(insertion_depth, dtype=np.float32)
        rendered = np.asarray(rendered_depth, dtype=np.float32).squeeze()
        opacity = np.asarray(opacity, dtype=np.float32).squeeze()
        if observed.shape != rendered.shape or observed.shape != opacity.shape:
            raise ValueError("DeferredCommit depth/opacity shape mismatch")
        evidence_config = dict(self.config)
        evidence_config["StaticEvidence"] = {
            "depth_abs_m": float(self.cfg.get("depth_abs_m", 0.03)),
            "depth_rel": float(self.cfg.get("depth_rel", 0.02)),
            "reliable_opacity_threshold": float(self.cfg.get("explained_opacity", 0.8)),
            "mapped_opacity_threshold": float(
                self.cfg.get("unmapped_opacity_threshold", 0.35)
            ),
        }
        evidence = compute_static_evidence(
            evidence_config, observed, rendered, opacity, dynamic_mask
        )
        valid = np.isfinite(observed) & (observed > 0.01)
        dynamic = evidence.semantic_dynamic.cpu().numpy()
        static_valid = valid & (~dynamic)
        explained = evidence.reliable_static.cpu().numpy()
        front_foreground = evidence.foreground_conflict.cpu().numpy() & static_valid
        background_reveal = evidence.background_reveal.cpu().numpy() & static_valid
        uncertain = front_foreground | background_reveal
        certain_mask = static_valid & (~explained) & (~uncertain)

        immediate = np.zeros_like(observed)
        immediate[certain_mask] = observed[certain_mask]
        self.summary["valid_static_pixels"] += int(static_valid.sum())
        self.summary["immediate_insert"] += int(certain_mask.sum())
        self.summary["explained"] += int(explained.sum())
        self.summary["semantic_dynamic"] += int((valid & dynamic).sum())

        candidate_inserts = []
        if self.mode == "immediate":
            # Null arm (vanilla MonoGS): the uncertain pixels are inserted NOW, untracked
            # -- no candidate batch, no deferral, no lineage. Identical to inserting the
            # full static depth in one shot (the sole difference between arms is the
            # handling of exactly these uncertain pixels).
            immediate[uncertain] = observed[uncertain]
            self.summary["immediate_insert"] += int(uncertain.sum())
            return immediate, candidate_inserts

        # prune / deferred: hold the uncertain pixels as a tracked candidate batch.
        batch = self._add_typed_batch(
            viewpoint, front_foreground, background_reveal, observed
        )
        if self.mode == "prune" and batch is not None:
            # insert-then-remove control: commit the candidates to the map NOW, tagged
            # with lineage, so a later reject/expire can delete exactly them.
            candidate_inserts.append(
                CandidateInsert(
                    source_id=int(viewpoint.uid),
                    pixels_x=batch.x.copy(),
                    pixels_y=batch.y.copy(),
                    depth=batch.depth.copy(),
                    color=batch.color.copy(),
                    lineage_ids=batch.lineage_id.copy(),
                )
            )
            self.summary["prune_immediate_insert"] += int(len(batch.x))
        return immediate, candidate_inserts

    def record_commit_decision(self, promotion, queued_count):
        queued_count = int(queued_count)
        deduplicated = max(int(promotion.candidate_count) - queued_count, 0)
        self.summary["queued_for_commit"] += queued_count
        self.summary["deduplicated_before_commit"] += deduplicated
        if queued_count:
            self._event(promotion.source_id, "commit_queued", queued_count, 0)
        if deduplicated:
            self._event(promotion.source_id, "deduplicated", deduplicated, 0)

    def _add_batch(self, viewpoint, dynamic_mask):
        depth_map = np.asarray(viewpoint.depth, dtype=np.float32)
        dynamic = _mask_numpy(dynamic_mask, depth_map.shape)
        valid = np.isfinite(depth_map) & (depth_map > 0.01) & (~dynamic)
        self._add_typed_batch(viewpoint, valid, np.zeros_like(valid), depth_map)

    def _add_typed_batch(self, viewpoint, front_mask, background_mask, depth_map):
        candidate_mask = np.asarray(front_mask) | np.asarray(background_mask)
        y, x = np.nonzero(candidate_mask)
        types = np.where(front_mask[y, x], 0, 1).astype(np.int8)
        total = len(x)
        maximum = int(self.cfg.get("max_candidates_per_keyframe", 5000))
        if len(x) > maximum:
            selected = np.linspace(0, len(x) - 1, maximum, dtype=np.int64)
            x = x[selected]
            y = y[selected]
            types = types[selected]
            overflow = total - maximum
            self.summary["candidate_overflow"] += overflow
            self._event(viewpoint.uid, "candidate_overflow", overflow, 0)
        if len(x) == 0:
            return None
        color = _image_numpy(viewpoint)[y, x]
        depth = depth_map[y, x].copy()
        lineage = self._lineage.allocate(len(x)).numpy().astype(np.int32)
        batch = PendingBatch(
            source_id=int(viewpoint.uid),
            height=depth_map.shape[0],
            width=depth_map.shape[1],
            x=x.astype(np.int32),
            y=y.astype(np.int32),
            depth=depth,
            color=color,
            support=np.zeros(len(x), dtype=np.int16),
            contradictions=np.zeros(len(x), dtype=np.int16),
            pending=np.ones(len(x), dtype=bool),
            candidate_type=types,
            lineage_id=lineage,
        )
        self.batches.append(batch)
        self.summary["candidate_total"] += len(x)
        front_count = int((types == 0).sum())
        background_count = int((types == 1).sum())
        self.summary["deferred_front_foreground"] += front_count
        self.summary["deferred_background_reveal"] += background_count
        if front_count:
            self._event(viewpoint.uid, "created_front_foreground", front_count, 0)
        if background_count:
            self._event(viewpoint.uid, "created_background_reveal", background_count, 0)
        self._event(viewpoint.uid, "created", len(x), 0)
        return batch

    def _reliability_maps(self, target):
        """The observer keyframe's frozen reliability maps for weighted confirmation.

        Returns ``(s_map (H,W) float32, flow_valid (H,W) bool)`` when the run opts into
        reliability confirmation (``DeferredCommit.reliability_confirm``) AND the target
        carries both maps (attached by the frontend only when ``ReliabilitySignal`` is
        enabled), else ``(None, None)`` -> the caller keeps the integer count path. The
        maps are read-only observations of the target frame; they never touch the active
        map, so the non-influence invariant is untouched. A shape mismatch is treated as
        absent (defensive: never index a stale-shaped map).
        """
        if not deferred_reliability_confirm_enabled(self.config):
            return None, None
        s = getattr(target, "reliability_s", None)
        fv = getattr(target, "reliability_flow_valid", None)
        if s is None or fv is None:
            return None, None
        s = np.asarray(s, dtype=np.float32)
        fv = np.asarray(fv, dtype=bool)
        shape = (int(target.image_height), int(target.image_width))
        if s.shape != shape or fv.shape != shape:
            return None, None
        return s, fv

    def _update_batch(self, batch, source, target):
        ids = np.nonzero(batch.pending)[0]
        if len(ids) == 0:
            return None
        batch.age += 1
        s_map, fv_map = self._reliability_maps(target)
        use_reliability = s_map is not None

        z = batch.depth[ids]
        source_points = np.stack(
            [
                (batch.x[ids] - source.cx) * z / source.fx,
                (batch.y[ids] - source.cy) * z / source.fy,
                z,
                np.ones_like(z),
            ],
            axis=1,
        )
        world_points = (np.linalg.inv(_pose_cw(source)) @ source_points.T).T
        camera_points = (_pose_cw(target) @ world_points.T).T[:, :3]
        projected_z = camera_points[:, 2]
        safe_z = np.where(np.abs(projected_z) > 1e-8, projected_z, 1.0)
        u = np.rint(target.fx * camera_points[:, 0] / safe_z + target.cx).astype(int)
        v = np.rint(target.fy * camera_points[:, 1] / safe_z + target.cy).astype(int)
        inside = (
            np.isfinite(camera_points).all(axis=1)
            & (projected_z > 0.01)
            & (u >= 0)
            & (u < target.image_width)
            & (v >= 0)
            & (v < target.image_height)
        )
        inside_local = np.nonzero(inside)[0]
        if len(inside_local) > 0:
            global_ids = ids[inside_local]
            target_depth = np.asarray(target.depth, dtype=np.float32)
            observed = target_depth[v[inside_local], u[inside_local]]
            threshold = np.maximum(
                float(self.cfg.get("depth_abs_m", 0.03)),
                float(self.cfg.get("depth_rel", 0.02)) * projected_z[inside_local],
            )
            valid_depth = np.isfinite(observed) & (observed > 0.01)
            target_dynamic = _mask_numpy(
                getattr(target, "dynamic_mask", None), target_depth.shape
            )
            valid_depth &= ~target_dynamic[v[inside_local], u[inside_local]]
            delta = observed - projected_z[inside_local]

            target_rgb = _image_numpy(target)
            color_error = np.abs(
                target_rgb[v[inside_local], u[inside_local]] - batch.color[global_ids]
            ).mean(axis=1)
            supported = valid_depth & (np.abs(delta) <= threshold)
            supported &= color_error <= float(self.cfg.get("color_l1", 0.15))
            contradiction = valid_depth & (delta > threshold)
            occluded = valid_depth & (delta < -threshold)
            unknown = ~valid_depth
            batch.support[global_ids[supported]] += 1
            batch.contradictions[global_ids[contradiction]] += 1
            self.summary["occluded_observations"] += int(occluded.sum())
            self.summary["unknown_observations"] += int(unknown.sum())
            if use_reliability:
                s_view = s_map[v[inside_local], u[inside_local]]
                fv_view = fv_map[v[inside_local], u[inside_local]]
                # Missing-cue policy (doc-10 §4/§6): a view whose frozen-flow consensus is
                # unavailable at y is gated OUT of C± -- it moves NEITHER C⁺ nor C⁻ (a
                # missing observation is not read as static). Only reliably-observed views
                # accumulate evidence, so the deferred MAP decision becomes flow-driven.
                eligible = valid_depth & fv_view
                # Depth-consistency weight h in [0,1]: 1 at an exact depth match, ramping to
                # 0 at the depth gate. Reuses the established depth_abs/rel threshold as the
                # scale (a per-batch MAD here would couple candidates in a batch); doc-10 #16.
                safe_thr = np.maximum(threshold, 1e-6)
                h = np.clip(1.0 - np.abs(delta) / safe_thr, 0.0, 1.0)
                support_w = eligible & supported          # reliably static + depth+colour ok
                contra_w = eligible & (delta > threshold)  # reliably static, surface GONE
                batch.c_plus[global_ids[support_w]] += (s_view * h)[support_w]
                batch.c_minus[global_ids[contra_w]] += s_view[contra_w]

        confirming = float(self.cfg.get("confirming_views", 2))
        rejecting = float(self.cfg.get("reject_contradictions", 2))
        if use_reliability:
            # doc-10 §6: PROMOTE ⟺ C⁺ ≥ N_confirm ∧ C⁺ > C⁻ (weighted symmetric evidence).
            # N_confirm reuses confirming_views as a continuous threshold on Σ s·h: needs
            # ~2 fully-reliable exact-match views, more if the views are partially reliable.
            promote = (
                batch.pending & (batch.c_plus >= confirming) & (batch.c_plus > batch.c_minus)
            )
        else:
            promote = batch.pending & (batch.support >= confirming)
        fast = np.zeros_like(batch.pending)
        if bool(self.cfg.get("fast_promotion", False)) and len(inside_local) > 0:
            global_ids = ids[inside_local]
            observed = np.asarray(target.depth, dtype=np.float32)[
                v[inside_local], u[inside_local]
            ]
            depth_error = np.abs(observed - projected_z[inside_local])
            target_rgb = _image_numpy(target)
            color_error = np.abs(
                target_rgb[v[inside_local], u[inside_local]] - batch.color[global_ids]
            ).mean(axis=1)
            fast_local = (
                valid_depth
                & (depth_error <= float(self.cfg.get("fast_depth_abs_m", 0.01)))
                & (color_error <= float(self.cfg.get("fast_color_l1", 0.05)))
            )
            fast[global_ids[fast_local]] = batch.support[global_ids[fast_local]] >= 1
        promote |= fast
        if use_reliability:
            # doc-10 §6: REJECT ⟺ C⁻ ≥ N_confirm ∧ C⁻ > C⁺.
            reject = (
                batch.pending
                & (batch.c_minus >= rejecting)
                & (batch.c_minus > batch.c_plus)
                & (~promote)
            )
        else:
            reject = batch.pending & (batch.contradictions >= rejecting) & (~promote)

        promoted_ids = np.nonzero(promote)[0]
        rejected_count = int(reject.sum())
        batch.pending[promote | reject] = False
        self.summary["promoted"] += len(promoted_ids)
        self.summary["fast_promoted"] += int(fast[promoted_ids].sum())
        self.summary["rejected"] += rejected_count
        if len(promoted_ids):
            self._event(batch.source_id, "promoted", len(promoted_ids), batch.age)
        if rejected_count:
            self._event(batch.source_id, "rejected", rejected_count, batch.age)

        ttl = int(self.cfg.get("ttl_keyframes", 5))
        if batch.age >= ttl and batch.pending_count:
            expired = batch.pending_count
            batch.pending[:] = False
            self.summary["expired"] += expired
            self._event(batch.source_id, "expired", expired, batch.age)

        if len(promoted_ids) == 0:
            return None
        depth_map = np.zeros((batch.height, batch.width), dtype=np.float32)
        depth_map[batch.y[promoted_ids], batch.x[promoted_ids]] = batch.depth[
            promoted_ids
        ]
        return Promotion(
            batch.source_id,
            depth_map,
            len(promoted_ids),
            int(fast[promoted_ids].sum()),
            "mixed"
            if len(np.unique(batch.candidate_type[promoted_ids])) > 1
            else "front_foreground"
            if batch.candidate_type[promoted_ids][0] == 0
            else "background_reveal",
            promoted_local_ids=promoted_ids,
            pixels_x=batch.x[promoted_ids].copy(),
            pixels_y=batch.y[promoted_ids].copy(),
            depth=batch.depth[promoted_ids].copy(),
            color=batch.color[promoted_ids].copy(),
            lineage_ids=batch.lineage_id[promoted_ids].copy(),
        )

    def _enforce_capacity(self):
        maximum = int(self.cfg.get("max_pending_keyframes", 6))
        while len(self.batches) > maximum:
            batch = self.batches.pop(0)
            count = batch.pending_count
            self._queue_prune(batch.lineage_id[np.nonzero(batch.pending)[0]])
            self.summary["dropped_capacity"] += count
            self._event(batch.source_id, "capacity_drop", count, batch.age)

    def _expire_batch(self, batch, reason):
        count = batch.pending_count
        batch.pending[:] = False
        self.summary["expired"] += count
        self._event(batch.source_id, reason, count, batch.age)
        if batch in self.batches:
            self.batches.remove(batch)

    def _event(self, source_id, event, count, age):
        self.events.append(
            {
                "source_kf": int(source_id),
                "event": event,
                "count": int(count),
                "age_keyframes": int(age),
            }
        )

    def flush(self):
        if not self.save_dir:
            return
        os.makedirs(self.save_dir, exist_ok=True)
        summary = dict(self.summary)
        summary["pending_final"] = sum(batch.pending_count for batch in self.batches)
        with open(
            os.path.join(self.save_dir, "deferred_commit_summary.json"),
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(summary, file, indent=2)
        with open(
            os.path.join(self.save_dir, "deferred_commit_events.csv"),
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file, fieldnames=["source_kf", "event", "count", "age_keyframes"]
            )
            writer.writeheader()
            writer.writerows(self.events)
