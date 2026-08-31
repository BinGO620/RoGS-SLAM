"""Gates on the vanilla (MonoGS) 3-seed ratio denominator in the main table.

Every improvement ratio in the paper divides by this baseline, and an earlier draft
quoted ratios against a single-seed number with no dispersion at all
(results/evidence/headline_ratio_recompute.md). The table builder therefore refuses
to emit when the denominator drifts, is incomplete, or would render a fabricated
"+-0.00". A gate that never fires is not a gate, so each of those refusals is fed a
known-bad value here (project rule, exp33 criterion #11 / exp37 gate-writing lesson).
"""
import csv
import importlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

BUILD = "scripts.build_18seq_main_table"


def _load():
    mod = importlib.import_module(BUILD)
    return importlib.reload(mod)


def _csv_text(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["method", "dataset", "sequence", "seed", "run_id", "status", "notes",
                "ate_rmse_cm"])
    for seq, seed, status, ate in rows:
        w.writerow(["MonoGS", "BONN", seq, seed, f"{seq}_seed_{seed}", status, "", ate])
    return buf.getvalue()


class VanillaDenominatorGate(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    # ---- the gate passes on the real, landed denominator --------------------
    def test_real_csv_matches_the_published_audit(self):
        """The on-disk baseline must still reproduce headline_ratio_recompute.md."""
        rec = self.mod.read_vanilla_3seed()
        for seq, (exp_m, exp_sd) in self.mod.VANILLA_EXPECTED.items():
            self.assertIn(seq, rec, f"{seq} missing from denominator")
            got_m, got_sd = rec[seq][0], rec[seq][1]
            self.assertAlmostEqual(got_m, exp_m, delta=0.011, msg=f"{seq} mean drifted")
            self.assertIsNotNone(got_sd, f"{seq} has no sd")
            self.assertAlmostEqual(got_sd, exp_sd, delta=0.011, msg=f"{seq} sd drifted")

    def test_all_18_paper_sequences_resolve(self):
        rec = self.mod.read_vanilla_3seed()
        for seq in self.mod.SEQORDER:
            self.assertIn(seq, rec, f"{seq} unresolved (alias table out of date?)")

    def test_pt_aliases_resolve_to_the_bonn_upstream_names(self):
        """pt1/pt2 exist only via the alias; a dropped alias must not pass silently."""
        rec = self.mod.read_vanilla_3seed()
        self.assertEqual(rec["pt1"], rec["person_t"])
        self.assertEqual(rec["pt2"], rec["person_t2"])

    # ---- the gate FIRES on known-bad denominators ---------------------------
    def test_drifted_mean_is_refused(self):
        bad = _csv_text([("person_t", s, "OK", v) for s, v in
                         enumerate([54.45, 36.46, 43.56])]
                        + [("balloon", s, "OK", v) for s, v in
                           enumerate([99.0, 99.0, 99.0])])   # balloon mean 99 != 39.32
        with mock.patch("builtins.open", mock.mock_open(read_data=bad)), \
                mock.patch.object(self.mod.os.path, "exists", return_value=True):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.read_vanilla_3seed()
        self.assertIn("disagrees with headline_ratio_recompute", str(ctx.exception))

    def test_missing_sequence_is_refused(self):
        bad = _csv_text([("balloon", s, "OK", v) for s, v in
                         enumerate([38.31, 39.32, 40.33])])   # every other seq absent
        with mock.patch("builtins.open", mock.mock_open(read_data=bad)), \
                mock.patch.object(self.mod.os.path, "exists", return_value=True):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.read_vanilla_3seed()
        self.assertIn("absent", str(ctx.exception))

    def test_absent_csv_is_refused(self):
        with mock.patch.object(self.mod.os.path, "exists", return_value=False):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.read_vanilla_3seed()
        self.assertIn("denominator missing", str(ctx.exception))

    def test_non_ok_rows_do_not_enter_the_denominator(self):
        """A crashed seed must not be averaged into the baseline."""
        text = _csv_text([("balloon", 0, "OK", 38.31), ("balloon", 1, "OK", 39.32),
                          ("balloon", 2, "OK", 40.33), ("balloon", 3, "FAIL", 900.0)])
        with mock.patch("builtins.open", mock.mock_open(read_data=text)), \
                mock.patch.object(self.mod.os.path, "exists", return_value=True), \
                mock.patch.dict(self.mod.VANILLA_EXPECTED, {}, clear=True):
            rec = self.mod.read_vanilla_3seed()
        self.assertEqual(rec["balloon"][2], 3, "FAIL row leaked into n")
        self.assertAlmostEqual(rec["balloon"][0], 39.32, delta=0.005)


class DispersionFormatting(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_high_cv_is_flagged_and_low_cv_is_not(self):
        hi = self.mod.fmt_vanilla((15.33, 9.47, 3, 9.47 / 15.33))     # CV 62%
        lo = self.mod.fmt_vanilla((39.32, 1.01, 3, 1.01 / 39.32))     # CV 3%
        self.assertIn("⚠", hi)
        self.assertIn("CV 62%", hi)
        self.assertNotIn("⚠", lo)

    def test_single_seed_never_renders_a_fabricated_zero_sd(self):
        s = self.mod.fmt_vanilla((12.0, None, 1, None))
        self.assertNotIn("±", s)
        self.assertIn("n=1", s)

    def test_the_eight_high_cv_sequences_are_exactly_the_audited_ones(self):
        """The audit names 8 sequences with vanilla CV>20%; the table must flag those 8."""
        rec = self.mod.read_vanilla_3seed()
        flagged = {s for s in self.mod.SEQORDER
                   if "⚠" in self.mod.fmt_vanilla(rec.get(s))}
        self.assertEqual(
            flagged,
            {"crowd", "crowd2", "f3_wk_hf", "f3_st_hf", "f3_st_rpy",
             "mv_no_box", "mv_no_box2", "pt1"},
            "flagged set drifted from headline_ratio_recompute.md §五-A",
        )


if __name__ == "__main__":
    unittest.main()
