import os
import random
import re
import sys
import time
import atexit
import threading
from argparse import ArgumentParser
from datetime import datetime
from queue import Empty
from typing import Any, cast

import numpy as np
import torch
import torch.multiprocessing as mp
import yaml
from munch import Munch
from munch import munchify

import wandb
from gaussian_splatting.scene.gaussian_model import GaussianModel
from gaussian_splatting.utils.system_utils import mkdir_p
from gui import gui_utils
from utils.config_utils import load_config
from utils.dataset import load_dataset
from utils.eval_utils import (
    eval_ate,
    eval_final_mapping_raw,
    eval_rendering,
    eval_static_background_raw,
    save_efficiency_raw,
    save_final_tracking_raw,
    save_gaussians,
    save_mapping_raw_from_official_eval,
)
from utils.logging_utils import Log
from utils.gpu_memory_monitor import ProcessTreeGpuMemoryMonitor
from utils.multiprocessing_utils import FakeQueue, release_cuda_ipc_cache
from utils.slam_backend import BackEnd
from utils.slam_frontend import FrontEnd
from utils.dba_lite import (
    dba_lite_enabled,
    dba_lite_oracle_enabled,
    run_dba_oracle,
    run_dba_v0,
)


BACKEND_TIMING_TIMEOUT_SECONDS = 60.0
BACKEND_BARRIER_TIMEOUT_SECONDS = 60.0
BACKEND_STOP_TIMEOUT_SECONDS = 10.0


def _stop_process(
    process, queue=None, message=None, timeout=BACKEND_STOP_TIMEOUT_SECONDS
):
    """Ask a worker to exit, then terminate it if it does not respond."""
    if process is None:
        return
    try:
        if process.is_alive() and queue is not None and message is not None:
            queue.put([message])
    except (AssertionError, OSError, EOFError, ValueError):
        pass
    try:
        if process.is_alive():
            process.join(timeout=timeout)
        if process.is_alive():
            process.terminate()
            process.join(timeout=timeout)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(timeout=timeout)
    except (AssertionError, OSError, EOFError, ValueError):
        pass


def _stop_gui_process(process, finish_queue=None, finish=False):
    if process is None:
        return
    if finish and finish_queue is not None:
        try:
            finish_queue.put(gui_utils.GaussianPacket(finish=True))
        except (OSError, EOFError, ValueError):
            pass
    _stop_process(process)


def color_refinement_iterations(config):
    """Read the optional refinement budget while keeping the MonoGS default."""
    value = config.get("Training", {}).get("color_refinement_iterations", 26000)
    value = int(value)
    if value < 0:
        raise ValueError("Training.color_refinement_iterations must be >= 0")
    return value


def _wait_for_backend_timing(backend_process, timing_path, timeout_seconds):
    started_at = time.monotonic()
    while True:
        if os.path.exists(timing_path):
            return
        if not backend_process.is_alive():
            raise RuntimeError(
                "Backend exited before writing timing data "
                f"(exit code {backend_process.exitcode})"
            )
        if time.monotonic() - started_at >= timeout_seconds:
            raise TimeoutError(
                f"Backend did not write timing data within {timeout_seconds:.0f}s: "
                f"{timing_path}"
            )
        time.sleep(0.05)


def _wait_for_backend_barrier(
    frontend,
    frontend_queue,
    backend_process,
    barrier_tag,
    timeout_seconds,
):
    """Consume every backend snapshot queued before a CPU-only barrier."""

    started_at = time.monotonic()
    while True:
        if not backend_process.is_alive():
            raise RuntimeError(
                "Backend exited before the queue barrier "
                f"(exit code {backend_process.exitcode})"
            )
        elapsed = time.monotonic() - started_at
        if elapsed >= timeout_seconds:
            raise TimeoutError(
                f"Backend queue barrier timed out after {timeout_seconds:.0f}s: "
                f"{barrier_tag}"
            )
        try:
            data = frontend_queue.get(timeout=min(0.1, timeout_seconds - elapsed))
        except Empty:
            continue
        if not data:
            continue
        tag = data[0]
        if tag == "backend_error":
            raise RuntimeError(f"Backend worker failed: {data[1]}")
        if tag in {"sync_backend", "keyframe", "init"}:
            frontend.sync_backend(data)
            continue
        if tag == barrier_tag:
            return
        raise RuntimeError(f"Unexpected backend message before barrier: {tag}")


