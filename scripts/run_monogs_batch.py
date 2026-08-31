import argparse
import csv
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_utils import load_config
from utils.experiment_contract import (
    ExperimentContractError,
    load_experiment_manifest,
    managed_results_root,
    write_run_manifest,
)
from utils.geometry_metrics import mapping_geometry_artifacts_complete


RAW_FILENAMES = ("tracking_raw.csv", "mapping_raw.csv", "efficiency_raw.csv")
DEFAULT_OUTPUT_DIR = "results/tables"
OOM_PATTERNS = (
    "cuda out of memory",
    "cuda error: out of memory",
    "cublas_status_alloc_failed",
    "cudnn_status_alloc_failed",
)
GPU_FAULT_PATTERNS = (
    "illegal memory access",
    "device-side assert",
    "nvidia-smi has failed",
    "xid (pci:",
)
ATE_ABORT_PATTERN = "ate_abort threshold exceeded"


RAW_FIELDNAMES = {
    "tracking_raw.csv": [
        "method",
        "dataset",
        "sequence",
        "seed",
        "run_id",
        "status",
        "notes",
        "ate_rmse_cm",
        "ate_error_std_cm",
        "rpe_trans_rmse_cm",
        "path_length_ratio",
        "success_by_threshold",
        "success_threshold_cm",
        "keyframe_ate_rmse_cm",
        "kf_propagated_ate_rmse_cm",
        "method_raw_mean_reliability",
        "method_raw_low_reliability_ratio",
        "method_raw_tri_dynamic_evidence",
        "method_raw_tri_unmapped_evidence",
        "method_raw_tri_boundary_evidence",
        "method_raw_tri_static_weight",
        "method_raw_gaussian_static_prob",
        "method_raw_gaussian_low_static_ratio",
        "source_dir",
    ],
    "mapping_raw.csv": [
        "method",
        "dataset",
        "sequence",
        "seed",
        "run_id",
        "status",
        "notes",
        "psnr",
        "ssim",
        "lpips",
        "depth_l1_cm",
        "accuracy_cm",
        "mask_type",
        "completion_cm",
        "completion_ratio",
        "method_raw_depth_l1_before_opt",
        "method_raw_depth_l1_after_opt",
        "method_raw_geometry_sample_points",
        "method_raw_geometry_gt_points",
        "method_raw_geometry_threshold_m",
        "method_raw_geometry_source_gt",
        "method_raw_geometry_protocol_version",
        "method_raw_geometry_representation",
        "method_raw_geometry_pose_source",
        "method_raw_geometry_protocol_eligible",
        "method_raw_geometry_mesh_path",
        "method_raw_geometry_mesh_vertices",
        "method_raw_geometry_mesh_faces",
        "method_raw_gaussian_center_accuracy_cm",
        "method_raw_gaussian_center_completion_cm",
        "method_raw_gaussian_center_completion_ratio",
        "method_raw_psnr_before_opt",
        "method_raw_ssim_before_opt",
        "method_raw_lpips_before_opt",
        "method_raw_psnr_after_opt",
        "method_raw_ssim_after_opt",
        "method_raw_lpips_after_opt",
        "method_raw_mean_reliability",
        "method_raw_low_reliability_ratio",
        "method_raw_tri_dynamic_evidence",
        "method_raw_tri_unmapped_evidence",
        "method_raw_tri_boundary_evidence",
        "method_raw_tri_static_weight",
        "method_raw_gaussian_static_prob",
        "method_raw_gaussian_low_static_ratio",
        "source_dir",
    ],
    "efficiency_raw.csv": [
        "method",
        "dataset",
        "sequence",
        "seed",
        "run_id",
        "status",
        "notes",
        "efficiency_protocol_version",
        "online_fps",
        "online_time_s",
        "online_peak_gpu_memory_gb",
        "online_num_gaussians",
        "refinement_wall_time_s",
        "refinement_backend_time_s",
        "refinement_peak_gpu_memory_gb",
        "refined_num_gaussians",
        "geometry_eval_time_s",
        "geometry_eval_peak_gpu_memory_gb",
        "fps_end_to_end",
        "tracking_fps",
        "mapping_fps",
        "tracking_time_ms",
        "mapping_time_ms",
        "gpu_memory_gb",
        "num_gaussians",
        "total_time_s",
        "num_frames",
        "tracking_time_s",
        "tracking_frames",
        "mapping_time_s",
        "mapping_iterations",
        "mapping_calls",
        "color_refinement_time_s",
        "alpha_lifecycle_steps",
        "alpha_lifecycle_skips",
        "alpha_exit_reset_total",
        "alpha_carve_total",
        "alpha_fill_inserted_total",
        "alpha_fill_steps",
        "alpha_fill_cleared_px_total",
        "alpha_fill_vacated_px_total",
        "reliability_time_ms",
        "reliability_calls",
        "tri_reliability_time_ms",
        "tri_reliability_calls",
        "reliable_tracking_time_ms",
        "reliable_tracking_calls",
        "reliable_tracking_depth_fallback_ratio",
        "semantic_time_ms",
        "semantic_calls",
        "source_dir",
    ],
}


