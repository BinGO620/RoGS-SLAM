import json
import os
import tempfile
import unittest

from scripts.check_flow_complete import check_sequence_flow, sequence_needs_flow


def _make_seq(directory, n_rgb, n_flow, manifest_frames, frame_stems=None):
    rgb = os.path.join(directory, "rgb")
    flow = os.path.join(directory, "flow_raft")
    os.makedirs(rgb)
    os.makedirs(flow)
    for i in range(n_rgb):
        open(os.path.join(rgb, f"{i:06d}.png"), "wb").close()
    for i in range(n_flow):
        open(os.path.join(flow, f"{i:06d}.npy"), "wb").close()
    if manifest_frames is not None:
        manifest = {"n_frames": manifest_frames}
        if frame_stems is not None:
            manifest["frame_stems"] = frame_stems
        with open(os.path.join(flow, "manifest.json"), "w", encoding="utf-8") as file:
            json.dump(manifest, file)


class CheckFlowCompleteTests(unittest.TestCase):
    def test_full_backward_flow_is_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            _make_seq(directory, n_rgb=10, n_flow=9, manifest_frames=10)
            report = check_sequence_flow(directory)
        self.assertTrue(report["complete"])

    def test_truncated_dev_build_fails(self):
        # the obox trap: 79 flow files + manifest n_frames=80 against 590 rgb frames
        with tempfile.TemporaryDirectory() as directory:
            _make_seq(directory, n_rgb=590, n_flow=79, manifest_frames=80)
            report = check_sequence_flow(directory)
        self.assertFalse(report["complete"])

    def test_missing_flow_dir_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "rgb"))
            open(os.path.join(directory, "rgb", "0.png"), "wb").close()
            report = check_sequence_flow(directory)
        self.assertFalse(report["complete"])

    def test_manifest_mismatch_fails_even_with_enough_files(self):
        with tempfile.TemporaryDirectory() as directory:
            _make_seq(directory, n_rgb=10, n_flow=9, manifest_frames=8)
            report = check_sequence_flow(directory)
        self.assertFalse(report["complete"])

    def test_duplicate_depth_stems_collapse_is_complete(self):
        # Bonn associations can map one depth frame to two rgb frames; flow files
        # are stem-keyed so duplicates collapse (mv_no_box2: 937 rgb, 6 dups ->
        # 931 unique stems -> 930 npy). Expected count follows unique stems.
        stems = [f"{i:06d}" for i in range(8)] + ["000003", "000005"]  # 10 frames, 8 unique
        with tempfile.TemporaryDirectory() as directory:
            _make_seq(directory, n_rgb=10, n_flow=7, manifest_frames=10, frame_stems=stems)
            report = check_sequence_flow(directory)
        self.assertTrue(report["complete"])
        self.assertEqual(report["n_unique_stems"], 8)

    def test_truncated_build_still_fails_with_frame_stems(self):
        stems = [f"{i:06d}" for i in range(590)]
        with tempfile.TemporaryDirectory() as directory:
            _make_seq(directory, n_rgb=590, n_flow=79, manifest_frames=590, frame_stems=stems)
            report = check_sequence_flow(directory)
        self.assertFalse(report["complete"])

    def test_flow_requirement_reads_both_gates(self):
        self.assertFalse(sequence_needs_flow({}))
        self.assertTrue(sequence_needs_flow({"ReliabilitySignal": {"enabled": True}}))
        self.assertTrue(
            sequence_needs_flow({"DeferredCommit": {"reliability_confirm": True}})
        )


if __name__ == "__main__":
    unittest.main()
