"""Unit tests for the reliability_signal/frames.csv provenance column contract.

WHY THIS FILE EXISTS (exp26, 2026-08-17). ``_flush_reliability_signal`` wrote a
hard-coded 9-column whitelist, so every provenance key the producer emitted --
``ego_projection``, ``ego_pose_oracle`` and the whole ``ego_*`` guard block --
was silently dropped. Both ``reliability_signal.compute_reliability_tracking_weight``
and the frontend call site carried comments asserting the column "never
disappears"; on disk the P8 control / oracle / fix arms had byte-identical
headers and were indistinguishable. That is the silent-no-op failure class
again: an asserted invariant with no test behind it.

Contracts (frozen 2026-08-17, exp26):
  1. The historical 9 columns keep their exact order at the FRONT of the header
     (existing readers must not break).
  2. Any other key present on a row REACHES DISK -- specifically the ego
     provenance/guard block. This is the regression that must never return.
  3. A legacy run (no ego keys) still writes exactly the historical 9 columns,
     so turning the mechanism off does not churn the schema.
  4. Rows with missing keys write a blank cell instead of raising.
  5. Header order is deterministic for the same row set.
  6. summary.json carries the ego provenance block (applied fraction + reject
     reason histogram) so a run can be triaged without re-parsing frames.csv.

Pure CPU / tempdir; no torch, no FrontEnd instance.
"""

import csv
import json
import os
import tempfile
import unittest

from utils.slam_frontend import (
    RELIABILITY_FRAMES_BASE_FIELDS,
    reliability_frames_fields,
    reliability_frames_summary,
    write_reliability_frames,
)

BASE = list(RELIABILITY_FRAMES_BASE_FIELDS)

# The keys the ego-projection producer emits (reliability_signal.py `stats` +
# ego_residual_projection `stats` + the frontend's oracle provenance column).
EGO_KEYS = [
    "ego_projection",
    "ego_pose_oracle",
    "ego_fit_applied",
    "ego_reject",
    "ego_corr_px",
    "ego_dxi_norm",
    "ego_explained_frac",
]


def _base_row(frame, itr=0):
    return {
        "frame": frame, "tracking_itr": itr,
        "mean_s": 0.9, "min_s": 0.1, "mean_w": 0.8, "min_w": 0.2,
        "flow_valid_frac": 0.95, "e_flow_mean_valid": 0.13, "g_mean": 0.05,
    }


def _ego_row(frame, applied=1, reject="none", corr=3.2, explained=0.6, oracle=0):
    row = _base_row(frame)
    row.update({
        "ego_projection": 1, "ego_pose_oracle": oracle,
        "ego_fit_applied": applied, "ego_reject": reject,
        "ego_corr_px": corr, "ego_dxi_norm": 0.004,
        "ego_explained_frac": explained,
    })
    return row


class ReliabilityFramesFieldsTest(unittest.TestCase):
    def test_base_block_keeps_frozen_order_at_front(self):
        fields = reliability_frames_fields([_ego_row(0), _ego_row(1)])
        self.assertEqual(fields[: len(BASE)], BASE)

    def test_ego_provenance_keys_reach_the_header(self):
        """The exact exp26 regression: these were silently dropped."""
        fields = reliability_frames_fields([_ego_row(0)])
        for key in EGO_KEYS:
            self.assertIn(key, fields, f"{key} must not be dropped from frames.csv")

    def test_legacy_rows_write_exactly_the_historical_columns(self):
        self.assertEqual(reliability_frames_fields([_base_row(0)]), BASE)

    def test_header_order_is_deterministic(self):
        rows = [_ego_row(0), _ego_row(1)]
        self.assertEqual(
            reliability_frames_fields(rows), reliability_frames_fields(rows)
        )

    def test_union_over_rows_not_just_the_first(self):
        """A key that only appears on a later row still reaches disk."""
        rows = [_base_row(0), _ego_row(1)]
        self.assertIn("ego_reject", reliability_frames_fields(rows))


