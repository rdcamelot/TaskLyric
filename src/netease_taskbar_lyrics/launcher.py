from __future__ import annotations

import argparse
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

from .cloudmusic import CloudMusicWindowProbe

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REMOTE_DEBUG_PORT = 9222
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
SHORTCUT_REPAIR_INTERVAL_SECONDS = 300.0
REMOTE_DEBUG_STARTUP_GRACE_SECONDS = 30.0
TASKLYRIC_RESTART_MIN_SECONDS = 3.0
TASKLYRIC_RESTART_MAX_SECONDS = 60.0
TASKLYRIC_STABLE_RUN_SECONDS = 120.0
TASKLYRIC_LOG_MAX_BYTES = 5 * 1024 * 1024
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ERROR_ALREADY_EXISTS = 183
LAUNCHER_MUTEX_NAME = r"Local\TaskLyric.BackgroundLauncher"
_WINDOW_PROBE = CloudMusicWindowProbe()
STATE_DIR = ROOT / "state"
LAUNCHER_STATE_PATH = STATE_DIR / "launcher-state.json"
TASKLYRIC_STOP_REQUEST_PATH = STATE_DIR / "tasklyric-stop.request"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
kernel32.CreateMutexW.restype = ctypes.c_void_p
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.c_bool


def _acquire_launcher_mutex() -> int | None:
    handle = kernel32.CreateMutexW(None, False, LAUNCHER_MUTEX_NAME)
    if not handle:
        return None
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def _stop_tasklyric_python_processes(*, include_launcher: bool = True) -> bool:
    stopped = _stop_tasklyric_state_processes(include_launcher=include_launcher)
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
    current_pid = os.getpid()
    for pid in pids:
        if pid > 0 and pid != current_pid:
            stopped = _stop_pid(pid) or stopped
    return stopped


def _stop_tasklyric_state_processes(*, include_launcher: bool) -> bool:
    try:
        payload = json.loads(LAUNCHER_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False

    candidate_pids = [payload.get("taskLyricPid")]
    if include_launcher:
        candidate_pids.append(payload.get("launcherPid"))

    stopped = False
    current_pid = os.getpid()
    for value in candidate_pids:
        if not isinstance(value, (int, float)):
            continue
        pid = int(value)
        if pid <= 0 or pid == current_pid:
            continue
        stopped = _stop_pid(pid) or stopped
    return stopped


def _stop_pid(pid: int) -> bool:
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue"],
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
    payload = _powershell_json(
        r"""
$ids = @()
foreach ($process in Get-Process -ErrorAction SilentlyContinue) {
    $name = [string]$process.ProcessName
    if ($name -ieq 'cloudmusic') {
        $ids += [int]$process.Id
        continue
    }

    $path = ''
    try {
        $path = [string]$process.Path
    } catch {
        $path = ''
    }

    if ($path -match '(?i)\\CloudMusic\\' -and $name -notmatch '(?i)reporter|minidump|crash') {
        $ids += [int]$process.Id
    }
}
$ids | Sort-Object -Unique | ConvertTo-Json -Compress
"""
    )
    if payload is None:
        return []
    if isinstance(payload, int):
        return [payload]
    if isinstance(payload, list):
        return [int(value) for value in payload if isinstance(value, (int, float))]
    return []


def cloudmusic_reporter_process_ids() -> list[int]:
    payload = _powershell_json("Get-Process -Name cloudmusic_reporter -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id | ConvertTo-Json -Compress")
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


def cloudmusic_has_remote_debug_port(port: int) -> bool:
    expected = f"--remote-debugging-port={int(port)}"
    payload = _powershell_json(
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -ieq 'cloudmusic.exe' } | Select-Object -ExpandProperty CommandLine | ConvertTo-Json -Compress"
    )
    if isinstance(payload, str):
        command_lines = [payload]
    elif isinstance(payload, list):
        command_lines = [str(value) for value in payload if value]
    else:
        return False
    return any(expected in command_line for command_line in command_lines)

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