REQUIRED_EVAL_ARTIFACTS = [
    "tracking_raw.csv",
    "mapping_raw.csv",
    "efficiency_raw.csv",
    "psnr/before_opt/final_result.json",
    "psnr/after_opt/final_result.json",
    "point_cloud/final/point_cloud.ply",
    "point_cloud/final_after_opt/point_cloud.ply",
    "mapping_geometry_metrics_v2.json",
    "geometry/tsdf_mesh.ply",
]


REQUIRED_EVAL_PRE_GEOMETRY_ARTIFACTS = [
    artifact
    for artifact in REQUIRED_EVAL_ARTIFACTS
    if artifact not in ("mapping_geometry_metrics_v2.json", "geometry/tsdf_mesh.ply")
]


REQUIRED_NORMAL_ARTIFACTS = [
    "tracking_raw.csv",
    "efficiency_raw.csv",
    "point_cloud/final/point_cloud.ply",
]


REQUIRED_FAST_ARTIFACTS = [
    "tracking_raw.csv",
    "efficiency_raw.csv",
]


def load_sequences(path, only):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    sequences = data["sequences"]
    if only:
        wanted = {item.strip() for item in only.split(",") if item.strip()}
        sequences = [seq for seq in sequences if seq["id"] in wanted]
    return sequences


def sanitize_experiment_name(name):
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    if not safe_name:
        raise ValueError(f"Invalid experiment name: {name!r}")
    return safe_name


def resolve_results_root(experiment_name="", results_root=""):
    if results_root:
        return results_root
    if experiment_name:
        return f"results/runs/{sanitize_experiment_name(experiment_name)}"
    return ""


def sequence_method(seq):
    if seq.get("method"):
        return seq["method"]
    config = Path(seq.get("config", ""))
    if config.exists():
        try:
            return load_config(str(config)).get("method", "MonoGS")
        except Exception:
            return "MonoGS"
    return "MonoGS"


def sequence_result_id(seq):
    config = Path(seq.get("config", ""))
    if config.exists():
        try:
            configured = load_config(str(config)).get("Dataset", {}).get("sequence")
            return str(configured) if configured else config.stem
        except Exception:
            pass
    return str(seq["id"])


