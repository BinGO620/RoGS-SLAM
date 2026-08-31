import json
import os
import tempfile
import unittest

from utils.config_utils import load_config
from utils.experiment_contract import (
    ExperimentContractError,
    managed_results_root,
    validate_experiment_manifest,
)


class ExperimentContractTests(unittest.TestCase):
    @staticmethod
    def _write_json(path, payload):
        with open(path, "w", encoding="utf-8") as file:
            json.dump(payload, file)

    def _manifest(self, sequence_file):
        return {
            "schema_version": 1,
            "plan_id": "R0-P01",
            "experiment_id": "R0-P01-E1",
            "status": "APPROVED",
            "stage": "E1",
            "hypothesis": "One declared mechanism improves paired tracking.",
            "sequence_file": sequence_file,
            "seeds": [0],
            "comparison": {
                "control": "approved-control",
                "candidate": "candidate",
                "allowed_config_diff": ["Proposed.enabled"],
            },
            "run": {
                "dry_run": False,
                "fast": True,
                "max_frames": 15,
                "timeout_seconds": 900,
                "stall_timeout_seconds": 180,
                "heartbeat_seconds": 30,
                "ate_abort_threshold_cm": 10.0,
                "ate_abort_min_frames": 100,
            },
            "gates": {"max_relative_ate_regression_pct": 10.0},
            "hardware": "",
        }

    def _diagnostic_manifest(self, sequence_file):
        return {
            "schema_version": 1,
            "mode": "diagnostic",
            "plan_id": "R0-P01",
            "experiment_id": "R0-P01-D2",
            "status": "APPROVED",
            "stage": "D2",
            "hypothesis": "Locate where the control first drifts on the static sequence.",
            "sequence_file": sequence_file,
            "seeds": [0],
            "comparison": {
                "control": "approved-control",
                "candidate": "",
                "allowed_config_diff": [],
            },
            "run": {
                "dry_run": False,
                "fast": True,
                "max_frames": 0,
                "timeout_seconds": 900,
                "stall_timeout_seconds": 180,
                "heartbeat_seconds": 30,
                "ate_abort_threshold_cm": 50.0,
                "ate_abort_min_frames": 100,
            },
            "gates": {"max_absolute_ate_cm": 100.0},
            "hardware": "RTX2060",
        }

    def _diagnostic_sequences(self, directory, arm="diagnostic", method="approved-control"):
        control = os.path.join(directory, "control.yaml")
        sequences = os.path.join(directory, "sequences.yaml")
        self._write_json(control, {"method": method})
        self._write_json(
            sequences,
            {
                "sequences": [
                    {
                        "arm": arm,
                        "dataset": "TUM",
                        "id": "f2_xyz",
                        "method": method,
                        "config": control,
                    }
                ]
            },
        )
        return sequences

    def test_draft_manifest_is_fail_closed(self):
        with self.assertRaisesRegex(ExperimentContractError, "APPROVED"):
            validate_experiment_manifest({"schema_version": 1, "status": "DRAFT"})

    def test_paired_config_diff_must_be_declared(self):
        with tempfile.TemporaryDirectory() as directory:
            control = os.path.join(directory, "control.yaml")
            candidate = os.path.join(directory, "candidate.yaml")
            sequences = os.path.join(directory, "sequences.yaml")
            self._write_json(
                control,
                {"method": "approved-control", "Proposed": {"enabled": False}},
            )
            self._write_json(
                candidate,
                {"method": "candidate", "Proposed": {"enabled": True}},
            )
            self._write_json(
                sequences,
                {
                    "sequences": [
                        {
                            "pair": "f1",
                            "arm": "control",
                            "dataset": "TUM",
                            "id": "f1_desk",
                            "config": control,
                        },
                        {
                            "pair": "f1",
                            "arm": "candidate",
                            "dataset": "TUM",
                            "id": "f1_desk",
                            "config": candidate,
                        },
                    ]
                },
            )
            manifest = self._manifest(sequences)
            validate_experiment_manifest(manifest)

            self._write_json(
                candidate,
                {
                    "method": "candidate",
                    "Proposed": {"enabled": True},
                    "Training": {"window_size": 99},
                },
            )
            with self.assertRaisesRegex(
                ExperimentContractError, "Training.window_size"
            ):
                validate_experiment_manifest(manifest)

    def test_e2_allows_fast_and_full_eval_seed0(self):
        with tempfile.TemporaryDirectory() as directory:
            control = os.path.join(directory, "control.yaml")
            candidate = os.path.join(directory, "candidate.yaml")
            sequences = os.path.join(directory, "sequences.yaml")
            self._write_json(
                control,
                {"method": "approved-control", "Proposed": {"enabled": False}},
            )
            self._write_json(
                candidate,
                {"method": "candidate", "Proposed": {"enabled": True}},
            )
            self._write_json(
                sequences,
                {
                    "sequences": [
                        {
                            "pair": "f1",
                            "arm": "control",
                            "dataset": "TUM",
                            "id": "f1_desk",
                            "config": control,
                        },
                        {
                            "pair": "f1",
                            "arm": "candidate",
                            "dataset": "TUM",
                            "id": "f1_desk",
                            "config": candidate,
                        },
                    ]
                },
            )
            manifest = self._manifest(sequences)
            manifest["experiment_id"] = "R0-P01-E2"
            manifest["stage"] = "E2"
            manifest["hardware"] = "RTX2060"
            manifest["run"]["max_frames"] = 0
            for fast in (True, False):
                manifest["run"]["fast"] = fast
                validate_experiment_manifest(manifest)
            manifest["stage"] = "E3"
            manifest["experiment_id"] = "R0-P01-E3"
            manifest["seeds"] = [0, 1, 2]
            manifest["run"]["fast"] = False
            with self.assertRaisesRegex(ExperimentContractError, "run.fast"):
                validate_experiment_manifest(manifest)

    def test_comparison_mode_still_requires_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            sequences = os.path.join(directory, "sequences.yaml")
            self._write_json(sequences, {"sequences": []})
            manifest = self._manifest(sequences)
            manifest["comparison"]["candidate"] = ""
            with self.assertRaisesRegex(
                ExperimentContractError, "control and candidate"
            ):
                validate_experiment_manifest(manifest)

    def test_diagnostic_single_arm_manifest_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            sequences = self._diagnostic_sequences(directory)
            validate_experiment_manifest(self._diagnostic_manifest(sequences))

    def test_diagnostic_mode_forbids_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            sequences = self._diagnostic_sequences(directory)
            manifest = self._diagnostic_manifest(sequences)
            manifest["comparison"]["candidate"] = "sneaky-candidate"
            with self.assertRaisesRegex(ExperimentContractError, "candidate"):
                validate_experiment_manifest(manifest)

    def test_diagnostic_mode_forbids_allowed_config_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            sequences = self._diagnostic_sequences(directory)
            manifest = self._diagnostic_manifest(sequences)
            manifest["comparison"]["allowed_config_diff"] = ["Proposed.enabled"]
            with self.assertRaisesRegex(ExperimentContractError, "allowed_config_diff"):
                validate_experiment_manifest(manifest)

    def test_diagnostic_mode_rejects_comparison_arms(self):
        with tempfile.TemporaryDirectory() as directory:
            sequences = self._diagnostic_sequences(directory, arm="control")
            with self.assertRaisesRegex(ExperimentContractError, "arm=diagnostic"):
                validate_experiment_manifest(self._diagnostic_manifest(sequences))

    def test_diagnostic_experiment_id_must_use_d_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            sequences = self._diagnostic_sequences(directory)
            manifest = self._diagnostic_manifest(sequences)
            manifest["experiment_id"] = "R0-P01-E2"
            with self.assertRaisesRegex(ExperimentContractError, "experiment_id"):
                validate_experiment_manifest(manifest)

    def test_v1_is_loaded_as_reference_not_control(self):
        config = load_config("configs/rgbd/experiments/reference/v1/f3_wk_xyz.yaml")
        self.assertEqual(config["method"], "v1-reference")
        self.assertTrue(config["SemanticMask"]["mask_insertion"])

    def test_results_root_uses_current_plan_ids(self):
        root = managed_results_root(
            {"plan_id": "R0-P01", "experiment_id": "R0-P01-E1"}
        )
        self.assertEqual(str(root), "results/runs/R0-P01/R0-P01-E1")


if __name__ == "__main__":
    unittest.main()
