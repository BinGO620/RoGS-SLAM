from dataclasses import dataclass
import csv
import json
import os

import torch


PROTOCOL_VERSION = "static-evidence-v1"


def static_evidence_enabled(config):
    return bool(config.get("StaticEvidence", {}).get("enabled", False))


@dataclass
class StaticEvidence:
    reliable_static: torch.Tensor
    semantic_dynamic: torch.Tensor
    foreground_conflict: torch.Tensor
    background_reveal: torch.Tensor
    unknown: torch.Tensor
    static_support_ratio: float
    conflict_ratio: float
    protocol_version: str = PROTOCOL_VERSION
    valid_pixels: int = 0
    zero_support: bool = False


class StaticEvidenceRecorder:
    def __init__(self, save_dir=None):
        self.save_dir = save_dir
        self.rows = []

    def record(self, frame_id, evidence):
        self.rows.append(
            {
                "frame_id": int(frame_id),
                "protocol_version": evidence.protocol_version,
                "valid_pixels": int(evidence.valid_pixels),
                "reliable_static": int(evidence.reliable_static.count_nonzero().item()),
                "semantic_dynamic": int(
                    evidence.semantic_dynamic.count_nonzero().item()
                ),
                "foreground_conflict": int(
                    evidence.foreground_conflict.count_nonzero().item()
                ),
                "background_reveal": int(
                    evidence.background_reveal.count_nonzero().item()
                ),
                "unknown": int(evidence.unknown.count_nonzero().item()),
                "static_support_ratio": float(evidence.static_support_ratio),
                "conflict_ratio": float(evidence.conflict_ratio),
                "zero_support": bool(evidence.zero_support),
            }
        )

    def flush(self):
        if not self.save_dir:
            return
        directory = os.path.join(self.save_dir, "static_evidence")
        os.makedirs(directory, exist_ok=True)
        csv_path = os.path.join(directory, "frames.csv")
        fields = list(self.rows[0]) if self.rows else ["frame_id", "protocol_version"]
        with open(csv_path, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(self.rows)
        summary = {
            "protocol_version": PROTOCOL_VERSION,
            "frames": len(self.rows),
            "zero_support_frames": sum(
                row.get("zero_support", False) for row in self.rows
            ),
            "mean_static_support_ratio": sum(
                row.get("static_support_ratio", 0.0) for row in self.rows
            )
            / max(len(self.rows), 1),
            "mean_conflict_ratio": sum(
                row.get("conflict_ratio", 0.0) for row in self.rows
            )
            / max(len(self.rows), 1),
        }
        with open(
            os.path.join(directory, "summary.json"), "w", encoding="utf-8"
        ) as file:
            json.dump(summary, file, indent=2)


def _as_2d(value, device, dtype=None):
    tensor = torch.as_tensor(value, device=device, dtype=dtype)
    while tensor.ndim > 2 and tensor.shape[0] == 1:
        tensor = tensor.squeeze(0)
    if tensor.ndim != 2:
        raise ValueError(
            f"StaticEvidence expects HxW inputs, got {tuple(tensor.shape)}"
        )
    return tensor


def compute_static_evidence(
    config,
    observed_depth,
    rendered_depth,
    opacity,
    semantic_dynamic=None,
):
    """Classify causal RGB-D/map evidence without using ground truth.

    The five public masks are mutually exclusive over valid observed RGB-D pixels.
    Invalid observations are intentionally outside the accounting denominator.
    """

    if torch.is_tensor(rendered_depth):
        device = rendered_depth.device
    elif torch.is_tensor(observed_depth):
        device = observed_depth.device
    else:
        device = torch.device("cpu")
    observed = _as_2d(observed_depth, device, torch.float32)
    rendered = _as_2d(rendered_depth, device, torch.float32)
    alpha = _as_2d(opacity, device, torch.float32)
    if observed.shape != rendered.shape or observed.shape != alpha.shape:
        raise ValueError("StaticEvidence depth/opacity shape mismatch")
    if semantic_dynamic is None:
        dynamic = torch.zeros_like(observed, dtype=torch.bool)
    else:
        dynamic = _as_2d(semantic_dynamic, device).bool()
        if dynamic.shape != observed.shape:
            raise ValueError("StaticEvidence semantic-mask shape mismatch")

    cfg = config.get("StaticEvidence", {})
    valid = torch.isfinite(observed) & (observed > float(cfg.get("min_depth", 0.01)))
    rendered_valid = torch.isfinite(rendered) & (
        rendered > float(cfg.get("min_depth", 0.01))
    )
    semantic = valid & dynamic
    static_valid = valid & (~semantic)
    threshold = torch.maximum(
        torch.full_like(observed, float(cfg.get("depth_abs_m", 0.03))),
        float(cfg.get("depth_rel", 0.02)) * observed,
    )
    difference = observed - rendered
    mapped = rendered_valid & (
        alpha >= float(cfg.get("mapped_opacity_threshold", 0.35))
    )
    reliable = (
        static_valid
        & rendered_valid
        & (alpha >= float(cfg.get("reliable_opacity_threshold", 0.80)))
        & (difference.abs() <= threshold)
    )
    foreground = static_valid & mapped & (difference < -threshold)
    background = static_valid & mapped & (difference > threshold)
    assigned = semantic | reliable | foreground | background
    unknown = valid & (~assigned)

    valid_count = int(valid.count_nonzero().item())
    denominator = max(valid_count, 1)
    reliable_count = int(reliable.count_nonzero().item())
    conflict_count = int((foreground | background).count_nonzero().item())
    return StaticEvidence(
        reliable_static=reliable,
        semantic_dynamic=semantic,
        foreground_conflict=foreground,
        background_reveal=background,
        unknown=unknown,
        static_support_ratio=reliable_count / denominator,
        conflict_ratio=conflict_count / denominator,
        valid_pixels=valid_count,
        zero_support=valid_count == 0 or reliable_count == 0,
    )
