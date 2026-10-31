# RoGS-SLAM

**动态场景 3D Gaussian Splatting SLAM**（研究内容一 / MMM 2027 已录用，camera-ready 14 页）。

基于 [MonoGS](https://github.com/muskie82/MonoGS) 的动态场景 3DGS SLAM。方法用**光流一致性
可靠性信号**加权动态观测，而非依赖语义分割直接剔除：四个组件——
K 统一关键帧覆盖（`DynamicKeyframe`）、R 鲁棒重加权（`RobustTracking`, Huber IRLS）、
L 可靠性信号（`ReliabilitySignal`，观测流 vs 刚体流残差 → Cauchy 只降权）、
D lineage 生命周期（`DeferredCommit`）+ 可选语义掩码（`SemanticMask`）。
全部在 `configs/experiments/combined_prune/method.yaml` 中默认开启。

## Installation

```bash
git clone --recursive https://github.com/BinGO620/RoGS-SLAM.git
cd RoGS-SLAM
./setup_env.sh          # conda env + 两个 CUDA 扩展（pin SHA）+ Bonn/TUM 数据集
conda activate rogs-slam
```

## Usage

```bash
# 单序列（论文1 主实验口径，BONN/TUM 18 序列）
python slam.py --config configs/experiments/combined_prune/balloon.yaml --seed 0 --eval

# 重算 Table 1（18 序列 × 4 方法 ATE）并与已发表数字逐格核对
python results/evidence/verify_table1.py

# 门禁
pytest tests/test_config_valid.py -q
```

## Results（Table 1 复现）

`results/evidence/table1_18seq_ate.{csv,md}` 为已发表数字（4 方法 × 18 序列）。
`results/runs/P6/` 入库了 P6 家族 8 个子族的判据小件（config.yml / tracking_raw.csv /
mapping_raw.csv / efficiency_raw.csv / summary+stats_final.json / console.log /
per_frame_ape.csv，111 个 run）。`verify_table1.py` 从这些 CSV 重算并与表逐格核对：

- **combined 与 maskfree 两列 28 格逐位 MATCH**（mean±std 与表完全一致）；
- vanilla（MonoGS 原版）与 rgd（对照方法）两列的 run 工件不在归档中，数字以
  evidence CSV 为准（逐格标注 NO-RUN-IN-REPO，如实不掩饰）。

## Project Structure

```
slam.py / utils/ / gaussian_splatting/ / gui/   # 运行主干（裁剪清单见 PROVENANCE.md）
configs/rgbd/{bonn,tum}/                        # 18+ 序列数据配置（BONN 动态 + TUM）
configs/experiments/combined_prune/             # 方法主干（method.yaml）+ control 臂
results/evidence/                               # Table 1 / 因子实验 / cuesplit 判决
results/runs/P6/                                # P6 家族判据小件（tar 归档提取）
submodules/                                     # diff-gaussian-rasterization-w-pose + simple-knn
```

## Provenance

本仓库由 monogs-ours@`31b0f0367` 按依赖闭包裁剪重建；复制清单、删改明细、验证记录见
[PROVENANCE.md](PROVENANCE.md)。本仓库 = 论文1 的最小复现集；论文2 见 RoGS-Map，
论文3 见 RoGS-Densify（三仓主干同源，`diff -r utils/` = 论文间机制差异）。

## Acknowledgements

Built on [MonoGS](https://github.com/muskie82/MonoGS) and
[3D Gaussian Splatting](https://github.com/graphdeco-inria/gaussian-splatting).
