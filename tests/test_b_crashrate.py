"""Candidate B Phase 0 verdict rule (``scripts/b_crashrate_verdict.py``).

The whole point of this experiment is that a *mean* hid a *bimodal* distribution, so the
verdict rule must be tested on the shapes it is meant to tell apart -- including the one
that would retroactively invalidate the project's mask-free columns (T-CONFIRMED).

The ATE reader is tested too: the headline number is the full-trajectory
``ate_rmse_cm`` in ``tables/tracking_raw.csv``, and reading anything else (notably the
console keyframe RMSE) has silently produced wrong tables in this project before.
"""

import csv
import importlib.util
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_SPEC = importlib.util.spec_from_file_location(
    "b_crashrate_verdict", os.path.join(_ROOT, "scripts", "b_crashrate_verdict.py"))
b = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(b)


def _mk(root, name, ate):
    d = os.path.join(root, name, "tables")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "tracking_raw.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["seq", "ate_rmse_cm", "n_frames"])
        w.writeheader()
        w.writerow({"seq": "crowd2", "ate_rmse_cm": ate, "n_frames": 895})


def _run(t_vals, s_vals):
    root = tempfile.mkdtemp()
    for i, v in enumerate(t_vals, 1):
        _mk(root, f"T_seed0_rep{i}", v)
    for i, v in enumerate(s_vals, 1):
        _mk(root, f"S_seed{i}", v)
    return b.verdict(root)


class TestAteReader(unittest.TestCase):
    def test_reads_full_trajectory_ate(self):
        root = tempfile.mkdtemp()
        _mk(root, "T_seed0_rep1", 44.21)
        self.assertAlmostEqual(b._ate(os.path.join(root, "T_seed0_rep1")), 44.21)

    def test_missing_run_is_none_not_zero(self):
        """A crashed run must not be read as a perfect 0 cm."""
        self.assertIsNone(b._ate(tempfile.mkdtemp()))

    def test_missing_runs_are_excluded_not_imputed(self):
        root = tempfile.mkdtemp()
        for i, v in enumerate([44.0, 46.0, 45.0], 1):
            _mk(root, f"T_seed0_rep{i}", v)
        os.makedirs(os.path.join(root, "T_seed0_rep4"), exist_ok=True)   # died
        self.assertEqual(len(b.collect(root)["T"]), 3)


class TestVerdictRule(unittest.TestCase):
    def test_timing_split_is_confirmed(self):
        """Identical config AND seed spanning 44->97 -> the mask-free mean is invalid."""
        v = _run([44.2, 45.1, 97.0, 46.0, 95.5, 44.9], [44.0, 96.0, 45.0, 94.0, 44.5, 45.5])
        self.assertTrue(v["verdict"].startswith("T-CONFIRMED"), v)

    def test_seed_split_with_stable_repeats(self):
        v = _run([44.2, 44.5, 44.0, 44.3, 44.1, 44.4], [44.0, 96.0, 45.0, 94.0, 44.5, 45.5])
        self.assertTrue(v["verdict"].startswith("S-CONFIRMED"), v)

    def test_no_reproduction_is_its_own_verdict(self):
        """Both blocks tight: the split did not reproduce -- not a licence to trust the mean."""
        v = _run([44.2, 44.5, 44.0, 44.3, 44.1, 44.4], [44.0, 45.0, 44.6, 44.2, 44.9, 45.1])
        self.assertTrue(v["verdict"].startswith("NEITHER"), v)

    def test_ambiguous_is_indeterminate_not_rounded_to_a_side(self):
        v = _run([44.0, 55.0, 44.5, 54.0, 44.2, 53.0], [44.0, 45.0, 44.6, 44.2, 44.9, 45.1])
        self.assertEqual(v["verdict"], "INDETERMINATE")

    def test_too_few_runs_is_incomplete(self):
        v = _run([44.0, 97.0], [44.0, 45.0])
        self.assertEqual(v["verdict"], "INCOMPLETE")

    def test_collapse_rate_uses_the_registered_50cm_line(self):
        v = _run([44.0, 44.5, 97.0, 98.0, 44.2, 44.9], [44.0, 45.0, 44.6, 44.2, 44.9, 45.1])
        self.assertAlmostEqual(v["blocks"]["T"]["collapse_rate"], 2 / 6)
        self.assertAlmostEqual(v["blocks"]["S"]["collapse_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
