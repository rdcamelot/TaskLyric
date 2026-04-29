from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request

from .cloudmusic import CloudMusicWindowProbe

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REMOTE_DEBUG_PORT = 9222
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_WINDOW_PROBE = CloudMusicWindowProbe()


def _stop_tasklyric_python_processes(*, include_launcher: bool = True) -> bool:
    predicates = ["$_.CommandLine -like '*TaskLyric__efb8867*main.py*'", "$_.CommandLine -like '*TaskLyric*main.py*'"]
    if include_launcher:
        predicates.extend(["$_.CommandLine -like '*TaskLyric__efb8867*launcher.pyw*'", "$_.CommandLine -like '*TaskLyric*launcher.pyw*'"])
    predicate = ' -or '.join(predicates)
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { ($_.Name -ieq 'pythonw.exe' -or $_.Name -ieq 'python.exe') -and $_.CommandLine -and ("
        f"{predicate}) }} | "
        "Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress"
    )
    payload = _powershell_json(command)
    pids: list[int] = []
    if isinstance(payload, int):
        pids = [payload]
    elif isinstance(payload, list):
        pids = [int(value) for value in payload if isinstance(value, (int, float))]
    stopped = False
    current_pid = os.getpid()
    for pid in pids:
        if pid > 0 and pid != current_pid:
            try:
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    creationflags=CREATE_NO_WINDOW,
                )
                stopped = True
            except (OSError, subprocess.SubprocessError):
                continue
    return stopped


def _powershell_json(command: str):
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    output = (completed.stdout or "").strip()
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def cloudmusic_process_ids() -> list[int]:
    payload = _powershell_json("Get-Process -Name cloudmusic -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id | ConvertTo-Json -Compress")
    if payload is None:
        return []
    if isinstance(payload, int):
        return [payload]
    if isinstance(payload, list):
        return [int(value) for value in payload if isinstance(value, (int, float))]
    return []


def is_cloudmusic_running() -> bool:
    return bool(cloudmusic_process_ids())


def has_cloudmusic_window() -> bool:
    try:
        return _WINDOW_PROBE.has_player_window()
    except Exception:
        return False


def find_cloudmusic_executable() -> Path | None:
    payload = _powershell_json("Get-CimInstance Win32_Process -Filter \"name='cloudmusic.exe'\" | Select-Object -First 1 -ExpandProperty ExecutablePath | ConvertTo-Json -Compress")
    if isinstance(payload, str) and payload.strip():
        path = Path(payload.strip())
        if path.exists():
            return path

    candidates = [
        Path(r"D:\CloudMusic\CloudMusic\cloudmusic.exe"),
        Path.home().parent / "Program Files" / "NetEase" / "CloudMusic" / "cloudmusic.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "NetEase" / "CloudMusic" / "cloudmusic.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def remote_debug_available(port: int) -> bool:
    url = f"http://127.0.0.1:{int(port)}/json/list"
    try:
        with urllib_request.urlopen(url, timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib_error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    return isinstance(payload, list) and len(payload) > 0


def launch_cloudmusic_with_debug(port: int) -> bool:
    executable = find_cloudmusic_executable()
    if executable is None:
        return False
    try:
        subprocess.Popen(
            [str(executable), f"--remote-debugging-port={int(port)}"],
            cwd=str(executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError:
        return False
    return True


def stop_cloudmusic() -> None:
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "Get-Process -Name cloudmusic -ErrorAction SilentlyContinue | Stop-Process -Force"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return


def _pythonw_executable() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "python.exe":
        candidate = executable.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return str(executable)


class TaskLyricBackgroundLauncher:
    def __init__(
        self,
        *,
        remote_debug_port: int = DEFAULT_REMOTE_DEBUG_PORT,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        launch_cloudmusic: bool = False,
        restart_with_debug: bool = False,
    ) -> None:
        self.remote_debug_port = int(remote_debug_port)
        self.poll_interval_seconds = max(0.5, float(poll_interval_seconds))
        self.launch_cloudmusic = bool(launch_cloudmusic)
        self.restart_with_debug = bool(restart_with_debug)
        self._tasklyric_process: subprocess.Popen[str] | None = None
        self._launched_cloudmusic = False
        self._last_restart_attempt = 0.0
        self._startup_grace_until = 0.0
        self._remote_missing_since = 0.0

    def run(self) -> None:
        try:
            while True:
                self._tick()
                time.sleep(self.poll_interval_seconds)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop_tasklyric()

    def _tick(self) -> None:
        process_running = is_cloudmusic_running()
        remote_ready = remote_debug_available(self.remote_debug_port)
        window_ready = has_cloudmusic_window()
        now = time.monotonic()
        running = process_running and (remote_ready or window_ready or now < self._startup_grace_until)

        if self.launch_cloudmusic and not process_running and not self._launched_cloudmusic:
            if launch_cloudmusic_with_debug(self.remote_debug_port):
                self._launched_cloudmusic = True
                self._startup_grace_until = time.monotonic() + 12.0
                process_running = True
                running = True

        if remote_ready or not process_running or not window_ready:
            self._remote_missing_since = 0.0
        elif self._remote_missing_since <= 0:
            self._remote_missing_since = now

        if process_running and self.restart_with_debug and window_ready and not remote_ready:
            missing_for = now - self._remote_missing_since if self._remote_missing_since > 0 else 0.0
            if missing_for >= 15.0 and now - self._last_restart_attempt >= 20.0:
                self._last_restart_attempt = now
                stop_cloudmusic()
                time.sleep(0.8)
                if launch_cloudmusic_with_debug(self.remote_debug_port):
                    self._launched_cloudmusic = True
                    self._startup_grace_until = time.monotonic() + 15.0
                    self._remote_missing_since = 0.0
                running = True

        if running:
            self._ensure_tasklyric_running()
        else:
            self._launched_cloudmusic = False
            self._startup_grace_until = 0.0
            self._remote_missing_since = 0.0
            self._stop_tasklyric()

    def _ensure_tasklyric_running(self) -> None:
        process = self._tasklyric_process
        if process is not None and process.poll() is None:
            return

        python_executable = _pythonw_executable()
        log_path = ROOT / "logs" / "tasklyric-launcher.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_stream = open(log_path, "ab")
        self._tasklyric_process = subprocess.Popen(
            [python_executable, str(ROOT / "main.py"), "--remote-debug-port", str(self.remote_debug_port)],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=log_stream,
            creationflags=CREATE_NO_WINDOW,
        )

    def _stop_tasklyric(self) -> None:
        process = self._tasklyric_process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=4.0)
            except subprocess.TimeoutExpired:
                process.kill()
        self._tasklyric_process = None


def run(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run TaskLyric without opening a terminal window.")
    parser.add_argument("--remote-debug-port", type=int, default=DEFAULT_REMOTE_DEBUG_PORT)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--launch-cloudmusic", action="store_true", help="Launch NetEase Cloud Music with the remote debug port before starting TaskLyric.")
    parser.add_argument("--restart-cloudmusic-with-debug", action="store_true", help="If Cloud Music is already running without a remote debug port, restart it with the debug port so exact sync and taskbar controls work.")
    parser.add_argument("--stop", action="store_true", help="Stop the running TaskLyric background processes.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.stop:
        _stop_tasklyric_python_processes(include_launcher=True)
        return

    launcher = TaskLyricBackgroundLauncher(
        remote_debug_port=args.remote_debug_port,
        poll_interval_seconds=args.poll_interval,
        launch_cloudmusic=args.launch_cloudmusic,
        restart_with_debug=args.restart_cloudmusic_with_debug,
    )
    launcher.run()