def repair_pinned_cloudmusic_shortcuts(port: int) -> dict[str, object] | None:
    port = int(port)
    # NetEase updates can recreate the pinned taskbar shortcut and drop our
    # remote-debug argument. Repairing the link is safe; restarting the current
    # player remains opt-in because it interrupts user playback.
    command = r"""
$ErrorActionPreference = 'SilentlyContinue'
$port = __PORT__
$pinned = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
$result = [ordered]@{
    checked = 0
    repaired = 0
    found = 0
    paths = @()
}

function Get-CloudMusicExecutable {
    $processPath = Get-CimInstance Win32_Process -Filter "name='cloudmusic.exe'" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty ExecutablePath
    if ($processPath -and (Test-Path $processPath)) {
        return $processPath
    }

    $candidates = @(
        'D:\CloudMusic\CloudMusic\cloudmusic.exe',
        (Join-Path $env:ProgramFiles 'NetEase\CloudMusic\cloudmusic.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\NetEase\CloudMusic\cloudmusic.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }
    return $null
}

if (Test-Path $pinned) {
    $wsh = New-Object -ComObject WScript.Shell
    $cloudMusicExe = Get-CloudMusicExecutable
    $expected = "--remote-debugging-port=$port"

    foreach ($shortcutFile in Get-ChildItem -LiteralPath $pinned -Filter '*.lnk' -ErrorAction SilentlyContinue) {
        try {
            $shortcut = $wsh.CreateShortcut($shortcutFile.FullName)
            $targetPath = [string]$shortcut.TargetPath
            $argsText = [string]$shortcut.Arguments
            $name = [string]$shortcutFile.Name
        } catch {
            continue
        }

        $targetLooksCloudMusic = $targetPath -match '(?i)cloudmusic\.exe$' -or $targetPath -match '(?i)\\NetEase\\CloudMusic\\'
        $nameLooksCloudMusic = $name -match '(?i)CloudMusic|NetEase'
        if (-not ($targetLooksCloudMusic -or $nameLooksCloudMusic)) {
            continue
        }

        $result['found'] = [int]$result['found'] + 1
        if ((-not $targetPath -or -not (Test-Path $targetPath)) -and $cloudMusicExe) {
            $targetPath = $cloudMusicExe
        }
        if (-not $targetPath -or -not (Test-Path $targetPath)) {
            continue
        }

        $result['checked'] = [int]$result['checked'] + 1
        if ($argsText -match [regex]::Escape($expected)) {
            continue
        }

        $backupPath = "$($shortcutFile.FullName).tasklyric-backup"
        if (-not (Test-Path $backupPath)) {
            Copy-Item -LiteralPath $shortcutFile.FullName -Destination $backupPath -Force
        }

        $shortcut.TargetPath = $targetPath
        $shortcut.Arguments = $expected
        $shortcut.WorkingDirectory = Split-Path -Parent $targetPath
        $shortcut.IconLocation = "$targetPath,0"
        $shortcut.Description = 'Launch NetEase Cloud Music with the remote debug port required by TaskLyric.'
        $shortcut.Save()

        $result['repaired'] = [int]$result['repaired'] + 1
        $result['paths'] = @($result['paths']) + $shortcutFile.FullName
    }
}

$result | ConvertTo-Json -Compress
""".replace("__PORT__", str(port))
    payload = _powershell_json(command)
    if isinstance(payload, dict):
        return payload
    return None


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
        self._tasklyric_started_at = 0.0
        self._next_tasklyric_start_at = 0.0
        self._tasklyric_restart_delay = TASKLYRIC_RESTART_MIN_SECONDS
        self._launched_cloudmusic = False
        self._last_restart_attempt = 0.0
        self._startup_grace_until = 0.0
        self._remote_debug_process_signature: tuple[int, ...] = ()
        self._remote_missing_since = 0.0
        self._last_shortcut_repair_check = 0.0

    def run(self) -> None:
        self._write_state({"event": "launcher-started"})
        try:
            while True:
                self._tick()
                time.sleep(self.poll_interval_seconds)
        except KeyboardInterrupt:
            pass
        finally:
            self._write_state({"event": "launcher-stopping"})
            self._stop_tasklyric()

    def _tick(self) -> None:
        cloudmusic_pids = cloudmusic_process_ids()
        reporter_pids = cloudmusic_reporter_process_ids()
        process_running = bool(cloudmusic_pids)
        remote_debug_process = cloudmusic_has_remote_debug_port(self.remote_debug_port) if process_running else False
        remote_ready = remote_debug_available(self.remote_debug_port)
        window_ready = has_cloudmusic_window()
        now = time.monotonic()
        self._repair_cloudmusic_shortcuts_if_due(now)

        self._observe_remote_debug_process(
            process_ids=cloudmusic_pids,
            remote_debug_process=remote_debug_process,
            remote_ready=remote_ready,
            now=now,
        )

        # NetEase updates may change process visibility during early startup.
        # If the remote-debug endpoint is reachable, it is the strongest signal
        # and should keep TaskLyric running even if process-name probing fails.
        running = self._cloudmusic_is_usable(
            process_running=process_running,
            remote_ready=remote_ready,
            window_ready=window_ready,
            startup_grace_until=self._startup_grace_until,
            now=now,
        )

        if self.launch_cloudmusic and not process_running and not self._launched_cloudmusic:
            if launch_cloudmusic_with_debug(self.remote_debug_port):
                self._launched_cloudmusic = True
                self._startup_grace_until = time.monotonic() + 12.0
                process_running = True
                remote_debug_process = True
                running = True

        if remote_ready or not process_running or not window_ready or remote_debug_process:
            self._remote_missing_since = 0.0
        elif self._remote_missing_since <= 0:
            self._remote_missing_since = now

        if process_running and self.restart_with_debug and window_ready and not remote_ready and not remote_debug_process:
            missing_for = now - self._remote_missing_since if self._remote_missing_since > 0 else 0.0
            if missing_for >= 45.0 and now - self._last_restart_attempt >= 90.0:
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

        self._write_state(
            {
                "event": "tick",
                "cloudMusicProcessIds": cloudmusic_pids,
                "cloudMusicReporterProcessIds": reporter_pids,
                "cloudMusicRunning": process_running,
                "cloudMusicReporterOnly": bool(reporter_pids and not cloudmusic_pids),
                "remoteDebugProcess": remote_debug_process,
                "remoteDebugAvailable": remote_ready,
                "windowReady": window_ready,
                "cloudMusicUsable": running,
                "taskLyricRunning": self._tasklyric_process is not None and self._tasklyric_process.poll() is None,
                "taskLyricPid": self._tasklyric_process.pid if self._tasklyric_process is not None and self._tasklyric_process.poll() is None else 0,
                "launchCloudMusic": self.launch_cloudmusic,
                "restartWithDebug": self.restart_with_debug,
                "remoteMissingSeconds": max(0.0, now - self._remote_missing_since) if self._remote_missing_since > 0 else 0.0,
            }
        )

    @staticmethod
    def _cloudmusic_is_usable(
        *,
        process_running: bool,
        remote_ready: bool,
        window_ready: bool,
        startup_grace_until: float,
        now: float,
    ) -> bool:
        return remote_ready or (process_running and (window_ready or now < startup_grace_until))

    def _observe_remote_debug_process(
        self,
        *,
        process_ids: list[int],
        remote_debug_process: bool,
        remote_ready: bool,
        now: float,
    ) -> None:
        if not process_ids:
            self._remote_debug_process_signature = ()
            return
        if not remote_debug_process:
            return

        # A crashed Cloud Music instance can leave cloudmusic.exe alive with the
        # remote-debug argument but no window or reachable endpoint. Consume the
        # startup grace once per PID set. Do not reset it when command-line
        # probing has a transient failure, otherwise a zombie keeps TaskLyric
        # alive forever.
        signature = tuple(sorted(process_ids))
        if signature == self._remote_debug_process_signature:
            return
        self._remote_debug_process_signature = signature
        if not remote_ready:
            self._startup_grace_until = max(
                self._startup_grace_until,
                now + REMOTE_DEBUG_STARTUP_GRACE_SECONDS,
            )

    def _repair_cloudmusic_shortcuts_if_due(self, now: float) -> None:
        if self._last_shortcut_repair_check > 0 and now - self._last_shortcut_repair_check < SHORTCUT_REPAIR_INTERVAL_SECONDS:
            return
        self._last_shortcut_repair_check = now
        repair_pinned_cloudmusic_shortcuts(self.remote_debug_port)

    def _ensure_tasklyric_running(self) -> None:
        process = self._tasklyric_process
        now = time.monotonic()
        if process is not None:
            exit_code = process.poll()
            if exit_code is None:
                return

            runtime = max(0.0, now - self._tasklyric_started_at)
            self._tasklyric_process = None
            self._append_launcher_log(
                f"TaskLyric child exited: pid={process.pid} code={exit_code} runtimeSeconds={runtime:.1f}"
            )
            if runtime >= TASKLYRIC_STABLE_RUN_SECONDS:
                self._tasklyric_restart_delay = TASKLYRIC_RESTART_MIN_SECONDS
            self._next_tasklyric_start_at = now + self._tasklyric_restart_delay
            self._tasklyric_restart_delay = min(
                TASKLYRIC_RESTART_MAX_SECONDS,
                self._tasklyric_restart_delay * 2.0,
            )

        if now < self._next_tasklyric_start_at:
            return

        python_executable = _pythonw_executable()
        log_path = ROOT / "logs" / "tasklyric-launcher.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_log_if_needed(log_path)
        try:
            TASKLYRIC_STOP_REQUEST_PATH.unlink(missing_ok=True)
            child_environment = os.environ.copy()
            child_environment["PYTHONFAULTHANDLER"] = "1"
            with open(log_path, "ab") as log_stream:
                process = subprocess.Popen(
                    [
                        python_executable,
                        str(ROOT / "main.py"),
                        "--remote-debug-port",
                        str(self.remote_debug_port),
                        "--stop-file",
                        str(TASKLYRIC_STOP_REQUEST_PATH),
                    ],
                    cwd=str(ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=log_stream,
                    stderr=log_stream,
                    env=child_environment,
                    creationflags=CREATE_NO_WINDOW,
                )
        except OSError as exc:
            self._append_launcher_log(f"TaskLyric child launch failed: {exc}")
            self._next_tasklyric_start_at = now + self._tasklyric_restart_delay
            self._tasklyric_restart_delay = min(
                TASKLYRIC_RESTART_MAX_SECONDS,
                self._tasklyric_restart_delay * 2.0,
            )
            return

        self._tasklyric_process = process
        self._tasklyric_started_at = now
        self._next_tasklyric_start_at = 0.0
        self._append_launcher_log(f"TaskLyric child started: pid={process.pid}")

    def _stop_tasklyric(self) -> None:
        process = self._tasklyric_process
        if process is None:
            return
        if process.poll() is None:
            try:
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                TASKLYRIC_STOP_REQUEST_PATH.write_text(
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    encoding="utf-8",
                )
            except OSError:
                pass
            try:
                process.wait(timeout=6.0)
            except subprocess.TimeoutExpired:
                self._append_launcher_log(
                    f"TaskLyric child did not stop gracefully: pid={process.pid}; terminating"
                )
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
        try:
            TASKLYRIC_STOP_REQUEST_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        self._tasklyric_process = None

    @staticmethod
    def _rotate_log_if_needed(log_path: Path) -> None:
        try:
            if log_path.stat().st_size < TASKLYRIC_LOG_MAX_BYTES:
                return
            backup_path = log_path.with_suffix(log_path.suffix + ".1")
            backup_path.unlink(missing_ok=True)
            log_path.replace(backup_path)
        except OSError:
            return

    @staticmethod
    def _append_launcher_log(message: str) -> None:
        log_path = ROOT / "logs" / "tasklyric-launcher.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            TaskLyricBackgroundLauncher._rotate_log_if_needed(log_path)
            with open(log_path, "a", encoding="utf-8") as stream:
                stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        except OSError:
            return

    def _write_state(self, payload: dict[str, object]) -> None:
        data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "remoteDebugPort": self.remote_debug_port,
            "launcherPid": os.getpid(),
        }
        data.update(payload)
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            LAUNCHER_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return


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

    mutex_handle = _acquire_launcher_mutex()
    if mutex_handle is None:
        return

    launcher = TaskLyricBackgroundLauncher(
        remote_debug_port=args.remote_debug_port,
        poll_interval_seconds=args.poll_interval,
        launch_cloudmusic=args.launch_cloudmusic,
        restart_with_debug=args.restart_cloudmusic_with_debug,
    )
    try:
        launcher.run()
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(mutex_handle))