def append_failure(raw_path, seq, seed, status, notes):
    raw_path = Path(raw_path)
    fieldnames = None
    row = {
        "method": sequence_method(seq),
        "dataset": seq["dataset"],
        "sequence": sequence_result_id(seq),
        "seed": seed,
        "run_id": "MISSING",
        "status": status,
        "notes": notes,
    }
    if raw_path.exists() and raw_path.stat().st_size > 0:
        with open(raw_path, "r", newline="", encoding="utf-8") as f:
            fieldnames = next(csv.reader(f), None)
    if not fieldnames:
        fieldnames = RAW_FIELDNAMES.get(raw_path.name)
    if fieldnames is None:
        fieldnames = list(row.keys())
    for name in fieldnames:
        row.setdefault(name, "MISSING")
    write_header = not raw_path.exists() or raw_path.stat().st_size == 0
    with open(raw_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def snapshot_raw_tables(output_dir, filenames=RAW_FILENAMES):
    """Capture raw tables before a child run so its writes are transactional."""
    output_dir = Path(output_dir)
    return {
        name: (output_dir / name).read_bytes() if (output_dir / name).exists() else None
        for name in filenames
    }


def restore_raw_tables(output_dir, snapshot):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in snapshot.items():
        path = output_dir / name
        if content is None:
            path.unlink(missing_ok=True)
            continue
        temporary = path.with_suffix(f"{path.suffix}.rollback")
        temporary.write_bytes(content)
        os.replace(temporary, path)


def rollback_and_append_failure(output_dir, snapshot, seq, seed, status, notes):
    output_dir = Path(output_dir)
    restore_raw_tables(output_dir, snapshot)
    for raw_name in RAW_FILENAMES:
        append_failure(output_dir / raw_name, seq, seed, status, notes)


def read_identity_rows(raw_path, seq, seed):
    if not raw_path.exists():
        return []
    method = sequence_method(seq)
    result_id = sequence_result_id(seq)
    rows = []
    with open(raw_path, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (
                row.get("method") == method
                and row.get("dataset") == seq["dataset"]
                and row.get("sequence") == result_id
                and str(row.get("seed")) == str(seed)
            ):
                rows.append(row)
    return rows


def read_ok_rows(raw_path, seq, seed):
    return [
        row for row in read_identity_rows(raw_path, seq, seed) if row.get("status") == "OK"
    ]


def read_ok_rows_from_snapshot(content, seq, seed):
    if content is None:
        return []
    method = sequence_method(seq)
    result_id = sequence_result_id(seq)
    rows = []
    text = content.decode("utf-8", errors="replace")
    for row in csv.DictReader(io.StringIO(text)):
        if (
            row.get("method") == method
            and row.get("dataset") == seq["dataset"]
            and row.get("sequence") == result_id
            and str(row.get("seed")) == str(seed)
            and row.get("status") == "OK"
        ):
            rows.append(row)
    return rows


def has_required_artifacts(source_dir, required_artifacts):
    if not source_dir:
        return False
    if not all(
        (Path(source_dir) / artifact).exists() for artifact in required_artifacts
    ):
        return False
    if "mapping_geometry_metrics_v2.json" in required_artifacts:
        return mapping_geometry_artifacts_complete(source_dir)
    return True


def run_geometry_eval(source_dir, output_dir, python_executable):
    cmd = [
        python_executable,
        "scripts/eval_mapping_geometry.py",
        "--run-dir",
        source_dir,
        "--tables-dir",
        str(output_dir),
    ]
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def run_aggregate(output_dir, python_executable):
    cmd = [
        python_executable,
        "scripts/aggregate_results.py",
        "--output-dir",
        str(output_dir),
    ]
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def completed_run(
    output_dir,
    seq,
    seed,
    eval_mode,
    *,
    fast_mode=False,
    geometry_complete=True,
    raw_snapshot=None,
):
    output_dir = Path(output_dir)
    identity_rows = read_identity_rows(output_dir / "tracking_raw.csv", seq, seed)
    if identity_rows and identity_rows[-1].get("status") == "ATE_ABORT":
        return True, identity_rows[-1].get("notes", "terminal ATE_ABORT")
    raw_filenames = (
        RAW_FILENAMES if eval_mode else ("tracking_raw.csv", "efficiency_raw.csv")
    )
    if eval_mode:
        required_artifacts = (
            REQUIRED_EVAL_ARTIFACTS
            if geometry_complete
            else REQUIRED_EVAL_PRE_GEOMETRY_ARTIFACTS
        )
    elif fast_mode:
        required_artifacts = REQUIRED_FAST_ARTIFACTS
    else:
        required_artifacts = REQUIRED_NORMAL_ARTIFACTS
    source_dirs = []
    for raw_name in raw_filenames:
        raw_path = output_dir / raw_name
        rows = read_ok_rows(raw_path, seq, seed)
        if raw_snapshot is not None:
            previous_rows = read_ok_rows_from_snapshot(
                raw_snapshot.get(raw_name), seq, seed
            )
            if len(rows) <= len(previous_rows):
                return False, f"{raw_name} has no new OK row from the child run"
        if not rows:
            return False, f"{raw_name} has no OK row"
        source_dir = rows[-1].get("source_dir", "")
        if not has_required_artifacts(source_dir, required_artifacts):
            return False, f"{raw_name} points to incomplete source_dir: {source_dir}"
        source_dirs.append(source_dir)
    if len(set(source_dirs)) != 1:
        return False, "raw CSV source_dir values do not match"
    return True, source_dirs[0]


def _read_log_tail(log_path, max_bytes=4 * 1024 * 1024):
    if log_path is None or not Path(log_path).exists():
        return ""
    with open(log_path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(size - max_bytes, 0))
        return f.read().decode("utf-8", errors="replace")


def _gpu_fault_in_log(log_tail):
    return any(pattern in log_tail for pattern in GPU_FAULT_PATTERNS)


def _terminate_process_group(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def append_status_event(status_file, event, **fields):
    if not status_file:
        return
    path = Path(status_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        file.flush()
        os.fsync(file.fileno())


def query_gpu_used_memory_mb():
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=memory.used",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        timeout=15,
    )
    values = [float(line.strip()) for line in output.splitlines() if line.strip()]
    if not values:
        raise RuntimeError("nvidia-smi returned no GPU memory values")
    return max(values)


def wait_for_gpu_recovery(
    cooldown_seconds,
    timeout_seconds,
    max_used_memory_mb=512.0,
    poll_seconds=10.0,
):
    if cooldown_seconds > 0:
        print(
            f"GPU recovery cooldown: {cooldown_seconds:.0f}s",
            flush=True,
        )
        time.sleep(cooldown_seconds)
    started_at = time.monotonic()
    last_error = ""
    while True:
        try:
            used_memory_mb = query_gpu_used_memory_mb()
            if used_memory_mb <= max_used_memory_mb:
                print(
                    f"GPU recovered: memory.used={used_memory_mb:.0f} MiB",
                    flush=True,
                )
                return True, used_memory_mb
            last_error = f"memory.used={used_memory_mb:.0f} MiB"
        except Exception as exc:
            last_error = f"nvidia-smi failed: {exc}"
        elapsed = time.monotonic() - started_at
        if timeout_seconds <= 0 or elapsed >= timeout_seconds:
            print(f"GPU recovery timed out: {last_error}", flush=True)
            return False, last_error
        time.sleep(min(poll_seconds, max(timeout_seconds - elapsed, 0.0)))


def run_command(
    cmd,
    log_path=None,
    timeout_seconds=0,
    stall_timeout_seconds=0,
    heartbeat_seconds=0,
    poll_interval_seconds=5.0,
):
    log_file = None
    try:
        if log_path is not None:
            log_path = Path(log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT if log_file is not None else None,
            start_new_session=True,
        )
        started_at = time.monotonic()
        last_progress_at = started_at
        last_heartbeat_at = started_at
        last_log_size = -1
        traceback_seen_at = None
        while proc.poll() is None:
            now = time.monotonic()
            log_size = 0
            if log_path is not None and Path(log_path).exists():
                log_size = Path(log_path).stat().st_size
            if log_size != last_log_size:
                last_log_size = log_size
                last_progress_at = now
            log_tail = _read_log_tail(log_path).lower()
            if any(pattern in log_tail for pattern in OOM_PATTERNS):
                _terminate_process_group(proc)
                return (
                    proc.returncode or 1,
                    "OOM",
                    f"confirmed CUDA out of memory; log: {log_path}",
                )
            if _gpu_fault_in_log(log_tail):
                _terminate_process_group(proc)
                return (
                    proc.returncode or 1,
                    "GPU_FAULT",
                    f"NVIDIA CUDA/GPU fault detected; log: {log_path}",
                )
            if "traceback (most recent call last):" in log_tail:
                if traceback_seen_at is None:
                    traceback_seen_at = time.monotonic()
                elif time.monotonic() - traceback_seen_at >= 15:
                    _terminate_process_group(proc)
                    return (
                        proc.returncode or 1,
                        "FAIL",
                        f"fatal traceback did not exit after 15s; log: {log_path}",
                    )
            if (
                stall_timeout_seconds > 0
                and now - last_progress_at >= stall_timeout_seconds
            ):
                _terminate_process_group(proc)
                return (
                    125,
                    "TIMEOUT",
                    (
                        "slam.py produced no log progress for "
                        f"{stall_timeout_seconds}s; log: {log_path}"
                    ),
                )
            if timeout_seconds > 0 and now - started_at >= timeout_seconds:
                _terminate_process_group(proc)
                return (
                    124,
                    "TIMEOUT",
                    f"slam.py exceeded {timeout_seconds}s timeout; log: {log_path}",
                )
            if heartbeat_seconds > 0 and now - last_heartbeat_at >= heartbeat_seconds:
                print(
                    "HEARTBEAT "
                    f"pid={proc.pid} elapsed_s={now - started_at:.0f} "
                    f"log_idle_s={now - last_progress_at:.0f} "
                    f"log_bytes={last_log_size} cmd={Path(cmd[0]).name}",
                    flush=True,
                )
                last_heartbeat_at = now
            time.sleep(poll_interval_seconds)
        returncode = proc.returncode
    finally:
        if log_file is not None:
            log_file.close()

    log_tail = _read_log_tail(log_path).lower()
    if returncode == 0:
        if "traceback (most recent call last):" in log_tail:
            return (
                1,
                "FAIL",
                f"child-process traceback despite zero parent exit; log: {log_path}",
            )
        return returncode, "OK", ""
    if ATE_ABORT_PATTERN in log_tail:
        return (
            returncode,
            "ATE_ABORT",
            f"online ATE exceeded the configured threshold; log: {log_path}",
        )
    if _gpu_fault_in_log(log_tail):
        return (
            returncode,
            "GPU_FAULT",
            f"NVIDIA driver/GPU fault detected; log: {log_path}",
        )
    if any(pattern in log_tail for pattern in OOM_PATTERNS):
        return (
            returncode,
            "OOM",
            (
                f"confirmed CUDA out of memory (return code {returncode}); log: {log_path}"
            ),
        )
    return (
        returncode,
        "FAIL",
        (f"slam.py failed with return code {returncode}; log: {log_path}"),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default="",
        help="Approved experiment contract; required for managed research runs.",
    )
    parser.add_argument(
        "--unsafe-legacy-cli",
        action="store_true",
        help="Bypass the experiment contract for manual debugging only.",
    )
    parser.add_argument(
        "--sequence-file",
        default="configs/rgbd/experiments/reference/monogs/sequences.yaml",
    )
    parser.add_argument("--sequences", default="")
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--experiment-name", default="")
    parser.add_argument("--results-root", default="")
    parser.add_argument("--no-eval", action="store_true")
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument(
        "--ate-abort-threshold-cm",
        type=float,
        default=0.0,
        help="Abort a run when periodic online ATE exceeds this value; 0 disables it.",
    )
    parser.add_argument(
        "--ate-abort-min-frames",
        type=int,
        default=100,
        help="Do not apply the ATE abort gate before this frame count.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="Terminate one sequence after this many seconds; 0 disables the timeout.",
    )
    parser.add_argument(
        "--stall-timeout-seconds",
        type=int,
        default=0,
        help="Terminate a child when its driver log stops growing; 0 disables it.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=int,
        default=0,
        help="Print watchdog heartbeats while a child is running; 0 disables them.",
    )
    parser.add_argument(
        "--failure-cooldown-seconds",
        type=int,
        default=0,
        help="Cooldown after OOM/GPU faults before continuing with the next arm.",
    )
    parser.add_argument(
        "--gpu-recovery-timeout-seconds",
        type=int,
        default=300,
        help="Maximum nvidia-smi recovery wait after OOM/GPU faults.",
    )
    parser.add_argument(
        "--status-file",
        default="",
        help="Optional append-only JSONL file recording job lifecycle events.",
    )
    parser.add_argument(
        "--log-dir",
        default="",
        help="Optional directory for one driver log per sequence and seed.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = None
    if args.manifest:
        if args.unsafe_legacy_cli:
            parser.error("--manifest and --unsafe-legacy-cli are mutually exclusive")
        try:
            manifest = load_experiment_manifest(args.manifest)
        except (OSError, yaml.YAMLError, ExperimentContractError) as exc:
            parser.error(str(exc))
        run = manifest["run"]
        args.sequence_file = manifest["sequence_file"]
        args.sequences = ""
        args.seeds = ",".join(str(seed) for seed in manifest["seeds"])
        args.results_root = str(managed_results_root(manifest))
        args.experiment_name = ""
        args.output_dir = DEFAULT_OUTPUT_DIR
        args.fast = run["fast"]
        args.no_eval = False
        args.max_frames = run["max_frames"]
        args.dry_run = run["dry_run"]
        args.timeout_seconds = run["timeout_seconds"]
        args.stall_timeout_seconds = run["stall_timeout_seconds"]
        args.heartbeat_seconds = run["heartbeat_seconds"]
        args.ate_abort_threshold_cm = run["ate_abort_threshold_cm"]
        args.ate_abort_min_frames = run["ate_abort_min_frames"]
        if not args.status_file:
            args.status_file = str(managed_results_root(manifest) / "status.jsonl")
        if not args.log_dir:
            args.log_dir = str(managed_results_root(manifest) / "logs")
    elif not args.unsafe_legacy_cli:
        parser.error(
            "--manifest is required; use --unsafe-legacy-cli only for manual debugging"
        )

    sequences = load_sequences(args.sequence_file, args.sequences)
    seeds = [int(seed.strip()) for seed in args.seeds.split(",") if seed.strip()]
    results_root = resolve_results_root(args.experiment_name, args.results_root)
    output_dir_arg = args.output_dir
    if results_root and output_dir_arg == DEFAULT_OUTPUT_DIR:
        output_dir_arg = str(Path(results_root) / "tables")
    output_dir = Path(output_dir_arg)
    if not args.dry_run:
        if manifest is not None:
            try:
                write_run_manifest(
                    Path(results_root) / "run_manifest.json",
                    args.manifest,
                    manifest,
                    sys.argv,
                    resume=args.resume,
                )
            except ExperimentContractError as exc:
                parser.error(str(exc))
        output_dir.mkdir(parents=True, exist_ok=True)
        append_status_event(
            args.status_file,
            "batch_started",
            sequence_file=args.sequence_file,
            seeds=seeds,
            results_root=results_root,
            fast=args.fast,
        )
    for seq in sequences:
        config = Path(seq["config"])
        if not config.exists():
            notes = f"config missing: {config}"
            if args.dry_run:
                print(f"MISSING {notes}", flush=True)
                continue
            append_failure(
                output_dir / "tracking_raw.csv", seq, "ALL", "MISSING", notes
            )
            append_failure(output_dir / "mapping_raw.csv", seq, "ALL", "MISSING", notes)
            append_failure(
                output_dir / "efficiency_raw.csv", seq, "ALL", "MISSING", notes
            )
            continue
        for seed in seeds:
            if args.resume:
                complete, reason = completed_run(
                    output_dir,
                    seq,
                    seed,
                    eval_mode=not (args.no_eval or args.fast),
                    fast_mode=args.fast,
                )
                if complete:
                    print(
                        f"SKIP {seq['id']} seed {seed}: complete at {reason}",
                        flush=True,
                    )
                    append_status_event(
                        args.status_file,
                        "job_skipped",
                        sequence=sequence_result_id(seq),
                        method=sequence_method(seq),
                        seed=seed,
                        source_dir=reason,
                    )
                    continue
                print(f"RUN {seq['id']} seed {seed}: {reason}", flush=True)
            cmd = [args.python, "slam.py", "--config", str(config), "--seed", str(seed)]
            if results_root:
                cmd.extend(["--results-root", results_root])
                cmd.extend(["--tables-dir", str(output_dir)])
            if args.fast:
                cmd.append("--fast")
            elif not args.no_eval:
                cmd.append("--eval")
            if args.max_frames > 0:
                cmd.extend(["--max-frames", str(args.max_frames)])
            if args.ate_abort_threshold_cm > 0:
                cmd.extend(
                    [
                        "--ate-abort-threshold-cm",
                        str(args.ate_abort_threshold_cm),
                        "--ate-abort-min-frames",
                        str(args.ate_abort_min_frames),
                    ]
                )
            print(" ".join(cmd), flush=True)
            if args.dry_run:
                continue
            log_path = None
            if args.log_dir:
                log_stem = sanitize_experiment_name(seq.get("label", seq["id"]))
                log_path = Path(args.log_dir) / f"{log_stem}_seed{seed}.log"
                print(f"driver log: {log_path}", flush=True)
            raw_snapshot = snapshot_raw_tables(output_dir)
            append_status_event(
                args.status_file,
                "job_started",
                sequence=sequence_result_id(seq),
                label=seq.get("label", seq["id"]),
                method=sequence_method(seq),
                seed=seed,
                log_path=str(log_path) if log_path is not None else "",
            )
            returncode, failure_status, notes = run_command(
                cmd,
                log_path=log_path,
                timeout_seconds=args.timeout_seconds,
                stall_timeout_seconds=args.stall_timeout_seconds,
                heartbeat_seconds=args.heartbeat_seconds,
            )
            if returncode != 0:
                rollback_and_append_failure(
                    output_dir,
                    raw_snapshot,
                    seq,
                    seed,
                    failure_status,
                    notes,
                )
                append_status_event(
                    args.status_file,
                    "job_finished",
                    sequence=sequence_result_id(seq),
                    method=sequence_method(seq),
                    seed=seed,
                    status=failure_status,
                    returncode=returncode,
                    notes=notes,
                )
                if failure_status in {"OOM", "GPU_FAULT"}:
                    recovered, recovery_detail = wait_for_gpu_recovery(
                        args.failure_cooldown_seconds,
                        args.gpu_recovery_timeout_seconds,
                    )
                    append_status_event(
                        args.status_file,
                        "gpu_recovery",
                        sequence=sequence_result_id(seq),
                        seed=seed,
                        recovered=recovered,
                        detail=recovery_detail,
                    )
                continue
            eval_mode = not (args.no_eval or args.fast)
            complete, reason = completed_run(
                output_dir,
                seq,
                seed,
                eval_mode=eval_mode,
                fast_mode=args.fast,
                geometry_complete=False if eval_mode else True,
                raw_snapshot=raw_snapshot,
            )
            if not complete:
                notes = (
                    f"child exited successfully but outputs are incomplete: {reason}"
                )
                rollback_and_append_failure(
                    output_dir,
                    raw_snapshot,
                    seq,
                    seed,
                    "FAIL",
                    notes,
                )
                append_status_event(
                    args.status_file,
                    "job_finished",
                    sequence=sequence_result_id(seq),
                    method=sequence_method(seq),
                    seed=seed,
                    status="FAIL",
                    returncode=0,
                    notes=notes,
                )
                continue
            if eval_mode:
                source_dir = reason
                geometry_returncode = run_geometry_eval(
                    source_dir, output_dir, args.python
                )
                if geometry_returncode != 0:
                    notes = (
                        f"mapping geometry evaluation failed with return code "
                        f"{geometry_returncode}; source_dir: {source_dir}"
                    )
                    restore_raw_tables(
                        output_dir,
                        {"mapping_raw.csv": raw_snapshot["mapping_raw.csv"]},
                    )
                    append_failure(
                        output_dir / "mapping_raw.csv", seq, seed, "FAIL", notes
                    )
                    append_status_event(
                        args.status_file,
                        "job_finished",
                        sequence=sequence_result_id(seq),
                        method=sequence_method(seq),
                        seed=seed,
                        status="FAIL",
                        returncode=geometry_returncode,
                        notes=notes,
                    )
                    continue
                complete, reason = completed_run(
                    output_dir,
                    seq,
                    seed,
                    eval_mode=True,
                    raw_snapshot=raw_snapshot,
                )
                if not complete:
                    notes = (
                        "geometry evaluation exited successfully but outputs are "
                        f"incomplete: {reason}"
                    )
                    rollback_and_append_failure(
                        output_dir,
                        raw_snapshot,
                        seq,
                        seed,
                        "FAIL",
                        notes,
                    )
                    append_status_event(
                        args.status_file,
                        "job_finished",
                        sequence=sequence_result_id(seq),
                        method=sequence_method(seq),
                        seed=seed,
                        status="FAIL",
                        returncode=0,
                        notes=notes,
                    )
                    continue
            append_status_event(
                args.status_file,
                "job_finished",
                sequence=sequence_result_id(seq),
                method=sequence_method(seq),
                seed=seed,
                status="OK",
                returncode=0,
                source_dir=reason,
            )
    if not args.dry_run:
        aggregate_returncode = run_aggregate(output_dir, args.python)
        append_status_event(
            args.status_file,
            "batch_finished",
            aggregate_returncode=aggregate_returncode,
            output_dir=str(output_dir),
        )
        if aggregate_returncode != 0:
            raise SystemExit(aggregate_returncode)


if __name__ == "__main__":
    main()
