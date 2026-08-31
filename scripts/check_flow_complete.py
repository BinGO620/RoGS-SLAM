"""Preflight: assert frozen RAFT flow completeness for a managed experiment.

Guards against the f2_xyz/obox trap where a dev-era truncated ``flow_raft/`` build
(e.g. 79/590 frames left by an ``--max-frames`` smoke) silently passes an
existence-only check and the reliability signal then runs "missing-cue -> neutral"
on most frames. Completeness, not existence, is the gate:

    n_flow >= n_unique_stems - 1   (backward flow f_{t->t-1}: frame 0 has none)
    manifest n_frames == n_rgb

``n_unique_stems`` = unique depth-file stems in the manifest's ``frame_stems``
(falls back to ``n_rgb`` when absent). Bonn associations can map one depth frame
to two rgb frames (e.g. moving_nonobstructing_box2 has 6 such duplicates, obox 1);
flow/mask files are keyed by depth stem, so duplicates collapse to one file on
disk. Runtime lookup is also stem-keyed, so every frame still resolves a flow
field — comparing raw file count against ``n_rgb`` would false-FAIL these
sequences while the truncated-build trap is still caught (79/590 << unique-1).

Works on DRAFT manifests (plain YAML parse, no APPROVED gate) so it can run
before approval; the managed runner's own contract checks stay authoritative.
"""

import argparse
import glob
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_utils import load_config


def sequence_needs_flow(config):
    reliability = config.get("ReliabilitySignal", {}) or {}
    deferred = config.get("DeferredCommit", {}) or {}
    return bool(reliability.get("enabled")) or bool(deferred.get("reliability_confirm"))


def check_sequence_flow(seq_dir, flow_subdir="flow_raft"):
    """Return a completeness report dict for one sequence directory."""
    rgb_files = glob.glob(os.path.join(seq_dir, "rgb", "*.png"))
    flow_dir = os.path.join(seq_dir, flow_subdir)
    flow_files = glob.glob(os.path.join(flow_dir, "*.npy"))
    manifest_frames = None
    n_unique_stems = None
    manifest_path = os.path.join(flow_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as file:
                manifest = json.load(file)
            manifest_frames = manifest.get("n_frames")
            stems = manifest.get("frame_stems")
            if stems:
                n_unique_stems = len(set(stems))
        except (OSError, ValueError):
            manifest_frames = None
    n_rgb = len(rgb_files)
    n_flow = len(flow_files)
    n_expected = n_unique_stems if n_unique_stems is not None else n_rgb
    complete = (
        n_rgb > 0
        and n_flow >= n_expected - 1
        and manifest_frames == n_rgb
    )
    return {
        "seq_dir": seq_dir,
        "flow_subdir": flow_subdir,
        "n_rgb": n_rgb,
        "n_flow": n_flow,
        "n_unique_stems": n_unique_stems,
        "manifest_n_frames": manifest_frames,
        "complete": complete,
    }


def check_manifest_flow(manifest_path):
    """Check every unique sequence dir referenced by the manifest's registry.

    Returns (reports, failures); sequences whose effective config does not use
    the flow signal are skipped (reported with needed=False).
    """
    with open(manifest_path, encoding="utf-8") as file:
        manifest = yaml.safe_load(file)
    sequence_file = manifest.get("sequence_file", "")
    with open(sequence_file, encoding="utf-8") as file:
        sequences = yaml.safe_load(file)["sequences"]

    reports = []
    seen = set()
    for seq in sequences:
        config = load_config(seq["config"])
        seq_dir = str(config.get("Dataset", {}).get("dataset_path", ""))
        flow_subdir = str(
            (config.get("ReliabilitySignal", {}) or {}).get("flow_subdir", "flow_raft")
        )
        key = (seq_dir, flow_subdir)
        if key in seen:
            continue
        seen.add(key)
        needed = sequence_needs_flow(config)
        report = {"id": seq.get("id", "?"), "needed": needed}
        if needed:
            report.update(check_sequence_flow(seq_dir, flow_subdir))
        else:
            report.update({"seq_dir": seq_dir, "complete": True})
        reports.append(report)
    failures = [r for r in reports if r["needed"] and not r["complete"]]
    return reports, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default="configs/rgbd/experiments/active/experiment.yaml",
        help="experiment manifest whose sequence registry to check",
    )
    args = parser.parse_args()
    reports, failures = check_manifest_flow(args.manifest)
    for report in reports:
        if not report["needed"]:
            print(f"SKIP  {report['id']} (flow signal off)")
            continue
        state = "OK  " if report["complete"] else "FAIL"
        print(
            f"{state}  {report['id']}  rgb={report['n_rgb']} "
            f"flow={report['n_flow']} unique_stems={report['n_unique_stems']} "
            f"manifest={report['manifest_n_frames']} "
            f"({report['seq_dir']})"
        )
    if failures:
        print(
            f"flow incomplete for {len(failures)} sequence(s); build full-length "
            "flow first: python scripts/build_flow_raft.py --sequence-dir <dir>"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
