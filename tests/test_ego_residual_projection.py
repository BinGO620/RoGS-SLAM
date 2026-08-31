"""ego-residual projection (`ego_residual_projection` / `flow_jacobian_se3`).

修的缺陷见 results/evidence/eflow_pose_error_defect.md：`rigid_flow` 的自运动预测
用的是**正在被优化的位姿**，其误差落进残差里，在近静态帧被 MAD 归一化放大成
"动态"证据。修法 = 把残差里"任何相机位姿误差都能解释"的那部分（6-DoF 子空间）
鲁棒拟合掉，只把解释不了的送进异常度。

这些测试要钉死的四件事：
  1. Jacobian 是对的（与 rigid_flow 的有限差分一致）——否则整个投影是在减一个错东西；
  2. 纯位姿误差被吃掉，真实独立运动留得下来（机制本身）；
  3. 三道护栏在该开火时开火（少像素 / 病态 / 主导 mover），且失败时**原样返回**
     （fail-safe = 现状，绝不留半修复）；
  4. 默认关闭时与历史臂**逐字节一致**（不惊动任何已有实验臂）。
"""
import numpy as np
import pytest
import torch

from utils.reliability_signal import (
    ego_residual_projection,
    flow_anomaly,
    flow_jacobian_se3,
    rigid_flow,
)


def _so3(axis, ang):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * (K @ K)


def _scene(h=48, w=64, seed=0):
    """深度带明显的远近层次 —— 平移/旋转在几何上可分，否则 6-DoF 本就不可辨识。"""
    g = torch.Generator().manual_seed(seed)
    base = torch.linspace(0.6, 4.0, w).view(1, w).expand(h, w).clone()
    depth = base + 0.05 * torch.rand(h, w, generator=g)
    return depth, 60.0, 60.0, w / 2.0, h / 2.0


def test_jacobian_matches_finite_difference_of_rigid_flow():
    """J 必须真的是 d(rigid_flow)/d(xi)（左扰动约定 T' = exp(xi^) T）。

    用**中心**差分：rigid_flow 内部转 float32，前向差分在 eps=1e-5 时
    f1-f0 会灾难性抵消（f~90px，float32 分辨率~1e-5，差值~9e-4 => 相对误差~1%）。
    中心差分 + eps=1e-3 把截断误差降到 O(eps^2)、抵消误差降到 ~1e-4 相对量级。
    """
    depth, fx, fy, cx, cy = _scene()
    R = torch.from_numpy(_so3([0.3, 1.0, -0.2], 0.05)).float()
    t = torch.tensor([0.02, -0.01, 0.03])
    J, valid = flow_jacobian_se3(depth, fx, fy, cx, cy, R, t)
    _, v0 = rigid_flow(depth, fx, fy, cx, cy, R, t)
    m = valid & v0

    def perturbed(xi):
        nu, om = np.asarray(xi[:3], float), np.asarray(xi[3:], float)
        ang = float(np.linalg.norm(om))
        dR = torch.from_numpy(_so3(om if ang > 0 else [1.0, 0.0, 0.0], ang)).float()
        return rigid_flow(depth, fx, fy, cx, cy,
                          dR @ R, dR @ t + torch.from_numpy(nu).float())

    eps = 1e-3
    for k in range(6):
        xi = np.zeros(6)
        xi[k] = eps
        fp, vp = perturbed(xi)
        xi[k] = -eps
        fm, vm = perturbed(xi)
        mm = m & vp & vm
        fd = (fp - fm)[mm] / (2 * eps)
        an = J[mm][:, :, k]
        scale = an.abs().max().clamp_min(1e-6)
        rel = (fd - an).abs().max() / scale
        assert rel < 5e-3, (
            f"J 第{k}列与中心差分不符: 相对误差={float(rel):.2e} "
            f"(max|Δ|={float((fd-an).abs().max()):.4f}, 列尺度={float(scale):.2f})")


def test_pure_pose_error_is_removed():
    """纯位姿误差 -> 残差应被压到接近 0（这正是缺陷的来源）。"""
    depth, fx, fy, cx, cy = _scene()
    R = torch.from_numpy(_so3([0, 1, 0], 0.02)).float()
    t = torch.tensor([0.01, 0.0, 0.02])
    f_true, v_true = rigid_flow(depth, fx, fy, cx, cy, R, t)
    # 估计位姿差一点点（2cm 平移）——探针实测这已让 e_flow 涨 60%+
    t_err = t + torch.tensor([0.02, 0.0, 0.0])
    f_pred, v_pred = rigid_flow(depth, fx, fy, cx, cy, R, t_err)
    J, v_j = flow_jacobian_se3(depth, fx, fy, cx, cy, R, t_err)
    valid = v_true & v_pred & v_j

    res = f_true - f_pred
    before = res[valid].norm(dim=-1).median()
    out, st = ego_residual_projection(res, J, valid)
    after = out[valid].norm(dim=-1).median()

    assert st["ego_fit_applied"] == 1, st
    assert after < before * 0.1, f"位姿误差没被吃掉: {before:.3f} -> {after:.3f}"


