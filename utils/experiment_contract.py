import hashlib
import json
import re
import subprocess
from pathlib import Path

import yaml

from utils.config_utils import load_config


MODES = {"comparison", "diagnostic"}

ID_PATTERN = re.compile(r"^[A-Z0-9]+-P\d{2}-E[0-4]$")
STAGE_POLICIES = {
    "E0": {"seeds": [0], "dry_run": True, "fast": True, "max_frames": 0},
    "E1": {"seeds": [0], "dry_run": False, "fast": True, "max_frames": {15, 100}},
    # E2 gate semantics = full-trajectory seed 0 before any multi-seed. fast may be
    # False when the screening decision needs mapping metrics (e.g. a map-quality
    # hypothesis where ATE is no-harm only and the seed-0 gate must see band-PSNR/
    # geometry before committing E3/E4 budget). Tracking-only screenings keep True.
    "E2": {"seeds": [0], "dry_run": False, "fast": {True, False}, "max_frames": 0},
    "E3": {"seeds": [0, 1, 2], "dry_run": False, "fast": True, "max_frames": 0},
    "E4": {"seeds": [0, 1, 2], "dry_run": False, "fast": False, "max_frames": 0},
}

# Diagnostic lane: single-arm instrumentation of an existing method to locate a
# failure. It cannot express a control-vs-candidate delta, so it can never stand
# in for a method result. Stages mirror E0/E1/E2 (dry-run / smoke / full seed-0);
# there is deliberately no multi-seed diagnostic stage -- multi-seed evaluation is
# a method claim and belongs in the comparison lane.
DIAGNOSTIC_ID_PATTERN = re.compile(r"^[A-Z0-9]+-P\d{2}-D[0-2]$")
DIAGNOSTIC_STAGE_POLICIES = {
    "D0": {"seeds": [0], "dry_run": True, "fast": True, "max_frames": 0},
    "D1": {"seeds": [0], "dry_run": False, "fast": True, "max_frames": {15, 100}},
    "D2": {"seeds": [0], "dry_run": False, "fast": True, "max_frames": 0},
}
DRY_RUN_STAGES = {"E0", "D0"}
HARDWARE_REQUIRED_STAGES = {"E2", "E3", "E4", "D2"}
IGNORED_CONFIG_KEYS = {"inherit_from", "method_from"}


class ExperimentContractError(ValueError):
    pass


def load_experiment_manifest(path):
    path = Path(path)
    with path.open(encoding="utf-8") as file:
        manifest = yaml.safe_load(file)
    if not isinstance(manifest, dict):
        raise ExperimentContractError("experiment manifest must be a mapping")
    validate_experiment_manifest(manifest)
    return manifest


def _require_positive(run, name):
    value = run.get(name, 0)
    if not isinstance(value, (int, float)) or value <= 0:
        raise ExperimentContractError(f"run.{name} must be greater than zero")


