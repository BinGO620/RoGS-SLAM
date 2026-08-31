"""exp39 Step B 装置门单测（B-0 进程清场 / B-1 显存清场）。

为什么这个文件存在：Step B 的首次派发在 frame ~300 双臂 OOM，原因是前一次崩溃
（ema_component_decomposition 的 shape bug）留下的 frontend/backend 进程仍持有
约 14 GB 显存，而 launcher 没有任何发批前清场检查。补上门之后必须证明门会拦——
exp33 判据 #11：一个从不失败的门不是门，所以每个门都喂一次已知坏值。

门只在 launcher 的 precheck 段，测试用 stub 的 pgrep / nvidia-smi 驱动它，
PY 指向 /bin/true 让"slam.py"瞬间返回，因此本文件零 GPU、零真实 run。
"""
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_exp39c_step_b.sh"
CFG_DIR = "configs/rgbd/experiments/exp39_mapping_soft"
CFG_NAMES = ("exp39c_ema_balloon.yaml", "exp39c_escrambled_balloon.yaml")


def _write_stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


@pytest.fixture
def harness(tmp_path):
    """A fake REPO with the two configs present and a stub bin/ on PATH."""
    repo = tmp_path / "repo"
    (repo / CFG_DIR).mkdir(parents=True)
    for name in CFG_NAMES:
        (repo / CFG_DIR / name).write_text("method: stub\n")

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()

    def run(n_slam: int, gpu_used: list[int]):
        # pgrep -fc <pat> prints the count; it exits 1 on zero matches, which is
        # exactly the case that made `|| echo 0` produce "0\n0" in exp37.
        _write_stub(
            stub_bin / "pgrep",
            f"""
            echo {n_slam}
            [ {n_slam} -gt 0 ] && exit 0 || exit 1
            """,
        )
        rows = "\n".join(f"{i}, {mib}" for i, mib in enumerate(gpu_used))
        _write_stub(stub_bin / "nvidia-smi", f"cat <<'EOF'\n{rows}\nEOF\n")

        env = dict(os.environ)
        env["PATH"] = f"{stub_bin}:{env['PATH']}"
        env["REPO"] = str(repo)
        env["PY"] = "/bin/true"          # "slam.py" returns immediately
        env["OUT"] = "results/runs/stepb_test"
        env["STAGGER"] = "0"             # 不在单测里等真实的 30s 错开
        proc = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env, capture_output=True, text=True, timeout=180,
        )
        done = (repo / env["OUT"] / "done.flag").read_text()
        return proc.returncode, done

    return run


class TestGateB0ProcessClearance:
    def test_aborts_when_slam_still_running(self, harness):
        """已知坏值：2 个 slam.py 在跑 —— 正是首发时的现场。"""
        rc, done = harness(n_slam=2, gpu_used=[159, 300])
        assert rc == 1
        assert "ABORT" in done and "2 个 slam.py" in done
        assert "START" not in done, "门没拦住，run 还是发出去了"

    def test_passes_when_no_slam_running(self, harness):
        rc, done = harness(n_slam=0, gpu_used=[159, 300])
        assert "GATE B-0/B-1 PASS" in done
        assert "ABORT" not in done

    def test_zero_match_does_not_break_integer_compare(self, harness):
        """pgrep 零匹配时退出码为 1；门不能因此报错或误判（exp37 门缺陷）。"""
        rc, done = harness(n_slam=0, gpu_used=[159, 300])
        assert "integer expression expected" not in done
        assert "ABORT" not in done


class TestGateB1MemoryClearance:
    def test_aborts_on_orphan_memory(self, harness):
        """已知坏值：14139 MiB 残留 —— 首发 OOM 时 GPU 0 的实测值。"""
        rc, done = harness(n_slam=0, gpu_used=[14139, 300])
        assert rc == 1
        assert "ABORT" in done and "GPU 0 残留 14139 MiB" in done
        assert "START" not in done

    def test_aborts_when_second_card_dirty(self, harness):
        """两张卡都要查，不能只查第一张。"""
        rc, done = harness(n_slam=0, gpu_used=[159, 9000])
        assert rc == 1
        assert "GPU 1 残留 9000 MiB" in done

    def test_boundary_just_under_threshold_passes(self, harness):
        rc, done = harness(n_slam=0, gpu_used=[1024, 1024])
        assert "GATE B-0/B-1 PASS" in done

    def test_boundary_just_over_threshold_aborts(self, harness):
        rc, done = harness(n_slam=0, gpu_used=[1025, 159])
        assert rc == 1
        assert "ABORT" in done


class TestLauncherWiring:
    def test_missing_config_aborts(self, harness, tmp_path):
        """config 缺失门（原有）仍然有效。"""
        repo_cfg = tmp_path / "repo" / CFG_DIR / CFG_NAMES[1]
        # 先跑一次建立 harness 的 repo，再删掉一个 config
        harness(n_slam=0, gpu_used=[159, 300])
        repo_cfg.unlink()
        rc, done = harness(n_slam=0, gpu_used=[159, 300])
        assert rc == 1
        assert "config 缺" in done

    def test_gates_run_before_any_launch(self):
        """门必须写在 run 段之前（exp33 判据 #9：门在判据前）。"""
        text = SCRIPT.read_text()
        assert text.index("GATE B-0/B-1 PASS") < text.index("START E-decomposed")
