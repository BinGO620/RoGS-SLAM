# RoGS-SLAM

**Robust Gaussian Splatting SLAM in Dynamic Environments via Reliability-Guided Weighting**

<p align="center">
  <img src="papers/maskfree_bundle/figures/fig1_pipeline_v3.png" width="720" alt="RoGS-SLAM pipeline">
</p>

## Overview

RoGS-SLAM is a **mask-free** dynamic 3D Gaussian Splatting SLAM system built on [MonoGS](https://github.com/muskie82/MonoGS). It handles dynamic objects without any semantic segmentation network using four lightweight components:

| Component | Description | Attaches to |
|---|---|---|
| **Uniform keyframe coverage (K)** | Regular temporal sampling | Keyframe insertion |
| **Robust reweighting (R)** | Huber IRLS in the pose solver | Tracking residual |
| **Reliability signal (L)** | Flow-consistency static confidence | Tracking + lifecycle |
| **Lineage lifecycle (D)** | Deferred Gaussian commit/evict | Gaussian creation |

The reliability signal decides which pixels to trust **from optical-flow consistency alone** — no class labels, no object detectors. Pixels are down-weighted (never hard-removed).

### Key results (BONN RGB-D Dynamic, ATE RMSE cm)

| | crowd | crowd2 | mv_no_box | pt2 |
|---|---|---|---|---|
| MonoGS (baseline) | 86.5 | 147.5 | 15.3 | 43.8 |
| **RoGS-SLAM combined** | **2.3** | **2.2** | 2.7 | 10.4 |
| RoGS-SLAM mask-free | 34.9 | 45.9 | 3.1 | 9.3 |

Component necessity is **regime-dependent** — no single component is universally required.

## Installation

```bash
git clone --recursive git@github.com:BinGo620/RoGS-SLAM.git
cd RoGS-SLAM

conda create -n rogsslam python=3.8 -y
conda activate rogsslam

pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
pip install -r requirements.txt

pip install submodules/diff-gaussian-rasterization
pip install submodules/simple-knn
```

## Running

```bash
# RoGS-SLAM combined (full system)
python slam.py --config configs/rgbd/balloon_combined.yaml

# RoGS-SLAM mask-free (no semantic mask)
python slam.py --config configs/rgbd/balloon_maskfree.yaml

# GUI mode
python slam.py --config configs/rgbd/balloon_combined.yaml --gui
```

## Evaluation

```bash
# Build 18-sequence comparison table
python scripts/build_18seq_main_table.py

# ATE evaluation
evo_ape tum /path/to/ground.txt /path/to/estimated.txt -r full
```

## Project Structure

```
RoGS-SLAM/
├── slam.py                    # Main entry point
├── gaussian_splatting/        # 3DGS renderer & model
├── utils/
│   ├── reliability_signal.py  # Flow-consistency signal (L)
│   ├── deferred_commit.py     # Gaussian lifecycle (D)
│   ├── slam_frontend.py       # Tracking
│   ├── slam_backend.py        # Mapping
│   └── ...
├── configs/                   # Experiment configs
├── scripts/                   # Analysis scripts
├── tests/                     # Test suite
├── results/                   # Experiment results & evidence
└── submodules/                # diff-gaussian-rasterization, simple-knn
```

## Reproducibility

All experiments use 3 seeds per cell. Run directories and evidence are preserved in `results/`. Registry of all runs: `results/registry.csv`.

## Citation

```bibtex
@inproceedings{chen2027rogsslam,
  title     = {RoGS-SLAM: Robust Gaussian Splatting SLAM in Dynamic Environments via Reliability-Guided Weighting},
  author    = {Chen, Bin and Su, Jie and Zhang, Jing},
  booktitle = {Proceedings of the International Conference on MultiMedia Modeling (MMM)},
  year      = {2027}
}
```

## Acknowledgements

Built on [MonoGS](https://github.com/muskie82/MonoGS) by Matsuki et al. and [3D Gaussian Splatting](https://github.com/graphdeco-inria/gaussian-splatting) by Kerbl et al.
