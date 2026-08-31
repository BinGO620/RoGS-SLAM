import csv
import os
import tempfile
import unittest

import pandas as pd

from scripts.aggregate_results import mean_std
from scripts.run_monogs_batch import append_failure, resolve_results_root
from scripts.summarize_three_metrics import build_summary, write_summary


class StableScriptTests(unittest.TestCase):
    def test_managed_result_name_is_sanitized(self):
        self.assertEqual(
            resolve_results_root("R0-P01-E1"),
            "results/runs/R0-P01-E1",
        )
        self.assertEqual(
            resolve_results_root("unsafe name"),
            "results/runs/unsafe_name",
        )

    def test_failure_row_uses_stable_raw_schema(self):
        sequence = {"method": "candidate", "dataset": "TUM", "id": "f1_desk"}
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "tracking_raw.csv")
            append_failure(path, sequence, 0, "FAIL", "test failure")
            with open(path, newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
        self.assertEqual(rows[0]["status"], "FAIL")
        self.assertEqual(rows[0]["sequence"], "f1_desk")
        self.assertIn("ate_rmse_cm", rows[0])

    def test_three_metric_summary_joins_by_run_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "tracking_raw.csv")
            with open(path, "w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=(
                        "method",
                        "dataset",
                        "sequence",
                        "seed",
                        "status",
                        "ate_rmse_cm",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "method": "control",
                        "dataset": "TUM",
                        "sequence": "f1_desk",
                        "seed": 0,
                        "status": "OK",
                        "ate_rmse_cm": 1.25,
                    }
                )
            rows = build_summary(directory)
            output = write_summary(directory, rows)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["tracking_ate_rmse_cm"], "1.25")
            self.assertTrue(output.exists())

    def test_aggregate_mean_std_uses_sample_standard_deviation(self):
        summary = mean_std(pd.Series([1.0, 3.0]))
        self.assertEqual(summary, "2.0000 ± 1.4142")


if __name__ == "__main__":
    unittest.main()