class WriteReliabilityFramesTest(unittest.TestCase):
    def test_written_header_and_values_round_trip(self):
        rows = [_ego_row(0, applied=1, reject="none"),
                _ego_row(1, applied=0, reject="not_ego_explainable")]
        with tempfile.TemporaryDirectory() as tmp:
            fields = write_reliability_frames(tmp, rows)
            with open(os.path.join(tmp, "frames.csv"), newline="") as fh:
                got = list(csv.DictReader(fh))
            self.assertEqual(list(got[0].keys()), fields)
            self.assertEqual(got[0]["ego_projection"], "1")
            self.assertEqual(got[1]["ego_reject"], "not_ego_explainable")
            self.assertEqual(got[1]["ego_fit_applied"], "0")

    def test_oracle_arm_is_distinguishable_on_disk(self):
        """control / oracle frames.csv must differ -- the 12.4x claim's audit trail."""
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = os.path.join(tmp, "control")
            orac = os.path.join(tmp, "oracle")
            write_reliability_frames(ctrl, [_ego_row(0, oracle=0)])
            write_reliability_frames(orac, [_ego_row(0, oracle=1)])
            with open(os.path.join(ctrl, "frames.csv"), newline="") as fh:
                c = list(csv.DictReader(fh))[0]["ego_pose_oracle"]
            with open(os.path.join(orac, "frames.csv"), newline="") as fh:
                o = list(csv.DictReader(fh))[0]["ego_pose_oracle"]
            self.assertNotEqual(c, o)

    def test_missing_key_writes_blank_not_raise(self):
        rows = [_base_row(0), _ego_row(1)]
        with tempfile.TemporaryDirectory() as tmp:
            write_reliability_frames(tmp, rows)
            with open(os.path.join(tmp, "frames.csv"), newline="") as fh:
                got = list(csv.DictReader(fh))
            self.assertEqual(got[0]["ego_reject"], "")
            self.assertEqual(got[1]["ego_reject"], "none")


class ReliabilityFramesSummaryTest(unittest.TestCase):
    def test_legacy_summary_keeps_historical_keys_and_no_ego_block(self):
        s = reliability_frames_summary([_base_row(0), _base_row(1)])
        for key in ("frames", "mean_mean_w", "mean_min_w",
                    "mean_flow_valid_frac", "mean_mean_s"):
            self.assertIn(key, s)
        self.assertNotIn("ego_projection", s)

    def test_ego_block_reports_applied_fraction_and_reject_histogram(self):
        rows = [
            _ego_row(0, applied=1, reject="none", corr=2.0, explained=0.5),
            _ego_row(1, applied=0, reject="not_ego_explainable"),
            _ego_row(2, applied=0, reject="corr_too_large"),
            _ego_row(3, applied=1, reject="none", corr=4.0, explained=0.7),
        ]
        s = reliability_frames_summary(rows)
        self.assertEqual(s["ego_projection"], 1)
        self.assertEqual(s["ego_fit_applied_frames"], 2)
        self.assertAlmostEqual(s["ego_fit_applied_frac"], 0.5)
        self.assertEqual(
            s["ego_reject_counts"],
            {"corr_too_large": 1, "none": 2, "not_ego_explainable": 1},
        )
        self.assertAlmostEqual(s["mean_ego_corr_px"], 3.0)
        self.assertAlmostEqual(s["mean_ego_explained_frac"], 0.6)

    def test_all_rejected_run_reports_zero_applied_without_dividing_by_zero(self):
        rows = [_ego_row(i, applied=0, reject="min_valid") for i in range(3)]
        s = reliability_frames_summary(rows)
        self.assertEqual(s["ego_fit_applied_frames"], 0)
        self.assertAlmostEqual(s["ego_fit_applied_frac"], 0.0)
        self.assertNotIn("mean_ego_corr_px", s)

    def test_summary_is_json_serialisable(self):
        s = reliability_frames_summary([_ego_row(0), _ego_row(1, oracle=1)])
        self.assertIsInstance(json.dumps(s), str)
        self.assertEqual(s["ego_pose_oracle"], 1)


if __name__ == "__main__":
    unittest.main()
