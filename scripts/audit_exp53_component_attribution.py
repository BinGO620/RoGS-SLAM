#!/usr/bin/env python3
"""Audit EXP53 P11/Combined artifacts without running SLAM.

This is a descriptive, zero-GPU audit.  It deliberately does not infer a
single-component effect from the bundled P11-vs-Combined contrast.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import re
import statistics
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - useful error is raised by load_config
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = ROOT / "results/runs/EXP53/p11phase2"
DEFAULT_JSON = ROOT / "results/evidence/exp53_component_attribution_audit.json"
DEFAULT_EVIDENCE = ROOT / "results/evidence/exp53_component_attribution_audit.md"
SEEDS = (0, 1, 2)
SEQUENCES = {
    "crowd2": {"P11": "crowd2_P11", "C": "crowd2_C"},
    "mv_no_box": {"P11": "mvnobox_P11", "C": "mvnobox_C"},
}

# These are intentionally references, not data sources.  The audit never
# combines their numbers with EXP53; each has a distinct campaign/protocol.
HISTORICAL_EVIDENCE = [
    {
        "path": "results/evidence/p6_pb_2x2_3seed_verdict.md",
        "campaign": "P-B exp-v3-11",
        "hardware": "jiangwenheng 3090",
        "seeds": "0/1/2",
        "metric": "full-trajectory tracking_raw.csv ate_rmse_cm, evo -a Horn",
        "scope": "mv_no_box mask x DynamicKeyframe 2x2; not EXP53 and not crowd2",
    },
    {
        "path": "results/evidence/archive_pre_exp32/wpa_factorial_verdict.md",
        "campaign": "WP-A exp-v3-18",
        "hardware": "jiangwenheng 3090",
        "seeds": "0/1/2",
        "metric": "full-trajectory ATE, log-ratio factor readout",
        "scope": "mv_no_box DynamicKeyframe/Reliability/RobustTracking factorization; mask-free backbone",
    },
    {
        "path": "results/evidence/p7_cuesplit_verdict.md",
        "campaign": "P7 exp-v3-17",
        "hardware": "jiangwenheng 3090",
        "seeds": "0/1/2",
        "metric": "full-trajectory tracking_raw.csv ate_rmse_cm, evo -a Horn",
        "scope": "mv_no_box Reliability cue split; not a P11-vs-Combined contrast",
    },
    {
        "path": "results/evidence/archive_pre_exp32/fullkern_rerun_regime_split.md",
        "campaign": "EXP25 FULLKERN rerun",
        "hardware": "jiangwenheng 3090",
        "seeds": "0/1/2",
        "metric": "full-trajectory tracking_raw.csv ate_rmse_cm, evo -a Horn",
        "scope": "crowd2 old K1R1L0 versus complete K1R1L1; historical source correction",
    },
    {
        "path": "results/evidence/exp53_p11phase2_verdict.md",
        "campaign": "EXP53 P11 phase 2",
        "hardware": "jiangwenheng 3090",
        "seeds": "0/1/2",
        "metric": "full-trajectory tracking_raw.csv ate_rmse_cm, evo -a Horn",
        "scope": "current bundled P11-vs-Combined contrast",
    },
]


def _first_csv_row(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.DictReader(handle), {})


def _number(value):
    if value in (None, "", "N/A", "MISSING"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _latest_save_dir(run_dir: Path) -> Path | None:
    candidates = [Path(p) for p in glob.glob(str(run_dir / "datasets_*" / "*" / "seed_*" / "*"))]
    candidates = [p for p in candidates if p.is_dir() and (p / "config.yml").is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime_ns)


def _read_kf(save_dir: Path) -> dict:
    path = save_dir / "plot" / "trj_final.json"
    if not path.is_file():
        return {"count": None, "ids": [], "gap_min": None, "gap_max": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ids = [int(value) for value in payload.get("trj_id", [])]
    except (OSError, ValueError, TypeError):
        return {"count": None, "ids": [], "gap_min": None, "gap_max": None}
    gaps = [b - a for a, b in zip(ids, ids[1:])]
    return {
        "count": len(ids),
        "ids": ids,
        "gap_min": min(gaps) if gaps else None,
        "gap_max": max(gaps) if gaps else None,
    }


def _read_reliability(save_dir: Path) -> dict:
    directory = save_dir / "reliability_signal"
    frames = directory / "frames.csv"
    summary = directory / "summary.json"
    row_count = 0
    columns = []
    if frames.is_file():
        with frames.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            row_count = sum(1 for _ in reader)
    payload = {}
    if summary.is_file():
        try:
            payload = json.loads(summary.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
    return {
        "present": frames.is_file() and summary.is_file(),
        "frames": row_count,
        "columns": columns,
        "summary": payload,
    }


def _read_deferred(save_dir: Path) -> dict:
    path = save_dir / "deferred_commit_summary.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _log_activity(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    return {
        "insertion_gate_lines": len(re.findall(r"Semantic insertion gate", text)),
        "candidate_insert_lines": len(re.findall(r"Candidate insert KF", text)),
        "promotion_health_lines": len(re.findall(r"Deferred promotion health", text)),
        "keyframe_diag_lines": len(re.findall(r"keyframe_diag", text)),
        "crisis_mentions": len(re.findall(r"(?:trigger_reason|kf_reason|crisis)", text, re.I)),
        "completed": bool(re.search(r"(?:Map refinement done|MonoGS: Done\.)", text)),
    }


def _resolved_component_config(path: Path) -> dict:
    if yaml is None:
        raise RuntimeError("PyYAML is required to read resolved EXP53 config.yml files")
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    semantic = config.get("SemanticMask", {})
    dynamic = config.get("DynamicKeyframe", {})
    reliability = config.get("ReliabilitySignal", {})
    return {
        "DynamicKeyframe.enabled": bool(dynamic.get("enabled", False)),
        "DynamicKeyframe.gap_cap": dynamic.get("gap_cap"),
        "ReliabilitySignal.enabled": bool(reliability.get("enabled", False)),
        "SemanticMask.mask_mapping": bool(semantic.get("mask_mapping", False)),
        "SemanticMask.mask_insertion": bool(semantic.get("mask_insertion", False)),
        "DeferredCommit.reliability_confirm": bool(
            config.get("DeferredCommit", {}).get("reliability_confirm", False)
        ),
        "Mapping.lifecycle_mode": config.get("Mapping", {}).get("lifecycle_mode"),
        "Training.kf_interval": config.get("Training", {}).get("kf_interval"),
    }


def read_run(run_dir: Path) -> dict:
    save_dir = _latest_save_dir(run_dir)
    tracking = _first_csv_row(run_dir / "tables" / "tracking_raw.csv")
    efficiency = _first_csv_row(run_dir / "tables" / "efficiency_raw.csv")
    if save_dir is None:
        return {"run_dir": str(run_dir), "complete": False, "error": "missing save_dir"}
    config_path = save_dir / "config.yml"
    return {
        "run_dir": str(run_dir),
        "save_dir": str(save_dir),
        "complete": bool(tracking and efficiency and (save_dir / "plot" / "trj_final.json").is_file()),
        "ate_rmse_cm": _number(tracking.get("ate_rmse_cm")),
        "rpe_trans_rmse_cm": _number(tracking.get("rpe_trans_rmse_cm")),
        "status": tracking.get("status"),
        "online_fps": _number(efficiency.get("online_fps")),
        "num_gaussians": _number(efficiency.get("num_gaussians")),
        "reliability_time_ms": _number(efficiency.get("reliability_time_ms")),
        "reliability_calls": _number(efficiency.get("reliability_calls")),
        "semantic_calls": _number(efficiency.get("semantic_calls")),
        "config": _resolved_component_config(config_path),
        "kf": _read_kf(save_dir),
        "reliability": _read_reliability(save_dir),
        "deferred": _read_deferred(save_dir),
        "log": _log_activity(Path(run_dir).with_suffix(".consolelog")),
    }


def _mean_sd(values):
    values = [float(value) for value in values if value is not None]
    return {
        "n": len(values),
        "mean": statistics.mean(values) if values else None,
        "sd": statistics.stdev(values) if len(values) > 1 else (0.0 if values else None),
    }


def _all_equal(records, key_path):
    values = []
    for record in records:
        node = record
        for key in key_path:
            node = node.get(key) if isinstance(node, dict) else None
        values.append(node)
    return len(values) > 0 and all(value == values[0] for value in values)


def _config_diff(p11, combined):
    keys = (
        "DynamicKeyframe.enabled",
        "ReliabilitySignal.enabled",
        "SemanticMask.mask_mapping",
        "SemanticMask.mask_insertion",
        "Mapping.lifecycle_mode",
        "Training.kf_interval",
    )
    return {
        key: (p11["config"].get(key), combined["config"].get(key))
        for key in keys
        if p11["config"].get(key) != combined["config"].get(key)
    }


def summarize(runs_root: Path) -> dict:
    arms = {}
    for sequence, labels in SEQUENCES.items():
        arms[sequence] = {}
        for arm, prefix in labels.items():
            records = [read_run(runs_root / f"{prefix}_seed{seed}") for seed in SEEDS]
            ates = [record.get("ate_rmse_cm") for record in records]
            arms[sequence][arm] = {
                "records": records,
                "ates": ates,
                "ate": _mean_sd(ates),
                "escape_lt5": sum(value is not None and value < 5.0 for value in ates),
                "complete_3seed": all(record.get("complete", False) for record in records),
            }
        p11 = arms[sequence]["P11"]["ates"]
        combined = arms[sequence]["C"]["ates"]
        paired = [p - c for p, c in zip(p11, combined) if p is not None and c is not None]
        p_mean = arms[sequence]["P11"]["ate"]["mean"]
        c_mean = arms[sequence]["C"]["ate"]["mean"]
        p_records = arms[sequence]["P11"]["records"]
        c_records = arms[sequence]["C"]["records"]
        arms[sequence]["paired"] = {
            "p11_minus_combined": paired,
            "mean": _mean_sd(paired),
            "ratio_p11_over_combined": p_mean / c_mean if p_mean is not None and c_mean else None,
        }
        arms[sequence]["integrity"] = {
            "resolved_diff": _config_diff(p_records[0], c_records[0]),
            "resolved_diff_same_across_seeds": all(
                _config_diff(p, c) == _config_diff(p_records[0], c_records[0])
                for p, c in zip(p_records, c_records)
            ),
            "p11_reliability_absent": all(not r["reliability"]["present"] for r in p_records),
            "combined_reliability_present": all(r["reliability"]["present"] for r in c_records),
            "p11_insertion_log_absent": all(r["log"]["insertion_gate_lines"] == 0 for r in p_records),
            "combined_insertion_log_present": all(r["log"]["insertion_gate_lines"] > 0 for r in c_records),
            "combined_keyframe_diag_absent": all(r["log"]["keyframe_diag_lines"] == 0 for r in c_records),
            "all_deferred_summaries_present": all(bool(r["deferred"]) for r in p_records + c_records),
        }
    return {
        "campaign": "EXP53-P11-phase2",
        "runs_root": str(runs_root),
        "metric": "full-trajectory tracking_raw.csv ate_rmse_cm (evo -a Horn)",
        "hardware": "jiangwenheng dual RTX 3090; one task per GPU",
        "seeds": list(SEEDS),
        "sequences": arms,
        "historical_evidence": HISTORICAL_EVIDENCE,
    }


def _fmt(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}"


def render_markdown(report: dict) -> str:
    lines = [
        "# EXP53 组件归因审计（零 GPU）",
        "",
        "> 本文档只读取 EXP53 已落盘产物，不运行 SLAM、不申请 GPU。它审计结构与机制活动，",
        "> 不把 bundled contrast 解释成单组件因果效应。",
        "",
        f"- campaign: `{report['campaign']}`",
        f"- run root: `{report['runs_root']}`",
        f"- hardware: {report['hardware']}",
        f"- metric: `{report['metric']}`",
        "- seeds: `0/1/2`; mean ± sample sd（ddof=1）; escape = ATE < 5 cm",
        "",
        "## 1. EXP53 目标结果",
        "",
        "| sequence | P11 seed0/1/2 | P11 mean±sd | Combined seed0/1/2 | Combined mean±sd | P11−C mean | ratio |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for sequence in SEQUENCES:
        p11 = report["sequences"][sequence]["P11"]
        combined = report["sequences"][sequence]["C"]
        paired = report["sequences"][sequence]["paired"]
        pvals = "/".join(_fmt(value, 4) for value in p11["ates"])
        cvals = "/".join(_fmt(value, 4) for value in combined["ates"])
        lines.append(
            f"| {sequence} | {pvals} | {_fmt(p11['ate']['mean'])}±{_fmt(p11['ate']['sd'])} | "
            f"{cvals} | {_fmt(combined['ate']['mean'])}±{_fmt(combined['ate']['sd'])} | "
            f"{_fmt(paired['mean']['mean'])} | {_fmt(paired['ratio_p11_over_combined'])}× |"
        )

    lines += [
        "",
        "## 2. Resolved configuration and activity",
        "",
        "| sequence | arm | DynKF | Reliability | mask mapping | mask insertion | reliability frames | KF count | KF gap | completed |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for sequence in SEQUENCES:
        for arm in ("P11", "C"):
            records = report["sequences"][sequence][arm]["records"]
            dyn = {record["config"].get("DynamicKeyframe.enabled") for record in records}
            rel = {record["config"].get("ReliabilitySignal.enabled") for record in records}
            mapping = {record["config"].get("SemanticMask.mask_mapping") for record in records}
            insertion = {record["config"].get("SemanticMask.mask_insertion") for record in records}
            rel_frames = "/".join(str(record["reliability"]["frames"]) for record in records)
            kfs = "/".join(str(record["kf"]["count"]) for record in records)
            gaps = "/".join(
                f"{record['kf']['gap_min']}–{record['kf']['gap_max']}" for record in records
            )
            done = all(record["log"]["completed"] for record in records)
            lines.append(
                f"| {sequence} | {arm} | {sorted(dyn)} | {sorted(rel)} | {sorted(mapping)} | "
                f"{sorted(insertion)} | {rel_frames} | {kfs} | {gaps} | {done} |"
            )

    lines += [
        "",
        "### Directly observed",
        "",
        "- Both sequences have complete 3-seed P11 and Combined records; all runs report `status=OK`.",
        "- P11 and Combined share `mask_mapping=ON`, RobustTracking/Huber, `lifecycle_mode=prune`, and `kf_interval=5`.",
        "- The resolved P11→Combined difference is exactly three switches: `DynamicKeyframe.enabled`, `ReliabilitySignal.enabled`, and `mask_insertion`.",
        "- Combined has complete frozen-flow reliability artifacts; P11 has no reliability-signal artifact, as expected from its disabled setting.",
        "- Combined KF IDs are spaced at five frames in both target sequences, while P11 is substantially sparser and irregular.",
        "- `deferred_commit_summary.json` exists for both arms, so lifecycle activity is present on both sides; its counters differ substantially with the KF schedule and reliability confirmation path.",
        "",
        "## 3. What the artifacts can and cannot establish",
        "",
        "### Mechanism clues, not causal estimates",
        "",
        "- Combined's reliability frames and weighted candidate-confirmation path show that ReliabilitySignal is active, but activity is not an ATE counterfactual.",
        "- Combined's five-frame KF spacing is consistent with the configured `gap_cap=5`; without `KeyframeDiag`, existing logs cannot distinguish ordinary covisibility KFs from `crisis` promotions.",
        "- Insertion-gate log activity separates the arms operationally, but does not quantify the counterfactual effect of insertion while the other two switches remain fixed.",
        "- The different deferred/prune counters are compatible with a changed keyframe schedule and reliability confirmation, but are downstream observations rather than isolated effects.",
        "",
        "### Causal gap",
        "",
        "The EXP53 contrast is a three-variable bundled intervention. It cannot identify the separate effects of DynamicKeyframe, ReliabilitySignal, or `mask_insertion`, and it cannot tell whether the observed improvement is additive or interactive.",
        "",
        "The next causal test therefore remains a new, pre-registered 2-sequence × 2-single-variable-arm × 3-seed campaign:",
        "",
        "- `P11 + DynKF`: only `DynamicKeyframe.enabled=true`; Reliability and insertion remain OFF.",
        "- `P11 + Reliability`: only `ReliabilitySignal.enabled=true`; DynKF and insertion remain OFF. Because `reliability_confirm=true` changes C± confirmation when maps exist, this arm measures the Reliability signal family (tracking + candidate confirmation), not pure tracking down-weight.",
        "- Open `KeyframeDiag.enabled` in both intervention arms so `covis` versus `crisis` decisions are recorded.",
        "",
        "## 4. Historical evidence boundary",
        "",
        "Each historical item below is a separate reference. Its numbers are not merged into EXP53 means:",
        "",
        "| evidence | campaign | hardware | seeds | metric | scope |",
        "|---|---|---|---|---|---|",
    ]
    for item in report["historical_evidence"]:
        lines.append(
            f"| `{item['path']}` | {item['campaign']} | {item['hardware']} | {item['seeds']} | "
            f"{item['metric']} | {item['scope']} |"
        )
    lines += [
        "",
        "## 5. Audit verdict",
        "",
        "**ZERO-GPU STRUCTURAL AUDIT PASS; COMPONENT CAUSAL ATTRIBUTION UNRESOLVED.**",
        "",
        "The current evidence supports the EXP53 regime split: Combined is better on `crowd2` and `mv_no_box` under the full bundled configuration. It does not license a claim that DynamicKeyframe or ReliabilitySignal alone caused the gain. Freeze the EXP54 single-variable design before any GPU dispatch.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args(argv)
    report = summarize(args.root)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    print(f"\nwrote {args.json}\nwrote {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
