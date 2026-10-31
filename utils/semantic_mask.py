"""P2d: light semantic dynamic mask. Two backends (torchvision, no new dep):
  - "deeplabv3"  DeepLabV3-MobileNetV3 (fast semantic seg, VOC person=15) -- weak on TUM.
  - "maskrcnn"   Mask R-CNN ResNet50-FPN (COCO instance seg, person=1) -- much more reliable.
Masks dynamic-class pixels out of tracking, reusing the `tracking_dynamic_mask`
plumbing. Pose-independent. YOLOv8n-seg avoided (`ultralytics` risks pinned numpy/torch).
"""

import json
import os
import time

import torch
import torch.nn.functional as F

_MODEL_CACHE = {}
_TIMING = {"calls": 0, "time_ms": 0.0, "hard_calls": 0, "soft_calls": 0}


def _timing_start(device):
    if torch.cuda.is_available() and torch.device(device).type == "cuda":
        torch.cuda.synchronize(device)
    return time.perf_counter()


def _record_timing(device, started_at, mode):
    if torch.cuda.is_available() and torch.device(device).type == "cuda":
        torch.cuda.synchronize(device)
    _TIMING["calls"] += 1
    _TIMING["time_ms"] += (time.perf_counter() - started_at) * 1000.0
    _TIMING[f"{mode}_calls"] += 1


def semantic_timing_snapshot():
    return dict(_TIMING)


