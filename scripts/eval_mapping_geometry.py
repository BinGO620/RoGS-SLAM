import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.geometry_metrics import (
    discover_run_dirs,
    evaluate_run_geometry,
    update_mapping_raw_for_run,
    update_csv_row,
)
from utils.gpu_memory_monitor import ProcessTreeGpuMemoryMonitor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--results-root", default="results")
    parser.add_argument("--tables-dir", default="results/tables")
    parser.add_argument("--sample-count", type=int, default=200000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--frame-stride", type=int, default=5)
    parser.add_argument("--pixel-stride", type=int, default=4)
    parser.add_argument("--voxel-length", type=float, default=0.02)
    parser.add_argument("--sdf-trunc", type=float, default=0.08)
    parser.add_argument("--depth-trunc", type=float, default=5.0)
    parser.add_argument("--opacity-threshold", type=float, default=0.5)
    parser.add_argument("--min-triangles", type=int, default=100)
    parser.add_argument(
        "--allow-keyframe-fallback",
        action="store_true",
        help="Allow legacy keyframe trajectories for diagnostic-only geometry.",
    )
    parser.add_argument(
        "--source-dir-match",
        default=None,
        help="CSV source_dir identity when evaluating a copied legacy run.",
    )
    args = parser.parse_args()

    run_dirs = [args.run_dir] if args.run_dir else discover_run_dirs(args.results_root)
    if not run_dirs:
        print("No run directories found.")
        return 1

    failures = 0
    for run_dir in run_dirs:
        run_dir = os.path.normpath(run_dir)
        source_dir_match = os.path.normpath(args.source_dir_match or run_dir)
        started_at = time.perf_counter()
        memory_monitor = ProcessTreeGpuMemoryMonitor().start()
        try:
            metrics = evaluate_run_geometry(
                run_dir,
                sample_count=args.sample_count,
                seed=args.seed,
                frame_stride=args.frame_stride,
                pixel_stride=args.pixel_stride,
                voxel_length=args.voxel_length,
                sdf_trunc=args.sdf_trunc,
                depth_trunc=args.depth_trunc,
                opacity_threshold=args.opacity_threshold,
                min_triangles=args.min_triangles,
            )
            formal_eligible = metrics["protocol_eligible"]
            update_mapping_raw_for_run(
                run_dir,
                metrics,
                tables_dir=args.tables_dir,
                source_dir=args.source_dir_match,
            )
            if not formal_eligible and not args.allow_keyframe_fallback:
                raise RuntimeError(
                    "full estimated trajectory is missing; diagnostic artifacts were "
                    "written, but formal geometry is incomplete. Use "
                    "--allow-keyframe-fallback only for legacy diagnostics"
                )
            memory = memory_monitor.stop()
            efficiency_updates = {
                "geometry_eval_time_s": round(time.perf_counter() - started_at, 4),
                "geometry_eval_peak_gpu_memory_gb": memory["peak_gpu_memory_gb"],
            }
            notes = (
                f"geometry memory monitor: {memory['error']}"
                if memory["error"]
                else None
            )
            update_csv_row(
                os.path.join(args.tables_dir, "efficiency_raw.csv"),
                source_dir_match,
                efficiency_updates,
                append_notes=notes,
            )
            update_csv_row(
                os.path.join(run_dir, "efficiency_raw.csv"),
                source_dir_match,
                efficiency_updates,
                append_notes=notes,
            )
            print(
                f"OK {run_dir}: accuracy_cm={metrics['accuracy_cm']}, "
                f"completion_cm={metrics['completion_cm']}, "
                f"completion_ratio={metrics['completion_ratio']}"
            )
        except Exception as exc:
            memory_monitor.stop()
            print(f"FAIL {run_dir}: {exc}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