def get_sequence_id(config, config_path):
    sequence = config["Dataset"].get("sequence")
    if sequence:
        return str(sequence)
    return os.path.splitext(os.path.basename(config_path))[0]


def get_dataset_result_dir(config):
    dataset_path = config["Dataset"]["dataset_path"].rstrip("/")
    path_parts = dataset_path.split("/")
    if len(path_parts) >= 3:
        return path_parts[-3] + "_" + path_parts[-2]
    return config["Dataset"]["type"].lower()


def sanitize_experiment_name(name):
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    if not safe_name:
        raise ValueError(f"Invalid experiment name: {name!r}")
    return safe_name


def resolve_results_root(config, experiment_name="", results_root=""):
    if results_root:
        return results_root
    if experiment_name:
        return f"results/runs/{sanitize_experiment_name(experiment_name)}"
    return config["Results"]["save_dir"]


def apply_results_root(config, results_root, tables_dir=None):
    config["Results"]["save_dir"] = results_root
    tables_dir = tables_dir or os.path.join(results_root, "tables")
    raw_paths = {
        "tracking_raw_path": "tracking_raw.csv",
        "mapping_raw_path": "mapping_raw.csv",
        "efficiency_raw_path": "efficiency_raw.csv",
    }
    for key, filename in raw_paths.items():
        if key in config["Results"]:
            config["Results"][key] = os.path.join(tables_dir, filename)