def validate_experiment_manifest(manifest):
    if manifest.get("schema_version") != 1:
        raise ExperimentContractError("schema_version must be 1")
    if manifest.get("status") != "APPROVED":
        raise ExperimentContractError("manifest status must be APPROVED before running")

    mode = manifest.get("mode", "comparison")
    if mode not in MODES:
        raise ExperimentContractError(
            f"unsupported mode: {mode!r}; use 'comparison' or 'diagnostic'"
        )
    if mode == "comparison":
        stage_policies, id_pattern, id_hint = STAGE_POLICIES, ID_PATTERN, "R0-P01-E1"
    else:
        stage_policies = DIAGNOSTIC_STAGE_POLICIES
        id_pattern, id_hint = DIAGNOSTIC_ID_PATTERN, "R0-P01-D2"

    plan_id = str(manifest.get("plan_id", ""))
    experiment_id = str(manifest.get("experiment_id", ""))
    stage = str(manifest.get("stage", ""))
    if stage not in stage_policies:
        raise ExperimentContractError(f"unsupported stage for {mode} mode: {stage!r}")
    if not id_pattern.fullmatch(experiment_id):
        raise ExperimentContractError(f"invalid experiment_id: {experiment_id!r}")
    if not experiment_id.startswith(f"{plan_id}-") or not experiment_id.endswith(stage):
        raise ExperimentContractError(
            f"experiment_id must match plan_id and stage, for example {id_hint}"
        )
    if not str(manifest.get("hypothesis", "")).strip():
        raise ExperimentContractError("hypothesis must be non-empty")

    sequence_file = Path(str(manifest.get("sequence_file", "")))
    if not sequence_file.is_file():
        raise ExperimentContractError(f"sequence_file does not exist: {sequence_file}")

    comparison = manifest.get("comparison")
    if not isinstance(comparison, dict):
        raise ExperimentContractError("comparison must be a mapping")
    allowed = comparison.get("allowed_config_diff")
    if not isinstance(allowed, list):
        raise ExperimentContractError("comparison.allowed_config_diff must be a list")
    if mode == "comparison":
        if not comparison.get("control") or not comparison.get("candidate"):
            raise ExperimentContractError(
                "comparison requires control and candidate names"
            )
    else:
        if not comparison.get("control"):
            raise ExperimentContractError(
                "diagnostic mode requires comparison.control to name the instrumented arm"
            )
        if comparison.get("candidate"):
            raise ExperimentContractError(
                "diagnostic mode forbids a candidate; use comparison mode to compare arms"
            )
        if allowed:
            raise ExperimentContractError(
                "diagnostic mode forbids allowed_config_diff; there is no second arm"
            )

    run = manifest.get("run")
    if not isinstance(run, dict):
        raise ExperimentContractError("run must be a mapping")
    policy = stage_policies[stage]
    seeds = manifest.get("seeds")
    if seeds != policy["seeds"]:
        raise ExperimentContractError(
            f"{stage} requires seeds {policy['seeds']}, got {seeds!r}"
        )
    for field in ("dry_run", "fast", "max_frames"):
        expected = policy[field]
        actual = run.get(field)
        if isinstance(expected, set):
            if actual not in expected:
                raise ExperimentContractError(
                    f"{stage} requires run.{field} in {sorted(expected)}, got {actual!r}"
                )
        elif actual != expected:
            raise ExperimentContractError(
                f"{stage} requires run.{field}={expected!r}, got {actual!r}"
            )
    for field in ("timeout_seconds", "stall_timeout_seconds", "heartbeat_seconds"):
        _require_positive(run, field)
    if stage not in DRY_RUN_STAGES:
        _require_positive(run, "ate_abort_threshold_cm")

    gates = manifest.get("gates")
    if not isinstance(gates, dict) or not gates:
        raise ExperimentContractError("gates must be a non-empty mapping")
    if stage in HARDWARE_REQUIRED_STAGES and not str(manifest.get("hardware", "")).strip():
        raise ExperimentContractError(f"{stage} requires a hardware identifier")

    if mode == "comparison":
        validate_paired_configs(manifest, sequence_file)
    else:
        validate_diagnostic_sequences(manifest, sequence_file)


def _flatten_config(value, prefix=""):
    flattened = {}
    if isinstance(value, dict):
        for key, child in value.items():
            if key in IGNORED_CONFIG_KEYS:
                continue
            path = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_config(child, path))
    else:
        flattened[prefix] = value
    return flattened


def effective_config_diff(control_path, candidate_path):
    control = _flatten_config(load_config(str(control_path)))
    candidate = _flatten_config(load_config(str(candidate_path)))
    missing = object()
    return {
        key
        for key in control.keys() | candidate.keys()
        if control.get(key, missing) != candidate.get(key, missing)
    }


