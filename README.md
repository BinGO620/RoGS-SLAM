# RoGS-SLAM

**Dynamic 3D Gaussian Splatting SLAM** (research content 1; accepted at MMM 2027,
camera-ready 14 pages).

A dynamic-scene 3DGS SLAM system built on [MonoGS](https://github.com/muskie82/MonoGS).
Instead of relying on semantic segmentation to remove dynamic observations
outright, the method **re-weights** them with an optical-flow consistency
reliability signal. Four components:

- **K** — unified keyframe coverage (`DynamicKeyframe`)
- **R** — robust re-weighting (`RobustTracking`, Huber IRLS)
- **L** — reliability signal (`ReliabilitySignal`: observation flow vs rigid-body
  flow residual → Cauchy down-weighting only)
- **D** — lineage lifecycle (`DeferredCommit`), plus an optional semantic mask
  (`SemanticMask`)

All are enabled by default in `configs/experiments/combined_prune/method.yaml`.

## Installation

```bash
git clone --recursive https://github.com/BinGO620/RoGS-SLAM.git
cd RoGS-SLAM
./setup_env.sh          # conda env + two CUDA extensions (SHA-pinned) + Bonn/TUM datasets
conda activate rogs-slam
```

For a full step-by-step walkthrough — requirements, CUDA checks, datasets, smoke
test, and Table 1 reproduction — see **[REPRODUCING.md](REPRODUCING.md)**.

## Usage

```bash
# Single sequence (paper 1 evaluation protocol; 18 BONN/TUM sequences)
python slam.py --config configs/experiments/combined_prune/balloon.yaml --seed 0 --eval

# Recompute Table 1 (18 sequences x 4 methods, ATE) and check it cell by cell
python results/evidence/verify_table1.py

# Gates
pytest tests/test_config_valid.py -q
```

## Results (Table 1 reproduction)

`results/evidence/table1_18seq_ate.{csv,md}` holds the published numbers
(4 methods x 18 sequences). `results/runs/P6/` archives the P6 family's
criterion artifacts (8 sub-families; `config.yml` / `tracking_raw.csv` /
`mapping_raw.csv` / `efficiency_raw.csv` / `summary`+`stats_final.json` /
`console.log` / `per_frame_ape.csv`, 111 runs). `verify_table1.py` recomputes
from those CSVs and compares against the table:

- **`combined` and `maskfree`: all 28 cells match bit for bit** (mean ± std
  identical to the published table);
- `vanilla` (stock MonoGS) and `rgd` (comparison method): the run artifacts are
  not part of this archive, so the numbers come from the evidence CSV. Those
  cells are explicitly reported as `NO-RUN-IN-REPO` rather than silently passed.

## Project Structure

```
slam.py / utils/ / gaussian_splatting/ / gui/   # runtime core (pruning list in PROVENANCE.md)
configs/rgbd/{bonn,tum}/                        # 18+ sequence configs (BONN dynamic + TUM)
configs/experiments/combined_prune/             # method core (method.yaml) + control arms
results/evidence/                               # Table 1 / factorial / cuesplit verdicts
results/runs/P6/                                # P6 family criterion artifacts (tar extract)
submodules/                                     # diff-gaussian-rasterization-w-pose + simple-knn
```

## Provenance

This repository was rebuilt from monogs-ours@`31b0f0367` by dependency-closure
pruning; the copy list, deletions, and verification record are in
[PROVENANCE.md](PROVENANCE.md). This repository is the minimal reproduction set
for paper 1. Paper 2 is RoGS-Map, paper 3 is RoGS-Densify (the three share an
upstream core; `diff -r utils/` shows the per-paper mechanism differences).

## Testing

```bash
pytest tests/test_config_valid.py -q     # 9 passed
```

## Acknowledgements

Built on [MonoGS](https://github.com/muskie82/MonoGS) and
[3D Gaussian Splatting](https://github.com/graphdeco-inria/gaussian-splatting).

## License

Released for **non-commercial research and evaluation use only**, inherited from
the Inria/MPII Gaussian-Splatting License that covers the rasterizer submodule.
See [LICENSE](LICENSE) for the combined terms and the per-component table.

## Citation

If you use this code, please cite the paper — see [CITATION.cff](CITATION.cff).
