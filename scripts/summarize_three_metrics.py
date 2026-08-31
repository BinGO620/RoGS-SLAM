import argparse
import csv
from pathlib import Path


IDENTITY_FIELDS = ("method", "dataset", "sequence", "seed")
TABLE_FIELDS = {
    "tracking_raw.csv": (
        "status",
        "ate_rmse_cm",
        "keyframe_ate_rmse_cm",
        "rpe_trans_rmse_cm",
        "path_length_ratio",
    ),
    "mapping_raw.csv": (
        "status",
        "psnr",
        "ssim",
        "lpips",
        "depth_l1_cm",
        "accuracy_cm",
        "completion_cm",
        "completion_ratio",
    ),
    "efficiency_raw.csv": (
        "status",
        "efficiency_protocol_version",
        "online_fps",
        "tracking_fps",
        "mapping_fps",
        "online_peak_gpu_memory_gb",
        "online_num_gaussians",
        "online_time_s",
        "refinement_wall_time_s",
        "geometry_eval_time_s",
        "semantic_time_ms",
        "semantic_calls",
    ),
}
PREFIXES = {
    "tracking_raw.csv": "tracking",
    "mapping_raw.csv": "mapping",
    "efficiency_raw.csv": "efficiency",
}


def read_table(path):
    path = Path(path)
    if not path.exists():
        return {}
    rows = {}
    with open(path, newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            key = tuple(row.get(field, "MISSING") for field in IDENTITY_FIELDS)
            rows[key] = row
    return rows


def build_summary(tables_dir):
    tables_dir = Path(tables_dir)
    tables = {name: read_table(tables_dir / name) for name in TABLE_FIELDS}
    keys = sorted({key for rows in tables.values() for key in rows})
    summary = []
    for key in keys:
        output = dict(zip(IDENTITY_FIELDS, key))
        for name, fields in TABLE_FIELDS.items():
            row = tables[name].get(key, {})
            prefix = PREFIXES[name]
            for field in fields:
                output[f"{prefix}_{field}"] = row.get(field, "MISSING")
        summary.append(output)
    return summary


def write_summary(tables_dir, rows):
    output_path = Path(tables_dir) / "three_metric_summary.csv"
    fieldnames = list(IDENTITY_FIELDS)
    for name, fields in TABLE_FIELDS.items():
        prefix = PREFIXES[name]
        fieldnames.extend(f"{prefix}_{field}" for field in fields)
    with open(output_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Merge tracking, mapping and efficiency raw rows by run identity."
    )
    parser.add_argument("--tables-dir", required=True)
    args = parser.parse_args()
    rows = build_summary(args.tables_dir)
    output_path = write_summary(args.tables_dir, rows)
    print(f"Wrote {len(rows)} rows to {output_path}")


if __name__ == "__main__":
    main()