def validate_paired_configs(manifest, sequence_file):
    with Path(sequence_file).open(encoding="utf-8") as file:
        data = yaml.safe_load(file)
    sequences = data.get("sequences", []) if isinstance(data, dict) else []
    pairs = {}
    for sequence in sequences:
        pair = sequence.get("pair")
        arm = sequence.get("arm")
        if not pair or arm not in {"control", "candidate"}:
            raise ExperimentContractError(
                "every managed sequence requires pair and arm=control|candidate"
            )
        if arm in pairs.setdefault(pair, {}):
            raise ExperimentContractError(f"duplicate {arm} arm for pair {pair}")
        pairs[pair][arm] = sequence
    if not pairs:
        raise ExperimentContractError("sequence registry contains no comparison pairs")

    allowed = set(manifest["comparison"]["allowed_config_diff"]) | {"method"}
    for pair, arms in pairs.items():
        if set(arms) != {"control", "candidate"}:
            raise ExperimentContractError(f"pair {pair} must contain both arms")
        control = arms["control"]
        candidate = arms["candidate"]
        for arm, sequence in arms.items():
            configured_method = sequence.get("method")
            if not configured_method:
                configured_method = load_config(sequence["config"]).get("method")
            expected_method = manifest["comparison"][arm]
            if configured_method != expected_method:
                raise ExperimentContractError(
                    f"pair {pair} {arm} method must be {expected_method!r}, "
                    f"got {configured_method!r}"
                )
        for identity in ("dataset", "id"):
            if control.get(identity) != candidate.get(identity):
                raise ExperimentContractError(
                    f"pair {pair} has mismatched {identity}: "
                    f"{control.get(identity)!r} != {candidate.get(identity)!r}"
                )
        actual = effective_config_diff(control["config"], candidate["config"])
        undeclared = actual - allowed
        if undeclared:
            raise ExperimentContractError(
                f"pair {pair} has undeclared config differences: {sorted(undeclared)}"
            )


def validate_diagnostic_sequences(manifest, sequence_file):
    with Path(sequence_file).open(encoding="utf-8") as file:
        data = yaml.safe_load(file)
    sequences = data.get("sequences", []) if isinstance(data, dict) else []
    if not sequences:
        raise ExperimentContractError(
            "diagnostic sequence registry contains no sequences"
        )
    instrumented = manifest["comparison"]["control"]
    for sequence in sequences:
        if sequence.get("arm") != "diagnostic":
            raise ExperimentContractError(
                "every diagnostic sequence requires arm=diagnostic; a control|candidate "
                "registry belongs to the comparison lane"
            )
        for identity in ("dataset", "id", "config"):
            if not sequence.get(identity):
                raise ExperimentContractError(
                    f"diagnostic sequence requires {identity}"
                )
        configured_method = sequence.get("method")
        if not configured_method:
            configured_method = load_config(sequence["config"]).get("method")
        if configured_method != instrumented:
            raise ExperimentContractError(
                f"diagnostic sequence method must be {instrumented!r}, "
                f"got {configured_method!r}"
            )


def managed_results_root(manifest):
    return Path("results/runs") / manifest["plan_id"] / manifest["experiment_id"]


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def require_clean_git():
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ExperimentContractError("cannot verify Git worktree state") from exc
    if status:
        preview = "\n".join(status.splitlines()[:10])
        raise ExperimentContractError(
            "managed GPU runs require a clean Git worktree; commit the frozen code, "
            f"plan and manifest first:\n{preview}"
        )


def write_run_manifest(path, source_path, manifest, command, *, resume=False):
    require_clean_git()
    sequence_file = Path(manifest["sequence_file"])
    with sequence_file.open(encoding="utf-8") as file:
        sequences = yaml.safe_load(file)["sequences"]
    config_hashes = {
        sequence["config"]: file_sha256(sequence["config"]) for sequence in sequences
    }
    payload = {
        "contract": manifest,
        "contract_path": str(source_path),
        "contract_sha256": file_sha256(source_path),
        "code_commit": git_revision(),
        "config_sha256": config_hashes,
        "command": command,
    }
    path = Path(path)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        identity_fields = ("contract_sha256", "code_commit", "config_sha256")
        changed = [field for field in identity_fields if existing.get(field) != payload[field]]
        if not resume:
            raise ExperimentContractError(
                f"result root already contains {path.name}; use --resume only for "
                "the identical frozen experiment"
            )
        if changed:
            raise ExperimentContractError(
                f"resume rejected because frozen provenance changed: {changed}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
