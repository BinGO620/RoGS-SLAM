#!/usr/bin/env bash
# setup_env.sh — 一键环境：conda env + CUDA 扩展编译 + 数据/权重就位
# 依赖：conda、CUDA 11.8 工具链（编译 diff-gaussian-rasterization / simple-knn）
set -euo pipefail
cd "$(dirname "$0")"

# 1) 子模块源码（两个 CUDA 扩展，已 pin 到与论文数字一致的确切 commit）
git submodule update --init --recursive

# 2) conda 环境
conda env create -f environment.yaml || conda env update -f environment.yaml
PY=$(conda info --base)/envs/rogs-slam/bin/python

# 3) 编译 CUDA 扩展（environment.yaml 里的 pip 条目在首次 create 时已编译；
#    env 已存在时手动补一次，幂等）
$PY -m pip install ./submodules/simple-knn ./submodules/diff-gaussian-rasterization

# 4) 数据集：Bonn+TUM（论文1 用 18 序列）
#    或者把已有数据集软链进来：ln -s /path/to/Bonn datasets/bonn
if [ ! -e datasets/bonn ]; then
    mkdir -p datasets
    bash scripts/download_bonn.sh || \
        echo "[warn] Bonn 下载未完成，可手动执行 scripts/download_bonn.sh"
fi
if [ ! -e datasets/tum ]; then
    bash scripts/download_tum.sh || \
        echo "[warn] TUM 下载未完成，可手动执行 scripts/download_tum.sh"
fi

# 5) 预训练权重（MaskRCNN 经 torchvision 自动下载；RAFT 经 torch.hub）
#    如需离线，设置 TORCH_HOME 指向缓存目录。
echo "setup 完成。冒烟验证："
echo "  $PY slam.py --config configs/experiments/combined_prune/balloon.yaml --seed 0 --eval --max-frames 40"
