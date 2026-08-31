"""Unit tests for the exp23 ReliabilitySignal silent-noop hard gate.

Contracts (frozen 2026-08-16, exp24, after user-confirmed incident):
  1. ``assert_reliability_flow_available(config, dataset_path)`` RAISES when
     ``ReliabilitySignal.enabled=true`` but the flow dir is empty/missing.
  2. It does NOT raise when flow exists, OR when enabled=false OR subdir is wrong
     but flow present.
  3. It respects ``flow_subdir`` (default ``flow_raft``).
  4. The gate decision is independent of gaussians/iteration (takes only config +
     dataset_path), so it aborts on the FIRST frame.
  Pure CPU: temp dirs + dummy .npy files (frozen_flow_index only globs .npy).
"""

import os
import tempfile
import unittest

import numpy as np

from utils.reliability_signal import assert_reliability_flow_available


def _write_flow(seq_dir, name="1341846313.654212.npy", subdir="flow_raft"):
    d = os.path.join(seq_dir, subdir)
    os.makedirs(d, exist_ok=True)
    np.save(os.path.join(d, name), np.zeros((2, 2, 2), dtype=np.float32))
    return d


class ReliabilityFlowGateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.seq = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_enabled_no_flow_raises(self):
        config = {"ReliabilitySignal": {"enabled": True}}
        with self.assertRaisesRegex(RuntimeError, "no frozen flow"):
            assert_reliability_flow_available(config, self.seq)

    def test_enabled_subdir_missing_raises(self):
        config = {"ReliabilitySignal": {"enabled": True, "flow_subdir": "missing"}}
        with self.assertRaisesRegex(RuntimeError, "no frozen flow"):
            assert_reliability_flow_available(config, self.seq)

    def test_enabled_flow_present_ok(self):
        _write_flow(self.seq)
        config = {"ReliabilitySignal": {"enabled": True}}
        idx = assert_reliability_flow_available(config, self.seq)
        self.assertTrue(idx)  # non-empty index returned

    def test_disabled_not_called(self):
        # enabled=false + missing flow: the helper is NEVER called (slam_frontend
        # gates entry on reliability_signal_enabled). Document that boundary by
        # asserting the caller-side predicate is False, not by calling the helper.
        from utils.reliability_signal import reliability_signal_enabled

        self.assertFalse(reliability_signal_enabled({"ReliabilitySignal": {"enabled": False}}))
        self.assertFalse(reliability_signal_enabled({"ReliabilitySignal": {}}))
        self.assertFalse(reliability_signal_enabled({}))

    def test_custom_subdir_respected(self):
        _write_flow(self.seq, subdir="myflow")
        config = {"ReliabilitySignal": {"enabled": True, "flow_subdir": "myflow"}}
        idx = assert_reliability_flow_available(config, self.seq)
        self.assertTrue(idx)

    def test_empty_dir_raises(self):
        # dir exists but no .npy files -> empty index -> raises.
        os.makedirs(os.path.join(self.seq, "flow_raft"), exist_ok=True)
        config = {"ReliabilitySignal": {"enabled": True}}
        with self.assertRaisesRegex(RuntimeError, "no frozen flow"):
            assert_reliability_flow_available(config, self.seq)


if __name__ == "__main__":
    unittest.main()