def test_real_mover_survives_the_projection():
    """真实独立运动不落在 6-DoF 子空间里，必须留得下来 —— 否则修法把信号一起修没了。"""
    depth, fx, fy, cx, cy = _scene()
    R = torch.from_numpy(_so3([0, 1, 0], 0.02)).float()
    t = torch.tensor([0.01, 0.0, 0.02])
    f_true, v_true = rigid_flow(depth, fx, fy, cx, cy, R, t)
    t_err = t + torch.tensor([0.02, 0.0, 0.0])
    f_pred, v_pred = rigid_flow(depth, fx, fy, cx, cy, R, t_err)
    J, v_j = flow_jacobian_se3(depth, fx, fy, cx, cy, R, t_err)
    valid = v_true & v_pred & v_j

    # 一个占 ~9% 画面的 mover（少数派），额外平移流
    mover = torch.zeros_like(valid)
    mover[10:30, 8:22] = True
    obs = f_true.clone()
    obs[mover] += torch.tensor([6.0, -3.0])

    res = obs - f_pred
    out, st = ego_residual_projection(res, J, valid)
    assert st["ego_fit_applied"] == 1, st

    mm = valid & mover
    ms = valid & ~mover
    mover_mag = out[mm].norm(dim=-1).median()
    static_mag = out[ms].norm(dim=-1).median()
    assert mover_mag > 5.0 * static_mag, (
        f"mover 被一起投影掉了: mover={mover_mag:.2f} static={static_mag:.2f}")
    assert mover_mag > 3.0, f"mover 幅度被压得太狠: {mover_mag:.2f}"


def test_dominant_mover_is_rejected_not_absorbed():
    """主导 mover 若捕获拟合 -> 必须拒绝并原样返回, 不能悄悄吸收。

    这是本项目已知的 majority-dominance 失败模式，不能只靠鲁棒损失兜底。
    诚实边界：占满画面且刚性运动的 mover 在单帧对上与相机位姿误差**原理上不可分**
    （它的流确实落在 ego 子空间里）。护栏只保证退回原状，不声称能解这个歧义。
    """
    depth, fx, fy, cx, cy = _scene()
    R = torch.eye(3)
    t = torch.tensor([0.0, 0.0, 0.0])
    f_pred, v_pred = rigid_flow(depth, fx, fy, cx, cy, R, t)
    J, v_j = flow_jacobian_se3(depth, fx, fy, cx, cy, R, t)
    valid = v_pred & v_j

    res = torch.zeros_like(f_pred)
    res[:, :] = torch.tensor([30.0, 20.0])  # 全画面一致的大位移
    out, st = ego_residual_projection(res, J, valid)
    assert st["ego_fit_applied"] == 0
    assert st["ego_reject"] in ("corr_too_large", "not_ego_explainable"), st
    assert torch.equal(out, res), "拒绝时必须原样返回残差（fail-safe = 现状）"


def test_default_max_corr_px_admits_realistic_pose_errors():
    """护栏必须放行**真实量级**的位姿误差修正，否则等于没修。

    探针实测(f3_st_hf, scripts/probe_eflow_pose_sensitivity.py)：median|f_static|
    =4.95px，1-5cm 位姿误差的拟合修正是 2.8-10.5px。早先手拍的 max_corr_px=4.0
    会把这些帧全拒掉 —— 默认值必须由数据定，这条测试就是钉住这一点。
    """
    depth, fx, fy, cx, cy = _scene()
    R = torch.from_numpy(_so3([0, 1, 0], 0.02)).float()
    t = torch.tensor([0.01, 0.0, 0.02])
    f_true, v_true = rigid_flow(depth, fx, fy, cx, cy, R, t)
    for dt in (0.01, 0.02, 0.05):
        t_err = t + torch.tensor([dt, 0.0, 0.0])
        f_pred, v_pred = rigid_flow(depth, fx, fy, cx, cy, R, t_err)
        J, v_j = flow_jacobian_se3(depth, fx, fy, cx, cy, R, t_err)
        valid = v_true & v_pred & v_j
        out, st = ego_residual_projection(f_true - f_pred, J, valid)  # 全默认参数
        assert st["ego_fit_applied"] == 1, (
            f"δt={dt}m 的真实位姿误差被护栏拒了: {st}")


