"""CPU tests for the zero-GPU EXP53 component attribution audit."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_exp53_component_attribution",
    ROOT / "scripts" / "audit_exp53_component_attribution.py",
)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class TestExp53ComponentAudit(unittest.TestCase):
    def test_mean_sd_uses_sample_standard_deviation(self):
        result = AUDIT._mean_sd([1.0, 2.0, 3.0])
        self.assertEqual(result["n"], 3)
        self.assertAlmostEqual(result["mean"], 2.0)
        self.assertAlmostEqual(result["sd"], 1.0)

    def test_config_diff_only_reports_component_fields(self):
        p11 = {
            "config": {
                "DynamicKeyframe.enabled": False,
                "ReliabilitySignal.enabled": False,
                "SemanticMask.mask_mapping": True,
                "SemanticMask.mask_insertion": False,
                "Mapping.lifecycle_mode": "prune",
                "Training.kf_interval": 5,
            }
        }
        combined = {
            "config": {
                "DynamicKeyframe.enabled": True,
                "ReliabilitySignal.enabled": True,
                "SemanticMask.mask_mapping": True,
                "SemanticMask.mask_insertion": True,
                "Mapping.lifecycle_mode": "prune",
                "Training.kf_interval": 5,
            }
        }
        self.assertEqual(
            AUDIT._config_diff(p11, combined),
            {
                "DynamicKeyframe.enabled": (False, True),
                "ReliabilitySignal.enabled": (False, True),
                "SemanticMask.mask_insertion": (False, True),
            },
        )

    def test_report_explicitly_preserves_causal_unresolved_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = AUDIT.summarize(ROOT / "results/runs/EXP53/p11phase2")
            text = AUDIT.render_markdown(report)
            self.assertIn("COMPONENT CAUSAL ATTRIBUTION UNRESOLVED", text)
            self.assertIn("three-variable bundled intervention", text)
            payload = Path(tmp) / "report.json"
            payload.write_text(json.dumps(report), encoding="utf-8")
            self.assertIn("EXP53-P11-phase2", payload.read_text(encoding="utf-8"))

    def test_missing_run_is_not_treated_as_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = AUDIT.read_run(Path(tmp) / "missing")
            self.assertFalse(record["complete"])
            self.assertEqual(record["error"], "missing save_dir")


if __name__ == "__main__":
    unittest.main(verbosity=2)
