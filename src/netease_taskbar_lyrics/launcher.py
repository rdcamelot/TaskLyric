from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REMOTE_DEBUG_PORT = 9222
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
        running = is_cloudmusic_running()

        if self.launch_cloudmusic and not running and not self._launched_cloudmusic:
            if launch_cloudmusic_with_debug(self.remote_debug_port):
                self._launched_cloudmusic = True
                running = True

        if running and self.restart_with_debug and not remote_debug_available(self.remote_debug_port):
            now = time.monotonic()
            if now - self._last_restart_attempt >= 8.0:
                self._last_restart_attempt = now
                stop_cloudmusic()
                time.sleep(0.8)
                if launch_cloudmusic_with_debug(self.remote_debug_port):
                    self._launched_cloudmusic = True
                running = True

        if running:
            self._ensure_tasklyric_running()
        else:
            self._launched_cloudmusic = False
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
    args = parser.parse_args(list(argv) if argv is not None else None)

    launcher = TaskLyricBackgroundLauncher(
        remote_debug_port=args.remote_debug_port,
        poll_interval_seconds=args.poll_interval,
        launch_cloudmusic=args.launch_cloudmusic,
        restart_with_debug=args.restart_cloudmusic_with_debug,
    )
    launcher.run()
