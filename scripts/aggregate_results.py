import argparse
import os

import pandas as pd


TRACKING_FIELDS = [
    ("ATE RMSE (cm)", "ate_rmse_cm"),
    ("ATE Error STD (cm)", "ate_error_std_cm"),
    ("RPE Trans. RMSE (cm)", "rpe_trans_rmse_cm"),
    ("Path Length Ratio (%)", "path_length_ratio"),
    ("Keyframe ATE (cm)", "keyframe_ate_rmse_cm"),
]
MAPPING_FIELDS = [
    ("PSNR", "psnr"),
    ("SSIM", "ssim"),
    ("LPIPS", "lpips"),
    ("Depth L1 (cm)", "depth_l1_cm"),
    ("Accuracy (cm)", "accuracy_cm"),
]
EFFICIENCY_FIELDS = [
    ("FPS", "online_fps"),
    ("Tracking FPS", "tracking_fps"),
    ("Mapping FPS", "mapping_fps"),
    ("Tracking Time (ms)", "tracking_time_ms"),
    ("Mapping Time (ms)", "mapping_time_ms"),
    ("Reliable Tracking Time (ms)", "reliable_tracking_time_ms"),
    ("Reliable Depth Fallback", "reliable_tracking_depth_fallback_ratio"),
    ("Semantic Time (ms)", "semantic_time_ms"),
    ("GPU (GB)", "online_peak_gpu_memory_gb"),
    ("#Gaussians", "online_num_gaussians"),
    ("Refinement Time (s)", "refinement_wall_time_s"),
    ("Geometry Eval Time (s)", "geometry_eval_time_s"),
]


def mean_std(series):
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        labels = {str(item).strip() for item in series.dropna()}
        if labels and labels <= {"N/A"}:
            return "N/A"
        if labels and labels <= {"FAIL"}:
            return "FAIL"
        return "MISSING"
    if len(values) == 1:
        return f"{values.mean():.4f}"
    std = values.std(ddof=1)
    return f"{values.mean():.4f} ± {std:.4f}"


def _parse_seeds(seeds_arg):
    if not seeds_arg:
        return None
    return {str(int(seed.strip())) for seed in seeds_arg.split(",") if seed.strip()}


def _latest_per_seed(raw):
    if "seed" not in raw or "run_id" not in raw:
        return raw
    raw = raw.copy()
    raw["_row_order"] = range(len(raw))
    raw["_run_sort"] = raw["run_id"].astype(str)
    raw = raw.sort_values(["_run_sort", "_row_order"])
    key = ["method", "dataset", "sequence", "seed"]
    ok = raw[raw["status"] == "OK"] if "status" in raw else raw.iloc[0:0]
    latest_ok = ok.drop_duplicates(subset=key, keep="last")
    latest_any = raw.drop_duplicates(subset=key, keep="last")
    deduped = pd.concat([latest_any, latest_ok]).drop_duplicates(
        subset=key,
        keep="last",
    )
    return deduped.drop(columns=["_row_order", "_run_sort"])


def aggregate(raw_path, fields, seeds=None, include_duplicate_runs=False):
    if not os.path.exists(raw_path):
        return pd.DataFrame(
            columns=["Method", "Dataset", "Sequence"] + [name for name, _ in fields]
        )
    raw = pd.read_csv(raw_path, keep_default_na=False)
    if raw.empty:
        return pd.DataFrame(
            columns=["Method", "Dataset", "Sequence"] + [name for name, _ in fields]
        )
    if seeds is not None and "seed" in raw:
        raw = raw[raw["seed"].astype(str).isin(seeds)]
    if not include_duplicate_runs:
        raw = _latest_per_seed(raw)
    rows = []
    for (method, dataset, sequence), group in raw.groupby(
        ["method", "dataset", "sequence"], dropna=False
    ):
        ok = group[group["status"] == "OK"]
        row = {"Method": method, "Dataset": dataset, "Sequence": sequence}
        source = ok if not ok.empty else group
        for display_name, raw_name in fields:
            row[display_name] = (
                mean_std(source[raw_name]) if raw_name in source else "MISSING"
            )
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="results/tables")
    parser.add_argument("--tracking-raw", default=None)
    parser.add_argument("--mapping-raw", default=None)
    parser.add_argument("--efficiency-raw", default=None)
    parser.add_argument(
        "--seeds",
        default=None,
        help="Optional comma-separated seed filter, for example 0,1,2.",
    )
    parser.add_argument(
        "--include-duplicate-runs",
        action="store_true",
        help="Aggregate every OK run instead of keeping only the latest run per seed.",
    )
    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    seeds = _parse_seeds(args.seeds)
    tracking_raw = args.tracking_raw or os.path.join(
        args.output_dir, "tracking_raw.csv"
    )
    mapping_raw = args.mapping_raw or os.path.join(args.output_dir, "mapping_raw.csv")
    efficiency_raw = args.efficiency_raw or os.path.join(
        args.output_dir, "efficiency_raw.csv"
    )

    tracking = aggregate(
        tracking_raw,
        TRACKING_FIELDS,
        seeds=seeds,
        include_duplicate_runs=args.include_duplicate_runs,
    )
    mapping = aggregate(
        mapping_raw,
        MAPPING_FIELDS,
        seeds=seeds,
        include_duplicate_runs=args.include_duplicate_runs,
    )
    efficiency = aggregate(
        efficiency_raw,
        EFFICIENCY_FIELDS,
        seeds=seeds,
        include_duplicate_runs=args.include_duplicate_runs,
    )

    tracking.to_excel(
        os.path.join(args.output_dir, "tracking_results.xlsx"), index=False
    )
    mapping.to_excel(os.path.join(args.output_dir, "mapping_results.xlsx"), index=False)
    efficiency.to_excel(
        os.path.join(args.output_dir, "efficiency_results.xlsx"), index=False
    )

    main_table = tracking[["Method", "Dataset", "Sequence", "ATE RMSE (cm)"]].rename(
        columns={"ATE RMSE (cm)": "ATE (cm)"}
    )
    for table, cols in [
        (mapping, ["PSNR", "SSIM", "LPIPS", "Depth L1 (cm)"]),
        (efficiency, ["FPS", "GPU (GB)"]),
    ]:
        main_table = main_table.merge(
            table[["Method", "Dataset", "Sequence"] + cols],
            on=["Method", "Dataset", "Sequence"],
            how="outer",
        )
    main_table.to_excel(os.path.join(args.output_dir, "main_results.xlsx"), index=False)


if __name__ == "__main__":
    main()
