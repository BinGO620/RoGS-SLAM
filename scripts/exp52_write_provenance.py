"""One-off: write EXP52 provenance json on the remote (post-dispatch re-issue).

The runner's inline provenance writer crashed on PosixPath/str sort_keys serialization
(missing str() on glob results). Runs were unaffected; the hashed file set is unchanged
since dispatch (tracked tree clean-checked by the runner; runs write only to gitignored
results/). This re-issue records the same payload plus an honest note.
"""

import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path

files = [
    "utils/slam_backend.py",
    "utils/slam_frontend.py",
    "utils/reliability_signal.py",
    "utils/slam_utils.py",
    "utils/alpha_lifecycle.py",
    "utils/mapping_probe.py",
    "utils/mapping_weight.py",
    "configs/rgbd/tum/base_config.yaml",
    "configs/rgbd/bonn/base_config.yaml",
    "configs/rgbd/bonn/balloon.yaml",
    "configs/rgbd/tum/f3_st_hf.yaml",
    "configs/rgbd/experiments/active/candidate/method_combined_maskoff_prune.yaml",
    "configs/rgbd/experiments/wpm_maskonly/method_maskonly.yaml",
    "configs/rgbd/experiments/p11_maskonly/method_p11_maskonly.yaml",
    "configs/rgbd/experiments/p11_maskonly/p11_maskonly_f3_st_hf.yaml",
    "configs/rgbd/experiments/p11_maskonly/p11_maskonly_balloon.yaml",
]
files.extend(str(p) for p in sorted(Path("configs/rgbd/experiments/exp52_p11").glob("*.yaml")))
files.extend([
    "scripts/run_exp52_p11_3090.sh",
    "scripts/read_exp52_p11.py",
    "tests/test_exp52_p11_configs.py",
    "results/evidence/exp52_p11_prereg.md",
])


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


payload = {
    "experiment": "EXP52-P11-revalidate-matched",
    "expected_head": os.environ.get("EXPECTED_HEAD"),
    "actual_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "hostname": socket.gethostname(),
    "python": os.path.realpath(os.environ.get("PY", "")),
    "files_sha256": {p: sha256(p) for p in files},
    "note": (
        "Re-issued post-dispatch: the runner inline provenance writer crashed on "
        "PosixPath/str sort_keys serialization (missing str() on glob results). Runs "
        "were unaffected; the hashed file set is unchanged since dispatch (tracked "
        "tree clean-checked by the runner; runs write only to gitignored results/)."
    ),
}
with open("results/runs/EXP52/exp52_provenance.json", "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
print("WROTE results/runs/EXP52/exp52_provenance.json with", len(files), "files")
