"""Unit tests for the frozen RAFT-flow artifact IO (utils/flow_raft.py, method #8 R0).

Pure CPU tests: no torchvision, no GPU, no dataset. Verify the frozen-provenance
contract -- deterministic content hash, float16 round-trip, shape guards, the
source-stem index, and the config/variant gates. The RAFT model forward is exercised
only by the GPU builder (scripts/build_flow_raft.py), like the gtmc GPU loop.
"""

import os
import tempfile
import unittest

import numpy as np

from utils.flow_raft import (
    flow_raft_enabled,
    flow_sha256,
    frozen_flow_index,
    get_flow_raft_config,
    load_frozen_flow,
    load_raft_model,
    save_frozen_flow,
)


class FlowHashTests(unittest.TestCase):
    def test_deterministic_and_content_sensitive(self):
        a = np.zeros((4, 5, 2), dtype=np.float32)
        b = a.copy()
        b[0, 0, 0] = 3.0
        self.assertEqual(flow_sha256([a]), flow_sha256([a.copy()]))
        self.assertNotEqual(flow_sha256([a]), flow_sha256([b]))
        # order matters (stack hash), and matches a re-read of the fp16 bytes
        self.assertNotEqual(flow_sha256([a, b]), flow_sha256([b, a]))

    def test_hash_is_float16_domain(self):
        # a float32-only perturbation below fp16 resolution must NOT change the hash
        a = np.full((3, 3, 2), 4.0, dtype=np.float32)
        b = a.copy()
        b[0, 0, 0] = 4.0 + 1e-4  # far below fp16 ulp at magnitude 4
        self.assertEqual(flow_sha256([a]), flow_sha256([b]))


class FrozenFlowIOTests(unittest.TestCase):
    def test_roundtrip_shape_and_dtype(self):
        rng = np.random.default_rng(0)
        flow = (rng.standard_normal((6, 8, 2)) * 5.0).astype(np.float32)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "1234.567.npy")
            save_frozen_flow(p, flow)
            out = load_frozen_flow(p)
        self.assertEqual(out.shape, (6, 8, 2))
        self.assertEqual(out.dtype, np.float32)
        # float16 storage: agreement to ~1e-2 px at |f|~5, far below the noise floor
        self.assertTrue(np.allclose(out, flow, atol=2e-2))

    def test_save_rejects_bad_shape(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                save_frozen_flow(os.path.join(d, "x.npy"), np.zeros((4, 4, 3)))
            with self.assertRaises(ValueError):
                save_frozen_flow(os.path.join(d, "y.npy"), np.zeros((4, 4)))

    def test_load_rejects_bad_shape(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.npy")
            np.save(p, np.zeros((4, 4, 5), dtype=np.float16), allow_pickle=False)
            with self.assertRaises(ValueError):
                load_frozen_flow(p)


class FrozenFlowIndexTests(unittest.TestCase):
    def test_index_maps_stems_and_ignores_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            for stem in ("1548339348.69390", "1548339348.72742"):
                save_frozen_flow(os.path.join(d, f"{stem}.npy"), np.zeros((2, 2, 2)))
            with open(os.path.join(d, "manifest.json"), "w") as fh:
                fh.write("{}")
            idx = frozen_flow_index(d)
        self.assertEqual(
            set(idx), {"1548339348.69390", "1548339348.72742"}
        )
        self.assertTrue(all(p.endswith(".npy") and os.path.isabs(p) for p in idx.values()))

    def test_missing_or_empty_dir_is_empty(self):
        self.assertEqual(frozen_flow_index(None), {})
        self.assertEqual(frozen_flow_index("/no/such/flow/dir"), {})
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(frozen_flow_index(d), {})


class ConfigGateTests(unittest.TestCase):
    def test_enabled_and_config_accessor(self):
        self.assertFalse(flow_raft_enabled({}))
        self.assertFalse(flow_raft_enabled({"FlowRaft": {"enabled": False}}))
        self.assertTrue(flow_raft_enabled({"FlowRaft": {"enabled": True}}))
        self.assertEqual(get_flow_raft_config({"FlowRaft": {"variant": "small"}}),
                         {"variant": "small"})

    def test_invalid_variant_rejected_before_torch_import(self):
        # variant is validated first, so this raises without torchvision present
        with self.assertRaises(ValueError):
            load_raft_model("bogus")


if __name__ == "__main__":
    unittest.main()