def test_non_ego_explainable_residual_is_rejected():
    """残差不是任何单一 6-DoF 能解释的 -> 必须拒绝（减掉它只会注入误差）。"""
    depth, fx, fy, cx, cy = _scene()
    R, t = torch.eye(3), torch.zeros(3)
    f_pred, v = rigid_flow(depth, fx, fy, cx, cy, R, t)
    J, vj = flow_jacobian_se3(depth, fx, fy, cx, cy, R, t)
    valid = v & vj
    g = torch.Generator().manual_seed(11)
    # 绝大多数像素是互不相干的大幅随机流：任何单一 6-DoF 都解释不了
    res = 40.0 * torch.randn(*f_pred.shape, generator=g)
    out, st = ego_residual_projection(res, J, valid, max_corr_px=1e9)
    assert st["ego_fit_applied"] == 0, st
    assert st["ego_reject"] == "not_ego_explainable", st
    assert torch.equal(out, res)


def test_too_few_pixels_rejects_and_returns_unchanged():
    depth, fx, fy, cx, cy = _scene(h=8, w=8)
    R, t = torch.eye(3), torch.zeros(3)
    f, v = rigid_flow(depth, fx, fy, cx, cy, R, t)
    J, vj = flow_jacobian_se3(depth, fx, fy, cx, cy, R, t)
    res = torch.randn_like(f)
    out, st = ego_residual_projection(res, J, v & vj, min_valid=512)
    assert st["ego_fit_applied"] == 0 and st["ego_reject"] == "min_valid"
    assert torch.equal(out, res)


def test_ill_conditioned_geometry_rejects_and_returns_unchanged():
    """常深度平面 + 窄视场 -> 平移与旋转近似不可分，必须拒绝而不是解出个大数。"""
    h, w = 48, 64
    depth = torch.full((h, w), 2.0)
    fx = fy = 5000.0            # 极长焦 => 视场极窄
    cx, cy = w / 2.0, h / 2.0
    R, t = torch.eye(3), torch.zeros(3)
    f, v = rigid_flow(depth, fx, fy, cx, cy, R, t)
    J, vj = flow_jacobian_se3(depth, fx, fy, cx, cy, R, t)
    res = torch.randn_like(f) * 0.1
    out, st = ego_residual_projection(res, J, v & vj, cond_max=1e6)
    assert st["ego_fit_applied"] == 0 and st["ego_reject"] == "ill_conditioned", st
    assert torch.equal(out, res)


def test_default_off_is_byte_identical_to_historical_arm():
    """不传 ego_jac 时，flow_anomaly 必须与历史实现逐字节一致。"""
    depth, fx, fy, cx, cy = _scene(seed=3)
    R = torch.from_numpy(_so3([0.2, -0.4, 1.0], 0.03)).float()
    t = torch.tensor([0.015, 0.004, -0.02])
    f_static, v = rigid_flow(depth, fx, fy, cx, cy, R, t)
    g = torch.Generator().manual_seed(7)
    f_obs = f_static + 0.4 * torch.randn(*f_static.shape, generator=g)

    got = flow_anomaly(f_obs, f_static, v, scale_floor=2.0)
    # 历史实现（本次改动前的原样）
    diff = (f_obs.float() - f_static.float())
    delta = (diff ** 2).sum(dim=-1).clamp_min(0.0).sqrt()
    from utils.reliability_signal import robust_anomaly
    want = robust_anomaly(delta, v, scale_floor=2.0)
    assert torch.equal(got, want), "默认关闭路径被改动了"


def test_stats_out_records_provenance():
    """开启时必须留痕：run 要能自证跑的是哪个机制。"""
    depth, fx, fy, cx, cy = _scene(seed=5)
    R = torch.from_numpy(_so3([0, 1, 0], 0.02)).float()
    t = torch.tensor([0.01, 0.0, 0.02])
    f_static, v = rigid_flow(depth, fx, fy, cx, cy, R, t)
    J, vj = flow_jacobian_se3(depth, fx, fy, cx, cy, R, t)
    f_obs = f_static + 0.2
    out = {}
    flow_anomaly(f_obs, f_static, v & vj, scale_floor=2.0, ego_jac=J, ego_stats_out=out)
    assert set(out) >= {"ego_fit_applied", "ego_corr_px", "ego_dxi_norm", "ego_reject"}