def write_semantic_timing_summary(save_dir, scope):
    if not save_dir:
        return
    output_dir = os.path.join(save_dir, "semantic_timing")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "summary.json")
    summary = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                summary = json.load(file)
        except json.JSONDecodeError:
            summary = {}
    summary[scope] = semantic_timing_snapshot()
    scopes = [summary.get(name, {}) for name in ("frontend", "backend")]
    summary["total"] = {
        name: sum(float(item.get(name, 0)) for item in scopes)
        for name in ("calls", "time_ms", "hard_calls", "soft_calls")
    }
    summary["total"]["calls"] = int(summary["total"]["calls"])
    summary["total"]["hard_calls"] = int(summary["total"]["hard_calls"])
    summary["total"]["soft_calls"] = int(summary["total"]["soft_calls"])
    with open(path, "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2)


def semantic_efficiency_fields(save_dir):
    path = os.path.join(save_dir, "semantic_timing", "summary.json")
    if not os.path.exists(path):
        return {"semantic_time_ms": "N/A", "semantic_calls": "N/A"}
    with open(path, "r", encoding="utf-8") as file:
        total = json.load(file).get("total", {})
    return {
        "semantic_time_ms": round(float(total.get("time_ms", 0.0)), 4),
        "semantic_calls": int(total.get("calls", 0)),
    }


def get_semantic_mask_config(config):
    return config.get("SemanticMask", {})


def semantic_mask_enabled(config):
    return bool(get_semantic_mask_config(config).get("enabled", False))


def mask_mapping_enabled(config):
    sc = get_semantic_mask_config(config)
    return bool(sc.get("enabled", False)) and bool(sc.get("mask_mapping", False))


def get_or_compute_dynamic_mask(config, viewpoint):
    """Per-keyframe dynamic (person) mask, cached on the Camera. Pose-independent
    (depends only on the RGB image), so it is computed once and reused across the
    many mapping/BA iterations over the same keyframe. Returns (1,H,W) bool or None."""
    cached = getattr(viewpoint, "dynamic_mask", None)
    if cached is not None:
        return cached
    if not semantic_mask_enabled(config) or viewpoint.original_image is None:
        return None
    mask = compute_semantic_dynamic_mask(config, viewpoint.original_image)
    viewpoint.dynamic_mask = mask
    return mask


def _load_model(device, model_name):
    key = (model_name, str(device))
    if key not in _MODEL_CACHE:
        if model_name == "maskrcnn":
            from torchvision.models.detection import (
                maskrcnn_resnet50_fpn,
                MaskRCNN_ResNet50_FPN_Weights,
            )

            model = maskrcnn_resnet50_fpn(weights=MaskRCNN_ResNet50_FPN_Weights.DEFAULT)
        else:
            from torchvision.models.segmentation import (
                deeplabv3_mobilenet_v3_large,
                DeepLabV3_MobileNet_V3_Large_Weights,
            )

            model = deeplabv3_mobilenet_v3_large(
                weights=DeepLabV3_MobileNet_V3_Large_Weights.DEFAULT
            )
        model.eval().to(device)
        for p in model.parameters():
            p.requires_grad_(False)
        _MODEL_CACHE[key] = model
    return _MODEL_CACHE[key]


def compute_semantic_dynamic_mask(config, image):
    """image: (3,H,W) float [0,1] RGB. Returns (1,H,W) bool dynamic mask, or None."""
    sc = get_semantic_mask_config(config)
    model_name = sc.get("model", "deeplabv3")
    dilate_px = int(sc.get("dilate_px", 5))
    max_ratio = float(sc.get("max_mask_ratio", 0.95))
    dev = sc.get("device", None)
    timing_device = torch.device(dev) if dev else image.device
    started_at = _timing_start(timing_device)

    with torch.no_grad():
        img = image.detach()
        device = torch.device(dev) if dev else img.device
        model = _load_model(device, model_name)
        x_img = img.to(device)
        H, W = x_img.shape[-2], x_img.shape[-1]

        if model_name == "maskrcnn":
            classes = sc.get("dynamic_classes", [1])  # COCO person=1
            conf = float(sc.get("conf_threshold", 0.5))
            mask_thr = float(sc.get("mask_threshold", 0.5))
            out = model([x_img])[0]
            dyn = torch.zeros((H, W), dtype=torch.bool, device=device)
            masks = out.get("masks")
            if masks is not None and masks.numel() > 0:
                labels, scores = out["labels"], out["scores"]
                for i in range(labels.shape[0]):
                    if int(labels[i]) in classes and float(scores[i]) >= conf:
                        dyn = dyn | (masks[i, 0] >= mask_thr)
        else:
            classes = sc.get("dynamic_classes", [15])  # VOC person=15
            mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(3, 1, 1)
            std = torch.tensor([0.229, 0.224, 0.225], device=device).view(3, 1, 1)
            out = model(((x_img - mean) / std).unsqueeze(0))["out"]
            pred = out.argmax(dim=1)[0]
            dyn = torch.zeros_like(pred, dtype=torch.bool)
            for c in classes:
                dyn = dyn | (pred == int(c))

        if dilate_px > 0:
            k = 2 * dilate_px + 1
            dyn = (
                F.max_pool2d(
                    dyn.float().view(1, 1, H, W),
                    kernel_size=k,
                    stride=1,
                    padding=dilate_px,
                ).view(H, W)
                > 0.5
            )
        result = None if dyn.float().mean().item() > max_ratio else dyn.view(1, H, W)
    _record_timing(timing_device, started_at, "hard")
    return result


def compute_semantic_person_prob(config, image):
    """P3a soft path: return a SOFT (1,H,W) float [0,1] person(dynamic-class)
    probability map (NOT thresholded) for soft down-weighting. Uses deeplabv3
    softmax (light + gives calibrated per-pixel prob); maskrcnn soft not needed
    since coverage ~= deeplabv3."""
    sc = get_semantic_mask_config(config)
    classes = sc.get("dynamic_classes", [15])
    dev = sc.get("device", None)
    timing_device = torch.device(dev) if dev else image.device
    started_at = _timing_start(timing_device)
    with torch.no_grad():
        img = image.detach()
        device = torch.device(dev) if dev else img.device
        model = _load_model(device, "deeplabv3")
        mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225], device=device).view(3, 1, 1)
        out = model(((img.to(device) - mean) / std).unsqueeze(0))["out"]
        prob = torch.softmax(out, dim=1)[0]  # (21,H,W)
        person = prob[int(classes[0])]
        for c in classes[1:]:
            person = torch.maximum(person, prob[int(c)])
        result = person.unsqueeze(0)  # (1,H,W) soft [0,1]
    _record_timing(timing_device, started_at, "soft")
    return result


def flow_threshold_mask_enabled(config):
    """WP-B: SemanticMask.source == 'flow_threshold' (learned-free, thresholded flow mask).
    Default OFF — WP-A mask-on still uses 'maskrcnn'; mask-off keeps enabled:false."""
    return (
        semantic_mask_enabled(config)
        and get_semantic_mask_config(config).get("source", "maskrcnn") == "flow_threshold"
    )
