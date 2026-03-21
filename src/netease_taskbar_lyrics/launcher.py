from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
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
ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\TaskLyricLauncherSingleton"
LAUNCHER_STATE_PATH = ROOT / "state" / "launcher-state.json"
DEBUG_READY_GRACE_SECONDS = 18.0
DEBUG_TARGET_STABLE_SECONDS = 10.0
RESTART_COOLDOWN_SECONDS = 30.0
CLOUDMUSIC_STOP_TIMEOUT_SECONDS = 10.0


def _append_log(message: str) -> None:
    try:
        log_path = ROOT / "logs" / "tasklyric-launcher.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        return


def _write_launcher_state(payload: dict[str, object]) -> None:
    try:
        LAUNCHER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAUNCHER_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _read_launcher_state() -> dict[str, object] | None:
    try:
        data = json.loads(LAUNCHER_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _remove_launcher_state() -> None:
    try:
        LAUNCHER_STATE_PATH.unlink(missing_ok=True)
    except OSError:
        return


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id | ConvertTo-Json -Compress"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return str(pid) in (completed.stdout or "")


def _stop_pid(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _stop_tasklyric_python_processes(*, include_launcher: bool) -> bool:
    predicates = ["$_.CommandLine -like '*TaskLyric*main.py*'"]
    if include_launcher:
        predicates.append("$_.CommandLine -like '*TaskLyric*launcher.pyw*'")
    predicate = " -or ".join(predicates)
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
        if pid > 0 and pid != current_pid and _pid_exists(pid):
            _stop_pid(pid)
            stopped = True
    return stopped


def stop_existing_launcher(*, include_launcher: bool = True) -> bool:
    state = _read_launcher_state() or {}
    child_pid = int(state.get("tasklyricPid") or 0)
    launcher_pid = int(state.get("launcherPid") or 0)
    stopped = False
    if child_pid and _pid_exists(child_pid):
        _append_log(f"external stop requested for tasklyric pid={child_pid}")
        _stop_pid(child_pid)
        stopped = True
    if include_launcher and launcher_pid and _pid_exists(launcher_pid):
        _append_log(f"external stop requested for launcher pid={launcher_pid}")
        _stop_pid(launcher_pid)
        stopped = True
    if _stop_tasklyric_python_processes(include_launcher=include_launcher):
        if include_launcher:
            _append_log("external stop requested for residual TaskLyric python processes")
        else:
            _append_log("external stop requested for residual TaskLyric main.py processes")
        stopped = True
    if include_launcher:
        _remove_launcher_state()
    return stopped


def _acquire_single_instance_mutex() -> tuple[int | None, bool]:
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None, True
    already_running = ctypes.GetLastError() == ERROR_ALREADY_EXISTS
    return int(handle), already_running


def _release_single_instance_mutex(handle: int | None) -> None:
    if not handle:
        return
    ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


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


def remote_debug_target_id(port: int) -> str:
    url = f"http://127.0.0.1:{int(port)}/json/list"
    try:
        with urllib_request.urlopen(url, timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib_error.URLError, TimeoutError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, list):
        return ""
    best_score = -1
    best_target = ""
    for item in payload:
        if not isinstance(item, dict):
            continue
        ws_url = str(item.get("webSocketDebuggerUrl") or "").strip()
        page_url = str(item.get("url") or "")
        title = str(item.get("title") or "")
        if not ws_url:
            continue
        text_blob = f"{title} {page_url}".lower()
        score = 0
        if item.get("type") == "page":
            score += 10
        if "orpheus" in text_blob:
            score += 20
        if "cloudmusic" in text_blob or "app.html" in text_blob or "subapp.html" in text_blob:
            score += 10
        if score > best_score:
            best_score = score
            best_target = ws_url
    return best_target


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


def find_tasklyric_launcher_executable() -> Path | None:
    candidates = [
        ROOT / "build-tasklyric" / "launcher" / "tasklyric_launcher.exe",
        ROOT / "build" / "launcher" / "tasklyric_launcher.exe",
        ROOT / "dist" / "tasklyric_launcher.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def start_tasklyric_launcher_process(arguments: list[str]) -> bool:
    launcher_executable = find_tasklyric_launcher_executable()
    command: list[str]
    if launcher_executable is not None:
        command = [str(launcher_executable), *arguments]
    else:
        launcher_script = ROOT / "launcher.pyw"
        if not launcher_script.exists():
            return False
        command = [_pythonw_executable(), str(launcher_script), *arguments]

    try:
        subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError:
        return False
    return True


def stop_cloudmusic(timeout_seconds: float = CLOUDMUSIC_STOP_TIMEOUT_SECONDS) -> bool:
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
        return False

    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        if not is_cloudmusic_running():
            return True
        time.sleep(0.3)
    return not is_cloudmusic_running()


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
        self._mutex_handle: int | None = None
        self._last_remote_target_id = ""
        self._waiting_for_debug_ready = False
        self._debug_wait_started_at = 0.0
        self._debug_target_stable_since = 0.0
        self._last_seen_remote_target_id = ""
        self._warned_missing_debug_ready = False
        self._should_exit = False
        self._handoff_arguments: list[str] | None = None

    def _schedule_launcher_handoff(self, *, launch_cloudmusic: bool, restart_with_debug: bool, reason: str) -> None:
        if self._handoff_arguments is not None:
            return
        arguments = ["--remote-debug-port", str(self.remote_debug_port)]
        if launch_cloudmusic:
            arguments.append("--launch-cloudmusic")
        if restart_with_debug:
            arguments.append("--restart-cloudmusic-with-debug")
        arguments.append("--replace-existing")
        self._handoff_arguments = arguments
        self._should_exit = True
        _append_log(f"scheduling launcher handoff: {reason}")


    def run(self) -> None:
        self._mutex_handle, already_running = _acquire_single_instance_mutex()
        if already_running:
            _append_log("launcher start ignored because another launcher instance is already running")
            return

        atexit.register(_remove_launcher_state)
        try:
            while True:
                self._tick()
                if self._should_exit:
                    break
                time.sleep(self.poll_interval_seconds)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop_tasklyric()
            _remove_launcher_state()
            _release_single_instance_mutex(self._mutex_handle)
            self._mutex_handle = None
            if self._handoff_arguments is not None:
                if start_tasklyric_launcher_process(self._handoff_arguments):
                    _append_log("launcher handoff started a fresh launcher process")
                else:
                    _append_log("launcher handoff failed to start a fresh launcher process")

    def _tick(self) -> None:
        now = time.monotonic()
        running = is_cloudmusic_running()
        target_id = remote_debug_target_id(self.remote_debug_port) if self.remote_debug_port > 0 else ""
        debug_target_seen = bool(target_id)
        if debug_target_seen:
            if target_id != self._last_seen_remote_target_id:
                self._last_seen_remote_target_id = target_id
                self._debug_target_stable_since = now
                _append_log("remote debug target changed; waiting for stability before starting tasklyric")
        else:
            self._last_seen_remote_target_id = ""
            self._debug_target_stable_since = 0.0

        debug_target_stable = bool(debug_target_seen and self._debug_target_stable_since > 0.0 and (now - self._debug_target_stable_since) >= DEBUG_TARGET_STABLE_SECONDS)
        debug_ready = bool(debug_target_stable)

        if self.launch_cloudmusic and not running and not self._launched_cloudmusic:
            if launch_cloudmusic_with_debug(self.remote_debug_port):
                _append_log(f"launched cloudmusic with debug port {self.remote_debug_port}")
                self._launched_cloudmusic = True
                self._waiting_for_debug_ready = True
                self._debug_wait_started_at = now
                return

        if running and not debug_ready:
            if debug_target_seen and not debug_target_stable:
                if not self._warned_missing_debug_ready:
                    _append_log(
                        f"remote debug target detected on {self.remote_debug_port} but not stable yet; delaying tasklyric start"
                    )
                    self._warned_missing_debug_ready = True
                self._waiting_for_debug_ready = True
                if self._debug_wait_started_at <= 0.0:
                    self._debug_wait_started_at = now
                return

            if self.restart_with_debug:
                if not self._waiting_for_debug_ready:
                    _append_log(f"waiting for remote debug port {self.remote_debug_port} to become ready; will wait indefinitely for user to start cloudmusic")
                    self._waiting_for_debug_ready = True
                    self._debug_wait_started_at = now
                elif self._debug_wait_started_at <= 0.0:
                    self._debug_wait_started_at = now

                if now - self._debug_wait_started_at < DEBUG_READY_GRACE_SECONDS:
                    return

                if not self._warned_missing_debug_ready:
                    _append_log(
                        f"remote debug port {self.remote_debug_port} is still unavailable after grace period; starting tasklyric in fallback mode"
                    )
                    self._warned_missing_debug_ready = True

                self._last_remote_target_id = ""
                self._ensure_tasklyric_running()
                return

            if not self._warned_missing_debug_ready:
                _append_log(
                    f"cloudmusic is running but remote debug port {self.remote_debug_port} is not ready; waiting without starting tasklyric"
                )
                self._warned_missing_debug_ready = True
            self._stop_tasklyric()
            self._last_remote_target_id = ""
            self._waiting_for_debug_ready = False
            self._debug_wait_started_at = 0.0
            return

        if running and debug_ready:
            process = self._tasklyric_process
            target_changed = bool(self._last_remote_target_id) and target_id != self._last_remote_target_id
            if target_changed and process is not None and process.poll() is None:
                _append_log("remote debug target changed; restarting tasklyric for a clean reattach")
                self._stop_tasklyric()
            elif self._waiting_for_debug_ready and process is not None and process.poll() is None:
                _append_log("remote debug became ready; restarting tasklyric to avoid a half-initialized session")
                self._stop_tasklyric()
            self._waiting_for_debug_ready = False
            self._debug_wait_started_at = 0.0
            self._warned_missing_debug_ready = False
            self._last_remote_target_id = target_id
            self._ensure_tasklyric_running()
            return

        if running:
            self._warned_missing_debug_ready = False
            self._ensure_tasklyric_running()
        else:
            self._launched_cloudmusic = False
            self._waiting_for_debug_ready = False
            self._debug_wait_started_at = 0.0
            self._debug_target_stable_since = 0.0
            self._last_seen_remote_target_id = ""
            self._warned_missing_debug_ready = False
            self._last_remote_target_id = ""
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
        _write_launcher_state({
            "launcherPid": os.getpid(),
            "tasklyricPid": self._tasklyric_process.pid,
            "remoteDebugPort": self.remote_debug_port,
            "updatedAt": time.time(),
        })
        _append_log(f"started tasklyric pid={self._tasklyric_process.pid} remote_debug_port={self.remote_debug_port}")

    def _stop_tasklyric(self) -> None:
        process = self._tasklyric_process
        if process is None:
            return
        if process.poll() is None:
            _append_log(f"stopping tasklyric pid={process.pid}")
            process.terminate()
            try:
                process.wait(timeout=4.0)
            except subprocess.TimeoutExpired:
                process.kill()
        self._tasklyric_process = None
        _write_launcher_state({
            "launcherPid": os.getpid(),
            "tasklyricPid": 0,
            "remoteDebugPort": self.remote_debug_port,
            "updatedAt": time.time(),
        })


def run(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run TaskLyric without opening a terminal window.")
    parser.add_argument("--remote-debug-port", type=int, default=DEFAULT_REMOTE_DEBUG_PORT)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--launch-cloudmusic", action="store_true", help="Launch NetEase Cloud Music with the remote debug port before starting TaskLyric.")
    parser.add_argument("--restart-cloudmusic-with-debug", action=argparse.BooleanOptionalAction, default=False, help="If Cloud Music is already running without a remote debug port, restart it with the debug port so exact sync and taskbar controls work.")
    parser.add_argument("--replace-existing", action="store_true", help="Internal flag: replace existing launcher and TaskLyric background processes before starting.")
    parser.add_argument("--stop", action="store_true", help="Stop only the background TaskLyric process (main.py), keep the launcher watcher alive.")
    parser.add_argument("--stop-all", action="store_true", help="Stop both the launcher watcher and background TaskLyric process.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.stop_all:
        stop_existing_launcher(include_launcher=True)
        return

    if args.stop:
        stop_existing_launcher(include_launcher=False)
        return

    if args.launch_cloudmusic or args.restart_cloudmusic_with_debug or args.replace_existing:
        if stop_existing_launcher():
            _append_log("replacing existing launcher instance for an explicit launch request")
            time.sleep(1.0)

    launcher = TaskLyricBackgroundLauncher(
        remote_debug_port=args.remote_debug_port,
        poll_interval_seconds=args.poll_interval,
        launch_cloudmusic=args.launch_cloudmusic,
        restart_with_debug=args.restart_cloudmusic_with_debug,
    )
    launcher.run()
