"""Cross-document consistency of every shared ATE cell and derived ratio.

An r3 review round found three failure classes that no existing gate covers:
(1) a verdict file printing a population sd (ddof=0) where every table uses the
    sample sd (ddof=1), so the same runs carried two different dispersions;
(2) SI S3.2 improvement ratios computed from a stale campaign's combined arm,
    disagreeing with the final S12 cells by up to 10%;
(3) hand-typed S12 cells drifting by one final digit from the script-generated
    authoritative table (results/evidence/18seq_rendering_main_table.md).

This test pins all three: shared cells must match across SI/S12, verdict and
authoritative table; every printed mean/sd must recompute from its printed
seeds with ddof=1; every quoted ratio must be the quotient of the authoritative
cells (to 0.01, round-half-up). It fails loudly rather than warning.
"""
import os
import re
import statistics
import unittest
from decimal import Decimal, ROUND_HALF_UP

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SI = os.path.join(ROOT, "papers/maskfree_bundle/latex_si/si_body_v3.tex")
AUTH = os.path.join(ROOT, "results/evidence/18seq_rendering_main_table.md")
VERDICT = os.path.join(ROOT, "results/evidence/p6_maskoff_3seed_verdict.md")
HEADLINE = os.path.join(ROOT, "results/evidence/headline_ratio_recompute.md")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _r2(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class TestVerdictSeedArithmetic(unittest.TestCase):
    """Class (1): printed mean/sd must recompute from printed seeds, ddof=1."""

    def test_balloon_and_mvnobox_cells(self):
        text = _read(VERDICT)
        for seq, seeds, mean, sd in [
            ("balloon", [13.66, 9.43, 13.24], "12.11", "2.33"),
            ("mv_no_box", [3.60, 2.99, 2.70], "3.10", "0.46"),
        ]:
            m = statistics.mean(seeds)
            s = statistics.stdev(seeds)  # ddof=1
            self.assertEqual(str(_r2(m)), mean, f"{seq} mean in {VERDICT}")
            self.assertEqual(str(_r2(s)), sd, f"{seq} sd in {VERDICT}")
            cell = re.search(re.escape(seq) + r".*?\*\*(\d+\.\d+±\d+\.\d+)\*\*", text)
            self.assertTrue(cell, f"{seq} cell row not found in verdict")
            self.assertEqual(cell.group(1), f"{mean}±{sd}")


class TestS12AgainstAuthoritativeTable(unittest.TestCase):
    """Class (3): every S12 cell must equal the script-generated table cell."""

    def _auth_cells(self):
        cells = {}
        for line in _read(AUTH).splitlines():
            m = re.match(
                r"\|\s*(\S+)\s*\|[^|]+\|\s*\*\*(Ours-(?:mask-free|combined\(mask-ON\)))\*\*\s*\|"
                r"\s*(\d+\.\d+)±(\d+\.\d+)\s*\|",
                line,
            )
            if m:
                seq, arm, mean, sd = m.groups()
                arm = "mask-free" if "mask-free" in arm else "combined"
                cells[(seq, arm)] = (mean, sd)
        return cells

    def test_all_shared_cells_equal(self):
        auth = self._auth_cells()
        self.assertGreaterEqual(len(auth), 36, "authoritative table parse broke")
        si = _read(SI)
        # S12 rows: seq & group & MonoGS & mask-free & combined & RGD
        rows = {}
        for line in si.splitlines():
            if "&" not in line or "$\\pm$" not in line:
                continue
            cols = [c.strip() for c in line.split("&")]
            if len(cols) < 6:
                continue
            seq = re.sub(r"\\path\{|\\texttt\{|\}", "", cols[0])
            if seq not in {s for s, _ in auth}:
                continue
            rows[seq] = cols
        checked = 0
        for (seq, arm), (mean, sd) in auth.items():
            self.assertIn(seq, rows, f"S12 row for {seq} not found")
            cols = rows[seq]
            cell = cols[3] if arm == "mask-free" else cols[4]
            cell = cell.replace("$\\pm$", "±").replace("\\pm", "±")
            cell = re.sub(r"[${}\\]|\\dag\{\}|\\ddag\{\}|boldmath|ddag|dag", "", cell)
            self.assertEqual(cell, f"{mean}±{sd}",
                             f"S12 {seq} {arm} drifted from authoritative table")
            checked += 1
        self.assertGreaterEqual(checked, 36, f"only {checked} S12 cells checked")


class TestS32Ratios(unittest.TestCase):
    """Class (2): SI S3.2 ratios must be quotients of the authoritative cells."""

    def test_quoted_ratios_recompute(self):
        si = _read(SI)
        auth = TestS12AgainstAuthoritativeTable()._auth_cells()
        vanilla = {}
        for line in _read(AUTH).splitlines():
            m = re.match(r"\|\s*(\S+)\s*\|[^|]+\|\s*MonoGS \(vanilla, 3-seed\)\s*\|\s*(\d+\.\d+)±", line)
            if m:
                vanilla[m.group(1)] = float(m.group(2))

        for seq, arm, quoted in [
            ("f3_wk_rpy", "combined", "14.66"), ("balloon", "combined", "12.85"),
            ("f3_wk_xyz", "combined", "9.20"), ("balloon2", "combined", "4.18"),
            ("pt2", "combined", "4.20"), ("crowd2", "combined", "67.33"),
            ("crowd", "combined", "37.76"), ("f3_wk_hf", "combined", "13.51"),
            ("pt1", "combined", "3.77"),
            ("pt2", "mask-free", "4.72"), ("balloon", "mask-free", "3.25"),
            ("balloon2", "mask-free", "2.17"),
        ]:
            got = _r2(vanilla[seq] / float(auth[(seq, arm)][0]))
            self.assertEqual(str(got), quoted, f"S3.2 {seq} {arm} ratio is stale")

        # stale values from the old campaign must not survive anywhere in the SI
        for stale in ["17.13", "60.93", "37.11$\\times$", "14.67$\\times$"]:
            self.assertNotIn(stale, si, f"stale ratio {stale} still present in SI")


class TestHeadlineFileConsistency(unittest.TestCase):
    def test_headline_ratios_match_authoritative(self):
        text = _read(HEADLINE)
        auth = TestS12AgainstAuthoritativeTable()._auth_cells()
        vanilla = {}
        for line in _read(AUTH).splitlines():
            m = re.match(r"\|\s*(\S+)\s*\|[^|]+\|\s*MonoGS \(vanilla, 3-seed\)\s*\|\s*(\d+\.\d+)±", line)
            if m:
                vanilla[m.group(1)] = float(m.group(2))
        for seq, arm, quoted in [
            ("f3_wk_rpy", "combined", "14.66"), ("crowd2", "combined", "67.33"),
            ("crowd", "combined", "37.76"), ("f3_wk_hf", "combined", "13.51"),
            ("balloon", "mask-free", "3.25"), ("pt2", "mask-free", "4.72"),
        ]:
            got = _r2(vanilla[seq] / float(auth[(seq, arm)][0]))
            self.assertIn(f"{quoted}×", text, f"headline {seq} {arm} ratio missing/stale")




class TestS33RenderingTableAgainstAuthoritative(unittest.TestCase):
    """Every S3.3 rendering cell must equal the script-generated table."""

    def test_all_s33_cells_equal(self):
        auth = {}
        for line in _read(AUTH).splitlines():
            m = re.match(
                r"\|\s*(\S+)\s*\|[^|]+\|\s*\*\*(Ours-(?:mask-free|combined\(mask-ON\)))\*\*\s*\|"
                r"\s*(\d+\.\d+)±(\d+\.\d+)\s*\|\s*(\d+\.\d+)±(\d+\.\d+)\s*\|\s*"
                r"(\d+\.\d+)±(\d+\.\d+)\s*\|\s*(\d+\.\d+)±(\d+\.\d+)\s*\|\s*"
                r"(\d+\.\d+)±(\d+\.\d+)\s*\|", line)
            if m:
                seq, arm = m.group(1), ("mask-free" if "mask-free" in m.group(2) else "combined")
                auth[(seq, arm)] = m.groups()[2:]
        self.assertGreaterEqual(len(auth), 36, "authoritative table parse broke")
        si = _read(SI)
        row = re.compile(
            r"\\path\{(\S+)\} & (mask-free|combined) & (\d+\.\d+)\$\\pm\$(\d+\.\d+) & "
            r"(\d+\.\d+)\$\\pm\$(\d+\.\d+) & (\d+\.\d+)\$\\pm\$(\d+\.\d+) & "
            r"(\d+\.\d+)\$\\pm\$(\d+\.\d+) & (\d+\.\d+)\$\\pm\$(\d+\.\d+)")
        checked = 0
        for m in row.finditer(si):
            key = (m.group(1), m.group(2))
            self.assertIn(key, auth, f"S3.3 row {key} absent from authoritative table")
            got = m.groups()[2:]
            want = auth[key]
            self.assertEqual(got, want, f"S3.3 {key} drifted from authoritative table")
            checked += 1
        self.assertGreaterEqual(checked, 24, f"only {checked} S3.3 rows parsed")


if __name__ == "__main__":
    unittest.main()