def start_console_log(save_dir):
    if save_dir is None:
        return None
    log_path = os.path.join(save_dir, "console.log")
    log_fd = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
    stdout_fd = os.dup(1)
    stderr_fd = os.dup(2)
    read_fd, write_fd = os.pipe()
    os.dup2(write_fd, 1)
    os.dup2(write_fd, 2)
    os.close(write_fd)

    def strip_ansi(data):
        text = data.decode("utf-8", errors="replace")
        result = []
        idx = 0
        while idx < len(text):
            if text[idx] == "\x1b" and idx + 1 < len(text) and text[idx + 1] == "[":
                idx += 2
                while idx < len(text) and not ("@" <= text[idx] <= "~"):
                    idx += 1
                idx += 1
                continue
            result.append(text[idx])
            idx += 1
        return "".join(result).encode("utf-8")

    def copy_console_output():
        while True:
            data = os.read(read_fd, 4096)
            if not data:
                break
            os.write(stdout_fd, data)
            os.write(log_fd, strip_ansi(data))

    thread = threading.Thread(target=copy_console_output, daemon=True)
    thread.start()

    def close_console_log():
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        thread.join(timeout=1.0)
        for fd in (read_fd, stdout_fd, stderr_fd, log_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    atexit.register(close_console_log)
    return log_path


class SLAM:
    def __init__(self, config, save_dir=None):
        SLAM._active_instance = self
        self._backend_process = None
        self._gui_process = None
        self._online_memory_monitor = None
        self._refinement_monitor = None
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        cuda_stream = torch.cuda.current_stream()

        start.record(cuda_stream)

        self.config = config
        self.save_dir = save_dir
        model_params = cast(Munch, munchify(config["model_params"]))
        opt_params = cast(Munch, munchify(config["opt_params"]))
        pipeline_params = cast(Munch, munchify(config["pipeline_params"]))
        self.model_params, self.opt_params, self.pipeline_params = (
            model_params,
            opt_params,
            pipeline_params,
        )

        self.live_mode = self.config["Dataset"]["type"] == "realsense"
        self.monocular = self.config["Dataset"]["sensor_type"] == "monocular"
        self.use_spherical_harmonics = self.config["Training"]["spherical_harmonics"]
        self.use_gui = self.config["Results"]["use_gui"]
        if self.live_mode:
            self.use_gui = True
        self.eval_rendering = self.config["Results"]["eval_rendering"]

        model_params.sh_degree = 3 if self.use_spherical_harmonics else 0

        self.gaussians = GaussianModel(model_params.sh_degree, config=self.config)
        self.gaussians.init_lr(6.0)
        self.dataset = load_dataset(
            model_params, model_params.source_path, config=config
        )

        self.gaussians.training_setup(opt_params)
        bg_color = [0, 0, 0]
        self.background = torch.tensor(bg_color, dtype=torch.float32, device="cuda")

        frontend_queue = mp.Queue()
        backend_queue = mp.Queue()
        self._backend_queue = backend_queue

        q_main2vis = mp.Queue() if self.use_gui else FakeQueue()
        q_vis2main = mp.Queue() if self.use_gui else FakeQueue()
        self._q_main2vis = q_main2vis

        self.config["Results"]["save_dir"] = save_dir
        self.config["Training"]["monocular"] = self.monocular

        self.frontend = FrontEnd(self.config)
        self.backend = BackEnd(self.config)
        frontend = cast(Any, self.frontend)
        backend = cast(Any, self.backend)

        frontend.dataset = self.dataset
        frontend.background = self.background
        frontend.pipeline_params = self.pipeline_params
        frontend.frontend_queue = frontend_queue
        frontend.backend_queue = backend_queue
        frontend.q_main2vis = q_main2vis
        frontend.q_vis2main = q_vis2main
        self.frontend.set_hyperparams()

        backend.gaussians = self.gaussians
        backend.background = self.background
        backend.cameras_extent = 6.0
        backend.pipeline_params = self.pipeline_params
        backend.opt_params = self.opt_params
        backend.frontend_queue = frontend_queue
        backend.backend_queue = backend_queue
        backend.live_mode = self.live_mode

        self.backend.set_hyperparams()

        self.params_gui = gui_utils.ParamsGUI(
            pipe=self.pipeline_params,
            background=self.background,
            gaussians=self.gaussians,
            q_main2vis=q_main2vis,
            q_vis2main=q_vis2main,
        )

        backend_process = mp.Process(target=self.backend.run)
        self._backend_process = backend_process
        gui_process = None
        if self.use_gui:
            from gui import slam_gui

            gui_process = mp.Process(target=slam_gui.run, args=(self.params_gui,))
            self._gui_process = gui_process
            gui_process.start()
            time.sleep(5)

        online_started_at = time.perf_counter()
        online_memory_monitor = ProcessTreeGpuMemoryMonitor().start()
        self._online_memory_monitor = online_memory_monitor
        backend_process.start()
        self.frontend.backend_process = backend_process
        try:
            self.frontend.run()
            backend_queue.put(["pause"])
            backend_queue.put(["save_timing"])
            backend_timing_path = (
                os.path.join(self.save_dir, "backend_timing.json")
                if self.save_dir is not None
                else None
            )
            if backend_timing_path is not None:
                _wait_for_backend_timing(
                    backend_process,
                    backend_timing_path,
                    BACKEND_TIMING_TIMEOUT_SECONDS,
                )
            _wait_for_backend_barrier(
                self.frontend,
                frontend_queue,
                backend_process,
                "timing_saved",
                BACKEND_BARRIER_TIMEOUT_SECONDS,
            )
        except BaseException:
            self._cleanup_workers()
            raise

        end.record(cuda_stream)
        torch.cuda.synchronize()
        online_time_s = time.perf_counter() - online_started_at
        online_memory = online_memory_monitor.stop()
        if online_memory["error"]:
            Log(f"Online GPU memory monitor unavailable: {online_memory['error']}")
        # empty the frontend queue
        N_frames = len(self.frontend.cameras)
        FPS = N_frames / online_time_s
        Log("Online SLAM time", online_time_s, tag="Eval")
        Log("Online SLAM FPS", FPS, tag="Eval")
        total_time_s = online_time_s
        self.gaussians = self.frontend.gaussians
        online_num_gaussians = int(self.gaussians.get_xyz.shape[0])
        refinement_wall_time_s = None
        refinement_peak_gpu_memory_gb = "N/A"

        # Numerical safety (always-on): drop any Gaussian with a non-finite (Inf/NaN)
        # parameter before final save/eval. Inf-scale Gaussians rasterize to NaN pixels
        # and poison the before_opt PSNR/SSIM/LPIPS (np.mean over eval frames -> NaN);
        # they never represent valid geometry. No-op on a healthy map. (The after_opt
        # map is separately cleaned inside the backend before color_refinement.)
        try:
            n_bad = self.gaussians.prune_nonfinite_points()
            if n_bad:
                Log(f"Pruned {n_bad} non-finite Gaussians before final eval/save")
        except Exception as exc:  # never let a safety prune break a finished run
            Log(f"prune_nonfinite_points (frontend) failed: {exc}")

        # Step 2 (default-off): offline final-map pose refinement of non-keyframes
        # against the frozen dynamic-clean map. Must run before save_final_tracking_raw
        # so the reported full-trajectory ATE reflects the refined poses.
        self.frontend.final_pose_refinement()

        # P2b (doc 14): offline KF-only geometric pose-graph BA. Writes optimized KF
        # poses into frontend.cameras BEFORE save_final_tracking_raw so the reported
        # ATE reflects them. Gauge-fixes KF0; held-out validation edges guard vs
        # train-edge overfit. Default-off (DBALite.enabled).
        # DBA-lite GT-oracle falsifier (default-off, read-only): does the masked
        # geometric objective even prefer GT poses? Runs on the online poses BEFORE
        # any v0 modification. Decides whether a learning-free geometric BA can help.
        if dba_lite_oracle_enabled(self.config):
            try:
                run_dba_oracle(
                    self.frontend.cameras,
                    self.frontend.kf_indices,
                    self.dataset,
                    self.config,
                )
            except Exception as exc:
                Log(f"DBA-lite oracle failed: {exc}")

        if dba_lite_enabled(self.config):
            try:
                run_dba_v0(
                    self.frontend.cameras,
                    self.frontend.kf_indices,
                    self.dataset,
                    self.config,
                )
            except Exception as exc:
                Log(f"DBA-lite v0 failed: {exc}")

        if self.config["Results"].get("save_final_tracking", True):
            save_final_tracking_raw(
                self.frontend.cameras,
                self.frontend.kf_indices,
                self.save_dir,
                self.config,
                monocular=self.monocular,
            )
        if self.config["Results"].get("save_final_gaussians", True):
            save_gaussians(self.gaussians, self.save_dir, "final", final=True)
        if self.config["Results"].get("save_final_mapping", False):
            eval_final_mapping_raw(
                self.frontend.cameras,
                self.gaussians,
                self.dataset,
                self.save_dir,
                self.pipeline_params,
                self.background,
                self.config,
            )
        if self.eval_rendering:
            kf_indices = self.frontend.kf_indices
            ATE = eval_ate(
                self.frontend.cameras,
                self.frontend.kf_indices,
                self.save_dir,
                0,
                final=True,
                monocular=self.monocular,
            )

            rendering_before = eval_rendering(
                self.frontend.cameras,
                self.gaussians,
                self.dataset,
                self.save_dir,
                self.pipeline_params,
                self.background,
                kf_indices=kf_indices,
                iteration="before_opt",
            )
            columns = ["tag", "psnr", "ssim", "lpips", "RMSE ATE", "FPS"]
            metrics_table = wandb.Table(columns=columns)
            metrics_table.add_data(
                "Before",
                rendering_before["mean_psnr"],
                rendering_before["mean_ssim"],
                rendering_before["mean_lpips"],
                ATE,
                FPS,
            )

            # re-used the frontend queue to retrive the gaussians from the backend.
            while not frontend_queue.empty():
                frontend_queue.get()
            refinement_started_at = time.perf_counter()
            refinement_monitor = ProcessTreeGpuMemoryMonitor().start()
            self._refinement_monitor = refinement_monitor
            try:
                backend_queue.put(["color_refinement"])
                while True:
                    if not backend_process.is_alive():
                        raise RuntimeError(
                            "Backend exited during color refinement "
                            f"(exit code {backend_process.exitcode})"
                        )
                    if frontend_queue.empty():
                        time.sleep(0.01)
                        continue
                    data = frontend_queue.get()
                    if data[0] == "backend_error":
                        raise RuntimeError(f"Backend worker failed: {data[1]}")
                    if data[0] == "sync_backend" and frontend_queue.empty():
                        self.frontend.sync_backend(data)
                        self.gaussians = self.frontend.gaussians
                        break
            except BaseException:
                self._cleanup_workers()
                raise
            refinement_wall_time_s = time.perf_counter() - refinement_started_at
            refinement_memory = refinement_monitor.stop()
            refinement_peak_gpu_memory_gb = refinement_memory["peak_gpu_memory_gb"]

            rendering_after = eval_rendering(
                self.frontend.cameras,
                self.gaussians,
                self.dataset,
                self.save_dir,
                self.pipeline_params,
                self.background,
                kf_indices=kf_indices,
                iteration="after_opt",
            )
            metrics_table.add_data(
                "After",
                rendering_after["mean_psnr"],
                rendering_after["mean_ssim"],
                rendering_after["mean_lpips"],
                ATE,
                FPS,
            )
            wandb.log({"Metrics": metrics_table})
            save_mapping_raw_from_official_eval(
                self.config,
                self.save_dir,
                rendering_before,
                rendering_after,
            )
            try:
                eval_static_background_raw(
                    self.frontend.cameras,
                    self.gaussians,
                    self.dataset,
                    self.save_dir,
                    self.pipeline_params,
                    self.background,
                    self.config,
                )
            except Exception as exc:  # never let the P-A metric break a run's teardown
                Log(f"P-A static-background eval failed: {exc}", tag="Eval")
            save_gaussians(self.gaussians, self.save_dir, "final_after_opt", final=True)

        save_efficiency_raw(
            self.config,
            self.save_dir,
            FPS,
            total_time_s,
            N_frames,
            gaussians=self.gaussians,
            tracking_time_s=self.frontend.tracking_time_s,
            tracking_frames=self.frontend.tracking_frames,
            online_time_s=online_time_s,
            online_peak_gpu_memory_gb=online_memory["peak_gpu_memory_gb"],
            online_num_gaussians=online_num_gaussians,
            refinement_wall_time_s=refinement_wall_time_s,
            refinement_peak_gpu_memory_gb=refinement_peak_gpu_memory_gb,
            refined_num_gaussians=int(self.gaussians.get_xyz.shape[0]),
            memory_monitor_error=online_memory["error"],
        )

        # All backend-produced snapshots have been adopted into process-local
        # storage.  Collect their released IPC mappings before asking the producer
        # to terminate, then collect frontend-produced mappings after it has exited.
        release_cuda_ipc_cache()
        _stop_process(backend_process, backend_queue, "stop")
        release_cuda_ipc_cache()
        if backend_process.exitcode not in (None, 0):
            raise RuntimeError(
                f"Backend process failed with exit code {backend_process.exitcode}"
            )
        Log("Backend stopped and joined the main thread")
        if self.use_gui:
            _stop_gui_process(gui_process, q_main2vis, finish=True)
            Log("GUI Stopped and joined the main thread")

        self._online_memory_monitor = None
        self._refinement_monitor = None

    def _cleanup_workers(self):
        """Stop child processes and memory samplers on every exit path."""
        monitor = self._refinement_monitor
        if monitor is not None:
            monitor.stop()
            self._refinement_monitor = None
        monitor = self._online_memory_monitor
        if monitor is not None:
            monitor.stop()
            self._online_memory_monitor = None
        _stop_process(
            self._backend_process,
            getattr(self, "_backend_queue", None),
            "stop",
        )
        _stop_gui_process(
            self._gui_process,
            getattr(self, "_q_main2vis", None),
            finish=False,
        )

    def __del__(self):
        try:
            self._cleanup_workers()
        except Exception:
            pass

    def run(self):
        pass


if __name__ == "__main__":
    # Set up command line argument parser
    parser = ArgumentParser(description="Training script parameters")
    parser.add_argument("--config", type=str)
    parser.add_argument("--eval", action="store_true")
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--ate-abort-threshold-cm", type=float, default=0.0)
    parser.add_argument("--ate-abort-min-frames", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--experiment-name", type=str, default="")
    parser.add_argument("--results-root", type=str, default="")
    parser.add_argument("--tables-dir", type=str, default="")

    args = parser.parse_args(sys.argv[1:])
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)

    mp.set_start_method("spawn")

    with open(args.config, "r") as yml:
        config = yaml.safe_load(yml)

    config = load_config(args.config)
    config["seed"] = args.seed
    color_refinement_iterations(config)
    if args.max_frames > 0:
        # fast iteration: cap the sequence length (partial-trajectory ATE, use for
        # quick relative signal only -- full number needs the whole sequence)
        config["Dataset"]["max_frames"] = args.max_frames
    if args.ate_abort_threshold_cm < 0:
        raise ValueError("--ate-abort-threshold-cm must be >= 0")
    if args.ate_abort_min_frames < 0:
        raise ValueError("--ate-abort-min-frames must be >= 0")
    if args.ate_abort_threshold_cm > 0:
        config["Results"]["ate_abort_threshold_cm"] = args.ate_abort_threshold_cm
        config["Results"]["ate_abort_min_frames"] = args.ate_abort_min_frames
    results_root = resolve_results_root(
        config,
        experiment_name=args.experiment_name,
        results_root=args.results_root,
    )
    apply_results_root(config, results_root, tables_dir=args.tables_dir or None)
    save_dir = None

    if args.eval:
        Log("Running MonoGS evaluation mode")
        Log("Following config will be overriden")
        Log("\tsave_results=True")
        config["Results"]["save_results"] = True
        Log("\teval_rendering=True")
        config["Results"]["eval_rendering"] = True
        Log("\tsave_raw_metrics=True")
        config["Results"]["save_raw_metrics"] = True
        Log("\tsave_final_tracking=True")
        config["Results"]["save_final_tracking"] = True
        Log("\tsave_final_gaussians=True")
        config["Results"]["save_final_gaussians"] = True

    if args.fast:
        # FAST tracking-iteration mode: full tracking ATE (save_final_tracking_raw),
        # but skip rendering eval, color refinement, and the final PLY save.
        Log("Running FAST tracking-only mode (skip rendering eval + color refinement)")
        config["Results"]["save_results"] = True
        config["Results"]["save_raw_metrics"] = True
        config["Results"]["save_final_tracking"] = True
        config["Results"]["eval_rendering"] = False
        config["Results"]["save_final_gaussians"] = False

    if config["Results"]["save_results"]:
        mkdir_p(config["Results"]["save_dir"])
        current_datetime = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        dataset_result_dir = get_dataset_result_dir(config)
        sequence_id = get_sequence_id(config, args.config)
        config["Dataset"]["sequence"] = sequence_id
        save_dir = os.path.join(
            config["Results"]["save_dir"],
            dataset_result_dir,
            sequence_id,
            f"seed_{args.seed}",
            current_datetime,
        )
        tmp = args.config
        tmp = tmp.split(".")[0]
        config["Results"]["save_dir"] = save_dir
        mkdir_p(save_dir)
        log_path = start_console_log(save_dir)
        with open(os.path.join(save_dir, "config.yml"), "w") as file:
            documents = yaml.dump(config, file)
        Log("saving results in " + save_dir)
        if log_path:
            Log("logging console output to " + log_path)
        run = wandb.init(
            project="MonoGS",
            name=f"{tmp}_{current_datetime}",
            config=config,
            mode=None if config["Results"]["use_wandb"] else "disabled",
        )
        wandb.define_metric("frame_idx")
        wandb.define_metric("ate*", step_metric="frame_idx")

    slam = None
    try:
        slam = SLAM(config, save_dir=save_dir)
        slam.run()
        wandb.finish()
    finally:
        active = getattr(SLAM, "_active_instance", None)
        if active is not None:
            active._cleanup_workers()

    # All done
    Log("Done.")
