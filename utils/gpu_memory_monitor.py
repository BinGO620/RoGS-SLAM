import os
import subprocess
import threading


def _descendant_pids(root_pid):
    descendants = {int(root_pid)}
    changed = True
    while changed:
        changed = False
        try:
            entries = os.listdir("/proc")
        except OSError:
            break
        for entry in entries:
            if not entry.isdigit() or int(entry) in descendants:
                continue
            try:
                with open(f"/proc/{entry}/stat", "r", encoding="utf-8") as file:
                    stat = file.read()
                closing = stat.rfind(")")
                parent = int(stat[closing + 2 :].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            if parent in descendants:
                descendants.add(int(entry))
                changed = True
    return descendants


def parse_compute_apps_memory(output, included_pids):
    total = 0.0
    for line in output.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 2:
            continue
        try:
            pid = int(fields[0])
            memory_mb = float(fields[1])
        except ValueError:
            continue
        if pid in included_pids:
            total += memory_mb
    return total


def query_process_tree_gpu_memory_mb(root_pid):
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,used_memory",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        stderr=subprocess.STDOUT,
        timeout=5,
    )
    descendants = _descendant_pids(root_pid)
    return parse_compute_apps_memory(output, descendants)


class ProcessTreeGpuMemoryMonitor:
    def __init__(self, root_pid=None, interval_s=0.1):
        self.root_pid = int(root_pid or os.getpid())
        self.interval_s = float(interval_s)
        self.peak_mb = 0.0
        self.samples = 0
        self.error = None
        self._stop_event = threading.Event()
        self._thread = None

    def _poll(self):
        while not self._stop_event.is_set():
            try:
                self.peak_mb = max(
                    self.peak_mb,
                    query_process_tree_gpu_memory_mb(self.root_pid),
                )
                self.samples += 1
            except Exception as exc:
                self.error = str(exc)
            self._stop_event.wait(self.interval_s)

    def start(self):
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_s * 3))
        return {
            "peak_gpu_memory_gb": round(self.peak_mb / 1024.0, 4)
            if self.samples
            else "MISSING",
            "samples": self.samples,
            "error": self.error or "",
        }
