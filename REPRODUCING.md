# Reproducing Paper 1 (RoGS-SLAM)

Step-by-step instructions to go from a fresh clone to the numbers in Table 1 of
*RoGS-SLAM: Robust Gaussian Splatting SLAM in Dynamic Environments via
Reliability-Guided Weighting* (MMM 2027).

Everything here runs from this repository alone. Nothing outside the repo is
required except a GPU, CUDA 11.8, and internet access for the datasets and
pretrained weights on first run.

---

## 0. Requirements

| Item | Requirement |
|---|---|
| OS | Linux x86_64 (tested on Ubuntu) |
| GPU | NVIDIA, ≥ 8 GB VRAM (paper numbers produced on RTX 3090) |
| Driver | supports CUDA 11.8 |
| Toolchain | CUDA 11.8 (`nvcc`), `gcc`/`g++`, `git` |
| Conda | Miniconda or Anaconda |
| Disk | ~15 GB for Bonn + TUM sequences |
| Python | provided by the conda environment (3.10) |

Check your driver supports 11.8 before starting:

```bash
nvcc --version          # expect release 11.8
nvidia-smi              # driver version and VRAM
```

---

## 1. Clone with submodules

The two CUDA extensions live in submodules pinned to the commits that produced
the paper's numbers. Clone recursively:

```bash
git clone --recursive https://github.com/BinGO620/RoGS-SLAM.git
cd RoGS-SLAM
```

If you already cloned without `--recursive`:

```bash
git submodule update --init --recursive
```

Verify the submodules are present and pinned:

```bash
git submodule status
# both lines must start with a commit hash (no leading '-')
```

---

## 2. Create the environment

```bash
conda env create -f environment.yaml
conda activate rogs-slam
```

The environment pins all versions, including `torch==2.1.0+cu118` and
`torchvision==0.16.0+cu118`. If the environment already exists and you need to
refresh it:

```bash
conda env update -f environment.yaml
```

---

## 3. Build the CUDA extensions

```bash
python -m pip install ./submodules/simple-knn ./submodules/diff-gaussian-rasterization
```

These are the only compiled components. If the build fails, the usual cause is
a CUDA toolkit / torch mismatch — confirm `nvcc --version` reports 11.8 and that
you are inside the `rogs-slam` environment.

Smoke-check the imports:

```bash
python -c "import torch, diff_gaussian_rasterization, simple_knn._C; print(torch.__version__, torch.cuda.is_available())"
```

`True` for `cuda.is_available()` is required.

---

## 4. Get the datasets

The paper uses Bonn RGB-D Dynamic and TUM RGB-D (18 sequences total).

```bash
bash scripts/download_bonn.sh
bash scripts/download_tum.sh
```

Both scripts support `--dry-run` and honor `DOWNLOAD_TOOL=aria2c|wget`,
`WGET_ARGS`, and `ARIA2_CONNECTIONS`.

If you already have the data, symlink instead of downloading:

```bash
ln -s /path/to/Bonn datasets/bonn
ln -s /path/to/TUM  datasets/tum
```

Paths in the configs are lowercase (`datasets/bonn`, `datasets/tum`); keep the
symlink targets consistent with that.

---

## 5. First-run smoke test (fast)

Before running the full table, confirm the pipeline works on a 40-frame slice:

```bash
python slam.py --config configs/experiments/combined_prune/balloon.yaml \
  --seed 0 --eval --max-frames 40
```

You are looking for: the run completes with `rc=0`, the guard never triggers,
and a result line is printed at the end. A 40-frame run is a pipeline check
only — it is **not** a paper number.

---

## 6. Full single-sequence run

```bash
python slam.py --config configs/experiments/combined_prune/balloon.yaml --seed 0 --eval
```

Replace `balloon` with any sequence under `configs/rgbd/{bonn,tum}/`. Each
sequence is run with seeds 0, 1, 2 for paper numbers (the config sets the seed
via `--seed`).

Outputs land under `results/<exp_id>/...`: `config.yml`, `tracking_raw.csv`,
`mapping_raw.csv`, `efficiency_raw.csv`, `per_frame_ape.csv`, `console.log`,
and `point_cloud/final/point_cloud.ply`.

---

## 7. Reproduce Table 1 and verify against the paper

The published table is stored in the repo:

- `results/evidence/table1_18seq_ate.csv`
- `results/evidence/table1_18seq_ate.md`

The archived per-run criterion artifacts for the P6 family (111 runs) are under
`results/runs/P6/`. Recompute the table from those CSVs and compare cell by cell:

```bash
python results/evidence/verify_table1.py
```

Expected outcome:

- `combined` and `maskfree` columns: **28/28 cells match** the published values
  (mean ± std, n = 3 seeds, within the table's rounding tolerance).
- `vanilla` (stock MonoGS) and `rgd` (comparison method) columns:
  reported as **NO-RUN-IN-REPO**. Their run artifacts are not part of this
  archive; the numbers in the evidence CSV are authoritative and the script
  says so rather than silently passing.

A non-zero exit code means at least one cell mismatched — inspect the printed
diff.

---

## 8. Run the test suite

```bash
pytest tests/test_config_valid.py -q
```

This checks that every config parses and that the method defaults are as
described in the paper.

---

## Reproducibility notes

- **Single-variable comparison.** The method components (K unified keyframe
  coverage, R robust reweighting, L reliability signal, D lineage lifecycle,
  plus optional semantic mask) are all enabled by default in
  `configs/experiments/combined_prune/method.yaml`. Disable them one at a time
  to reproduce the ablation — do not change more than one at a time.
- **Determinism.** Absolute ATE is the primary criterion; rendering metrics are
  secondary and the two are anti-correlated in this project. Same-config
  same-seed reruns on the instrumented setup (single-threaded dataset and
  reliability paths plus deterministic rasterizer backward) are bitwise
  identical for trajectories; wall time and peak memory are not.
- **What is not in this repo.** The `vanilla` and `rgd` run directories are
  absent by design (see `PROVENANCE.md`). Everything else needed for the
  published numbers is present.
- **No hidden dependency on other repos.** This repository does not read from
  the RoGS-Map or RoGS-Densify checkouts. They are separate papers sharing an
  upstream code base; `diff -r` between their `utils/` trees shows the
  mechanism differences.

If a step fails, open an issue with the failing command, the full error text,
`nvidia-smi`, `nvcc --version`, and `conda list | grep -E "torch|numpy"`.
